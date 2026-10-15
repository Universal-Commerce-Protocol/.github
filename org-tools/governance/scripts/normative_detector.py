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

"""Normative RFC 2119 clause change detector for Markdown documents.

Delegates Markdown parsing, RFC 2119 classification, exclusion rules, and
clause normalization directly to ``requirements_extractor``
(``org-tools/requirements-extractor``) while also flagging unbolded uppercase
RFC 2119 keywords in prose so that any addition, removal, or modification of
normative clauses in Markdown files is escalated to at least Level 3 (Technical
Council) approval.
"""

import dataclasses
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

_EXTRACTOR_SCRIPTS_DIR = str(
    Path(__file__).resolve().parents[2] / "requirements-extractor" / "scripts"
)
if _EXTRACTOR_SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _EXTRACTOR_SCRIPTS_DIR)

from requirements_extractor import (  # noqa: E402
    classifier,
    config,
    identity,
    models,
    parser,
)

_LEVEL_ORDER: dict[str, int] = {
    level.value: idx for idx, level in enumerate(models.Level)
}

_CODE_SPAN_RE = re.compile(r"`[^`]*`")

# Matches a leading field or status label on the opening sentence of a list
# item, e.g. `` `ec_version`: ``, `` `credential` (string, **OPTIONAL**): ``,
# or `` **complete_in_progress**: ``.
_BULLET_LABEL_RE = re.compile(
    r"^\s*("
    r"(?:\*\*`[^`]+`\*\*|`[^`]+`|\*\*[^*:]+\*\*|[A-Za-z0-9_.-]+)"
    r"(?:\s*\([^)]*\))?"
    r")\s*:"
)


@dataclass(frozen=True)
class NormativeClause:
    """A normative RFC 2119 requirement clause extracted from Markdown prose."""

    level: str
    keyword: str
    bolded: bool
    text: str
    compound_parent: str | None = None
    normalized: str = ""
    text_digest: str = ""
    line_start: int = 1
    line_end: int = 1

    @property
    def comparison_key(self) -> tuple[str, str, bool, str | None, str, str]:
        """Tuple identity used to detect any semantic or emphasis change to a normative clause."""
        normalized_parent = (
            identity.normalize(self.compound_parent) if self.compound_parent else None
        )
        normalized_text = self.normalized or identity.normalize(self.text)
        return (
            self.level,
            self.keyword,
            self.bolded,
            normalized_parent,
            normalized_text,
            self.text_digest,
        )


@dataclass(frozen=True)
class NormativeChangeResult:
    """Result of checking a file for normative RFC 2119 clause changes."""

    has_normative_changes: bool
    added_clauses: list[NormativeClause] = field(default_factory=list)
    removed_clauses: list[NormativeClause] = field(default_factory=list)

    @property
    def affected_keywords(self) -> list[str]:
        """Sorted list of distinct RFC 2119 keywords touched by the change."""
        rank_by_keyword: dict[str, int] = {}
        for clause in (*self.added_clauses, *self.removed_clauses):
            rank = _LEVEL_ORDER.get(clause.level, 99)
            if (
                clause.keyword not in rank_by_keyword
                or rank < rank_by_keyword[clause.keyword]
            ):
                rank_by_keyword[clause.keyword] = rank
        return sorted(rank_by_keyword, key=lambda k: (rank_by_keyword[k], k))

    def format_reason(self, target_team_desc: str | None = None) -> str:
        """Human-readable explanation for why L3 approval is required."""
        keywords = self.affected_keywords
        kw_str = f" ({', '.join(f'`{k}`' for k in keywords)})" if keywords else ""
        target_suffix = f" ({target_team_desc})" if target_team_desc else ""
        return (
            f"Normative RFC 2119 clauses{kw_str} were added, removed, or modified "
            f"in this document; requires at least Level 3 Technical Council "
            f"approval{target_suffix}."
        )


def is_markdown_file(file_path: str) -> bool:
    """Return True if the file path points to a Markdown document."""
    return file_path.lower().endswith((".md", ".markdown"))


def _replace_outside_code_spans(text: str, old: str, new: str) -> str:
    """Replace ``old`` with ``new`` everywhere outside inline backtick code spans."""
    pieces: list[str] = []
    last = 0
    for span in _CODE_SPAN_RE.finditer(text):
        pieces.append(text[last : span.start()].replace(old, new))
        pieces.append(span.group(0))
        last = span.end()
    pieces.append(text[last:].replace(old, new))
    return "".join(pieces)


