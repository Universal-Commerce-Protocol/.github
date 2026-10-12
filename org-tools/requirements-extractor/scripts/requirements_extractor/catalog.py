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

"""Stage 5: running the pipeline and writing the catalog.

Two kinds of document come out of a run. The catalog is the requirements
themselves, written as one file per specification page, so a page's rules
always live in one predictable file and a catalog diff names the page it
came from. The report is everything the extractor decided not to put in the
catalog, and why -- it is the half that makes the other half trustworthy,
because a clause citing an RFC 2119 keyword either reaches the catalog or
appears in the report with a reason, never neither.

Every catalog file is checked against the published schema before it is
written or compared, so the tool cannot emit a catalog that its own contract
rejects.

Everything is written deterministically. The same input produces the same
output, apart from `generated_at`, which is what lets a consumer regenerate
and diff to prove the catalog matches the spec it claims to describe.

  `generated_at` is a wall-clock reading and differs on every run. It is
  published so a catalog read outside the repository can be dated, and
  `--check` ignores it (see config.NON_DETERMINISTIC_FIELDS), so the
  comparison still covers everything that is a function of the spec.

Requirements are emitted in source order. The catalog's primary review path
is reading it beside the specification, and an identifier is stable under
insertion regardless of where it sits in the file, so nothing is gained by
ordering on the digest.
"""

from __future__ import annotations

import collections
from collections.abc import Iterable
import datetime
import functools
import json
from pathlib import Path
import subprocess

import jsonschema

from requirements_extractor import (
    classifier,
    config,
    identity,
    metadata,
    parser,
)
from requirements_extractor.models import ExtractionReport, Requirement


def build(spec_root: Path) -> tuple[list[Requirement], ExtractionReport]:
    """Run every stage and return the requirements and the diagnostics.

    Args:
      spec_root: Root of the specification checkout.

    Returns:
      Requirements in source order, and the report accumulated across all
      stages.

    """
    clauses = parser.parse_all(spec_root)
    obligations, report = classifier.classify_all(clauses)
    annotated, report = metadata.annotate_all(obligations, spec_root, report)
    requirements, report = identity.assign_identities(annotated, report)

    requirements.sort(
        key=lambda r: (r.source.file, r.source.line_start, r.document_order)
    )
    return requirements, report


def _counter(values: list[str]) -> dict[str, int]:
    """Count values into a dict with deterministic key order."""
    counts = collections.Counter(values)
    return {key: counts[key] for key in sorted(counts)}


def summarize(
    requirements: list[Requirement], report: ExtractionReport
) -> dict[str, object]:
    """Describe a run in numbers.

    The reconciliation totals are included so the catalog carries its own
    evidence: every clause that cited a keyword is accounted for, either as a
    requirement or as a diagnostic.

    Args:
      requirements: The extracted requirements.
      report: Diagnostics from the run.

    Returns:
      A summary suitable for the head of either document.

    """
    diagnostics = {
        name: len(entries) for name, entries in sorted(report.as_dict().items())
    }
    by_level = _counter([str(r.level) for r in requirements if r.level is not None])
    return {
        "total": len(requirements),
        "must_count": by_level.get("MUST", 0),
        "must_not_count": by_level.get("MUST NOT", 0),
        "should_count": by_level.get("SHOULD", 0),
        "should_not_count": by_level.get("SHOULD NOT", 0),
        "may_count": by_level.get("MAY", 0),
        "by_level": by_level,
        "by_actor": _counter(
            [config.published_actor(r.actor) or "UNRESOLVED" for r in requirements]
        ),
        "by_file": _counter([r.source.file for r in requirements]),
        "with_condition": sum(1 for r in requirements if r.condition),
        "with_referenced_fields": sum(1 for r in requirements if r.referenced_fields),
        "from_compound_split": sum(1 for r in requirements if r.split_from_compound),
        "diagnostics": diagnostics,
    }


