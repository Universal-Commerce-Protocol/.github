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

"""Unit tests for configuration helpers: versions, URLs, tokens, schema."""

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


class TestPublishedUrl(unittest.TestCase):
    """Tests for the URLs published with each requirement."""

    def test_index_document_renders_as_its_directory(self):
        """index.md maps to the directory URL, anchored on the last heading."""
        self.assertEqual(
            config.published_url(
                f"{CHECKOUT_DIR}/index.md",
                "Checkout Capability > Continue URL",
                "2026-01-11",
            ),
            "https://ucp.dev/2026-01-11/specification/shopping/checkout/#continue-url",
        )

    def test_other_documents_render_as_a_subdirectory(self):
        """rest.md maps to .../checkout/rest/."""
        self.assertEqual(
            config.published_url(
                f"{CHECKOUT_DIR}/rest.md",
                "Checkout REST Binding > Transport Security",
                "draft",
            ),
            "https://ucp.dev/draft/specification/shopping/checkout/rest/"
            "#transport-security",
        )


class TestTokens(unittest.TestCase):
    """Tests for the pieces of a readable id."""

    def test_section_token_uses_the_deepest_heading(self):
        """The document title is dropped and the last heading is kept."""
        self.assertEqual(
            config.section_token("Checkout Capability > Status > `continue_url`"),
            "CONTINUE-URL",
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


if __name__ == "__main__":
    unittest.main()
