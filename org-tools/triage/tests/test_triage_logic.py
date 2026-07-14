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

"""Unit tests for the TriageLabeler class."""

import os
import sys
import unittest
from unittest.mock import MagicMock, Mock, call, patch
from github import GithubException
import github

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts"))
)

from triage_logic import TriageLabeler


class TestTriageLabelerInitialization(unittest.TestCase):
    """Tests for TriageLabeler initialization."""

    def test_init(self):
        mock_client = Mock()
        mock_repo = Mock()
        mock_repo.full_name = "mock-org/mock-repo"

        labeler = TriageLabeler(mock_client, mock_repo, dry_run=False)

        self.assertEqual(labeler.client, mock_client)
        self.assertEqual(labeler.repo, mock_repo)
        self.assertFalse(labeler.dry_run)


class TestTriageLabelerPRRules(unittest.TestCase):
    """Tests for PR eligibility rules evaluation in TriageLabeler."""

    def setUp(self):
        self.mock_client = Mock()
        self.mock_repo = Mock()
        self.mock_repo.full_name = "mock-org/mock-repo"
        self.labeler = TriageLabeler(self.mock_client, self.mock_repo, dry_run=False)

    def test_eligible_pr_should_be_triaged(self):
        """Test that an open, non-draft PR without triage or skip labels returns True."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False
        pr.labels = []
        pr.requested_reviewers = []
        pr.requested_teams = []
        pr.get_reviews.return_value.totalCount = 0
        self.assertTrue(self.labeler._is_eligible_for_triage(pr))

    def test_closed_pr_should_not_be_triaged(self):
        """Test that a closed PR returns False."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "closed"
        pr.draft = False
        self.assertFalse(self.labeler._is_eligible_for_triage(pr))

    def test_draft_pr_should_not_be_triaged(self):
        """Test that a draft PR returns False."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = True
        self.assertFalse(self.labeler._is_eligible_for_triage(pr))

    def test_pr_with_triage_label_should_not_be_triaged(self):
        """Test that a PR already carrying the triage label returns False."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False
        pr.requested_reviewers = []
        pr.requested_teams = []
        pr.get_reviews.return_value.totalCount = 0

        mock_label = Mock()
        mock_label.name = "status:needs-triage"
        pr.labels = [mock_label]

        self.assertFalse(self.labeler._is_eligible_for_triage(pr))

    def test_pr_with_backlog_label_should_not_be_triaged(self):
        """Test that a PR carrying the backlog label returns False."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False
        pr.requested_reviewers = []
        pr.requested_teams = []
        pr.get_reviews.return_value.totalCount = 0

        mock_label = Mock()
        mock_label.name = "status:backlog"
        pr.labels = [mock_label]

        self.assertFalse(self.labeler._is_eligible_for_triage(pr))

    def test_pr_with_stale_label_should_not_be_triaged(self):
        """Test that a PR carrying the stale label returns False."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False
        pr.requested_reviewers = []
        pr.requested_teams = []
        pr.get_reviews.return_value.totalCount = 0

        mock_label = Mock()
        mock_label.name = "status:stale"
        pr.labels = [mock_label]

        self.assertFalse(self.labeler._is_eligible_for_triage(pr))

    def test_pr_with_under_review_label_should_not_be_triaged(self):
        """Test that a PR carrying the under-review label returns False."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False
        pr.requested_reviewers = []
        pr.requested_teams = []
        pr.get_reviews.return_value.totalCount = 0

        mock_label = Mock()
        mock_label.name = "status:under-review"
        pr.labels = [mock_label]

        self.assertFalse(self.labeler._is_eligible_for_triage(pr))

    def test_pr_with_generic_label_should_not_be_triaged(self):
        """Test that a PR carrying any generic label returns False."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False
        pr.requested_reviewers = []
        pr.requested_teams = []
        pr.get_reviews.return_value.totalCount = 0

        mock_label = Mock()
        mock_label.name = "some-random-label"
        pr.labels = [mock_label]

        self.assertFalse(self.labeler._is_eligible_for_triage(pr))


