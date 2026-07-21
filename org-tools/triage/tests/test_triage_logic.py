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
from datetime import datetime, timezone, timedelta
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
        self.mock_issue.labels = []

    def test_apply_label_adds_label_when_dry_run_is_false(self):
        """Test that the triage label is added to the PR when dry_run is False."""
        labeler = TriageLabeler(self.mock_client, self.mock_repo, dry_run=False)
        labeler._apply_label(self.mock_issue, "status:needs-triage")
        self.mock_issue.add_to_labels.assert_called_once_with("status:needs-triage")

    def test_apply_label_does_not_add_label_when_dry_run_is_true(self):
        """Test that the triage label is not added to the PR when dry_run is True."""
        labeler = TriageLabeler(self.mock_client, self.mock_repo, dry_run=True)
        labeler._apply_label(self.mock_issue, "status:needs-triage")
        self.mock_issue.add_to_labels.assert_not_called()

    @patch("triage_logic.log_error")
    def test_apply_label_logs_error_on_api_failure(self, mock_log_error):
        """Test that any exception during label application is caught and logged as an error."""
        labeler = TriageLabeler(self.mock_client, self.mock_repo, dry_run=False)
        self.mock_issue.add_to_labels.side_effect = Exception("API Error")
        labeler._apply_label(self.mock_issue, "status:needs-triage")
        self.mock_issue.add_to_labels.assert_called_once()
        mock_log_error.assert_called_once_with(
            "Error applying label %s to PR #%s in %s: %s",
            "status:needs-triage",
            1,
            "mock-org/mock-repo",
            self.mock_issue.add_to_labels.side_effect,
        )

    def test_apply_label_removes_other_status_labels_when_dry_run_is_false(self):
        """Test that other mutually exclusive status labels are removed when dry_run is False."""
        labeler = TriageLabeler(self.mock_client, self.mock_repo, dry_run=False)

        mock_label_blocked = Mock()
        mock_label_blocked.name = "status:blocked"
        mock_label_other = Mock()
        mock_label_other.name = "some-other-label"

        self.mock_issue.labels = [mock_label_blocked, mock_label_other]

        labeler._apply_label(self.mock_issue, "status:stale")

        # Verify it tried to remove "status:blocked"
        self.mock_issue.remove_from_labels.assert_called_once_with("status:blocked")
        # Verify it added "status:stale"
        self.mock_issue.add_to_labels.assert_called_once_with("status:stale")

    def test_apply_label_does_not_remove_other_status_labels_when_dry_run_is_true(self):
        """Test that status labels are NOT removed when dry_run is True."""
        labeler = TriageLabeler(self.mock_client, self.mock_repo, dry_run=True)

        mock_label_blocked = Mock()
        mock_label_blocked.name = "status:blocked"
        self.mock_issue.labels = [mock_label_blocked]

        labeler._apply_label(self.mock_issue, "status:stale")

        self.mock_issue.remove_from_labels.assert_not_called()
        self.mock_issue.add_to_labels.assert_not_called()

    def test_apply_label_ignores_non_status_labels(self):
        """Test that non-status labels are not touched during label application."""
        labeler = TriageLabeler(self.mock_client, self.mock_repo, dry_run=False)

        mock_label_other = Mock()
        mock_label_other.name = "some-other-label"
        self.mock_issue.labels = [mock_label_other]

        labeler._apply_label(self.mock_issue, "status:stale")

        self.mock_issue.remove_from_labels.assert_not_called()
        self.mock_issue.add_to_labels.assert_called_once_with("status:stale")


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
        """Test that the constructed search queries contain all required filters."""
        self.mock_client.search_issues.return_value = MagicMock(totalCount=0)

        self.labeler.triage_all_outstanding()

        self.assertEqual(self.mock_client.search_issues.call_count, 5)
        calls = self.mock_client.search_issues.call_args_list

        query1 = calls[0][0][0]
        self.assertIn("is:pr", query1)
        self.assertIn("is:open", query1)
        self.assertIn("-is:draft", query1)
        self.assertIn("no:label", query1)
        self.assertIn("repo:mock-org/mock-repo", query1)

        query2 = calls[1][0][0]
        self.assertIn("is:pr", query2)
        self.assertIn("is:open", query2)
        self.assertIn("-is:draft", query2)
        self.assertIn('label:"status:blocked"', query2)
        self.assertIn("repo:mock-org/mock-repo", query2)

        query3 = calls[2][0][0]
        self.assertIn("is:pr", query3)
        self.assertIn("is:open", query3)
        self.assertIn("-is:draft", query3)
        self.assertIn('label:"status:under-review"', query3)
        self.assertIn("repo:mock-org/mock-repo", query3)

        query4 = calls[3][0][0]
        self.assertIn("is:pr", query4)
        self.assertIn("is:open", query4)
        self.assertIn("-is:draft", query4)
        self.assertIn('label:"status:stale"', query4)
        self.assertIn("repo:mock-org/mock-repo", query4)

        query5 = calls[4][0][0]
        self.assertIn("is:pr", query5)
        self.assertIn("is:open", query5)
        self.assertIn("-is:draft", query5)
        self.assertIn('label:"status:stale-review"', query5)
        self.assertIn("repo:mock-org/mock-repo", query5)

    def test_bulk_triage_raises_runtime_error_on_search_failure(self):
        """Test that a failure during the Search API call raises a RuntimeError."""
        self.mock_client.search_issues.side_effect = Exception("Search failed")

        with self.assertRaises(RuntimeError) as ctx:
            self.labeler.triage_all_outstanding()
        self.assertIn(
            "Failed to search PRs needing triage for mock-org/mock-repo",
            str(ctx.exception),
        )


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


