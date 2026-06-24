#!/usr/bin/env python3
#   Copyright 2026 UCP Authors
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

# /// script
# dependencies = [
#   "PyGithub",
#   "PyYAML",
# ]
# ///
"""Pull Request validator using governance rules and team memberships under the Venn Diagram model."""

import argparse
from datetime import datetime
from enum import Enum
import sys

from github import Auth, Github, GithubException

from governance_config_parser import (
    GovernanceConfig,
    GovernanceConfigParser,
    RuleRequirement,
)
from pr_models import (
    FileValidationStatus,
    MergeableReason,
    PullRequest,
    RequirementStatus,
    Review,
    ReviewState,
    TeamMemberships,
    ValidationErrorReason,
    ValidationResult,
)
from validation_logger import ValidationLogger


class RepoName(Enum):
    """Supported repository names mapping to governance rules."""

    UCP = "ucp"
    PYTHON_SDK = "python-sdk"


REPO_RULES_MAPPING = {
    RepoName.UCP: ".github-central/org-tools/governance/rules/ucp-rules.yml",
    RepoName.PYTHON_SDK: ".github-central/org-tools/governance/rules/python-sdk-rules.yml",
}


class PullRequestValidator:
    """Rule engine for validating Pull Requests against governance rules using the Venn Diagram model."""

    def __init__(self, config: GovernanceConfig, memberships: TeamMemberships):
        """Initialize the validator with config and memberships."""
        self.config = config
        self.memberships = memberships

    def validate(self, pr: PullRequest) -> ValidationResult:
        """Validate a Pull Request against the governance rules."""
        # 1. Draft PR Check
        if pr.is_draft:
            return ValidationResult(
                is_mergeable=False, error=ValidationErrorReason.DRAFT_PR
            )

        # 2. Extract Latest Reviews
        latest_reviews = self._get_relevant_reviews_by_user(pr.reviews)

        # 3. Proxy Voter Override Check
        if self._has_proxy_override(latest_reviews):
            return ValidationResult(
                is_mergeable=True,
                mergeable_reason=MergeableReason.PROXY_OVERRIDE,
            )

        # 4. Empty Changed Files Check
        if not pr.changed_files:
            return ValidationResult(
                is_mergeable=True,
                mergeable_reason=MergeableReason.NO_CHANGED_FILES,
            )

        # 5. Rule Matching
        applicable_requirements = self._get_applicable_requirements(pr.changed_files)

        # 6. Changes Requested Check
        authorized_reviewers = self._get_authorized_reviewers(applicable_requirements)
        authorized_and_proxy_reviewers = set(authorized_reviewers) | set(
            self.config.proxy_reviewers
        )
        if any(
            latest_reviews.get(reviewer) == ReviewState.CHANGES_REQUESTED
            for reviewer in authorized_and_proxy_reviewers
        ):
            return ValidationResult(
                is_mergeable=False,
                error=ValidationErrorReason.CHANGES_REQUESTED,
            )

        # 7. Approvals & Assignments Evaluation (Global)
        requirement_statuses = self._evaluate_requirements(
            pr, latest_reviews, applicable_requirements
        )

        # 8. File-by-File Evaluation
        file_statuses = self._evaluate_file_statuses(pr, latest_reviews)

        # 9. Determine overall mergeability
        is_mergeable = not any(
            not status.is_satisfied for status in requirement_statuses
        )

        if not is_mergeable:
            return ValidationResult(
                is_mergeable=False,
                error=ValidationErrorReason.INSUFFICIENT_APPROVALS,
                requirement_statuses=requirement_statuses,
                file_statuses=file_statuses,
            )

        return ValidationResult(
            is_mergeable=True,
            mergeable_reason=MergeableReason.RULES_SATISFIED,
            requirement_statuses=requirement_statuses,
            file_statuses=file_statuses,
        )

    def _evaluate_file_statuses(
        self,
        pr: PullRequest,
        latest_reviews: dict[str, ReviewState],
    ) -> list[FileValidationStatus]:
        """Evaluates and generates validation statuses for each changed file in the PR."""
        requested_users_set = set(pr.assigned_users)
        for team in pr.assigned_teams:
            requested_users_set.update(
                self.memberships.members_by_team.get(team, set())
            )

        valid_approvals_set = {
            user
            for user, state in latest_reviews.items()
            if state == ReviewState.APPROVED
            and (user != pr.author or pr.author in self.config.proxy_reviewers)
        }

        file_statuses = []
        for file in pr.changed_files:
            # Find rules matching this specific file
            file_rules = []
            for rule in self.config.rules:
                if rule.matches(file):
                    file_rules.append(rule)

            file_requirements = []
            if file_rules:
                unique_file_rules = list({r.name: r for r in file_rules}.values())
                for r in unique_file_rules:
                    file_requirements.extend(r.requires_all)
            else:
                file_requirements.extend(self.config.fallback)

            # Merge file-specific requirements
            file_requirements = self._merge_requirements(file_requirements)

            file_req_statuses = []
            file_satisfied = True
            for req in file_requirements:
                # Under the Venn model, all valid approvals satisfying req are approvers
                approvers = [
                    user
                    for user in valid_approvals_set
                    if self._is_user_authorized_for_requirement(user, req)
                ]
                approved_count = len(approvers)
                # Count assigned eligible reviewers for this requirement
                assigned_count = sum(
                    1
                    for assigned_user in requested_users_set
                    if self._is_user_authorized_for_requirement(assigned_user, req)
                )

                # Check if this requirement is satisfied for this file
                req_satisfied = approved_count >= req.min_approvals
                if not req_satisfied:
                    file_satisfied = False

                file_req_statuses.append(
                    RequirementStatus(
                        requirement=req,
                        approved_count=approved_count,
                        assigned_count=assigned_count,
                        is_satisfied=req_satisfied,
                        approvers=sorted(approvers),
                    )
                )

            file_statuses.append(
                FileValidationStatus(
                    file_path=file,
                    requirement_statuses=file_req_statuses,
                    is_satisfied=file_satisfied,
                )
            )
        return file_statuses

    def _has_proxy_override(self, latest_reviews: dict[str, ReviewState]) -> bool:
        """Check if a proxy reviewer has approved the PR, bypassing rules."""
        return any(
            state == ReviewState.APPROVED and user in self.config.proxy_reviewers
            for user, state in latest_reviews.items()
        )

    def _get_applicable_requirements(
        self, changed_files: list[str]
    ) -> list[RuleRequirement]:
        """Identify all rule requirements that apply to the PR's changed files.

        If multiple rules match, their requirements are merged by keeping the
        maximum min_approvals for each unique target team/level to prevent
        redundant approval demands.
        """
        matched_rules = []
        has_fallback = False

        for file in changed_files:
            matched_any = False
            for rule in self.config.rules:
                if rule.matches(file):
                    matched_rules.append(rule)
                    matched_any = True
            if not matched_any:
                has_fallback = True

        # De-duplicate matched rules by name, preserving insertion order
        unique_rules = list({r.name: r for r in matched_rules}.values())

        requirements = []
        for r in unique_rules:
            requirements.extend(r.requires_all)
        if has_fallback:
            requirements.extend(self.config.fallback)

        return self._merge_requirements(requirements)

    def _merge_requirements(
        self, requirements: list[RuleRequirement]
    ) -> list[RuleRequirement]:
        """Merge a list of requirements by keeping the maximum min_approvals for each target."""
        merged: dict[tuple[str, str], RuleRequirement] = {}
        for req in requirements:
            if req.team is not None:
                key = ("team", req.team.name)
            elif req.min_team is not None:
                key = ("min_team", req.min_team.name)
            else:
                continue

            if key not in merged:
                merged[key] = req
            else:
                existing = merged[key]
                if req.min_approvals > existing.min_approvals:
                    merged[key] = req

        return list(merged.values())

    def _get_relevant_reviews_by_user(
        self, reviews: list[Review]
    ) -> dict[str, ReviewState]:
        """Resolve the latest review state for each user.

        Skips non-actionable states like COMMENTED.
        """
        # Sort reviews by submitted_at (if available) to ensure chronological processing
        sorted_reviews = sorted(
            reviews,
            key=lambda x: (
                x.submitted_at if x.submitted_at is not None else datetime.min
            ),
        )

        relevant_reviews: dict[str, ReviewState] = {}
        for r in sorted_reviews:
            if r.state in ReviewState.actionable_states():
                relevant_reviews[r.user] = r.state
        return relevant_reviews

    def _get_user_level(self, user: str) -> int:
        """Calculate the user's hierarchy level.

        Uses the max level of any team they belong to.
        """
        max_level = 0
        for team, members in self.memberships.members_by_team.items():
            if user in members:
                team_info = self.config.teams.get(team)
                level = team_info.level if team_info is not None else 0
                if level > max_level:
                    max_level = level
        return max_level

    def _is_user_authorized_for_requirement(
        self, user: str, req: RuleRequirement
    ) -> bool:
        """Check if a user satisfies the team or hierarchical level requirement."""
        if req.team is not None:
            team_members = self.memberships.members_by_team.get(req.team.name, set())
            return user in team_members
        elif req.min_team is not None:
            min_level = req.min_team.level
            user_level = self._get_user_level(user)
            return user_level >= min_level
        return False

    def _get_authorized_reviewers(
        self, requirements: list[RuleRequirement]
    ) -> set[str]:
        """Retrieve users who are authorized to satisfy any of the requirements.

        Gets them from team memberships.
        """
        all_users = set()
        for members in self.memberships.members_by_team.values():
            all_users.update(members)

        authorized = set()
        for user in all_users:
            for req in requirements:
                if self._is_user_authorized_for_requirement(user, req):
                    authorized.add(user)
                    break
        return authorized

    def _evaluate_requirements(
        self,
        pr: PullRequest,
        latest_reviews: dict[str, ReviewState],
        requirements: list[RuleRequirement],
    ) -> list[RequirementStatus]:
        """Evaluate each requirement's approvals and assignments count under the Venn Diagram model."""
        # Filter valid approvals (excluding author's self-approvals unless
        # they are a proxy)
        valid_approvals = {
            user
            for user, state in latest_reviews.items()
            if state == ReviewState.APPROVED
            and (user != pr.author or pr.author in self.config.proxy_reviewers)
        }

        # Resolve all unique users currently requested to review (individually
        # or via team)
        requested_users_set = set(pr.assigned_users)
        for team in pr.assigned_teams:
            requested_users_set.update(
                self.memberships.members_by_team.get(team, set())
            )

        requirement_statuses = []
        for req in requirements:
            # Under the Venn model, all valid approvals satisfying req are approvers
            approvers = [
                user
                for user in valid_approvals
                if self._is_user_authorized_for_requirement(user, req)
            ]
            approved_count = len(approvers)
            # Count assigned (requested eligible reviewers) independently
            assigned_count = sum(
                1
                for assigned_user in requested_users_set
                if self._is_user_authorized_for_requirement(assigned_user, req)
            )
            requirement_statuses.append(
                RequirementStatus(
                    requirement=req,
                    approved_count=approved_count,
                    assigned_count=assigned_count,
                    is_satisfied=approved_count >= req.min_approvals,
                    approvers=sorted(approvers),
                )
            )

        return requirement_statuses