def _with_bullet_label(
    clause: NormativeClause, bullet_label: str | None
) -> NormativeClause:
    """Attach a leading list-item field/status label to ``compound_parent`` and recompute ``text_digest``."""
    if not bullet_label:
        return clause
    parent = (
        f"{clause.compound_parent} | {bullet_label}"
        if clause.compound_parent
        else bullet_label
    )
    normalized = clause.normalized or identity.normalize(clause.text)
    digest = identity.text_digest(parent, normalized)
    return dataclasses.replace(
        clause,
        compound_parent=parent,
        normalized=normalized,
        text_digest=digest,
    )


def _to_normative_clause(
    ob: models.Clause, *, bolded: bool, text_override: str | None = None
) -> NormativeClause:
    """Convert a classified ``requirements_extractor.models.Clause`` to ``NormativeClause``."""
    text = text_override if text_override is not None else ob.text
    level_str = ob.level.value if ob.level else ""
    keyword_str = ob.annotation.value if ob.annotation else level_str
    normalized = identity.normalize(text)
    digest = identity.text_digest(ob.compound_parent, normalized)
    return NormativeClause(
        level=level_str,
        keyword=keyword_str,
        bolded=bolded,
        text=text,
        compound_parent=ob.compound_parent,
        normalized=normalized,
        text_digest=digest,
        line_start=ob.source.line_start,
        line_end=ob.source.line_end,
    )


def _classify_unbolded_candidate(clause: models.Clause) -> list[NormativeClause]:
    """Classify a candidate clause with unbolded uppercase RFC 2119 keywords via ``classifier.classify``."""
    masked = parser.mask_code_spans(clause.text)
    hits = classifier.find_keywords(masked, config.ALL_KEYWORDS)
    unbolded_hits = [hit for hit in hits if not hit.bolded]
    if not unbolded_hits:
        return []

    emphasized_text = clause.text
    for hit in reversed(unbolded_hits):
        emphasized_text = (
            f"{emphasized_text[: hit.start]}**{emphasized_text[hit.start : hit.end]}**"
            f"{emphasized_text[hit.end :]}"
        )

    emphasized_clause = dataclasses.replace(clause, text=emphasized_text)
    classified = classifier.classify(emphasized_clause, models.ExtractionReport())
    if not classified:
        return []

    results: list[NormativeClause] = []
    for ob in classified:
        if not ob.split_from_compound:
            restored_text = clause.text
        else:
            restored_text = ob.text
            for hit in unbolded_hits:
                raw_kw = clause.text[hit.start : hit.end]
                restored_text = _replace_outside_code_spans(
                    restored_text, f"**{raw_kw}**", raw_kw
                )
        results.append(
            _to_normative_clause(ob, bolded=False, text_override=restored_text)
        )
    return results


def _classify_clause(clause: models.Clause) -> list[NormativeClause]:
    """Classify a candidate ``models.Clause`` into zero or more ``NormativeClause`` items."""
    report = models.ExtractionReport()
    obligations = classifier.classify(clause, report)
    if obligations:
        return [_to_normative_clause(ob, bolded=ob.bolded) for ob in obligations]

    if report.candidates_without_emphasis:
        return _classify_unbolded_candidate(clause)

    # If a list item has no RFC 2119 keyword of its own, check whether its
    # colon-terminated stem (compound_parent) is a normative obligation.
    if (
        clause.compound_parent
        and clause.source.block_type is models.BlockType.LIST_ITEM
    ):
        parent_candidate = dataclasses.replace(
            clause,
            text=clause.compound_parent,
            compound_parent=None,
            source=dataclasses.replace(
                clause.source, block_type=models.BlockType.PARAGRAPH
            ),
        )
        parent_clauses = _classify_clause(parent_candidate)
        if parent_clauses:
            parent = parent_clauses[0]
            normalized = identity.normalize(clause.text)
            digest = identity.text_digest(clause.compound_parent, normalized)
            return [
                NormativeClause(
                    level=parent.level,
                    keyword=parent.keyword,
                    bolded=parent.bolded,
                    text=clause.text,
                    compound_parent=clause.compound_parent,
                    normalized=normalized,
                    text_digest=digest,
                    line_start=clause.source.line_start,
                    line_end=clause.source.line_end,
                )
            ]

    return []


