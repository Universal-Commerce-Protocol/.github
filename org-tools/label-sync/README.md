# GitHub Label Synchronization Tool

A Python CLI utility to synchronize label configurations from central YAML files (`general-labels.yml` and `triage-labels.yml`) to GitHub organization repositories.

---

## 📝 Configuration Format

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

### 🔄 In-Place Label Renaming Example

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

> [!NOTE]
> **Why this safe approach?**
> By keeping this transition explicit and avoiding automated destructive merges or deletions, the tool guarantees that no label configurations are merged by accident in the future if configuration files are modified or copy-pasted incorrectly.

---

## 🚀 Running the Label Sync CLI

This tool is designed to run easily with [**`uv`**](https://docs.astral.sh/uv/), which handles dependencies automatically.

> **Note:** If you do not have `uv` installed, refer to the [uv Installation Guide](https://docs.astral.sh/uv/getting-started/installation/).

### 1. Dry Run (Preview Changes)

By default, the tool runs in Dry-Run mode to preview operations safely without making live changes:

```bash
uv run org-tools/label-sync/sync_labels.py \
  --token "YOUR_GITHUB_TOKEN" \
  --org "YOUR_ORGANIZATION" \
  --repos "my-repository"
```

### 2. Targeting Specific Repositories (Filter)

#### Sync all repositories except excluded ones (Most Common)

This is the standard way to synchronize labels across your entire GitHub organization while skipping internal or special repositories (like `.github` or sandbox):

```bash
uv run org-tools/label-sync/sync_labels.py \
  --token "YOUR_GITHUB_TOKEN" \
  --org "YOUR_ORGANIZATION" \
  --all-repos \
  --exclude-repos ".github,sandbox" \
  --apply
```

#### Sync specific repositories

If you only want to target a specific subset of repositories:

```bash
uv run org-tools/label-sync/sync_labels.py \
  --token "YOUR_GITHUB_TOKEN" \
  --org "YOUR_ORGANIZATION" \
  --repos "repo-a,repo-b" \
  --apply
```

---

## 🧪 Running Unit Tests Offline

To run the offline test suite for label sync from the root of the repository:

```bash
uv run org-tools/label-sync/test_sync_labels.py
```