def fetch_team_memberships(
    g: Github, org_name: str, config: GovernanceConfig
) -> TeamMemberships:
    """Fetch team membership lists from GitHub.

    Gets memberships for all teams in the hierarchy.
    """
    members_by_team = {}
    try:
        org = g.get_organization(org_name)
    except GithubException as e:
        raise RuntimeError(f"Failed to fetch organization '{org_name}': {e}") from e

    for team_slug in config.teams:
        try:
            team = org.get_team_by_slug(team_slug)
            members = {m.login for m in team.get_members()}
            members_by_team[team_slug] = members
        except GithubException as e:
            raise RuntimeError(
                f"Could not fetch members for team '{team_slug}': {e}"
            ) from e
    return TeamMemberships.create(members_by_team=members_by_team)


def fetch_pull_request(g: Github, repo_name: str, pr_number: int) -> PullRequest:
    """Fetch PR files, reviews, and requested reviewers from GitHub.

    Maps them to the PullRequest dataclass.
    """
    try:
        repo = g.get_repo(repo_name)
        pr = repo.get_pull(pr_number)

        # Fetch changed files
        changed_files = [f.filename for f in pr.get_files()]

        # Fetch reviews
        reviews = []
        for r in pr.get_reviews():
            # Map string state to ReviewState enum
            try:
                state = ReviewState(r.state.lower()) if r.state else ReviewState.UNKNOWN
            except ValueError:
                # Fall back to UNKNOWN for unsupported or unknown states
                state = ReviewState.UNKNOWN
            reviews.append(
                Review.create(
                    user=r.user.login, state=state, submitted_at=r.submitted_at
                )
            )

        # Fetch review requests (assigned users and teams)
        review_requests = pr.get_review_requests()
        assigned_users = [u.login for u in review_requests[0]]
        assigned_teams = [t.slug for t in review_requests[1]]

        return PullRequest.create(
            number=pr.number,
            author=pr.user.login,
            is_draft=pr.draft,
            changed_files=changed_files,
            reviews=reviews,
            assigned_users=assigned_users,
            assigned_teams=assigned_teams,
        )
    except GithubException as e:
        raise RuntimeError(f"Failed to fetch PR info from GitHub: {e}") from e


