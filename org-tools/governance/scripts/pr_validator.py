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
    User,
    ValidationErrorReason,
    ValidationResult,
    merge_requirements,
)
from validation_logger import ValidationLogger


class RepoName(Enum):
    """Supported repository names mapping to governance rules."""

    PYTHON_SDK = "python-sdk"


REPO_RULES_MAPPING = {
    RepoName.PYTHON_SDK: ".github-central/org-tools/governance/rules/python-sdk-rules.yml",
}


class GitHubClient:
    """Handles all interactions with the GitHub API."""

    def __init__(self, g: Github):
        self.g = g

    def fetch_team_memberships(
        self, org_name: str, config: GovernanceConfig
    ) -> TeamMemberships:
        """Fetch team membership lists from GitHub.

        Gets memberships for all teams in the hierarchy.
        """
        members_by_team = {}
        try:
            org = self.g.get_organization(org_name)
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

    def fetch_pull_request(self, repo_name: str, pr_number: int) -> PullRequest:
        """Fetch PR files, reviews, and requested reviewers from GitHub.

        Maps them to the PullRequest dataclass.
        """
        try:
            repo = self.g.get_repo(repo_name)
            pr = repo.get_pull(pr_number)

            # Fetch changed files
            changed_files = [f.filename for f in pr.get_files()]

            # Fetch reviews
            reviews = []
            for r in pr.get_reviews():
                # Map string state to ReviewState enum
                try:
                    state = (
                        ReviewState(r.state.lower()) if r.state else ReviewState.UNKNOWN
                    )
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
            assigned_user_names = [u.login for u in review_requests[0]]
            assigned_team_names = [t.slug for t in review_requests[1]]

            return PullRequest.create(
                number=pr.number,
                author=pr.user.login,
                is_draft=pr.draft,
                changed_files=changed_files,
                reviews=reviews,
                assigned_user_names=assigned_user_names,
                assigned_team_names=assigned_team_names,
            )
        except GithubException as e:
            raise RuntimeError(f"Failed to fetch PR info from GitHub: {e}") from e


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
        latest_reviews = pr.latest_actionable_reviews_by_username

        # 3. Proxy Voter Override Check
        if pr.has_proxy_override(self.config.proxy_reviewers):
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
        requirements_by_file = self.config.get_applicable_requirements(pr.changed_files)
        unmerged_requirements = []
        for reqs in requirements_by_file.values():
            unmerged_requirements.extend(reqs)
        merged_requirements = merge_requirements(unmerged_requirements)

        # 6. Resolve Reviews and Assignments once
        approver_usernames, assigned_usernames = (
            self._get_all_approvers_and_assigned_usernames(pr)
        )

        # 7. Approvals & Assignments Evaluation (Global)
        requirement_statuses = self._evaluate_requirements(
            merged_requirements, approver_usernames, assigned_usernames
        )

        # 8. File-by-File Evaluation
        file_statuses = self._evaluate_file_statuses(
            requirements_by_file, approver_usernames, assigned_usernames
        )

        # 9. Changes Requested Check
        authorized_reviewers = self._get_authorized_reviewers(merged_requirements)
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
                requirement_statuses=requirement_statuses,
                file_statuses=file_statuses,
            )

        # 10. Determine overall mergeability
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

    def _to_user(self, username: str) -> User:
        """Resolve a username into a rich User domain object."""
        user_teams = {
            team_name
            for team_name, members in self.memberships.members_by_team.items()
            if username in members
        }

        # Calculate their max hierarchy level
        max_level = 0
        for team_name in user_teams:
            team_info = self.config.teams.get(team_name)
            level = team_info.level if team_info is not None else 0
            if level > max_level:
                max_level = level

        return User(username=username, teams=user_teams, level=max_level)

    def _evaluate_requirement(
        self,
        req: RuleRequirement,
        approver_usernames: set[str],
        requested_users_set: set[str],
    ) -> RequirementStatus:
        """Calculate and return status for a requirement under the Venn Diagram model."""
        approver_users = [self._to_user(u) for u in approver_usernames]
        assigned_users = [self._to_user(u) for u in requested_users_set]

        approvers = [u.username for u in approver_users if req.is_satisfied_by(u)]
        assigned_count = sum(1 for u in assigned_users if req.is_satisfied_by(u))
        approved_count = len(approvers)
        return RequirementStatus(
            requirement=req,
            approved_count=approved_count,
            assigned_count=assigned_count,
            is_satisfied=approved_count >= req.min_approvals,
            approvers=sorted(approvers),
        )

    def _get_authorized_reviewers(
        self, requirements: list[RuleRequirement]
    ) -> set[str]:
        """Retrieve users who are authorized to satisfy any of the requirements."""
        all_users = {
            user
            for members in self.memberships.members_by_team.values()
            for user in members
        }

        authorized = set()
        for username in all_users:
            user = self._to_user(username)
            for req in requirements:
                if req.is_satisfied_by(user):
                    authorized.add(username)
                    break
        return authorized

    def _get_all_approvers_and_assigned_usernames(
        self, pr: PullRequest
    ) -> tuple[set[str], set[str]]:
        """Resolve valid approvals set and requested reviewers set for a PR."""
        assigned_usernames = set(pr.assigned_user_names)
        for team in pr.assigned_team_names:
            assigned_usernames.update(self.memberships.members_by_team.get(team, set()))

        latest_reviews = pr.latest_actionable_reviews_by_username
        approver_usernames = {
            user
            for user, state in latest_reviews.items()
            if state == ReviewState.APPROVED
            and (user != pr.author or pr.author in self.config.proxy_reviewers)
        }
        return approver_usernames, assigned_usernames

    def _evaluate_file_statuses(
        self,
        requirements_by_file: dict[str, list[RuleRequirement]],
        approver_usernames: set[str],
        assigned_usernames: set[str],
    ) -> list[FileValidationStatus]:
        """Evaluates and generates validation statuses for each changed file in the PR."""
        file_statuses = []
        for file, file_requirements in requirements_by_file.items():
            file_req_statuses = self._evaluate_requirements(
                file_requirements, approver_usernames, assigned_usernames
            )
            file_satisfied = all(status.is_satisfied for status in file_req_statuses)

            file_statuses.append(
                FileValidationStatus(
                    file_path=file,
                    requirement_statuses=file_req_statuses,
                    is_satisfied=file_satisfied,
                )
            )
        return file_statuses

    def _evaluate_requirements(
        self,
        requirements: list[RuleRequirement],
        approver_usernames: set[str],
        assigned_usernames: set[str],
    ) -> list[RequirementStatus]:
        """Evaluate each requirement's approvals and assignments count under the Venn Diagram model."""
        requirement_statuses = []
        for req in requirements:
            status = self._evaluate_requirement(
                req, approver_usernames, assigned_usernames
            )
            requirement_statuses.append(status)

        return requirement_statuses


def parse_args(args: list[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments."""
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
    return parser.parse_args(args)


def run_validation(args: argparse.Namespace) -> ValidationResult:
    """Execute the core validation flow."""
    try:
        repo_enum = RepoName(args.repo_name)
    except ValueError as e:
        raise ValueError(
            f"Invalid repository name '{args.repo_name}'. Must be one of: "
            f"{[e.value for e in RepoName]}"
        ) from e

    rules_file = REPO_RULES_MAPPING.get(repo_enum)
    if not rules_file:
        raise ValueError(
            f"No governance rules mapped for repository '{repo_enum.value}'."
        )

    # 1. Load config
    config = GovernanceConfigParser().parse_file(rules_file)

    # 2. Authenticate and fetch data
    auth = Auth.Token(args.token)
    g = Github(auth=auth)
    github_client = GitHubClient(g)

    # 3. Fetch team memberships & PR details
    memberships = github_client.fetch_team_memberships(args.org, config)
    pr = github_client.fetch_pull_request(args.repo, args.pr)

    # 4. Validate PR
    validator = PullRequestValidator(config, memberships)
    return validator.validate(pr)


def main() -> None:
    """Run the governance gate check on a pull request."""
    try:
        args = parse_args()
        result = run_validation(args)

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
