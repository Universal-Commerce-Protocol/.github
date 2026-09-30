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

"""Unit tests for stage 4: readable ids and content digests."""

import hashlib
import os
import sys
import unittest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts"))
)

from requirements_extractor import identity
from requirements_extractor.models import BlockType, Clause, Level, SourceRef

CHECKOUT = "dev.ucp.shopping.checkout"
INDEX = "docs/specification/shopping/checkout/index.md"
REST = "docs/specification/shopping/checkout/rest.md"
MCP = "docs/specification/shopping/checkout/mcp.md"


def _clause(
    text: str,
    file: str = INDEX,
    line: int = 1,
    section: str = "Checkout Capability > Continue URL",
    compound_parent: str | None = None,
) -> Clause:
    """Build an annotated obligation ready for identity assignment."""
    return Clause(
        text=text,
        source=SourceRef(
            file=file,
            line_start=line,
            line_end=line,
            section=section,
            block_type=BlockType.PARAGRAPH,
        ),
        document_order=line,
        level=Level.MUST,
        bolded=True,
        capability=CHECKOUT,
        compound_parent=compound_parent,
    )


class TestNormalize(unittest.TestCase):
    """Tests for the canonical form that feeds the digest."""

    def test_editorial_differences_are_erased(self):
        """Links, emphasis, backticks, dashes, spacing and case do not matter."""
        self.assertEqual(
            identity.normalize(
                "The  [Business](../x.md) **MUST** set `status` \u2014 Always."
            ),
            "the business must set status - always",
        )

    def test_link_attribute_block_is_dropped_with_the_link(self):
        """`{ target="_blank" }` on a link is markup, not wording."""
        self.assertEqual(
            identity.normalize(
                "Bodies **MUST** be valid JSON as specified in "
                '[RFC 8259](https://tools.ietf.org/html/rfc8259){ target="_blank" }.'
            ),
            "bodies must be valid json as specified in rfc 8259",
        )
        self.assertEqual(
            identity.normalize(
                'Use field syntax ([RFC 8941](https://x.test){target="_blank"}).'
            ),
            "use field syntax (rfc 8941)",
        )

    def test_braces_not_attached_to_a_link_are_kept(self):
        """A brace in prose or inline code is content."""
        self.assertEqual(
            identity.normalize("Send `{action}_request` to [the host](h.md)."),
            "send {action}_request to the host",
        )


class TestRequirementDigest(unittest.TestCase):
    """Tests for the content digest."""

    def test_digest_is_the_prefix_of_sha256_over_the_published_fields(self):
        """A consumer can recompute the digest from the catalog alone."""
        expected = hashlib.sha256(
            f"{CHECKOUT}\x1f\x1fthe business must reply".encode()
        ).hexdigest()[:10]
        self.assertEqual(
            identity.requirement_digest(CHECKOUT, None, "the business must reply"),
            expected,
        )

    def test_capability_and_context_change_the_digest(self):
        """The same words under another capability or parent are different."""
        base = identity.requirement_digest(CHECKOUT, None, "must")
        self.assertNotEqual(
            base, identity.requirement_digest("dev.ucp.shopping.cart", None, "must")
        )
        self.assertNotEqual(
            base, identity.requirement_digest(CHECKOUT, "Platform | Create", "must")
        )


class TestAssignIdentities(unittest.TestCase):
    """Tests for giving a batch of clauses their ids and digests."""

    def test_ordinals_count_within_a_section_in_source_order(self):
        """Ids number from 01 per section, in the order clauses appear."""
        clauses = [
            _clause("The platform **MUST** redirect.", line=12),
            _clause("The business **MUST NOT** reuse a key.", line=14),
            _clause("The host **MUST** tear down.", line=26, section="C > Teardown"),
        ]
        requirements, _ = identity.assign_identities(clauses)
        self.assertEqual(
            [r.id for r in requirements],
            [
                "REQ-CHECKOUT-CONTINUE-URL-01",
                "REQ-CHECKOUT-CONTINUE-URL-02",
                "REQ-CHECKOUT-TEARDOWN-01",
            ],
        )

    def test_binding_documents_add_a_document_token(self):
        """rest.md adds REST; the core document adds nothing."""
        [requirement], _ = identity.assign_identities(
            [
                _clause(
                    "All endpoints **MUST** use TLS 1.3.",
                    file=REST,
                    section="Checkout REST Binding > Transport Security",
                )
            ]
        )
        self.assertEqual(requirement.id, "REQ-CHECKOUT-REST-TRANSPORT-SECURITY-01")

    def test_id_does_not_depend_on_wording_and_digest_does(self):
        """Rewording keeps the id and moves the digest."""
        [before], _ = identity.assign_identities([_clause("It **MUST** reply.")])
        [after], _ = identity.assign_identities([_clause("It **MUST** respond.")])
        self.assertEqual(before.id, after.id)
        self.assertNotEqual(before.content_digest, after.content_digest)

    def test_moving_a_clause_keeps_the_digest(self):
        """The digest ignores file, line and heading."""
        [here], _ = identity.assign_identities([_clause("It **MUST** reply.")])
        [there], _ = identity.assign_identities(
            [_clause("It **MUST** reply.", file=REST, line=90, section="R > Other")]
        )
        self.assertNotEqual(here.id, there.id)
        self.assertEqual(here.content_digest, there.content_digest)

    def test_identical_clauses_share_a_digest_and_are_reported(self):
        """One sentence kept in two documents is flagged as a hazard."""
        text = "The business **MUST** return the error."
        requirements, report = identity.assign_identities(
            [
                _clause(text, file=REST, line=10, section="R > Errors"),
                _clause(text, file=MCP, line=20, section="M > Errors"),
            ]
        )
        self.assertEqual(len({r.content_digest for r in requirements}), 1)
        self.assertEqual(len({r.id for r in requirements}), 2)
        [entry] = report.duplicate_requirements
        self.assertEqual(entry["copies"], 2)
        self.assertEqual(entry["locations"], [f"{MCP}:20", f"{REST}:10"])


if __name__ == "__main__":
    unittest.main()
