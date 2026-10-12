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

"""Unit tests for configuration helpers: versions, locations, tokens, schema."""

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts"))
)

from requirements_extractor import config

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "spec"
CHECKOUT_DIR = "docs/specification/shopping/checkout"

# SHA-256 of the canonical JSON of the shipped catalog schema. It changes only
# together with a new schema file and a new CATALOG_SCHEMA_VERSION.
PUBLISHED_SCHEMA_DIGEST = (
    "f46f75751ed9b87fbaaff3a8923fe95b60ae0141b9c9905724475d78a6a72393"
)


class TestSpecVersion(unittest.TestCase):
    """Tests for reading the release from mkdocs.yml."""

    def test_reads_ucp_version(self):
        """The dated release in the fixture is returned verbatim."""
        self.assertEqual(config.spec_version(FIXTURE_ROOT), "2026-01-11")

    def test_defaults_when_no_version_is_declared(self):
        """A mkdocs.yml without ucp_version is the draft."""
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "mkdocs.yml").write_text("site_name: x\n")
            self.assertEqual(
                config.spec_version(Path(directory)), config.DEFAULT_SPEC_VERSION
            )

    def test_missing_mkdocs_is_an_error(self):
        """A wrong spec root fails instead of silently stamping draft."""
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(OSError):
                config.spec_version(Path(directory))


class TestPublishedLocation(unittest.TestCase):
    """Tests for the page and anchor published with each requirement."""

    def test_index_document_renders_as_its_directory(self):
        """index.md maps to the directory, anchored on the last heading."""
        self.assertEqual(
            config.published_page(f"{CHECKOUT_DIR}/index.md"),
            "specification/shopping/checkout/",
        )
        self.assertEqual(
            config.published_anchor("Checkout Capability > Continue URL"),
            "continue-url",
        )

    def test_other_documents_render_as_a_subdirectory(self):
        """rest.md maps to .../checkout/rest/."""
        self.assertEqual(
            config.published_page(f"{CHECKOUT_DIR}/rest.md"),
            "specification/shopping/checkout/rest/",
        )
        self.assertEqual(
            config.published_anchor("Checkout REST Binding > Transport Security"),
            "transport-security",
        )

    def test_explicit_anchor_is_used_as_is(self):
        """A heading's attr_list id replaces the slugified heading."""
        self.assertEqual(
            config.published_anchor("Checkout Capability > Entities > Total", "totals"),
            "totals",
        )

    def test_clause_before_any_heading_has_no_anchor(self):
        """No heading means no fragment, rather than an empty one."""
        self.assertIsNone(config.published_anchor(""))
        self.assertIsNone(config.published_anchor(None))


class TestCatalogFile(unittest.TestCase):
    """Tests for mapping a page to its catalog file."""

    def test_catalog_mirrors_the_specification_tree(self):
        """A page's catalog sits at the same path below the catalog dir."""
        self.assertEqual(
            config.catalog_file(f"{CHECKOUT_DIR}/rest.md"),
            Path("shopping/checkout/rest.json"),
        )
        self.assertEqual(
            config.catalog_file(f"{CHECKOUT_DIR}/index.md"),
            Path("shopping/checkout/index.json"),
        )

    def test_page_outside_the_specification_is_rejected(self):
        """Only pages under the specification root have a catalog file."""
        with self.assertRaises(ValueError):
            config.catalog_file("docs/index.md")


class TestHeadingAttributes(unittest.TestCase):
    """Tests for separating attr_list blocks from heading text."""

    def test_id_is_extracted_and_block_removed(self):
        """`{: #totals }` is dropped from the text and its id returned."""
        self.assertEqual(
            config.split_heading_attributes("Total {: #totals }"), ("Total", "totals")
        )

    def test_colon_is_optional(self):
        """attr_list accepts the block without the leading colon."""
        self.assertEqual(
            config.split_heading_attributes("Detail Product { #detail-product }"),
            ("Detail Product", "detail-product"),
        )

    def test_block_without_an_id_is_removed(self):
        """A class-only block is not shown, and the heading is slugified."""
        self.assertEqual(config.split_heading_attributes("X {: .note }"), ("X", None))

    def test_heading_without_a_block_is_unchanged(self):
        """Ordinary headings pass through."""
        self.assertEqual(
            config.split_heading_attributes("Continue URL"), ("Continue URL", None)
        )


