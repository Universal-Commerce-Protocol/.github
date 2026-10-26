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

"""Unit tests for run_governance_gate.py."""

import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts"))
)

import run_governance_gate  # noqa: E402

SAMPLE_SHA = "a" * 40
OTHER_SHA = "b" * 40


class TestRunGovernanceGate(unittest.TestCase):
    """Tests for PR/SHA resolution, summary annotations, and status posting."""

    def _base_env(self, step_summary: str = "") -> dict[str, str]:
        return {
            "ORG_READ_TOKEN": "org-token",
            "STATUS_TOKEN": "status-token",
            "GITHUB_ORG": "Universal-Commerce-Protocol",
            "GITHUB_REPO": "Universal-Commerce-Protocol/ucp",
            "GITHUB_API_URL": "https://api.github.com",
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_RUN_ID": "987654",
            "GITHUB_STEP_SUMMARY": step_summary,
        }

    def test_parse_pr_number_and_sha_filtering(self) -> None:
        self.assertEqual(
            run_governance_gate.parse_pr_number("", "null", "0", "42"),
            42,
        )
        self.assertIsNone(run_governance_gate.parse_pr_number("", "null", "0"))
        with self.assertRaises(ValueError):
            run_governance_gate.parse_pr_number("42; rm -rf /")

        self.assertEqual(
            run_governance_gate.parse_commit_sha("", "null", SAMPLE_SHA),
            SAMPLE_SHA,
        )
        with self.assertRaises(ValueError):
            run_governance_gate.parse_commit_sha("../etc/passwd")

    @patch.object(run_governance_gate, "_github_api_json")
    @patch.object(subprocess, "run")
    def test_pull_request_target_success_posts_status_and_summary(
        self,
        mock_subproc: unittest.mock.MagicMock,
        mock_api: unittest.mock.MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            summary_file = tmp / "summary.txt"
            step_summary = tmp / "step_summary.md"
            validator_script = tmp / "pr_validator.py"
            validator_script.write_text("# stub\n", encoding="utf-8")

            def fake_validator(
                cmd: list[str], check: bool = False
            ) -> subprocess.CompletedProcess[str]:
                summary_file.write_text("Line 1\nLine 2 100%\r\n", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 0)

            mock_subproc.side_effect = fake_validator
            env = self._base_env(step_summary=str(step_summary))
            env["INPUT_PR_NUMBER"] = "123"
            env["INPUT_COMMIT_SHA"] = SAMPLE_SHA
            env["INPUT_RULES_FILE"] = "custom/rules.yml"

            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                rc = run_governance_gate.run_gate(
                    env=env,
                    validator_script=validator_script,
                    summary_file=summary_file,
                )

            self.assertEqual(rc, 0)
            mock_subproc.assert_called_once_with(
                [
                    "uv",
                    "run",
                    str(validator_script),
                    "--token",
                    "org-token",
                    "--org",
                    "Universal-Commerce-Protocol",
                    "--repo",
                    "Universal-Commerce-Protocol/ucp",
                    "--pr",
                    "123",
                    "--rules-file",
                    "custom/rules.yml",
                ],
                check=False,
            )
            self.assertIn(
                "::notice title=Approval Status::Line 1%0ALine 2 100%25%0A",
                stdout.getvalue(),
            )
            self.assertIn(
                "Line 1\nLine 2 100%", step_summary.read_text(encoding="utf-8")
            )
            mock_api.assert_called_once_with(
                "POST",
                f"https://api.github.com/repos/Universal-Commerce-Protocol/ucp/statuses/{SAMPLE_SHA}",
                "status-token",
                payload={
                    "state": "success",
                    "context": "Governance / Approvals",
                    "description": "Governance approvals met",
                    "target_url": "https://github.com/Universal-Commerce-Protocol/ucp/actions/runs/987654",
                },
            )

    @patch.object(run_governance_gate, "_github_api_json")
    @patch.object(subprocess, "run")
    def test_workflow_run_resolves_fork_pr_and_posts_failure_status(
        self,
        mock_subproc: unittest.mock.MagicMock,
        mock_api: unittest.mock.MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            summary_file = tmp / "summary.txt"
            validator_script = tmp / "pr_validator.py"
            validator_script.write_text("# stub\n", encoding="utf-8")

            def fake_validator(
                cmd: list[str], check: bool = False
            ) -> subprocess.CompletedProcess[str]:
                summary_file.write_text("Missing L2 approval", encoding="utf-8")
                return subprocess.CompletedProcess(cmd, 1)

            mock_subproc.side_effect = fake_validator

            def fake_api(
                method: str,
                url: str,
                token: str,
                payload: dict[str, object] | None = None,
            ) -> object:
                if method == "GET" and url.endswith(f"/commits/{SAMPLE_SHA}/pulls"):
                    return [
                        {"number": 77, "state": "closed", "head": {"sha": OTHER_SHA}},
                        {"number": 88, "state": "open", "head": {"sha": SAMPLE_SHA}},
                    ]
                return {}

            mock_api.side_effect = fake_api
            env = self._base_env()
            env["INPUT_PR_NUMBER"] = ""
            env["EVENT_PR_NUMBER"] = "null"
            env["INPUT_COMMIT_SHA"] = SAMPLE_SHA

            stdout = io.StringIO()
            with patch("sys.stdout", stdout):
                rc = run_governance_gate.run_gate(
                    env=env,
                    validator_script=validator_script,
                    summary_file=summary_file,
                )

            self.assertEqual(rc, 0)
            self.assertIn(
                "::error title=Missing Approvals::Missing L2 approval",
                stdout.getvalue(),
            )
            self.assertEqual(mock_api.call_count, 2)
            post_call = mock_api.call_args_list[1]
            self.assertEqual(post_call.args[0], "POST")
            self.assertEqual(
                post_call.kwargs["payload"],
                {
                    "state": "failure",
                    "context": "Governance / Approvals",
                    "description": "Pending required approvals",
                    "target_url": "https://github.com/Universal-Commerce-Protocol/ucp/actions/runs/987654",
                },
            )

    @patch.object(run_governance_gate, "_github_api_json")
    def test_search_fallback_when_commits_pulls_empty(
        self,
        mock_api: unittest.mock.MagicMock,
    ) -> None:
        mock_api.side_effect = [
            [],
            {"items": [{"number": 99}]},
        ]
        pr_num = run_governance_gate.resolve_pr_number_from_sha(
            "https://api.github.com",
            "Universal-Commerce-Protocol/ucp",
            SAMPLE_SHA,
            "org-token",
        )
        self.assertEqual(pr_num, 99)

    @patch.object(run_governance_gate, "_github_api_json")
    def test_unresolvable_pr_returns_nonzero(
        self,
        mock_api: unittest.mock.MagicMock,
    ) -> None:
        mock_api.return_value = []
        env = self._base_env()
        env["EVENT_WORKFLOW_RUN_HEAD_SHA"] = SAMPLE_SHA
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            rc = run_governance_gate.run_gate(env=env)
        self.assertEqual(rc, 1)
        self.assertIn("PR number could not be resolved", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