class TestTriageLabelerLabelApplication(unittest.TestCase):
    """Tests for applying the 'status:needs-triage' label to PRs on GitHub."""

    def setUp(self):
        self.mock_client = Mock()
        self.mock_repo = Mock()
        self.mock_repo.full_name = "mock-org/mock-repo"
        self.mock_issue = Mock(spec=github.PullRequest.PullRequest)
        self.mock_issue.number = 1

    def test_apply_label_adds_label_when_dry_run_is_false(self):
        """Test that the triage label is added to the PR when dry_run is False."""
        labeler = TriageLabeler(self.mock_client, self.mock_repo, dry_run=False)
        labeler._apply_label(self.mock_issue)
        self.mock_issue.add_to_labels.assert_called_once_with("status:needs-triage")

    def test_apply_label_does_not_add_label_when_dry_run_is_true(self):
        """Test that the triage label is not added to the PR when dry_run is True."""
        labeler = TriageLabeler(self.mock_client, self.mock_repo, dry_run=True)
        labeler._apply_label(self.mock_issue)
        self.mock_issue.add_to_labels.assert_not_called()

    @patch("triage_logic.log_error")
    def test_apply_label_logs_error_on_api_failure(self, mock_log_error):
        """Test that any exception during label application is caught and logged as an error."""
        labeler = TriageLabeler(self.mock_client, self.mock_repo, dry_run=False)
        self.mock_issue.add_to_labels.side_effect = Exception("API Error")
        labeler._apply_label(self.mock_issue)
        self.mock_issue.add_to_labels.assert_called_once()
        mock_log_error.assert_called_once_with(
            "Error applying label to PR #%s in %s: %s",
            1,
            "mock-org/mock-repo",
            self.mock_issue.add_to_labels.side_effect,
        )


