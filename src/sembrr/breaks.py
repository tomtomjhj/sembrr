"""Public line-breaking API."""

from __future__ import annotations

from .engine import BreakEngine, SentenceEngine, SentenceEngineError
from .layout import apply_breaks, select_breaks
from .models import (
    MODES,
    BreakBoundary,
    BreakOptions,
    Mode,
)

__all__ = [
    "MODES",
    "BreakBoundary",
    "BreakEngine",
    "BreakOptions",
    "Mode",
    "SentenceEngine",
    "SentenceEngineError",
    "apply_breaks",
    "format_prose",
    "select_breaks",
]


def format_prose(text: str, engine: BreakEngine, options: BreakOptions) -> str:
    boundaries = engine.break_boundaries(
        text,
        include_optional=options.mode != "sentence",
    )
    selected = select_breaks(text, boundaries, options)
    return apply_breaks(text, selected)
