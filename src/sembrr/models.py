"""Shared formatter types and validated options."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Mode = Literal["sentence", "semantic", "strict"]
MODES: tuple[Mode, ...] = ("sentence", "semantic", "strict")


@dataclass(frozen=True)
class BreakBoundary:
    offset: int
    penalty: float
    mandatory: bool = False


@dataclass(frozen=True)
class BreakOptions:
    mode: Mode = "semantic"
    target_segment_chars: int = 100
    min_segment_chars: int = 24

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"unknown formatting mode: {self.mode}")
        if self.target_segment_chars <= 0:
            raise ValueError("target segment characters must be greater than zero")
        if self.min_segment_chars <= 0:
            raise ValueError("minimum segment characters must be greater than zero")
