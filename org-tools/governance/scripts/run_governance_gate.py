#!/usr/bin/env python3
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

"""Orchestrates PR governance evaluation and posts the static commit status.

Invoked by `.github/workflows/reusable-governance.yml` with all untrusted workflow
inputs and event payloads passed strictly through environment variables rather
than inline shell or script template interpolation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

STATUS_CONTEXT = "Governance / Approvals"
ORG_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
OPEN_PRS_PER_PAGE = 100
MAX_OPEN_PR_PAGES = 5


class GitHubApiError(RuntimeError):
    """Raised when a GitHub REST API request returns an HTTP error."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


def _clean_env(value: str | None) -> str:
    """Normalize unset or literal 'null' GitHub expression strings to empty."""
    if value is None:
        return ""
    stripped = value.strip()
    return "" if stripped.lower() == "null" else stripped


def parse_pr_number(*candidates: str | None) -> int | None:
    """Return the first valid positive integer PR number from candidates."""
    for raw in candidates:
        cleaned = _clean_env(raw)
        if not cleaned or cleaned == "0":
            continue
        if not cleaned.isdigit():
            raise ValueError(f"Invalid pull request number: {cleaned!r}")
        number = int(cleaned)
        if number > 0:
            return number
    return None


def parse_commit_sha(*candidates: str | None) -> str | None:
    """Return the first valid 40-character hex commit SHA from candidates."""
    for raw in candidates:
        cleaned = _clean_env(raw)
        if not cleaned:
            continue
        if not SHA_RE.fullmatch(cleaned):
            raise ValueError(f"Invalid 40-char commit SHA: {cleaned!r}")
        return cleaned
    return None


