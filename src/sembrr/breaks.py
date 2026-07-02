from __future__ import annotations

import importlib
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BreakCandidate:
    offset: int
    kind: str
    confidence: float
    reason: str
    mandatory: bool = False


@dataclass(frozen=True)
class BreakOptions:
    mode: str = "clause"
    target_segment_chars: int = 100
    min_clause_chars: int = 24
    model: str = "en_core_web_sm"


class SentenceEngineError(RuntimeError):
    """Raised when the configured spaCy runtime cannot support formatting."""


class SentenceEngine:
    """Find sentence and clause boundaries with the requested spaCy model."""

    def __init__(self, model: str = "en_core_web_sm") -> None:
        self._model = model

        try:
            spacy: Any = importlib.import_module("spacy")
        except ModuleNotFoundError as error:
            raise SentenceEngineError("spaCy is required") from error

        try:
            self._nlp: Any = spacy.load(model, disable=["ner"])
        except OSError as error:
            raise SentenceEngineError(f"spaCy model not found: {model}") from error

        self._has_parser = bool(self._nlp.has_pipe("parser"))
        if not self._has_sentence_boundaries():
            raise SentenceEngineError(f"spaCy model does not provide sentence boundaries: {model}")

    def sentence_candidates(self, text: str) -> list[BreakCandidate]:
        if not text:
            return []

        sentence_breaks, _ = self.break_candidates(text, include_clauses=False)
        return sentence_breaks

    def clause_candidates(self, text: str) -> list[BreakCandidate]:
        if not text:
            return []

        _, clause_breaks = self.break_candidates(text, include_clauses=True)
        return clause_breaks

    def break_candidates(
        self,
        text: str,
        *,
        include_clauses: bool,
    ) -> tuple[list[BreakCandidate], list[BreakCandidate]]:
        if not text:
            return [], []

        if include_clauses and not self._has_parser:
            raise SentenceEngineError(f"clause mode requires a spaCy parser model: {self._model}")

        doc = self._nlp(text)
        sentence_breaks = self._spacy_sentence_candidates_from_doc(text, doc)
        clause_breaks = _spacy_clause_candidates(text, doc) if include_clauses else []
        return sentence_breaks, clause_breaks

    def _has_sentence_boundaries(self) -> bool:
        return any(self._nlp.has_pipe(name) for name in ("parser", "senter", "sentencizer"))

    def _spacy_sentence_candidates_from_doc(self, text: str, doc: Any) -> list[BreakCandidate]:
        candidates: list[BreakCandidate] = []

        for sent in doc.sents:
            offset = sent.end_char
            offset = _after_closing_punctuation(text, offset)
            if offset < len(text):
                candidates.append(
                    BreakCandidate(
                        offset=offset,
                        kind="sentence",
                        confidence=1.0,
                        reason="spaCy sentence boundary",
                        mandatory=True,
                    )
                )

        return _dedupe_candidates(candidates, len(text))


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
CLAUSE_KIND_PRIORITY = {
    "semicolon": 5,
    "colon": 4,
    "dash": 4,
    "subordinate": 2,
    "coordinate": 2,
    "relative": 1,
}


