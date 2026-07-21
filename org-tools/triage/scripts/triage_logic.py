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

"""Triage labeling logic for GitHub Pull Requests.

This module provides the TriageLabeler class which handles the evaluation
and labeling of Pull Requests in a repository.
"""

import logging
import os
import sys
from datetime import datetime, timezone
import github


# Configure logging
logger = logging.getLogger("triage")

TARGET_LABEL = "status:needs-triage"
BLOCKED_LABEL = "status:blocked"
STALE_LABEL = "status:stale"
UNDER_REVIEW_LABEL = "status:under-review"
STALE_REVIEW_LABEL = "status:stale-review"
BLOCKED_STALE_THRESHOLD_DAYS = 21
STALE_REVIEW_THRESHOLD_DAYS = 21


def log_error(message: str, *args) -> None:
    """Logs an error message.

    Uses GitHub Actions workflow commands if running in CI.

    Args:
        message: The error message format string.
        *args: Arguments to interpolate into the message.
    """
    if os.getenv("GITHUB_ACTIONS") == "true":
        formatted = message % args if args else message
        print(f"::error::{formatted}", file=sys.stderr)
    else:
        logger.error(message, *args)


class TriageLabeler:
    """Triage manager for a single GitHub repository.

    Validates repository access and applies the 'status:needs-triage' label
    to eligible Pull Requests.
    """

    def __init__(
        self,
        client: github.Github,
        repo: github.Repository.Repository,
        dry_run: bool = True,
    ):
        """Initializes the TriageLabeler instance.

        Args:
            client: An initialized Github client.
            repo: An initialized PyGithub Repository object.
            dry_run: If True, only logs actions without applying labels.
        """
        self.client = client
        self.repo = repo
        self.dry_run = dry_run

    def triage_all_outstanding(self) -> None:
        """Triages the repository using the Search API.

        Finds open, non-draft PRs needing triage or blocked for too long,
        and applies appropriate labels.

        Raises:
            RuntimeError: If the Search API fails.
        """
        logger.info("\nProcessing Repository: %s", self.repo.full_name)

        query_needs_triage = (
            f"is:pr is:open -is:draft no:label repo:{self.repo.full_name}"
        )
        query_blocked = f'is:pr is:open -is:draft label:"{BLOCKED_LABEL}" repo:{self.repo.full_name}'
        query_under_review = f'is:pr is:open -is:draft label:"{UNDER_REVIEW_LABEL}" repo:{self.repo.full_name}'

        logger.info("  Search Query (Needs Triage): %s", query_needs_triage)
        logger.info("  Search Query (Blocked): %s", query_blocked)
        logger.info("  Search Query (Under Review): %s", query_under_review)

        pr_numbers = set()

        try:
            prs_needs_triage = self.client.search_issues(query_needs_triage)
            logger.info(
                "  Found %s PRs needing initial triage.", prs_needs_triage.totalCount
            )
            for pr in prs_needs_triage:
                pr_numbers.add(pr.number)
        except Exception as e:
            raise RuntimeError(
                f"Failed to search PRs needing triage for {self.repo.full_name}: {e}"
            )

        try:
            prs_blocked = self.client.search_issues(query_blocked)
            logger.info("  Found %s blocked PRs to check.", prs_blocked.totalCount)
            for pr in prs_blocked:
                pr_numbers.add(pr.number)
        except Exception as e:
            raise RuntimeError(
                f"Failed to search blocked PRs for {self.repo.full_name}: {e}"
            )

        try:
            prs_under_review = self.client.search_issues(query_under_review)
            logger.info(
                "  Found %s PRs under review to check.", prs_under_review.totalCount
            )
            for pr in prs_under_review:
                pr_numbers.add(pr.number)
        except Exception as e:
            raise RuntimeError(
                f"Failed to search PRs under review for {self.repo.full_name}: {e}"
            )

        logger.info("  Total unique PRs to process: %s", len(pr_numbers))

        for pr_num in sorted(pr_numbers, reverse=True):
            logger.info("  Processing PR #%s", pr_num)
            try:
                # Fetch fresh PullRequest object to perform in-memory checks
                pull = self.repo.get_pull(pr_num)
                self._triage_pull(pull)
            except Exception as e:
                # We log the error and continue to process other PRs. This prevents a single
                # problematic PR (e.g., deleted, inaccessible, or failing rules check)
                # from blocking the entire run.
                log_error(
                    "Error processing PR #%s in %s: %s",
                    pr_num,
                    self.repo.full_name,
                    e,
                )

    def triage(self, pr_num: int) -> None:
        """Runs the triage process for a single specific PR."""
        logger.info("\nProcessing Single PR #%s in %s", pr_num, self.repo.full_name)
        try:
            pull = self.repo.get_pull(pr_num)
        except github.GithubException as e:
            if e.status == 404:
                raise RuntimeError(
                    f"PR #{pr_num} not found or access denied in {self.repo.full_name}"
                )
            raise RuntimeError(
                f"Failed to fetch PR #{pr_num} in {self.repo.full_name}: {e}"
            )
        except Exception as e:
            raise RuntimeError(
                f"Failed to fetch PR #{pr_num} in {self.repo.full_name}: {e}"
            )

        self._triage_pull(pull)

    def _triage_pull(self, pull: github.PullRequest.PullRequest) -> None:
        """Evaluates rules and applies labels to a single PR."""
        self._triage_needs_triage(pull)
        self._triage_blocked_stale(pull)
        self._triage_stale_review(pull)

    def _triage_needs_triage(self, pull: github.PullRequest.PullRequest) -> None:
        """Checks and applies 'status:needs-triage' if eligible."""
        if self._is_eligible_for_triage(pull):
            self._apply_label(pull, TARGET_LABEL)

    def _triage_blocked_stale(self, pull: github.PullRequest.PullRequest) -> None:
        """Checks and applies 'status:stale' if PR is blocked for > 21 days."""
        if self._is_eligible_for_blocked_stale(pull):
            self._apply_label(pull, STALE_LABEL)

    def _triage_stale_review(self, pull: github.PullRequest.PullRequest) -> None:
        """Checks and applies 'status:stale-review' if PR is under review with no activity for > 21 days."""
        if self._is_eligible_for_stale_review(pull):
            self._apply_label(pull, STALE_REVIEW_LABEL)

    def _is_eligible_for_blocked_stale(
        self, pull: github.PullRequest.PullRequest
    ) -> bool:
        """Checks if a PR is eligible for being marked stale due to being blocked."""
        return self._is_eligible_for_stale_by_label(
            pull, BLOCKED_LABEL, STALE_LABEL, BLOCKED_STALE_THRESHOLD_DAYS
        )

    def _is_eligible_for_stale_review(
        self, pull: github.PullRequest.PullRequest
    ) -> bool:
        """Checks if a PR is eligible for being marked stale-review."""
        return self._is_eligible_for_stale_by_label(
            pull, UNDER_REVIEW_LABEL, STALE_REVIEW_LABEL, STALE_REVIEW_THRESHOLD_DAYS
        )

    def _is_eligible_for_stale_by_label(
        self,
        pull: github.PullRequest.PullRequest,
        target_label: str,
        stale_label: str,
        threshold_days: int,
    ) -> bool:
        """Helper to check if a PR is stale based on a label and inactivity."""
        if pull.state != "open":
            return False
        if pull.draft:
            return False

        labels = {label.name for label in pull.labels}
        if target_label not in labels:
            return False

        if stale_label in labels:
            logger.info(
                "Skipping: PR #%s already has '%s' label.", pull.number, stale_label
            )
            return False

        label_applied_time = self._get_label_applied_time(pull, target_label)
        if not label_applied_time:
            logger.warning(
                "Could not find when '%s' was applied to PR #%s",
                target_label,
                pull.number,
            )
            return False

        latest_activity = self._get_latest_activity_time_after(pull, label_applied_time)
        baseline_time = latest_activity if latest_activity else label_applied_time

        now = datetime.now(timezone.utc)
        duration = now - baseline_time
        duration_days = duration.total_seconds() / (24 * 3600)

        logger.info(
            "  PR #%s has been %s with no activity for %.2f days (threshold: %s days).",
            pull.number,
            target_label.split(":")[-1],
            duration_days,
            threshold_days,
        )

        return duration_days > threshold_days

    def _get_label_applied_time(
        self, pull: github.PullRequest.PullRequest, label_name: str
    ) -> datetime | None:
        """Returns the latest time a label was applied to a PR, or None."""
        try:
            events = pull.get_issue_events()
            latest_labeled_time = None
            for event in events:
                if (
                    event.event == "labeled"
                    and event.label
                    and event.label.name == label_name
                ):
                    latest_labeled_time = event.created_at

            if latest_labeled_time:
                if latest_labeled_time.tzinfo is None:
                    latest_labeled_time = latest_labeled_time.replace(
                        tzinfo=timezone.utc
                    )
                return latest_labeled_time
        except Exception as e:
            log_error(
                "Error getting label application time for PR #%s in %s: %s",
                pull.number,
                self.repo.full_name,
                e,
            )
        return None

    def _get_latest_activity_time_after(
        self, pull: github.PullRequest.PullRequest, threshold_time: datetime
    ) -> datetime | None:
        """Returns the latest activity (comments/reviews) time after the threshold_time, or None."""
        latest_time = None

        def update_latest(activity_time):
            nonlocal latest_time
            if activity_time:
                if activity_time.tzinfo is None:
                    activity_time = activity_time.replace(tzinfo=timezone.utc)
                if activity_time > threshold_time:
                    if latest_time is None or activity_time > latest_time:
                        latest_time = activity_time

        try:
            # 1. Issue comments (main thread)
            comments = pull.get_issue_comments()
            for comment in comments:
                update_latest(comment.created_at)

            # 2. Review comments (inline)
            review_comments = pull.get_review_comments(since=threshold_time)
            for comment in review_comments:
                update_latest(comment.created_at)

            # 3. Reviews
            reviews = pull.get_reviews()
            for review in reviews:
                update_latest(review.submitted_at)

        except Exception as e:
            log_error(
                "Error getting latest activity for PR #%s in %s: %s",
                pull.number,
                self.repo.full_name,
                e,
            )

        return latest_time

    def _is_eligible_for_triage(self, pull: github.PullRequest.PullRequest) -> bool:
        """Performs in-memory checks to determine if a PR is eligible for triage.

        Used for both bulk and single-PR triage to ensure consistency.
        """
        if pull.state != "open":
            logger.info("Skipping: PR #%s is %s (not open).", pull.number, pull.state)
            return False

        if pull.draft:
            logger.info("Skipping: PR #%s is a draft.", pull.number)
            return False

        labels = {label.name for label in pull.labels}
        if TARGET_LABEL in labels:
            logger.info(
                "Skipping: PR #%s already has '%s' label.", pull.number, TARGET_LABEL
            )
            return False

        if len(labels) > 0:
            logger.info("Skipping: PR #%s has other labels: %s", pull.number, labels)
            return False

        return True

    def _apply_label(
        self,
        pull: github.PullRequest.PullRequest,
        label_name: str,
    ) -> None:
        """Applies the given label to the PR."""
        try:
            if not self.dry_run:
                pull.add_to_labels(label_name)
                logger.info(
                    "    Success: PR #%s. Applied '%s'.",
                    pull.number,
                    label_name,
                )
            else:
                logger.info(
                    "    [DRY RUN] Success: PR #%s. Would apply '%s'.",
                    pull.number,
                    label_name,
                )
        except Exception as e:
            log_error(
                "Error applying label %s to PR #%s in %s: %s",
                label_name,
                pull.number,
                self.repo.full_name,
                e,
            )
