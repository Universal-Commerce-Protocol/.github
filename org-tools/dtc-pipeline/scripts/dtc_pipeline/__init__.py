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

"""UCP DTC Review Pipeline package."""

from __future__ import annotations

from .config import (  # noqa: F401
    CIRCLE_BACK_MARKER_RE,
    DEFAULT_EXCLUDED_COMPANIES,
    DEFAULT_MAINTAINERS_PATH,
    DEFAULT_ORG,
    DEFAULT_REPO,
    DOMAIN_LABELS,
    EXCLUDED_EMAIL_DOMAINS,
    EXCLUDED_ISSUE_LABELS,
    EXCLUDED_ORG_TEAMS,
    HYGIENE_BLOCKED_ISSUE_LABELS,
    POST_MEETING_STATUSES,
    PROJECT_STATUS_OPTIONS,
    PROJECT_TRACK_OPTIONS,
    PROJECT_VERTICAL_DOMAINS,
    PROPOSAL_LABELS,
    PROPOSAL_PREFIX_RE,
    VERTICAL_DOMAIN_LABELS,
    infer_item_verticals,
    logger,
)
from .project_v2 import GitHubProjectV2Manager  # noqa: F401
from .spotlight import (  # noqa: F401
    AuthorMeta,
    CommentMeta,
    ContributionCandidate,
    GateEvaluation,
    PriorityScoreBreakdown,
    compute_priority_score,
    evaluate_candidate_gates,
    evaluate_gate1_affiliation,
    evaluate_gate2_scope,
    evaluate_gate3_hygiene,
    fetch_excluded_handles,
    has_structured_proposal_body,
    is_bot_user,
    log_spotlight_report,
    parse_maintainers_companies,
    scan_live_spotlight,
)
