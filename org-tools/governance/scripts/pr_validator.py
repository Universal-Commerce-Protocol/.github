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
# requires-python = ">=3.11"
# dependencies = [
#   "PyGithub",
#   "PyYAML",
#   "markdown-it-py==3.0.0",
#   "markdown==3.10.2",
# ]
# ///
"""Pull Request validator using governance rules and team memberships under the Venn Diagram model."""

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path

from github import Auth, Github, GithubException
from governance_config_parser import (
    GovernanceConfig,
    GovernanceConfigParser,
    RuleRequirement,
)
from normative_detector import detect_normative_changes, is_markdown_file
from pr_models import (
    FileValidationStatus,
    MergeableReason,
    PullRequest,
    RequirementStatus,
    Review,
    ReviewState,
    Team,
    TeamMemberships,
    User,
    ValidationErrorReason,
    ValidationResult,
    merge_requirements,
)
from validation_logger import ValidationLogger

NORMATIVE_ESCALATION_LEVEL = 3
GENERIC_TECH_COUNCIL_TEAM = Team(
    name="technical-council", level=NORMATIVE_ESCALATION_LEVEL
)
DOMAIN_TECH_COUNCIL_BY_SEGMENT: dict[str, str] = {
    "shopping": "shopping-tech-council",
    "food": "food-tech-council",
    "lodging": "lodging-tech-council",
    "payment": "payments-tech-council",
    "payments": "payments-tech-council",
}


def requires_normative_check(config: GovernanceConfig, file_path: str) -> bool:
    """Return True if a changed file must be checked for normative RFC 2119 clause changes.

    Only Markdown files matched by a rule that opts in via
    `normative_escalation: true` are checked.
    """
    return is_markdown_file(file_path) and config.is_normative_escalation_file(
        file_path
    )


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
                if e.status == 404:
                    print(
                        f"⚠️ WARNING: Team '{team_slug}' not found in organization '{org_name}'. Treating as empty.",
                        file=sys.stderr,
                    )
                    members_by_team[team_slug] = set()
                else:
                    raise RuntimeError(
                        f"Could not fetch members for team '{team_slug}': {e}"
                    ) from e
        return TeamMemberships.create(
            members_by_team=members_by_team, teams=config.teams
        )

    def _fetch_file_content(
        self, repo: object, path: str, ref: str | None
    ) -> str | None:
        """Fetch decoded UTF-8 file content from GitHub at a specific git ref."""
        if not ref or not isinstance(ref, str):
            return None
        try:
            content_file = repo.get_contents(path, ref=ref)
            if isinstance(content_file, list):
                return None
            decoded = getattr(content_file, "decoded_content", None)
            if isinstance(decoded, bytes):
                return decoded.decode("utf-8", errors="replace")
        except Exception:
            # Callers treat missing content as "unable to analyze" and fail closed.
            return None
        return None

    def _fetch_base_and_head_contents(
        self, repo: object, pr_file: object, base_sha: str | None, head_sha: str | None
    ) -> tuple[str | None, str | None] | None:
        """Fetch (base, head) contents for a changed file.

        Returns None unless every side that should exist (base unless the file was
        added, head unless it was removed) was fetched successfully, so that a
        partial fetch is never mistaken for an added or deleted document.
        """
        status = getattr(pr_file, "status", None)
        prev_filename = getattr(pr_file, "previous_filename", None) or pr_file.filename

        base_text: str | None = None
        if status != "added":
            base_text = self._fetch_file_content(repo, prev_filename, base_sha)
            if base_text is None:
                return None

        head_text: str | None = None
        if status != "removed":
            head_text = self._fetch_file_content(repo, pr_file.filename, head_sha)
            if head_text is None:
                return None

        return base_text, head_text

    def fetch_pull_request(
        self,
        repo_name: str,
        pr_number: int,
        normative_check: Callable[[str], bool] | None = None,
    ) -> PullRequest:
        """Fetch PR files, reviews, and requested reviewers from GitHub.

        Maps them to the PullRequest dataclass. For changed files accepted by
        `normative_check`, also fetches the unified diff patch and the base/head
        file contents used for normative RFC 2119 clause detection.
        """
        try:
            repo = self.g.get_repo(repo_name)
            pr = repo.get_pull(pr_number)

            pr_files = list(pr.get_files())
            changed_files = [f.filename for f in pr_files]
            file_patches: dict[str, str] = {}
            file_contents: dict[str, tuple[str | None, str | None]] = {}

            if normative_check is not None:
                base_sha = getattr(getattr(pr, "base", None), "sha", None)
                head_sha = getattr(getattr(pr, "head", None), "sha", None)

                for f in pr_files:
                    if not normative_check(f.filename):
                        continue
                    patch_val = getattr(f, "patch", None)
                    if isinstance(patch_val, str):
                        file_patches[f.filename] = patch_val
                    contents = self._fetch_base_and_head_contents(
                        repo, f, base_sha, head_sha
                    )
                    if contents is not None:
                        file_contents[f.filename] = contents

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
                file_patches=file_patches,
                file_contents=file_contents,
            )
        except GithubException as e:
            raise RuntimeError(f"Failed to fetch PR info from GitHub: {e}") from e


