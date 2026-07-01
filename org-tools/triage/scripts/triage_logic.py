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
import github


# Configure logging
logger = logging.getLogger("triage")

TARGET_LABEL = "status:needs-triage"
SKIP_LABELS = {"status:backlog", "status:stale", "status:under-review"}


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

        Finds open, non-draft PRs lacking target/skip labels, and applies the
        label.

        Raises:
            RuntimeError: If the Search API fails.
        """
        logger.info("\nProcessing Repository: %s", self.repo.full_name)

        # Construct query to filter out drafts and labeled/skip PRs at the API level.
        exclude_labels_query = " ".join(
            f"-label:{label}" for label in [TARGET_LABEL] + list(SKIP_LABELS)
        )
        query = (
            f"is:pr is:open -is:draft {exclude_labels_query} repo:{self.repo.full_name}"
        )
        logger.info("  Search Query: %s", query)

        try:
            prs = self.client.search_issues(query, sort="created", order="desc")
            count = prs.totalCount
            logger.info("  Found %s PRs needing triage (from search index).", count)
        except Exception as e:
            raise RuntimeError(f"Failed to search PRs for {self.repo.full_name}: {e}")

        for pr in prs:
            logger.info("  Processing PR #%s: %s", pr.number, pr.title)
            try:
                # Fetch fresh PullRequest object to perform in-memory checks
                pull = self.repo.get_pull(pr.number)
                self._triage_pull(pull)
            except Exception as e:
                # We log the error and continue to process other PRs. This prevents a single
                # problematic PR (e.g., deleted, inaccessible, or failing rules check)
                # from blocking the entire run.
                log_error(
                    "Error processing PR #%s in %s: %s",
                    pr.number,
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
        """Evaluates rules and applies the label to a single PR if eligible."""
        if self._is_eligible_for_triage(pull):
            self._apply_label(pull)

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

        for skip_label in SKIP_LABELS:
            if skip_label in labels:
                logger.info(
                    "Skipping: PR #%s has skip label '%s'.", pull.number, skip_label
                )
                return False

        return True

    def _apply_label(
        self,
        pull: github.PullRequest.PullRequest,
    ) -> None:
        """Applies the 'status:needs-triage' label to the given PR."""
        try:
            if not self.dry_run:
                pull.add_to_labels(TARGET_LABEL)
                logger.info(
                    "    Success: PR #%s needs triage. Applied '%s'.",
                    pull.number,
                    TARGET_LABEL,
                )
            else:
                logger.info(
                    "    [DRY RUN] Success: PR #%s needs triage. Would apply '%s'.",
                    pull.number,
                    TARGET_LABEL,
                )
        except Exception as e:
            log_error(
                "Error applying label to PR #%s in %s: %s",
                pull.number,
                self.repo.full_name,
                e,
            )
