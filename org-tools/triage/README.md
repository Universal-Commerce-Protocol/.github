# Central PR Triage Tool

This tool automatically applies the `status:needs-triage` label to eligible Pull Requests (PRs) and marks blocked PRs as `status:stale` if they have been blocked for more than 21 days. It is designed to run centrally as a cron job.

---

## Architecture & Flow

The tool consists of a CLI entry point ([triage_cli.py](scripts/triage_cli.py)) and the core triage logic ([triage_logic.py](scripts/triage_logic.py)).

### Execution Flow

1.  **CLI Initialization**: Parses command-line options (e.g., `--token`, `--org`, `--repos`, `--pr`) and initializes the GitHub client.
2.  **Mode Selection**:
    - **Single PR Mode**: If `--pr` is specified, the tool fetches the specific PR from the target `--repos` (which must contain exactly one repository) and triages it.
    - **Bulk Mode**: If `--pr` is not specified, the tool enters bulk triage mode.
3.  **Upfront Access Pre-Check (Bulk Mode)**: Iterates through the list of `--repos` and verifies API access for each. If any repository is inaccessible (e.g., 404 or 403), the run is aborted immediately.
4.  **Candidate PR Query (Bulk Mode)**: Queries the GitHub Search API for:
    - Open, non-draft PRs in the target repositories with no labels.
    - Open, non-draft PRs with `status:blocked` label.
5.  **Core Triage Loop**: For each candidate PR, the tool:
    - Fetches its live state from the GitHub API.
    - Evaluates the PR against the **Core Triage Rules**.
    - Applies `status:needs-triage` or `status:stale` labels if eligible (or logs the would-be action if running in dry-run mode).

### Key Features

- **Upfront Access Pre-Check**: In bulk mode, the tool verifies access to all specified repositories before performing any triage work. If any repository is inaccessible (e.g., due to a typo or permission issue), the run is aborted immediately to prevent partial execution.
- **Dry-Run by Default**: The tool will only log what it _would_ do and will not apply labels unless the `--apply` flag is explicitly passed.
- **GitHub Actions Integration**: When run in GitHub Actions, errors are reported directly to the GitHub UI using workflow commands (`::error::`).

---

## Core Triage Rules

When evaluating a PR (either in bulk or single-PR mode), the tool applies the following rules:

### Initial Triage (`status:needs-triage`)

| PR Condition                        |           Action            |
| :---------------------------------- | :-------------------------: |
| Open, not draft, and **no labels**  | Apply `status:needs-triage` |
| Closed, draft, or has **any label** |            Skip             |

### Blocked PRs (`status:stale`)

When a PR has the `status:blocked` label, the tool checks how long it has been blocked:

| PR Condition                                                                    |        Action        |
| :------------------------------------------------------------------------------ | :------------------: |
| Open, has `status:blocked`, lacks `status:stale`, and blocked for **> 21 days** | Apply `status:stale` |
| Otherwise                                                                       |         Skip         |

> [!IMPORTANT]
> Since the triage tool does not automatically skip PRs with active reviewers or reviews, applying any label (such as `status:under-review`) is the primary way to signal that a PR is currently active and should not be marked as needing triage.

---

## Example Console Outputs

Here are examples of how the tool behaves and logs information in different scenarios:

### Scenario 1: Successful Bulk Run (Dry-Run)

Shows a successful pre-check and a mix of would-be labeled and skipped PRs.

```text
=== Starting PR Triage (Dry Run: True) ===
Verifying access to all repositories...
Access verification successful. Starting triage...

Processing Repository: my-org/repo-a
  Search Query (Needs Triage): is:pr is:open -is:draft no:label repo:my-org/repo-a
  Search Query (Blocked): is:pr is:open -is:draft label:"status:blocked" repo:my-org/repo-a
  Found 2 PRs needing initial triage.
  Found 0 blocked PRs to check.
  Total unique PRs to process: 2
  Processing PR #145
    [DRY RUN] Success: PR #145. Would apply 'status:needs-triage'.
  Processing PR #142
    Skipping: PR #142 has other labels: {'status:backlog'}

=== PR Triage Completed Successfully ===
```

> [!NOTE]
> Due to the eventual consistency of the GitHub Search index, PRs that were recently labeled might still temporarily appear in the search results for unlabeled PRs. The tool's core triage loop performs an in-memory check using the live PR state to safely skip these cases.

### Scenario 2: Pre-Check Verification Failure (Aborted Run)

If a repository is inaccessible (e.g. typo or missing permissions), the tool logs the error and aborts immediately before performing any triage.

```text
=== Starting PR Triage (Dry Run: True) ===
Verifying access to all repositories...
Error: Repository not found or access denied: my-org/typo-repo
Aborting: One or more repositories are inaccessible: typo-repo
```

### Scenario 3: Isolated PR Fetch Failure (Resilient Run)

If a specific PR fails to fetch (e.g. temporary API error), the error is logged and skipped, but the rest of the run completes successfully.