def main() -> None:
    """Run the governance gate check on a pull request."""
    parser = argparse.ArgumentParser(
        description=(
            "Run governance gate check on a pull request using PullRequestValidator."
        )
    )
    parser.add_argument(
        "--token", required=True, help="GitHub token for authentication."
    )
    parser.add_argument("--org", required=True, help="GitHub Organization name.")
    parser.add_argument(
        "--repo",
        required=True,
        help="GitHub Repository name (e.g. 'your-organization/your-repo').",
    )
    parser.add_argument("--pr", type=int, required=True, help="Pull Request number.")
    parser.add_argument(
        "--repo-name",
        required=True,
        help="The name of the repository (e.g. 'ucp').",
    )
    args = parser.parse_args()

    try:
        repo_enum = RepoName(args.repo_name)
    except ValueError:
        print(
            f"❌ ERROR: Invalid repository name '{args.repo_name}'. Must be one of: "
            f"{[e.value for e in RepoName]}",
            file=sys.stderr,
        )
        sys.exit(1)

    rules_file = REPO_RULES_MAPPING.get(repo_enum)
    if not rules_file:
        print(
            f"❌ ERROR: No governance rules mapped for repository '{repo_enum.value}'.",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        # 1. Load config
        config = GovernanceConfigParser().parse_file(rules_file)

        # 2. Authenticate and fetch data
        auth = Auth.Token(args.token)
        g = Github(auth=auth)

        # 3. Fetch team memberships & PR details
        memberships = fetch_team_memberships(g, args.org, config)
        pr = fetch_pull_request(g, args.repo, args.pr)

        # 4. Validate PR
        validator = PullRequestValidator(config, memberships)
        result = validator.validate(pr)

        # 5. Output result and format messages
        logger = ValidationLogger(result)
        logger.write_summary()
        if not result.is_mergeable:
            sys.exit(1)
        sys.exit(0)

    except Exception as e:
        error_msg = f"ERROR: {e}"
        print(f"❌ {error_msg}", file=sys.stderr)
        try:
            with open("summary.txt", "w", encoding="utf-8") as f:
                f.write(error_msg)
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
