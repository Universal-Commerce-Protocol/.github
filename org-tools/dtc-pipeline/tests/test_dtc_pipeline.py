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

"""Unit tests for the UCP DTC Meeting Pipeline & Community Spotlight Engine."""

from __future__ import annotations

import datetime
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import dtc_pipeline as dp  # noqa: E402


class TestDtcPipeline(unittest.TestCase):
    """Tests for the 3 automated eligibility gates, 100-point formula, and Project v2 schema."""

    def setUp(self) -> None:
        self.now = datetime.datetime(2026, 10, 20, 9, 0, tzinfo=datetime.timezone.utc)
        self.excluded_handles = {"amithanda", "igrigorik", "gsmith85", "karangoel16"}

    def test_parse_maintainers_companies(self) -> None:
        md = """
| Name | Company |
| :--- | :------ |
| Amit Handa* | Google |
| Ilya Grigorik | Shopify |
| Open | to be elected |
"""
        companies = dp.parse_maintainers_companies(md)
        self.assertIn("google", companies)
        self.assertIn("shopify", companies)
        self.assertNotIn("to be elected", companies)

    def test_gate1_excludes_dtc_member_and_company_and_bot(self) -> None:
        ext_candidate = dp.ContributionCandidate(
            number=773,
            title="feat: add state-bound Offer extension for Cart proposals",
            url="https://github.com/Universal-Commerce-Protocol/ucp/pull/773",
            is_pr=True,
            created_at=self.now - datetime.timedelta(days=36),
            author=dp.AuthorMeta(
                login="arjun2075",
                company="Intuit",
                email="arjun@intuit.com",
            ),
            labels={"gov:needs-tc-review", "area:shopping"},
        )
        ok, reasons = dp.evaluate_gate1_affiliation(
            ext_candidate, self.excluded_handles
        )
        self.assertTrue(ok)
        self.assertEqual(reasons, [])

        goog_candidate = dp.ContributionCandidate(
            number=900,
            title="feat: internal proposal",
            url="https://github.com/Universal-Commerce-Protocol/ucp/pull/900",
            is_pr=True,
            created_at=self.now,
            author=dp.AuthorMeta(
                login="somegoogler",
                company="",
                email="dev@google.com",
            ),
        )
        ok_g, reasons_g = dp.evaluate_gate1_affiliation(
            goog_candidate, self.excluded_handles
        )
        self.assertFalse(ok_g)
        self.assertTrue(any("google.com" in r for r in reasons_g))

        bot_candidate = dp.ContributionCandidate(
            number=901,
            title="chore(deps): bump uv",
            url="https://github.com/Universal-Commerce-Protocol/ucp/pull/901",
            is_pr=True,
            created_at=self.now,
            author=dp.AuthorMeta(login="dependabot[bot]", user_type="Bot"),
        )
        ok_b, _ = dp.evaluate_gate1_affiliation(bot_candidate, self.excluded_handles)
        self.assertFalse(ok_b)

    def test_gate2_scope_pr_and_issue(self) -> None:
        tc_pr = dp.ContributionCandidate(
            number=811,
            title="feat: add per-seller offer attribution",
            url="https://github.com/Universal-Commerce-Protocol/ucp/pull/811",
            is_pr=True,
            created_at=self.now,
            author=dp.AuthorMeta(login="proshoumma", company="Klarna"),
            labels={"gov:needs-tc-review", "area:shopping"},
        )
        self.assertTrue(dp.evaluate_gate2_scope(tc_pr)[0])

        typo_pr = dp.ContributionCandidate(
            number=812,
            title="docs: fix typo in overview",
            url="https://github.com/Universal-Commerce-Protocol/ucp/pull/812",
            is_pr=True,
            created_at=self.now,
            author=dp.AuthorMeta(login="proshoumma", company="Klarna"),
        )
        self.assertFalse(dp.evaluate_gate2_scope(typo_pr)[0])

        prop_issue = dp.ContributionCandidate(
            number=841,
            title="[Proposal]: Structured inapplicable discount codes",
            url="https://github.com/Universal-Commerce-Protocol/ucp/issues/841",
            is_pr=False,
            created_at=self.now,
            author=dp.AuthorMeta(login="extdev"),
            labels={"area:shopping", "enhancement-proposal"},
        )
        self.assertTrue(dp.evaluate_gate2_scope(prop_issue)[0])

        common_issue = dp.ContributionCandidate(
            number=842,
            title="[RFC]: Shared envelope pagination cursor",
            url="https://github.com/Universal-Commerce-Protocol/ucp/issues/842",
            is_pr=False,
            created_at=self.now,
            author=dp.AuthorMeta(login="extdev"),
            labels={"area:common", "rfc"},
        )
        self.assertTrue(dp.evaluate_gate2_scope(common_issue)[0])

    def test_gate3_hygiene_and_blocked_exclusion(self) -> None:
        dirty_pr = dp.ContributionCandidate(
            number=700,
            title="feat: dirty pr",
            url="https://github.com/Universal-Commerce-Protocol/ucp/pull/700",
            is_pr=True,
            created_at=self.now,
            author=dp.AuthorMeta(login="extdev"),
            mergeable_state="dirty",
        )
        ok, reasons = dp.evaluate_gate3_hygiene(dirty_pr)
        self.assertFalse(ok)
        self.assertTrue(any("dirty" in r for r in reasons))

        blocked_pr = dp.ContributionCandidate(
            number=701,
            title="feat: blocked pr",
            url="https://github.com/Universal-Commerce-Protocol/ucp/pull/701",
            is_pr=True,
            created_at=self.now,
            author=dp.AuthorMeta(login="extdev"),
            labels={"status:blocked"},
        )
        ok_b, reasons_b = dp.evaluate_gate3_hygiene(blocked_pr)
        self.assertFalse(ok_b)
        self.assertTrue(any("status:blocked" in r for r in reasons_b))

    def test_priority_score_and_cooldown(self) -> None:
        pr_773 = dp.ContributionCandidate(
            number=773,
            title="feat: add state-bound Offer extension for Cart proposals",
            url="https://github.com/Universal-Commerce-Protocol/ucp/pull/773",
            is_pr=True,
            created_at=self.now - datetime.timedelta(days=36),
            author=dp.AuthorMeta(login="arjun2075", company="Intuit"),
            labels={"gov:needs-tc-review", "area:shopping"},
            comments=[
                dp.CommentMeta(
                    "reviewer1",
                    "User",
                    "Looks promising",
                    self.now - datetime.timedelta(days=10),
                ),
                dp.CommentMeta(
                    "reviewer2",
                    "User",
                    "Question on schema",
                    self.now - datetime.timedelta(days=8),
                ),
                dp.CommentMeta(
                    "reviewer3",
                    "User",
                    "+1 on use case",
                    self.now - datetime.timedelta(days=5),
                ),
            ],
        )
        score = dp.compute_priority_score(pr_773, self.now)
        self.assertEqual(score.readiness, 40)
        self.assertEqual(score.traction, 15)
        self.assertEqual(score.wait_boost, 30)
        self.assertEqual(score.cooldown_penalty, 0)
        self.assertEqual(score.total, 85)

        pr_773.comments.append(
            dp.CommentMeta(
                "github-actions[bot]",
                "Bot",
                "<!-- ucp-meeting-minutes: tc/shopping/2026/2026-10-16.md -->\n📋 **Discussed**",
                self.now - datetime.timedelta(days=3),
            )
        )
        score_after = dp.compute_priority_score(pr_773, self.now)
        self.assertEqual(score_after.wait_boost, 3)
        self.assertEqual(score_after.cooldown_penalty, 30)
        self.assertEqual(score_after.total, 40 + 15 + 3 - 30)

    def test_status_options_six_columns_with_next_dtc_agenda(self) -> None:
        self.assertEqual(
            [opt[0] for opt in dp.PROJECT_STATUS_OPTIONS],
            [
                "Triage / Unscheduled",
                "Next DTC Agenda",
                "Approved",
                "Follow-up / Revisions",
                "Redirected / Declined",
                "Closed / Merged",
            ],
        )
        self.assertEqual(dp.PROJECT_STATUS_OPTIONS[1][0], "Next DTC Agenda")
        self.assertEqual(dp.PROJECT_STATUS_OPTIONS[1][1], "ORANGE")
        self.assertIn("⚠️ Confirm Framing", dp.PROJECT_STATUS_OPTIONS[1][2])

        class StubManager(dp.GitHubProjectV2Manager):
            def graphql(self, query: str, variables: dict | None = None) -> dict:
                if "updateProjectV2Field" in query and variables is not None:
                    return {
                        "updateProjectV2Field": {
                            "projectV2Field": {
                                "id": variables["fieldId"],
                                "options": [
                                    {"id": f"opt_{idx}", "name": o["name"]}
                                    for idx, o in enumerate(variables["options"])
                                ],
                            }
                        }
                    }
                return {}

        mgr = StubManager(token="fake")
        opts = mgr._ensure_status_field("f_status")
        self.assertEqual(len(opts), 6)
        self.assertNotIn("Ready / Framed", opts)
        self.assertIn("Next DTC Agenda", opts)

        matching_existing = [
            {"id": f"existing_{idx}", "name": name, "color": color, "description": desc}
            for idx, (name, color, desc) in enumerate(dp.PROJECT_STATUS_OPTIONS)
        ]
        mutations_called = False

        class NoOpMutationManager(dp.GitHubProjectV2Manager):
            def graphql(self, query: str, variables: dict | None = None) -> dict:
                nonlocal mutations_called
                if "updateProjectV2Field" in query:
                    mutations_called = True
                return {}

        noop_mgr = NoOpMutationManager(token="fake")
        preserved = noop_mgr._ensure_status_field(
            "f_status", existing_options=matching_existing
        )
        self.assertFalse(mutations_called)
        self.assertEqual(preserved["Next DTC Agenda"], "existing_1")

    def test_spotlight_score_is_milestone_blind(self) -> None:
        base_pr = dp.ContributionCandidate(
            number=811,
            title="feat: add per-seller offer attribution",
            url="https://github.com/Universal-Commerce-Protocol/ucp/pull/811",
            is_pr=True,
            created_at=self.now - datetime.timedelta(days=24),
            author=dp.AuthorMeta(login="proshoumma", company="Klarna"),
            labels={"gov:needs-tc-review", "area:shopping"},
            milestone_title=None,
        )
        milestoned_pr = dp.ContributionCandidate(
            number=811,
            title="feat: add per-seller offer attribution",
            url="https://github.com/Universal-Commerce-Protocol/ucp/pull/811",
            is_pr=True,
            created_at=self.now - datetime.timedelta(days=24),
            author=dp.AuthorMeta(login="proshoumma", company="Klarna"),
            labels={"gov:needs-tc-review", "area:shopping"},
            milestone_title="2026-12-08",
        )
        self.assertEqual(
            dp.compute_priority_score(base_pr, self.now).total,
            dp.compute_priority_score(milestoned_pr, self.now).total,
        )

    def test_configure_project_views_five_views_single_board_per_vertical(self) -> None:
        calls: list[tuple[str, dict | None]] = []

        class StubManager(dp.GitHubProjectV2Manager):
            def graphql(self, query: str, variables: dict | None = None) -> dict:
                calls.append((query, variables))
                if "views(first: 20)" in query:
                    return {
                        "node": {
                            "fields": {
                                "nodes": [
                                    {"id": "f_title", "name": "Title"},
                                    {"id": "f_status", "name": "Status"},
                                    {"id": "f_ms", "name": "Milestone"},
                                    {"id": "f_track", "name": "Track"},
                                    {"id": "f_labels", "name": "Labels"},
                                    {"id": "f_score", "name": "Priority Score"},
                                ]
                            },
                            "views": {
                                "nodes": [
                                    {
                                        "id": "v1",
                                        "number": 1,
                                        "name": "Shopping TC",
                                        "layout": "BOARD_LAYOUT",
                                        "filter": "label:area:shopping,area:common",
                                    },
                                    {
                                        "id": "v2",
                                        "number": 2,
                                        "name": "Payments TC",
                                        "layout": "BOARD_LAYOUT",
                                        "filter": "label:area:payments",
                                    },
                                    {
                                        "id": "v3",
                                        "number": 3,
                                        "name": "Food TC",
                                        "layout": "BOARD_LAYOUT",
                                        "filter": "label:area:food",
                                    },
                                    {
                                        "id": "v4",
                                        "number": 4,
                                        "name": "Lodging TC",
                                        "layout": "BOARD_LAYOUT",
                                        "filter": "label:area:lodging",
                                    },
                                    {
                                        "id": "v5",
                                        "number": 5,
                                        "name": "Community Spotlight Pool",
                                        "layout": "TABLE_LAYOUT",
                                        "filter": "label:community-spotlight",
                                    },
                                ]
                            },
                        }
                    }
                if "updateProjectV2View" in query:
                    assert variables is not None
                    return {
                        "updateProjectV2View": {
                            "projectV2View": {
                                "id": variables["viewId"],
                                "number": 1,
                                "name": variables.get(
                                    "name", "Community Spotlight Pool"
                                ),
                                "layout": (
                                    "BOARD_LAYOUT"
                                    if "BOARD_LAYOUT" in query
                                    else "TABLE_LAYOUT"
                                ),
                                "filter": variables.get("filter"),
                            }
                        }
                    }
                return {}

        mgr = StubManager(token="fake")
        configured = mgr.configure_project_views("PVT_test")
        self.assertEqual(len(configured), 5)

        update_vars = [
            v for q, v in calls if "updateProjectV2View" in q and v is not None
        ]
        self.assertEqual(len(update_vars), 5)
        for v in update_vars:
            self.assertIn("f_ms", v["visibleFieldIds"])
            self.assertNotIn("f_labels", v["visibleFieldIds"])

    def test_sync_agenda_assignees_auto_assigns_mover_to_next_dtc_agenda(self) -> None:
        mutations: list[dict] = []

        class StubManager(dp.GitHubProjectV2Manager):
            def graphql(self, query: str, variables: dict | None = None) -> dict:
                if "addAssigneesToAssignable" in query:
                    assert variables is not None
                    mutations.append(variables)
                    return {
                        "addAssigneesToAssignable": {
                            "assignable": {"__typename": "PullRequest"}
                        }
                    }
                return {
                    "node": {
                        "items": {
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                            "nodes": [
                                {
                                    "id": "item_1",
                                    "content": {
                                        "__typename": "PullRequest",
                                        "id": "PR_node_773",
                                        "number": 773,
                                        "title": "Offer extension",
                                        "assignees": {"nodes": []},
                                    },
                                    "statusValue": {
                                        "name": "Next DTC Agenda",
                                        "updatedAt": "2026-10-29T10:00:00Z",
                                        "creator": {
                                            "__typename": "User",
                                            "id": "U_damaz91",
                                            "login": "damaz91",
                                        },
                                    },
                                },
                                {
                                    "id": "item_2",
                                    "content": {
                                        "__typename": "Issue",
                                        "id": "I_node_738",
                                        "number": 738,
                                        "title": "Already assigned",
                                        "assignees": {"nodes": [{"login": "gsmith85"}]},
                                    },
                                    "statusValue": {
                                        "name": "Next DTC Agenda",
                                        "updatedAt": "2026-10-29T10:05:00Z",
                                        "creator": {
                                            "__typename": "User",
                                            "id": "U_gsmith85",
                                            "login": "gsmith85",
                                        },
                                    },
                                },
                                {
                                    "id": "item_3",
                                    "content": {
                                        "__typename": "PullRequest",
                                        "id": "PR_node_691",
                                        "number": 691,
                                        "title": "In Triage",
                                        "assignees": {"nodes": []},
                                    },
                                    "statusValue": {
                                        "name": "Triage / Unscheduled",
                                        "updatedAt": "2026-10-29T10:00:00Z",
                                        "creator": {
                                            "__typename": "User",
                                            "id": "U_damaz91",
                                            "login": "damaz91",
                                        },
                                    },
                                },
                            ],
                        }
                    }
                }

        mgr = StubManager(token="fake")
        res = mgr.sync_agenda_assignees("PVT_test", apply=True)
        self.assertEqual(len(res["assigned"]), 1)
        self.assertEqual(res["assigned"][0]["number"], 773)
        self.assertEqual(res["assigned"][0]["assignee"], "damaz91")
        self.assertEqual(len(res["already_assigned"]), 1)
        self.assertEqual(res["already_assigned"][0]["number"], 738)
        self.assertEqual(
            mutations,
            [{"assignableId": "PR_node_773", "assigneeIds": ["U_damaz91"]}],
        )

    def test_apply_spotlight_scan_syncs_project_without_applying_labels(self) -> None:
        mutations: list[tuple[str, dict]] = []

        class StubManager(dp.GitHubProjectV2Manager):
            def graphql(self, query: str, variables: dict | None = None) -> dict:
                if "fields(first: 30)" in query:
                    return {
                        "node": {
                            "fields": {
                                "nodes": [
                                    {
                                        "id": "F_status",
                                        "name": "Status",
                                        "options": [
                                            {
                                                "id": "OPT_triage",
                                                "name": "Triage / Unscheduled",
                                            }
                                        ],
                                    },
                                    {
                                        "id": "F_track",
                                        "name": "Track",
                                        "options": [
                                            {
                                                "id": "OPT_cs",
                                                "name": "Community Spotlight",
                                            }
                                        ],
                                    },
                                    {"id": "F_score", "name": "Priority Score"},
                                ]
                            },
                            "items": {"nodes": []},
                        }
                    }
                if "addProjectV2ItemById" in query:
                    assert variables is not None
                    mutations.append(("add_item", variables))
                    return {"addProjectV2ItemById": {"item": {"id": "PVTI_811"}}}
                if "addLabelsToLabelable" in query:
                    raise AssertionError("Should never apply repository labels")
                if "updateProjectV2ItemFieldValue" in query:
                    assert variables is not None
                    mutations.append(("update_field", variables))
                    return {
                        "updateProjectV2ItemFieldValue": {
                            "projectV2Item": {"id": "PVTI_811"}
                        }
                    }
                return {}

        cand = dp.ContributionCandidate(
            number=811,
            title="feat: add per-seller offer attribution",
            url="https://github.com/Universal-Commerce-Protocol/ucp/pull/811",
            is_pr=True,
            created_at=self.now,
            author=dp.AuthorMeta(login="proshoumma", company="Klarna"),
            labels={"gov:needs-tc-review", "area:shopping"},
            node_id="PR_node_811",
        )
        score = dp.PriorityScoreBreakdown(
            readiness=40,
            participant_points=10,
            reaction_points=9,
            wait_days=30,
            wait_boost=30,
            cooldown_penalty=0,
        )
        scan_result = {
            "eligible": [
                (
                    cand,
                    dp.GateEvaluation(True, True, True, True, ()),
                    score,
                )
            ]
        }
        mgr = StubManager(token="fake")
        applied = mgr.apply_spotlight_scan(
            scan_result,
            project_ids=["PVT_prod"],
            apply=True,
        )
        self.assertEqual(len(applied["synced_projects"]), 1)
        self.assertEqual(
            [m[0] for m in mutations],
            ["add_item", "update_field", "update_field", "update_field"],
        )

    def test_pending_cla_check_run_is_not_treated_as_passed(self) -> None:
        from dtc_pipeline.spotlight import _parse_pr_checks

        pr_pending_cla = {
            "commits": {
                "nodes": [
                    {
                        "commit": {
                            "statusCheckRollup": {
                                "contexts": {
                                    "nodes": [
                                        {
                                            "__typename": "CheckRun",
                                            "name": "cla/google",
                                            "conclusion": None,
                                        }
                                    ]
                                }
                            }
                        }
                    }
                ]
            }
        }
        cla_passed, ci_passed = _parse_pr_checks(pr_pending_cla)
        self.assertFalse(cla_passed)
        self.assertTrue(ci_passed)


if __name__ == "__main__":
    unittest.main()