def _spacy_clause_candidates(text: str, doc: Any) -> list[BreakCandidate]:
    tokens: list[Any] = list(doc)
    candidates: list[BreakCandidate] = []

    for token in tokens:
        token_text = str(token.text)
        lower = str(token.lower_)
        offset = int(token.idx)

        if token_text in {";", ":"}:
            candidates.append(
                BreakCandidate(
                    offset=_token_end(token),
                    kind="semicolon" if token_text == ";" else "colon",
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

        if _is_coordinate_marker(token, text):
            candidates.append(
                BreakCandidate(
                    offset=offset,
                    kind="coordinate",
                    confidence=0.78,
                    reason=f"spaCy coordinate conjunction {lower}",
                )
            )
            continue

        if _is_subordinate_marker(token):
            candidates.append(
                BreakCandidate(
                    offset=offset,
                    kind="subordinate",
                    confidence=0.76,
                    reason=f"spaCy subordinate marker {lower}",
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
        if _has_finite_verb(tokens, 0, _token_index_at(tokens, candidate.offset))
        and _has_finite_verb(tokens, _token_index_at(tokens, candidate.offset), len(tokens))
    ]


def format_prose(text: str, engine: SentenceEngine, options: BreakOptions) -> str:
    sentence_breaks, optional_breaks = engine.break_candidates(
        text,
        include_clauses=options.mode == "clause",
    )
    selected = select_breaks(text, sentence_breaks, optional_breaks, options)
    return apply_breaks(text, selected)


def select_breaks(
    text: str,
    mandatory: Iterable[BreakCandidate],
    optional: Iterable[BreakCandidate],
    options: BreakOptions,
) -> list[BreakCandidate]:
    selected = sorted(mandatory, key=lambda candidate: candidate.offset)

    if options.mode != "clause":
        return selected

    optional_candidates = [
        candidate
        for candidate in optional
        if _valid_fragment(text, candidate.offset, 0, len(text), options)
    ]
    selected_offsets = {candidate.offset for candidate in selected}

    while True:
        chosen = _next_clause_break(text, selected, optional_candidates, selected_offsets, options)
        if chosen is None:
            break

        selected.append(chosen)
        selected_offsets.add(chosen.offset)

    return sorted(selected, key=lambda candidate: candidate.offset)


def apply_breaks(text: str, candidates: Iterable[BreakCandidate]) -> str:
    offsets = [candidate.offset for candidate in candidates]
    if not offsets:
        return text.strip()

    pieces: list[str] = []
    start = 0

    for offset in offsets:
        piece = text[start:offset].strip()
        if piece:
            pieces.append(piece)
        start = offset
        while start < len(text) and text[start].isspace():
            start += 1

    tail = text[start:].strip()
    if tail:
        pieces.append(tail)

    return "\n".join(pieces)


def _after_closing_punctuation(text: str, offset: int) -> int:
    while offset < len(text) and text[offset] in "\"')]}":
        offset += 1
    return offset


def _next_clause_break(
    text: str,
    selected: Iterable[BreakCandidate],
    optional_candidates: list[BreakCandidate],
    selected_offsets: set[int],
    options: BreakOptions,
) -> BreakCandidate | None:
    boundaries = [0] + [candidate.offset for candidate in selected] + [len(text)]
    boundaries = sorted(set(boundaries))

    for start, end in zip(boundaries, boundaries[1:], strict=False):
        segment = text[start:end].strip()
        if len(segment) <= options.target_segment_chars:
            continue

        local = [
            candidate
            for candidate in optional_candidates
            if start < candidate.offset < end
            and candidate.offset not in selected_offsets
            and _valid_fragment(text, candidate.offset, start, end, options)
        ]
        if not local:
            continue

        target = start + options.target_segment_chars
        return sorted(local, key=lambda candidate: _clause_candidate_rank(candidate, target))[0]

    return None


def _clause_candidate_rank(candidate: BreakCandidate, target: int) -> tuple[int, float, int, int]:
    return (
        -CLAUSE_KIND_PRIORITY.get(candidate.kind, 0),
        -candidate.confidence,
        abs(candidate.offset - target),
        candidate.offset,
    )


def _valid_fragment(text: str, offset: int, start: int, end: int, options: BreakOptions) -> bool:
    left = text[start:offset].strip()
    right = text[offset:end].strip()
    return len(left) >= options.min_clause_chars and len(right) >= options.min_clause_chars


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


def _is_coordinate_marker(token: Any, text: str) -> bool:
    return (
        str(token.lower_) in COORDINATORS
        and str(token.dep_) == "cc"
        and _has_comma_before(text, int(token.idx))
    )


def _is_subordinate_marker(token: Any) -> bool:
    return str(token.lower_) in SUBORDINATORS and str(token.dep_) in {"mark", "advmod"}


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


def _has_comma_before(text: str, offset: int) -> bool:
    return text[:offset].rstrip().endswith(",")


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