class TestTriageLabelerBlockedStaleRules(unittest.TestCase):
    """Tests for blocked-stale eligibility rules in TriageLabeler."""

    def setUp(self):
        self.mock_client = Mock()
        self.mock_repo = Mock()
        self.mock_repo.full_name = "mock-org/mock-repo"
        self.labeler = TriageLabeler(self.mock_client, self.mock_repo, dry_run=False)

    def test_non_blocked_pr_should_not_be_stale(self):
        """PR without status:blocked label should not be eligible."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False
        pr.labels = []
        self.assertFalse(self.labeler._is_eligible_for_blocked_stale(pr))

    def test_blocked_pr_less_than_21_days_should_not_be_stale(self):
        """PR blocked for less than 21 days should not be eligible."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False

        mock_label = Mock()
        mock_label.name = "status:blocked"
        pr.labels = [mock_label]

        # Mock event: labeled 10 days ago
        event = Mock()
        event.event = "labeled"
        event.label.name = "status:blocked"
        event.created_at = datetime.now(timezone.utc) - timedelta(days=10)
        pr.get_issue_events.return_value = [event]

        # Mock no activity
        pr.get_issue_comments.return_value = []
        pr.get_review_comments.return_value = []
        pr.get_reviews.return_value = []

        self.assertFalse(self.labeler._is_eligible_for_blocked_stale(pr))

    def test_blocked_pr_more_than_21_days_should_be_stale(self):
        """PR blocked for more than 21 days should be eligible."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False

        mock_label = Mock()
        mock_label.name = "status:blocked"
        pr.labels = [mock_label]

        # Mock event: labeled 22 days ago
        event = Mock()
        event.event = "labeled"
        event.label.name = "status:blocked"
        event.created_at = datetime.now(timezone.utc) - timedelta(days=22)
        pr.get_issue_events.return_value = [event]

        # Mock no activity
        pr.get_issue_comments.return_value = []
        pr.get_review_comments.return_value = []
        pr.get_reviews.return_value = []

        self.assertTrue(self.labeler._is_eligible_for_blocked_stale(pr))

    def test_blocked_pr_with_recent_activity_should_not_be_stale(self):
        """PR with activity in the last 21 days should not be eligible, even if labeled long ago."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False

        mock_label = Mock()
        mock_label.name = "status:blocked"
        pr.labels = [mock_label]

        # Mock event: labeled 25 days ago
        event = Mock()
        event.event = "labeled"
        event.label.name = "status:blocked"
        event.created_at = datetime.now(timezone.utc) - timedelta(days=25)
        pr.get_issue_events.return_value = [event]

        # Mock recent comment (10 days ago)
        comment = Mock()
        comment.created_at = datetime.now(timezone.utc) - timedelta(days=10)
        pr.get_issue_comments.return_value = [comment]
        pr.get_review_comments.return_value = []
        pr.get_reviews.return_value = []

        self.assertFalse(self.labeler._is_eligible_for_blocked_stale(pr))

    def test_blocked_pr_with_old_activity_should_be_stale(self):
        """PR with activity > 21 days ago should be eligible if labeled long ago."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False

        mock_label = Mock()
        mock_label.name = "status:blocked"
        pr.labels = [mock_label]

        # Mock event: labeled 30 days ago
        event = Mock()
        event.event = "labeled"
        event.label.name = "status:blocked"
        event.created_at = datetime.now(timezone.utc) - timedelta(days=30)
        pr.get_issue_events.return_value = [event]

        # Mock old comment (25 days ago)
        comment = Mock()
        comment.created_at = datetime.now(timezone.utc) - timedelta(days=25)
        pr.get_issue_comments.return_value = [comment]
        pr.get_review_comments.return_value = []
        pr.get_reviews.return_value = []

        self.assertTrue(self.labeler._is_eligible_for_blocked_stale(pr))

    def test_already_stale_blocked_pr_should_not_be_stale_again(self):
        """PR that is already marked stale should not be eligible."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False

        mock_blocked = Mock()
        mock_blocked.name = "status:blocked"
        mock_stale = Mock()
        mock_stale.name = "status:stale"
        pr.labels = [mock_blocked, mock_stale]

        self.assertFalse(self.labeler._is_eligible_for_blocked_stale(pr))

    def test_closed_blocked_pr_should_not_be_stale(self):
        """Closed PR should not be eligible."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "closed"
        pr.draft = False
        mock_label = Mock()
        mock_label.name = "status:blocked"
        pr.labels = [mock_label]
        self.assertFalse(self.labeler._is_eligible_for_blocked_stale(pr))

    def test_draft_blocked_pr_should_not_be_stale(self):
        """Draft PR should not be eligible."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = True
        mock_label = Mock()
        mock_label.name = "status:blocked"
        pr.labels = [mock_label]
        self.assertFalse(self.labeler._is_eligible_for_blocked_stale(pr))


