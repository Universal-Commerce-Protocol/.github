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

"""Unit tests for stage 1: Markdown to candidate clauses."""

import os
import sys
import unittest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts"))
)

from requirements_extractor import parser
from requirements_extractor.models import BlockType

DOC = "docs/specification/shopping/checkout/index.md"


class TestSplitSentences(unittest.TestCase):
    """Tests for sentence boundary detection."""

    def test_number_ending_a_sentence_is_kept_whole(self):
        """A decimal at the end of a sentence must not lose its last part."""
        self.assertEqual(
            parser.split_sentences(
                "All REST endpoints **MUST** be served over HTTPS with "
                "minimum TLS version 1.3."
            ),
            [
                "All REST endpoints **MUST** be served over HTTPS with "
                "minimum TLS version 1.3."
            ],
        )

    def test_step_number_ending_a_sentence_is_kept(self):
        """A sentence ending in a numbered reference keeps the number."""
        self.assertEqual(
            parser.split_sentences("The platform **MUST NOT** proceed to step 2."),
            ["The platform **MUST NOT** proceed to step 2."],
        )

    def test_trailing_list_marker_residue_is_removed(self):
        """A following list item's numeral left on a sentence is stripped."""
        self.assertEqual(
            parser.split_sentences("Fetch the profile unless already cached. 2. Then"),
            ["Fetch the profile unless already cached.", "Then"],
        )

    def test_leading_list_marker_is_removed(self):
        """A numeral opening a fragment is list residue, not content."""
        self.assertEqual(
            parser.split_sentences("3. Retry the call."), ["Retry the call."]
        )

    def test_abbreviation_does_not_end_a_sentence(self):
        """e.g. followed by a capital letter is not a boundary."""
        self.assertEqual(
            parser.split_sentences("Use a stable key, e.g. The order ID. Then retry."),
            ["Use a stable key, e.g. The order ID.", "Then retry."],
        )

    def test_punctuation_inside_code_span_is_not_a_boundary(self):
        """A colon inside inline code must not split the sentence."""
        self.assertEqual(
            parser.split_sentences(
                "The host **MUST** send `{transfer: [port2]}` to the frame. Then wait."
            ),
            [
                "The host **MUST** send `{transfer: [port2]}` to the frame.",
                "Then wait.",
            ],
        )

    def test_fragments_without_letters_are_dropped(self):
        """Table debris such as a lone dash is not a sentence."""
        self.assertEqual(parser.split_sentences("-"), [])


class TestMaskCodeSpans(unittest.TestCase):
    """Tests for masking inline code before keyword scanning."""

    def test_mask_preserves_length_and_hides_keywords(self):
        """Offsets survive masking, and the keyword inside backticks is gone."""
        text = "The value `MUST` is literal."
        masked = parser.mask_code_spans(text)
        self.assertEqual(len(masked), len(text))
        self.assertNotIn("MUST", masked)
        self.assertTrue(masked.startswith("The value "))