class TestTriageLabelerBulkExecution(unittest.TestCase):
    """Tests for the bulk triage orchestration logic."""

    def setUp(self):
        self.mock_client = Mock()
        self.mock_repo = Mock()
        self.mock_repo.full_name = "mock-org/mock-repo"
        self.labeler = TriageLabeler(self.mock_client, self.mock_repo, dry_run=False)

    @patch.object(TriageLabeler, "_triage_pull")
    def test_bulk_triage_processes_prs_in_descending_order(self, mock_triage_pull):
        """Test that bulk triage processes PRs sorted by creation date in descending order."""
        mock_pr_item1 = Mock()
        mock_pr_item1.number = 1
        mock_pr_item1.title = "PR 1"
        mock_pr_item2 = Mock()
        mock_pr_item2.number = 2
        mock_pr_item2.title = "PR 2"

        mock_prs = MagicMock()
        mock_prs.totalCount = 2
        mock_prs.__iter__.return_value = [mock_pr_item2, mock_pr_item1]
        self.mock_client.search_issues.return_value = mock_prs

        mock_pull1 = Mock(spec=github.PullRequest.PullRequest)
        mock_pull1.number = 1
        mock_pull2 = Mock(spec=github.PullRequest.PullRequest)
        mock_pull2.number = 2

        self.mock_repo.get_pull.side_effect = (
            lambda num: mock_pull1 if num == 1 else mock_pull2
        )

        self.labeler.triage_all_outstanding()

        # Verify descending sorting (2 then 1)
        mock_triage_pull.assert_has_calls([call(mock_pull2), call(mock_pull1)])

    @patch.object(TriageLabeler, "_triage_pull")
    @patch("triage_logic.log_error")
    def test_bulk_triage_isolates_individual_pr_errors(
        self, mock_log_error, mock_triage_pull
    ):
        """Test that a failure processing a single PR does not abort the entire bulk triage process."""
        mock_pr_item1 = Mock()
        mock_pr_item1.number = 1
        mock_pr_item1.title = "PR 1"
        mock_pr_item2 = Mock()
        mock_pr_item2.number = 2
        mock_pr_item2.title = "PR 2"

        mock_prs = MagicMock()
        mock_prs.totalCount = 2
        mock_prs.__iter__.return_value = [mock_pr_item2, mock_pr_item1]
        self.mock_client.search_issues.return_value = mock_prs

        mock_pull1 = Mock(spec=github.PullRequest.PullRequest)
        mock_pull1.number = 1

        # get_pull fails for PR #2, but succeeds for PR #1
        def get_pull_side_effect(num):
            if num == 1:
                return mock_pull1
            raise Exception("Fetch error")

        self.mock_repo.get_pull.side_effect = get_pull_side_effect

        self.labeler.triage_all_outstanding()

        # PR #2 should fail and log error
        mock_log_error.assert_called_once()
        # PR #1 should still be processed
        mock_triage_pull.assert_called_once_with(mock_pull1)

    def test_bulk_triage_verifies_search_query_structure(self):
        """Test that the constructed search query contains all required filters."""
        self.mock_client.search_issues.return_value = MagicMock(totalCount=0)

        self.labeler.triage_all_outstanding()

        self.mock_client.search_issues.assert_called_once()
        called_args, _ = self.mock_client.search_issues.call_args
        query = called_args[0]

        self.assertIn("is:pr", query)
        self.assertIn("is:open", query)
        self.assertIn("-is:draft", query)
        self.assertIn("no:label", query)
        self.assertIn("repo:mock-org/mock-repo", query)

    def test_bulk_triage_raises_runtime_error_on_search_failure(self):
        """Test that a failure during the Search API call raises a RuntimeError."""
        self.mock_client.search_issues.side_effect = Exception("Search failed")

        with self.assertRaises(RuntimeError) as ctx:
            self.labeler.triage_all_outstanding()
        self.assertIn("Failed to search PRs for mock-org/mock-repo", str(ctx.exception))


class TestTriageLabelerSingleExecution(unittest.TestCase):
    """Tests for single PR triage execution and error handling."""

    def setUp(self):
        self.mock_client = Mock()
        self.mock_repo = Mock()
        self.mock_repo.full_name = "mock-org/mock-repo"
        self.labeler = TriageLabeler(self.mock_client, self.mock_repo, dry_run=False)

    @patch.object(TriageLabeler, "_triage_pull")
    def test_single_pr_triage_success(self, mock_triage_pull):
        """Test that triaging a single PR successfully fetches and triages the PR."""
        mock_pull = Mock(spec=github.PullRequest.PullRequest)
        mock_pull.number = 123
        self.mock_repo.get_pull.return_value = mock_pull

        self.labeler.triage(123)

        self.mock_repo.get_pull.assert_called_once_with(123)
        mock_triage_pull.assert_called_once_with(mock_pull)

    def test_single_pr_triage_raises_runtime_error_when_not_found(self):
        """Test that a 404 GithubException when fetching a single PR raises a RuntimeError."""
        self.mock_repo.get_pull.side_effect = GithubException(
            status=404, data={"message": "Not Found"}, headers={}
        )

        with self.assertRaises(RuntimeError) as ctx:
            self.labeler.triage(123)
        self.assertIn(
            "PR #123 not found or access denied in mock-org/mock-repo",
            str(ctx.exception),
        )

    def test_single_pr_triage_raises_runtime_error_on_unexpected_error(self):
        """Test that an unexpected exception when fetching a single PR raises a RuntimeError."""
        self.mock_repo.get_pull.side_effect = Exception("Unexpected network error")

        with self.assertRaises(RuntimeError) as ctx:
            self.labeler.triage(123)
        self.assertIn(
            "Failed to fetch PR #123 in mock-org/mock-repo", str(ctx.exception)
        )


if __name__ == "__main__":
    unittest.main()
