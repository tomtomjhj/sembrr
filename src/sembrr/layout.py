"""Select and apply line breaks from ranked candidates."""

from __future__ import annotations

from bisect import bisect_left
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

from .models import BreakCandidate, BreakOptions


@dataclass(frozen=True)
class RankedBreakpoint:
    candidate: BreakCandidate
    level: int
    require_min_fragment: bool


@dataclass(frozen=True)
class LayoutState:
    breakpoints_by_level: dict[int, list[RankedBreakpoint]]
    offsets_by_level: dict[int, list[int]]
    leading_run: list[int]
    trailing_run: list[int]


OPTIONAL_KIND_PRIORITY = {
    "semicolon": 6,
    "finite_coordinate": 5,
    "colon": 4,
    "dash": 4,
    "parenthetical-start": 4,
    "parenthetical-end": 4,
    "comma_clause": 3,
    "subordinate": 2,
    "coordinate": 2,
    "relative": 1,
    "example_phrase": 0,
    "gerund_coordinate": 0,
    "nominal_coordinate": 0,
    "infinitive_phrase": 0,
    "participial_phrase": 0,
    "comma_phrase": -1,
}
SEMANTIC_PRIORITIES = tuple(
    sorted(
        {priority for kind, priority in OPTIONAL_KIND_PRIORITY.items() if kind != "comma_phrase"},
        reverse=True,
    )
)
SEMANTIC_LEVEL_BY_PRIORITY = {priority: index for index, priority in enumerate(SEMANTIC_PRIORITIES)}
LAYOUT_LEVEL_COMMA_FALLBACK = len(SEMANTIC_PRIORITIES)
LAYOUT_LEVEL_WORD_FALLBACK = LAYOUT_LEVEL_COMMA_FALLBACK + 1


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

    layout = _layout_breaks(
        text,
        optional,
        options,
        protected_spans=tuple(protected_spans),
    )
    _select_layout_breaks(text, selected, _layout_state(text, layout), options)

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


def _layout_breaks(
    text: str,
    candidates: Iterable[BreakCandidate],
    options: BreakOptions,
    *,
    protected_spans: tuple[tuple[int, int], ...],
) -> list[RankedBreakpoint]:
    breakpoints: list[RankedBreakpoint] = []

    for candidate in candidates:
        if candidate.kind == "comma_phrase":
            breakpoints.append(
                RankedBreakpoint(
                    candidate=candidate,
                    level=LAYOUT_LEVEL_COMMA_FALLBACK,
                    require_min_fragment=options.mode != "strict",
                )
            )
            continue

        breakpoints.append(
            RankedBreakpoint(
                candidate=candidate,
                level=_semantic_level(candidate),
                require_min_fragment=True,
            )
        )

    if options.mode == "strict":
        breakpoints.extend(_word_breakpoints(text, protected_spans))

    return breakpoints


def _word_breakpoints(
    text: str,
    protected_spans: tuple[tuple[int, int], ...],
) -> Iterable[RankedBreakpoint]:
    for offset in _word_boundary_offsets(text, 0, len(text), protected_spans):
        yield RankedBreakpoint(
            candidate=BreakCandidate(
                offset=offset,
                kind="word",
                confidence=0.0,
                reason="strict word boundary",
            ),
            level=LAYOUT_LEVEL_WORD_FALLBACK,
            require_min_fragment=False,
        )


def _select_layout_breaks(
    text: str,
    selected: list[BreakCandidate],
    state: LayoutState,
    options: BreakOptions,
) -> None:
    selected_offsets = {candidate.offset for candidate in selected}
    boundaries = [0] + [candidate.offset for candidate in selected] + [len(text)]
    boundaries = sorted(set(boundaries))
    pending = deque((start, end, 0) for start, end in zip(boundaries, boundaries[1:], strict=False))

    while pending:
        start, end, level = pending.popleft()
        if _trimmed_len(state, start, end) <= options.target_segment_chars:
            continue

        if level > LAYOUT_LEVEL_WORD_FALLBACK:
            continue

        chosen = _breakpoint_at_level(start, end, level, state, selected_offsets, options)
        if chosen is None:
            pending.appendleft((start, end, level + 1))
            continue

        selected.append(chosen.candidate)
        selected_offsets.add(chosen.candidate.offset)

        offset = chosen.candidate.offset
        pending.appendleft((offset, end, level))
        pending.appendleft((start, offset, level))


def _layout_state(text: str, breakpoints: list[RankedBreakpoint]) -> LayoutState:
    breakpoints_by_level: dict[int, list[RankedBreakpoint]] = {}
    offsets_by_level: dict[int, list[int]] = {}

    for ranked in sorted(breakpoints, key=lambda ranked: ranked.candidate.offset):
        breakpoints_by_level.setdefault(ranked.level, []).append(ranked)
        offsets_by_level.setdefault(ranked.level, []).append(ranked.candidate.offset)

    return LayoutState(
        breakpoints_by_level=breakpoints_by_level,
        offsets_by_level=offsets_by_level,
        leading_run=_leading_run(text),
        trailing_run=_trailing_run(text),
    )