def extract_normative_clauses(
    markdown_text: str, file_path: str = "document.md"
) -> list[NormativeClause]:
    """Extract all normative RFC 2119 clauses from a Markdown document."""
    if not markdown_text:
        return []
    candidates = parser.parse_text(markdown_text, file_path)
    clauses: list[NormativeClause] = []
    active_list_span: tuple[int, int] | None = None
    active_bullet_label: str | None = None

    for candidate in candidates:
        bullet_label_for_clause: str | None = None
        if candidate.source.block_type is models.BlockType.LIST_ITEM:
            span = (candidate.source.line_start, candidate.source.line_end)
            if span != active_list_span:
                active_list_span = span
                label_match = _BULLET_LABEL_RE.match(candidate.text)
                active_bullet_label = label_match.group(1) if label_match else None
            else:
                bullet_label_for_clause = active_bullet_label
        else:
            active_list_span = None
            active_bullet_label = None

        for extracted in _classify_clause(candidate):
            clauses.append(_with_bullet_label(extracted, bullet_label_for_clause))
    return clauses


def _compare_clause_lists(
    before_clauses: list[NormativeClause],
    after_clauses: list[NormativeClause],
) -> tuple[list[NormativeClause], list[NormativeClause]]:
    """Return (added_or_modified_after, removed_or_modified_before) clauses."""
    before_counts = Counter(c.comparison_key for c in before_clauses)
    after_counts = Counter(c.comparison_key for c in after_clauses)

    added_diff = after_counts - before_counts
    removed_diff = before_counts - after_counts

    added: list[NormativeClause] = []
    for clause in after_clauses:
        key = clause.comparison_key
        if added_diff[key] > 0:
            added.append(clause)
            added_diff[key] -= 1

    removed: list[NormativeClause] = []
    for clause in before_clauses:
        key = clause.comparison_key
        if removed_diff[key] > 0:
            removed.append(clause)
            removed_diff[key] -= 1

    return added, removed


def _extract_hunks_from_patch(patch: str) -> list[tuple[str, str]]:
    """Parse a unified diff patch into (before_text, after_text) per hunk."""
    if not patch:
        return []

    hunks: list[tuple[str, str]] = []
    before_lines: list[str] = []
    after_lines: list[str] = []
    in_hunk = False

    for line in patch.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.startswith("@@"):
            if in_hunk and (before_lines or after_lines):
                hunks.append(("\n".join(before_lines), "\n".join(after_lines)))
            before_lines = []
            after_lines = []
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if line.startswith("\\ No newline at end of file"):
            continue
        if line.startswith("-") and not line.startswith("---"):
            before_lines.append(line[1:])
        elif line.startswith("+") and not line.startswith("+++"):
            after_lines.append(line[1:])
        elif line.startswith(" "):
            before_lines.append(line[1:])
            after_lines.append(line[1:])
        else:
            before_lines.append(line)
            after_lines.append(line)

    if in_hunk and (before_lines or after_lines):
        hunks.append(("\n".join(before_lines), "\n".join(after_lines)))

    return hunks


def detect_normative_changes(
    file_path: str,
    base_content: str | None = None,
    head_content: str | None = None,
    patch: str | None = None,
) -> NormativeChangeResult:
    """Detect whether a file change adds, removes, or modifies normative clauses.

    Only Markdown files (`*.md`, `*.markdown`) are evaluated. When `base_content`
    or `head_content` is provided, full-document comparison is performed so
    multi-line paragraphs, code fences, colon-list stems, and table headers
    have complete structural context. Falls back to hunk-by-hunk unified diff
    comparison when only `patch` is available.
    """
    if not is_markdown_file(file_path):
        return NormativeChangeResult(has_normative_changes=False)

    if base_content is not None or head_content is not None:
        before_clauses = extract_normative_clauses(base_content or "", file_path)
        after_clauses = extract_normative_clauses(head_content or "", file_path)
        added, removed = _compare_clause_lists(before_clauses, after_clauses)
        return NormativeChangeResult(
            has_normative_changes=bool(added or removed),
            added_clauses=added,
            removed_clauses=removed,
        )

    if patch:
        all_added: list[NormativeClause] = []
        all_removed: list[NormativeClause] = []
        for before_hunk, after_hunk in _extract_hunks_from_patch(patch):
            before_clauses = extract_normative_clauses(before_hunk, file_path)
            after_clauses = extract_normative_clauses(after_hunk, file_path)
            added, removed = _compare_clause_lists(before_clauses, after_clauses)
            all_added.extend(added)
            all_removed.extend(removed)
        return NormativeChangeResult(
            has_normative_changes=bool(all_added or all_removed),
            added_clauses=all_added,
            removed_clauses=all_removed,
        )

    return NormativeChangeResult(has_normative_changes=False)
