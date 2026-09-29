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

"""Unit tests for stage 2: deciding which clauses are normative."""

import os
import sys
import unittest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../scripts"))
)

from requirements_extractor import classifier, config
from requirements_extractor.models import (
    Annotation,
    BlockType,
    Clause,
    ExtractionReport,
    Level,
    SourceRef,
)


def _clause(text: str) -> Clause:
    """Build a parser-shaped clause for the checkout core document."""
    return Clause(
        text=text,
        source=SourceRef(
            file="docs/specification/shopping/checkout/index.md",
            line_start=1,
            line_end=1,
            section="Checkout Capability > Test",
            block_type=BlockType.PARAGRAPH,
        ),
        document_order=1,
    )


class TestFindKeywords(unittest.TestCase):
    """Tests for keyword location."""

    def test_must_not_is_not_truncated_to_must(self):
        """The longest keyword wins, so a prohibition stays a prohibition."""
        hits = classifier.find_keywords(
            "The business **MUST NOT** reuse a key.", config.OBLIGATION_KEYWORDS
        )
        self.assertEqual([hit.keyword for hit in hits], ["MUST NOT"])
        self.assertTrue(hits[0].bolded)

    def test_unbolded_keyword_is_reported_as_such(self):
        """A plain keyword is found but not marked bolded."""
        hits = classifier.find_keywords("It MUST reply.", config.OBLIGATION_KEYWORDS)
        self.assertEqual([(hit.keyword, hit.bolded) for hit in hits], [("MUST", False)])


class TestClassify(unittest.TestCase):
    """Tests for classifying single clauses."""

    def setUp(self):
        self.report = ExtractionReport()

    def test_bolded_obligation_gets_its_level(self):
        """A single bolded keyword yields one clause at that level."""
        [result] = classifier.classify(
            _clause("The business **SHOULD** log it."), self.report
        )
        self.assertIs(result.level, Level.SHOULD)
        self.assertTrue(result.bolded)

    def test_unbolded_obligation_is_reported_not_emitted(self):
        """Without emphasis the clause is excluded and recorded for review."""
        result = classifier.classify(
            _clause("Businesses MUST respond in time."), self.report
        )
        self.assertEqual(result, [])
        self.assertEqual(len(self.report.candidates_without_emphasis), 1)
        self.assertEqual(
            self.report.candidates_without_emphasis[0]["keywords"], ["MUST"]
        )

    def test_keyword_inside_code_span_is_ignored(self):
        """A keyword in backticks names a value and states nothing."""
        result = classifier.classify(
            _clause("The literal `MUST` is a value."), self.report
        )
        self.assertEqual(result, [])
        self.assertEqual(self.report.as_dict(), ExtractionReport().as_dict())

    def test_rfc2119_boilerplate_is_dropped(self):
        """The keyword definition paragraph is not an obligation."""
        result = classifier.classify(
            _clause(
                "The key words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** "
                "are to be interpreted as described in RFC 2119."
            ),
            self.report,
        )
        self.assertEqual(result, [])
        self.assertEqual(len(self.report.rfc2119_boilerplate), 1)

    def test_compound_sentence_is_split_with_shared_subject(self):
        """Two obligations in one sentence become two clauses."""
        result = classifier.classify(
            _clause(
                "The host **MUST** tear down the context and **MAY** redirect "
                "the buyer."
            ),
            self.report,
        )
        self.assertEqual(
            [(c.text, c.level) for c in result],
            [
                ("The host **MUST** tear down the context", Level.MUST),
                ("The host **MAY** redirect the buyer.", Level.MAY),
            ],
        )
        self.assertTrue(all(c.split_from_compound for c in result))
        self.assertEqual(len(self.report.multi_obligation_sentences), 1)

    def test_compound_without_conjunction_collapses_to_strongest(self):
        """With no boundary to cut at, the strongest level is kept."""
        [result] = classifier.classify(
            _clause("It **MAY** retry, it **MUST** stop after three."), self.report
        )
        self.assertIs(result.level, Level.MUST)
        self.assertEqual(len(self.report.compounds_not_split), 1)

    def test_schema_field_annotation_is_excluded(self):
        """Field optionality markers are not obligations on a party."""
        result = classifier.classify(
            _clause("`ec_version` (string, **REQUIRED**):"), self.report
        )
        self.assertEqual(result, [])
        self.assertEqual(len(self.report.annotations_excluded), 1)

    def test_annotation_keyword_in_prose_is_promoted(self):
        """RECOMMENDED in running prose states a SHOULD."""
        [result] = classifier.classify(
            _clause("Response signatures are **RECOMMENDED** for webhooks."),
            self.report,
        )
        self.assertIs(result.level, Level.SHOULD)
        self.assertIs(result.annotation, Annotation.RECOMMENDED)
        self.assertEqual(len(self.report.annotation_as_obligation), 1)


if __name__ == "__main__":
    unittest.main()
