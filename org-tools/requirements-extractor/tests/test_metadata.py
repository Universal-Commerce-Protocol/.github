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

"""Unit tests for stage 3: actor, referenced fields and conditions."""

import os
import sys
import unittest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts"))
)

from requirements_extractor import config, metadata
from requirements_extractor.models import BlockType, Clause, Level, SourceRef


def _clause(
    text: str,
    section: str = "Checkout Capability > Test",
    compound_parent: str | None = None,
    block_type: BlockType = BlockType.PARAGRAPH,
) -> Clause:
    """Build a classified obligation for the checkout core document."""
    return Clause(
        text=text,
        source=SourceRef(
            file="docs/specification/shopping/checkout/index.md",
            line_start=1,
            line_end=1,
            section=section,
            block_type=block_type,
        ),
        document_order=1,
        level=Level.MUST,
        bolded=True,
        compound_parent=compound_parent,
    )


class TestExtractActor(unittest.TestCase):
    """Tests for the actor resolution ladder."""

    def test_last_party_before_the_keyword_is_the_subject(self):
        """The subject is the last party named before the keyword."""
        clause = _clause(
            "When a buyer selects an option the platform cannot fully process, "
            "the platform **SHOULD** show an error."
        )
        self.assertEqual(
            metadata.extract_actor(clause), ("platform", config.ACTOR_CONFIDENCE_INLINE)
        )

    def test_party_after_the_keyword_is_not_used(self):
        """A party after the keyword is usually the object, not the subject."""
        clause = _clause("**MUST** present the content to the buyer.")
        self.assertEqual(
            metadata.extract_actor(clause), (None, config.ACTOR_CONFIDENCE_NONE)
        )

    def test_colon_stem_naming_a_party_supplies_the_actor(self):
        """A responsibilities stem assigns its list items to that party."""
        clause = _clause(
            "**MUST** validate origin.", compound_parent="**Host responsibilities:**"
        )
        self.assertEqual(
            metadata.extract_actor(clause),
            ("host", config.ACTOR_CONFIDENCE_COMPOUND_PARENT),
        )

    def test_topic_stem_does_not_supply_an_actor(self):
        """A stem that is a topic label rather than an obligation assigns nothing."""
        clause = _clause(
            "**MUST** be logged.", compound_parent="**Implementation Notes:**"
        )
        self.assertEqual(metadata.extract_actor(clause)[0], None)

    def test_heading_is_the_weakest_signal(self):
        """A party named only in the section heading gets low confidence."""
        clause = _clause(
            "**MUST** respond.", section="Checkout Capability > Business Behavior"
        )
        self.assertEqual(
            metadata.extract_actor(clause),
            ("business", config.ACTOR_CONFIDENCE_SECTION),
        )

    def test_party_after_an_annotation_keyword_is_not_used(self):
        """An annotation keyword anchors the subject search just as MUST does."""
        clause = _clause(
            "The `created` parameter is **OPTIONAL** and is checked by the business."
        )
        self.assertEqual(
            metadata.extract_actor(clause), (None, config.ACTOR_CONFIDENCE_NONE)
        )

    def test_obligation_keyword_is_preferred_to_an_annotation_keyword(self):
        """With both kinds present, the obligation keyword is the anchor."""
        text = "A REQUIRED field is set, so the platform **MUST** send it."
        self.assertEqual(metadata.keyword_position(_clause(text)), text.index("**MUST"))

    def test_possessive_gives_way_to_a_party_named_plainly(self):
        """'the buyer's preference' says whose it is; it is not the subject."""
        clause = _clause(
            "When no scheme is given, the Embedded Checkout can use the buyer's "
            "system preference, and **SHOULD** listen for changes."
        )
        self.assertEqual(
            metadata.extract_actor(clause),
            ("embedded_checkout", config.ACTOR_CONFIDENCE_INLINE),
        )

    def test_possessive_alone_still_names_the_party(self):
        """With nothing else named, the possessive is who the rule binds."""
        clause = _clause(
            "The handler\u2019s trust policy **MUST** authorize the origin."
        )
        self.assertEqual(
            metadata.extract_actor(clause), ("handler", config.ACTOR_CONFIDENCE_INLINE)
        )

    def test_name_inside_a_longer_name_is_not_a_mention(self):
        """An authorization server is not also a server."""
        clause = _clause(
            "The business's authorization server **MUST** validate the assertion."
        )
        self.assertEqual(
            metadata.extract_actor(clause),
            ("auth_server", config.ACTOR_CONFIDENCE_INLINE),
        )

    def test_server_and_mcp_client_name_parties(self):
        """In the bindings the server is the business and an MCP client the platform."""
        server = _clause("When provided, the server **MUST** echo the header.")
        client = _clause("MCP clients **MUST** include a `meta` object.")
        self.assertEqual(metadata.extract_actor(server)[0], "business")
        self.assertEqual(metadata.extract_actor(client)[0], "platform")

    def test_bare_client_is_not_a_party(self):
        """'client' alone is too often part of another term to name a party."""
        clause = _clause(
            "The Embedded Checkout can read the HTTP client hint and **SHOULD** "
            "apply it."
        )
        self.assertEqual(metadata.extract_actor(clause)[0], "embedded_checkout")

    def test_matrix_cell_takes_its_party_from_a_header(self):
        """A keyword-only cell binds the party its row or column names."""
        for context in ("**Platform** | Create", "Create | Platform"):
            clause = _clause(
                "**MUST**", compound_parent=context, block_type=BlockType.TABLE_CELL
            )
            self.assertEqual(
                metadata.extract_actor(clause),
                ("platform", config.ACTOR_CONFIDENCE_COMPOUND_PARENT),
                context,
            )

    def test_header_that_only_mentions_a_party_is_not_used(self):
        """A descriptive row label names a topic, not who is obliged."""
        clause = _clause(
            "**MUST**",
            compound_parent="**Buyer notification** | Description",
            block_type=BlockType.TABLE_CELL,
        )
        self.assertEqual(
            metadata.extract_actor(clause), (None, config.ACTOR_CONFIDENCE_NONE)
        )

    def test_deepest_heading_names_the_party(self):
        """An inner heading naming a party beats an outer one."""
        clause = _clause(
            "**MUST** distinguish this option from its siblings.",
            section="Fulfillment Extension > Rendering > Business Responsibilities",
        )
        self.assertEqual(
            metadata.extract_actor(clause),
            ("business", config.ACTOR_CONFIDENCE_SECTION),
        )


