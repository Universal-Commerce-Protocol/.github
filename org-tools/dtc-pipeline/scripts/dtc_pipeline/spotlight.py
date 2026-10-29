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

"""Community Spotlight eligibility gates, 100-point priority scoring, and live GitHub scanner."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import datetime
from pathlib import Path
import re

from .config import (
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
    PROPOSAL_LABELS,
    PROPOSAL_PREFIX_RE,
    infer_item_verticals,
    logger,
)

EXPLICIT_ISSUE_REF_RE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|issue|proposal|implements|addresses)\s*:?\s*(?:#|https://github\.com/[\w.-]+/[\w.-]+/issues/)(\d+)",
    re.IGNORECASE,
)
ANY_ISSUE_MENTION_RE = re.compile(
    r"(?:#|https://github\.com/[\w.-]+/[\w.-]+/issues/)(\d+)",
    re.IGNORECASE,
)


@dataclass
class AuthorMeta:
    """Metadata about a GitHub contribution author."""

    login: str
    user_type: str = "User"
    company: str = ""
    email: str = ""


@dataclass
class CommentMeta:
    """Metadata about an issue or PR comment or review."""

    author_login: str
    author_type: str
    body: str
    created_at: datetime.datetime


@dataclass
class ContributionCandidate:
    """Normalized representation of a PR, Proposal Issue, or Issue+PR Bundle."""

    number: int
    title: str
    url: str
    is_pr: bool
    created_at: datetime.datetime
    author: AuthorMeta
    labels: set[str] = field(default_factory=set)
    body: str = ""
    draft: bool = False
    mergeable_state: str = "clean"
    cla_passed: bool = True
    ci_passed: bool = True
    ready_for_review_at: datetime.datetime | None = None
    linked_issue_number: int | None = None
    comments: list[CommentMeta] = field(default_factory=list)
    thumbs_up_count: int = 0
    rocket_count: int = 0
    milestone_title: str | None = None


@dataclass(frozen=True)
class GateEvaluation:
    """Detailed result of evaluating the 3 Community Spotlight gates."""

    eligible: bool
    gate1_passed: bool
    gate2_passed: bool
    gate3_passed: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class PriorityScoreBreakdown:
    """Deterministic 100-Point Priority Score breakdown."""

    readiness: int
    participant_points: int
    reaction_points: int
    wait_days: int
    wait_boost: int
    cooldown_penalty: int

    @property
    def traction(self) -> int:
        return min(30, self.participant_points + self.reaction_points)

    @property
    def total(self) -> int:
        raw = self.readiness + self.traction + self.wait_boost - self.cooldown_penalty
        return max(0, min(100, raw))


def parse_maintainers_companies(markdown_text: str) -> set[str]:
    """Extracts normalized company names from MAINTAINERS.md markdown tables."""
    companies = set(DEFAULT_EXCLUDED_COMPANIES)
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or stripped.startswith("| :"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 2:
            continue
        name_col, company_col = cells[0].lower(), cells[1].lower()
        if name_col in ("name", "") or company_col in (
            "company",
            "to be elected",
            "open",
            "",
        ):
            continue
        companies.add(company_col)
    return companies


def is_bot_user(author: AuthorMeta) -> bool:
    """Returns True if the author is an automated bot account."""
    login_lower = author.login.strip().lower()
    return (
        author.user_type.lower() == "bot"
        or login_lower.endswith("[bot]")
        or login_lower in ("dependabot", "github-actions", "renovate")
    )


def _normalize_company(raw_company: str) -> str:
    cleaned = raw_company.strip().lower().lstrip("@")
    cleaned = re.sub(r"\b(?:inc\.?|llc|ltd\.?|corp\.?|nv|gmbh)\b", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip(" ,.-")


def evaluate_gate1_affiliation(
    candidate: ContributionCandidate,
    excluded_handles: set[str],
    excluded_companies: set[str] = DEFAULT_EXCLUDED_COMPANIES,
    excluded_email_domains: set[str] = EXCLUDED_EMAIL_DOMAINS,
) -> tuple[bool, list[str]]:
    """Gate 1: Automated Non-DTC Corporate Affiliation (Author Filter)."""
    reasons: list[str] = []
    person = candidate.author
    if is_bot_user(person):
        return (False, [f"Author '{person.login}' is an automated bot."])

    norm_excluded_handles = {h.lower().lstrip("@") for h in excluded_handles}
    norm_excluded_companies = {_normalize_company(c) for c in excluded_companies if c}

    handle = person.login.strip().lower().lstrip("@")
    if handle in norm_excluded_handles:
        reasons.append(
            f"Author '@{person.login}' is a member of a UCP governance/maintainer team."
        )

    for excl in norm_excluded_companies:
        if (
            excl
            and len(excl) >= 4
            and (
                handle.endswith(f"-{excl}")
                or handle.endswith(f"_{excl}")
                or handle.startswith(f"{excl}-")
            )
        ):
            reasons.append(
                f"Author '@{person.login}' handle suffix/prefix matches DTC/GC member organization '{excl}'."
            )
            break

    if person.company:
        norm_comp = _normalize_company(person.company)
        for excl in norm_excluded_companies:
            if excl and (
                norm_comp == excl
                or f" {excl} " in f" {norm_comp} "
                or norm_comp.startswith(f"{excl} ")
            ):
                reasons.append(
                    f"Author '@{person.login}' company '{person.company}' matches DTC/GC member organization '{excl}'."
                )
                break

    if person.email and "@" in person.email:
        domain = person.email.rsplit("@", 1)[-1].strip().lower()
        if domain in excluded_email_domains or any(
            domain.endswith(f".{d}") for d in excluded_email_domains
        ):
            reasons.append(
                f"Author '@{person.login}' email domain '{domain}' belongs to a DTC/GC member organization."
            )

    return (len(reasons) == 0, reasons)


def evaluate_gate2_scope(candidate: ContributionCandidate) -> tuple[bool, list[str]]:
    """Gate 2: Automated DTC Governance Scope Check (Scope Gate)."""
    labels_lower = {lbl.lower() for lbl in candidate.labels}

    if candidate.is_pr:
        if "gov:needs-tc-review" in labels_lower or "gov:tc-meeting" in labels_lower:
            return (True, [])
        return (
            False,
            ["PR does not carry 'gov:needs-tc-review' or 'gov:tc-meeting'."],
        )

    if labels_lower & EXCLUDED_ISSUE_LABELS:
        return (False, ["Issue is labeled 'bug' or 'question' (non-proposal)."])

    if not (labels_lower & DOMAIN_LABELS):
        return (
            False,
            [
                "Standalone Issue lacks an 'area:<domain>' label (area:shopping, area:payments, area:food, area:lodging, area:common)."
            ],
        )

    has_proposal_prefix = bool(PROPOSAL_PREFIX_RE.search(candidate.title))
    has_proposal_label = bool(labels_lower & PROPOSAL_LABELS)
    if not (has_proposal_prefix or has_proposal_label):
        return (
            False,
            [
                "Standalone Issue lacks a proposal prefix ([Feat], [Proposal], [Enhancement Proposal], [RFC]) or proposal label."
            ],
        )

    return (True, [])


def has_structured_proposal_body(body: str) -> bool:
    """Checks Gate 3 structured body requirement (>= 400 chars + template headers or JSON block)."""
    if len(body.strip()) < 400:
        return False
    lower = body.lower()
    has_ep_headers = "### summary" in lower and (
        "### motivation" in lower or "### detailed design" in lower
    )
    has_feat_header = "### describe the solution you'd like" in lower
    has_legacy_headers = "### problem" in lower and "### proposed solution" in lower
    has_json_fence = "```json" in lower
    return has_ep_headers or has_feat_header or has_legacy_headers or has_json_fence


def evaluate_gate3_hygiene(
    candidate: ContributionCandidate,
) -> tuple[bool, list[str]]:
    """Gate 3: Automated Baseline Readiness Check (Hygiene Gate)."""
    reasons: list[str] = []
    labels_lower = {lbl.lower() for lbl in candidate.labels}

    if labels_lower & HYGIENE_BLOCKED_ISSUE_LABELS:
        reasons.append(
            "Item carries a blocked/stale label ('status:stale', 'status:blocked', or 'wontfix')."
        )

    if candidate.is_pr:
        if candidate.draft:
            reasons.append("PR is still a WIP Draft (draft == true).")
        if candidate.mergeable_state.lower() == "dirty":
            reasons.append(
                "PR has unresolved merge conflicts (mergeable_state == 'dirty')."
            )
        if not candidate.cla_passed:
            reasons.append("Google CLA check ('cla/google') has not passed.")
        if not candidate.ci_passed:
            reasons.append("Required schema/spec validation CI checks are failing.")
        return (len(reasons) == 0, reasons)

    if not has_structured_proposal_body(candidate.body):
        reasons.append(
            "Issue body is < 400 characters or lacks completed proposal template headers / JSON schema block."
        )
    return (len(reasons) == 0, reasons)


def evaluate_candidate_gates(
    candidate: ContributionCandidate,
    excluded_handles: set[str],
    excluded_companies: set[str] = DEFAULT_EXCLUDED_COMPANIES,
) -> GateEvaluation:
    """Evaluates all 3 automated Community Spotlight eligibility gates."""
    g1_ok, g1_reasons = evaluate_gate1_affiliation(
        candidate,
        excluded_handles=excluded_handles,
        excluded_companies=excluded_companies,
    )
    g2_ok, g2_reasons = evaluate_gate2_scope(candidate)
    g3_ok, g3_reasons = evaluate_gate3_hygiene(candidate)
    all_reasons = tuple(g1_reasons + g2_reasons + g3_reasons)
    return GateEvaluation(
        eligible=(g1_ok and g2_ok and g3_ok),
        gate1_passed=g1_ok,
        gate2_passed=g2_ok,
        gate3_passed=g3_ok,
        reasons=all_reasons,
    )


def compute_priority_score(
    candidate: ContributionCandidate,
    now: datetime.datetime,
) -> PriorityScoreBreakdown:
    """Computes the deterministic 100-Point Priority Score for an eligible candidate."""
    # 1. Implementation & Spec Readiness (40 pts for PR, 10 pts for standalone Proposal Issue)
    readiness = 40 if candidate.is_pr else 10

    # 2. Capped Community Traction (0-30 Points)
    author_login = candidate.author.login.lower()
    distinct_participants: set[str] = set()
    latest_circle_back_at: datetime.datetime | None = None

    for comment in candidate.comments:
        if CIRCLE_BACK_MARKER_RE.search(comment.body):
            if (
                latest_circle_back_at is None
                or comment.created_at > latest_circle_back_at
            ):
                latest_circle_back_at = comment.created_at
            continue

        c_login = comment.author_login.strip().lower()
        if (
            not c_login
            or c_login == author_login
            or comment.author_type.lower() == "bot"
            or c_login.endswith("[bot]")
        ):
            continue
        if len(comment.body.strip()) > 0:
            distinct_participants.add(c_login)

    participant_points = min(15, len(distinct_participants) * 5)
    total_reactions = max(0, candidate.thumbs_up_count) + max(0, candidate.rocket_count)
    reaction_points = min(15, total_reactions * 3)

    # 3. Anti-Starvation / Queue Aging Boost (0-30 Points) & Cooldown (0 or 30)
    anchor_times = [candidate.created_at]
    if candidate.ready_for_review_at is not None:
        anchor_times.append(candidate.ready_for_review_at)
    if latest_circle_back_at is not None:
        anchor_times.append(latest_circle_back_at)

    wait_anchor = max(anchor_times)
    wait_days = max(0, (now - wait_anchor).days)
    wait_boost = min(30, wait_days)

    cooldown_penalty = 0
    if latest_circle_back_at is not None:
        days_since_circle_back = max(0, (now - latest_circle_back_at).days)
        if days_since_circle_back < 14:
            cooldown_penalty = 30

    return PriorityScoreBreakdown(
        readiness=readiness,
        participant_points=participant_points,
        reaction_points=reaction_points,
        wait_days=wait_days,
        wait_boost=wait_boost,
        cooldown_penalty=cooldown_penalty,
    )


def fetch_excluded_handles(
    graphql_fn: Callable[[str, dict | None], dict],
    org: str = DEFAULT_ORG,
) -> set[str]:
    """Fetches GitHub handles belonging to UCP governance/maintainer teams."""
    handles: set[str] = {
        "amithanda",
        "damaz91",
        "karangoel16",
        "igrigorik",
        "dwyckoff",
        "drewolson",
    }
    try:
        data = graphql_fn(
            """
            query($org: String!) {
              organization(login: $org) {
                teams(first: 30) {
                  nodes {
                    slug
                    members(first: 100) {
                      nodes {
                        login
                      }
                    }
                  }
                }
              }
            }
            """,
            {"org": org},
        )
        teams = data.get("organization", {}).get("teams", {}).get("nodes") or []
        for team in teams:
            if not team:
                continue
            slug = (team.get("slug") or "").lower()
            if slug in EXCLUDED_ORG_TEAMS or "maintainer" in slug or "council" in slug:
                for member in team.get("members", {}).get("nodes") or []:
                    if member and member.get("login"):
                        handles.add(member["login"].lower())
    except Exception as exc:
        logger.debug(
            "Could not query org teams (using fallback + company list): %s", exc
        )
    return handles


def _fetch_open_issues(
    graphql_fn: Callable[[str, dict | None], dict],
    org: str,
    repo: str,
) -> dict[int, dict]:
    """Fetches all OPEN repository Issues keyed by issue number."""
    open_issues: dict[int, dict] = {}
    cursor = None
    while True:
        data = graphql_fn(
            """
            query($owner: String!, $name: String!, $cursor: String) {
              repository(owner: $owner, name: $name) {
                issues(states: OPEN, first: 50, after: $cursor, orderBy: {field: CREATED_AT, direction: DESC}) {
                  pageInfo { hasNextPage endCursor }
                  nodes {
                    number
                    title
                    url
                    createdAt
                    body
                    author {
                      login
                      __typename
                      ... on User { company email }
                    }
                    milestone { title }
                    labels(first: 20) { nodes { name } }
                    reactions(content: THUMBS_UP) { totalCount }
                    rocketReactions: reactions(content: ROCKET) { totalCount }
                    comments(first: 50) {
                      nodes {
                        author { login __typename }
                        body
                        createdAt
                      }
                    }
                  }
                }
              }
            }
            """,
            {"owner": org, "name": repo, "cursor": cursor},
        )
        issues_conn = data["repository"]["issues"]
        for node in issues_conn["nodes"]:
            if node:
                open_issues[node["number"]] = node
        if not issues_conn["pageInfo"]["hasNextPage"]:
            break
        cursor = issues_conn["pageInfo"]["endCursor"]
    return open_issues


def _fetch_open_prs(
    graphql_fn: Callable[[str, dict | None], dict],
    org: str,
    repo: str,
) -> list[dict]:
    """Fetches all OPEN repository Pull Requests."""
    open_prs: list[dict] = []
    cursor = None
    while True:
        data = graphql_fn(
            """
            query($owner: String!, $name: String!, $cursor: String) {
              repository(owner: $owner, name: $name) {
                pullRequests(states: OPEN, first: 40, after: $cursor, orderBy: {field: CREATED_AT, direction: DESC}) {
                  pageInfo { hasNextPage endCursor }
                  nodes {
                    number
                    title
                    url
                    createdAt
                    body
                    isDraft
                    mergeable
                    author {
                      login
                      __typename
                      ... on User { company email }
                    }
                    milestone { title }
                    labels(first: 20) { nodes { name } }
                    closingIssuesReferences(first: 10) {
                      nodes { number }
                    }
                    reactions(content: THUMBS_UP) { totalCount }
                    rocketReactions: reactions(content: ROCKET) { totalCount }
                    comments(first: 50) {
                      nodes {
                        author { login __typename }
                        body
                        createdAt
                      }
                    }
                    reviews(first: 50) {
                      nodes {
                        author { login __typename }
                        body
                        createdAt
                      }
                    }
                    timelineItems(itemTypes: [READY_FOR_REVIEW_EVENT], last: 5) {
                      nodes {
                        ... on ReadyForReviewEvent { createdAt }
                      }
                    }
                    commits(last: 1) {
                      nodes {
                        commit {
                          statusCheckRollup {
                            contexts(first: 40) {
                              nodes {
                                __typename
                                ... on CheckRun { name conclusion }
                                ... on StatusContext { context state }
                              }
                            }
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
            """,
            {"owner": org, "name": repo, "cursor": cursor},
        )
        prs_conn = data["repository"]["pullRequests"]
        for node in prs_conn["nodes"]:
            if node:
                open_prs.append(node)
        if not prs_conn["pageInfo"]["hasNextPage"]:
            break
        cursor = prs_conn["pageInfo"]["endCursor"]
    return open_prs


def _extract_comments_meta(nodes: list[dict | None]) -> list[CommentMeta]:
    """Converts raw GraphQL comment/review nodes into `CommentMeta` items."""
    comments: list[CommentMeta] = []
    for node in nodes:
        if not node:
            continue
        author = node.get("author") or {}
        comments.append(
            CommentMeta(
                author_login=author.get("login") or "",
                author_type=author.get("__typename") or "User",
                body=node.get("body") or "",
                created_at=datetime.datetime.fromisoformat(
                    node["createdAt"].replace("Z", "+00:00")
                ),
            )
        )
    return comments


def _find_linked_issue_numbers(
    pr: dict,
    open_issues: dict[int, dict],
    author_login: str,
) -> list[int]:
    """Finds up to 1 primary linked open Proposal Issue for a Pull Request."""
    linked_nums: list[int] = []
    for ref in pr.get("closingIssuesReferences", {}).get("nodes") or []:
        if ref and ref.get("number") in open_issues:
            linked_nums.append(ref["number"])
    body = pr.get("body") or ""
    if not linked_nums:
        for m in EXPLICIT_ISSUE_REF_RE.finditer(body):
            inum = int(m.group(1))
            if inum in open_issues:
                linked_nums.append(inum)
                break
    if not linked_nums:
        for m in ANY_ISSUE_MENTION_RE.finditer(body):
            inum = int(m.group(1))
            if inum in open_issues:
                iss_author = (
                    (open_issues[inum].get("author") or {}).get("login") or ""
                ).lower()
                if iss_author and iss_author == author_login.lower():
                    linked_nums.append(inum)
                    break
    return linked_nums[:1]


def _parse_pr_checks(pr: dict) -> tuple[bool, bool]:
    """Extracts `(cla_passed, ci_passed)` from the PR's latest commit rollup."""
    cla_passed = True
    ci_passed = True
    commits_nodes = (pr.get("commits") or {}).get("nodes") or []
    if not (commits_nodes and commits_nodes[-1].get("commit")):
        return cla_passed, ci_passed

    rollup = commits_nodes[-1]["commit"].get("statusCheckRollup") or {}
    for ctx in rollup.get("contexts", {}).get("nodes") or []:
        if not ctx:
            continue
        if ctx.get("__typename") == "StatusContext":
            cname = (ctx.get("context") or "").lower()
            cstate = (ctx.get("state") or "").upper()
            if "cla" in cname:
                cla_passed = cstate == "SUCCESS"
            elif "governance" not in cname and cstate in ("FAILURE", "ERROR"):
                ci_passed = False
        elif ctx.get("__typename") == "CheckRun":
            cname = (ctx.get("name") or "").lower()
            concl = (ctx.get("conclusion") or "").upper()
            if "cla" in cname:
                cla_passed = concl in ("SUCCESS", "NEUTRAL", "SKIPPED")
            elif "governance" not in cname and concl in (
                "FAILURE",
                "TIMED_OUT",
                "ACTION_REQUIRED",
            ):
                ci_passed = False
    return cla_passed, ci_passed


def _build_pr_candidate(
    pr: dict,
    open_issues: dict[int, dict],
    bundled_issue_nums: set[int],
) -> ContributionCandidate:
    """Constructs a `ContributionCandidate` from a raw PR node, bundling any linked open Proposal Issue."""
    author_node = pr.get("author") or {}
    author = AuthorMeta(
        login=author_node.get("login") or "ghost",
        user_type=author_node.get("__typename") or "User",
        company=author_node.get("company") or "",
        email=author_node.get("email") or "",
    )
    labels = {
        lbl["name"]
        for lbl in (pr.get("labels", {}).get("nodes") or [])
        if lbl and lbl.get("name")
    }

    pr_created = datetime.datetime.fromisoformat(pr["createdAt"].replace("Z", "+00:00"))
    effective_created = pr_created
    linked_issue_num = None

    raw_pr_comments = (pr.get("comments", {}).get("nodes") or []) + (
        pr.get("reviews", {}).get("nodes") or []
    )
    comments_list = _extract_comments_meta(raw_pr_comments)
    thumbs = (pr.get("reactions") or {}).get("totalCount", 0)
    rockets = (pr.get("rocketReactions") or {}).get("totalCount", 0)

    for inum in _find_linked_issue_numbers(pr, open_issues, author.login):
        bundled_issue_nums.add(inum)
        issue_node = open_issues[inum]
        icreated = datetime.datetime.fromisoformat(
            issue_node["createdAt"].replace("Z", "+00:00")
        )
        if linked_issue_num is None:
            linked_issue_num = inum
        if icreated < effective_created:
            effective_created = icreated
        for ilbl in issue_node.get("labels", {}).get("nodes") or []:
            if ilbl and ilbl.get("name"):
                labels.add(ilbl["name"])
        thumbs += (issue_node.get("reactions") or {}).get("totalCount", 0)
        rockets += (issue_node.get("rocketReactions") or {}).get("totalCount", 0)
        comments_list.extend(
            _extract_comments_meta(issue_node.get("comments", {}).get("nodes") or [])
        )

    ready_at = None
    for ev in pr.get("timelineItems", {}).get("nodes") or []:
        if ev and ev.get("createdAt"):
            ready_at = datetime.datetime.fromisoformat(
                ev["createdAt"].replace("Z", "+00:00")
            )
    cla_passed, ci_passed = _parse_pr_checks(pr)
    mergeable_raw = (pr.get("mergeable") or "MERGEABLE").upper()
    mergeable_state = "dirty" if mergeable_raw == "CONFLICTING" else "clean"

    ms_title = (pr.get("milestone") or {}).get("title")
    if not ms_title and linked_issue_num is not None:
        ms_title = (open_issues[linked_issue_num].get("milestone") or {}).get("title")

    return ContributionCandidate(
        number=pr["number"],
        title=pr["title"],
        url=pr["url"],
        is_pr=True,
        created_at=effective_created,
        author=author,
        labels=labels,
        body=pr.get("body") or "",
        draft=bool(pr.get("isDraft")),
        mergeable_state=mergeable_state,
        cla_passed=cla_passed,
        ci_passed=ci_passed,
        ready_for_review_at=ready_at,
        linked_issue_number=linked_issue_num,
        comments=comments_list,
        thumbs_up_count=thumbs,
        rocket_count=rockets,
        milestone_title=ms_title,
    )


def _build_issue_candidate(inum: int, inode: dict) -> ContributionCandidate:
    """Constructs a standalone `ContributionCandidate` from a raw Issue node."""
    author_node = inode.get("author") or {}
    author = AuthorMeta(
        login=author_node.get("login") or "ghost",
        user_type=author_node.get("__typename") or "User",
        company=author_node.get("company") or "",
        email=author_node.get("email") or "",
    )
    labels = {
        lbl["name"]
        for lbl in (inode.get("labels", {}).get("nodes") or [])
        if lbl and lbl.get("name")
    }
    icreated = datetime.datetime.fromisoformat(
        inode["createdAt"].replace("Z", "+00:00")
    )
    comments_list = _extract_comments_meta(inode.get("comments", {}).get("nodes") or [])
    thumbs = (inode.get("reactions") or {}).get("totalCount", 0)
    rockets = (inode.get("rocketReactions") or {}).get("totalCount", 0)
    return ContributionCandidate(
        number=inum,
        title=inode["title"],
        url=inode["url"],
        is_pr=False,
        created_at=icreated,
        author=author,
        labels=labels,
        body=inode.get("body") or "",
        comments=comments_list,
        thumbs_up_count=thumbs,
        rocket_count=rockets,
        milestone_title=(inode.get("milestone") or {}).get("title"),
    )


def scan_live_spotlight(
    graphql_fn: Callable[[str, dict | None], dict],
    org: str = DEFAULT_ORG,
    repo: str = DEFAULT_REPO,
    maintainers_path: str = DEFAULT_MAINTAINERS_PATH,
) -> dict:
    """Runs a strictly read-only live Community Spotlight scan against `org/repo`."""
    now = datetime.datetime.now(datetime.timezone.utc)
    excluded_companies = set(DEFAULT_EXCLUDED_COMPANIES)
    mp = Path(maintainers_path)
    if mp.exists():
        excluded_companies |= parse_maintainers_companies(
            mp.read_text(encoding="utf-8")
        )
    excluded_handles = fetch_excluded_handles(graphql_fn, org=org)

    open_issues = _fetch_open_issues(graphql_fn, org, repo)
    open_prs = _fetch_open_prs(graphql_fn, org, repo)

    bundled_issue_nums: set[int] = set()
    candidates: list[ContributionCandidate] = [
        _build_pr_candidate(pr, open_issues, bundled_issue_nums) for pr in open_prs
    ]
    for inum, inode in open_issues.items():
        if inum not in bundled_issue_nums:
            candidates.append(_build_issue_candidate(inum, inode))

    eligible_items: list[
        tuple[ContributionCandidate, GateEvaluation, PriorityScoreBreakdown]
    ] = []
    gate_counts = {
        "total_open_prs": len(open_prs),
        "total_open_issues": len(open_issues),
        "bundled_pairs": len(bundled_issue_nums),
        "total_candidates": len(candidates),
        "passed_gate1": 0,
        "passed_gate1_and_2": 0,
        "passed_all_3_eligible": 0,
    }

    for cand in candidates:
        geval = evaluate_candidate_gates(
            cand,
            excluded_handles=excluded_handles,
            excluded_companies=excluded_companies,
        )
        score = compute_priority_score(cand, now=now)
        if geval.gate1_passed:
            gate_counts["passed_gate1"] += 1
        if geval.gate1_passed and geval.gate2_passed:
            gate_counts["passed_gate1_and_2"] += 1
            if geval.gate3_passed:
                gate_counts["passed_all_3_eligible"] += 1
                eligible_items.append((cand, geval, score))

    eligible_items.sort(
        key=lambda item: (-item[2].total, -item[2].readiness, item[0].created_at)
    )
    return {
        "counts": gate_counts,
        "eligible": eligible_items,
    }


def log_spotlight_report(res: dict, org: str, repo: str) -> None:
    """Logs a concise summary of the Community Spotlight scan per vertical."""
    counts = res["counts"]
    logger.info("=== Community Spotlight Scan (%s/%s) ===", org, repo)
    logger.info(
        "Candidates: %d | Passed Gate 1: %d | Passed Gate 1+2: %d | Eligible (All 3 Gates): %d",
        counts["total_candidates"],
        counts["passed_gate1"],
        counts["passed_gate1_and_2"],
        counts["passed_all_3_eligible"],
    )
    vertical_to_domain = (
        ("Shopping", "area:shopping"),
        ("Payments", "area:payments"),
        ("Food", "area:food"),
        ("Lodging", "area:lodging"),
    )
    for vertical, domain in vertical_to_domain:
        items = [
            (cand, score)
            for cand, _geval, score in res["eligible"]
            if vertical in infer_item_verticals(cand.labels)
        ]
        logger.info("--- %s (%d eligible) ---", domain, len(items))
        for idx, (cand, score) in enumerate(items, start=1):
            kind = "PR" if cand.is_pr else "Issue"
            logger.info(
                "  #%d: %s #%d (@%s) | Score: %d/100 (Readiness=%d, Traction=%d, Wait=%d, Cooldown=-%d) | %s",
                idx,
                kind,
                cand.number,
                cand.author.login,
                score.total,
                score.readiness,
                score.traction,
                score.wait_boost,
                score.cooldown_penalty,
                cand.title,
            )
