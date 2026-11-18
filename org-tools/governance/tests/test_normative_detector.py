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

"""Unit tests for the normative RFC 2119 clause extractor and change detector."""

import os
import sys
import unittest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts"))
)

from normative_detector import (
    detect_normative_changes,
    extract_normative_clauses,
    is_markdown_file,
)


class TestNormativeParserAndClassifier(unittest.TestCase):
    """Tests for Markdown prose extraction and RFC 2119 classification."""

    def test_is_markdown_file(self):
        """Test Markdown file extension detection."""
        self.assertTrue(is_markdown_file("README.md"))
        self.assertTrue(is_markdown_file("docs/specification/checkout.MD"))
        self.assertTrue(is_markdown_file("notes.markdown"))
        self.assertFalse(is_markdown_file("scripts/pr_validator.py"))
        self.assertFalse(is_markdown_file("source/schemas/checkout.json"))

    def test_all_seven_bolded_obligation_keywords(self):
        """Test extraction of all 7 bolded RFC 2119 obligation levels."""
        md = (
            "1. The server **MUST** validate the token.\n"
            "2. The server **MUST NOT** expose secrets.\n"
            "3. The client **SHALL** use HTTPS.\n"
            "4. The client **SHALL NOT** reuse nonces.\n"
            "5. The response **SHOULD** include a timestamp.\n"
            "6. The response **SHOULD NOT** exceed 1MB.\n"
            "7. The caller **MAY** cache the result.\n"
        )
        clauses = extract_normative_clauses(md)
        self.assertEqual(len(clauses), 7)
        self.assertEqual(
            [c.level for c in clauses],
            [
                "MUST",
                "MUST NOT",
                "SHALL",
                "SHALL NOT",
                "SHOULD",
                "SHOULD NOT",
                "MAY",
            ],
        )
        self.assertTrue(all(c.bolded for c in clauses))

    def test_unbolded_uppercase_keywords_detected(self):
        """Test extraction of unbolded uppercase RFC 2119 keywords in prose."""
        md = (
            "The server MUST validate the request.\n\n"
            "The server MUST NOT log credentials.\n\n"
            "The client SHOULD retry on 503.\n\n"
            "This header is REQUIRED for authentication.\n"
        )
        clauses = extract_normative_clauses(md)
        self.assertEqual(len(clauses), 4)
        self.assertEqual(
            [(c.level, c.keyword, c.bolded) for c in clauses],
            [
                ("MUST", "MUST", False),
                ("MUST NOT", "MUST NOT", False),
                ("SHOULD", "SHOULD", False),
                ("MUST", "REQUIRED", False),
            ],
        )

    def test_lowercase_and_partial_words_ignored(self):
        """Test that lowercase modal verbs and partial word matches are ignored."""
        md = (
            "The server must validate the request and should log errors.\n\n"
            "You may optionality check MUSTANG or MAYBE or SHOULDER.\n"
        )
        clauses = extract_normative_clauses(md)
        self.assertEqual(clauses, [])

    def test_annotation_keywords_promoted_in_prose(self):
        """Test that REQUIRED, RECOMMENDED, and OPTIONAL in prose promote to MUST/SHOULD/MAY."""
        md = (
            "TLS 1.3 support is **REQUIRED** for all endpoints.\n\n"
            "Idempotency keys are **RECOMMENDED** for POST requests.\n\n"
            "Webhook signatures are **OPTIONAL** in sandbox mode.\n"
        )
        clauses = extract_normative_clauses(md)
        self.assertEqual(len(clauses), 3)
        self.assertEqual(
            [(c.level, c.keyword, c.bolded) for c in clauses],
            [
                ("MUST", "REQUIRED", True),
                ("SHOULD", "RECOMMENDED", True),
                ("MAY", "OPTIONAL", True),
            ],
        )

    def test_schema_field_annotations_excluded(self):
        """Test that schema field optionality headers like `field` (string, REQUIRED): are excluded."""
        md = (
            "`ec_version` (string, **REQUIRED**):\n\n"
            "`checkout_id` (string, REQUIRED).\n\n"
            "**`metadata`** (object, **OPTIONAL**):\n"
        )
        clauses = extract_normative_clauses(md)
        self.assertEqual(clauses, [])

    def test_rfc2119_boilerplate_excluded(self):
        """Test that standard RFC 2119 boilerplate sentences citing >= 4 keywords are excluded."""
        md = (
            'The key words "**MUST**", "**MUST NOT**", "**REQUIRED**", '
            '"**SHALL**", "**SHALL NOT**", "**SHOULD**", "**SHOULD NOT**", '
            '"**RECOMMENDED**", "**MAY**", and "**OPTIONAL**" in this document '
            "are to be interpreted as described in RFC 2119.\n\n"
            'The key words "MUST", "MUST NOT", "SHOULD", and "MAY" are normative.\n'
        )
        clauses = extract_normative_clauses(md)
        self.assertEqual(clauses, [])

    def test_fenced_and_indented_code_blocks_ignored(self):
        """Test that fenced code blocks and indented code blocks are ignored."""
        md = (
            "```json\n"
            '{"note": "The server **MUST** ignore this block"}\n'
            "```\n\n"
            "~~~python\n"
            "# The client MUST ignore tilde fences too\n"
            "~~~\n\n"
            "Paragraph before indented code.\n\n"
            "    if x **MUST** be 1:\n"
            "        return REQUIRED\n"
        )
        clauses = extract_normative_clauses(md)
        self.assertEqual(clauses, [])

    def test_inline_code_spans_ignored_and_punctuation_inside_code_preserved(self):
        """Test that keywords and punctuation inside inline backticks do not trigger or split."""
        md = (
            "The status value `MUST` or `REQUIRED` is a literal string.\n\n"
            "The payload `{transfer: [port2]}` **MUST** be serialized as JSON.\n"
        )
        clauses = extract_normative_clauses(md)
        self.assertEqual(len(clauses), 1)
        self.assertEqual(
            clauses[0].text,
            "The payload `{transfer: [port2]}` **MUST** be serialized as JSON.",
        )

    def test_headings_and_html_blocks_ignored(self):
        """Test that ATX headings, Setext headings, and HTML blocks/comments are ignored."""
        md = (
            "# The Server **MUST** Ignore Headings\n\n"
            "Setext Heading **MUST** Be Ignored\n"
            "==================================\n\n"
            "<!-- The server **MUST** ignore HTML comments -->\n\n"
            "<div>The server **MUST** ignore HTML blocks</div>\n\n"
            "The server **MUST** strip <br/> inline HTML tags.\n"
        )
        clauses = extract_normative_clauses(md)
        self.assertEqual(len(clauses), 1)
        self.assertEqual(clauses[0].text, "The server **MUST** strip inline HTML tags.")

    def test_abbreviations_and_decimals_preserved(self):
        """Test that abbreviations like e.g. and decimals like 1.3. are not corrupted."""
        md = (
            "Clients **MUST** support modern protocols, e.g. TLS version 1.3.\n"
            "They **SHOULD** also complete step 2.\n"
        )
        clauses = extract_normative_clauses(md)
        self.assertEqual(len(clauses), 2)
        self.assertEqual(
            clauses[0].text,
            "Clients **MUST** support modern protocols, e.g. TLS version 1.3.",
        )
        self.assertEqual(
            clauses[1].text,
            "They **SHOULD** also complete step 2.",
        )

    def test_colon_stem_attaches_to_list_items_and_resets_after_code_block(self):
        """Test colon-terminated stem attachment and reset on intervening code fence."""
        md = (
            "When processing a request, the server:\n\n"
            "- **MUST** verify the signature.\n"
            "- **SHOULD** log the request ID.\n\n"
            "When building a config:\n\n"
            "```yaml\n"
            "key: value\n"
            "```\n\n"
            "- **MUST** use UTF-8.\n"
        )
        clauses = extract_normative_clauses(md)
        self.assertEqual(len(clauses), 3)
        self.assertEqual(
            clauses[0].compound_parent,
            "When processing a request, the server:",
        )
        self.assertEqual(
            clauses[1].compound_parent,
            "When processing a request, the server:",
        )
        self.assertIsNone(clauses[2].compound_parent)

    def test_table_cells_get_row_and_column_context(self):
        """Test GFM pipe table extraction and row | column compound_parent context."""
        md = (
            "| Field | Requirement | Notes |\n"
            "| --- | --- | --- |\n"
            "| `id` | The server **MUST** populate this field. | Primary key |\n"
        )
        clauses = extract_normative_clauses(md)
        self.assertEqual(len(clauses), 1)
        self.assertEqual(clauses[0].level, "MUST")
        self.assertEqual(clauses[0].compound_parent, "`id` | Requirement")

    def test_compound_sentence_splitting_and_collapsing(self):
        """Test compound sentence splitting on conjunctions and collapsing without conjunctions."""
        md = (
            "Clients **MUST** send the header and **SHOULD** retry on timeout.\n\n"
            "When a client **MUST** retry, it **SHOULD** use exponential backoff.\n"
        )
        clauses = extract_normative_clauses(md)
        self.assertEqual(len(clauses), 3)
        self.assertEqual(clauses[0].level, "MUST")
        self.assertEqual(clauses[0].text, "Clients **MUST** send the header")
        self.assertEqual(clauses[1].level, "SHOULD")
        self.assertEqual(clauses[1].text, "Clients **SHOULD** retry on timeout.")
        # Second sentence has no coordinating conjunction between MUST and SHOULD -> collapses to MUST
        self.assertEqual(clauses[2].level, "MUST")
        self.assertEqual(
            clauses[2].text,
            "When a client **MUST** retry, it **SHOULD** use exponential backoff.",
        )

    def test_compound_conjunctions_inside_code_spans_not_split(self):
        """Test that conjunctions inside inline code spans do not split compound sentences."""
        md = (
            "If a header **MUST** equal `a;b` (**MAY** also equal `c`), reject others.\n\n"
            "Clients MUST send `**MUST**` and SHOULD log retries.\n"
        )
        clauses = extract_normative_clauses(md)
        self.assertEqual(len(clauses), 3)
        self.assertEqual(clauses[0].level, "MUST")
        self.assertEqual(
            clauses[0].text,
            "If a header **MUST** equal `a;b` (**MAY** also equal `c`), reject others.",
        )
        self.assertEqual(clauses[1].text, "Clients MUST send `**MUST**`")
        self.assertEqual(clauses[2].text, "Clients SHOULD log retries.")


