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

"""Unit tests for the Click CLI entry point."""

import os
import sys
import unittest
from unittest.mock import Mock, patch
import github
from click.testing import CliRunner

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts"))
)

import triage_cli


class TestTriageCLIValidation(unittest.TestCase):
    """Tests for CLI argument validation and early exits."""

    def setUp(self):
        self.runner = CliRunner()

    def test_main_fails_validation_when_org_is_missing(self):
        """Test that the CLI fails validation when the --org option is missing."""
        result = self.runner.invoke(
            triage_cli.main, ["--token", "my-token", "--repos", "repo-a"]
        )
        self.assertEqual(result.exit_code, 2)
        self.assertIn("Error: Missing option '--org'", result.output)

    @patch.dict(os.environ, {}, clear=True)
    def test_main_fails_validation_when_token_and_env_var_are_missing(self):
        """Test that the CLI fails validation when both --token and ORG_TRIAGE_TOKEN env var are missing."""
        result = self.runner.invoke(
            triage_cli.main, ["--org", "my-org", "--repos", "repo-a"]
        )
        self.assertEqual(result.exit_code, 2)
        self.assertIn("Error: Missing option '--token'", result.output)

    def test_main_fails_validation_when_repos_option_is_missing(self):
        """Test that the CLI fails validation when the --repos option is missing."""
        result = self.runner.invoke(
            triage_cli.main, ["--org", "my-org", "--token", "my-token"]
        )
        self.assertEqual(result.exit_code, 2)
        self.assertIn("Error: Missing option '--repos'", result.output)

    @patch("triage_cli.log_error")
    def test_main_fails_validation_when_repos_empty(self, mock_log_error):
        """Test that the CLI fails validation if --repos is empty or whitespace only."""
        result = self.runner.invoke(
            triage_cli.main,
            ["--org", "my-org", "--token", "my-token", "--repos", " , "],
        )
        self.assertEqual(result.exit_code, 1)
        mock_log_error.assert_called_once_with(
            "Error: No repositories specified in --repos."
        )

    @patch("triage_cli.log_error")
    def test_main_fails_validation_when_multiple_repos_with_pr(self, mock_log_error):
        """Test that the CLI fails validation when multiple repositories are specified with --pr."""
        result = self.runner.invoke(
            triage_cli.main,
            [
                "--org",
                "my-org",
                "--token",
                "my-token",
                "--repos",
                "repo-a,repo-b",
                "--pr",
                "123",
            ],
        )
        self.assertEqual(result.exit_code, 1)
        mock_log_error.assert_called_once_with(
            "Error: Exactly one repository must be specified in --repos when --pr is provided."
        )


