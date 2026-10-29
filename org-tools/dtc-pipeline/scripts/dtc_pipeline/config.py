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

"""Configuration constants and label definitions for the UCP DTC Review Pipeline."""

from __future__ import annotations

import logging
from pathlib import Path
import re

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("dtc_pipeline")

DEFAULT_ORG = "Universal-Commerce-Protocol"
DEFAULT_REPO = "ucp"
DEFAULT_MAINTAINERS_PATH = str(Path(__file__).resolve().parents[4] / "MAINTAINERS.md")

DOMAIN_LABELS = frozenset(
    {
        "area:shopping",
        "area:payments",
        "area:food",
        "area:lodging",
        "area:common",
    }
)
VERTICAL_DOMAIN_LABELS = frozenset(
    {
        "area:shopping",
        "area:payments",
        "area:food",
        "area:lodging",
    }
)

EXCLUDED_ORG_TEAMS = (
    "shopping-tech-council",
    "payments-tech-council",
    "food-tech-council",
    "lodging-tech-council",
    "governance-council",
    "maintainers",
)

DEFAULT_EXCLUDED_COMPANIES = frozenset(
    {
        "google",
        "alphabet",
        "shopify",
        "stripe",
        "amazon",
        "meta",
        "facebook",
        "microsoft",
        "salesforce",
        "etsy",
        "target",
        "wayfair",
        "paypal",
        "adyen",
        "coinbase",
        "global payments",
        "ant international",
        "alipay",
        "square",
        "block",
        "toast",
        "doordash",
        "uber",
        "uber eats",
        "expedia",
        "booking.com",
        "booking",
        "trip.com",
        "marriott",
        "hilton",
        "amadeus",
    }
)

EXCLUDED_EMAIL_DOMAINS = frozenset(
    {
        "google.com",
        "shopify.com",
        "stripe.com",
        "amazon.com",
        "meta.com",
        "fb.com",
        "microsoft.com",
        "salesforce.com",
        "etsy.com",
        "target.com",
        "wayfair.com",
        "paypal.com",
        "adyen.com",
        "coinbase.com",
        "globalpay.com",
        "antgroup.com",
        "squareup.com",
        "block.xyz",
        "toasttab.com",
        "doordash.com",
        "uber.com",
        "expediagroup.com",
        "expedia.com",
        "booking.com",
        "trip.com",
        "marriott.com",
        "hilton.com",
        "amadeus.com",
    }
)

PROPOSAL_PREFIX_RE = re.compile(
    r"^\s*\[(?:Feat|Proposal|Enhancement Proposal|RFC)\]\s*:?",
    re.IGNORECASE,
)
PROPOSAL_LABELS = frozenset(
    {
        "enhancement-proposal",
        "enhancement",
        "rfc",
        "gov:tc-meeting",
    }
)
EXCLUDED_ISSUE_LABELS = frozenset({"bug", "question"})
HYGIENE_BLOCKED_ISSUE_LABELS = frozenset({"status:stale", "status:blocked", "wontfix"})

CIRCLE_BACK_MARKER_RE = re.compile(r"<!--\s*ucp-meeting-minutes:\s*([^\s>]+)\s*-->")

PROJECT_STATUS_OPTIONS = (
    (
        "Triage / Unscheduled",
        "GRAY",
        "Tagged gov:tc-meeting or community-spotlight; raw nomination awaiting triage.",
    ),
    (
        "Next DTC Agenda",
        "ORANGE",
        "⚠️ Confirm Framing Comment (or self-contained body) is in place before moving here.",
    ),
    (
        "Approved",
        "GREEN",
        "Approved by DTC; gov:tc-meeting removed and circle-back comment posted once meeting-minutes merges.",
    ),
    (
        "Follow-up / Revisions",
        "PURPLE",
        "Discussed in DTC; direction approved with revisions or follow-up requested.",
    ),
    (
        "Redirected / Declined",
        "RED",
        "Redirected to a Domain Working Group / self-hosted extension or declined.",
    ),
    (
        "Closed / Merged",
        "GRAY",
        "Automatically set by GitHub Projects native workflow when the PR/Issue is closed or merged.",
    ),
)

PROJECT_TRACK_OPTIONS = (
    (
        "General Track",
        "BLUE",
        "DTC or Maintainer nominated item for synchronous discussion.",
    ),
    (
        "Community Spotlight",
        "GREEN",
        "1 reserved slot/week per DTC via 100-point automated election heuristic.",
    ),
)

PROJECT_VERTICAL_DOMAINS = (
    ("Shopping", "label:area:shopping,area:common"),
    ("Payments", "label:area:payments"),
    ("Food", "label:area:food"),
    ("Lodging", "label:area:lodging"),
)


def infer_item_verticals(labels: set[str] | list[str]) -> list[str]:
    """Maps an Issue/PR's `area:*` labels to one or more DTC vertical names."""
    lower = {lbl.strip().lower() for lbl in labels if lbl}
    matched: list[str] = []
    if lower & {"area:shopping", "area:common"}:
        matched.append("Shopping")
    if "area:payments" in lower:
        matched.append("Payments")
    if "area:food" in lower:
        matched.append("Food")
    if "area:lodging" in lower:
        matched.append("Lodging")
    return matched or ["Shopping"]
