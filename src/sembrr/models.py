"""Shared formatter types and validated options."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args

Mode = Literal["sentence", "clause", "phrase", "strict"]
MODES: tuple[Mode, ...] = ("sentence", "clause", "phrase", "strict")

CandidateKind = Literal[
    "sentence",
    "semicolon",
    "finite_coordinate",
    "colon",
    "dash",
    "parenthetical-start",
    "parenthetical-end",
    "comma_clause",
    "subordinate",
    "coordinate",
    "relative",
    "example_phrase",
    "gerund_coordinate",
    "nominal_coordinate",
    "infinitive_phrase",
    "participial_phrase",
    "comma_phrase",
    "word",
]
CANDIDATE_KINDS: frozenset[str] = frozenset(get_args(CandidateKind))


@dataclass(frozen=True)
class BreakCandidate:
    offset: int
    kind: CandidateKind
    confidence: float
    reason: str
    mandatory: bool = False

    def __post_init__(self) -> None:
        if self.kind not in CANDIDATE_KINDS:
            raise ValueError(f"unknown break candidate kind: {self.kind}")


@dataclass(frozen=True)
class BreakOptions:
    mode: Mode = "phrase"
    target_segment_chars: int = 100
    min_clause_chars: int = 24

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"unknown formatting mode: {self.mode}")
        if self.target_segment_chars <= 0:
            raise ValueError("target segment characters must be greater than zero")
        if self.min_clause_chars <= 0:
            raise ValueError("minimum clause characters must be greater than zero")