class TestParseText(unittest.TestCase):
    """Tests for walking a document's token stream."""

    def test_fenced_code_is_excluded(self):
        """Nothing inside a fenced block becomes a clause."""
        source = "# Title\n\n```text\nThe platform MUST ignore this.\n```\n"
        self.assertEqual(parser.parse_text(source, DOC), [])

    def test_source_reference_records_section_and_line(self):
        """Clauses carry the heading breadcrumb and a 1-based line."""
        source = "# Checkout\n\n## Status\n\nThe business **MUST** reply.\n"
        [clause] = parser.parse_text(source, DOC)
        self.assertEqual(clause.source.section, "Checkout > Status")
        self.assertEqual(clause.source.line_start, 5)
        self.assertEqual(clause.source.file, DOC)
        self.assertIs(clause.source.block_type, BlockType.PARAGRAPH)

    def test_hard_wrapped_sentence_is_reflowed(self):
        """A sentence wrapped across lines is one clause on one line."""
        source = "# T\n\nAll endpoints **MUST** use TLS version\n1.3.\n"
        [clause] = parser.parse_text(source, DOC)
        self.assertEqual(clause.text, "All endpoints **MUST** use TLS version 1.3.")
        self.assertEqual((clause.source.line_start, clause.source.line_end), (3, 4))

    def test_heading_attribute_block_is_kept_out_of_the_breadcrumb(self):
        """`{: #totals }` is not in the section, and its id reaches the URL."""
        source = "# Checkout\n\n### Total {: #totals }\n\nIt **MUST** add up.\n"
        [clause] = parser.parse_text(source, DOC)
        self.assertEqual(clause.source.section, "Checkout > Total")
        self.assertEqual(clause.source.anchor, "totals")
        self.assertTrue(clause.source.as_dict("draft")["url"].endswith("/#totals"))

    def test_deeper_heading_without_a_block_has_no_anchor(self):
        """An explicit id belongs to its own heading, not to subsections."""
        source = (
            "# Checkout\n\n## Total {: #totals }\n\n### Verification\n\n"
            "It **MUST** add up.\n"
        )
        [clause] = parser.parse_text(source, DOC)
        self.assertIsNone(clause.source.anchor)
        self.assertEqual(clause.source.section, "Checkout > Total > Verification")

    def test_list_under_colon_stem_inherits_the_stem(self):
        """Items of a list introduced by a colon record the stem as parent."""
        source = (
            "# T\n\n**Host responsibilities:**\n\n"
            "- **MUST** validate origin.\n- **SHOULD** log it.\n"
        )
        clauses = parser.parse_text(source, DOC)
        items = [c for c in clauses if c.source.block_type is BlockType.LIST_ITEM]
        self.assertEqual(len(items), 2)
        for item in items:
            self.assertEqual(item.compound_parent, "**Host responsibilities:**")

    def test_list_without_stem_has_no_parent(self):
        """A list not introduced by a colon inherits nothing."""
        source = "# T\n\nSome prose.\n\n- **MUST** validate origin.\n"
        items = [
            c
            for c in parser.parse_text(source, DOC)
            if c.source.block_type is BlockType.LIST_ITEM
        ]
        self.assertEqual([item.compound_parent for item in items], [None])

    def _item_parents(self, source):
        return [
            c.compound_parent
            for c in parser.parse_text(source, DOC)
            if c.source.block_type is BlockType.LIST_ITEM
        ]

    def test_stem_does_not_carry_past_a_code_block_and_heading(self):
        """A stem followed by a code sample and a new section is dropped."""
        source = (
            "# T\n\nPlatforms **MUST** include a `meta` object:\n\n"
            "```json\n{}\n```\n\n## Platform Requirements\n\n"
            "1. Platforms **MUST** send a profile.\n"
        )
        self.assertEqual(self._item_parents(source), [None])

    def test_stem_does_not_carry_past_a_code_block(self):
        """A code block between a stem and a list ends the stem."""
        source = "# T\n\nSend this:\n\n```json\n{}\n```\n\n- **MUST** retry.\n"
        self.assertEqual(self._item_parents(source), [None])

    def test_stem_does_not_carry_past_an_html_block(self):
        """An HTML block between a stem and a list ends the stem."""
        source = "# T\n\nSend this:\n\n<div>x</div>\n\n- **MUST** retry.\n"
        self.assertEqual(self._item_parents(source), [None])

    def test_stem_does_not_carry_past_a_table(self):
        """A table between a stem and a list ends the stem."""
        # Header-only, because header cells return before the stem update.
        source = "# T\n\nFields:\n\n| A | B |\n| - | - |\n\n- **MUST** retry.\n"
        self.assertEqual(self._item_parents(source), [None])

    def test_table_cell_carries_row_and_column_context(self):
        """A matrix cell holding only a keyword keeps its row and column."""
        source = (
            "# T\n\n| Party | Create |\n| ----- | ------ |\n| Platform | **MUST** |\n"
        )
        cells = [
            c
            for c in parser.parse_text(source, DOC)
            if c.source.block_type is BlockType.TABLE_CELL
        ]
        must = [c for c in cells if c.text == "**MUST**"]
        self.assertEqual(len(must), 1)
        self.assertEqual(must[0].compound_parent, "Platform | Create")


if __name__ == "__main__":
    unittest.main()
