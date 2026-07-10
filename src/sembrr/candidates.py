"""Discover semantic break candidates from spaCy tokens."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .models import BreakCandidate, CandidateKind


@dataclass(frozen=True)
class ClauseMarkerRule:
    words: frozenset[str]
    kind: CandidateKind
    confidence: float
    reason: str
    dependencies: frozenset[str] = frozenset()
    comma_before: bool = False
    finite_clause_after: bool = False


COORDINATORS = {"and", "but", "or", "so", "yet"}
SUBORDINATORS = {
    "after",
    "although",
    "as",
    "because",
    "before",
    "if",
    "since",
    "though",
    "unless",
    "until",
    "when",
    "whereas",
    "while",
}
RELATIVE_MARKERS = {"that", "which", "who", "whom", "whose"}
DASHES = {"--", "—", "–"}
STANDALONE_FINITE_DEPS = {"ROOT", "advcl", "ccomp", "conj", "parataxis"}
WH_TAGS = {"WDT", "WP", "WP$", "WRB"}
CLAUSE_MARKER_RULES = (
    ClauseMarkerRule(
        words=frozenset(COORDINATORS),
        kind="coordinate",
        confidence=0.78,
        reason="coordinate conjunction",
        dependencies=frozenset({"cc"}),
        comma_before=True,
        finite_clause_after=True,
    ),
    ClauseMarkerRule(
        words=frozenset(SUBORDINATORS),
        kind="subordinate",
        confidence=0.76,
        reason="subordinate marker",
        dependencies=frozenset({"mark", "advmod"}),
    ),
)


def _spacy_optional_candidates(
    text: str,
    doc: Any,
    *,
    include_clauses: bool,
    include_phrases: bool,
) -> list[BreakCandidate]:
    candidates: list[BreakCandidate] = []
    if include_clauses:
        candidates.extend(_spacy_clause_candidates(text, doc))
    if include_phrases:
        candidates.extend(_spacy_phrase_candidates(text, doc))
    return _dedupe_candidates(candidates, len(text))


def _spacy_clause_candidates(text: str, doc: Any) -> list[BreakCandidate]:
    tokens: list[Any] = list(doc)
    parenthesis_pairs = _parenthesis_pairs(tokens)
    parenthesis_depths = _parenthesis_depths(tokens, parenthesis_pairs)
    candidates: list[BreakCandidate] = []

    for index, token in enumerate(tokens):
        token_text = str(token.text)
        lower = str(token.lower_)
        offset = int(token.idx)
        parenthesis_depth = parenthesis_depths[index]

        if token_text == "(" and index in parenthesis_pairs and parenthesis_depth == 0:
            candidates.append(
                BreakCandidate(
                    offset=offset,
                    kind="parenthetical-start",
                    confidence=0.94,
                    reason="spaCy parenthetical start",
                )
            )
            continue

        if token_text == ")" and index in parenthesis_pairs and parenthesis_depth == 1:
            close_offset = _token_end(token)
            if close_offset < len(text) and text[close_offset].isspace():
                candidates.append(
                    BreakCandidate(
                        offset=close_offset,
                        kind="parenthetical-end",
                        confidence=0.94,
                        reason="spaCy parenthetical end",
                    )
                )
            continue

        if token_text == ";":
            candidates.append(
                BreakCandidate(
                    offset=_token_end(token),
                    kind="semicolon",
                    confidence=0.95,
                    reason=f"spaCy punctuation {token_text}",
                )
            )
            continue

        if parenthesis_depth > 0:
            continue

        if token_text == ":":
            candidates.append(
                BreakCandidate(
                    offset=_token_end(token),
                    kind="colon",
                    confidence=0.95,
                    reason=f"spaCy punctuation {token_text}",
                )
            )
            continue

        if token_text in DASHES:
            candidates.append(
                BreakCandidate(
                    offset=_token_end(token),
                    kind="dash",
                    confidence=0.9,
                    reason="spaCy dash interruption",
                )
            )
            continue

        marker = _clause_marker_candidate(tokens, index, text)
        if marker is not None:
            candidates.append(marker)
            continue

        if _is_comma_clause_start(tokens, index, text):
            candidates.append(
                BreakCandidate(
                    offset=offset,
                    kind="comma_clause",
                    confidence=0.8,
                    reason=f"spaCy comma-led finite clause {lower}",
                )
            )
            continue

        if _is_relative_marker(token, text):
            candidates.append(
                BreakCandidate(
                    offset=offset,
                    kind="relative",
                    confidence=0.7,
                    reason=f"spaCy relative marker {lower}",
                )
            )

    return [
        candidate
        for candidate in _dedupe_candidates(candidates, len(text))
        if _valid_clause_candidate(tokens, candidate)
    ]


def _spacy_phrase_candidates(text: str, doc: Any) -> list[BreakCandidate]:
    tokens: list[Any] = list(doc)
    parenthesis_pairs = _parenthesis_pairs(tokens)
    parenthesis_depths = _parenthesis_depths(tokens, parenthesis_pairs)
    candidates: list[BreakCandidate] = []

    for index, token in enumerate(tokens):
        if parenthesis_depths[index] > 0:
            continue

        lower = str(token.lower_)

        if _is_example_phrase_marker(token):
            candidates.append(
                BreakCandidate(
                    offset=int(token.idx),
                    kind="example_phrase",
                    confidence=0.55,
                    reason=f"spaCy example phrase marker {lower}",
                )
            )
            continue

        if _is_gerund_coordinate_marker(tokens, index):
            candidates.append(
                BreakCandidate(
                    offset=int(token.idx),
                    kind="gerund_coordinate",
                    confidence=0.55,
                    reason=f"spaCy gerund coordinate marker {lower}",
                )
            )
            continue

        if _is_finite_coordinate_marker(tokens, index):
            candidates.append(
                BreakCandidate(
                    offset=int(token.idx),
                    kind="finite_coordinate",
                    confidence=0.65,
                    reason=f"spaCy finite coordinate marker {lower}",
                )
            )
            continue

        if _is_nominal_coordinate_marker(tokens, index, text):
            candidates.append(
                BreakCandidate(
                    offset=int(token.idx),
                    kind="nominal_coordinate",
                    confidence=0.5,
                    reason=f"spaCy nominal coordinate marker {lower}",
                )
            )
            continue

        if _is_infinitive_phrase_marker(tokens, index):
            candidates.append(
                BreakCandidate(
                    offset=int(token.idx),
                    kind="infinitive_phrase",
                    confidence=0.45,
                    reason=f"spaCy infinitive phrase marker {lower}",
                )
            )
            continue

        if _is_participial_phrase_marker(token):
            candidates.append(
                BreakCandidate(
                    offset=int(token.idx),
                    kind="participial_phrase",
                    confidence=0.45,
                    reason=f"spaCy participial phrase marker {lower}",
                )
            )
            continue

        if _is_comma_phrase_marker(token, text):
            candidates.append(
                BreakCandidate(
                    offset=_token_end(token),
                    kind="comma_phrase",
                    confidence=0.35,
                    reason="spaCy comma phrase boundary",
                )
            )

    return _dedupe_candidates(candidates, len(text))


def _dedupe_candidates(candidates: Iterable[BreakCandidate], text_len: int) -> list[BreakCandidate]:
    by_offset: dict[int, BreakCandidate] = {}
    for candidate in candidates:
        if candidate.offset <= 0 or candidate.offset >= text_len:
            continue
        current = by_offset.get(candidate.offset)
        if current is None or candidate.confidence > current.confidence:
            by_offset[candidate.offset] = candidate
    return [by_offset[offset] for offset in sorted(by_offset)]


def _token_end(token: Any) -> int:
    return int(token.idx) + len(str(token.text))


def _token_index_at(tokens: list[Any], offset: int) -> int:
    for index, token in enumerate(tokens):
        if int(token.idx) >= offset:
            return index
    return len(tokens)


def _parenthesis_pairs(tokens: list[Any]) -> dict[int, int]:
    stack: list[int] = []
    pairs: dict[int, int] = {}

    for index, token in enumerate(tokens):
        token_text = str(token.text)
        if token_text == "(":
            stack.append(index)
        elif token_text == ")" and stack:
            open_index = stack.pop()
            pairs[open_index] = index
            pairs[index] = open_index

    return pairs


def _parenthesis_depths(tokens: list[Any], parenthesis_pairs: dict[int, int]) -> list[int]:
    depths: list[int] = []
    depth = 0

    for index, token in enumerate(tokens):
        token_text = str(token.text)
        depths.append(depth)
        if token_text == "(" and index in parenthesis_pairs:
            depth += 1
        elif token_text == ")" and index in parenthesis_pairs and depth > 0:
            depth -= 1

    return depths


def _clause_marker_candidate(
    tokens: list[Any],
    index: int,
    text: str,
) -> BreakCandidate | None:
    token = tokens[index]
    lower = str(token.lower_)

    for rule in CLAUSE_MARKER_RULES:
        if _matches_clause_marker_rule(rule, tokens, index, text):
            return BreakCandidate(
                offset=int(token.idx),
                kind=rule.kind,
                confidence=rule.confidence,
                reason=f"spaCy {rule.reason} {lower}",
            )

    return None


def _matches_clause_marker_rule(
    rule: ClauseMarkerRule,
    tokens: list[Any],
    index: int,
    text: str,
) -> bool:
    token = tokens[index]
    if str(token.lower_) not in rule.words:
        return False

    if rule.dependencies and str(token.dep_) not in rule.dependencies:
        return False

    if rule.comma_before and not _has_comma_before(text, int(token.idx)):
        return False

    return not rule.finite_clause_after or _has_following_finite_clause(tokens, index)


def _is_comma_clause_start(tokens: list[Any], index: int, text: str) -> bool:
    token = tokens[index]
    if str(token.pos_) == "PUNCT" or not _has_comma_before(text, int(token.idx)):
        return False

    return _has_following_finite_clause(tokens, index, stop_at_comma=True)


def _is_relative_marker(token: Any, text: str) -> bool:
    if str(token.lower_) not in RELATIVE_MARKERS or not _has_comma_before(text, int(token.idx)):
        return False

    head = getattr(token, "head", None)
    return str(getattr(head, "dep_", "")) == "relcl" or str(token.dep_) in {
        "nsubj",
        "nsubjpass",
        "dobj",
        "pobj",
    }


def _is_example_phrase_marker(token: Any) -> bool:
    return str(token.lower_) in {"like", "including"} and str(token.pos_) == "ADP"


def _is_gerund_coordinate_marker(tokens: list[Any], index: int) -> bool:
    token = tokens[index]
    if str(token.lower_) not in {"and", "or"} or str(token.dep_) != "cc":
        return False

    next_token = _next_non_punctuation_token(tokens, index)
    return (
        next_token is not None and str(next_token.tag_) == "VBG" and str(next_token.dep_) == "conj"
    )


def _is_finite_coordinate_marker(tokens: list[Any], index: int) -> bool:
    token = tokens[index]
    if str(token.lower_) not in {"and", "or"} or str(token.dep_) != "cc":
        return False

    return _has_following_finite_clause(tokens, index)


def _is_nominal_coordinate_marker(tokens: list[Any], index: int, text: str) -> bool:
    token = tokens[index]
    if str(token.lower_) not in {"and", "or"} or str(token.dep_) != "cc":
        return False

    if _has_comma_before(text, int(token.idx)) or _has_following_finite_clause(tokens, index):
        return False

    conjunct = _next_conjunct_token(tokens, index)
    return conjunct is not None and str(conjunct.pos_) in {"ADJ", "NOUN", "PROPN", "PRON"}


def _is_infinitive_phrase_marker(tokens: list[Any], index: int) -> bool:
    token = tokens[index]
    if str(token.tag_) != "TO" or str(token.dep_) != "aux":
        return False

    next_token = _next_non_punctuation_token(tokens, index)
    return next_token is not None and str(next_token.tag_) == "VB"


def _is_participial_phrase_marker(token: Any) -> bool:
    return str(token.tag_) in {"VBG", "VBN"} and str(token.dep_) in {"acl", "advcl", "xcomp"}


def _is_comma_phrase_marker(token: Any, text: str) -> bool:
    offset = _token_end(token)
    return str(token.text) == "," and offset < len(text) and text[offset].isspace()


def _next_conjunct_token(tokens: list[Any], index: int) -> Any | None:
    for token in tokens[index + 1 :]:
        if str(token.text) in {".", "!", "?", ";", ":", ","}:
            return None
        if str(token.dep_) == "conj":
            return token
    return None


def _has_following_finite_clause(
    tokens: list[Any],
    index: int,
    *,
    stop_at_comma: bool = False,
) -> bool:
    verb_index = _next_clause_head_index(tokens, index, stop_at_comma=stop_at_comma)
    if verb_index is None:
        return False

    return _has_nominal_subject(tokens, index, verb_index + 1)


def _next_clause_head_index(
    tokens: list[Any],
    index: int,
    *,
    stop_at_comma: bool,
) -> int | None:
    for offset, token in enumerate(tokens[index + 1 :], start=index + 1):
        token_text = str(token.text)
        if token_text in {".", "!", "?", ";", ":"} or (stop_at_comma and token_text == ","):
            return None
        if _is_standalone_clause_head(tokens[index], token):
            return offset
    return None


def _is_standalone_clause_head(start_token: Any, token: Any) -> bool:
    if not _is_finite_verb(token):
        return False

    dep = str(token.dep_)
    return dep in STANDALONE_FINITE_DEPS or (dep == "relcl" and str(start_token.tag_) in WH_TAGS)


def _has_nominal_subject(tokens: list[Any], start: int, end: int) -> bool:
    return any(str(token.dep_) in {"nsubj", "nsubjpass", "csubj"} for token in tokens[start:end])


def _next_non_punctuation_token(tokens: list[Any], index: int) -> Any | None:
    for token in tokens[index + 1 :]:
        if str(token.pos_) != "PUNCT":
            return token
    return None


def _has_comma_before(text: str, offset: int) -> bool:
    return text[:offset].rstrip().endswith(",")


def _valid_clause_candidate(tokens: list[Any], candidate: BreakCandidate) -> bool:
    if candidate.kind == "semicolon":
        return True

    offset = _token_index_at(tokens, candidate.offset)
    return _has_finite_verb(tokens, 0, offset) and _has_finite_verb(tokens, offset, len(tokens))


def _has_finite_verb(tokens: list[Any], start: int, end: int) -> bool:
    return any(_is_finite_verb(token) for token in tokens[start:end])


def _is_finite_verb(token: Any) -> bool:
    if str(token.pos_) not in {"AUX", "VERB"}:
        return False

    tag = str(token.tag_)
    dep = str(token.dep_)
    return tag not in {"VBG", "VBN"} or dep in {
        "ROOT",
        "advcl",
        "ccomp",
        "conj",
        "relcl",
    }
