from __future__ import annotations

from dataclasses import dataclass, replace

import tree_sitter_markdown
from tree_sitter import Language, Node, Parser

from .engine import BreakAnalysis, BreakEngine
from .layout import apply_breaks, select_breaks
from .models import BreakOptions
from .protect import ProjectedText, inspect_inline

PRESERVED_PREFIX_NODE_TYPES = {"block_continuation", "block_quote_marker"}

BLOCK_PARSER = Parser()
BLOCK_PARSER.language = Language(tree_sitter_markdown.language())


def format_markdown(source: str, engine: BreakEngine, options: BreakOptions) -> str:
    lines = source.splitlines(keepends=True)
    paragraph_plans = _paragraph_plans(source, lines)
    parts: list[str | PreparedBlock] = []
    index = 0

    while index < len(lines):
        plan = paragraph_plans.get(index)
        if plan is None:
            parts.append(lines[index])
            index += 1
            continue

        block = "".join(lines[index : plan.end_row])
        prefix_info = PrefixInfo(
            first_prefix=plan.first_prefix,
            next_prefix=plan.next_prefix,
            body_lines=_strip_source_prefixes(block.splitlines(), plan.source_prefixes),
        )
        prepared = _prepare_block(block, prefix_info=prefix_info, markdown=True)
        parts.append(block if prepared is None else prepared)
        index = plan.end_row

    return _format_parts(parts, engine, options)


@dataclass(frozen=True)
class ParagraphPlan:
    start_row: int
    end_row: int
    source_prefixes: list[str]
    first_prefix: str
    next_prefix: str


def _paragraph_plans(source: str, lines: list[str]) -> dict[int, ParagraphPlan]:
    source_bytes = source.encode()
    line_start_bytes = _line_start_bytes(lines)
    tree = BLOCK_PARSER.parse(source_bytes)
    plans: dict[int, ParagraphPlan] = {}
    _collect_paragraph_plans(tree.root_node, source_bytes, line_start_bytes, plans)
    return plans


def _collect_paragraph_plans(
    node: Node,
    source_bytes: bytes,
    line_start_bytes: list[int],
    plans: dict[int, ParagraphPlan],
) -> None:
    if node.type == "paragraph":
        plan = _paragraph_plan(node, source_bytes, line_start_bytes)
        plans[plan.start_row] = plan
        return

    for child in node.children:
        _collect_paragraph_plans(child, source_bytes, line_start_bytes, plans)


def _paragraph_plan(
    paragraph: Node,
    source_bytes: bytes,
    line_start_bytes: list[int],
) -> ParagraphPlan:
    start_row = paragraph.start_point.row
    end_row = _paragraph_end_row_exclusive(paragraph)
    continuation_prefixes = _continuation_prefixes(paragraph, source_bytes)

    source_prefixes: list[str] = []
    for row in range(start_row, end_row):
        if row == start_row:
            source_prefixes.append(
                source_bytes[line_start_bytes[row] : paragraph.start_byte].decode()
            )
        else:
            source_prefixes.append(continuation_prefixes.get(row, ""))

    first_prefix = source_prefixes[0]
    existing_continuations = [
        prefix
        for row, prefix in sorted(continuation_prefixes.items())
        if start_row < row < end_row and prefix
    ]
    next_prefix = (
        existing_continuations[0]
        if existing_continuations
        else _synthesize_next_prefix(paragraph, source_bytes, line_start_bytes[start_row])
    )

    return ParagraphPlan(
        start_row=start_row,
        end_row=end_row,
        source_prefixes=source_prefixes,
        first_prefix=first_prefix,
        next_prefix=next_prefix,
    )


def _end_row_exclusive(node: Node) -> int:
    return node.end_point.row + (1 if node.end_point.column > 0 else 0)


def _paragraph_end_row_exclusive(paragraph: Node) -> int:
    content_children = [child for child in paragraph.children if child.type != "block_continuation"]
    if not content_children:
        return _end_row_exclusive(paragraph)

    return _end_row_exclusive(content_children[-1])


def _line_start_bytes(lines: list[str]) -> list[int]:
    starts: list[int] = []
    offset = 0
    for line in lines:
        starts.append(offset)
        offset += len(line.encode())
    return starts


def _continuation_prefixes(paragraph: Node, source_bytes: bytes) -> dict[int, str]:
    prefixes: dict[int, str] = {}
    _collect_continuation_prefixes(paragraph, source_bytes, prefixes)
    return prefixes


def _collect_continuation_prefixes(
    node: Node,
    source_bytes: bytes,
    prefixes: dict[int, str],
) -> None:
    if node.type == "block_continuation":
        prefixes[node.start_point.row] = source_bytes[node.start_byte : node.end_byte].decode()
        return

    for child in node.children:
        _collect_continuation_prefixes(child, source_bytes, prefixes)


def _synthesize_next_prefix(
    paragraph: Node,
    source_bytes: bytes,
    line_start_byte: int,
) -> str:
    prefix_bytes = source_bytes[line_start_byte : paragraph.start_byte]
    if not prefix_bytes:
        return ""

    preserved = _preserved_prefix_ranges(paragraph, line_start_byte)
    chars: list[str] = []
    byte_offset = line_start_byte

    for char in prefix_bytes.decode():
        next_offset = byte_offset + len(char.encode())
        if char.isspace() or _range_overlaps_preserved(byte_offset, next_offset, preserved):
            chars.append(char)
        else:
            chars.append(" ")
        byte_offset = next_offset

    return "".join(chars)


