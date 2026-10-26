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

import email.message
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts"))
)

import run_governance_gate  # noqa: E402

SAMPLE_SHA = "a" * 40
OTHER_SHA = "b" * 40


class TestRunGovernanceGate(unittest.TestCase):
    """Tests for PR/SHA resolution, TOCTOU guards, annotations, and status posting."""

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

            def fake_api(
                method: str,
                url: str,
                token: str,
                payload: dict[str, object] | None = None,
            ) -> object:
                if method == "GET" and url.endswith("/pulls/123"):
                    return {"number": 123, "head": {"sha": SAMPLE_SHA}}
                return {}

            mock_subproc.side_effect = fake_validator
            mock_api.side_effect = fake_api
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
            self.assertEqual(mock_api.call_count, 3)
            self.assertEqual(
                mock_api.call_args_list[2],
                unittest.mock.call(
                    "POST",
                    f"https://api.github.com/repos/Universal-Commerce-Protocol/ucp/statuses/{SAMPLE_SHA}",
                    "status-token",
                    payload={
                        "state": "success",
                        "context": "Governance / Approvals",
                        "description": "Governance approvals met",
                        "target_url": "https://github.com/Universal-Commerce-Protocol/ucp/actions/runs/987654",
                    },
                ),
            )

    @patch.object(run_governance_gate, "_github_api_json")
    @patch.object(subprocess, "run")
    def test_workflow_run_resolves_fork_pr_from_open_pulls_without_commits_index(
        self,
        mock_subproc: unittest.mock.MagicMock,
        mock_api: unittest.mock.MagicMock,
    ) -> None:
        """Fork PRs return [] on /commits/{sha}/pulls; open-pulls pagination resolves them."""
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

            page_1 = [
                {"number": i, "state": "open", "head": {"sha": OTHER_SHA}}
                for i in range(1, run_governance_gate.OPEN_PRS_PER_PAGE + 1)
            ]
            page_2 = [
                {"number": 201, "state": "open", "head": {"sha": SAMPLE_SHA}},
            ]

            def fake_api(
                method: str,
                url: str,
                token: str,
                payload: dict[str, object] | None = None,
            ) -> object:
                if method == "GET" and "state=open" in url and "&page=1" in url:
                    return page_1
                if method == "GET" and "state=open" in url and "&page=2" in url:
                    return page_2
                if method == "GET" and url.endswith(f"/commits/{SAMPLE_SHA}/pulls"):
                    raise AssertionError(
                        "/commits/{sha}/pulls should not be needed when open PR matches"
                    )
                if method == "GET" and url.endswith("/pulls/201"):
                    return {"number": 201, "head": {"sha": SAMPLE_SHA}}
                return {}

            mock_api.side_effect = fake_api
            env = self._base_env()
            env["INPUT_PR_NUMBER"] = ""
            env["EVENT_PR_NUMBER"] = "null"
            env["EVENT_WORKFLOW_RUN_PR_NUMBER"] = ""
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
            post_call = mock_api.call_args_list[-1]
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
    def test_search_fallback_prefers_open_pr_over_closed_duplicate(
        self,
        mock_api: unittest.mock.MagicMock,
    ) -> None:
        mock_api.side_effect = [
            [],  # /pulls?state=open&page=1
            [],  # /commits/{sha}/pulls
            {
                "items": [
                    {"number": 70, "state": "closed"},
                    {"number": 71, "state": "open"},
                ]
            },
        ]
        pr_num = run_governance_gate.resolve_pr_number_from_sha(
            "https://api.github.com",
            "Universal-Commerce-Protocol/ucp",
            SAMPLE_SHA,
            "org-token",
        )
        self.assertEqual(pr_num, 71)

    @patch.object(run_governance_gate, "_github_api_json")
    @patch.object(subprocess, "run")
    def test_skips_status_when_commit_superseded_before_or_during_validation(
        self,
        mock_subproc: unittest.mock.MagicMock,
        mock_api: unittest.mock.MagicMock,
    ) -> None:
        """Prevents TOCTOU stamping when PR head advances away from commit_sha."""
        # Case 1: PR head already advanced before pr_validator.py runs.
        mock_api.return_value = {"number": 55, "head": {"sha": OTHER_SHA}}
        env = self._base_env()
        env["INPUT_PR_NUMBER"] = "55"
        env["INPUT_COMMIT_SHA"] = SAMPLE_SHA

        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            rc = run_governance_gate.run_gate(env=env)

        self.assertEqual(rc, 0)
        mock_subproc.assert_not_called()
        self.assertIn("::notice title=Superseded Commit::", stdout.getvalue())

        # Case 2: PR head changes while pr_validator.py is running.
        mock_api.reset_mock()
        mock_api.side_effect = [
            {"number": 55, "head": {"sha": SAMPLE_SHA}},
            {"number": 55, "head": {"sha": OTHER_SHA}},
        ]
        mock_subproc.return_value = subprocess.CompletedProcess(["uv"], 0)

        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            rc = run_governance_gate.run_gate(env=env)

        self.assertEqual(rc, 0)
        mock_subproc.assert_called_once()
        # Only the 2 GET /pulls/55 calls occurred; POST /statuses was skipped.
        self.assertEqual(mock_api.call_count, 2)
        self.assertIn("changed to", stdout.getvalue())

    @patch.object(run_governance_gate, "_github_api_json")
    @patch.object(subprocess, "run")
    def test_validator_crash_without_summary_posts_error_status_and_returns_nonzero(
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

            mock_subproc.return_value = subprocess.CompletedProcess(["uv"], 2)
            mock_api.side_effect = [
                {"number": 12, "head": {"sha": SAMPLE_SHA}},
                {"number": 12, "head": {"sha": SAMPLE_SHA}},
                {},
            ]
            env = self._base_env(step_summary=str(step_summary))
            env["EVENT_WORKFLOW_RUN_PR_NUMBER"] = "12"
            env["EVENT_WORKFLOW_RUN_HEAD_SHA"] = SAMPLE_SHA

            stderr = io.StringIO()
            with patch("sys.stderr", stderr):
                rc = run_governance_gate.run_gate(
                    env=env,
                    validator_script=validator_script,
                    summary_file=summary_file,
                )

            self.assertEqual(rc, 2)
            self.assertIn("Validator Execution Failed", stderr.getvalue())
            self.assertIn(
                "ERROR: pr_validator.py exited with code 2 without producing summary.txt.",
                step_summary.read_text(encoding="utf-8"),
            )
            post_call = mock_api.call_args_list[2]
            self.assertEqual(post_call.args[0], "POST")
            self.assertEqual(post_call.kwargs["payload"]["state"], "error")
            self.assertEqual(
                post_call.kwargs["payload"]["description"],
                "Governance validator execution failed",
            )

    @patch.object(run_governance_gate, "_github_api_json")
    @patch.object(subprocess, "run")
    def test_validator_runtime_exception_with_error_summary_posts_error_and_writes_job_summary(
        self,
        mock_subproc: unittest.mock.MagicMock,
        mock_api: unittest.mock.MagicMock,
    ) -> None:
        """Runtime exceptions writing ERROR: to summary.txt post error status and write job summary."""
        for validator_rc in (2, 1):
            with self.subTest(validator_rc=validator_rc):
                with tempfile.TemporaryDirectory() as tmpdir:
                    tmp = Path(tmpdir)
                    summary_file = tmp / "summary.txt"
                    step_summary = tmp / "step_summary.md"
                    validator_script = tmp / "pr_validator.py"
                    validator_script.write_text("# stub\n", encoding="utf-8")

                    def fake_validator(
                        cmd: list[str],
                        check: bool = False,
                        rc: int = validator_rc,
                        out: Path = summary_file,
                    ) -> subprocess.CompletedProcess[str]:
                        out.write_text(
                            "ERROR: Failed to fetch organization 'Universal-Commerce-Protocol': 401 Bad credentials",
                            encoding="utf-8",
                        )
                        return subprocess.CompletedProcess(cmd, rc)

                    mock_subproc.reset_mock()
                    mock_api.reset_mock()
                    mock_subproc.side_effect = fake_validator
                    mock_api.side_effect = [
                        {"number": 84, "head": {"sha": SAMPLE_SHA}},
                        {"number": 84, "head": {"sha": SAMPLE_SHA}},
                        {},
                    ]

                    env = self._base_env(step_summary=str(step_summary))
                    env["INPUT_PR_NUMBER"] = "84"
                    env["INPUT_COMMIT_SHA"] = SAMPLE_SHA

                    stderr = io.StringIO()
                    with patch("sys.stderr", stderr):
                        rc = run_governance_gate.run_gate(
                            env=env,
                            validator_script=validator_script,
                            summary_file=summary_file,
                        )

                    self.assertEqual(rc, validator_rc)
                    self.assertIn(
                        "::error title=Validator Execution Failed::ERROR: Failed to fetch organization",
                        stderr.getvalue(),
                    )
                    self.assertEqual(
                        step_summary.read_text(encoding="utf-8"),
                        "ERROR: Failed to fetch organization 'Universal-Commerce-Protocol': 401 Bad credentials\n",
                    )
                    post_call = mock_api.call_args_list[2]
                    self.assertEqual(post_call.args[0], "POST")
                    self.assertEqual(post_call.kwargs["payload"]["state"], "error")
                    self.assertEqual(
                        post_call.kwargs["payload"]["description"],
                        "Governance validator execution failed",
                    )

    @patch.object(urllib.request, "urlopen")
    def test_github_api_json_includes_http_error_body(
        self,
        mock_urlopen: unittest.mock.MagicMock,
    ) -> None:
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="https://api.github.com/repos/o/r/statuses/" + SAMPLE_SHA,
            code=403,
            msg="Forbidden",
            hdrs=email.message.Message(),
            fp=io.BytesIO(b'{"message":"Resource not accessible by integration"}'),
        )
        with self.assertRaises(run_governance_gate.GitHubApiError) as ctx:
            run_governance_gate._github_api_json(
                "POST",
                "https://api.github.com/repos/o/r/statuses/" + SAMPLE_SHA,
                "bad-token",
                payload={"state": "success"},
            )
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Resource not accessible by integration", str(ctx.exception))

    @patch.object(run_governance_gate, "_github_api_json")
    def test_unresolvable_pr_returns_nonzero(
        self,
        mock_api: unittest.mock.MagicMock,
    ) -> None:
        mock_api.side_effect = [
            [],
            [],
            {"items": []},
        ]
        env = self._base_env()
        env["EVENT_WORKFLOW_RUN_HEAD_SHA"] = SAMPLE_SHA
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            rc = run_governance_gate.run_gate(env=env)
        self.assertEqual(rc, 1)
        self.assertIn("PR number could not be resolved", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
