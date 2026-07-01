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

"""Data models and enums representing pull request state and validation results."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class ReviewState(Enum):
    """Represents the state of a GitHub pull request review."""

    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"
    COMMENTED = "commented"
    DISMISSED = "dismissed"
    PENDING = "pending"
    UNKNOWN = "unknown"

    @classmethod
    def actionable_states(cls) -> set["ReviewState"]:
        """States that affect PR mergeability."""
        return {cls.APPROVED, cls.CHANGES_REQUESTED, cls.DISMISSED}


class ValidationErrorReason(Enum):
    """Reasons why a pull request might fail governance validation."""

    DRAFT_PR = "draft_pr"
    CHANGES_REQUESTED = "changes_requested"
    INSUFFICIENT_APPROVALS = "insufficient_approvals"


class MergeableReason(Enum):
    """Reasons why a pull request is considered mergeable."""

    NO_CHANGED_FILES = "no_changed_files"
    PROXY_OVERRIDE = "proxy_override"
    RULES_SATISFIED = "rules_satisfied"


@dataclass(frozen=True)
class Team:
    """Represents a review team group in the hierarchy."""

    name: str
    level: int

    @classmethod
    def create(cls, name: str, level: int) -> "Team":
        # Normalize to lowercase. GitHub team slugs are case-insensitive.
        return cls(name=name.lower(), level=level)


@dataclass(frozen=True)
class User:
    """Represents a user in the context of the governance rules engine."""

    username: str
    teams: set[str]
    level: int

    @classmethod
    def create(cls, username: str, memberships: "TeamMemberships") -> "User":
        """Resolve a username into a rich User domain object."""
        username_lower = username.lower()
        user_teams = {
            team
            for team, members in memberships.members_by_team.items()
            if username_lower in members
        }

        # Calculate their max hierarchy level
        max_level = max((t.level for t in user_teams), default=0)

        # Map Team objects to their string names for the User dataclass
        team_names = {t.name for t in user_teams}
        return cls(username=username_lower, teams=team_names, level=max_level)


class RequirementTargetType(Enum):
    """Represents the type of requirement target (exact team vs. hierarchical min team)."""

    TEAM = "team"
    MIN_TEAM = "min_team"


@dataclass(frozen=True)
class RuleRequirement:
    """Represents a requirement for a rule, specifying min approvals and the target Team."""

    min_approvals: int
    team: Team | None = None
    min_team: Team | None = None

    def __post_init__(self):
        if self.min_approvals is None or not isinstance(self.min_approvals, int):
            raise ValueError("min_approvals must be an integer")
        if self.min_approvals <= 0:
            raise ValueError("min_approvals must be a positive integer")
        if (self.team is None and self.min_team is None) or (
            self.team is not None and self.min_team is not None
        ):
            raise ValueError(
                "RuleRequirement must specify exactly one of 'team' or 'min_team'"
            )

    def is_satisfied_by(self, user: User) -> bool:
        """Check if a user satisfies this team or hierarchical level requirement."""
        if self.team is not None:
            return self.team.name in user.teams
        elif self.min_team is not None:
            return user.level >= self.min_team.level
        return False

    @property
    def target_key(self) -> tuple[RequirementTargetType, str]:
        """A unique tuple key representing the target of this requirement."""
        if self.team is not None:
            return (RequirementTargetType.TEAM, self.team.name)
        elif self.min_team is not None:
            return (RequirementTargetType.MIN_TEAM, self.min_team.name)
        raise ValueError("Invalid RuleRequirement: both team and min_team are None")


def merge_requirements(requirements: list[RuleRequirement]) -> list[RuleRequirement]:
    """Merge a list of requirements by keeping the maximum min_approvals for each target."""
    merged: dict[tuple[RequirementTargetType, str], RuleRequirement] = {}
    for req in requirements:
        key = req.target_key
        if key not in merged:
            merged[key] = req
        else:
            existing = merged[key]
            if req.min_approvals > existing.min_approvals:
                merged[key] = req
    return list(merged.values())


@dataclass(frozen=True)
class Review:
    """Represents a pull request review with a user and state."""

    user: str
    state: ReviewState
    submitted_at: datetime | None = None

    @classmethod
    def create(
        cls, user: str, state: ReviewState, submitted_at: datetime | None = None
    ) -> "Review":
        # Normalize to lowercase. GitHub usernames and team slugs are case-insensitive.
        # Reference: https://docs.github.com/en/rest/teams/teams?apiVersion=2026-03-10#get-a-team-by-name
        return cls(user=user.lower(), state=state, submitted_at=submitted_at)


@dataclass(frozen=True)
class PullRequest:
    """Represents a GitHub pull request with its files, reviews, and requests."""

    number: int
    author: str
    is_draft: bool
    changed_files: list[str]
    reviews: list[Review]
    assigned_user_names: list[str] = field(default_factory=list)
    assigned_team_names: list[str] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        number: int,
        author: str,
        is_draft: bool,
        changed_files: list[str],
        reviews: list[Review],
        assigned_user_names: list[str] = None,
        assigned_team_names: list[str] = None,
    ) -> "PullRequest":
        # Normalize to lowercase. GitHub usernames and team slugs are case-insensitive.
        # Reference: https://docs.github.com/en/rest/teams/teams?apiVersion=2026-03-10#get-a-team-by-name
        assigned_u = (
            [u.lower() for u in assigned_user_names] if assigned_user_names else []
        )
        assigned_t = (
            [t.lower() for t in assigned_team_names] if assigned_team_names else []
        )
        return cls(
            number=number,
            author=author.lower(),
            is_draft=is_draft,
            changed_files=changed_files,
            reviews=reviews,
            assigned_user_names=assigned_u,
            assigned_team_names=assigned_t,
        )

    @property
    def latest_actionable_reviews_by_username(self) -> dict[str, ReviewState]:
        """Resolve the latest actionable review state for each user.

        Skips non-actionable states like COMMENTED.
        """
        # Sort reviews by submitted_at (if available) to ensure chronological processing
        sorted_reviews = sorted(
            self.reviews,
            key=lambda x: (
                x.submitted_at if x.submitted_at is not None else datetime.min
            ),
        )

        relevant_reviews: dict[str, ReviewState] = {}
        for r in sorted_reviews:
            if r.state in ReviewState.actionable_states():
                relevant_reviews[r.user] = r.state
        return relevant_reviews

    def has_proxy_override(self, proxy_reviewers: set[str]) -> bool:
        """Check if a proxy reviewer has approved the PR, bypassing rules."""
        latest = self.latest_actionable_reviews_by_username
        return any(
            state == ReviewState.APPROVED and user in proxy_reviewers
            for user, state in latest.items()
        )


@dataclass(frozen=True)
class TeamMemberships:
    """Stores a map of Team objects to their members' GitHub usernames."""

    members_by_team: dict[Team, set[str]]

    @classmethod
    def create(
        cls, members_by_team: dict[str, set[str]], teams: dict[str, Team]
    ) -> "TeamMemberships":
        # Normalize to lowercase. GitHub usernames and team slugs are case-insensitive.
        # Reference: https://docs.github.com/en/rest/teams/teams?apiVersion=2026-03-10#get-a-team-by-name
        normalized = {}
        for team_slug, members in members_by_team.items():
            team_obj = teams.get(team_slug.lower())
            if team_obj is None:
                team_obj = Team.create(name=team_slug, level=0)
            normalized[team_obj] = {member.lower() for member in members}
        return cls(members_by_team=normalized)


@dataclass(frozen=True)
class RequirementStatus:
    """Represents the status of a specific rule requirement."""

    requirement: RuleRequirement
    approved_count: int = 0
    assigned_count: int = 0
    is_satisfied: bool = False
    approvers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FileValidationStatus:
    """Represents the validation status of a single file in the PR."""

    file_path: str
    requirement_statuses: list[RequirementStatus]
    is_satisfied: bool


@dataclass(frozen=True)
class ValidationResult:
    """Represents the final result of a pull request validation."""

    is_mergeable: bool
    error: ValidationErrorReason | None = None
    mergeable_reason: MergeableReason | None = None
    requirement_statuses: list[RequirementStatus] = field(default_factory=list)
    file_statuses: list[FileValidationStatus] = field(default_factory=list)
