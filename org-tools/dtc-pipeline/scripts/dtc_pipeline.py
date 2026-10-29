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

"""CLI entrypoint and package root for the UCP DTC Review Pipeline."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

# Expose `scripts/dtc_pipeline/` as submodules (`dtc_pipeline.config`,
# `dtc_pipeline.spotlight`, `dtc_pipeline.project_v2`) while keeping
# `scripts/dtc_pipeline.py` as the direct CLI script.
__path__ = [str(Path(__file__).resolve().with_suffix(""))]
if __spec__ is not None:
    __spec__.submodule_search_locations = __path__
sys.modules.setdefault("dtc_pipeline", sys.modules[__name__])

from dtc_pipeline.config import (  # noqa: E402,F401
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
    PROJECT_STATUS_OPTIONS,
    PROJECT_TRACK_OPTIONS,
    PROJECT_VERTICAL_DOMAINS,
    PROPOSAL_LABELS,
    PROPOSAL_PREFIX_RE,
    VERTICAL_DOMAIN_LABELS,
    infer_item_verticals,
    logger,
)
from dtc_pipeline.project_v2 import GitHubProjectV2Manager  # noqa: E402,F401
from dtc_pipeline.spotlight import (  # noqa: E402,F401
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


def build_parser() -> argparse.ArgumentParser:
    """Builds the CLI argument parser for `dtc_pipeline.py`."""
    parser = argparse.ArgumentParser(
        description="UCP DTC Meeting Pipeline & Community Spotlight Election Engine."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan_p = subparsers.add_parser(
        "scan-spotlight",
        help="Run the Community Spotlight 3-gate + 100-point election scan in read-only mode (no labels applied).",
    )
    scan_p.add_argument(
        "--org",
        default=DEFAULT_ORG,
        help="GitHub organization (default: Universal-Commerce-Protocol).",
    )
    scan_p.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help="GitHub repository (default: ucp).",
    )

    provision_p = subparsers.add_parser(
        "provision-project",
        help="Create or clone a GitHub Project v2 board with UCP DTC fields and views.",
    )
    provision_p.add_argument(
        "--owner",
        required=True,
        help="GitHub user or organization login (e.g. Universal-Commerce-Protocol).",
    )
    provision_p.add_argument(
        "--title",
        default="UCP DTC Review Pipeline",
        help="Project title.",
    )
    provision_p.add_argument(
        "--public",
        action="store_true",
        help="Make the project public (defaults to private).",
    )
    provision_p.add_argument(
        "--template-project-id",
        default="",
        help="Optional template Project v2 node ID to clone views and workflows from.",
    )
    provision_p.add_argument(
        "--replace-project-id",
        default="",
        help="Optional existing Project v2 node ID to delete before provisioning.",
    )

    views_p = subparsers.add_parser(
        "configure-views",
        help="Configure the 4 vertical TC Boards and the Community Spotlight Pool Table.",
    )
    views_p.add_argument(
        "--project-id",
        required=True,
        help="GitHub Project v2 GraphQL node ID (or comma-separated IDs).",
    )

    assignees_p = subparsers.add_parser(
        "sync-agenda-assignees",
        help="Auto-assign the TC member who dragged an item into Next DTC Agenda (`statusValue.creator`).",
    )
    assignees_p.add_argument(
        "--project-id",
        default=os.getenv("DTC_PROJECT_ID", ""),
        help="GitHub Project v2 GraphQL node ID (or comma-separated IDs; defaults to DTC_PROJECT_ID env var).",
    )
    assignees_p.add_argument(
        "--apply",
        action="store_true",
        help="Apply assignee mutations via GraphQL (defaults to dry-run preview).",
    )
    return parser


def _resolve_github_token() -> str | None:
    """Resolves a GitHub token from `ORG_TRIAGE_TOKEN`, `GITHUB_TOKEN`, or `gh auth token`."""
    token = os.getenv("ORG_TRIAGE_TOKEN") or os.getenv("GITHUB_TOKEN")
    if token:
        return token
    try:
        proc = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout.strip()
    except Exception as exc:
        logger.error("No GitHub token found in env or `gh auth token`: %s", exc)
        return None


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for UCP DTC Pipeline & Project v2 management."""
    args = build_parser().parse_args(argv)
    token = _resolve_github_token()
    if not token:
        return 1

    manager = GitHubProjectV2Manager(token=token)
    if args.command == "scan-spotlight":
        res = manager.scan_live_spotlight(org=args.org, repo=args.repo)
        log_spotlight_report(res, org=args.org, repo=args.repo)
        return 0

    if args.command == "provision-project":
        if args.replace_project_id:
            manager.delete_project(args.replace_project_id)
            logger.info("Deleted old Project (%s).", args.replace_project_id)
        project = manager.create_dtc_project(
            owner_login=args.owner,
            title=args.title,
            public=args.public,
            template_project_id=args.template_project_id or None,
        )
        logger.info(
            "Created Project #%s: %s (%s)",
            project["number"],
            project["title"],
            project["url"],
        )
        return 0

    project_ids = [pid.strip() for pid in args.project_id.split(",") if pid.strip()]
    if args.command == "configure-views":
        for pid in project_ids:
            for v in manager.configure_project_views(pid):
                logger.info(
                    "[%s] Configured View #%s '%s' (%s, filter=%r)",
                    pid,
                    v.get("number"),
                    v.get("name"),
                    v.get("layout"),
                    v.get("filter"),
                )
        return 0

    if args.command == "sync-agenda-assignees":
        if not project_ids:
            logger.info(
                "No project ID provided (--project-id or DTC_PROJECT_ID); skipping sync-agenda-assignees."
            )
            return 0
        for pid in project_ids:
            res = manager.sync_agenda_assignees(pid, apply=args.apply)
            for item in res["assigned"]:
                mode = "Assigned" if args.apply else "[DRY-RUN] Would assign"
                logger.info(
                    "[%s] %s @%s to #%s (%s)",
                    pid,
                    mode,
                    item["assignee"],
                    item["number"],
                    item["title"],
                )
            for item in res["already_assigned"]:
                logger.info(
                    "[%s] #%s already assigned to @%s",
                    pid,
                    item["number"],
                    item["assignee"],
                )
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
