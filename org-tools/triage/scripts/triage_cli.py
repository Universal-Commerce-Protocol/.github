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

# /// script
# dependencies = [
#   "pygithub",
#   "click",
# ]
# ///
"""CLI entry point for the Central PR Triage tool.

This script parses command-line arguments and orchestrates the triage process
across one or more GitHub repositories. It automatically applies the
'status:needs-triage' label to open, non-draft Pull Requests that do not have
triage or skip labels.

By default, the script scans all open PRs in the specified repositories.
It also supports an optional `--pr` parameter to target a single, specific PR
in a single repository, which is useful for debugging, testing, or manual
re-runs of the triage logic.
"""

import logging
import os
import sys
import click
import github
from triage_logic import TriageLabeler, log_error

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("triage")


def verify_and_fetch_repos(
    client: github.Github, org: str, repo_names: list[str]
) -> tuple[dict[str, github.Repository.Repository], list[str]]:
    """Verifies access to all repositories.

    Returns:
        A tuple containing:
            - A map of verified repository names to their Repository objects.
            - A list of repository names that were inaccessible.
    """
    logger.info("Verifying access to all repositories...")
    verified_repos = {}
    inaccessible_repos = []
    for repo_name in repo_names:
        org_repo_name = f"{org}/{repo_name}"
        try:
            repo_obj = client.get_repo(org_repo_name)
            verified_repos[repo_name] = repo_obj
        except github.GithubException as e:
            if e.status == 404:
                log_error(
                    "Error: Repository not found or access denied: %s",
                    org_repo_name,
                )
            else:
                log_error("Error: Failed to access repository %s: %s", org_repo_name, e)
            inaccessible_repos.append(repo_name)
        except Exception as e:
            log_error(
                "Error: Unexpected error accessing repository %s: %s",
                org_repo_name,
                e,
            )
            inaccessible_repos.append(repo_name)

    return verified_repos, inaccessible_repos


def triage_multiple_repositories(
    client: github.Github,
    org: str,
    verified_repos: dict[str, github.Repository.Repository],
    dry_run: bool,
) -> list[str]:
    """Runs triage on multiple repositories.

    Returns:
        List of repository names that failed to process.
    """
    failed_to_triage_repo_names = []
    for repo_name, repo_obj in verified_repos.items():
        triage_job = TriageLabeler(client, repo_obj, dry_run=dry_run)
        try:
            triage_job.triage_all_outstanding()
        except Exception as e:
            log_error("Error processing repository %s: %s", repo_name, e)
            failed_to_triage_repo_names.append(repo_name)
    return failed_to_triage_repo_names


def triage_single_pr(
    client: github.Github,
    org: str,
    repo_name: str,
    pr_num: int,
    dry_run: bool,
) -> None:
    """Triages a single specific pull request in a repository.

    Raises:
        RuntimeError: If repository access fails.
    """
    org_repo_name = f"{org}/{repo_name}"
    try:
        repo_obj = client.get_repo(org_repo_name)
    except Exception as e:
        raise RuntimeError(f"Failed to access repository {org_repo_name}: {e}")

    triage_job = TriageLabeler(client, repo_obj, dry_run=dry_run)
    triage_job.triage(pr_num)


@click.command()
@click.option(
    "--token",
    required=True,
    envvar="ORG_TRIAGE_TOKEN",
    help=(
        "GitHub Token with read access to org and write access to labels"
        " (defaults to ORG_TRIAGE_TOKEN env var)"
    ),
)
@click.option("--org", required=True, help="GitHub Organization")
@click.option(
    "--repos",
    required=True,
    help="Comma-separated list of repository names (exactly one required if --pr is specified)",
)
@click.option(
    "--pr",
    type=int,
    help=(
        "PR Number (optional). If specified, the tool will only triage this"
        " specific PR. This is useful for debugging or manual retries. Requires"
        " exactly one repository in --repos."
    ),
)
@click.option(
    "--apply",
    is_flag=True,
    help="Actually apply the label (default is dry-run)",
)
def main(token: str, org: str, repos: str, pr: int, apply: bool) -> None:
    """Central PR Triage Tool.

    Automatically applies the 'status:needs-triage' label to eligible open PRs.
    By default, runs in dry-run mode (does not apply labels).

    If --pr is provided, it triages only that specific PR in the specified repository.
    Otherwise, it scans all open PRs in the specified repositories.
    """
    dry_run = not apply
    logger.info("=== Starting PR Triage (Dry Run: %s) ===", dry_run)

    # Initialize GitHub client (respect GITHUB_API_URL for local testing/mocking)
    api_url = os.getenv("GITHUB_API_URL")
    try:
        auth = github.Auth.Token(token)
        if api_url and api_url != "https://api.github.com":
            client = github.Github(auth=auth, base_url=f"{api_url}/api/v3")
        else:
            client = github.Github(auth=auth)
    except Exception as e:
        log_error("Failed to initialize GitHub client: %s", e)
        sys.exit(1)

    # Global safety net to catch any unexpected critical errors and exit cleanly.
    try:
        repo_list = [r.strip() for r in repos.split(",") if r.strip()]
        if not repo_list:
            log_error("Error: No repositories specified in --repos.")
            sys.exit(1)

        if pr:
            if len(repo_list) != 1:
                log_error(
                    "Error: Exactly one repository must be specified in --repos when --pr is provided."
                )
                sys.exit(1)

            try:
                triage_single_pr(client, org, repo_list[0], pr, dry_run)
            except Exception as e:
                log_error("Error during single PR triage: %s", e)
                sys.exit(1)
        else:
            verified_repos, inaccessible_repos = verify_and_fetch_repos(
                client, org, repo_list
            )
            if inaccessible_repos:
                log_error(
                    "Aborting: One or more repositories are inaccessible: %s",
                    ", ".join(inaccessible_repos),
                )
                sys.exit(1)

            logger.info("Access verification successful. Starting triage...\n")

            failed_to_triage_repo_names = triage_multiple_repositories(
                client, org, verified_repos, dry_run
            )

            if failed_to_triage_repo_names:
                log_error(
                    "Failed to process repositories: %s",
                    ", ".join(failed_to_triage_repo_names),
                )
                sys.exit(1)

        logger.info("\n=== PR Triage Completed Successfully ===")

    except Exception as e:
        # Log any other unexpected critical error before exiting
        log_error("Critical error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
