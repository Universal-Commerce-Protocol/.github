# Requirements Extractor

This tool reads the normative prose of a UCP specification and writes a machine-readable catalog of its requirements. Each RFC 2119 obligation (**MUST**, **MUST NOT**, **SHOULD**, **MAY**, ...) becomes one record with a readable id, a content digest, its level, the party it binds, and a link to the published section.

The tool lives here and the catalog it produces lives in the specification repository, next to the prose it describes. The specification repository runs the check in CI through a reusable workflow, so an edit that changes a normative sentence also has to regenerate the catalog.

Scope is currently the checkout capability (`docs/specification/shopping/checkout`).

---

## Outputs

A run writes two files into the specification checkout:

| File                                            | Contents                                                                               |
| :---------------------------------------------- | :------------------------------------------------------------------------------------- |
| `generated/requirements/requirements.json`      | The catalog, described by [the published schema](schema/requirements-catalog-v1.json). |
| `generated/requirements/extraction_report.json` | Every keyword-bearing clause that did not become a requirement, and why.               |

The two reconcile: a clause citing an RFC 2119 keyword either reaches the catalog or appears in the report with a reason. The report is also how a spec author finds obligations the tool could not attribute to a party, and prose that reads as normative but is not marked up as such.

A catalog record looks like this:

```json
{
  "id": "REQ-CHECKOUT-REST-TRANSPORT-SECURITY-01",
  "content_digest": "df21d831cd",
  "capability": "dev.ucp.shopping.checkout",
  "version": "draft",
  "level": "MUST",
  "target_actor": null,
  "actor_confidence": 0.0,
  "clause": "All REST endpoints **MUST** be served over HTTPS with minimum TLS version 1.3.",
  "normalized": "all rest endpoints must be served over https with minimum tls version 1.3",
  "condition": null,
  "referenced_fields": [],
  "compound_parent": null,
  "document_order": 10,
  "source": {
    "file": "docs/specification/shopping/checkout/rest.md",
    "start_line": 76,
    "end_line": 77,
    "section": "Checkout Capability - REST Binding > Protocol Fundamentals > Transport Security",
    "block_type": "paragraph",
    "url": "https://ucp.dev/draft/specification/shopping/checkout/rest/#transport-security"
  }
}
```

### Two identifiers

- **`id`** is readable and positional: `REQ-<CAPABILITY>-[<DOCUMENT>-]<SECTION>-<NN>`. It is meant for conformance tests to bind to, so a binding says what it covers. Inserting a requirement above it in the same section renumbers it.
- **`content_digest`** is the first 10 hex characters of the SHA-256 of the capability, the normalized `compound_parent` and the `normalized` clause, joined by U+001F. It does not depend on file, line or heading, so it survives the document being reorganized, and it can be recomputed from the published record alone.

Comparing the two distinguishes a requirement that was reworded (same id, new digest) from one that was moved or removed.

---

## Usage

The script declares its dependencies inline ([PEP 723](https://peps.python.org/pep-0723/)), pinned to the versions the specification site builds with. `markdown` decides heading anchors, so a different version can publish URLs that do not resolve. [uv](https://docs.astral.sh/uv/) installs them automatically.

From the root of a specification checkout, with this repository checked out alongside it:

```bash
# Regenerate the catalog and the report after editing the specification.
uv run ../.github/org-tools/requirements-extractor/scripts/extract_requirements.py --spec-root .

# Verify the committed files match the specification (what CI runs).
uv run ../.github/org-tools/requirements-extractor/scripts/extract_requirements.py --spec-root . --check

# Print counts without writing anything.
uv run ../.github/org-tools/requirements-extractor/scripts/extract_requirements.py --spec-root . --dry-run --summary
```

`--spec-root` is required and must be the directory holding the specification's `mkdocs.yml`. The published release is read from `extra.ucp_version` in that file, so a wrong root is an error rather than a catalog stamped with the wrong version.

`--check` ignores `generated_at` and `commit_sha`, which change on every run and every commit, and compares everything else exactly.

---

## CI

Callers use [`reusable-requirements-check.yml`](../../.github/workflows/reusable-requirements-check.yml). Pin both the workflow and the extractor to the same commit of this repository, so neither changes until the caller opts in:

```yaml
name: Requirements Catalog

on:
  pull_request:
    paths:
      - "docs/specification/**"
      - "generated/requirements/**"
      - "mkdocs.yml"

jobs:
  requirements-check:
    uses: Universal-Commerce-Protocol/.github/.github/workflows/reusable-requirements-check.yml@<commit-sha>
    with:
      central_ref: <commit-sha>
```

| Input          | Default   | Description                                              |
| :------------- | :-------- | :------------------------------------------------------- |
| `central_repo` | `.github` | Name of the central tools repository.                    |
| `central_ref`  | `main`    | Ref to run the extractor from. Pin to the `uses:` SHA.   |
| `spec_root`    | `.`       | Directory, relative to the caller, holding `mkdocs.yml`. |

---

## How clauses are classified

- **Emphasis marks an obligation.** UCP bolds the keyword of a real obligation, so only bolded keywords produce requirements. An uppercase keyword without bold is reported under `candidates_without_emphasis` rather than dropped silently.
- **Code is not prose.** Fenced blocks, indented blocks, raw HTML and inline code spans are excluded, so a literal `MUST` inside backticks is never an obligation.
- **Schema annotations are not obligations.** `REQUIRED`, `OPTIONAL` and `RECOMMENDED` marking a field's optionality are excluded. The same words in running prose follow the emphasis rule above: bolded, they are promoted to their RFC 2119 level and reported; unbolded, they are reported under `candidates_without_emphasis`.
- **One sentence can hold several obligations.** "The host **MUST** tear down the context and **MAY** redirect the buyer" becomes two requirements that share the subject.
- **The actor is the subject, not the object.** The party is the last one named before the keyword. A party named only after it is usually the object ("**MUST** present the content to the buyer" binds the host), so it is reported rather than used. Colon stems such as "**Host responsibilities:**" and headings are weaker fallbacks, and each strategy carries its own `actor_confidence`.

Tunable policy (scope, keyword lists, actor vocabulary, id tokens) lives in [`config.py`](scripts/requirements_extractor/config.py).

---

## Layout

```text
requirements-extractor/
├── schema/requirements-catalog-v1.json   # Published catalog schema
├── scripts/
│   ├── extract_requirements.py           # CLI entry point
│   └── requirements_extractor/           # parser, classifier, metadata, identity, catalog
└── tests/
    ├── fixtures/spec/                    # Small offline specification
    └── test_*.py
```

---

## Running Unit Tests

From the root of this repository:

```bash
uv run --with markdown-it-py==3.0.0 --with markdown==3.10.2 \
  python -m unittest discover -s org-tools/requirements-extractor/tests
```

The tests run offline against the fixture specification in `tests/fixtures/spec`, not against a checkout of another repository.
