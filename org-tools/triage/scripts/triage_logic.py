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

NEEDS_TRIAGE_LABEL = "status:needs-triage"
BLOCKED_LABEL = "status:blocked"
STALE_LABEL = "status:stale"
UNDER_REVIEW_LABEL = "status:under-review"
STALE_REVIEW_LABEL = "status:stale-review"
BLOCKED_STALE_THRESHOLD_DAYS = 30
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
        self._org = None
        self._is_org_checked = False
        self._member_cache = {}

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
        query_stale = (
            f'is:pr is:open -is:draft label:"{STALE_LABEL}" repo:{self.repo.full_name}'
        )
        query_stale_review = f'is:pr is:open -is:draft label:"{STALE_REVIEW_LABEL}" repo:{self.repo.full_name}'

        logger.info("  Search Query (Needs Triage): %s", query_needs_triage)
        logger.info("  Search Query (Blocked): %s", query_blocked)
        logger.info("  Search Query (Under Review): %s", query_under_review)
        logger.info("  Search Query (Stale): %s", query_stale)
        logger.info("  Search Query (Stale Review): %s", query_stale_review)

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

        try:
            prs_stale = self.client.search_issues(query_stale)
            logger.info("  Found %s stale PRs to check.", prs_stale.totalCount)
            for pr in prs_stale:
                pr_numbers.add(pr.number)
        except Exception as e:
            raise RuntimeError(
                f"Failed to search stale PRs for {self.repo.full_name}: {e}"
            )

        try:
            prs_stale_review = self.client.search_issues(query_stale_review)
            logger.info(
                "  Found %s stale review PRs to check.", prs_stale_review.totalCount
            )
            for pr in prs_stale_review:
                pr_numbers.add(pr.number)
        except Exception as e:
            raise RuntimeError(
                f"Failed to search stale review PRs for {self.repo.full_name}: {e}"
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
        self._triage_stale_recovery(pull)
        self._triage_stale_review_recovery(pull)

    def _triage_needs_triage(self, pull: github.PullRequest.PullRequest) -> None:
        """Checks and applies 'status:needs-triage' if eligible."""
        if self._is_eligible_for_triage(pull):
            self._apply_label(pull, NEEDS_TRIAGE_LABEL)

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
        if NEEDS_TRIAGE_LABEL in labels:
            logger.info(
                "Skipping: PR #%s already has '%s' label.",
                pull.number,
                NEEDS_TRIAGE_LABEL,
            )
            return False

        if len(labels) > 0:
            logger.info("Skipping: PR #%s has other labels: %s", pull.number, labels)
            return False

        return True

    def _triage_stale_recovery(self, pull: github.PullRequest.PullRequest) -> None:
        """Checks if a 'status:stale' PR has new author activity and restores 'status:under-review'."""
        if self._is_eligible_for_stale_recovery(pull):
            self._apply_label(pull, UNDER_REVIEW_LABEL)

    def _is_eligible_for_stale_recovery(
        self, pull: github.PullRequest.PullRequest
    ) -> bool:
        """Checks if a 'status:stale' PR has new author activity."""
        if pull.state != "open":
            return False
        if pull.draft:
            return False

        labels = {label.name for label in pull.labels}
        if STALE_LABEL not in labels:
            return False

        label_applied_time = self._get_label_applied_time(pull, STALE_LABEL)
        if not label_applied_time:
            return False

        author = pull.user
        if not author:
            return False

        # 1. Check comments by author
        try:
            comments = pull.get_issue_comments()
            for comment in comments:
                if comment.user and comment.user.login == author.login:
                    comment_time = comment.created_at
                    if comment_time.tzinfo is None:
                        comment_time = comment_time.replace(tzinfo=timezone.utc)
                    if comment_time > label_applied_time:
                        logger.info(
                            "  PR #%s has author comment activity (by %s) at %s (stale applied: %s).",
                            pull.number,
                            author.login,
                            comment_time,
                            label_applied_time,
                        )
                        return True
        except Exception as e:
            log_error(
                "Error checking issue comments for stale recovery on PR #%s: %s",
                pull.number,
                e,
            )

        try:
            review_comments = pull.get_review_comments(since=label_applied_time)
            for comment in review_comments:
                if comment.user and comment.user.login == author.login:
                    comment_time = comment.created_at
                    if comment_time.tzinfo is None:
                        comment_time = comment_time.replace(tzinfo=timezone.utc)
                    if comment_time > label_applied_time:
                        logger.info(
                            "  PR #%s has author review comment activity (by %s) at %s (stale applied: %s).",
                            pull.number,
                            author.login,
                            comment_time,
                            label_applied_time,
                        )
                        return True
        except Exception as e:
            log_error(
                "Error checking review comments for stale recovery on PR #%s: %s",
                pull.number,
                e,
            )

        # 2. Check commits by author
        try:
            commits = pull.get_commits()
            for commit in commits:
                commit_author = commit.author
                if commit_author and commit_author.login == author.login:
                    # Use committer date to capture rebases/amends
                    commit_time = commit.commit.committer.date
                    if commit_time.tzinfo is None:
                        commit_time = commit_time.replace(tzinfo=timezone.utc)
                    if commit_time > label_applied_time:
                        logger.info(
                            "  PR #%s has author commit activity (by %s, sha: %s) at %s (stale applied: %s).",
                            pull.number,
                            author.login,
                            commit.sha[:7],
                            commit_time,
                            label_applied_time,
                        )
                        return True
        except Exception as e:
            log_error(
                "Error checking commits for stale recovery on PR #%s: %s",
                pull.number,
                e,
            )

        return False

    def _triage_stale_review_recovery(
        self, pull: github.PullRequest.PullRequest
    ) -> None:
        """Checks if a 'status:stale-review' PR has new reviewer activity and restores 'status:under-review'."""
        if self._is_eligible_for_stale_review_recovery(pull):
            self._apply_label(pull, UNDER_REVIEW_LABEL)

    def _is_eligible_for_stale_review_recovery(
        self, pull: github.PullRequest.PullRequest
    ) -> bool:
        """Checks if a 'status:stale-review' PR has new reviewer activity."""
        if pull.state != "open":
            return False
        if pull.draft:
            return False

        labels = {label.name for label in pull.labels}
        if STALE_REVIEW_LABEL not in labels:
            return False

        label_applied_time = self._get_label_applied_time(pull, STALE_REVIEW_LABEL)
        if not label_applied_time:
            return False

        author = pull.user
        if not author:
            return False

        # 1. Check comments by non-author org members
        try:
            comments = pull.get_issue_comments()
            for comment in comments:
                if (
                    comment.user
                    and comment.user.login != author.login
                    and self._is_member(comment.user)
                ):
                    comment_time = comment.created_at
                    if comment_time.tzinfo is None:
                        comment_time = comment_time.replace(tzinfo=timezone.utc)
                    if comment_time > label_applied_time:
                        logger.info(
                            "  PR #%s has reviewer comment activity (by %s) at %s (stale-review applied: %s).",
                            pull.number,
                            comment.user.login,
                            comment_time,
                            label_applied_time,
                        )
                        return True
        except Exception as e:
            log_error(
                "Error checking issue comments for stale-review recovery on PR #%s: %s",
                pull.number,
                e,
            )

        try:
            review_comments = pull.get_review_comments(since=label_applied_time)
            for comment in review_comments:
                if (
                    comment.user
                    and comment.user.login != author.login
                    and self._is_member(comment.user)
                ):
                    comment_time = comment.created_at
                    if comment_time.tzinfo is None:
                        comment_time = comment_time.replace(tzinfo=timezone.utc)
                    if comment_time > label_applied_time:
                        logger.info(
                            "  PR #%s has reviewer review comment activity (by %s) at %s (stale-review applied: %s).",
                            pull.number,
                            comment.user.login,
                            comment_time,
                            label_applied_time,
                        )
                        return True
        except Exception as e:
            log_error(
                "Error checking review comments for stale-review recovery on PR #%s: %s",
                pull.number,
                e,
            )

        # 2. Check reviews by non-author org members
        try:
            reviews = pull.get_reviews()
            for review in reviews:
                if (
                    review.user
                    and review.user.login != author.login
                    and self._is_member(review.user)
                ):
                    review_time = review.submitted_at
                    if review_time:
                        if review_time.tzinfo is None:
                            review_time = review_time.replace(tzinfo=timezone.utc)
                        if review_time > label_applied_time:
                            logger.info(
                                "  PR #%s has reviewer review activity (by %s, state: %s) at %s (stale-review applied: %s).",
                                pull.number,
                                review.user.login,
                                review.state,
                                review_time,
                                label_applied_time,
                            )
                            return True
        except Exception as e:
            log_error(
                "Error checking reviews for stale-review recovery on PR #%s: %s",
                pull.number,
                e,
            )

        return False

    def _get_org(self) -> github.Organization.Organization | None:
        if not self._is_org_checked:
            if self.repo.owner.type == "Organization":
                try:
                    self._org = self.client.get_organization(self.repo.owner.login)
                except Exception as e:
                    log_error(
                        "Error fetching organization %s: %s",
                        self.repo.owner.login,
                        e,
                    )
            self._is_org_checked = True
        return self._org

    def _is_member(self, user: github.NamedUser.NamedUser) -> bool:
        """Checks if a user is a member of the organization (or collaborator if personal repo)."""
        if user.login in self._member_cache:
            return self._member_cache[user.login]

        is_member = False
        org = self._get_org()
        if org:
            try:
                is_member = org.has_in_members(user)
            except Exception as e:
                log_error(
                    "Error checking org membership for %s in %s: %s",
                    user.login,
                    org.login,
                    e,
                )
        else:
            try:
                is_member = self.repo.has_in_collaborators(user)
            except Exception as e:
                log_error(
                    "Error checking collaborator status for %s in %s: %s",
                    user.login,
                    self.repo.full_name,
                    e,
                )

        self._member_cache[user.login] = is_member
        return is_member

    def _apply_label(
        self,
        pull: github.PullRequest.PullRequest,
        label_name: str,
    ) -> None:
        """Applies the given label to the PR and removes other mutually exclusive status labels."""
        STATUS_LABELS = {
            NEEDS_TRIAGE_LABEL,
            BLOCKED_LABEL,
            STALE_LABEL,
            UNDER_REVIEW_LABEL,
            STALE_REVIEW_LABEL,
        }

        try:
            if not self.dry_run:
                current_labels = {label.name for label in pull.labels}
                for label in current_labels:
                    if label in STATUS_LABELS and label != label_name:
                        logger.info(
                            "    Removing mutually exclusive label '%s' from PR #%s",
                            label,
                            pull.number,
                        )
                        pull.remove_from_labels(label)

                pull.add_to_labels(label_name)
                logger.info(
                    "    Success: PR #%s. Applied '%s'.",
                    pull.number,
                    label_name,
                )
            else:
                current_labels = {label.name for label in pull.labels}
                for label in current_labels:
                    if label in STATUS_LABELS and label != label_name:
                        logger.info(
                            "    [DRY RUN] Would remove mutually exclusive label '%s' from PR #%s",
                            label,
                            pull.number,
                        )
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
