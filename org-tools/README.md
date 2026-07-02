# GitHub Organization-Wide Tools

This directory contains CLI utilities and configuration files for organization-wide metadata syncing, label management, and pull request governance.

---

## 📁 Directory Structure

```text
org-tools/
├── governance/  # PR governance gate and approval verification (see governance/README.md)
├── label-sync/  # GitHub label synchronization utility (see label-sync/README.md)
└── triage/      # Central PR triage and labeling automation (see triage/README.md)
```

---

## 🛠️ Available Tools

- **[🏷️ GitHub Label Synchronization Tool](label-sync/README.md)**: Synchronizes custom label configurations from central YAML files to organization repositories.
- **[🛡️ Automated Governance Gate](governance/README.md)**: Enforces path-based repository ownership rules and PR approval thresholds.
- **[🤖 Central PR Triage Tool](triage/README.md)**: Automatically applies the `status:needs-triage` label to eligible open, non-draft Pull Requests.

---

## 🧪 Running Unit Tests Offline

You can run all unit tests locally from the root of the repository:

```bash
# Run all tests
uv run python3 -m unittest discover -s org-tools/governance/tests && \
uv run python3 -m unittest discover -s org-tools/label-sync && \
uv run python3 -m unittest discover -s org-tools/triage/tests
```