class TestReferencedFields(unittest.TestCase):
    """Tests for recognizing schema field names in inline code."""

    def test_field_shapes_are_kept_and_other_spans_dropped(self):
        """Fields and key-value pins are kept; headers, URLs and literals are not."""
        text = (
            'Set `status: "canceled"`, fill `line_items[]` and `buyer.email`, '
            "send `Content-Digest`, see `https://ucp.dev`, and pass `true`."
        )
        self.assertEqual(
            metadata.extract_referenced_fields(text),
            ["buyer.email", "line_items[]", "status"],
        )


class TestExtractCondition(unittest.TestCase):
    """Tests for recovering the trigger that bounds an obligation."""

    def test_leading_condition_ends_at_its_comma(self):
        """A leading condition is cut at the comma closing the clause."""
        clause = _clause(
            "When `continue_url` is present, the platform **MUST** use it."
        )
        self.assertEqual(
            metadata.extract_condition(clause), "When `continue_url` is present"
        )

    def test_comma_inside_parentheses_does_not_end_the_condition(self):
        """A parenthetical's own comma belongs to the parenthetical."""
        clause = _clause(
            "If the host cannot complete the handshake (e.g., origin failure), "
            "it **MUST** abort."
        )
        self.assertEqual(
            metadata.extract_condition(clause),
            "If the host cannot complete the handshake (e.g., origin failure)",
        )

    def test_trailing_condition_runs_to_the_end(self):
        """A condition after the keyword runs to the end of the sentence."""
        clause = _clause("The host **MUST** fire the event when the action occurs.")
        self.assertEqual(metadata.extract_condition(clause), "when the action occurs")

    def test_trailing_condition_after_an_annotation_keyword(self):
        """A condition after REQUIRED is trailing, not leading."""
        clause = _clause("The platform is **REQUIRED** to retry when the call fails.")
        self.assertEqual(metadata.extract_condition(clause), "when the call fails")

    def test_no_trigger_means_no_condition(self):
        """An unconditional obligation has no condition."""
        self.assertIsNone(metadata.extract_condition(_clause("It **MUST** reply.")))


if __name__ == "__main__":
    unittest.main()
