"""Select globally optimal line breaks from scored boundaries."""

from __future__ import annotations

from collections.abc import Iterable
from math import inf

from .models import BreakBoundary, BreakOptions

BREAK_COST = 2.0
SYNTAX_COST = 50.0
FILL_COST = 5.0
FINAL_FILL_COST = 10.0
SHORTFALL_COST = 2.0
SEMANTIC_OVERFLOW_COST = 2.0
STRICT_OVERFLOW_COST = 1000.0


def select_breaks(
    text: str,
    boundaries: Iterable[BreakBoundary],
    options: BreakOptions,
) -> list[BreakBoundary]:
    analyzed = sorted(boundaries, key=lambda boundary: boundary.offset)
    mandatory = [boundary for boundary in analyzed if boundary.mandatory]
    if options.mode == "sentence":
        return mandatory

    optional = [boundary for boundary in analyzed if not boundary.mandatory]
    selected = list(mandatory)
    segment_boundaries = [0, *(boundary.offset for boundary in mandatory), len(text)]

    for start, end in zip(segment_boundaries, segment_boundaries[1:], strict=False):
        if _segment_length(text, start, end) <= options.target_segment_chars:
            continue

        local = [boundary for boundary in optional if start < boundary.offset < end]
        selected.extend(_optimal_breaks(text, start, end, local, options))

    return sorted(selected, key=lambda boundary: boundary.offset)


def apply_breaks(text: str, boundaries: Iterable[BreakBoundary]) -> str:
    offsets = [boundary.offset for boundary in boundaries]
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


def _optimal_breaks(
    text: str,
    start: int,
    end: int,
    boundaries: list[BreakBoundary],
    options: BreakOptions,
) -> list[BreakBoundary]:
    points = [
        BreakBoundary(start, penalty=0),
        *boundaries,
        BreakBoundary(end, penalty=0),
    ]
    costs = [inf] * len(points)
    previous: list[int | None] = [None] * len(points)
    costs[0] = 0.0
    content_starts, content_ends = _content_extents(
        text,
        [point.offset for point in points],
    )

    # For each endpoint, keep the cheapest complete path from the segment start:
    # costs[right] = min(costs[left] + segment_cost(left, right)) for left < right.
    for right in range(1, len(points)):
        for left in range(right):
            length = max(0, content_ends[right] - content_starts[left])
            edge_cost = _segment_cost(
                length,
                points[right],
                final=right == len(points) - 1,
                options=options,
            )
            total = costs[left] + edge_cost
            if total < costs[right]:
                costs[right] = total
                previous[right] = left

    selected: list[BreakBoundary] = []
    current = len(points) - 1
    parent = previous[current]
    while parent is not None and parent != 0:
        selected.append(points[parent])
        current = parent
        parent = previous[current]

    return list(reversed(selected))


def _segment_cost(
    length: int,
    boundary: BreakBoundary,
    *,
    final: bool,
    options: BreakOptions,
) -> float:
    overflow = max(0, length - options.target_segment_chars)
    overflow_cost = SEMANTIC_OVERFLOW_COST * overflow * overflow
    if options.mode == "strict":
        overflow_cost *= STRICT_OVERFLOW_COST

    shortfall = max(0, options.min_segment_chars - length)
    short_cost = SHORTFALL_COST * shortfall * shortfall

    fill_ratio = max(0, options.target_segment_chars - length) / options.target_segment_chars
    fill_scale = FINAL_FILL_COST if final else FILL_COST
    fill_cost = fill_scale * fill_ratio * fill_ratio
    if final:
        return overflow_cost + short_cost + fill_cost

    boundary_cost = BREAK_COST + SYNTAX_COST * boundary.penalty
    return overflow_cost + short_cost + fill_cost + boundary_cost


def _segment_length(text: str, start: int, end: int) -> int:
    return len(text[start:end].strip())


def _content_extents(text: str, offsets: list[int]) -> tuple[list[int], list[int]]:
    """Return trim boundaries at each sorted source offset.

    Within the outer offset range, starts[i] is the first non-whitespace
    position at or after offsets[i]. Ends[i] is one past the final
    non-whitespace position before offsets[i].

    For i < j, max(0, ends[j] - starts[i]) equals the length of
    text[offsets[i]:offsets[j]].strip().
    """
    content_starts = [offsets[-1]] * len(offsets)
    next_content = offsets[-1]
    cursor = offsets[-1] - 1

    for index in range(len(offsets) - 1, -1, -1):
        offset = offsets[index]
        while cursor >= offset:
            if not text[cursor].isspace():
                next_content = cursor
            cursor -= 1
        content_starts[index] = next_content

    content_ends = [offsets[0]] * len(offsets)
    previous_content = offsets[0]
    cursor = offsets[0]

    for index, offset in enumerate(offsets):
        while cursor < offset:
            if not text[cursor].isspace():
                previous_content = cursor + 1
            cursor += 1
        content_ends[index] = previous_content

    return content_starts, content_ends
