# Description

<!-- Please provide a brief description of the changes in this pull request. -->

## Category (Required)

_Please select one or more categories that apply to this change._

- [ ] **Core Protocol**: Changes to the base communication layer, global context, or breaking refactors. (Requires Technical Council approval)
- [ ] **Governance/Contributing**: Updates to GOVERNANCE.md, CONTRIBUTING.md, or CODEOWNERS. (Requires Governance Council approval)
- [ ] **Capability**: New schemas (Discovery, Cart, etc.) or extensions. (Requires Maintainer approval)
- [ ] **Documentation**: Updates to README, or documentations regarding schema or capabilities. (Requires Maintainer approval)
- [ ] **Infrastructure**: CI/CD, Linters, or build scripts. (Requires DevOps Maintainer approval)
- [ ] **Maintenance**: Version bumps, lockfile updates, or minor bug fixes. (Requires DevOps Maintainer approval)
- [ ] **SDK**: Language-specific SDK updates and releases. (Requires DevOps Maintainer approval)
- [ ] **Samples / Conformance**: Maintaining samples and the conformance suite. (Requires Maintainer approval)
- [ ] **UCP Schema**: Changes to the `ucp-schema` tool (resolver, linter, validator). (Requires Maintainer approval)
- [ ] **Community Health (.github)**: Updates to templates, workflows, or org-level configs. (Requires DevOps Maintainer approval)

## Related Issues

<!-- Link to any related issues here. e.g., "Fixes #123" -->

## Checklist

- [ ] I have followed the [Contributing Guide](https://github.com/Universal-Commerce-Protocol/.github/blob/main/CONTRIBUTING.md).
- [ ] I have updated the documentation (if applicable).
- [ ] My changes pass all local linting and formatting checks.
- [ ] I have added tests that prove my fix is effective or that my feature works.
- [ ] New and existing unit tests pass locally with my changes.
- [ ] (For Core/Capability) I have included/updated the relevant JSON schemas.
- [ ] I have regenerated Python Pydantic models by running generate_models.sh under python_sdk.

## Screenshots / Logs (if applicable)

<!-- If applicable, add screenshots or log output to help explain your changes. -->

---

### Pull Request Title & Breaking Changes

This organization enforces **Conventional Commits** (`type: description`).

**Common Types:** `feat`, `fix`, `docs`, `chore`, `refactor`.

**Breaking Changes:**
If this PR introduces a breaking change or removes existing fields/files:
- [ ] **I have added `!` to my PR title** (e.g., `feat!: remove field`).
- [ ] **I have provided a justification below.**

```text
## Breaking Changes / Removal Justification

(Please provide a detailed technical and strategic rationale here for why this
breaking change or removal is necessary.)
```
