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

"""Stage 3: attaching the metadata a requirement needs to be actionable.

An obligation is only useful to an implementer if it says who is bound, what
it operates on, and when it applies. This stage derives those three from the
clause and its surroundings.

Actor
  Resolved by a fixed ladder of strategies, strongest first, each carrying a
  confidence so that consumers can tell a stated actor from an inferred one.
  The ladder stops at the first strategy that answers, and the confidence is
  that strategy's, never an average.

  Only text before the keyword is considered. This is the stage's least
  obvious rule and the one most likely to be "fixed" by a later reader, so:
  a lexicon match after the keyword is usually the direct object rather than
  the party under obligation. "**MUST** present the content to the buyer"
  obliges the host. Across this corpus the signal is wrong far more often
  than it is right, so it is rejected and reported instead of used.

Referenced fields
  The inline-code identifiers the obligation operates on, recognized by
  shape rather than by exclusion. A span that pins a field to a value keeps
  the field and drops the value.

Condition
  The trigger clause that bounds when the obligation applies, kept as the
  spec's own words. Reducing "When the pricing basis is the sale basis" to a
  formal predicate would be a semantic claim this stage cannot honestly
  make, so the text is recorded verbatim and normalization is left to a
  consumer that knows the schema.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
import re

from requirements_extractor import classifier, config, parser
from requirements_extractor.models import BlockType, Clause, ExtractionReport

# Surface form -> canonical actor, longest surface first so that "payment
# handler" is not shadowed by "handler" and "embedded checkout" is not
# shadowed by a bare party name.
_SURFACE_TO_ACTOR: dict[str, str] = {
    form: actor for actor, forms in config.ACTOR_LEXICON.items() for form in forms
}
_SURFACES: tuple[str, ...] = tuple(sorted(_SURFACE_TO_ACTOR, key=len, reverse=True))
_SURFACE_RE = {
    surface: re.compile(r"\b" + re.escape(surface) + r"\b", re.IGNORECASE)
    for surface in _SURFACES
}

# The possessive ending after a party's name, as in "the buyer's", with a
# straight or a typographic apostrophe.
_POSSESSIVE_RE = re.compile(r"['\u2019]s\b")

# Emphasis and code markers around a table header, as in "**Platform**".
_HEADER_MARKUP_RE = re.compile(r"[*_`]")

_CODE_SPAN_RE = re.compile(r"`([^`]*)`")

# Markdown that should not survive into a recorded condition.
_LINK_RE = config.MARKDOWN_LINK_RE
_EMPHASIS_RE = re.compile(r"\*\*|\*|__")

_OPENERS = "([{"
_CLOSERS = ")]}"


def keyword_position(clause: Clause) -> int:
    """Return the offset where this clause's governing keyword begins.

    Obligation keywords are searched first. A clause promoted from an
    annotation keyword ("is **REQUIRED** to") has none, so the annotation
    keywords are searched next; without them the actor and condition stages
    would treat the whole sentence as "before the keyword".

    Args:
      clause: A classified obligation.

    Returns:
      The offset of the governing keyword, or the length of the text when no
      keyword can be located, which makes "before the keyword" mean "anywhere".

    """
    masked = parser.mask_code_spans(clause.text)
    for keywords in (config.OBLIGATION_KEYWORDS, config.ANNOTATION_KEYWORDS):
        hits = classifier.find_keywords(masked, keywords)
        if hits:
            bolded = [hit for hit in hits if hit.bolded]
            return (bolded[0] if bolded else hits[0]).outer_start
    return len(clause.text)


def _lexicon_matches(text: str, end: int) -> list[tuple[int, int, str]]:
    """Return every party named in `text[:end]`, as (start, stop, actor).

    A name inside a longer one is not a mention of its own: "authorization
    server" names the authorization server, not a server. Surfaces are tried
    longest first, so the longer name is kept and a shorter one overlapping
    it is dropped.
    """
    found: list[tuple[int, int, str]] = []
    for surface in _SURFACES:
        for match in _SURFACE_RE[surface].finditer(text, 0, end):
            if not any(
                match.start() < stop and start < match.end() for start, stop, _ in found
            ):
                found.append((match.start(), match.end(), _SURFACE_TO_ACTOR[surface]))
    return found


def _last_match_before(text: str, cutoff: int) -> str | None:
    """Return the canonical actor of the last lexicon match before `cutoff`.

    A possessive counts only when no party is named plainly. In "the
    Embedded Checkout can use the buyer's system preference ... and
    **SHOULD** listen for changes", "the buyer's" says whose preference it
    is, and the Embedded Checkout is the subject. In "The handler's trust
    policy **MUST** authorize ...", the possessive is the only name, and it
    is the handler's policy the rule binds.
    """
    matches = _lexicon_matches(text, cutoff)
    plain = [match for match in matches if not _POSSESSIVE_RE.match(text, match[1])]
    candidates = plain or matches
    return max(candidates)[2] if candidates else None


def _first_match_within(text: str, limit: int) -> str | None:
    """Return the canonical actor of the earliest match starting within `limit`."""
    matches = [match for match in _lexicon_matches(text, len(text)) if match[0] < limit]
    return min(matches)[2] if matches else None


def _header_actor(context: str) -> str | None:
    """Return the party a table cell's row or column header names, if any.

    The parser gives a cell the context "<row label> | <column header>". In
    an obligation matrix one of them is a party -- "Platform | Create" -- and
    the cell holds only a keyword. A header counts only when it is a party's
    name and nothing more: "**Buyer notification**" labels a topic, and the
    buyer it mentions is not who the cell obliges.
    """
    for header in context.split(" | "):
        name = _HEADER_MARKUP_RE.sub("", header).strip().lower()
        if name in _SURFACE_TO_ACTOR:
            return _SURFACE_TO_ACTOR[name]
    return None


def _mentions_actor_after(text: str, cutoff: int) -> str | None:
    """Return an actor mentioned only after the keyword, for reporting."""
    for surface in _SURFACES:
        match = _SURFACE_RE[surface].search(text, cutoff)
        if match:
            return _SURFACE_TO_ACTOR[surface]
    return None


def extract_actor(clause: Clause) -> tuple[str | None, float]:
    """Resolve the party an obligation binds, with a confidence.

    Strategies are tried strongest first and the first answer wins:

      0.9  the last lexicon match before the keyword, which is the subject
      0.8  for a table cell, a row or column header that is a party's name,
           such as the "Platform" row of an obligation matrix
      0.8  a colon-list stem that names the party, e.g. "**Host
           responsibilities**:", where the obligation itself is a bare
           fragment such as "**MUST** validate that ..."
      0.5  a party named in the heading breadcrumb, deepest heading first
      0.0  unresolved

    Args:
      clause: A classified obligation.

    Returns:
      The canonical actor and the confidence of the strategy that found it,
      or (None, 0.0).

    """
    masked = parser.mask_code_spans(clause.text)

    inline = _last_match_before(masked, keyword_position(clause))
    if inline:
        return inline, config.ACTOR_CONFIDENCE_INLINE

    if clause.source.block_type is BlockType.TABLE_CELL and clause.compound_parent:
        header = _header_actor(clause.compound_parent)
        if header:
            return header, config.ACTOR_CONFIDENCE_COMPOUND_PARENT

    if clause.compound_parent and config.STEM_OBLIGATION_LABEL_RE.search(
        clause.compound_parent
    ):
        stem = _first_match_within(
            parser.mask_code_spans(clause.compound_parent),
            config.STEM_ACTOR_MAX_OFFSET,
        )
        if stem:
            return stem, config.ACTOR_CONFIDENCE_COMPOUND_PARENT

    # The innermost heading is the most specific. In "Fulfillment Extension >
    # Rendering > Business Responsibilities" it names the party, while the
    # outermost only names the page the section is on.
    for heading in reversed((clause.source.section or "").split(" > ")):
        section = _first_match_within(heading, len(heading))
        if section:
            return section, config.ACTOR_CONFIDENCE_SECTION

    return None, config.ACTOR_CONFIDENCE_NONE


def extract_referenced_fields(text: str) -> list[str]:
    """Return the schema fields an obligation names, sorted and deduplicated.

    Args:
      text: Clause text, with code spans intact.

    Returns:
      Canonical field names. A span pinning a field to a value contributes the
      field alone, so ``severity: "recoverable"`` yields ``severity``.

    """
    fields: set[str] = set()

    for raw in _CODE_SPAN_RE.findall(text):
        value = raw.strip()
        if not value or len(value) > config.FIELD_MAX_LENGTH:
            continue
        if config.FIELD_URL_RE.match(value):
            continue

        pair = config.FIELD_KEY_VALUE_RE.match(value)
        if pair:
            value = pair.group(1)

        if value in config.FIELD_STOP_WORDS:
            continue
        if config.FIELD_NAME_RE.match(value):
            fields.add(value)

    return sorted(fields)


def _clean(text: str) -> str:
    """Strip link syntax and emphasis from a recorded condition."""
    without_links = _LINK_RE.sub(r"\1", text)
    return " ".join(_EMPHASIS_RE.sub("", without_links).split())


def _subordinate_end(text: str, start: int) -> int:
    """Find the comma closing a leading subordinate clause.

    Commas inside brackets belong to a parenthetical rather than to the
    sentence structure -- "(e.g., origin validation failure)" contains one --
    so only depth-zero commas end the clause.

    Args:
      text: Clause text with code spans masked.
      start: Offset of the trigger word.

    Returns:
      Offset of the closing comma, or -1 if there is none.

    """
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char in _OPENERS:
            depth += 1
        elif char in _CLOSERS:
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            return index
    return -1


def extract_condition(clause: Clause) -> str | None:
    """Return the trigger clause bounding when an obligation applies.

    A condition may lead the sentence ("When `x` is provided, the host
    **MUST** ...") or trail it ("**MUST** fire the message when that action is
    triggered"). A leading condition is cut at the comma that closes it; a
    trailing one runs to the end of the sentence.

    Args:
      clause: A classified obligation.

    Returns:
      The condition in the spec's own words, or None when the clause states no
      trigger.

    """
    text = clause.text
    masked = parser.mask_code_spans(text)

    trigger = config.CONDITION_TRIGGER_RE.search(masked)
    if not trigger:
        return None

    start = trigger.start()
    if start < keyword_position(clause):
        end = _subordinate_end(masked, start)
        if end == -1:
            return None
    else:
        end = len(text)

    condition = _clean(text[start:end]).rstrip(".,;: ")
    if not condition or len(condition) > config.CONDITION_MAX_LENGTH:
        return None
    return condition


def _record(clause: Clause, **extra: object) -> dict[str, object]:
    """Build a report entry locating a clause in the source."""
    entry: dict[str, object] = {
        "file": clause.source.file,
        "line": clause.source.line_start,
        "section": clause.source.section,
        "text": clause.text,
    }
    entry.update(extra)
    return entry


def annotate(clause: Clause, report: ExtractionReport, spec_root: Path) -> Clause:
    """Return a copy of `clause` with actor, fields and condition filled in.

    Args:
      clause: A classified obligation.
      report: Diagnostics collector.
      spec_root: Root of the specification checkout, used to read the
        document's own capability declaration.

    Returns:
      A new clause; the input is not modified.

    """
    actor, confidence = extract_actor(clause)

    if actor is None:
        report.actor_unresolved.append(_record(clause))
        after = _mentions_actor_after(
            parser.mask_code_spans(clause.text), keyword_position(clause)
        )
        if after:
            report.actor_after_keyword_only.append(_record(clause, candidate=after))
    elif confidence < config.ACTOR_LOW_CONFIDENCE_THRESHOLD:
        report.actor_low_confidence.append(
            _record(clause, actor=actor, confidence=confidence)
        )

    return dataclasses.replace(
        clause,
        capability=config.resolve_capability(
            clause.source.file, spec_root / clause.source.file
        ),
        actor=actor,
        actor_confidence=confidence,
        referenced_fields=extract_referenced_fields(clause.text),
        condition=extract_condition(clause),
    )


def annotate_all(
    clauses: list[Clause], spec_root: Path, report: ExtractionReport | None = None
) -> tuple[list[Clause], ExtractionReport]:
    """Attach metadata to every obligation.

    Args:
      clauses: Classified obligations.
      spec_root: Root of the specification checkout.
      report: Existing diagnostics collector, or None to create one.

    Returns:
      The annotated clauses, and the diagnostics collected.

    """
    collected = report or ExtractionReport()
    return [annotate(clause, collected, spec_root) for clause in clauses], collected