class TestTriageLabelerStaleReviewRules(unittest.TestCase):
    """Tests for stale-review eligibility rules in TriageLabeler."""

    def setUp(self):
        self.mock_client = Mock()
        self.mock_repo = Mock()
        self.mock_repo.full_name = "mock-org/mock-repo"
        self.labeler = TriageLabeler(self.mock_client, self.mock_repo, dry_run=False)

    def test_non_under_review_pr_should_not_be_stale_review(self):
        """PR without status:under-review label should not be eligible."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False
        pr.labels = []
        self.assertFalse(self.labeler._is_eligible_for_stale_review(pr))

    def test_under_review_pr_with_recent_label_and_no_activity_should_not_be_stale(
        self,
    ):
        """PR labeled under-review recently with no activity should not be eligible."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False

        mock_label = Mock()
        mock_label.name = "status:under-review"
        pr.labels = [mock_label]

        # Mock event: labeled 10 days ago
        event = Mock()
        event.event = "labeled"
        event.label.name = "status:under-review"
        event.created_at = datetime.now(timezone.utc) - timedelta(days=10)
        pr.get_issue_events.return_value = [event]

        # Mock no activity
        pr.get_issue_comments.return_value = []
        pr.get_review_comments.return_value = []
        pr.get_reviews.return_value = []

        self.assertFalse(self.labeler._is_eligible_for_stale_review(pr))

    def test_under_review_pr_labeled_long_ago_with_no_activity_should_be_stale(self):
        """PR labeled under-review > 21 days ago with no activity should be eligible."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False

        mock_label = Mock()
        mock_label.name = "status:under-review"
        pr.labels = [mock_label]

        # Mock event: labeled 22 days ago
        event = Mock()
        event.event = "labeled"
        event.label.name = "status:under-review"
        event.created_at = datetime.now(timezone.utc) - timedelta(days=22)
        pr.get_issue_events.return_value = [event]

        # Mock no activity
        pr.get_issue_comments.return_value = []
        pr.get_review_comments.return_value = []
        pr.get_reviews.return_value = []

        self.assertTrue(self.labeler._is_eligible_for_stale_review(pr))

    def test_under_review_pr_with_recent_activity_should_not_be_stale(self):
        """PR with activity in the last 21 days should not be eligible, even if labeled long ago."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False

        mock_label = Mock()
        mock_label.name = "status:under-review"
        pr.labels = [mock_label]

        # Mock event: labeled 25 days ago
        event = Mock()
        event.event = "labeled"
        event.label.name = "status:under-review"
        event.created_at = datetime.now(timezone.utc) - timedelta(days=25)
        pr.get_issue_events.return_value = [event]

        # Mock recent comment (10 days ago)
        comment = Mock()
        comment.created_at = datetime.now(timezone.utc) - timedelta(days=10)
        pr.get_issue_comments.return_value = [comment]
        pr.get_review_comments.return_value = []
        pr.get_reviews.return_value = []

        self.assertFalse(self.labeler._is_eligible_for_stale_review(pr))

    def test_under_review_pr_with_old_activity_should_be_stale(self):
        """PR with activity > 21 days ago should be eligible if labeled long ago."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False

        mock_label = Mock()
        mock_label.name = "status:under-review"
        pr.labels = [mock_label]

        # Mock event: labeled 30 days ago
        event = Mock()
        event.event = "labeled"
        event.label.name = "status:under-review"
        event.created_at = datetime.now(timezone.utc) - timedelta(days=30)
        pr.get_issue_events.return_value = [event]

        # Mock old comment (25 days ago)
        comment = Mock()
        comment.created_at = datetime.now(timezone.utc) - timedelta(days=25)
        pr.get_issue_comments.return_value = [comment]
        pr.get_review_comments.return_value = []
        pr.get_reviews.return_value = []

        self.assertTrue(self.labeler._is_eligible_for_stale_review(pr))

    def test_already_stale_review_pr_should_not_be_stale_again(self):
        """PR that is already marked stale-review should be skipped."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False

        mock_ur = Mock()
        mock_ur.name = "status:under-review"
        mock_sr = Mock()
        mock_sr.name = "status:stale-review"
        pr.labels = [mock_ur, mock_sr]

        self.assertFalse(self.labeler._is_eligible_for_stale_review(pr))


