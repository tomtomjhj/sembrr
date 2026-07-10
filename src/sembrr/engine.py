"""Sentence-analysis engine interfaces and spaCy integration."""

from __future__ import annotations

from typing import Any, Protocol

from .candidates import _dedupe_candidates, _spacy_optional_candidates
from .models import BreakCandidate


class BreakEngine(Protocol):
    def break_candidates(
        self,
        text: str,
        *,
        include_clauses: bool,
        include_phrases: bool = False,
    ) -> tuple[list[BreakCandidate], list[BreakCandidate]]: ...


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


CLOSING_SENTENCE_MARKUP = "\"')]}"


def _after_closing_punctuation(text: str, offset: int) -> int:
    while offset < len(text) and text[offset] in CLOSING_SENTENCE_MARKUP:
        offset += 1
    return offset
