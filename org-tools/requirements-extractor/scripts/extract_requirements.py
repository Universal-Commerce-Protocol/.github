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

# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "markdown-it-py==3.0.0",
#   "markdown==3.10.2",
# ]
# ///
"""Extract a machine-readable requirements catalog from the specification.

Reads the normative prose of the checkout capability from a checkout of the
specification repository and writes two files into that checkout:

  generated/requirements/requirements.json       the requirements
  generated/requirements/extraction_report.json  what was excluded, and why

The report is not a debug log. Every clause citing an RFC 2119 keyword
either becomes a requirement or appears in the report with a reason, so the
two documents reconcile against the spec exactly. Reading the report is how
an author finds obligations the extractor could not attribute, and prose
that reads as normative but is not marked up as such.

`--spec-root` is required and must be the directory holding the
specification's mkdocs.yml. The published release (`extra.ucp_version`) is
read from that file, so running against the wrong directory is an error
rather than a catalog stamped with the wrong version.

Dependencies are pinned to the versions the specification site builds with.
`markdown` in particular decides heading anchors, and a different version
can publish URLs that do not resolve.

Usage, from the root of a ucp checkout:

  # Write both documents.
  uv run path/to/extract_requirements.py --spec-root .

  # Verify the committed documents match the specification. Exits non-zero
  # if regenerating would change anything, which is the form to run in CI.
  uv run path/to/extract_requirements.py --spec-root . --check

  # Print a summary without touching the filesystem.
  uv run path/to/extract_requirements.py --spec-root . --dry-run --summary
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from requirements_extractor import catalog, config  # noqa: E402


def _print_summary(summary: dict) -> None:
    """Print the run summary in a form that is readable in CI logs."""
    print(f"requirements: {summary['total']}")

    print("\n  by level:")
    for level, count in summary["by_level"].items():
        print(f"    {level:<12} {count}")

    print("\n  by actor:")
    for actor, count in summary["by_actor"].items():
        print(f"    {actor:<20} {count}")

    print("\n  by file:")
    for name, count in summary["by_file"].items():
        print(f"    {Path(name).name:<16} {count}")

    print(
        f"\n  with a condition: {summary['with_condition']}"
        f"   with referenced fields: {summary['with_referenced_fields']}"
        f"   from a compound split: {summary['from_compound_split']}"
    )

    print("\n  diagnostics:")
    for name, count in summary["diagnostics"].items():
        marker = " " if count == 0 else "*"
        print(f"   {marker}{name:<30} {count}")


def _display_path(path: Path, spec_root: Path) -> str:
    """Render a path for humans, relative to the spec root when possible.

    `Path.relative_to` raises for a path outside the tree rather than
    falling back, so redirecting output anywhere else -- a temporary directory
    in a determinism check, for instance -- would otherwise crash the CLI
    after the files had already been written.

    Args:
      path: Path to render.
      spec_root: Root of the specification checkout.

    Returns:
      A spec-root-relative path, or the path as given when outside the tree.

    """
    try:
        return str(path.resolve().relative_to(spec_root.resolve()))
    except ValueError:
        return str(path)


def _comparable(text: str) -> str:
    """Return a document's text with non-deterministic fields removed.

    `generated_at` is a wall clock reading, so a byte comparison against the
    committed file would fail every time. Stripping it from both sides keeps
    the check meaningful: everything that is a function of the specification
    still has to match exactly.

    Args:
      text: Serialized JSON document.

    Returns:
      Serialized JSON with `config.NON_DETERMINISTIC_FIELDS` removed, or the
      input unchanged if it does not parse.

    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(document, dict):
        for field in config.NON_DETERMINISTIC_FIELDS:
            document.pop(field, None)
    return catalog.serialize(document)


def _check(paths_and_documents: list[tuple[Path, dict]], spec_root: Path) -> int:
    """Compare regenerated documents against what is on disk.

    Args:
      paths_and_documents: Destination paths paired with fresh documents.
      spec_root: Root of the specification checkout.

    Returns:
      A process exit status: 0 when every file is already current.

    """
    stale = []
    for path, document in paths_and_documents:
        expected = _comparable(catalog.serialize(document))
        if not path.exists():
            stale.append((path, "missing"))
        elif _comparable(path.read_text(encoding="utf-8")) != expected:
            stale.append((path, "out of date"))

    if not stale:
        print("Requirements catalog is up to date.")
        return 0

    for path, reason in stale:
        print(f"{_display_path(path, spec_root)}: {reason}", file=sys.stderr)
    try:
        script = os.path.relpath(Path(__file__).resolve())
    except ValueError:
        script = str(Path(__file__).resolve())
    print(
        "\nRegenerate by running the extractor without --check:\n"
        f"  uv run {script} --spec-root {spec_root}\n"
        "The extractor is org-tools/requirements-extractor/scripts/"
        "extract_requirements.py in Universal-Commerce-Protocol/.github.",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
      argv: Command-line arguments, or None to read them from sys.argv.

    Returns:
      A process exit status.

    """
    argument_parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    argument_parser.add_argument(
        "--spec-root",
        type=Path,
        required=True,
        help=("Root of the specification checkout: the directory holding mkdocs.yml."),
    )
    argument_parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help=(
            "Where to write the requirements "
            f"(default: <spec-root>/{config.DEFAULT_CATALOG_PATH.as_posix()})."
        ),
    )
    argument_parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=(
            "Where to write the diagnostics "
            f"(default: <spec-root>/{config.DEFAULT_REPORT_PATH.as_posix()})."
        ),
    )
    argument_parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Do not write. Exit non-zero if regenerating would change either "
            "file, so CI can prove the committed catalog matches the spec."
        ),
    )
    argument_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the pipeline but write nothing.",
    )
    argument_parser.add_argument(
        "--summary",
        action="store_true",
        help="Print counts for the run.",
    )
    argument_parser.add_argument(
        "--fail-on-unresolved",
        action="store_true",
        help=(
            "Exit non-zero if any document's capability could not be resolved. "
            "Useful once scope widens past a single capability directory."
        ),
    )
    args = argument_parser.parse_args(argv)

    spec_root: Path = args.spec_root
    if not (spec_root / config.MKDOCS_FILENAME).is_file():
        argument_parser.error(
            f"--spec-root {spec_root} has no {config.MKDOCS_FILENAME}; "
            "pass the root of the specification checkout"
        )
    catalog_path: Path = args.catalog or spec_root / config.DEFAULT_CATALOG_PATH
    report_path: Path = args.report or spec_root / config.DEFAULT_REPORT_PATH

    requirements, report = catalog.build(spec_root)
    catalog_doc = catalog.catalog_document(requirements, report, spec_root)
    report_doc = catalog.report_document(requirements, report, spec_root)

    if args.summary:
        _print_summary(catalog_doc["summary"])

    unresolved = catalog.unresolved_capabilities(requirements)
    if unresolved:
        print(
            f"\nwarning: {len(unresolved)} document(s) with no capability:",
            file=sys.stderr,
        )
        for name in unresolved:
            print(f"  {name}", file=sys.stderr)
        if args.fail_on_unresolved:
            return 1

    if args.check:
        return _check(
            [(catalog_path, catalog_doc), (report_path, report_doc)], spec_root
        )

    if args.dry_run:
        print("\nDry run: nothing written.")
        return 0

    catalog.write(catalog_path, catalog_doc)
    catalog.write(report_path, report_doc)
    print(f"\nWrote {len(requirements)} requirements")
    print(f"  {_display_path(catalog_path, spec_root)}")
    print(f"  {_display_path(report_path, spec_root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
