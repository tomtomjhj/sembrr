from __future__ import annotations

import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from sembrr.breaks import (
    BreakCandidate,
    BreakOptions,
    SentenceEngine,
    SentenceEngineError,
    _spacy_clause_candidates,
    format_prose,
)
from sembrr.cli import main
from sembrr.markdown import format_markdown, format_text


class FixtureEngine:
    def break_candidates(
        self,
        text: str,
        *,
        include_clauses: bool,
    ) -> tuple[list[BreakCandidate], list[BreakCandidate]]:
        sentence_breaks = self.sentence_candidates(text)
        clause_breaks = self.clause_candidates(text) if include_clauses else []
        return sentence_breaks, clause_breaks

    def sentence_candidates(self, text: str) -> list[BreakCandidate]:
        candidates: list[BreakCandidate] = []
        index = 0

        while index < len(text):
            if text[index] not in ".!?":
                index += 1
                continue

            offset = _after_closing_punctuation(text, index + 1)
            if offset < len(text) and text[offset].isspace():
                candidates.append(
                    BreakCandidate(
                        offset=offset,
                        kind="sentence",
                        confidence=1.0,
                        reason="fixture sentence boundary",
                        mandatory=True,
                    )
                )

            index = offset + 1

        return candidates

    def clause_candidates(self, text: str) -> list[BreakCandidate]:
        candidates: list[BreakCandidate] = []

        semicolon = text.find(";")
        if semicolon >= 0:
            candidates.append(
                BreakCandidate(
                    offset=semicolon + 1,
                    kind="semicolon",
                    confidence=0.95,
                    reason="fixture semicolon boundary",
                )
            )

        comma_and = text.find(", and ")
        if comma_and >= 0:
            candidates.append(
                BreakCandidate(
                    offset=comma_and + 2,
                    kind="coordinate",
                    confidence=0.78,
                    reason="fixture coordinate boundary",
                )
            )

        return candidates


ENGINE = FixtureEngine()


class FakeToken:
    def __init__(
        self,
        text: str,
        idx: int,
        pos: str = "NOUN",
        dep: str = "",
        tag: str = "NN",
    ) -> None:
        self.text = text
        self.idx = idx
        self.pos_ = pos
        self.dep_ = dep
        self.tag_ = tag
        self.lower_ = text.lower()
        self.head = self


