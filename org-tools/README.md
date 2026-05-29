# GitHub Label Synchronization Tool

A local Python CLI utility to synchronize label configurations from central YAML files to GitHub organization repositories.

Note that this script only changes the Label name/color/description and avoids any manipulation of label assignment to issues or pull requests.

---

## 📝 Configuration Format

Each YAML configuration file expects a list of label objects:

```yaml
- name: "type/bug"
  color: "d73a4a"
  description: "Something is broken or not working as expected"
  aliases:
    - "bug"
    - "defect"
```

### Fields:

- **`name`** (Required): The final target name for the label on GitHub.
- **`color`** (Required): A 6-character hex code without a leading `#` (e.g., `"d73a4a"`).
- **`description`** (Optional): A short description of the label.
- **`aliases`** (Optional): A list of previous names. If found, the tool will perform an in-place rename to the target `name` on GitHub, preserving all existing Issue/PR assignments.

> **Conflict Validation Policy:**
>
> | Config Scenario        | Example Case                                                 | Result                               |
> | :--------------------- | :----------------------------------------------------------- | :----------------------------------- |
> | **Duplicate Names**    | Label `bug` in File A and Label `bug` in File B              | ❌ **Forbidden** (Duplicate Error)   |
> | **Name-Alias Overlap** | Label `type/bug` has Alias `bug`, AND Label `bug` is defined | ❌ **Forbidden** (Conflict Error)    |
> | **Shared Aliases**     | Label `type/bug` and `defect` both have Alias `issue`        | ❌ **Forbidden** (Conflict Error)    |
> | **Cyclic Redirects**   | Label A has alias B, Label B has alias A                     | ❌ **Forbidden** (Cyclic Loop Error) |

### 🔄 In-Place Label Renaming Example

If you want to rename an existing label (e.g., from `bug` to `type/bug`) without losing any of the issues or PRs currently associated with it:

1. Define the new target **`name`** (e.g. `type/bug`) that does not exist already.
2. Add the old label name (e.g. `bug`) inside the **`aliases`** list:

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
- **What to do if BOTH exist on GitHub:**
  This script does not support merging labels because of destructive side effects.
  If both `bug` and `type/bug` already exist, the rename call is safely skipped to prevent API errors. If you want to merge them:
  1. In GitHub, filter issues by `label:bug`, select all, and bulk-add the `type/bug` label.
  2. Go to GitHub's repository label settings and manually delete the old `bug` label.
     This will prevent any accidental merge of labels which could have sever consequences on underlying issues or pull requests.

> [!NOTE]
> **Why this safe approach?**
> By keeping this transition explicit and avoiding automated destructive merges or deletions, the tool guarantees that no label configurations are merged by accident in the future if configuration files are modified or copy-pasted incorrectly. This safety mechanism is specifically designed to safeguard your data when both the new standardized label and the old alias label already exist and have active issues or pull requests assigned to them.

---

## 🚀 Running the CLI

This tool is designed to run easily with **`uv`**, which handles dependencies automatically.

### 🔑 Prerequisites (Token Permissions)

Before running the tool, ensure you have a [GitHub Personal Access Token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens) (`--token`) with proper access to the organization and its repositories to manage labels.

### 1. Dry Run (Preview Changes)

By default, the tool runs in Dry-Run mode to preview operations safely without making live changes:

```bash
uv run org-tools/sync_labels.py \
  --token "YOUR_GITHUB_TOKEN" \
  --org "YOUR_ORGANIZATION" \
  --repos "demo-repository"
```

### 2. Targeting Specific Repositories (Filter)

Use the `--repos` flag to specify which repositories to sync, or `--all-repos` with `--exclude-repos` to filter specific ones out:

```bash
# Sync specific repositories
uv run org-tools/sync_labels.py \
  --token "YOUR_GITHUB_TOKEN" \
  --org "YOUR_ORGANIZATION" \
  --repos "repo-a,repo-b" \
  --apply

# Sync all repositories except excluded ones
uv run org-tools/sync_labels.py \
  --token "YOUR_GITHUB_TOKEN" \
  --org "YOUR_ORGANIZATION" \
  --all-repos \
  --exclude-repos ".github,sandbox" \
  --apply
```

---

## 🧪 Running Unit Tests Offline

To run the offline test suite:

```bash
uv run org-tools/test_sync_labels.py
```
