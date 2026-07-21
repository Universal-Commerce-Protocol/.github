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
BLOCKED_STALE_THRESHOLD_DAYS = 21


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

        logger.info("  Search Query (Needs Triage): %s", query_needs_triage)
        logger.info("  Search Query (Blocked): %s", query_blocked)

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

    def _triage_needs_triage(self, pull: github.PullRequest.PullRequest) -> None:
        """Checks and applies 'status:needs-triage' if eligible."""
        if self._is_eligible_for_triage(pull):
            self._apply_label(pull, TARGET_LABEL)

    def _triage_blocked_stale(self, pull: github.PullRequest.PullRequest) -> None:
        """Checks and applies 'status:stale' if PR is blocked for > 21 days."""
        if self._is_eligible_for_blocked_stale(pull):
            self._apply_label(pull, STALE_LABEL)

    def _is_eligible_for_blocked_stale(
        self, pull: github.PullRequest.PullRequest
    ) -> bool:
        """Checks if a PR is eligible for being marked stale due to being blocked."""
        if pull.state != "open":
            return False
        if pull.draft:
            return False

        labels = {label.name for label in pull.labels}
        if BLOCKED_LABEL not in labels:
            return False

        if STALE_LABEL in labels:
            logger.info(
                "Skipping: PR #%s already has '%s' label.", pull.number, STALE_LABEL
            )
            return False

        duration = self._get_label_applied_duration(pull, BLOCKED_LABEL)
        logger.info(
            "  PR #%s has been blocked for %.2f days (threshold: %s days).",
            pull.number,
            duration,
            BLOCKED_STALE_THRESHOLD_DAYS,
        )

        return duration > BLOCKED_STALE_THRESHOLD_DAYS

    def _get_label_applied_duration(
        self, pull: github.PullRequest.PullRequest, label_name: str
    ) -> float:
        """Returns the number of days a label has been continuously applied to a PR."""
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
                now = datetime.now(timezone.utc)
                duration = now - latest_labeled_time
                return duration.total_seconds() / (24 * 3600)
        except Exception as e:
            log_error(
                "Error getting label duration for PR #%s in %s: %s",
                pull.number,
                self.repo.full_name,
                e,
            )
        return 0.0

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