class TestTriageLabelerStaleRecoveryRules(unittest.TestCase):
    """Tests for stale recovery eligibility rules in TriageLabeler."""

    def setUp(self):
        self.mock_client = Mock()
        self.mock_repo = Mock()
        self.mock_repo.full_name = "mock-org/mock-repo"
        self.labeler = TriageLabeler(self.mock_client, self.mock_repo, dry_run=False)

    def test_non_stale_pr_should_not_be_recovered(self):
        """PR without status:stale label should not be eligible for recovery."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False
        pr.labels = []
        self.assertFalse(self.labeler._is_eligible_for_stale_recovery(pr))

    def test_stale_pr_with_no_activity_should_not_be_recovered(self):
        """PR with status:stale and no new activity should not be recovered."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False

        mock_label = Mock()
        mock_label.name = "status:stale"
        pr.labels = [mock_label]

        # Mock event: labeled stale 5 days ago
        event = Mock()
        event.event = "labeled"
        event.label.name = "status:stale"
        event.created_at = datetime.now(timezone.utc) - timedelta(days=5)
        pr.get_issue_events.return_value = [event]

        # Mock author
        mock_author = Mock()
        mock_author.login = "pr-author"
        pr.user = mock_author

        # Mock no activity
        pr.get_issue_comments.return_value = []
        pr.get_review_comments.return_value = []
        pr.get_commits.return_value = []

        self.assertFalse(self.labeler._is_eligible_for_stale_recovery(pr))

    def test_stale_pr_with_author_comment_should_be_recovered(self):
        """PR with status:stale and a new comment by author should be recovered."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False

        mock_label = Mock()
        mock_label.name = "status:stale"
        pr.labels = [mock_label]

        # Mock event: labeled stale 5 days ago
        event = Mock()
        event.event = "labeled"
        event.label.name = "status:stale"
        event.created_at = datetime.now(timezone.utc) - timedelta(days=5)
        pr.get_issue_events.return_value = [event]

        # Mock author
        mock_author = Mock()
        mock_author.login = "pr-author"
        pr.user = mock_author

        # Mock author comment (2 days ago)
        comment = Mock()
        comment.user.login = "pr-author"
        comment.created_at = datetime.now(timezone.utc) - timedelta(days=2)
        pr.get_issue_comments.return_value = [comment]
        pr.get_review_comments.return_value = []
        pr.get_commits.return_value = []

        self.assertTrue(self.labeler._is_eligible_for_stale_recovery(pr))

    def test_stale_pr_with_non_author_comment_should_not_be_recovered(self):
        """PR with status:stale and a new comment by someone else should not be recovered."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False

        mock_label = Mock()
        mock_label.name = "status:stale"
        pr.labels = [mock_label]

        # Mock event: labeled stale 5 days ago
        event = Mock()
        event.event = "labeled"
        event.label.name = "status:stale"
        event.created_at = datetime.now(timezone.utc) - timedelta(days=5)
        pr.get_issue_events.return_value = [event]

        # Mock author
        mock_author = Mock()
        mock_author.login = "pr-author"
        pr.user = mock_author

        # Mock non-author comment (2 days ago)
        comment = Mock()
        comment.user.login = "someone-else"
        comment.created_at = datetime.now(timezone.utc) - timedelta(days=2)
        pr.get_issue_comments.return_value = [comment]
        pr.get_review_comments.return_value = []
        pr.get_commits.return_value = []

        self.assertFalse(self.labeler._is_eligible_for_stale_recovery(pr))

    def test_stale_pr_with_author_commit_should_be_recovered(self):
        """PR with status:stale and a new commit by author should be recovered."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False

        mock_label = Mock()
        mock_label.name = "status:stale"
        pr.labels = [mock_label]

        # Mock event: labeled stale 5 days ago
        event = Mock()
        event.event = "labeled"
        event.label.name = "status:stale"
        event.created_at = datetime.now(timezone.utc) - timedelta(days=5)
        pr.get_issue_events.return_value = [event]

        # Mock author
        mock_author = Mock()
        mock_author.login = "pr-author"
        pr.user = mock_author

        # Mock author commit (2 days ago)
        commit = Mock()
        commit.sha = "1234567890"
        commit.author.login = "pr-author"
        commit.commit.committer.date = datetime.now(timezone.utc) - timedelta(days=2)
        pr.get_commits.return_value = [commit]

        pr.get_issue_comments.return_value = []
        pr.get_review_comments.return_value = []

        self.assertTrue(self.labeler._is_eligible_for_stale_recovery(pr))

    def test_stale_pr_with_old_author_activity_should_not_be_recovered(self):
        """PR with status:stale and activity by author BEFORE stale label should not be recovered."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False

        mock_label = Mock()
        mock_label.name = "status:stale"
        pr.labels = [mock_label]

        # Mock event: labeled stale 5 days ago
        event = Mock()
        event.event = "labeled"
        event.label.name = "status:stale"
        event.created_at = datetime.now(timezone.utc) - timedelta(days=5)
        pr.get_issue_events.return_value = [event]

        # Mock author
        mock_author = Mock()
        mock_author.login = "pr-author"
        pr.user = mock_author

        # Mock old author comment (10 days ago)
        comment = Mock()
        comment.user.login = "pr-author"
        comment.created_at = datetime.now(timezone.utc) - timedelta(days=10)
        pr.get_issue_comments.return_value = [comment]
        pr.get_review_comments.return_value = []
        pr.get_commits.return_value = []

        self.assertFalse(self.labeler._is_eligible_for_stale_recovery(pr))

    def test_triage_stale_recovery_applies_under_review(self):
        """Test that _triage_stale_recovery applies status:under-review when eligible."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False

        mock_label = Mock()
        mock_label.name = "status:stale"
        pr.labels = [mock_label]

        # Mock event: labeled stale 5 days ago
        event = Mock()
        event.event = "labeled"
        event.label.name = "status:stale"
        event.created_at = datetime.now(timezone.utc) - timedelta(days=5)
        pr.get_issue_events.return_value = [event]

        # Mock author
        mock_author = Mock()
        mock_author.login = "pr-author"
        pr.user = mock_author

        # Mock author comment (2 days ago)
        comment = Mock()
        comment.user.login = "pr-author"
        comment.created_at = datetime.now(timezone.utc) - timedelta(days=2)
        pr.get_issue_comments.return_value = [comment]
        pr.get_review_comments.return_value = []
        pr.get_commits.return_value = []

        self.labeler._triage_stale_recovery(pr)

        # Should remove status:stale (via mutual exclusivity inside _apply_label)
        pr.remove_from_labels.assert_called_once_with("status:stale")
        # Should add status:under-review
        pr.add_to_labels.assert_called_once_with("status:under-review")


class TestTriageLabelerStaleReviewRecoveryRules(unittest.TestCase):
    """Tests for stale-review recovery eligibility rules in TriageLabeler."""

    def setUp(self):
        self.mock_client = Mock()
        self.mock_repo = Mock()
        self.mock_repo.full_name = "mock-org/mock-repo"

        # Mock repo owner as Organization
        self.mock_repo.owner.type = "Organization"
        self.mock_repo.owner.login = "mock-org"

        # Mock organization membership
        self.mock_org = Mock()
        self.mock_client.get_organization.return_value = self.mock_org
        # Default: anyone is a member in tests unless overridden
        self.mock_org.has_in_members.return_value = True

        self.labeler = TriageLabeler(self.mock_client, self.mock_repo, dry_run=False)

    def test_non_stale_review_pr_should_not_be_recovered(self):
        """PR without status:stale-review label should not be eligible for recovery."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False
        pr.labels = []
        self.assertFalse(self.labeler._is_eligible_for_stale_review_recovery(pr))

    def test_stale_review_pr_with_no_activity_should_not_be_recovered(self):
        """PR with status:stale-review and no new activity should not be recovered."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False

        mock_label = Mock()
        mock_label.name = "status:stale-review"
        pr.labels = [mock_label]

        # Mock event: labeled stale-review 5 days ago
        event = Mock()
        event.event = "labeled"
        event.label.name = "status:stale-review"
        event.created_at = datetime.now(timezone.utc) - timedelta(days=5)
        pr.get_issue_events.return_value = [event]

        # Mock author
        mock_author = Mock()
        mock_author.login = "pr-author"
        pr.user = mock_author

        # Mock no activity
        pr.get_issue_comments.return_value = []
        pr.get_review_comments.return_value = []
        pr.get_reviews.return_value = []

        self.assertFalse(self.labeler._is_eligible_for_stale_review_recovery(pr))

    def test_stale_review_pr_with_reviewer_comment_should_be_recovered(self):
        """PR with status:stale-review and a new comment by reviewer should be recovered."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False

        mock_label = Mock()
        mock_label.name = "status:stale-review"
        pr.labels = [mock_label]

        # Mock event: labeled stale-review 5 days ago
        event = Mock()
        event.event = "labeled"
        event.label.name = "status:stale-review"
        event.created_at = datetime.now(timezone.utc) - timedelta(days=5)
        pr.get_issue_events.return_value = [event]

        # Mock author
        mock_author = Mock()
        mock_author.login = "pr-author"
        pr.user = mock_author

        # Mock reviewer comment (2 days ago)
        comment = Mock()
        comment.user.login = "reviewer-1"
        comment.created_at = datetime.now(timezone.utc) - timedelta(days=2)
        pr.get_issue_comments.return_value = [comment]
        pr.get_review_comments.return_value = []
        pr.get_reviews.return_value = []

        self.assertTrue(self.labeler._is_eligible_for_stale_review_recovery(pr))

    def test_stale_review_pr_with_author_comment_should_not_be_recovered(self):
        """PR with status:stale-review and a new comment by author should not be recovered."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False

        mock_label = Mock()
        mock_label.name = "status:stale-review"
        pr.labels = [mock_label]

        # Mock event: labeled stale-review 5 days ago
        event = Mock()
        event.event = "labeled"
        event.label.name = "status:stale-review"
        event.created_at = datetime.now(timezone.utc) - timedelta(days=5)
        pr.get_issue_events.return_value = [event]

        # Mock author
        mock_author = Mock()
        mock_author.login = "pr-author"
        pr.user = mock_author

        # Mock author comment (2 days ago)
        comment = Mock()
        comment.user.login = "pr-author"
        comment.created_at = datetime.now(timezone.utc) - timedelta(days=2)
        pr.get_issue_comments.return_value = [comment]
        pr.get_review_comments.return_value = []
        pr.get_reviews.return_value = []

        self.assertFalse(self.labeler._is_eligible_for_stale_review_recovery(pr))

    def test_stale_review_pr_with_reviewer_review_should_be_recovered(self):
        """PR with status:stale-review and a new review by reviewer should be recovered."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False

        mock_label = Mock()
        mock_label.name = "status:stale-review"
        pr.labels = [mock_label]

        # Mock event: labeled stale-review 5 days ago
        event = Mock()
        event.event = "labeled"
        event.label.name = "status:stale-review"
        event.created_at = datetime.now(timezone.utc) - timedelta(days=5)
        pr.get_issue_events.return_value = [event]

        # Mock author
        mock_author = Mock()
        mock_author.login = "pr-author"
        pr.user = mock_author

        # Mock reviewer review (2 days ago)
        review = Mock()
        review.user.login = "reviewer-1"
        review.state = "APPROVED"
        review.submitted_at = datetime.now(timezone.utc) - timedelta(days=2)
        pr.get_reviews.return_value = [review]

        pr.get_issue_comments.return_value = []
        pr.get_review_comments.return_value = []

        self.assertTrue(self.labeler._is_eligible_for_stale_review_recovery(pr))

    def test_triage_stale_review_recovery_applies_under_review(self):
        """Test that _triage_stale_review_recovery applies status:under-review when eligible."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False

        mock_label = Mock()
        mock_label.name = "status:stale-review"
        pr.labels = [mock_label]

        # Mock event: labeled stale-review 5 days ago
        event = Mock()
        event.event = "labeled"
        event.label.name = "status:stale-review"
        event.created_at = datetime.now(timezone.utc) - timedelta(days=5)
        pr.get_issue_events.return_value = [event]

        # Mock author
        mock_author = Mock()
        mock_author.login = "pr-author"
        pr.user = mock_author

        # Mock reviewer comment (2 days ago)
        comment = Mock()
        comment.user.login = "reviewer-1"
        comment.created_at = datetime.now(timezone.utc) - timedelta(days=2)
        pr.get_issue_comments.return_value = [comment]
        pr.get_review_comments.return_value = []
        pr.get_reviews.return_value = []

        self.labeler._triage_stale_review_recovery(pr)

        # Should remove status:stale-review (via mutual exclusivity inside _apply_label)
        pr.remove_from_labels.assert_called_once_with("status:stale-review")
        # Should add status:under-review
        pr.add_to_labels.assert_called_once_with("status:under-review")

    def test_stale_review_pr_with_non_member_comment_should_not_be_recovered(self):
        """PR with status:stale-review and comment by non-member should not be recovered."""
        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False

        mock_label = Mock()
        mock_label.name = "status:stale-review"
        pr.labels = [mock_label]

        # Mock event: labeled stale-review 5 days ago
        event = Mock()
        event.event = "labeled"
        event.label.name = "status:stale-review"
        event.created_at = datetime.now(timezone.utc) - timedelta(days=5)
        pr.get_issue_events.return_value = [event]

        # Mock author
        mock_author = Mock()
        mock_author.login = "pr-author"
        pr.user = mock_author

        # Mock reviewer who is NOT an org member
        non_member = Mock()
        non_member.login = "non-member"
        self.mock_org.has_in_members.return_value = False

        # Mock comment by non-member (2 days ago)
        comment = Mock()
        comment.user = non_member
        comment.created_at = datetime.now(timezone.utc) - timedelta(days=2)
        pr.get_issue_comments.return_value = [comment]
        pr.get_review_comments.return_value = []
        pr.get_reviews.return_value = []

        self.assertFalse(self.labeler._is_eligible_for_stale_review_recovery(pr))

    def test_stale_review_pr_personal_repo_with_collaborator_comment_should_be_recovered(
        self,
    ):
        """Test recovery on personal repo when comment is by collaborator."""
        # Re-initialize labeler with personal repo
        personal_repo = Mock()
        personal_repo.full_name = "user/repo"
        personal_repo.owner.type = "User"
        personal_repo.owner.login = "user"
        personal_repo.has_in_collaborators.return_value = True

        labeler = TriageLabeler(self.mock_client, personal_repo, dry_run=False)

        pr = Mock(spec=github.PullRequest.PullRequest)
        pr.number = 1
        pr.state = "open"
        pr.draft = False

        mock_label = Mock()
        mock_label.name = "status:stale-review"
        pr.labels = [mock_label]

        # Mock event: labeled stale-review 5 days ago
        event = Mock()
        event.event = "labeled"
        event.label.name = "status:stale-review"
        event.created_at = datetime.now(timezone.utc) - timedelta(days=5)
        pr.get_issue_events.return_value = [event]

        # Mock author
        mock_author = Mock()
        mock_author.login = "pr-author"
        pr.user = mock_author

        # Mock collaborator comment (2 days ago)
        comment = Mock()
        comment.user.login = "collaborator-1"
        comment.created_at = datetime.now(timezone.utc) - timedelta(days=2)
        pr.get_issue_comments.return_value = [comment]
        pr.get_review_comments.return_value = []
        pr.get_reviews.return_value = []

        self.assertTrue(labeler._is_eligible_for_stale_review_recovery(pr))
        personal_repo.has_in_collaborators.assert_called_once()


if __name__ == "__main__":
    unittest.main()
