"""Sentence-analysis engine interfaces and spaCy integration."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from .candidates import dedupe_boundaries, spacy_optional_boundaries
from .models import BreakBoundary

BreakAnalysis = list[BreakBoundary]


class BreakEngine(Protocol):
    def break_boundaries(
        self,
        text: str,
        *,
        include_optional: bool,
    ) -> BreakAnalysis: ...

    def break_boundaries_batch(
        self,
        texts: Iterable[str],
        *,
        include_optional: bool,
    ) -> list[BreakAnalysis]: ...


class SentenceEngineError(RuntimeError):
    """Raised when the configured spaCy runtime cannot support formatting."""


class SentenceEngine:
    """Find and score line-break boundaries with the requested spaCy model."""

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

    def break_boundaries(
        self,
        text: str,
        *,
        include_optional: bool,
    ) -> BreakAnalysis:
        if not text:
            return []

        self._require_optional_parser(include_optional)
        return self._break_boundaries_from_doc(
            text,
            self._nlp(text),
            include_optional=include_optional,
        )

    def break_boundaries_batch(
        self,
        texts: Iterable[str],
        *,
        include_optional: bool,
    ) -> list[BreakAnalysis]:
        text_batch = tuple(texts)
        if not text_batch:
            return []

        self._require_optional_parser(include_optional)
        docs = self._nlp.pipe(text_batch)
        return [
            self._break_boundaries_from_doc(
                text,
                doc,
                include_optional=include_optional,
            )
            for text, doc in zip(text_batch, docs, strict=True)
        ]

    def _break_boundaries_from_doc(
        self,
        text: str,
        doc: Any,
        *,
        include_optional: bool,
    ) -> BreakAnalysis:
        boundaries = self._spacy_sentence_boundaries_from_doc(text, doc)
        if include_optional:
            boundaries.extend(spacy_optional_boundaries(text, doc))
        return dedupe_boundaries(boundaries, len(text))

    def _require_optional_parser(self, include_optional: bool) -> None:
        if include_optional and not self._has_parser:
            raise SentenceEngineError(
                f"semantic breaks require a spaCy parser model: {self._model}"
            )

    def _has_sentence_boundaries(self) -> bool:
        return any(self._nlp.has_pipe(name) for name in ("parser", "senter", "sentencizer"))

    def _spacy_sentence_boundaries_from_doc(self, text: str, doc: Any) -> list[BreakBoundary]:
        boundaries: list[BreakBoundary] = []

        for sent in doc.sents:
            offset = sent.end_char
            offset = _after_closing_punctuation(text, offset)
            if offset < len(text) and text[offset].isspace():
                boundaries.append(
                    BreakBoundary(
                        offset=offset,
                        penalty=0,
                        mandatory=True,
                    )
                )

        return boundaries


CLOSING_SENTENCE_MARKUP = "\"')]}"


def _after_closing_punctuation(text: str, offset: int) -> int:
    while offset < len(text) and text[offset] in CLOSING_SENTENCE_MARKUP:
        offset += 1
    return offset
