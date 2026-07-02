from __future__ import annotations

from dataclasses import dataclass, replace

import tree_sitter_markdown
from tree_sitter import Language, Node, Parser

from .breaks import BreakOptions, SentenceEngine, apply_breaks, select_breaks
from .protect import ProjectedText, inspect_inline

PRESERVED_PREFIX_NODE_TYPES = {"block_quote_marker"}

BLOCK_PARSER = Parser()
BLOCK_PARSER.language = Language(tree_sitter_markdown.language())


def format_markdown(source: str, engine: SentenceEngine, options: BreakOptions) -> str:
    lines = source.splitlines(keepends=True)
    paragraph_plans = _paragraph_plans(source, lines)
    output: list[str] = []
    index = 0

    while index < len(lines):
        plan = paragraph_plans.get(index)
        if plan is None:
            output.append(lines[index])
            index += 1
            continue

        block = "".join(lines[index : plan.end_row])
        prefix_info = PrefixInfo(
            first_prefix=plan.first_prefix,
            next_prefix=plan.next_prefix,
            body_lines=_strip_source_prefixes(block.splitlines(), plan.source_prefixes),
        )
        output.append(format_markdown_block(block, engine, options, prefix_info=prefix_info))
        index = plan.end_row

    return "".join(output)


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
        if row > start_row and prefix
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
            if (
                sibling.type in PRESERVED_PREFIX_NODE_TYPES
                and sibling.start_point.row == paragraph.start_point.row
                and sibling.end_byte <= paragraph.start_byte
            ):
                ranges.append(range(sibling.start_byte, sibling.end_byte))
            sibling = sibling.prev_sibling
        current = parent

    return ranges


def _range_overlaps_preserved(start: int, end: int, preserved: list[range]) -> bool:
    return any(start in item or (end - 1) in item for item in preserved)


def format_text(source: str, engine: SentenceEngine, options: BreakOptions) -> str:
    lines = source.splitlines(keepends=True)
    output: list[str] = []
    index = 0

    while index < len(lines):
        if _is_blank(lines[index]):
            output.append(lines[index])
            index += 1
            continue

        start = index
        while index < len(lines) and not _is_blank(lines[index]):
            index += 1

        block = "".join(lines[start:index])
        output.append(format_markdown_block(block, engine, options))

    return "".join(output)


def format_markdown_block(
    block: str,
    engine: SentenceEngine,
    options: BreakOptions,
    prefix_info: PrefixInfo | None = None,
) -> str:
    if not block.strip():
        return block

    eol = "\r\n" if "\r\n" in block else "\n"
    ends_with_eol = block.endswith(("\n", "\r"))
    raw_lines = block.splitlines()

    if prefix_info is None:
        prefix_info = PrefixInfo("", "", raw_lines)
    body_lines = prefix_info.body_lines
    body_source = "\n".join(body_lines)
    body_inspection = inspect_inline(body_source)
    if body_inspection.has_hard_line_break or body_inspection.has_multiline_protected_span:
        return block

    text = " ".join(line.strip() for line in body_lines if line.strip())
    if not text:
        return block

    projected = body_inspection.projected if text == body_source else inspect_inline(text).projected
    formatted = _format_projected_prose(projected, engine, options)
    formatted_lines = formatted.split("\n")

    with_prefixes: list[str] = []
    for offset, line in enumerate(formatted_lines):
        prefix = prefix_info.first_prefix if offset == 0 else prefix_info.next_prefix
        with_prefixes.append(prefix + line)

    result = eol.join(with_prefixes)
    if ends_with_eol:
        result += eol
    return result


class PrefixInfo:
    def __init__(self, first_prefix: str, next_prefix: str, body_lines: list[str]) -> None:
        self.first_prefix = first_prefix
        self.next_prefix = next_prefix
        self.body_lines = body_lines


def _format_projected_prose(
    projected: ProjectedText,
    engine: SentenceEngine,
    options: BreakOptions,
) -> str:
    sentence_breaks, optional_breaks = engine.break_candidates(
        projected.text,
        include_clauses=options.mode in {"clause", "phrase"},
        include_phrases=options.mode == "phrase",
    )
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
    )
    return apply_breaks(projected.source, selected)


def _strip_source_prefixes(lines: list[str], prefixes: list[str]) -> list[str]:
    return [
        line[len(prefix) :] if line.startswith(prefix) else line
        for line, prefix in zip(lines, prefixes, strict=False)
    ]


def _is_blank(line: str) -> bool:
    return not line.strip()
