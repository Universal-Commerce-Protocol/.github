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

from governance_config_parser import RuleRequirement


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
    assigned_users: list[str] = field(default_factory=list)
    assigned_teams: list[str] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        number: int,
        author: str,
        is_draft: bool,
        changed_files: list[str],
        reviews: list[Review],
        assigned_users: list[str] = None,
        assigned_teams: list[str] = None,
    ) -> "PullRequest":
        # Normalize to lowercase. GitHub usernames and team slugs are case-insensitive.
        # Reference: https://docs.github.com/en/rest/teams/teams?apiVersion=2026-03-10#get-a-team-by-name
        assigned_u = [u.lower() for u in assigned_users] if assigned_users else []
        assigned_t = [t.lower() for t in assigned_teams] if assigned_teams else []
        return cls(
            number=number,
            author=author.lower(),
            is_draft=is_draft,
            changed_files=changed_files,
            reviews=reviews,
            assigned_users=assigned_u,
            assigned_teams=assigned_t,
        )


@dataclass(frozen=True)
class TeamMemberships:
    """Stores a map of team slugs to their members' GitHub usernames."""

    members_by_team: dict[str, set[str]]

    @classmethod
    def create(cls, members_by_team: dict[str, set[str]]) -> "TeamMemberships":
        # Normalize to lowercase. GitHub usernames and team slugs are case-insensitive.
        # Reference: https://docs.github.com/en/rest/teams/teams?apiVersion=2026-03-10#get-a-team-by-name
        normalized = {
            team.lower(): {member.lower() for member in members}
            for team, members in members_by_team.items()
        }
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