class TestTokens(unittest.TestCase):
    """Tests for the pieces of a readable id."""

    def test_section_token_uses_the_deepest_heading(self):
        """The document title is dropped and the last heading is kept."""
        self.assertEqual(
            config.section_token("Checkout Capability > Status > `continue_url`"),
            "CONTINUE-URL",
        )

    def test_section_token_prefers_an_explicit_anchor(self):
        """Same-named headings stay distinct through their explicit ids."""
        self.assertEqual(
            config.section_token("Order > Events > Guidelines", "events-guidelines"),
            "EVENTS-GUIDELINES",
        )

    def test_long_section_token_is_cut_on_a_word_boundary(self):
        """Tokens stop at the configured length without splitting a word."""
        token = config.section_token("Doc > Handling of Unrecognized Payment Methods")
        self.assertLessEqual(len(token), config.MAX_SECTION_TOKEN_LENGTH)
        self.assertEqual(token, "HANDLING-OF-UNRECOGNIZED")

    def test_missing_section_is_general(self):
        """A clause before any heading still gets a token."""
        self.assertEqual(config.section_token(""), "GENERAL")

    def test_document_token(self):
        """Core documents take no token; bindings take their own."""
        self.assertIsNone(config.document_token(f"{CHECKOUT_DIR}/index.md"))
        self.assertEqual(config.document_token(f"{CHECKOUT_DIR}/embedded.md"), "EP")
        self.assertEqual(config.document_token(f"{CHECKOUT_DIR}/rest.md"), "REST")


class TestCapabilityResolution(unittest.TestCase):
    """Tests for mapping a document to its capability."""

    def test_declaration_in_the_document_is_used(self):
        """The fixture's index.md declares its capability."""
        self.assertEqual(
            config.declared_capability(FIXTURE_ROOT / CHECKOUT_DIR / "index.md"),
            "dev.ucp.shopping.checkout",
        )

    def test_directory_resolves_an_undeclared_document(self):
        """rest.md declares nothing and is resolved by its directory."""
        rel = f"{CHECKOUT_DIR}/rest.md"
        self.assertIsNone(config.declared_capability(FIXTURE_ROOT / rel))
        self.assertEqual(
            config.resolve_capability(rel, FIXTURE_ROOT / rel),
            "dev.ucp.shopping.checkout",
        )

    def test_unknown_directory_is_unresolved(self):
        """A document outside every known directory has no capability."""
        self.assertIsNone(config.resolve_capability("docs/specification/other.md"))


class TestCatalogSchema(unittest.TestCase):
    """Tests tying the published schema URL to the shipped schema."""

    def test_schema_ships_with_the_tool(self):
        """The schema file exists where config says it does."""
        self.assertTrue(config.CATALOG_SCHEMA_PATH.is_file())

    def test_catalog_schema_url_is_the_schema_id(self):
        """$schema in a catalog must name the schema's own $id."""
        schema = json.loads(config.CATALOG_SCHEMA_PATH.read_text(encoding="utf-8"))
        self.assertEqual(schema["$id"], config.CATALOG_SCHEMA_URL)

    def test_schema_url_matches_the_file_location_in_this_repository(self):
        """The URL's path is where the file actually lives on main."""
        prefix = (
            "https://raw.githubusercontent.com/Universal-Commerce-Protocol/"
            ".github/main/"
        )
        self.assertTrue(config.CATALOG_SCHEMA_URL.startswith(prefix))
        repo_root = config.TOOL_ROOT.parent.parent
        self.assertEqual(
            config.CATALOG_SCHEMA_URL.removeprefix(prefix),
            config.CATALOG_SCHEMA_PATH.relative_to(repo_root).as_posix(),
        )

    def test_schema_file_name_carries_its_version(self):
        """Each format version is its own file, so none is edited in place."""
        self.assertEqual(
            config.CATALOG_SCHEMA_PATH.name,
            f"requirements-catalog-{config.CATALOG_SCHEMA_VERSION}.json",
        )

    def test_published_schema_is_unchanged(self):
        """The shipped schema matches the contract catalogs were written to.

        Committed catalogs name this file, so editing it in place would change
        what every one of them means without any of them changing. A format
        change ships as a new schema file with a new version instead. The
        digest covers the canonical JSON, so reformatting the file is free.
        """
        schema = json.loads(config.CATALOG_SCHEMA_PATH.read_text(encoding="utf-8"))
        canonical = json.dumps(
            schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )
        self.assertEqual(
            hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            PUBLISHED_SCHEMA_DIGEST,
        )


if __name__ == "__main__":
    unittest.main()