def _page_report(report: ExtractionReport, source_file: str) -> ExtractionReport:
    """Return the diagnostics recorded against one page.

    Every report entry names the file it came from, so each page's catalog can
    carry its own reconciliation totals. A duplicate spanning two pages is
    counted on the page of its first copy, which is where the report lists it.

    Args:
      report: Diagnostics from the whole run.
      source_file: Repository-relative path of the page.

    Returns:
      A report holding only the entries recorded against `source_file`.

    """
    return ExtractionReport(
        **{
            name: [entry for entry in entries if entry.get("file") == source_file]
            for name, entries in report.as_dict().items()
        }
    )


def _commit_sha(spec_root: Path) -> str | None:
    """Return the specification checkout's commit, or None outside git.

    Provenance that survives the file being copied out of the repository. It
    is stable for a given tree, so unlike a timestamp it does not by itself
    make two runs differ. Read from the spec root rather than from this
    tool's location, which is a different repository.
    """
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=spec_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    sha = completed.stdout.strip()
    return sha or None


def _envelope(spec_version: str, spec_root: Path) -> dict[str, object]:
    """Return the provenance header shared by every document of a run.

    `spec_version` lives here and nowhere else. Records carry no release, so
    cutting a release changes this one line in each file rather than every
    record in it.

    `$schema` is deliberately not here. Every document shares provenance, but
    only the catalog has a published schema; claiming it on the report would
    assert a shape the report does not have.

    `generated_at` is the one field here that changes between runs of the same
    input. It is published because a consumer reading the catalog outside the
    repository has no other way to date it, but it is excluded from the
    comparison `--check` performs -- otherwise every run would report the
    committed catalog as stale and the CI gate would be worthless.
    """
    return {
        "schema_version": config.CATALOG_SCHEMA_VERSION,
        "extractor_version": config.EXTRACTOR_VERSION,
        "spec_version": spec_version,
        "generated_at": datetime.datetime.now(datetime.UTC).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "commit_sha": _commit_sha(spec_root),
    }


def catalog_documents(
    requirements: list[Requirement], report: ExtractionReport, spec_root: Path
) -> dict[Path, dict[str, object]]:
    """Assemble one catalog document per specification page.

    A page with no requirements gets no document. The header is computed once,
    so every file from a run carries the same provenance.

    Args:
      requirements: The extracted requirements, in source order.
      report: Diagnostics from the run, used for each page's summary only.
      spec_root: Root of the specification checkout, for provenance.

    Returns:
      JSON-serializable catalogs keyed by their path relative to the catalog
      directory (see config.catalog_file), in path order.

    """
    envelope = _envelope(config.spec_version(spec_root), spec_root)
    by_page: dict[str, list[Requirement]] = {}
    for requirement in requirements:
        by_page.setdefault(requirement.source.file, []).append(requirement)

    documents = {
        config.catalog_file(source_file): {
            "$schema": config.CATALOG_SCHEMA_URL,
            **envelope,
            "source_file": source_file,
            "summary": summarize(page, _page_report(report, source_file)),
            "requirements": [requirement.as_dict() for requirement in page],
        }
        for source_file, page in by_page.items()
    }
    return dict(sorted(documents.items()))


def report_document(
    requirements: list[Requirement], report: ExtractionReport, spec_root: Path
) -> dict[str, object]:
    """Assemble the diagnostics document for the whole run.

    Args:
      requirements: The extracted requirements, used for the summary.
      report: Diagnostics from the run.
      spec_root: Root of the specification checkout, for provenance.

    Returns:
      A JSON-serializable report.

    """
    return {
        **_envelope(config.spec_version(spec_root), spec_root),
        # POSIX strings rather than Path objects, so the document is
        # serializable and identical regardless of the host platform.
        "source_spec": sorted(directory.as_posix() for directory in config.SPEC_DIRS),
        "summary": summarize(requirements, report),
        "diagnostics": dict(sorted(report.as_dict().items())),
    }


