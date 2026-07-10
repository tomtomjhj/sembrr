"""Public line-breaking API."""

from __future__ import annotations

from .engine import BreakEngine, SentenceEngine, SentenceEngineError
from .layout import apply_breaks, select_breaks
from .models import (
    CANDIDATE_KINDS,
    MODES,
    BreakCandidate,
    BreakOptions,
    CandidateKind,
    Mode,
)

__all__ = [
    "CANDIDATE_KINDS",
    "MODES",
    "BreakCandidate",
    "BreakEngine",
    "BreakOptions",
    "CandidateKind",
    "Mode",
    "SentenceEngine",
    "SentenceEngineError",
    "apply_breaks",
    "format_prose",
    "select_breaks",
]


def format_prose(text: str, engine: BreakEngine, options: BreakOptions) -> str:
    sentence_breaks, optional_breaks = engine.break_candidates(
        text,
        include_clauses=options.mode in {"clause", "phrase", "strict"},
        include_phrases=options.mode in {"phrase", "strict"},
    )
    selected = select_breaks(text, sentence_breaks, optional_breaks, options)
    return apply_breaks(text, selected)