class TestDetectNormativeChanges(unittest.TestCase):
    """Tests for detect_normative_changes across full content and diff patches."""

    def test_non_markdown_file_ignored(self):
        """Test that non-Markdown files never trigger normative clause changes."""
        res = detect_normative_changes(
            file_path="src/server.py",
            base_content="# The server MUST do X\n",
            head_content="# The server MUST do Y\n",
        )
        self.assertFalse(res.has_normative_changes)

    def test_non_normative_edit_in_same_paragraph_does_not_trigger(self):
        """Test that editing a non-normative sentence next to a normative one does not trigger."""
        base = (
            "This section provides an overview of checkout.\n"
            "The server **MUST** return a 200 OK response.\n"
        )
        head = (
            "This section provides a detailed overview of checkout sessions.\n"
            "The server **MUST** return a 200 OK response.\n"
        )
        res = detect_normative_changes(
            "docs/specification/checkout.md",
            base_content=base,
            head_content=head,
        )
        self.assertFalse(res.has_normative_changes)

    def test_wrapped_line_edit_in_normative_sentence_triggers(self):
        """Test that editing a continuation line of a normative sentence triggers escalation."""
        base = "The server **MUST** return\na 200 OK response within 5 seconds.\n"
        head = "The server **MUST** return\na 201 Created response within 10 seconds.\n"
        res = detect_normative_changes(
            "docs/specification/checkout.md",
            base_content=base,
            head_content=head,
        )
        self.assertTrue(res.has_normative_changes)
        self.assertEqual(res.affected_keywords, ["MUST"])

    def test_pure_line_wrap_reflow_does_not_trigger_but_emphasis_change_triggers(self):
        """Test that pure hard-wrap reflow matches requirements_extractor while emphasis edits trigger."""
        base = "The server **MUST** return\na 200 OK response.\n"
        head = "The server **MUST** return a 200 OK response.\n"
        res = detect_normative_changes(
            "docs/specification/checkout.md",
            base_content=base,
            head_content=head,
        )
        self.assertFalse(res.has_normative_changes)

        head_unbolded = "The server MUST return a 200 OK response.\n"
        res_emphasis = detect_normative_changes(
            "docs/specification/checkout.md",
            base_content=base,
            head_content=head_unbolded,
        )
        self.assertTrue(res_emphasis.has_normative_changes)
        self.assertEqual(res_emphasis.affected_keywords, ["MUST"])

    def test_editing_colon_stem_above_normative_list_triggers(self):
        """Test that modifying the colon stem introducing normative bullets triggers escalation."""
        base = (
            "When handling a checkout request, the server:\n\n"
            "- **MUST** validate the cart items.\n"
        )
        head = (
            "When handling an order request, the server:\n\n"
            "- **MUST** validate the cart items.\n"
        )
        res = detect_normative_changes(
            "docs/specification/checkout.md",
            base_content=base,
            head_content=head,
        )
        self.assertTrue(res.has_normative_changes)
        self.assertEqual(res.affected_keywords, ["MUST"])

    def test_editing_list_item_under_normative_stem_triggers(self):
        """Test that modifying a bullet item under a normative colon stem triggers escalation."""
        base = (
            "The server **MUST** validate all of the following fields:\n\n"
            "- `checkout_id`\n"
            "- `merchant_id`\n"
        )
        head = (
            "The server **MUST** validate all of the following fields:\n\n"
            "- `checkout_id`\n"
            "- `store_id`\n"
        )
        res = detect_normative_changes(
            "docs/specification/checkout.md",
            base_content=base,
            head_content=head,
        )
        self.assertTrue(res.has_normative_changes)
        self.assertEqual(res.affected_keywords, ["MUST"])

    def test_patch_fallback_mode_detects_changes(self):
        """Test that unified diff patch fallback detects normative changes when full content is absent."""
        patch = (
            "@@ -10,3 +10,3 @@\n"
            " Context line before.\n"
            "-The client **SHOULD** retry failed requests.\n"
            "+The client **MUST** retry failed requests.\n"
            " Context line after.\n"
        )
        res = detect_normative_changes(
            "docs/specification/overview.md",
            patch=patch,
        )
        self.assertTrue(res.has_normative_changes)
        self.assertEqual(res.affected_keywords, ["MUST", "SHOULD"])

    def test_link_retargeting_and_non_keyword_formatting_do_not_trigger(self):
        """Test that link URL retargeting, attr_list attributes, and non-keyword italics do not trigger, while link label or code-span wildcard changes do."""
        base = (
            "Payloads **MUST** conform to [RFC 8259](http://tools.ietf.org/html/rfc8259) "
            "for capability `dev.ucp.*` - with *valid* UTF-8.\n"
        )
        head_cosmetic = (
            'Payloads **MUST** conform to [RFC 8259](https://datatracker.ietf.org/doc/html/rfc8259){ target="_blank" } '
            "for capability `dev.ucp.*` \u2014 with valid UTF-8.\n"
        )
        res_cosmetic = detect_normative_changes(
            "docs/specification/checkout.md",
            base_content=base,
            head_content=head_cosmetic,
        )
        self.assertFalse(res_cosmetic.has_normative_changes)

        head_code_wildcard_changed = (
            "Payloads **MUST** conform to [RFC 8259](http://tools.ietf.org/html/rfc8259) "
            "for capability `dev.ucp.shopping` - with *valid* UTF-8.\n"
        )
        res_wildcard = detect_normative_changes(
            "docs/specification/checkout.md",
            base_content=base,
            head_content=head_code_wildcard_changed,
        )
        self.assertTrue(res_wildcard.has_normative_changes)

        head_link_label_changed = (
            "Payloads **MUST** conform to [RFC 9110](http://tools.ietf.org/html/rfc8259) "
            "for capability `dev.ucp.*` - with *valid* UTF-8.\n"
        )
        res_label = detect_normative_changes(
            "docs/specification/checkout.md",
            base_content=base,
            head_content=head_link_label_changed,
        )
        self.assertTrue(res_label.has_normative_changes)

    def test_label_led_bullet_field_or_status_change_triggers(self):
        """Test that renaming a field/status label on a multi-sentence bullet triggers while non-normative bullet prose does not."""
        base = (
            "* **complete_in_progress**: The Complete Checkout request was accepted. "
            "The response **MUST NOT** contain order.\n"
            "* `credential` (string, **OPTIONAL**): Bearer token. "
            "**MUST** be set if `auth` is present.\n"
        )
        head_non_normative_prose = (
            "* **complete_in_progress**: The Complete Checkout request was accepted by the Business. "
            "The response **MUST NOT** contain order.\n"
            "* `credential` (string, **OPTIONAL**): Opaque bearer token. "
            "**MUST** be set if `auth` is present.\n"
        )
        self.assertFalse(
            detect_normative_changes(
                "docs/specification/checkout.md",
                base_content=base,
                head_content=head_non_normative_prose,
            ).has_normative_changes
        )

        head_renamed_field = (
            "* **complete_in_progress**: The Complete Checkout request was accepted. "
            "The response **MUST NOT** contain order.\n"
            "* `api_key` (string, **OPTIONAL**): Bearer token. "
            "**MUST** be set if `auth` is present.\n"
        )
        res_renamed = detect_normative_changes(
            "docs/specification/checkout.md",
            base_content=base,
            head_content=head_renamed_field,
        )
        self.assertTrue(res_renamed.has_normative_changes)
        self.assertEqual(res_renamed.affected_keywords, ["MUST"])


if __name__ == "__main__":
    unittest.main()