class SembrrTests(unittest.TestCase):
    def test_sentence_engine_requires_requested_model(self) -> None:
        with self.assertRaisesRegex(SentenceEngineError, "spaCy model not found"):
            SentenceEngine(model="__missing_model__")

    def test_formats_stdin_style_markdown_paragraph(self) -> None:
        source = "One sentence. Another sentence.\n"
        self.assertEqual(
            format_markdown(source, ENGINE, BreakOptions()),
            "One sentence.\nAnother sentence.\n",
        )

    def test_cli_reads_stdin_and_writes_stdout(self) -> None:
        output = StringIO()

        with (
            patch("sembrr.cli.SentenceEngine", return_value=ENGINE),
            patch("sys.stdin", StringIO("One sentence. Another sentence.\n")),
            redirect_stdout(output),
        ):
            exit_code = main([])

        self.assertEqual(exit_code, 0)
        self.assertEqual(output.getvalue(), "One sentence.\nAnother sentence.\n")

    def test_preserves_inline_code_and_link_source(self) -> None:
        source = "Use [`foo.bar()`](./api.md#foo.bar). Then use `src/a.b.py`.\n"
        self.assertEqual(
            format_markdown(source, ENGINE, BreakOptions()),
            "Use [`foo.bar()`](./api.md#foo.bar).\nThen use `src/a.b.py`.\n",
        )

    def test_preserves_emphasis_at_sentence_start(self) -> None:
        source = (
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod "
            "tempor incididunt ut labore et dolore magna aliqua.\n"
            "*Ut enim ad minim veniam*, quis nostrud exercitation ullamco laboris "
            "nisi ut aliquip ex ea commodo consequat.\n"
        )
        expected = (
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod "
            "tempor incididunt ut labore et dolore magna aliqua.\n"
            "*Ut enim ad minim veniam*, quis nostrud exercitation ullamco laboris "
            "nisi ut aliquip ex ea commodo consequat.\n"
        )
        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_preserves_collapsed_reference_link_source(self) -> None:
        source = "Use [v1.2][]. Then continue.\n"
        expected = "Use [v1.2][].\nThen continue.\n"
        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_preserves_code_fence_byte_for_byte(self) -> None:
        source = "Before. After.\n\n```py\na.b()\n```\n\nNext. Last.\n"
        expected = "Before.\nAfter.\n\n```py\na.b()\n```\n\nNext.\nLast.\n"
        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_preserves_tables(self) -> None:
        source = "| A | B |\n| - | - |\n| One. Two. | x |\n\nAfter. Next.\n"
        expected = "| A | B |\n| - | - |\n| One. Two. | x |\n\nAfter.\nNext.\n"
        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_preserves_front_matter_heading_and_link_reference(self) -> None:
        source = (
            "---\ntitle: One. Two.\n---\n\n"
            "# Heading. Still heading.\n\n"
            "[ref]: ./a.b\n\nAfter. Next.\n"
        )
        expected = (
            "---\ntitle: One. Two.\n---\n\n# Heading. Still heading.\n\n"
            "[ref]: ./a.b\n\nAfter.\nNext.\n"
        )
        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_formats_list_item_with_continuation_indent(self) -> None:
        source = "- One sentence. Another sentence.\n"
        expected = "- One sentence.\n  Another sentence.\n"
        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_formats_task_list_item_with_marker_preserved(self) -> None:
        source = "- [ ] One sentence. Another sentence.\n"
        expected = "- [ ] One sentence.\n      Another sentence.\n"
        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_formats_nested_prefixes_from_tree_sitter_ranges(self) -> None:
        source = "> - One. Two.\n>   More.\n\n  - Nested. Item.\n    More.\n\n> > Quote. More.\n"
        expected = (
            "> - One.\n"
            ">   Two.\n"
            ">   More.\n\n"
            "  - Nested.\n"
            "    Item.\n"
            "    More.\n\n"
            "> > Quote.\n"
            "> > More.\n"
        )
        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_formats_nested_list_without_absorbing_child_item(self) -> None:
        source = (
            "* Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod "
            "tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, "
            "quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. \n"
            "    * Duis aute irure dolor in reprehenderit in voluptate velit esse cillum "
            "dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, "
            "sunt in culpa qui officia deserunt mollit anim id est laborum.\n"
        )
        expected = (
            "* Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod "
            "tempor incididunt ut labore et dolore magna aliqua.\n"
            "  Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi "
            "ut aliquip ex ea commodo consequat.\n"
            "    * Duis aute irure dolor in reprehenderit in voluptate velit esse cillum "
            "dolore eu fugiat nulla pariatur.\n"
            "      Excepteur sint occaecat cupidatat non proident, sunt in culpa qui "
            "officia deserunt mollit anim id est laborum.\n"
        )
        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_formats_list_item_before_following_paragraph(self) -> None:
        source = (
            "* Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod "
            "tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, "
            "quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.\n"
            "\n"
            "Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt "
            "mollit anim id est laborum.\n"
        )
        expected = (
            "* Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod "
            "tempor incididunt ut labore et dolore magna aliqua.\n"
            "  Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi "
            "ut aliquip ex ea commodo consequat.\n"
            "\n"
            "Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt "
            "mollit anim id est laborum.\n"
        )
        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_formats_blockquote(self) -> None:
        source = "> One sentence. Another sentence.\n"
        expected = "> One sentence.\n> Another sentence.\n"
        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_preserves_hard_breaks(self) -> None:
        source = "One sentence.  \nAnother sentence.\n"
        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), source)

    def test_preserves_backslash_hard_breaks(self) -> None:
        source = "One sentence.\\\nAnother sentence.\n"
        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), source)

    def test_preserves_multiline_inline_code_span(self) -> None:
        source = "`x\ny`. Next sentence.\n"
        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), source)

    def test_text_mode(self) -> None:
        source = "One sentence. Another sentence.\n\nLast sentence. Done.\n"
        expected = "One sentence.\nAnother sentence.\n\nLast sentence.\nDone.\n"
        self.assertEqual(format_text(source, ENGINE, BreakOptions()), expected)

    def test_clause_mode_selects_optional_breaks(self) -> None:
        source = (
            "The formatter keeps Markdown intact; it breaks long prose at semantic boundaries, "
            "and it avoids changing code spans when those spans appear inline."
        )
        expected = (
            "The formatter keeps Markdown intact;\n"
            "it breaks long prose at semantic boundaries,\n"
            "and it avoids changing code spans when those spans appear inline."
        )
        options = BreakOptions(mode="clause", target_segment_chars=60, min_clause_chars=20)

        self.assertEqual(format_prose(source, ENGINE, options), expected)

    def test_clause_mode_discovers_spacy_subordinate_boundary(self) -> None:
        source = (
            "The writer keeps context visible "
            "because the formatter uses dependency labels carefully."
        )
        tokens = _fake_doc(
            source,
            [
                ("The", "DET", "det", "DT"),
                ("writer", "NOUN", "nsubj", "NN"),
                ("keeps", "VERB", "ROOT", "VBZ"),
                ("context", "NOUN", "dobj", "NN"),
                ("visible", "ADJ", "acomp", "JJ"),
                ("because", "SCONJ", "mark", "IN"),
                ("the", "DET", "det", "DT"),
                ("formatter", "NOUN", "nsubj", "NN"),
                ("uses", "VERB", "advcl", "VBZ"),
                ("dependency", "NOUN", "compound", "NN"),
                ("labels", "NOUN", "dobj", "NNS"),
                ("carefully", "ADV", "advmod", "RB"),
                (".", "PUNCT", "punct", "."),
            ],
        )

        candidates = _spacy_clause_candidates(source, tokens)
        self.assertIn(("subordinate", source.index("because")), _candidate_summary(candidates))

    def test_clause_mode_discovers_spacy_coordinate_boundary(self) -> None:
        source = (
            "The writer keeps context visible, and the formatter uses dependency labels carefully."
        )
        tokens = _fake_doc(
            source,
            [
                ("The", "DET", "det", "DT"),
                ("writer", "NOUN", "nsubj", "NN"),
                ("keeps", "VERB", "ROOT", "VBZ"),
                ("context", "NOUN", "dobj", "NN"),
                ("visible", "ADJ", "acomp", "JJ"),
                (",", "PUNCT", "punct", ","),
                ("and", "CCONJ", "cc", "CC"),
                ("the", "DET", "det", "DT"),
                ("formatter", "NOUN", "nsubj", "NN"),
                ("uses", "VERB", "conj", "VBZ"),
                ("dependency", "NOUN", "compound", "NN"),
                ("labels", "NOUN", "dobj", "NNS"),
                ("carefully", "ADV", "advmod", "RB"),
                (".", "PUNCT", "punct", "."),
            ],
        )

        candidates = _spacy_clause_candidates(source, tokens)
        self.assertIn(("coordinate", source.index("and")), _candidate_summary(candidates))

    def test_preserves_tree_sitter_inline_spans(self) -> None:
        source = "Use `경로/a.b.py`. Visit <https://x.y/z>. Then see http://x.y/z.\n"
        expected = "Use `경로/a.b.py`.\nVisit <https://x.y/z>.\nThen see http://x.y/z.\n"
        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_bare_url_does_not_swallow_sentence_punctuation(self) -> None:
        source = "See http://x.y/z. Next sentence.\n"
        expected = "See http://x.y/z.\nNext sentence.\n"
        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_placeholder_text_in_source_is_not_replaced(self) -> None:
        source = "Keep SEMBRRATOM0_0_ literal. Then use `src/a.b.py`.\n"
        expected = "Keep SEMBRRATOM0_0_ literal.\nThen use `src/a.b.py`.\n"
        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_idempotent(self) -> None:
        source = "- One sentence. Another sentence.\n\nUse `src/a.b.py`. Next sentence.\n"
        first = format_markdown(source, ENGINE, BreakOptions())
        second = format_markdown(first, ENGINE, BreakOptions())
        self.assertEqual(first, second)


def _fake_doc(source: str, specs: list[tuple[str, str, str, str]]) -> list[FakeToken]:
    tokens: list[FakeToken] = []
    cursor = 0
    for text, pos, dep, tag in specs:
        idx = source.index(text, cursor)
        token = FakeToken(text=text, idx=idx, pos=pos, dep=dep, tag=tag)
        tokens.append(token)
        cursor = idx + len(text)
    return tokens


def _candidate_summary(candidates):
    return [(candidate.kind, candidate.offset) for candidate in candidates]


def _after_closing_punctuation(text: str, offset: int) -> int:
    while offset < len(text) and text[offset] in "\"')]}":
        offset += 1
    return offset


if __name__ == "__main__":
    unittest.main()
