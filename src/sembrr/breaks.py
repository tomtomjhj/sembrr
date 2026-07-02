from __future__ import annotations

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
    mode: str = "phrase"
    target_segment_chars: int = 100
    min_clause_chars: int = 24
    model: str = "en_core_web_sm"


@dataclass(frozen=True)
class ClauseMarkerRule:
    words: frozenset[str]
    kind: str
    confidence: float
    reason: str
    dependencies: frozenset[str] = frozenset()
    comma_before: bool = False
    finite_clause_after: bool = False


class SentenceEngineError(RuntimeError):
    """Raised when the configured spaCy runtime cannot support formatting."""


class SentenceEngine:
    """Find sentence and clause boundaries with the requested spaCy model."""

    def __init__(self, model: str = "en_core_web_sm") -> None:
        self._model = model

        try:
            import spacy

            self._nlp: Any = spacy.load(model, exclude=["ner", "lemmatizer"])
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
        include_phrases: bool = False,
    ) -> tuple[list[BreakCandidate], list[BreakCandidate]]:
        if not text:
            return [], []

        if (include_clauses or include_phrases) and not self._has_parser:
            raise SentenceEngineError(
                f"optional breaks require a spaCy parser model: {self._model}"
            )

        doc = self._nlp(text)
        sentence_breaks = self._spacy_sentence_candidates_from_doc(text, doc)
        optional_breaks = _spacy_optional_candidates(
            text,
            doc,
            include_clauses=include_clauses,
            include_phrases=include_phrases,
        )
        return sentence_breaks, optional_breaks

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
OPTIONAL_KIND_PRIORITY = {
    "finite_coordinate": 6,
    "parenthetical-start": 5,
    "parenthetical-end": 5,
    "semicolon": 5,
    "colon": 4,
    "dash": 4,
    "comma_clause": 3,
    "subordinate": 2,
    "coordinate": 2,
    "relative": 1,
    "example_phrase": 0,
    "gerund_coordinate": 0,
    "nominal_coordinate": 0,
    "infinitive_phrase": 0,
    "participial_phrase": 0,
}


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

        if parenthesis_depth > 0:
            continue

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
        if _has_finite_verb(tokens, 0, _token_index_at(tokens, candidate.offset))
        and _has_finite_verb(tokens, _token_index_at(tokens, candidate.offset), len(tokens))
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

    return _dedupe_candidates(candidates, len(text))


def format_prose(text: str, engine: SentenceEngine, options: BreakOptions) -> str:
    sentence_breaks, optional_breaks = engine.break_candidates(
        text,
        include_clauses=options.mode in {"clause", "phrase", "strict"},
        include_phrases=options.mode in {"phrase", "strict"},
    )
    selected = select_breaks(text, sentence_breaks, optional_breaks, options)
    return apply_breaks(text, selected)


def select_breaks(
    text: str,
    mandatory: Iterable[BreakCandidate],
    optional: Iterable[BreakCandidate],
    options: BreakOptions,
    *,
    protected_spans: Iterable[tuple[int, int]] = (),
) -> list[BreakCandidate]:
    selected = sorted(mandatory, key=lambda candidate: candidate.offset)

    if options.mode not in {"clause", "phrase", "strict"}:
        return selected

    optional_candidates = [
        candidate
        for candidate in optional
        if _valid_fragment(text, candidate.offset, 0, len(text), options)
    ]
    selected_offsets = {candidate.offset for candidate in selected}

    while True:
        chosen = _next_optional_break(
            text, selected, optional_candidates, selected_offsets, options
        )
        if chosen is None:
            break

        selected.append(chosen)
        selected_offsets.add(chosen.offset)

    if options.mode == "strict":
        _add_strict_word_breaks(
            text,
            selected,
            options,
            protected_spans=tuple(protected_spans),
        )

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


CLOSING_SENTENCE_MARKUP = "\"')]}"


def _after_closing_punctuation(text: str, offset: int) -> int:
    while offset < len(text) and text[offset] in CLOSING_SENTENCE_MARKUP:
        offset += 1
    return offset


def _next_optional_break(
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
        return sorted(local, key=lambda candidate: _optional_candidate_rank(candidate, target))[0]

    return None


def _optional_candidate_rank(candidate: BreakCandidate, target: int) -> tuple[int, float, int, int]:
    return (
        -OPTIONAL_KIND_PRIORITY.get(candidate.kind, 0),
        -candidate.confidence,
        abs(candidate.offset - target),
        candidate.offset,
    )


def _valid_fragment(text: str, offset: int, start: int, end: int, options: BreakOptions) -> bool:
    left = text[start:offset].strip()
    right = text[offset:end].strip()
    return len(left) >= options.min_clause_chars and len(right) >= options.min_clause_chars


def _add_strict_word_breaks(
    text: str,
    selected: list[BreakCandidate],
    options: BreakOptions,
    *,
    protected_spans: tuple[tuple[int, int], ...] = (),
) -> None:
    while True:
        boundaries = [0] + [candidate.offset for candidate in selected] + [len(text)]
        boundaries = sorted(set(boundaries))

        for start, end in zip(boundaries, boundaries[1:], strict=False):
            if len(text[start:end].strip()) <= options.target_segment_chars:
                continue

            offset = _strict_word_break_offset(
                text,
                start,
                end,
                options,
                protected_spans=protected_spans,
            )
            if offset is None:
                continue

            selected.append(
                BreakCandidate(
                    offset=offset,
                    kind="word",
                    confidence=0.0,
                    reason="strict word boundary",
                )
            )
            break
        else:
            return


def _strict_word_break_offset(
    text: str,
    start: int,
    end: int,
    options: BreakOptions,
    *,
    protected_spans: tuple[tuple[int, int], ...] = (),
) -> int | None:
    fallback: int | None = None
    before_target: int | None = None

    for offset in _word_boundary_offsets(text, start, end, protected_spans):
        if fallback is None:
            fallback = offset
        if len(text[start:offset].strip()) > options.target_segment_chars:
            break
        before_target = offset

    return before_target or fallback


def _word_boundary_offsets(
    text: str,
    start: int,
    end: int,
    protected_spans: tuple[tuple[int, int], ...],
) -> Iterable[int]:
    offset = start + 1
    while offset < end:
        if not text[offset].isspace():
            offset += 1
            continue

        next_offset = offset + 1
        while next_offset < end and text[next_offset].isspace():
            next_offset += 1

        if (
            not text[offset - 1].isspace()
            and next_offset < end
            and not _inside_protected_span(offset, protected_spans)
        ):
            yield offset

        offset = next_offset


def _inside_protected_span(offset: int, protected_spans: tuple[tuple[int, int], ...]) -> bool:
    return any(start < offset < end for start, end in protected_spans)


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
