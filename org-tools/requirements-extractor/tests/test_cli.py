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

"""End-to-end tests: the CLI run against the fixture specification."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts"))
)

import extract_requirements
from requirements_extractor import catalog, config

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "spec"
INDEX_DOC = "docs/specification/shopping/checkout/index.md"
REST_DOC = "docs/specification/shopping/checkout/rest.md"
INDEX_CATALOG = Path("shopping/checkout/index.json")
REST_CATALOG = Path("shopping/checkout/rest.json")

# The fixture is small enough to pin completely. Each entry is
# (id, level, target_actor, clause), in catalog-file order.
EXPECTED_REQUIREMENTS = [
    (
        "REQ-CHECKOUT-CONTINUE-URL-01",
        "MUST",
        "PLATFORM",
        "When `continue_url` is present, the platform **MUST** redirect the "
        "buyer to it.",
    ),
    (
        "REQ-CHECKOUT-CONTINUE-URL-02",
        "MUST NOT",
        "BUSINESS",
        "The business **MUST NOT** reuse an idempotency key.",
    ),
    (
        "REQ-CHECKOUT-SESSION-TEARDOWN-01",
        "MUST",
        "HOST",
        "The host **MUST** tear down the context",
    ),
    (
        "REQ-CHECKOUT-SESSION-TEARDOWN-02",
        "MAY",
        "HOST",
        "The host **MAY** redirect the buyer.",
    ),
    (
        "REQ-CHECKOUT-SESSION-TEARDOWN-03",
        "MUST",
        "BUSINESS",
        "**MUST** validate the cart before completing checkout.",
    ),
    (
        "REQ-CHECKOUT-SESSION-TEARDOWN-04",
        "SHOULD",
        "BUSINESS",
        "**SHOULD** log every rejected request.",
    ),
    (
        "REQ-CHECKOUT-REST-TRANSPORT-SECURITY-01",
        "MUST",
        None,
        "All REST endpoints **MUST** be served over HTTPS with minimum TLS "
        "version 1.3.",
    ),
]


def _run(*argv: str) -> tuple[int, str, str]:
    """Run the CLI in-process and capture its exit status and output."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            status = extract_requirements.main(list(argv))
        except SystemExit as exit_:
            status = exit_.code
    return status, out.getvalue(), err.getvalue()


class _FixtureCase(unittest.TestCase):
    """Copies the fixture to a scratch directory so runs can write to it."""

    def setUp(self):
        self._scratch = tempfile.TemporaryDirectory()
        self.spec_root = Path(self._scratch.name) / "spec"
        shutil.copytree(FIXTURE_ROOT, self.spec_root)
        self.catalog_dir = self.spec_root / config.DEFAULT_CATALOG_DIR
        self.report_path = self.spec_root / config.DEFAULT_REPORT_PATH

    def tearDown(self):
        self._scratch.cleanup()

    def _read_catalog(self) -> dict[Path, dict]:
        """Return the catalog files on disk, keyed relative to the catalog dir."""
        return {
            path.relative_to(self.catalog_dir): json.loads(
                path.read_text(encoding="utf-8")
            )
            for path in sorted(self.catalog_dir.rglob("*.json"))
        }

    def _write(self) -> dict[Path, dict]:
        """Run the CLI and return the catalog files it wrote."""
        status, _, err = _run("--spec-root", str(self.spec_root))
        self.assertEqual(status, 0, err)
        return self._read_catalog()

    def _stray(self, relative: str) -> Path:
        """Leave a catalog file behind that no page produces."""
        path = self.catalog_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
        return path


def _records(documents: dict[Path, dict]) -> list[dict]:
    """Return every record of a run, in catalog-file order."""
    return [
        record for document in documents.values() for record in document["requirements"]
    ]


class TestArguments(unittest.TestCase):
    """Tests for argument validation."""

    def test_spec_root_is_required(self):
        """Running without --spec-root is a usage error."""
        status, _, err = _run()
        self.assertEqual(status, 2)
        self.assertIn("--spec-root", err)

    def test_spec_root_without_mkdocs_is_rejected(self):
        """A directory that is not a specification checkout is a usage error."""
        with tempfile.TemporaryDirectory() as directory:
            status, _, err = _run("--spec-root", directory)
        self.assertEqual(status, 2)
        self.assertIn("mkdocs.yml", err)


