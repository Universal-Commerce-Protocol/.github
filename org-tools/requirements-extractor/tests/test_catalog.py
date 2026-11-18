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

"""Unit tests for stage 5: per-page catalog documents and their validation."""

import copy
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts"))
)

from requirements_extractor import catalog
from requirements_extractor.models import (
    BlockType,
    ExtractionReport,
    Level,
    Requirement,
    SourceRef,
)

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "spec"


def _fixture_documents() -> dict[Path, dict]:
    """Build the fixture's catalog documents without writing them."""
    requirements, report = catalog.build(FIXTURE_ROOT)
    return catalog.catalog_documents(requirements, report, FIXTURE_ROOT)


def _requirement(level: Level, line: int) -> Requirement:
    """Build a minimal requirement at a given obligation level."""
    return Requirement(
        text=f"The business **{level}** reply.",
        source=SourceRef(
            file="docs/specification/shopping/checkout/index.md",
            line_start=line,
            line_end=line,
            section="Checkout Capability > Replies",
            block_type=BlockType.PARAGRAPH,
        ),
        document_order=line,
        level=level,
        capability="dev.ucp.shopping.checkout",
    )


class TestCatalogDocuments(unittest.TestCase):
    """Tests for splitting a run into one document per page."""

    def test_documents_are_keyed_by_the_mirrored_page_path(self):
        """The fixture's two pages give two documents, in path order."""
        self.assertEqual(
            list(_fixture_documents()),
            [Path("shopping/checkout/index.json"), Path("shopping/checkout/rest.json")],
        )


class TestSummarize(unittest.TestCase):
    """Tests for the counts at the head of each document."""

    def test_every_level_has_a_counter_and_they_add_up(self):
        """A requirement at any level, SHALL included, is counted once."""
        requirements = [
            _requirement(level, line) for line, level in enumerate(Level, start=1)
        ]
        summary = catalog.summarize(requirements, ExtractionReport())
        for level in Level:
            self.assertEqual(summary[level.count_field], 1, level)
        self.assertEqual(
            sum(summary[level.count_field] for level in Level), summary["total"]
        )


class TestValidate(unittest.TestCase):
    """Tests for checking catalog documents against the published schema."""

    @classmethod
    def setUpClass(cls):
        cls.documents = _fixture_documents()

    def _document(self) -> dict:
        """Return a fresh, valid copy of one fixture page's catalog."""
        return copy.deepcopy(next(iter(self.documents.values())))

    def test_fixture_catalog_is_valid(self):
        """What the tool builds satisfies the contract it publishes."""
        for relative, document in self.documents.items():
            self.assertEqual(catalog.validate(document), [], relative)

    def test_requirement_without_a_capability_is_rejected(self):
        """A capability-scoped requirement must name its capability."""
        document = self._document()
        document["requirements"][0]["capabilities"] = []
        [error] = catalog.validate(document)
        self.assertTrue(error.startswith("$.requirements[0].capabilities:"), error)

    def test_protocol_requirement_naming_a_capability_is_rejected(self):
        """A protocol-wide requirement belongs to no capability."""
        document = self._document()
        document["requirements"][0]["scope"] = "protocol"
        [error] = catalog.validate(document)
        self.assertTrue(error.startswith("$.requirements[0].capabilities:"), error)

    def test_release_on_a_record_is_rejected(self):
        """The release lives in the header; a record may not carry its own."""
        document = self._document()
        document["requirements"][0]["version"] = "draft"
        [error] = catalog.validate(document)
        self.assertIn("'version' was unexpected", error)

    def test_versioned_url_is_rejected(self):
        """A source names a page and an anchor, not a release-bound URL."""
        document = self._document()
        document["requirements"][0]["source"]["url"] = "https://ucp.dev/draft/x/"
        [error] = catalog.validate(document)
        self.assertIn("'url' was unexpected", error)

    def test_header_without_its_page_is_rejected(self):
        """Every catalog file says which page it describes."""
        document = self._document()
        del document["source_file"]
        [error] = catalog.validate(document)
        self.assertIn("'source_file' is a required property", error)

    def test_dropped_field_is_rejected(self):
        """Every field the tool emits is required, so losing one is caught."""
        document = self._document()
        del document["requirements"][0]["text_digest"]
        [error] = catalog.validate(document)
        self.assertIn("'text_digest' is a required property", error)


class TestStaleCatalogFiles(unittest.TestCase):
    """Tests for finding and removing catalog files no page produces."""

    def setUp(self):
        self._scratch = tempfile.TemporaryDirectory()
        self.catalog_dir = Path(self._scratch.name) / "catalog"
        self.documents = {Path("shopping/checkout/index.json"): {"requirements": []}}

    def tearDown(self):
        self._scratch.cleanup()

    def _touch(self, relative: str) -> Path:
        path = self.catalog_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
        return path

    def test_missing_directory_has_no_stale_files(self):
        """Before the first run there is nothing to be stale."""
        self.assertEqual(
            catalog.stale_catalog_files(self.catalog_dir, self.documents), []
        )

    def test_file_without_a_document_is_stale(self):
        """Only files this run would not write are reported."""
        self._touch("shopping/checkout/index.json")
        gone = self._touch("shopping/cart/index.json")
        self.assertEqual(
            catalog.stale_catalog_files(self.catalog_dir, self.documents), [gone]
        )

    def test_kept_files_are_not_stale(self):
        """A report written inside the catalog directory is left alone."""
        report = self._touch("extraction_report.json")
        self.assertEqual(
            catalog.stale_catalog_files(
                self.catalog_dir, self.documents, keep=[report]
            ),
            [],
        )

    def test_write_removes_stale_files_and_prunes_what_they_emptied(self):
        """Stale files go, other files stay, and the documents are written."""
        gone = self._touch("shopping/cart/index.json")
        notes = self.catalog_dir / "shopping" / "NOTES.txt"
        notes.write_text("Not a catalog file.\n", encoding="utf-8")
        removed = catalog.write_catalog(self.catalog_dir, self.documents)
        self.assertEqual(removed, [gone])
        self.assertFalse(gone.parent.exists())
        self.assertTrue(notes.exists())
        self.assertTrue((self.catalog_dir / "shopping/checkout/index.json").is_file())


if __name__ == "__main__":
    unittest.main()