class TestTriageCLIExecution(unittest.TestCase):
    """Tests for the execution flow and orchestration of the triage CLI."""

    def setUp(self):
        self.runner = CliRunner()

    @patch("triage_cli.TriageLabeler")
    @patch("triage_cli.github.Github")
    def test_main_executes_bulk_triage_successfully(
        self, mock_github, mock_labeler_class
    ):
        """Test that the CLI successfully orchestrates bulk triage across multiple repositories."""
        mock_label = Mock()
        mock_labeler_class.return_value = mock_label

        mock_repo_a = Mock()
        mock_repo_a.name = "repo-a"
        mock_repo_b = Mock()
        mock_repo_b.name = "repo-b"
        mock_github.return_value.get_repo.side_effect = (
            lambda name: mock_repo_a if "repo-a" in name else mock_repo_b
        )

        result = self.runner.invoke(
            triage_cli.main,
            [
                "--org",
                "my-org",
                "--token",
                "my-token",
                "--repos",
                "repo-a, repo-b",
            ],
        )

        self.assertEqual(result.exit_code, 0)
        # TriageLabeler should be instantiated for each repo, passing the pre-fetched repo
        self.assertEqual(mock_labeler_class.call_count, 2)
        mock_labeler_class.assert_any_call(
            mock_github.return_value, mock_repo_a, dry_run=True
        )
        mock_labeler_class.assert_any_call(
            mock_github.return_value, mock_repo_b, dry_run=True
        )
        # triage_all_outstanding() should be called on both
        self.assertEqual(mock_label.triage_all_outstanding.call_count, 2)

    @patch("triage_cli.TriageLabeler")
    @patch("triage_cli.github.Github")
    @patch("triage_cli.log_error")
    def test_main_exits_with_error_on_partial_bulk_triage_failure(
        self, mock_log_error, mock_github, mock_labeler_class
    ):
        """Test that the CLI exits with code 1 if triage fails on one of the repositories."""
        mock_labeler_a = Mock()
        mock_labeler_b = Mock()
        # Make repo-b fail during triage
        mock_labeler_b.triage_all_outstanding.side_effect = RuntimeError(
            "Access Denied"
        )

        mock_repo_a = Mock()
        mock_repo_a.name = "repo-a"
        mock_repo_b = Mock()
        mock_repo_b.name = "repo-b"

        mock_github.return_value.get_repo.side_effect = (
            lambda name: mock_repo_a if "repo-a" in name else mock_repo_b
        )

        mock_labeler_class.side_effect = lambda client, repo, dry_run: (
            mock_labeler_a if repo.name == "repo-a" else mock_labeler_b
        )

        result = self.runner.invoke(
            triage_cli.main,
            [
                "--org",
                "my-org",
                "--token",
                "my-token",
                "--repos",
                "repo-a, repo-b",
            ],
        )

        # Exit code should be 1 because repo-b failed
        self.assertEqual(result.exit_code, 1)
        # Both should have been processed
        mock_labeler_a.triage_all_outstanding.assert_called_once()
        mock_labeler_b.triage_all_outstanding.assert_called_once()
        # Error should be logged for repo-b
        mock_log_error.assert_any_call(
            "Error processing repository %s: %s",
            "repo-b",
            mock_labeler_b.triage_all_outstanding.side_effect,
        )

    @patch("triage_cli.TriageLabeler")
    @patch("triage_cli.github.Github")
    @patch("triage_cli.log_error")
    def test_main_aborts_immediately_on_repository_verification_failure(
        self, mock_log_error, mock_github, mock_labeler_class
    ):
        """Test that the CLI aborts and exits with code 1 if any repository fails the initial access verification."""

        # Make get_repo fail for repo-b during verification
        def get_repo_side_effect(full_name):
            if "repo-b" in full_name:
                raise github.GithubException(
                    status=404, data={"message": "Not Found"}, headers={}
                )
            return Mock()

        mock_github.return_value.get_repo.side_effect = get_repo_side_effect

        result = self.runner.invoke(
            triage_cli.main,
            [
                "--org",
                "my-org",
                "--token",
                "my-token",
                "--repos",
                "repo-a, repo-b",
            ],
        )

        # Exit code should be 1 because repo-b failed verification
        self.assertEqual(result.exit_code, 1)
        # TriageLabeler should NOT be instantiated at all because we abort
        mock_labeler_class.assert_not_called()
        # Error should be logged
        mock_log_error.assert_any_call(
            "Aborting: One or more repositories are inaccessible: %s",
            "repo-b",
        )

    @patch("triage_cli.TriageLabeler")
    @patch("triage_cli.github.Github")
    def test_main_executes_single_pr_triage_successfully(
        self, mock_github, mock_labeler_class
    ):
        """Test that the CLI successfully orchestrates single PR triage."""
        mock_labeler = Mock()
        mock_labeler_class.return_value = mock_labeler

        mock_repo = Mock()
        mock_github.return_value.get_repo.return_value = mock_repo

        result = self.runner.invoke(
            triage_cli.main,
            [
                "--org",
                "my-org",
                "--token",
                "my-token",
                "--repos",
                "repo-a",
                "--pr",
                "123",
            ],
        )

        self.assertEqual(result.exit_code, 0)
        mock_github.return_value.get_repo.assert_called_once_with("my-org/repo-a")
        mock_labeler_class.assert_called_once_with(
            mock_github.return_value, mock_repo, dry_run=True
        )
        mock_labeler.triage.assert_called_once_with(123)

    @patch("triage_cli.TriageLabeler")
    @patch("triage_cli.github.Github")
    def test_main_propagates_apply_flag_to_triage_labeler(
        self, mock_github, mock_labeler_class
    ):
        """Test that the --apply flag is correctly propagated to the TriageLabeler instance."""
        mock_repo = Mock()
        mock_github.return_value.get_repo.return_value = mock_repo

        result = self.runner.invoke(
            triage_cli.main,
            [
                "--org",
                "my-org",
                "--token",
                "my-token",
                "--repos",
                "repo-a",
                "--apply",
            ],
        )

        self.assertEqual(result.exit_code, 0)
        mock_labeler_class.assert_called_once_with(
            mock_github.return_value,
            mock_repo,
            dry_run=False,
        )


if __name__ == "__main__":
    unittest.main()
