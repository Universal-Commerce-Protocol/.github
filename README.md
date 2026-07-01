# Central Organization Profile & Workflow Tools

This repository serves as the central configuration and automation hub for the organization. It contains shared community health documents, reusable GitHub Actions workflows, and command-line utilities.

---

## 📁 Directory Structure

```
.
├── .github/                        # Shared repository workflows and templates
├── org-tools/                      # Organization automation and CLI utilities (see org-tools/README.md)
├── CODE_OF_CONDUCT.md              # Organization-wide Code of Conduct
├── CONTRIBUTING.md                 # Organization-wide Contributing Guidelines
├── DOMAIN_TECH_COUNCIL_CHARTER.md  # Domain Technical Council Charter
├── GOVERNANCE.md                   # Organization-wide Governance Charter
├── SECURITY.md                     # Organization-wide Security Guidelines
├── TC_ELECTIONS.md                 # Technical Committee Elections Charter
└── README.md                       # Main organization entry point
```

---

## 📂 Repository Contents

- **Community Health & Governance Files**: Shared files inherited by all repositories in the organization, or defining our organizational governance structure:
  - [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
  - [CONTRIBUTING.md](CONTRIBUTING.md)
  - [GOVERNANCE.md](GOVERNANCE.md)
  - [SECURITY.md](SECURITY.md)
  - [TC_ELECTIONS.md](TC_ELECTIONS.md): Guidelines for Technical Committee elections.
  - [DOMAIN_TECH_COUNCIL_CHARTER.md](DOMAIN_TECH_COUNCIL_CHARTER.md): Charter defining Vertical Domain Tech Councils.

- **Reusable Workflows**:
  - [.github/workflows/reusable-governance.yml](.github/workflows/reusable-governance.yml): The automated status check that evaluates PR approvals against path-based reviewer requirements.

- **Organization Utilities (`org-tools/`)**:
  - [org-tools/governance/governance_check.py](org-tools/governance/governance_check.py): Python runner for PR approval verification.
  - [org-tools/governance/validate_governance_rules.py](org-tools/governance/validate_governance_rules.py): Validator for checking governance rules configurations.
  - [org-tools/label-sync/sync_labels.py](org-tools/label-sync/sync_labels.py): Utility to sync custom label schemas from YAML files to all org repositories.
  - For more information on using and running these CLI tools, see the [org-tools README](org-tools/README.md).

---

## 🛠️ Reusable Governance Gate Integration

To enable automated governance verification for other repositories in the organization, you can integrate our reusable PR approval gate.

For step-by-step instructions on setting up your caller workflow and configuring your governance rules, see the [reusable governance gate integration guide](org-tools/README.md#reusable-governance-gate-integration).
