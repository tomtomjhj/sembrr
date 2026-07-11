"""Project Markdown inline source spans for prose linebreaking.

The prose engine should see sentence text, not Markdown internals.
This module replaces tree-sitter inline nodes such as code spans, links, images,
autolinks, and HTML tags with placeholders before sentence splitting.
It also removes emphasis delimiters from the prose view while preserving a source
offset map for selected line breaks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import tree_sitter_markdown
from tree_sitter import Language, Node, Parser, Tree

PROTECTED_NODE_TYPES = {
    "code_span",
    "collapsed_reference_link",
    "email_autolink",
    "full_reference_link",
    "html_tag",
    "image",
    "inline_link",
    "shortcut_link",
    "uri_autolink",
}
SKIPPED_NODE_TYPES = {"emphasis_delimiter"}

INLINE_PARSER = Parser()
INLINE_PARSER.language = Language(tree_sitter_markdown.inline_language())


@dataclass(frozen=True)
class ProjectedText:
    source: str
    text: str
    source_offsets: tuple[int, ...]
    protected_spans: tuple[tuple[int, int], ...] = ()

    def source_offset(self, offset: int) -> int:
        return self.source_offsets[offset]


@dataclass(frozen=True)
class InlineInspection:
    has_hard_line_break: bool
    has_multiline_protected_span: bool
    projected: ProjectedText


def inspect_inline(text: str) -> InlineInspection:
    tree = _parse_inline(text)
    has_hard_line_break = _has_node_type(tree.root_node, "hard_line_break")
    has_multiline_protected_span = _has_multiline_protected_node(tree.root_node)
    projected = (
        ProjectedText(source=text, text=text, source_offsets=tuple(range(len(text) + 1)))
        if has_hard_line_break or has_multiline_protected_span
        else _project_text_from_tree(text, tree)
    )
    return InlineInspection(
        has_hard_line_break=has_hard_line_break,
        has_multiline_protected_span=has_multiline_protected_span,
        projected=projected,
    )


def project_inline(text: str) -> ProjectedText:
    tree = _parse_inline(text)
    return _project_text_from_tree(text, tree)


def has_hard_line_break(text: str) -> bool:
    tree = _parse_inline(text)
    return _has_node_type(tree.root_node, "hard_line_break")


def has_multiline_protected_span(text: str) -> bool:
    tree = _parse_inline(text)
    return _has_multiline_protected_node(tree.root_node)


def merge_multiline_code_spans(text: str) -> str:
    """Replace each line ending inside an inline code span with one space."""
    tree = _parse_inline(text)
    byte_to_char = _byte_to_char_offsets(text)
    spans = _multiline_code_spans(tree.root_node, byte_to_char)
    parts: list[str] = []
    cursor = 0

    for start, end in spans:
        parts.append(text[cursor:start])
        code_span = text[start:end]
        code_span = code_span.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
        parts.append(code_span)
        cursor = end

    parts.append(text[cursor:])
    return "".join(parts)


def _collect_spans_from_tree(text: str, tree: Tree) -> list[tuple[int, int]]:
    byte_to_char = _byte_to_char_offsets(text)
    spans = _protected_node_spans(tree.root_node, byte_to_char)

    # The inline grammar recognizes autolinks (`<https://...>`) but not bare URLs.
    spans.extend(_bare_url_spans(text))
    return _merge_spans(sorted(spans))


def _parse_inline(text: str) -> Tree:
    return INLINE_PARSER.parse(text.encode())


def _project_text_from_tree(text: str, tree: Tree) -> ProjectedText:
    protected_spans = _collect_spans_from_tree(text, tree)
    skipped_spans = _collect_skipped_spans(text, tree)
    protected_by_start = _span_by_start(protected_spans)
    skipped_by_start = _span_by_start(skipped_spans)
    placeholder_prefix = _placeholder_prefix(text, len(protected_spans))
    pieces: list[str] = []
    source_offsets = [0]
    cursor = 0
    atom_index = 0

    while cursor < len(text):
        protected_end = protected_by_start.get(cursor)
        if protected_end is not None:
            placeholder = f"{placeholder_prefix}{atom_index}X"
            atom_index += 1
            pieces.append(placeholder)
            source_offsets.extend(protected_end for _ in placeholder)
            cursor = protected_end
            continue

        skipped_end = skipped_by_start.get(cursor)
        if skipped_end is not None:
            if pieces:
                source_offsets[-1] = skipped_end
            cursor = skipped_end
            continue

        pieces.append(text[cursor])
        source_offsets.append(cursor + 1)
        cursor += 1

    return ProjectedText(
        source=text,
        text="".join(pieces),
        source_offsets=tuple(source_offsets),
        protected_spans=tuple(protected_spans),
    )


def _collect_skipped_spans(text: str, tree: Tree) -> list[tuple[int, int]]:
    byte_to_char = _byte_to_char_offsets(text)
    return _skipped_node_spans(tree.root_node, byte_to_char)


def _skipped_node_spans(node: Node, byte_to_char: dict[int, int]) -> list[tuple[int, int]]:
    if node.type in SKIPPED_NODE_TYPES:
        start = byte_to_char[node.start_byte]
        end = byte_to_char[node.end_byte]
        return [(start, end)]

    spans: list[tuple[int, int]] = []
    for child in node.children:
        spans.extend(_skipped_node_spans(child, byte_to_char))
    return spans


def _span_by_start(spans: list[tuple[int, int]]) -> dict[int, int]:
    return {start: end for start, end in spans}


def _placeholder_prefix(text: str, count: int) -> str:
    nonce = 0
    while True:
        prefix = f"SEMBRRATOM{nonce}X"
        if all(f"{prefix}{index}X" not in text for index in range(count)):
            return prefix
        nonce += 1


def _protected_node_spans(node: Node, byte_to_char: dict[int, int]) -> list[tuple[int, int]]:
    if node.type in PROTECTED_NODE_TYPES:
        start = byte_to_char[node.start_byte]
        end = byte_to_char[node.end_byte]
        return [(start, end)]

    spans: list[tuple[int, int]] = []
    for child in node.children:
        spans.extend(_protected_node_spans(child, byte_to_char))
    return spans


def _has_node_type(node: Node, node_type: str) -> bool:
    if node.type == node_type:
        return True

    return any(_has_node_type(child, node_type) for child in node.children)


def _has_multiline_protected_node(node: Node) -> bool:
    if node.type in PROTECTED_NODE_TYPES and node.start_point.row != node.end_point.row:
        return True

    return any(_has_multiline_protected_node(child) for child in node.children)


def _multiline_code_spans(node: Node, byte_to_char: dict[int, int]) -> list[tuple[int, int]]:
    if node.type == "code_span" and node.start_point.row != node.end_point.row:
        return [(byte_to_char[node.start_byte], byte_to_char[node.end_byte])]

    spans: list[tuple[int, int]] = []
    for child in node.children:
        spans.extend(_multiline_code_spans(child, byte_to_char))
    return spans


def _byte_to_char_offsets(text: str) -> dict[int, int]:
    offsets: dict[int, int] = {}
    byte_offset = 0

    for char_offset, char in enumerate(text):
        offsets[byte_offset] = char_offset
        byte_offset += len(char.encode())

    offsets[byte_offset] = len(text)
    return offsets


def _bare_url_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for match in re.finditer(r"https?://[^\s<>)]+", text):
        start, end = match.span()
        while end > start and text[end - 1] in ".?!;:":
            end -= 1
        spans.append((start, end))
    return spans


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []

    for start, end in spans:
        if not merged or start >= merged[-1][1]:
            merged.append((start, end))
        else:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))

    return merged
