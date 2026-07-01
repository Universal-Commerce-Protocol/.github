# GitHub Organization Profile & Workflow Tools

This directory contains CLI utilities and configuration files for organization-wide metadata syncing, label management, and pull request governance.

## 📖 Table of Contents

- [📁 Directory Structure](#directory-structure)
- [🏷️ GitHub Label Synchronization Tool](#github-label-synchronization-tool)
  - [📝 Configuration Format](#configuration-format)
  - [🚀 Running the Label Sync CLI](#running-the-label-sync-cli)
  - [🧪 Running Label Sync Unit Tests Offline](#running-label-sync-unit-tests-offline)
- [🛡️ Automated Governance Gate](#automated-governance-gate)
  - [📝 Example Governance Configuration](#governance-configuration-format)
  - [🛠️ Reusable Governance Gate Integration](#reusable-governance-gate-integration)
  - [🚀 Running the Governance Check CLI](#running-the-governance-check-cli)
  - [🧪 Running Governance Unit Tests Offline](#running-governance-unit-tests-offline)
- [🤖 Central PR Triage Tool](#central-pr-triage-tool)
  - [🚀 Running the Triage CLI](#running-the-triage-cli)
  - [🧪 Running Triage Unit Tests Offline](#running-triage-unit-tests-offline)
- [🔬 GitHub Actions Branch Testing](#github-actions-branch-testing)

## <a id="directory-structure"></a>📁 Directory Structure

```text
org-tools/
├── governance/
│   ├── governance_check.py          # Python runner for PR verification
│   ├── test_governance_check.py     # Offline test suite for governance check
│   └── validate_governance_rules.py # Utility to validate rules configurations
├── label-sync/
│   ├── labels/
│   │   ├── general-labels.yml       # YAML catalog for standard labels
│   │   └── triage-labels.yml        # YAML catalog for triage labels
│   ├── sync_labels.py              # Python sync runner for GitHub labels
│   └── test_sync_labels.py         # Offline test suite for label sync
├── triage/
│   ├── README.md                    # Handbook for the PR triage tool
│   ├── scripts/
│   │   ├── triage_cli.py            # CLI entry point for triage
│   │   ├── triage_logic.py          # Core triage logic
│   │   └── triage_pr_models.py      # PR data models for triage
│   └── tests/                       # Test suite for triage
└── README.md                       # Handbook for org utilities
```

---

## <a id="github-label-synchronization-tool"></a>🏷️ GitHub Label Synchronization Tool

A Python CLI utility to synchronize label configurations from central YAML files (`general-labels.yml` and `triage-labels.yml`) to GitHub organization repositories.

### <a id="configuration-format"></a>📝 Configuration Format

Label lists are configured as YAML blocks:

```yaml
- name: "type/bug"
  color: "d73a4a"
  description: "Something is broken or not working as expected"
  aliases:
    - "bug"
    - "defect"
```

- **`name`** (Required): The final target name for the label on GitHub.
- **`color`** (Required): A 6-character hex code without a leading `#` (e.g., `"d73a4a"`).
- **`description`** (Optional): A short description of the label.
- **`aliases`** (Optional): A list of previous names. If found, the tool will perform an in-place rename to the target `name` on GitHub, preserving all existing Issue/PR assignments.

#### 🔄 In-Place Label Renaming Example

If you want to rename an existing label (e.g., from `bug` to `type/bug`) without losing any of the issues or PRs currently associated with it:

1. Define the new target **`name`** as `type/bug`.
2. Add the old label name `bug` inside the **`aliases`** list:

```yaml
- name: "type/bug"
  color: "d73a4a"
  description: "Something is broken or not working as expected"
  aliases:
    - "bug"
```

**How it works under the hood:**

- **If `type/bug` does NOT exist in the repository, but `bug` DOES exist:** The script will rename `bug` to `type/bug` in-place. All issues and pull requests previously tagged with `bug` will now be automatically tagged with `type/bug`!
- **If `type/bug` ALREADY exists in the repository:** The script will update `type/bug` (color/description) to match your configuration. However, to prevent destructive API failures, it **will not** automatically delete `bug`.
- **What to do if BOTH exist on GitHub:** If both `bug` and `type/bug` already exist, the rename call is safely skipped to prevent API errors. If you want to merge them, filter issues by `label:bug`, bulk-add `type/bug`, and then manually delete the old `bug` label.

> **Note (Why this safe approach?):** By keeping this transition explicit and avoiding automated destructive merges or deletions, the tool guarantees that no label configurations are merged by accident in the future if configuration files are modified or copy-pasted incorrectly.

---

### <a id="running-the-label-sync-cli"></a>🚀 Running the Label Sync CLI

This tool is designed to run easily with [**`uv`**](https://docs.astral.sh/uv/), which handles dependencies automatically.

> **Note:** If you do not have `uv` installed, refer to the [uv Installation Guide](https://docs.astral.sh/uv/getting-started/installation/).

#### 1. Dry Run (Preview Changes)

By default, the tool runs in Dry-Run mode to preview operations safely without making live changes:

```bash
uv run org-tools/label-sync/sync_labels.py \
  --token "YOUR_GITHUB_TOKEN" \
  --org "YOUR_ORGANIZATION" \
  --repos "my-repository"
```

#### 2. Targeting Specific Repositories (Filter)

##### Sync all repositories except excluded ones (Most Common)

This is the standard way to synchronize labels across your entire GitHub organization while skipping internal or special repositories (like `.github` or sandbox):

```bash
uv run org-tools/label-sync/sync_labels.py \
  --token "YOUR_GITHUB_TOKEN" \
  --org "YOUR_ORGANIZATION" \
  --all-repos \
  --exclude-repos ".github,sandbox" \
  --apply
```

##### Sync specific repositories

If you only want to target a specific subset of repositories:

```bash
uv run org-tools/label-sync/sync_labels.py \
  --token "YOUR_GITHUB_TOKEN" \
  --org "YOUR_ORGANIZATION" \
  --repos "repo-a,repo-b" \
  --apply
```

### <a id="running-label-sync-unit-tests-offline"></a>🧪 Running Label Sync Unit Tests Offline

To run the offline test suite for label sync:

```bash
uv run org-tools/label-sync/test_sync_labels.py
```

---

## <a id="automated-governance-gate"></a>🛡️ Automated Governance Gate

An automated status check utility that enforces path-based repository governance and pull request approval thresholds. It matches modified files against organization ownership rules and verifies reviews using the GitHub API.

### <a id="governance-configuration-format"></a>📝 Example Governance Configuration (`.github/governance-rules.yml`)

The repository governance structure is defined in `.github/governance-rules.yml`. Below is an example configuration showing how to configure emergency bypass overrides, fallback rules for unmatched files, and targeted path-based approval requirements:

```yaml
# list of proxy reviewers authorized for emergency bypass overrides
proxy_reviewers:
  - user-a
  - user-b

# fallback rule applied when no specific rules match
fallback:
  name: "Governance Fallback"
  requirements:
    - team: "governance-council"
      threshold: 1

# path-specific rules
rules:
  - name: "Governance & Meta"
    patterns:
      - "LICENSE"
      - "GOVERNANCE.md"
      - "CODEOWNERS"
      - ".github/governance-rules.yml"
    requirements:
      - team: "governance-council"
        threshold: 1

  - name: "Technical Committee Core"
    patterns:
      - "source/**"
      - "schemas/**"
    requirements:
      - team: "technical-committee"
        threshold: 2
      - team: "governance-council"
        threshold: 1
```

#### Core Rules & Guardrails

1. **Cumulative Union Matching**: If a modified file matches multiple rules in `governance-rules.yml`, it must satisfy the approval requirements of **all** matching rules.
2. **Strict Change Requests**: If _any_ authorized reviewer for a matching rule has requested changes (`CHANGES_REQUESTED`), the PR is strictly blocked even if approval thresholds are met.
3. **Self-Approvals**: PR authors cannot approve their own changes to satisfy rule thresholds.
4. **Emergency Bypass Override**: If any user in the `proxy_reviewers` list approves the PR, all governance gate requirements are bypassed (Emergency Override).
5. **Fail-Secure Fallback**: If any modified file does not match any rule in the `rules:` list, the `fallback` rule is applied for evaluation.
6. **Draft Pull Requests**: Governance checks are automatically skipped for draft pull requests at the workflow level to save CI resources and prevent pending check blocks.

---

### <a id="reusable-governance-gate-integration"></a>🛠️ Reusable Governance Gate Integration

Integrating the automated governance gate into a target repository follows a 3-step process: local creation, local verification, and target deployment.

#### Step 1: Create Governance Rules & Workflow Files Locally

First, create the rules and workflow configuration files locally in this repository to define your setup:

1. **Governance Rules Configuration**: Create a new file `.github/proposed_governance_rules.yml` to define your path-specific rules, requirements, and teams. This should be similar to `.github/governance-rules.yml` without the comments and instructions.
2. **Caller Workflow Configuration**: Create a caller workflow file `.github/workflows/proposed_governance.yml` with the following structure:

```yaml
name: PR Governance

on:
  pull_request_target:
    types: [opened, synchronize, reopened, ready_for_review]
  pull_request_review:
    types: [submitted, dismissed]

# Prevent concurrent evaluations of the same PR to save CI resources
concurrency:
  group: ${{ github.workflow }}-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  governance:
    name: Approvals
    # skip for draft PRs
    if: github.event.pull_request.draft == false
    # Use the reusable workflow defined in the central governance repository
    uses: <your-organization>/<your-org-tools-repo>/.github/workflows/reusable-governance.yml@main
    with:
      # Optional: Path to custom governance rules inside this repository (default: .github/governance-rules.yml)
      governance_rules_file: ".github/governance-rules.yml"
    secrets:
      # Required: An org-level Read token to read team memberships
      ORG_READ_TOKEN: ${{ secrets.ORG_READ_TOKEN }}
```

> **Note (Why `pull_request_target`?):** The workflow runs using `pull_request_target` to safely access secrets (like `ORG_READ_TOKEN`) required for querying organization team memberships.

#### Step 2: Verify Your Local Configuration

Run the local validation tool to ensure the rules structure is valid before deploying to the target repository.

##### 1. Complete End-to-End Validation (Highly Recommended)

Verify your rule syntax, check file coverage, and connect to GitHub to ensure all referenced teams exist in the organization:

```bash
uv run org-tools/governance/validate_governance_rules.py \
  --governance-rules-file .github/proposed_governance_rules.yml \
  --org "YOUR_ORGANIZATION" \
  --token "YOUR_GITHUB_TOKEN"
```

##### 2. Offline File Coverage Check

Check which files in your repository will fall back to the default rule (i.e. are not matched by any path rules):

```bash
uv run org-tools/governance/validate_governance_rules.py \
  --governance-rules-file .github/proposed_governance_rules.yml \
  --check-coverage
```

##### 3. Offline Syntax Check Only

Perform a quick offline verification of the rules YAML file format and syntax:

```bash
uv run org-tools/governance/validate_governance_rules.py \
  --governance-rules-file .github/proposed_governance_rules.yml
```

#### Step 3: Deploy to the Target Repository

Once verified, copy these configuration files to your target repository, renaming the rules configuration to `governance-rules.yml` (convention) and the workflow file to `governance.yml` (convention).

> **Note:** Example commands below assume the repositories are cloned next to each other in the same parent directory so the `../` reference works.

1. **Copy the rules file**: Copy `.github/proposed_governance_rules.yml` to the root `.github/governance-rules.yml` of the target repository:
   ```bash
   cp .github/proposed_governance_rules.yml ../<your-target-repo>/.github/governance-rules.yml
   ```
2. **Copy the workflow file**: Copy `.github/workflows/proposed_governance.yml` to the `.github/workflows/governance.yml` of the target repository:
   ```bash
   cp .github/workflows/proposed_governance.yml ../<your-target-repo>/.github/workflows/governance.yml
   ```
   _Make sure the `uses:` key in the workflow points to correct values for `<your-organization>/<your-org-tools-repo>/.github/workflows/reusable-governance.yml@main`._

---

### <a id="running-the-governance-check-cli"></a>🚀 Running the Governance Check CLI

To execute the governance check runner locally or within a GitHub actions workflow:

```bash
uv run org-tools/governance/governance_check.py \
  --token "YOUR_GITHUB_TOKEN" \
  --org "YOUR_ORGANIZATION" \
  --repo "YOUR_ORGANIZATION/target-repo" \
  --pr 111
```

### <a id="running-governance-unit-tests-offline"></a>🧪 Running Governance Unit Tests Offline

To run the offline test suite for the governance validation engine:

```bash
uv run org-tools/governance/test_governance_check.py
```

---

---

## <a id="central-pr-triage-tool"></a>🤖 Central PR Triage Tool

An automated utility that applies the `status:needs-triage` label to eligible open Pull Requests across one or more repositories in the organization.

For detailed documentation on how the triage rules are evaluated, how to configure the GitHub Actions cron job, and advanced usage, see the [Triage Tool Handbook](triage/README.md).

### <a id="running-the-triage-cli"></a>🚀 Running the Triage CLI

This tool is designed to run easily with [**`uv`**](https://docs.astral.sh/uv/):

#### 1. Dry Run (Preview Changes)

By default, the tool runs in Dry-Run mode to preview which PRs would be labeled without making live changes:

```bash
uv run org-tools/triage/scripts/triage_cli.py \
  --token "YOUR_GITHUB_TOKEN" \
  --org "YOUR_ORGANIZATION" \
  --repos "repo-a,repo-b"
```

#### 2. Apply Labels

To actually apply the `status:needs-triage` label to eligible PRs, pass the `--apply` flag:

```bash
uv run org-tools/triage/scripts/triage_cli.py \
  --token "YOUR_GITHUB_TOKEN" \
  --org "YOUR_ORGANIZATION" \
  --repos "repo-a,repo-b" \
  --apply
```

### <a id="running-triage-unit-tests-offline"></a>🧪 Running Triage Unit Tests Offline

To run the offline test suite for the triage tool:

```bash
uv run --with pygithub --with click python3 -m unittest discover -s org-tools/triage/tests
```

---

## <a id="github-actions-branch-testing"></a>🔬 GitHub Actions Branch Testing

To test the reusable workflow end-to-end on GitHub before merging changes to `main`:

### Step A: Point to the Test Branch

In your caller workflow, temporarily change the `@main` ref to point to your test branch (e.g. `@test-workflow-action-governance`):

```yaml
uses: <your-organization>/<your-org-tools-repo>/.github/workflows/reusable-governance.yml@test-workflow-action-governance
```

### Step B: Trigger a Pull Request

1. Commit and push the caller workflow change.
2. Open a test Pull Request on a test branch (e.g. `test-main-branch-2`).
3. Modify different files in the PR to trigger different path-based owner rules.
4. Verify the check reports success (🟢) or pending approval status (🔴) correctly under the PR checks list.
5. Submit approvals from members of different teams to verify the threshold logic updates dynamically.

### Step C: Clean Up

Once tests pass, change the workflow reference back to `@main` before merging to production.