def _validate_https_base_url(url: str, label: str) -> str:
    """Ensure GitHub base URLs use HTTPS before issuing requests."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"{label} must be a valid https:// URL, got {url!r}")
    return url.rstrip("/")


def _github_api_json(
    method: str,
    url: str,
    token: str,
    payload: dict[str, Any] | None = None,
) -> Any:
    """Execute an authenticated GitHub REST API request and parse JSON output."""
    _validate_https_base_url(url, "GitHub API request URL")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ucp-governance-gate",
    }
    body_bytes: bytes | None = None
    if payload is not None:
        headers["Content-Type"] = "application/json; charset=utf-8"
        body_bytes = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        try:
            err_body = exc.read(512).decode("utf-8", errors="replace").strip()
        finally:
            exc.close()
        detail = f": {err_body}" if err_body else ""
        raise GitHubApiError(
            exc.code,
            f"GitHub API {method} {url} failed with HTTP {exc.code}{detail}",
        ) from exc


def _match_open_head_sha(pulls: object, commit_sha_lower: str) -> int | None:
    """Return the PR number of an open pull request whose head SHA matches."""
    if not isinstance(pulls, list):
        return None
    for pr in pulls:
        if (
            isinstance(pr, dict)
            and pr.get("state") == "open"
            and isinstance(pr.get("head"), dict)
            and isinstance(pr["head"].get("sha"), str)
            and pr["head"]["sha"].lower() == commit_sha_lower
            and isinstance(pr.get("number"), int)
        ):
            return pr["number"]
    return None


def resolve_pr_number_from_sha(
    api_url: str,
    repo: str,
    commit_sha: str,
    token: str,
) -> int | None:
    """Resolve the PR number associated with a commit SHA via GitHub REST API.

    Queries open pull requests directly first (covering both fork and same-repo
    PRs without search index lag, since `/commits/{sha}/pulls` omits fork PRs),
    then checks `/commits/{sha}/pulls`, and finally falls back to `/search/issues`
    preferring open pull requests.
    """
    commit_sha_lower = commit_sha.lower()

    # 1. Scan open PRs ordered by most recently updated (covers fork PRs with zero index lag).
    for page in range(1, MAX_OPEN_PR_PAGES + 1):
        open_pulls_url = (
            f"{api_url}/repos/{repo}/pulls"
            f"?state=open&sort=updated&direction=desc&per_page={OPEN_PRS_PER_PAGE}&page={page}"
        )
        try:
            page_pulls = _github_api_json("GET", open_pulls_url, token)
        except (GitHubApiError, urllib.error.HTTPError) as exc:
            status = getattr(exc, "status_code", getattr(exc, "code", "unknown"))
            print(
                f"Warning: open-pulls lookup returned HTTP {status}; falling back.",
                file=sys.stderr,
            )
            break

        matched = _match_open_head_sha(page_pulls, commit_sha_lower)
        if matched is not None:
            return matched
        if not isinstance(page_pulls, list) or len(page_pulls) < OPEN_PRS_PER_PAGE:
            break

    # 2. Check commit-to-pulls (covers same-repo branches beyond the open-PR window).
    commits_pulls_url = f"{api_url}/repos/{repo}/commits/{commit_sha}/pulls"
    try:
        pulls = _github_api_json("GET", commits_pulls_url, token)
    except (GitHubApiError, urllib.error.HTTPError) as exc:
        status = getattr(exc, "status_code", getattr(exc, "code", "unknown"))
        print(
            f"Warning: commit-to-pulls lookup returned HTTP {status}; falling back to search.",
            file=sys.stderr,
        )
        pulls = []

    if isinstance(pulls, list) and pulls:
        matched = _match_open_head_sha(pulls, commit_sha_lower)
        if matched is not None:
            return matched
        for pr in pulls:
            if (
                isinstance(pr, dict)
                and pr.get("state") == "open"
                and isinstance(pr.get("number"), int)
            ):
                return pr["number"]
        for pr in pulls:
            if isinstance(pr, dict) and isinstance(pr.get("number"), int):
                return pr["number"]

    # 3. Fall back to Search API, preferring open PRs over closed duplicates.
    query = urllib.parse.quote(f"repo:{repo} is:pr {commit_sha}")
    search_url = f"{api_url}/search/issues?q={query}&per_page=10"
    search_result = _github_api_json("GET", search_url, token)
    if isinstance(search_result, dict):
        items = search_result.get("items")
        if isinstance(items, list) and items:
            for item in items:
                if (
                    isinstance(item, dict)
                    and item.get("state") == "open"
                    and isinstance(item.get("number"), int)
                ):
                    return item["number"]
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("number"), int):
                    return item["number"]
    return None


def resolve_head_sha_from_pr(
    api_url: str,
    repo: str,
    pr_number: int,
    token: str,
) -> str | None:
    """Fetch the current head commit SHA of a pull request."""
    pr_data = _github_api_json(
        "GET", f"{api_url}/repos/{repo}/pulls/{pr_number}", token
    )
    if isinstance(pr_data, dict) and isinstance(pr_data.get("head"), dict):
        return parse_commit_sha(pr_data["head"].get("sha"))
    return None


def escape_workflow_annotation(text: str) -> str:
    """Escape multiline text for GitHub Actions ::notice / ::error commands."""
    return text.replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def _append_step_summary(step_summary_path: str | None, text: str) -> None:
    """Append text to GITHUB_STEP_SUMMARY if configured."""
    if not step_summary_path or not text:
        return
    with Path(step_summary_path).open("a", encoding="utf-8") as handle:
        handle.write(text)
        if not text.endswith("\n"):
            handle.write("\n")


def _is_validator_execution_error(
    eval_exit_code: int,
    summary_text: str | None,
) -> bool:
    """Return True when a non-zero validator exit indicates a runtime error."""
    if eval_exit_code == 0:
        return False
    if eval_exit_code != 1 or summary_text is None:
        return True
    stripped = summary_text.lstrip()
    return not stripped or stripped.startswith("ERROR:")


def publish_summary_and_annotation(
    eval_exit_code: int,
    summary_file: Path,
    step_summary_path: str | None,
    summary_text: str | None = None,
) -> None:
    """Append summary.txt to GITHUB_STEP_SUMMARY and emit a workflow annotation."""
    if summary_text is None:
        if not summary_file.is_file():
            return
        summary_text = summary_file.read_text(encoding="utf-8")

    _append_step_summary(step_summary_path, summary_text)

    escaped = escape_workflow_annotation(summary_text)
    if eval_exit_code == 0:
        print(f"::notice title=Approval Status::{escaped}")
    else:
        print(f"::error title=Missing Approvals::{escaped}")


def post_commit_status(
    api_url: str,
    server_url: str,
    repo: str,
    commit_sha: str,
    run_id: str,
    status_token: str,
    *,
    eval_exit_code: int = 0,
    state: str | None = None,
    description: str | None = None,
) -> None:
    """Post the Governance / Approvals commit status check to GitHub."""
    resolved_state = state or ("success" if eval_exit_code == 0 else "failure")
    resolved_description = description or (
        "Governance approvals met"
        if resolved_state == "success"
        else "Pending required approvals"
    )
    payload: dict[str, Any] = {
        "state": resolved_state,
        "context": STATUS_CONTEXT,
        "description": resolved_description,
    }
    if run_id:
        payload["target_url"] = f"{server_url}/{repo}/actions/runs/{run_id}"

    status_url = f"{api_url}/repos/{repo}/statuses/{commit_sha}"
    _github_api_json("POST", status_url, status_token, payload=payload)


def run_gate(
    env: dict[str, str] | None = None,
    validator_script: Path | None = None,
    summary_file: Path | None = None,
) -> int:
    """Run the end-to-end governance gate workflow step."""
    environ = env if env is not None else dict(os.environ)

    org_read_token = _clean_env(environ.get("ORG_READ_TOKEN"))
    status_token = _clean_env(environ.get("STATUS_TOKEN"))
    if not org_read_token:
        print("::error::ORG_READ_TOKEN is required.", file=sys.stderr)
        return 1
    if not status_token:
        print("::error::STATUS_TOKEN is required.", file=sys.stderr)
        return 1

    org = _clean_env(
        environ.get("GITHUB_ORG") or environ.get("GITHUB_REPOSITORY_OWNER")
    )
    repo = _clean_env(environ.get("GITHUB_REPO") or environ.get("GITHUB_REPOSITORY"))
    if not org or not ORG_RE.fullmatch(org):
        print(f"::error::Invalid GitHub organization: {org!r}", file=sys.stderr)
        return 1
    if not repo or not REPO_RE.fullmatch(repo):
        print(f"::error::Invalid GitHub repository: {repo!r}", file=sys.stderr)
        return 1

    run_id = _clean_env(environ.get("GITHUB_RUN_ID"))
    rules_file = _clean_env(environ.get("INPUT_RULES_FILE"))

    try:
        api_url = _validate_https_base_url(
            _clean_env(environ.get("GITHUB_API_URL")) or "https://api.github.com",
            "GITHUB_API_URL",
        )
        server_url = _validate_https_base_url(
            _clean_env(environ.get("GITHUB_SERVER_URL")) or "https://github.com",
            "GITHUB_SERVER_URL",
        )
        pr_number = parse_pr_number(
            environ.get("INPUT_PR_NUMBER"),
            environ.get("EVENT_PR_NUMBER"),
            environ.get("EVENT_WORKFLOW_RUN_PR_NUMBER"),
        )
        commit_sha = parse_commit_sha(
            environ.get("INPUT_COMMIT_SHA"),
            environ.get("EVENT_PR_HEAD_SHA"),
            environ.get("EVENT_WORKFLOW_RUN_HEAD_SHA"),
        )
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    if pr_number is None and commit_sha is not None:
        print(f"Resolving pull request number for commit {commit_sha}...")
        pr_number = resolve_pr_number_from_sha(
            api_url, repo, commit_sha, org_read_token
        )

    if pr_number is None:
        print("::error::PR number could not be resolved.", file=sys.stderr)
        return 1

    # Verify the PR's live head SHA before running pr_validator.py so we never
    # evaluate a newer commit and stamp its verdict onto a superseded SHA.
    live_head_sha = resolve_head_sha_from_pr(api_url, repo, pr_number, org_read_token)
    if live_head_sha is None:
        print("::error::Commit SHA could not be resolved.", file=sys.stderr)
        return 1

    if commit_sha is None:
        commit_sha = live_head_sha
    elif live_head_sha.lower() != commit_sha.lower():
        print(
            f"::notice title=Superseded Commit::Skipping governance status for "
            f"{commit_sha}; PR #{pr_number} is now at {live_head_sha}."
        )
        return 0

    script_path = (
        validator_script
        if validator_script is not None
        else Path(__file__).resolve().parent / "pr_validator.py"
    )
    summary_path = summary_file if summary_file is not None else Path("summary.txt")
    if summary_path.exists():
        summary_path.unlink()

    cmd = [
        "uv",
        "run",
        str(script_path),
        "--token",
        org_read_token,
        "--org",
        org,
        "--repo",
        repo,
        "--pr",
        str(pr_number),
    ]
    if rules_file:
        cmd.extend(["--rules-file", rules_file])

    proc = subprocess.run(cmd, check=False)
    eval_exit_code = proc.returncode

    # Re-verify the PR head SHA after evaluation to prevent TOCTOU races if a
    # force-push occurred while pr_validator.py was fetching PR files/reviews.
    post_eval_head_sha = resolve_head_sha_from_pr(
        api_url, repo, pr_number, org_read_token
    )
    if post_eval_head_sha is None or post_eval_head_sha.lower() != commit_sha.lower():
        print(
            f"::notice title=Superseded Commit::Skipping governance status for "
            f"{commit_sha}; PR #{pr_number} head changed to {post_eval_head_sha!r} "
            f"during evaluation."
        )
        return 0

    step_summary_path = _clean_env(environ.get("GITHUB_STEP_SUMMARY")) or None
    summary_text = (
        summary_path.read_text(encoding="utf-8") if summary_path.is_file() else None
    )

    if _is_validator_execution_error(eval_exit_code, summary_text):
        has_summary_detail = bool(summary_text and summary_text.strip())
        error_detail = (
            summary_text.strip()
            if has_summary_detail and summary_text is not None
            else (
                f"pr_validator.py exited with code {eval_exit_code} "
                f"without producing {summary_path.name}."
            )
        )
        _append_step_summary(
            step_summary_path,
            summary_text
            if has_summary_detail and summary_text is not None
            else f"ERROR: {error_detail}",
        )
        escaped_error = escape_workflow_annotation(error_detail)
        print(
            f"::error title=Validator Execution Failed::{escaped_error}",
            file=sys.stderr,
        )
        post_commit_status(
            api_url=api_url,
            server_url=server_url,
            repo=repo,
            commit_sha=commit_sha,
            run_id=run_id,
            status_token=status_token,
            state="error",
            description="Governance validator execution failed",
        )
        return eval_exit_code if eval_exit_code > 0 else 1

    publish_summary_and_annotation(
        eval_exit_code=eval_exit_code,
        summary_file=summary_path,
        step_summary_path=step_summary_path,
        summary_text=summary_text,
    )

    post_commit_status(
        api_url=api_url,
        server_url=server_url,
        repo=repo,
        commit_sha=commit_sha,
        run_id=run_id,
        status_token=status_token,
        eval_exit_code=eval_exit_code,
    )
    return 0


def main() -> None:
    """CLI entrypoint."""
    try:
        sys.exit(run_gate())
    except Exception as exc:
        print(f"::error::Governance gate execution failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