def _leading_run(text: str) -> list[int]:
    run_lengths: list[int] = []
    count = 0
    for char in text:
        if char.isspace():
            count += 1
        else:
            count = 0
        run_lengths.append(count)
    run_lengths.append(0)
    return run_lengths


def _trailing_run(text: str) -> list[int]:
    run_lengths = [0] * (len(text) + 1)
    count = 0
    for offset in range(len(text) - 1, -1, -1):
        if text[offset].isspace():
            count += 1
        else:
            count = 0
        run_lengths[offset] = count
    return run_lengths


def _semantic_level(candidate: BreakCandidate) -> int:
    priority = OPTIONAL_KIND_PRIORITY.get(candidate.kind, 0)
    return SEMANTIC_LEVEL_BY_PRIORITY[priority]


def _breakpoint_at_level(
    start: int,
    end: int,
    level: int,
    state: LayoutState,
    selected_offsets: set[int],
    options: BreakOptions,
) -> RankedBreakpoint | None:
    breakpoints = state.breakpoints_by_level.get(level)
    offsets = state.offsets_by_level.get(level)
    if not breakpoints or not offsets:
        return None

    first = bisect_left(offsets, start + 1)
    last = bisect_left(offsets, end)
    if first == last:
        return None

    return _best_breakpoint_at_level(
        breakpoints,
        offsets,
        first,
        last,
        start,
        end,
        state,
        selected_offsets,
        options,
    )


def _best_breakpoint_at_level(
    breakpoints: list[RankedBreakpoint],
    offsets: list[int],
    first: int,
    last: int,
    start: int,
    end: int,
    state: LayoutState,
    selected_offsets: set[int],
    options: BreakOptions,
) -> RankedBreakpoint | None:
    valid_first, valid_last = _valid_breakpoint_range(
        breakpoints,
        offsets,
        first,
        last,
        start,
        end,
        state,
        options,
    )
    if valid_first == valid_last:
        return None

    after_target = _first_breakpoint_after_target(
        offsets,
        valid_first,
        valid_last,
        start,
        state,
        options,
    )
    chosen_index = after_target - 1 if after_target > valid_first else valid_first
    chosen = breakpoints[chosen_index]
    if chosen.candidate.offset in selected_offsets:
        return None
    return chosen


def _valid_breakpoint_range(
    breakpoints: list[RankedBreakpoint],
    offsets: list[int],
    first: int,
    last: int,
    start: int,
    end: int,
    state: LayoutState,
    options: BreakOptions,
) -> tuple[int, int]:
    if not breakpoints[first].require_min_fragment:
        return first, last

    min_left = _first_breakpoint_with_min_left(offsets, first, last, start, state, options)
    min_right = _first_breakpoint_without_min_right(offsets, min_left, last, end, state, options)
    return min_left, min_right


def _first_breakpoint_with_min_left(
    offsets: list[int],
    first: int,
    last: int,
    start: int,
    state: LayoutState,
    options: BreakOptions,
) -> int:
    left = first
    right = last

    while left < right:
        middle = (left + right) // 2
        if _trimmed_len(state, start, offsets[middle]) < options.min_clause_chars:
            left = middle + 1
        else:
            right = middle

    return left


def _first_breakpoint_without_min_right(
    offsets: list[int],
    first: int,
    last: int,
    end: int,
    state: LayoutState,
    options: BreakOptions,
) -> int:
    left = first
    right = last

    while left < right:
        middle = (left + right) // 2
        if _trimmed_len(state, offsets[middle], end) >= options.min_clause_chars:
            left = middle + 1
        else:
            right = middle

    return left


def _first_breakpoint_after_target(
    offsets: list[int],
    first: int,
    last: int,
    start: int,
    state: LayoutState,
    options: BreakOptions,
) -> int:
    left = first
    right = last

    while left < right:
        middle = (left + right) // 2
        if _trimmed_len(state, start, offsets[middle]) <= options.target_segment_chars:
            left = middle + 1
        else:
            right = middle

    return left


def _trimmed_len(state: LayoutState, start: int, end: int) -> int:
    leading = min(state.trailing_run[start], end - start)
    trailing = min(state.leading_run[end - 1], end - start - leading)
    return end - start - leading - trailing


def _word_boundary_offsets(
    text: str,
    start: int,
    end: int,
    protected_spans: tuple[tuple[int, int], ...],
) -> Iterable[int]:
    spans = sorted(protected_spans)
    span_index = 0
    offset = start + 1
    while offset < end:
        if not text[offset].isspace():
            offset += 1
            continue

        next_offset = offset + 1
        while next_offset < end and text[next_offset].isspace():
            next_offset += 1

        while span_index < len(spans) and spans[span_index][1] <= offset:
            span_index += 1

        inside_protected_span = (
            span_index < len(spans) and spans[span_index][0] < offset < spans[span_index][1]
        )
        if not text[offset - 1].isspace() and next_offset < end and not inside_protected_span:
            yield offset

        offset = next_offset
