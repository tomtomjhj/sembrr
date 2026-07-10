"""Sentence-analysis engine interfaces and spaCy integration."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from .candidates import _dedupe_candidates, _spacy_optional_candidates
from .models import BreakCandidate

BreakAnalysis = tuple[list[BreakCandidate], list[BreakCandidate]]


class BreakEngine(Protocol):
    def break_candidates(
        self,
        text: str,
        *,
        include_clauses: bool,
        include_phrases: bool = False,
    ) -> BreakAnalysis: ...

    def break_candidates_batch(
        self,
        texts: Iterable[str],
        *,
        include_clauses: bool,
        include_phrases: bool = False,
    ) -> list[BreakAnalysis]: ...


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
    ) -> BreakAnalysis:
        if not text:
            return [], []

        self._require_optional_parser(include_clauses, include_phrases)
        return self._break_candidates_from_doc(
            text,
            self._nlp(text),
            include_clauses=include_clauses,
            include_phrases=include_phrases,
        )

    def break_candidates_batch(
        self,
        texts: Iterable[str],
        *,
        include_clauses: bool,
        include_phrases: bool = False,
    ) -> list[BreakAnalysis]:
        text_batch = tuple(texts)
        if not text_batch:
            return []

        self._require_optional_parser(include_clauses, include_phrases)
        docs = self._nlp.pipe(text_batch)
        return [
            self._break_candidates_from_doc(
                text,
                doc,
                include_clauses=include_clauses,
                include_phrases=include_phrases,
            )
            for text, doc in zip(text_batch, docs, strict=True)
        ]

    def _break_candidates_from_doc(
        self,
        text: str,
        doc: Any,
        *,
        include_clauses: bool,
        include_phrases: bool,
    ) -> BreakAnalysis:
        sentence_breaks = self._spacy_sentence_candidates_from_doc(text, doc)
        optional_breaks = _spacy_optional_candidates(
            text,
            doc,
            include_clauses=include_clauses,
            include_phrases=include_phrases,
        )
        return sentence_breaks, optional_breaks

    def _require_optional_parser(self, include_clauses: bool, include_phrases: bool) -> None:
        if (include_clauses or include_phrases) and not self._has_parser:
            raise SentenceEngineError(
                f"optional breaks require a spaCy parser model: {self._model}"
            )

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


CLOSING_SENTENCE_MARKUP = "\"')]}"


def _after_closing_punctuation(text: str, offset: int) -> int:
    while offset < len(text) and text[offset] in CLOSING_SENTENCE_MARKUP:
        offset += 1
    return offset