class PullRequestValidator:
    """Rule engine for validating Pull Requests against governance rules using the Venn Diagram model."""

    def __init__(self, config: GovernanceConfig, memberships: TeamMemberships):
        """Initialize the validator with config and memberships."""
        self.config = config
        self.memberships = memberships

    def _resolve_l3_target_team(self, file_path: str) -> Team:
        """Resolve the Level 3 Technical Council target team for a file path."""
        segments = Path(file_path).as_posix().lower().split("/")
        for segment in segments:
            council_slug = DOMAIN_TECH_COUNCIL_BY_SEGMENT.get(segment)
            if council_slug and council_slug in self.config.teams:
                team = self.config.teams[council_slug]
                if team.level >= NORMATIVE_ESCALATION_LEVEL:
                    return team
        return self.config.teams.get("technical-council", GENERIC_TECH_COUNCIL_TEAM)

    @staticmethod
    def _escalation_reason(file_path: str, cause: str, sources: list[str]) -> str:
        """Build the human-readable reason for a Level 3 normative escalation."""
        return (
            f"{cause} in `{file_path}` (escalated from {', '.join(sources)} "
            f"to Level 3 Technical Council)."
        )

    def _apply_normative_escalations(
        self,
        pr: PullRequest,
        requirements_by_file: dict[str, list[RuleRequirement]],
    ) -> tuple[dict[str, list[RuleRequirement]], dict[str, str]]:
        """Escalate lower-level requirements to Level 3 for opted-in Markdown files that touch normative clauses.

        Fails closed: if neither the base/head contents nor the diff patch of an
        opted-in Markdown file are available, the file is escalated as if it
        modified normative clauses.
        """
        updated_by_file: dict[str, list[RuleRequirement]] = {}
        escalation_reasons_by_file: dict[str, str] = {}

        for file_path, reqs in requirements_by_file.items():
            if not requires_normative_check(self.config, file_path):
                updated_by_file[file_path] = reqs
                continue

            contents = pr.file_contents.get(file_path)
            patch = pr.file_patches.get(file_path)
            if contents is None and not patch:
                cause = (
                    "Normative RFC 2119 clauses could not be analyzed because the "
                    "file contents and diff were unavailable"
                )
            else:
                base_content, head_content = contents or (None, None)
                change_result = detect_normative_changes(
                    file_path=file_path,
                    base_content=base_content,
                    head_content=head_content,
                    patch=patch,
                )
                if not change_result.has_normative_changes:
                    updated_by_file[file_path] = reqs
                    continue
                keywords = change_result.affected_keywords
                kw_str = (
                    f" ({', '.join(f'`{k}`' for k in keywords)})" if keywords else ""
                )
                cause = (
                    f"Normative RFC 2119 clauses{kw_str} were added, removed, "
                    f"or modified"
                )

            target_l3_team = self._resolve_l3_target_team(file_path)
            new_reqs: list[RuleRequirement] = []
            escalated_from_descriptions: list[str] = []

            for req in reqs:
                source_team = req.team or req.min_team
                if (
                    source_team is not None
                    and source_team.level < NORMATIVE_ESCALATION_LEVEL
                ):
                    source_desc = f"'{source_team.name}' (Level {source_team.level})"
                    if source_desc not in escalated_from_descriptions:
                        escalated_from_descriptions.append(source_desc)
                    new_reqs.append(
                        RuleRequirement(
                            min_approvals=req.min_approvals,
                            min_team=target_l3_team,
                            escalation_reason=self._escalation_reason(
                                file_path, cause, [source_desc]
                            ),
                        )
                    )
                else:
                    new_reqs.append(req)

            updated_by_file[file_path] = merge_requirements(new_reqs)

            if escalated_from_descriptions:
                escalation_reasons_by_file[file_path] = self._escalation_reason(
                    file_path, cause, escalated_from_descriptions
                )

        return updated_by_file, escalation_reasons_by_file

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

        # 5. Rule Matching & Normative Clause L3 Escalation
        requirements_by_file = self.config.get_applicable_requirements(pr.changed_files)
        requirements_by_file, escalation_reasons_by_file = (
            self._apply_normative_escalations(pr, requirements_by_file)
        )
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
            merged_requirements,
            approver_usernames,
            assigned_usernames,
            author=pr.author,
        )

        # 8. File-by-File Evaluation
        file_statuses = self._evaluate_file_statuses(
            requirements_by_file,
            approver_usernames,
            assigned_usernames,
            author=pr.author,
            escalation_reasons_by_file=escalation_reasons_by_file,
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

    def _evaluate_requirement(
        self,
        req: RuleRequirement,
        approver_usernames: set[str],
        requested_users_set: set[str],
        author: str | None = None,
    ) -> RequirementStatus:
        """Calculate and return status for a requirement under the Venn Diagram model."""
        approver_users = [User.create(u, self.memberships) for u in approver_usernames]
        assigned_users = [User.create(u, self.memberships) for u in requested_users_set]

        approvers = [u.username for u in approver_users if req.is_satisfied_by(u)]
        assigned_count = sum(1 for u in assigned_users if req.is_satisfied_by(u))
        approved_count = len(approvers)

        # Dynamic Governance Council requirement evaluation based on PR author
        is_gc_req = (req.team and req.team.name == "governance-council") or (
            req.min_team and req.min_team.name == "governance-council"
        )

        effective_req = req
        require_total_approvals = None

        if is_gc_req and author:
            author_user = User.create(author, self.memberships)
            is_author_gc = "governance-council" in author_user.teams

            if is_author_gc:
                min_approvals = 1
                if min_approvals != req.min_approvals:
                    effective_req = RuleRequirement(
                        min_approvals=min_approvals,
                        team=req.team,
                        min_team=req.min_team,
                        escalation_reason=req.escalation_reason,
                    )
                    require_total_approvals = req.min_approvals

        is_satisfied = approved_count >= effective_req.min_approvals
        if (
            require_total_approvals is not None
            and len(approver_usernames) < require_total_approvals
        ):
            is_satisfied = False

        return RequirementStatus(
            requirement=effective_req,
            approved_count=approved_count,
            assigned_count=assigned_count,
            is_satisfied=is_satisfied,
            approvers=sorted(approvers),
        )

    def _evaluate_requirements(
        self,
        requirements: list[RuleRequirement],
        approver_usernames: set[str],
        assigned_usernames: set[str],
        author: str | None = None,
    ) -> list[RequirementStatus]:
        """Evaluate each requirement's approvals and assignments count under the Venn Diagram model."""
        requirement_statuses = []
        for req in requirements:
            status = self._evaluate_requirement(
                req, approver_usernames, assigned_usernames, author=author
            )
            requirement_statuses.append(status)

        return requirement_statuses

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
            user = User.create(username, self.memberships)
            for req in requirements:
                if req.is_satisfied_by(user):
                    authorized.add(username)
                    break
        return authorized

    def _get_all_approvers_and_assigned_usernames(
        self, pr: PullRequest
    ) -> tuple[set[str], set[str]]:
        """Resolve valid approvals set and requested reviewers set for a PR."""
        assigned = set(pr.assigned_user_names)
        for team in pr.assigned_team_names:
            if team_obj := self.config.teams.get(team):
                assigned.update(self.memberships.members_by_team.get(team_obj, set()))

        approvers = set()
        for user, state in pr.latest_actionable_reviews_by_username.items():
            if state == ReviewState.APPROVED:
                if user != pr.author:
                    approvers.add(user)
            else:
                assigned.add(user)

        # Count reviewers who have submitted reviews (including comments) as actively reviewing
        for review in pr.reviews:
            if review.user != pr.author:
                assigned.add(review.user.lower())

        assigned.difference_update(approvers)
        assigned.discard(pr.author)
        return approvers, assigned

    def _evaluate_file_statuses(
        self,
        requirements_by_file: dict[str, list[RuleRequirement]],
        approver_usernames: set[str],
        assigned_usernames: set[str],
        author: str | None = None,
        escalation_reasons_by_file: dict[str, str] | None = None,
    ) -> list[FileValidationStatus]:
        """Evaluates and generates validation statuses for each changed file in the PR."""
        file_statuses = []
        escalation_map = escalation_reasons_by_file or {}
        for file, file_requirements in requirements_by_file.items():
            file_req_statuses = self._evaluate_requirements(
                file_requirements, approver_usernames, assigned_usernames, author=author
            )
            file_satisfied = all(status.is_satisfied for status in file_req_statuses)

            file_statuses.append(
                FileValidationStatus(
                    file_path=file,
                    requirement_statuses=file_req_statuses,
                    is_satisfied=file_satisfied,
                    escalation_reason=escalation_map.get(file),
                )
            )
        return file_statuses


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
        "--rules-file",
        help="Path to the governance rules YAML file. If not provided, resolved via --repo mapping.",
    )
    return parser.parse_args(args)


def run_validation(args: argparse.Namespace) -> ValidationResult:
    """Execute the core validation flow."""
    if args.rules_file:
        rules_file = args.rules_file
    else:
        # Resolve rules file path by convention: rules/<repo-suffix>-rules.yml
        repo_suffix = args.repo.split("/")[-1]
        rules_file = (
            f".github-central/org-tools/governance/rules/{repo_suffix}-rules.yml"
        )

    if not os.path.exists(rules_file):
        raise FileNotFoundError(
            f"Governance rules file not found at '{rules_file}'. "
            f"Please ensure it exists or specify a custom path using --rules-file."
        )

    # 1. Load config
    config = GovernanceConfigParser().parse_file(rules_file)

    # 2. Authenticate and fetch data
    auth = Auth.Token(args.token)
    g = Github(auth=auth)
    github_client = GitHubClient(g)

    # 3. Fetch team memberships & PR details
    memberships = github_client.fetch_team_memberships(args.org, config)
    pr = github_client.fetch_pull_request(
        args.repo,
        args.pr,
        normative_check=lambda path: requires_normative_check(config, path),
    )

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
        # Exit 2 to distinguish runtime/config errors from unsatisfied rules (exit 1).
        sys.exit(2)


if __name__ == "__main__":
    main()