```text
=== Starting PR Triage (Dry Run: True) ===
Verifying access to all repositories...
Access verification successful. Starting triage...

Processing Repository: my-org/repo-a
  Search Query (Needs Triage): is:pr is:open -is:draft no:label repo:my-org/repo-a
  Search Query (Blocked): is:pr is:open -is:draft label:"status:blocked" repo:my-org/repo-a
  Found 2 PRs needing initial triage.
  Found 0 blocked PRs to check.
  Total unique PRs to process: 2
  Processing PR #145
    [DRY RUN] Success: PR #145. Would apply 'status:needs-triage'.
  Processing PR #142
    Error processing PR #142 in my-org/repo-a: GithubException (status 500, ...)

=== PR Triage Completed Successfully ===
```

### Scenario 4: Single PR Triage

Shows the output when triaging a single specific PR locally.

```text
=== Starting PR Triage (Dry Run: True) ===

Processing Single PR #123 in my-org/repo-a
  Skipping: PR #123 is a draft.

=== PR Triage Completed Successfully ===
```

---

## CLI Usage

You can run the script locally using `uv` to automatically manage dependencies.

### Arguments & Options

- `--token` (Required): GitHub Personal Access Token. Can also be set via the `ORG_TRIAGE_TOKEN` environment variable.
- `--org` (Required): The target GitHub Organization.
- `--repos` (Required): Comma-separated list of repository names to triage. If `--pr` is specified, this must contain exactly one repository.
- `--pr` (Optional): The specific PR number to triage.
- `--apply` (Optional): If passed, actually applies the label on GitHub. Otherwise, runs in dry-run mode.

### Local Examples

Set your GitHub token:

```bash
export ORG_TRIAGE_TOKEN="your-github-token"
```

Run triage in **dry-run** mode for multiple repositories:

```bash
uv run org-tools/triage/scripts/triage_cli.py --org "my-org" --repos "repo-a,repo-b"
```

Run triage and **apply** labels:

```bash
uv run org-tools/triage/scripts/triage_cli.py --org "my-org" --repos "repo-a,repo-b" --apply
```

Triage a **single specific PR** (dry-run):

```bash
uv run org-tools/triage/scripts/triage_cli.py --org "my-org" --repos "repo-a" --pr 123
```

---

## GitHub Actions Integration

This tool is designed to **run centrally** from this administration repository.

> [!IMPORTANT]
> **No workflow deployment is needed in the target repositories.** The triage tool runs remotely via the GitHub API and only needs to be configured once in this repository.

The automated scheduling is managed by the [.github/workflows/triage-cron.yml](../../.github/workflows/triage-cron.yml) workflow, which runs as an hourly cron job or can be triggered manually.

### Workflow Configuration & Triggers

The workflow behaves differently depending on how it is triggered:

1. **Scheduled Runs (Cron)**:
   - **Trigger**: Automatically runs every hour at minute 37.
   - **Repositories**: Evaluates the repositories specified in the `DEFAULT_REPOS` environment variable defined in the workflow file.
   - **Action**: Automatically runs with the `--apply` flag to apply the `status:needs-triage` label to eligible PRs.

2. **Manual Runs (Workflow Dispatch)**:
   - **Trigger**: Triggered manually via the GitHub Actions tab.
   - **Inputs**:
     - `repos` (Optional): A custom comma-separated list of repositories to triage (defaults to the `DEFAULT_REPOS` list if left empty).
       > [!IMPORTANT]
       > Although this input is optional to allow falling back to `DEFAULT_REPOS`, the resolved list of repositories must not be empty. If both the `repos` input is left blank and `DEFAULT_REPOS` is empty, the workflow will fail with an error.
     - `apply` (Optional): A boolean checkbox to determine whether to actually apply the labels (defaults to `false` / dry-run).

To configure the default repositories for the hourly cron job, edit the `DEFAULT_REPOS` environment variable in [.github/workflows/triage-cron.yml](../../.github/workflows/triage-cron.yml):

```yaml
jobs:
  triage:
    runs-on: ubuntu-latest
    env:
      DEFAULT_REPOS: "repo-a,repo-b"
```

The workflow requires a GitHub Secret named `ORG_TRIAGE_TOKEN` containing a GitHub token with:

1. Read access to the organization's repositories (to search and fetch PRs).
2. Write access to the repositories' labels (to apply the triage label).

### Token Permissions

For `ORG_TRIAGE_TOKEN`, you should generate a **Fine-Grained Personal Access Token (PAT)** with the following configuration:

- **Repository Selection**: Select **Only select repositories** and add the target repositories you want the triage tool to monitor.
- **Repository Permissions**:
  - `Pull requests`: **Read and Write** (required to fetch PRs and apply labels).
  - `Issues`: **Read and Write** (required to manage labels).
  - `Metadata`: **Read-only** (mandatory base permission).

---

## Running Unit Tests

The tool includes a comprehensive suite of unit tests that mock the GitHub API.

To run all unit tests in the triage module:

```bash
uv run python3 -m unittest discover -s org-tools/triage/tests
```

To run a specific test file:

```bash
uv run python3 -m unittest org-tools/triage/tests/test_triage_logic.py
```
