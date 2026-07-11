"""Score safe line-break boundaries from a dependency tree."""

from __future__ import annotations

from itertools import pairwise
from typing import Any

from .models import BreakBoundary

PHRASE_PREFIX_POS = {"ADP", "AUX", "CCONJ", "DET", "PART", "SCONJ"}
PHRASE_PREFIX_PENALTY = 1.0


def spacy_optional_boundaries(text: str, doc: Any) -> list[BreakBoundary]:
    boundaries: list[BreakBoundary] = []

    for sentence in doc.sents:
        tokens = list(sentence)
        for left, right in pairwise(tokens):
            offset = _token_end(left)
            next_offset = int(right.idx)
            if offset >= next_offset or not text[offset:next_offset].isspace():
                continue

            boundaries.append(
                BreakBoundary(
                    offset=offset,
                    penalty=_boundary_penalty(tokens, left),
                )
            )

    return boundaries


def dedupe_boundaries(
    boundaries: list[BreakBoundary],
    text_length: int,
) -> list[BreakBoundary]:
    by_offset: dict[int, BreakBoundary] = {}
    for boundary in boundaries:
        if boundary.offset <= 0 or boundary.offset >= text_length:
            continue

        current = by_offset.get(boundary.offset)
        if (
            current is None
            or boundary.mandatory
            or (not current.mandatory and boundary.penalty < current.penalty)
        ):
            by_offset[boundary.offset] = boundary

    return [by_offset[offset] for offset in sorted(by_offset)]


def _boundary_penalty(tokens: list[Any], left: Any) -> float:
    offset = int(left.i)
    cut_penalty = sum(
        1.0 / (abs(int(token.i) - int(token.head.i)) ** 2)
        for token in tokens
        if int(token.head.i) != int(token.i)
        and min(int(token.i), int(token.head.i)) <= offset < max(int(token.i), int(token.head.i))
    )
    prefix_penalty = PHRASE_PREFIX_PENALTY if str(left.pos_) in PHRASE_PREFIX_POS else 0.0
    return cut_penalty + prefix_penalty


def _token_end(token: Any) -> int:
    return int(token.idx) + len(str(token.text))
