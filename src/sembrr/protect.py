"""Hide Markdown inline source spans from prose linebreaking.

The prose engine should see sentence text, not Markdown internals.
This module replaces tree-sitter inline nodes such as code spans, links, images,
autolinks, and HTML tags with placeholders before sentence splitting.
After line breaks are selected, the original source slices are restored
byte-for-byte.
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

INLINE_PARSER = Parser()
INLINE_PARSER.language = Language(tree_sitter_markdown.inline_language())


@dataclass(frozen=True)
class ProtectedText:
    text: str
    atoms: dict[str, str]

    def restore(self, value: str) -> str:
        for placeholder, original in self.atoms.items():
            value = value.replace(placeholder, original)
        return value


@dataclass(frozen=True)
class InlineInspection:
    has_hard_line_break: bool
    has_multiline_protected_span: bool
    protected: ProtectedText


def inspect_inline(text: str) -> InlineInspection:
    tree = _parse_inline(text)
    has_hard_line_break = _has_node_type(tree.root_node, "hard_line_break")
    has_multiline_protected_span = _has_multiline_protected_node(tree.root_node)
    protected = (
        ProtectedText(text=text, atoms={})
        if has_hard_line_break or has_multiline_protected_span
        else _protect_spans(text, _collect_spans_from_tree(text, tree))
    )
    return InlineInspection(
        has_hard_line_break=has_hard_line_break,
        has_multiline_protected_span=has_multiline_protected_span,
        protected=protected,
    )


def protect_inline(text: str) -> ProtectedText:
    return _protect_spans(text, _collect_spans(text))


def _protect_spans(text: str, spans: list[tuple[int, int]]) -> ProtectedText:
    if not spans:
        return ProtectedText(text=text, atoms={})

    pieces: list[str] = []
    atoms: dict[str, str] = {}
    cursor = 0
    placeholder_prefix = _placeholder_prefix(text, len(spans))

    for index, (start, end) in enumerate(spans):
        if start < cursor:
            continue
        placeholder = f"{placeholder_prefix}{index}_"
        pieces.append(text[cursor:start])
        pieces.append(placeholder)
        atoms[placeholder] = text[start:end]
        cursor = end

    pieces.append(text[cursor:])
    return ProtectedText(text="".join(pieces), atoms=atoms)


def has_hard_line_break(text: str) -> bool:
    tree = _parse_inline(text)
    return _has_node_type(tree.root_node, "hard_line_break")


def has_multiline_protected_span(text: str) -> bool:
    tree = _parse_inline(text)
    return _has_multiline_protected_node(tree.root_node)


def _collect_spans(text: str) -> list[tuple[int, int]]:
    tree = _parse_inline(text)
    return _collect_spans_from_tree(text, tree)


def _collect_spans_from_tree(text: str, tree: Tree) -> list[tuple[int, int]]:
    byte_to_char = _byte_to_char_offsets(text)
    spans = _protected_node_spans(tree.root_node, byte_to_char)

    # The inline grammar recognizes autolinks (`<https://...>`) but not bare URLs.
    spans.extend(_bare_url_spans(text))
    return _merge_spans(sorted(spans))


def _parse_inline(text: str) -> Tree:
    return INLINE_PARSER.parse(text.encode())


def _placeholder_prefix(text: str, count: int) -> str:
    nonce = 0
    while True:
        prefix = f"SEMBRRATOM{nonce}_"
        if all(f"{prefix}{index}_" not in text for index in range(count)):
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
