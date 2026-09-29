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
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts"))
)

import extract_requirements
from requirements_extractor import config

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "spec"
REST_DOC = "docs/specification/shopping/checkout/rest.md"

# The fixture is small enough to pin completely. Each entry is
# (id, level, target_actor, clause).
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
        self.catalog_path = self.spec_root / config.DEFAULT_CATALOG_PATH
        self.report_path = self.spec_root / config.DEFAULT_REPORT_PATH

    def tearDown(self):
        self._scratch.cleanup()

    def _write(self) -> dict:
        status, _, err = _run("--spec-root", str(self.spec_root))
        self.assertEqual(status, 0, err)
        return json.loads(self.catalog_path.read_text(encoding="utf-8"))


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
        catalog = self._write()
        self.assertEqual(
            [
                (r["id"], r["level"], r["target_actor"], r["clause"])
                for r in catalog["requirements"]
            ],
            EXPECTED_REQUIREMENTS,
        )

    def test_envelope(self):
        """Provenance fields are present and well formed."""
        catalog = self._write()
        self.assertEqual(catalog["$schema"], config.CATALOG_SCHEMA_URL)
        self.assertEqual(catalog["schema_version"], config.CATALOG_SCHEMA_VERSION)
        self.assertEqual(catalog["extractor_version"], config.EXTRACTOR_VERSION)
        self.assertEqual(catalog["spec_version"], "2026-01-11")
        self.assertRegex(
            catalog["generated_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
        )
        self.assertEqual(
            catalog["source_spec"], ["docs/specification/shopping/checkout"]
        )

    def test_records_carry_version_url_and_metadata(self):
        """A record links to the published spec and carries its metadata."""
        first = self._write()["requirements"][0]
        self.assertEqual(first["capability"], "dev.ucp.shopping.checkout")
        self.assertEqual(first["version"], "2026-01-11")
        self.assertEqual(first["condition"], "When `continue_url` is present")
        self.assertEqual(first["referenced_fields"], ["continue_url"])
        self.assertRegex(first["content_digest"], r"^[0-9a-f]{10}$")
        self.assertEqual(
            first["source"]["url"],
            "https://ucp.dev/2026-01-11/specification/shopping/checkout/#continue-url",
        )

    def test_catalog_fits_the_published_schema(self):
        """Required keys are present and no key falls outside the schema."""
        catalog = self._write()
        schema = json.loads(config.CATALOG_SCHEMA_PATH.read_text(encoding="utf-8"))

        def assert_fits(document: dict, definition: dict, where: str) -> None:
            keys = set(document)
            missing = set(definition["required"]) - keys
            extra = keys - set(definition["properties"])
            self.assertFalse(missing, f"{where} is missing {sorted(missing)}")
            self.assertFalse(extra, f"{where} has unexpected {sorted(extra)}")

        assert_fits(catalog, schema, "catalog")
        for record in catalog["requirements"]:
            assert_fits(record, schema["$defs"]["requirement"], record["id"])
            assert_fits(record["source"], schema["$defs"]["source"], record["id"])
            self.assertRegex(
                record["id"],
                schema["$defs"]["requirement"]["properties"]["id"]["pattern"],
            )

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
        """Editing a normative sentence makes the committed catalog stale."""
        self._write()
        rest = self.spec_root / REST_DOC
        rest.write_text(
            rest.read_text(encoding="utf-8").replace("1.3.", "1.2."), encoding="utf-8"
        )
        status, _, err = _run("--spec-root", str(self.spec_root), "--check")
        self.assertEqual(status, 1)
        self.assertIn("out of date", err)
        self.assertIn("Regenerate with: uv run", err)

    def test_check_ignores_generated_at(self):
        """The timestamp differs on every run and must not fail the check."""
        catalog = self._write()
        catalog["generated_at"] = "2000-01-01T00:00:00Z"
        self.catalog_path.write_text(json.dumps(catalog, indent=2) + "\n")
        status, _, _ = _run("--spec-root", str(self.spec_root), "--check")
        self.assertEqual(status, 0)

    def test_dry_run_writes_nothing(self):
        """--dry-run runs the pipeline and leaves the tree untouched."""
        status, out, _ = _run("--spec-root", str(self.spec_root), "--dry-run")
        self.assertEqual(status, 0)
        self.assertIn("Dry run", out)
        self.assertFalse(self.catalog_path.exists())


class TestDeterminism(_FixtureCase):
    """Two runs over the same input agree on everything but the clock."""

    def test_runs_are_identical_apart_from_generated_at(self):
        """Regenerating produces the same bytes once the timestamp is removed."""
        first = self._write()
        second = self._write()
        for document in (first, second):
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
        catalog = json.loads(self.catalog_path.read_text(encoding="utf-8"))
        self.assertEqual(
            [r["id"] for r in catalog["requirements"]],
            [expected[0] for expected in EXPECTED_REQUIREMENTS],
        )


if __name__ == "__main__":
    unittest.main()