def _preserved_prefix_ranges(paragraph: Node, line_start_byte: int) -> list[range]:
    ranges: list[range] = []
    current = paragraph

    while True:
        parent = current.parent
        if parent is None:
            break

        sibling = current.prev_sibling
        while sibling is not None and sibling.end_byte > line_start_byte:
            _collect_preserved_prefix_ranges(
                sibling,
                paragraph.start_point.row,
                line_start_byte,
                paragraph.start_byte,
                ranges,
            )
            sibling = sibling.prev_sibling
        current = parent

    return ranges


def _collect_preserved_prefix_ranges(
    node: Node,
    row: int,
    start_byte: int,
    end_byte: int,
    ranges: list[range],
) -> None:
    if node.end_byte <= start_byte or node.start_byte >= end_byte:
        return

    if node.type in PRESERVED_PREFIX_NODE_TYPES and node.start_point.row == row:
        ranges.append(range(max(node.start_byte, start_byte), min(node.end_byte, end_byte)))
        return

    for child in node.children:
        _collect_preserved_prefix_ranges(child, row, start_byte, end_byte, ranges)


def _range_overlaps_preserved(start: int, end: int, preserved: list[range]) -> bool:
    return any(start in item or (end - 1) in item for item in preserved)


def format_text(source: str, engine: BreakEngine, options: BreakOptions) -> str:
    lines = source.splitlines(keepends=True)
    parts: list[str | PreparedBlock] = []
    index = 0

    while index < len(lines):
        if _is_blank(lines[index]):
            parts.append(lines[index])
            index += 1
            continue

        start = index
        while index < len(lines) and not _is_blank(lines[index]):
            index += 1

        block = "".join(lines[start:index])
        prepared = _prepare_block(block, markdown=False)
        parts.append(block if prepared is None else prepared)

    return _format_parts(parts, engine, options)


def format_markdown_block(
    block: str,
    engine: BreakEngine,
    options: BreakOptions,
    prefix_info: PrefixInfo | None = None,
) -> str:
    prepared = _prepare_block(block, prefix_info=prefix_info, markdown=True)
    if prepared is None:
        return block
    return _format_parts([prepared], engine, options)


def _prepare_block(
    block: str,
    *,
    prefix_info: PrefixInfo | None = None,
    markdown: bool,
) -> PreparedBlock | None:
    if not block.strip():
        return None

    eol = "\r\n" if "\r\n" in block else "\n"
    ends_with_eol = block.endswith(("\n", "\r"))
    raw_lines = block.splitlines()

    if prefix_info is None:
        prefix_info = PrefixInfo("", "", raw_lines)
    body_lines = prefix_info.body_lines
    body_source = "\n".join(body_lines)

    body_inspection = inspect_inline(body_source) if markdown else None
    if body_inspection is not None and (
        body_inspection.has_hard_line_break or body_inspection.has_multiline_protected_span
    ):
        return None

    text = " ".join(line.strip() for line in body_lines if line.strip())
    if not text:
        return None

    if body_inspection is None:
        projected = ProjectedText(
            source=text,
            text=text,
            source_offsets=tuple(range(len(text) + 1)),
        )
    else:
        projected = (
            body_inspection.projected if text == body_source else inspect_inline(text).projected
        )

    return PreparedBlock(
        projected=projected,
        prefix_info=prefix_info,
        eol=eol,
        ends_with_eol=ends_with_eol,
    )


def _format_parts(
    parts: list[str | PreparedBlock],
    engine: BreakEngine,
    options: BreakOptions,
) -> str:
    analyses = iter(
        engine.break_candidates_batch(
            (part.projected.text for part in parts if isinstance(part, PreparedBlock)),
            include_clauses=options.mode in {"clause", "phrase", "strict"},
            include_phrases=options.mode in {"phrase", "strict"},
        )
    )

    output: list[str] = []
    for part in parts:
        if isinstance(part, str):
            output.append(part)
            continue

        output.append(_format_prepared_block(part, next(analyses), options))

    return "".join(output)


def _format_prepared_block(
    prepared: PreparedBlock,
    analysis: BreakAnalysis,
    options: BreakOptions,
) -> str:
    formatted = _format_projected_prose(prepared.projected, analysis, options)
    formatted_lines = formatted.split("\n")

    with_prefixes: list[str] = []
    for offset, line in enumerate(formatted_lines):
        prefix = (
            prepared.prefix_info.first_prefix if offset == 0 else prepared.prefix_info.next_prefix
        )
        with_prefixes.append(prefix + line)

    result = prepared.eol.join(with_prefixes)
    if prepared.ends_with_eol:
        result += prepared.eol
    return result


@dataclass(frozen=True)
class PrefixInfo:
    first_prefix: str
    next_prefix: str
    body_lines: list[str]


@dataclass(frozen=True)
class PreparedBlock:
    projected: ProjectedText
    prefix_info: PrefixInfo
    eol: str
    ends_with_eol: bool


def _format_projected_prose(
    projected: ProjectedText,
    analysis: BreakAnalysis,
    options: BreakOptions,
) -> str:
    sentence_breaks, optional_breaks = analysis
    source_sentence_breaks = [
        replace(candidate, offset=projected.source_offset(candidate.offset))
        for candidate in sentence_breaks
    ]
    source_optional_breaks = [
        replace(candidate, offset=projected.source_offset(candidate.offset))
        for candidate in optional_breaks
    ]
    selected = select_breaks(
        projected.source,
        source_sentence_breaks,
        source_optional_breaks,
        options,
        protected_spans=projected.protected_spans,
    )
    return apply_breaks(projected.source, selected)


def _strip_source_prefixes(lines: list[str], prefixes: list[str]) -> list[str]:
    return [
        line[len(prefix) :] if line.startswith(prefix) else line
        for line, prefix in zip(lines, prefixes, strict=False)
    ]


def _is_blank(line: str) -> bool:
    return not line.strip()