class TestCatalog(_FixtureCase):
    """Tests for the catalog written from the fixture."""

    def test_requirements_match_the_fixture(self):
        """Every requirement in the fixture, and nothing else, is extracted."""
        self.assertEqual(
            [
                (r["id"], r["level"], r["target_actor"], r["clause"])
                for r in _records(self._write())
            ],
            EXPECTED_REQUIREMENTS,
        )

    def test_one_catalog_file_per_page(self):
        """Each page's requirements are in the file mirroring its path."""
        documents = self._write()
        self.assertEqual(list(documents), [INDEX_CATALOG, REST_CATALOG])
        self.assertEqual(documents[INDEX_CATALOG]["source_file"], INDEX_DOC)
        self.assertEqual(documents[REST_CATALOG]["source_file"], REST_DOC)
        for document in documents.values():
            self.assertEqual(
                {r["source"]["file"] for r in document["requirements"]},
                {document["source_file"]},
            )

    def test_envelope(self):
        """Provenance fields are present and well formed in every file."""
        for document in self._write().values():
            self.assertEqual(document["$schema"], config.CATALOG_SCHEMA_URL)
            self.assertEqual(document["schema_version"], config.CATALOG_SCHEMA_VERSION)
            self.assertEqual(document["extractor_version"], config.EXTRACTOR_VERSION)
            self.assertEqual(document["spec_version"], "2026-01-11")
            self.assertRegex(
                document["generated_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
            )
            self.assertNotIn("source_spec", document)

    def test_records_carry_no_release_and_keep_their_metadata(self):
        """The release is in the header; a record names a page and an anchor."""
        first = self._write()[INDEX_CATALOG]["requirements"][0]
        self.assertNotIn("version", first)
        self.assertNotIn("url", first["source"])
        self.assertEqual(first["scope"], "capability")
        self.assertEqual(first["capabilities"], ["dev.ucp.shopping.checkout"])
        self.assertEqual(first["condition"], "When `continue_url` is present")
        self.assertEqual(first["referenced_fields"], ["continue_url"])
        self.assertRegex(first["text_digest"], r"^[0-9a-f]{10}$")
        self.assertEqual(first["source"]["page"], "specification/shopping/checkout/")
        self.assertEqual(first["source"]["anchor"], "continue-url")

    def test_catalog_fits_the_published_schema(self):
        """Every file validates against the schema the catalog names."""
        for relative, document in self._write().items():
            self.assertEqual(catalog.validate(document), [], relative)

    def test_page_summary_counts_only_its_own_diagnostics(self):
        """A page's totals reconcile against that page alone."""
        documents = self._write()
        index = documents[INDEX_CATALOG]["summary"]
        rest = documents[REST_CATALOG]["summary"]
        self.assertEqual((index["total"], rest["total"]), (6, 1))
        self.assertEqual(index["diagnostics"]["candidates_without_emphasis"], 1)
        self.assertEqual(rest["diagnostics"]["candidates_without_emphasis"], 0)
        self.assertEqual(index["diagnostics"]["actor_unresolved"], 0)
        self.assertEqual(rest["diagnostics"]["actor_unresolved"], 1)

    def test_report_accounts_for_what_the_catalog_left_out(self):
        """Excluded clauses land in the report with their reason."""
        self._write()
        report = json.loads(self.report_path.read_text(encoding="utf-8"))
        diagnostics = report["diagnostics"]
        self.assertEqual(
            [entry["line"] for entry in diagnostics["candidates_without_emphasis"]],
            [16],
        )
        self.assertEqual(
            [entry["line"] for entry in diagnostics["rfc2119_boilerplate"]], [7]
        )
        self.assertEqual(
            [entry["file"] for entry in diagnostics["actor_unresolved"]], [REST_DOC]
        )
        self.assertEqual(
            report["source_spec"], ["docs/specification/shopping/checkout"]
        )
        self.assertNotIn("$schema", report)


class TestCheck(_FixtureCase):
    """Tests for --check, the form CI runs."""

    def test_check_passes_on_a_fresh_catalog(self):
        """A catalog just written is current."""
        self._write()
        status, out, _ = _run("--spec-root", str(self.spec_root), "--check")
        self.assertEqual(status, 0)
        self.assertIn("up to date", out)

    def test_check_fails_when_the_catalog_is_missing(self):
        """No committed catalog is a failure, not a pass."""
        status, _, err = _run("--spec-root", str(self.spec_root), "--check")
        self.assertEqual(status, 1)
        self.assertIn("missing", err)

    def test_check_fails_when_the_spec_changes(self):
        """Editing a normative sentence makes that page's catalog stale."""
        self._write()
        rest = self.spec_root / REST_DOC
        rest.write_text(
            rest.read_text(encoding="utf-8").replace("1.3.", "1.2."), encoding="utf-8"
        )
        status, _, err = _run("--spec-root", str(self.spec_root), "--check")
        self.assertEqual(status, 1)
        self.assertIn(f"{REST_CATALOG.as_posix()}: out of date", err)
        self.assertNotIn(f"{INDEX_CATALOG.as_posix()}: out of date", err)
        self.assertIn("Regenerate by running the extractor without --check", err)
        self.assertIn(f"extract_requirements.py --spec-root {self.spec_root}", err)

    def test_check_fails_on_a_catalog_file_no_page_produces(self):
        """A file left behind by a deleted page is stale too."""
        self._write()
        self._stray("shopping/checkout/retired.json")
        status, _, err = _run("--spec-root", str(self.spec_root), "--check")
        self.assertEqual(status, 1)
        self.assertIn("retired.json: no longer generated", err)

    def test_check_ignores_generated_at(self):
        """The timestamp differs on every run and must not fail the check."""
        document = self._write()[INDEX_CATALOG]
        document["generated_at"] = "2000-01-01T00:00:00Z"
        (self.catalog_dir / INDEX_CATALOG).write_text(
            json.dumps(document, indent=2) + "\n"
        )
        status, _, _ = _run("--spec-root", str(self.spec_root), "--check")
        self.assertEqual(status, 0)

    def test_dry_run_writes_nothing(self):
        """--dry-run runs the pipeline and leaves the tree untouched."""
        status, out, _ = _run("--spec-root", str(self.spec_root), "--dry-run")
        self.assertEqual(status, 0)
        self.assertIn("Dry run", out)
        self.assertFalse(self.catalog_dir.exists())
        self.assertFalse(self.report_path.exists())


class TestWrite(_FixtureCase):
    """Tests for regenerating over an existing catalog."""

    def test_files_no_page_produces_are_removed(self):
        """Regenerating deletes stale files and the directories they emptied."""
        self._write()
        stray = self._stray("shopping/retired/index.json")
        notes = self.catalog_dir / "NOTES.txt"
        notes.write_text("Not a catalog file.\n", encoding="utf-8")
        status, out, err = _run("--spec-root", str(self.spec_root))
        self.assertEqual(status, 0, err)
        self.assertIn("Removed", out)
        self.assertFalse(stray.parent.exists())
        self.assertTrue(notes.exists())
        self.assertEqual(list(self._read_catalog()), [INDEX_CATALOG, REST_CATALOG])


class TestRefusals(_FixtureCase):
    """Tests for runs that must stop before writing anything."""

    def test_document_without_a_capability_fails(self):
        """A requirement that belongs to nothing has no valid record."""
        with mock.patch.dict(config.CAPABILITY_BY_PREFIX, {}, clear=True):
            status, _, err = _run("--spec-root", str(self.spec_root))
            check_status, _, _ = _run("--spec-root", str(self.spec_root), "--check")
        self.assertEqual(status, 1)
        self.assertEqual(check_status, 1)
        self.assertIn("no capability", err)
        self.assertIn(REST_DOC, err)
        self.assertFalse(self.catalog_dir.exists())
        self.assertFalse(self.report_path.exists())

    def test_catalog_that_fails_its_schema_is_not_written(self):
        """The tool never writes a catalog its own contract rejects."""
        with mock.patch.object(
            catalog, "validate", return_value=["$.requirements[0]: rejected"]
        ):
            status, _, err = _run("--spec-root", str(self.spec_root))
        self.assertEqual(status, 1)
        self.assertIn("does not match its published schema", err)
        self.assertIn("rejected", err)
        self.assertFalse(self.catalog_dir.exists())
        self.assertFalse(self.report_path.exists())


class TestDeterminism(_FixtureCase):
    """Two runs over the same input agree on everything but the clock."""

    def test_runs_are_identical_apart_from_generated_at(self):
        """Regenerating produces the same bytes once the timestamp is removed."""
        first = self._write()
        second = self._write()
        for documents in (first, second):
            for document in documents.values():
                document.pop("generated_at")
        self.assertEqual(first, second)

    def test_relative_spec_root(self):
        """A relative spec root such as '.' works."""
        previous = os.getcwd()
        os.chdir(self.spec_root)
        try:
            status, _, err = _run("--spec-root", ".")
        finally:
            os.chdir(previous)
        self.assertEqual(status, 0, err)
        self.assertEqual(
            [r["id"] for r in _records(self._read_catalog())],
            [expected[0] for expected in EXPECTED_REQUIREMENTS],
        )


class TestCommitSha(unittest.TestCase):
    """Tests for recording the specification commit."""

    def test_failed_git_call_records_no_commit(self):
        """Output from a failing `git rev-parse` is not taken as a commit."""
        failed = subprocess.CompletedProcess(
            args=["git"], returncode=128, stdout="not-a-sha\n", stderr="fatal"
        )
        with mock.patch.object(catalog.subprocess, "run", return_value=failed):
            self.assertIsNone(catalog._commit_sha(FIXTURE_ROOT))


if __name__ == "__main__":
    unittest.main()