@functools.cache
def _validator() -> jsonschema.protocols.Validator:
    """Return a validator for the published catalog schema, built once."""
    schema = json.loads(config.CATALOG_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator_class = jsonschema.validators.validator_for(schema)
    validator_class.check_schema(schema)
    return validator_class(schema)


def validate(document: dict[str, object]) -> list[str]:
    """Check a catalog document against the published schema.

    Run before anything is written or compared, so the tool never emits a
    catalog that its own published contract rejects -- a requirement with no
    capability, say, or a field the schema does not define.

    Args:
      document: A catalog document, as built by `catalog_documents`.

    Returns:
      One message per violation, located by JSON path, in a stable order.
      Empty when the document is valid.

    """
    return sorted(
        f"{error.json_path}: {error.message}"
        for error in _validator().iter_errors(document)
    )


def serialize(document: dict[str, object]) -> str:
    """Render a document as deterministic JSON.

    Args:
      document: The catalog or report.

    Returns:
      JSON text, newline-terminated. Key order is the order the document was
      assembled in, which is fixed by the code rather than by a dict's
      insertion history, so runs agree byte for byte.

    """
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def write(path: Path, document: dict[str, object]) -> None:
    """Write a document to disk, creating parent directories.

    Args:
      path: Destination file.
      document: The catalog or report.

    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize(document), encoding="utf-8")


def stale_catalog_files(
    catalog_dir: Path,
    documents: dict[Path, dict[str, object]],
    keep: Iterable[Path] = (),
) -> list[Path]:
    """Return catalog files on disk that this run did not produce.

    A page that was deleted, renamed or left without requirements leaves its
    old catalog file behind. That file describes rules the specification no
    longer states, so it is as stale as an out-of-date one.

    Args:
      catalog_dir: Directory the catalog files are written to.
      documents: This run's documents, keyed relative to `catalog_dir`.
      keep: Other files that may live under `catalog_dir` and are not
        catalog files, such as a report written there.

    Returns:
      Sorted paths of `*.json` files under `catalog_dir` that no document of
      this run accounts for. Empty when the directory does not exist.

    """
    if not catalog_dir.is_dir():
        return []
    expected = {(catalog_dir / relative).resolve() for relative in documents}
    expected.update(path.resolve() for path in keep)
    return sorted(
        path for path in catalog_dir.rglob("*.json") if path.resolve() not in expected
    )


def write_catalog(
    catalog_dir: Path,
    documents: dict[Path, dict[str, object]],
    keep: Iterable[Path] = (),
) -> list[Path]:
    """Write every catalog document and remove the files no longer produced.

    The catalog directory belongs to the tool, so a catalog file this run did
    not produce is removed rather than left to fail the next `--check`. Only
    `*.json` files are touched, and directories a removal empties are pruned.

    Args:
      catalog_dir: Directory the catalog files are written to.
      documents: Documents keyed by path relative to `catalog_dir`.
      keep: Files under `catalog_dir` to leave alone; see
        `stale_catalog_files`.

    Returns:
      The stale files that were removed, sorted.

    """
    stale = stale_catalog_files(catalog_dir, documents, keep)
    for path in stale:
        path.unlink()
        _prune_empty_directories(path.parent, catalog_dir)
    for relative, document in documents.items():
        write(catalog_dir / relative, document)
    return stale


def _prune_empty_directories(directory: Path, root: Path) -> None:
    """Remove `directory` and its parents while they are empty, below `root`."""
    root = root.resolve()
    current = directory.resolve()
    while root in current.parents and not any(current.iterdir()):
        current.rmdir()
        current = current.parent


def unresolved_capabilities(requirements: list[Requirement]) -> list[str]:
    """Return the files whose capability could not be resolved.

    Args:
      requirements: The extracted requirements.

    Returns:
      Sorted, deduplicated file paths. Empty when every document resolved.

    """
    return sorted({r.source.file for r in requirements if not r.capability})
