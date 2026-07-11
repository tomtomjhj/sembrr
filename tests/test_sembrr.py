from __future__ import annotations

import subprocess
import sys
import unittest
from collections.abc import Iterable
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sembrr.breaks import (
    BreakBoundary,
    BreakOptions,
    SentenceEngine,
    SentenceEngineError,
    select_breaks,
)
from sembrr.candidates import spacy_optional_boundaries
from sembrr.cli import main
from sembrr.layout import _content_extents
from sembrr.markdown import format_markdown, format_text


class FixtureEngine:
    def break_boundaries(
        self,
        text: str,
        *,
        include_optional: bool,
    ) -> list[BreakBoundary]:
        boundaries = _sentence_boundaries(text)
        if include_optional:
            boundaries.extend(_whitespace_boundaries(text))
        return boundaries

    def break_boundaries_batch(
        self,
        texts: Iterable[str],
        *,
        include_optional: bool,
    ) -> list[list[BreakBoundary]]:
        return [self.break_boundaries(text, include_optional=include_optional) for text in texts]


ENGINE = FixtureEngine()


class RecordingEngine(FixtureEngine):
    def __init__(self) -> None:
        self.seen_text: list[str] = []

    def break_boundaries(
        self,
        text: str,
        *,
        include_optional: bool,
    ) -> list[BreakBoundary]:
        self.seen_text.append(text)
        return super().break_boundaries(text, include_optional=include_optional)


class BatchRecordingEngine(FixtureEngine):
    def __init__(self) -> None:
        self.seen_batches: list[list[str]] = []

    def break_boundaries_batch(
        self,
        texts: Iterable[str],
        *,
        include_optional: bool,
    ) -> list[list[BreakBoundary]]:
        text_batch = list(texts)
        self.seen_batches.append(text_batch)
        return super().break_boundaries_batch(
            text_batch,
            include_optional=include_optional,
        )


class FakeToken:
    def __init__(self, text: str, idx: int, index: int, pos: str) -> None:
        self.text = text
        self.idx = idx
        self.i = index
        self.pos_ = pos
        self.head = self


class FakeDoc:
    def __init__(self, tokens: list[FakeToken]) -> None:
        self.sents = [tokens]


class SembrrTests(unittest.TestCase):
    def test_sentence_engine_requires_requested_model(self) -> None:
        with self.assertRaisesRegex(SentenceEngineError, "spaCy model not found"):
            SentenceEngine(model="__missing_model__")

    def test_sentence_boundaries_require_source_whitespace(self) -> None:
        source = "First sentence.Second sentence."
        doc = SimpleNamespace(
            sents=[
                SimpleNamespace(end_char=source.index(".") + 1),
                SimpleNamespace(end_char=len(source)),
            ]
        )
        engine = SentenceEngine.__new__(SentenceEngine)

        self.assertEqual(engine._spacy_sentence_boundaries_from_doc(source, doc), [])

    def test_formats_stdin_style_markdown_paragraph(self) -> None:
        source = "One sentence. Another sentence.\n"
        expected = "One sentence.\nAnother sentence.\n"

        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

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

    def test_cli_handles_closed_downstream_pipe(self) -> None:
        with (
            patch("sembrr.cli.SentenceEngine", return_value=ENGINE),
            patch("sys.stdin", StringIO("One sentence. Another sentence.\n")),
            patch("sys.stdout") as stdout,
        ):
            stdout.write.side_effect = BrokenPipeError
            exit_code = main([])

        self.assertEqual(exit_code, 0)
        stdout.write.assert_called_once_with("One sentence.\nAnother sentence.\n")

    def test_markdown_parser_survives_large_shallow_document(self) -> None:
        code = (
            "import sys\n"
            "sys.path.insert(0, 'src')\n"
            "from sembrr.breaks import BreakOptions\n"
            "from sembrr.markdown import format_markdown\n"
            "class Engine:\n"
            "    def break_boundaries(self, text, *, include_optional):\n"
            "        return []\n"
            "    def break_boundaries_batch(self, texts, **kwargs):\n"
            "        return [[] for _ in texts]\n"
            "def section(index):\n"
            "    return (\n"
            "        f'### x.{index} heading (`code`)\\n\\n'\n"
            "        'word word word word word word word word word word word word word.\\n'\n"
            "        'word `code` word **word** word [link](target.md) word word.\\n\\n'\n"
            "        '| a | b | c |\\n|---|---|---|\\n'\n"
            "        '| word | `code` | word word word word word word word |\\n'\n"
            "        '| word | `code` | word word word word word word word |\\n\\n'\n"
            "        '- `code[x]` -- word word word word word word word word word.\\n'\n"
            "        '  word word word word word word word word word word word word.\\n'\n"
            "        '- **word** (`code`) -- word word word word word word word word.\\n'\n"
            "        '  word word word word word word word word word word word word.\\n\\n'\n"
            "    )\n"
            "source = 'x `code` word word word word word word.\\n\\n'\n"
            "source += ''.join(section(index) for index in range(21))\n"
            "format_markdown(source, Engine(), BreakOptions())\n"
        )

        result = subprocess.run(
            [sys.executable, "-X", "faulthandler", "-c", code],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_markdown_batches_paragraph_analysis(self) -> None:
        engine = BatchRecordingEngine()
        source = "One sentence. Another sentence.\n\nThird sentence. Fourth sentence.\n"

        result = format_markdown(source, engine, BreakOptions())

        self.assertEqual(
            result,
            "One sentence.\nAnother sentence.\n\nThird sentence.\nFourth sentence.\n",
        )
        self.assertEqual(
            engine.seen_batches,
            [["One sentence. Another sentence.", "Third sentence. Fourth sentence."]],
        )

    def test_preserves_atomic_markdown_source(self) -> None:
        cases = [
            (
                "Use [`foo.bar()`](./api.md#foo.bar). Then use `src/a.b.py`.\n",
                "Use [`foo.bar()`](./api.md#foo.bar).\nThen use `src/a.b.py`.\n",
            ),
            (
                "Use [v1.2][]. Then continue.\n",
                "Use [v1.2][].\nThen continue.\n",
            ),
            (
                "Before. After.\n\n```py\na.b()\n```\n\nNext. Last.\n",
                "Before.\nAfter.\n\n```py\na.b()\n```\n\nNext.\nLast.\n",
            ),
            (
                "| A | B |\n| - | - |\n| One. Two. | x |\n\nAfter. Next.\n",
                "| A | B |\n| - | - |\n| One. Two. | x |\n\nAfter.\nNext.\n",
            ),
            (
                "---\ntitle: One. Two.\n---\n\n"
                "# Heading. Still heading.\n\n"
                "[ref]: ./a.b\n\nAfter. Next.\n",
                "---\ntitle: One. Two.\n---\n\n"
                "# Heading. Still heading.\n\n"
                "[ref]: ./a.b\n\nAfter.\nNext.\n",
            ),
        ]

        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_maps_sentence_breaks_around_inline_markup(self) -> None:
        cases = [
            (
                "~~Removed sentence.~~ Remaining sentence.\n",
                "~~Removed sentence.~~\nRemaining sentence.\n",
            ),
            (
                "*One sentence. Two sentence.* Outside sentence.\n",
                "*One sentence.\nTwo sentence.*\nOutside sentence.\n",
            ),
            (
                "**First sentence.** Remaining sentence.\n",
                "**First sentence.**\nRemaining sentence.\n",
            ),
        ]

        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_formats_structural_continuation_prefixes(self) -> None:
        cases = [
            (
                "- One sentence. Another sentence.\n",
                "- One sentence.\n  Another sentence.\n",
            ),
            (
                "- [ ] One sentence. Another sentence.\n",
                "- [ ] One sentence.\n      Another sentence.\n",
            ),
            (
                "> One sentence. Another sentence.\n",
                "> One sentence.\n> Another sentence.\n",
            ),
            (
                "> - One. Two.\n>   More.\n\n  - Nested. Item.\n    More.\n\n> > Quote. More.\n",
                "> - One.\n>   Two.\n>   More.\n\n"
                "  - Nested.\n    Item.\n    More.\n\n"
                "> > Quote.\n> > More.\n",
            ),
        ]

        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_preserves_structure_across_long_markdown_blocks(self) -> None:
        cases = [
            (
                "* The parent item establishes context for the remaining steps. "
                "It records another result for later readers.\n"
                "  * The child item describes a separate operation. "
                "It keeps its own continuation text.\n",
                "* The parent item establishes context for the remaining steps.\n"
                "  It records another result for later readers.\n"
                "  * The child item describes a separate operation.\n"
                "    It keeps its own continuation text.\n",
            ),
            (
                "> * The quoted parent item introduces the procedure. "
                "It supplies supporting context.\n"
                ">   * The quoted child item records an independent check. "
                "It retains both structural prefixes.\n",
                "> * The quoted parent item introduces the procedure.\n"
                ">   It supplies supporting context.\n"
                ">   * The quoted child item records an independent check.\n"
                ">     It retains both structural prefixes.\n",
            ),
            (
                "* The list item contains two related observations. "
                "The second observation stays in the item.\n\n"
                "The following paragraph begins a separate discussion. "
                "Its continuation has no list prefix.\n",
                "* The list item contains two related observations.\n"
                "  The second observation stays in the item.\n\n"
                "The following paragraph begins a separate discussion.\n"
                "Its continuation has no list prefix.\n",
            ),
            (
                "The opening sentence establishes the paragraph. "
                "It prepares the marked statement.\n"
                "*The marked sentence starts on an authored line.* "
                "The final sentence remains in the paragraph.\n",
                "The opening sentence establishes the paragraph.\n"
                "It prepares the marked statement.\n"
                "*The marked sentence starts on an authored line.*\n"
                "The final sentence remains in the paragraph.\n",
            ),
        ]
        options = BreakOptions(mode="sentence")

        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(format_markdown(source, ENGINE, options), expected)

    def test_preserves_uncertain_multiline_inline_source(self) -> None:
        cases = [
            "One sentence.  \nAnother sentence.\n",
            "One sentence.\\\nAnother sentence.\n",
            "`x\ny`. Next sentence.\n",
        ]

        for source in cases:
            with self.subTest(source=source):
                self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), source)

    def test_passes_projected_text_to_engine(self) -> None:
        engine = RecordingEngine()
        source = "~~Removed sentence.~~ Remaining sentence.\n"

        format_markdown(source, engine, BreakOptions())

        self.assertEqual(engine.seen_text, ["Removed sentence. Remaining sentence."])

    def test_text_mode_uses_unprojected_paragraphs(self) -> None:
        engine = RecordingEngine()
        source = "One sentence. `Two sentence. Three sentence.` Four sentence.\n"

        format_text(source, engine, BreakOptions())

        self.assertEqual(
            engine.seen_text,
            ["One sentence. `Two sentence. Three sentence.` Four sentence."],
        )

    def test_text_mode_normalizes_markdown_hard_break_syntax(self) -> None:
        source = "One sentence.  \nAnother sentence.\n"
        expected = "One sentence.\nAnother sentence.\n"

        self.assertEqual(format_text(source, ENGINE, BreakOptions()), expected)

    def test_dependency_cuts_score_every_safe_gap(self) -> None:
        source = "Alpha beta gamma delta."
        doc = _fake_tree(
            source,
            ["Alpha", "beta", "gamma", "delta", "."],
            [1, 1, 3, 1, 3],
        )

        boundaries = spacy_optional_boundaries(source, doc)

        self.assertEqual(
            [(boundary.offset, boundary.penalty) for boundary in boundaries],
            [
                (source.index(" "), 1),
                (source.index(" ", 6), 0.25),
                (source.rindex(" "), 1.25),
            ],
        )

    def test_punctuation_and_wrappers_do_not_change_boundary_eligibility(self) -> None:
        source = "(Alpha beta — gamma delta.)"
        doc = _fake_tree(
            source,
            ["(", "Alpha", "beta", "—", "gamma", "delta", ".", ")"],
            [2, 2, 2, 2, 5, 2, 5, 2],
        )

        boundaries = spacy_optional_boundaries(source, doc)

        self.assertEqual(
            [boundary.offset for boundary in boundaries],
            [index for index, char in enumerate(source) if char == " "],
        )

    def test_short_dependencies_make_a_break_expensive(self) -> None:
        source = "Alpha and beta arrives."
        doc = _fake_tree(
            source,
            ["Alpha", "and", "beta", "arrives", "."],
            [3, 2, 0, 3, 3],
        )

        boundaries = spacy_optional_boundaries(source, doc)

        self.assertGreater(boundaries[1].penalty, boundaries[0].penalty)

    def test_function_words_are_expensive_line_endings(self) -> None:
        source = "Alpha and beta arrives."
        doc = _fake_tree(
            source,
            ["Alpha", "and", "beta", "arrives", "."],
            [0, 0, 3, 0, 3],
            ["NOUN", "CCONJ", "NOUN", "VERB", "PUNCT"],
        )

        boundaries = spacy_optional_boundaries(source, doc)

        self.assertGreaterEqual(boundaries[1].penalty, 1)

    def test_semantic_selection_prefers_stronger_syntax(self) -> None:
        source = f"{'a' * 35} {'b' * 35} {'c' * 35}"
        weak = BreakBoundary(offset=35, penalty=1)
        strong = BreakBoundary(offset=71, penalty=0.1)
        options = BreakOptions(target_segment_chars=80)

        self.assertEqual(select_breaks(source, [weak, strong], options), [strong])

    def test_content_extents_preserve_trimmed_segment_lengths(self) -> None:
        source = "  alpha \t beta\n\n gamma  "
        offsets = list(range(len(source) + 1))
        content_starts, content_ends = _content_extents(source, offsets)

        for left in range(len(offsets)):
            for right in range(left + 1, len(offsets)):
                expected = len(source[offsets[left] : offsets[right]].strip())
                actual = max(0, content_ends[right] - content_starts[left])
                self.assertEqual(actual, expected)

    def test_global_selection_avoids_extra_strong_breaks(self) -> None:
        source = " ".join(part * 45 for part in "abcd")
        first = BreakBoundary(offset=45, penalty=0.1)
        middle = BreakBoundary(offset=91, penalty=0.2)
        last = BreakBoundary(offset=137, penalty=0.1)
        options = BreakOptions(target_segment_chars=100)

        self.assertEqual(
            select_breaks(source, [first, middle, last], options),
            [middle],
        )

    def test_short_segment_length_is_a_soft_cost(self) -> None:
        source = f"{'a' * 20} {'b' * 90}"
        boundary = BreakBoundary(offset=20, penalty=0)
        options = BreakOptions(target_segment_chars=100, min_segment_chars=24)

        self.assertEqual(select_breaks(source, [boundary], options), [boundary])

    def test_semantic_mode_can_leave_a_small_overflow(self) -> None:
        source = f"{'a' * 50} {'b' * 51}"
        boundary = BreakBoundary(offset=50, penalty=1)
        options = BreakOptions(target_segment_chars=100)

        self.assertEqual(select_breaks(source, [boundary], options), [])

    def test_strict_mode_uses_a_weak_boundary_for_overflow(self) -> None:
        source = f"{'a' * 50} {'b' * 51}"
        boundary = BreakBoundary(offset=50, penalty=1)
        options = BreakOptions(mode="strict", target_segment_chars=100)

        self.assertEqual(select_breaks(source, [boundary], options), [boundary])

    def test_sentence_mode_ignores_optional_boundaries(self) -> None:
        source = "First sentence. Second sentence."
        mandatory = BreakBoundary(
            offset=source.index(" ", source.index(".")),
            penalty=0,
            mandatory=True,
        )
        optional = BreakBoundary(offset=source.index(" "), penalty=0)

        self.assertEqual(
            select_breaks(source, [optional, mandatory], BreakOptions(mode="sentence")),
            [mandatory],
        )

    def test_selection_uses_printed_source_length(self) -> None:
        source = "**Writers keep context visible; readers understand the result**"
        boundary = BreakBoundary(offset=source.index(";") + 1, penalty=0)
        options = BreakOptions(target_segment_chars=59, min_segment_chars=10)

        self.assertEqual(select_breaks(source, [boundary], options), [boundary])

    def test_strict_mode_preserves_oversized_markdown_atom(self) -> None:
        source = (
            "Read [an unusually long linked reference](https://example.com/some/long/path) "
            "after words.\n"
        )
        expected = (
            "Read\n"
            "[an unusually long linked reference](https://example.com/some/long/path)\n"
            "after words.\n"
        )
        options = BreakOptions(mode="strict", target_segment_chars=24)

        self.assertEqual(format_markdown(source, ENGINE, options), expected)

    def test_strict_mode_counts_structural_prefix_in_target(self) -> None:
        source = "1. The snapshot includes stable identifiers, timestamps, and source links.\n"
        options = BreakOptions(
            mode="strict",
            target_segment_chars=72,
            min_segment_chars=18,
        )

        result = format_markdown(source, ENGINE, options)

        self.assertTrue(all(len(line) <= 72 for line in result.splitlines()))

    def test_preserves_tree_sitter_inline_spans(self) -> None:
        source = "Use `경로/a.b.py`. Visit <https://x.y/z>. Then see http://x.y/z.\n"
        expected = "Use `경로/a.b.py`.\nVisit <https://x.y/z>.\nThen see http://x.y/z.\n"

        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_bare_url_does_not_swallow_sentence_punctuation(self) -> None:
        source = "See http://x.y/z. Next sentence.\n"
        expected = "See http://x.y/z.\nNext sentence.\n"

        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_placeholder_text_in_source_is_not_replaced(self) -> None:
        source = "Keep SEMBRRATOM0X0X literal. Then use `src/a.b.py`.\n"
        expected = "Keep SEMBRRATOM0X0X literal.\nThen use `src/a.b.py`.\n"

        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_idempotent(self) -> None:
        source = "- One sentence. Another sentence.\n\nUse `src/a.b.py`. Next sentence.\n"
        first = format_markdown(source, ENGINE, BreakOptions())
        second = format_markdown(first, ENGINE, BreakOptions())

        self.assertEqual(first, second)

    def test_task_list_continuation_is_idempotent(self) -> None:
        source = "- [ ] Confirm the selected destination. Keep the review record.\n"
        expected = "- [ ] Confirm the selected destination.\n      Keep the review record.\n"
        options = BreakOptions(mode="sentence")

        first = format_markdown(source, ENGINE, options)
        second = format_markdown(first, ENGINE, options)

        self.assertEqual(first, expected)
        self.assertEqual(second, first)


class RealEngineEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = SentenceEngine()

    def test_semantic_mode_uses_scored_boundaries(self) -> None:
        source = (
            "The formatter preserves the original source; the analyzer scores each boundary, "
            "and the layout chooses a coherent result.\n"
        )
        expected = (
            "The formatter preserves the original source;\n"
            "the analyzer scores each boundary,\n"
            "and the layout chooses a coherent result.\n"
        )
        options = BreakOptions(target_segment_chars=62, min_segment_chars=20)

        self.assertEqual(format_markdown(source, self.engine, options), expected)

    def test_strict_markdown_formatting_preserves_an_atom(self) -> None:
        source = (
            "Review [`render_page()`](api.md) before the integration runner processes "
            "the remaining configuration values.\n"
        )
        expected = (
            "Review [`render_page()`](api.md)\n"
            "before the integration\n"
            "runner processes\n"
            "the remaining configuration values.\n"
        )
        options = BreakOptions(
            mode="strict",
            target_segment_chars=36,
            min_segment_chars=12,
        )

        self.assertEqual(format_markdown(source, self.engine, options), expected)

    def test_semantic_mode_preserves_local_attachments(self) -> None:
        cases = [
            (
                "The report command reads a project manifest, validates the selected profile, "
                "and writes a deterministic summary for reviewers.\n",
                "The report command reads a project manifest,\n"
                "validates the selected profile,\n"
                "and writes a deterministic summary for reviewers.\n",
            ),
            (
                "The preview records every selected input, and the final pass reuses that "
                "snapshot so reviewers can compare the two operations.\n",
                "The preview records every selected input,\n"
                "and the final pass reuses that snapshot\n"
                "so reviewers can compare the two operations.\n",
            ),
            (
                "The final status may be **ready** (all required checks passed), "
                "**blocked** (a required input is missing), or **degraded** "
                "(publication succeeded with a recoverable warning); each state has a "
                "distinct follow-up action for the operator.\n",
                "The final status may be **ready** (all required checks passed),\n"
                "**blocked** (a required input is missing),\n"
                "or **degraded** (publication succeeded with a recoverable warning);\n"
                "each state has a distinct follow-up action for the operator.\n",
            ),
        ]
        options = BreakOptions(target_segment_chars=72, min_segment_chars=18)

        for source, expected in cases:
            with self.subTest(source=source):
                self.assertEqual(format_markdown(source, self.engine, options), expected)

    def test_semantic_mode_avoids_an_optional_overflow(self) -> None:
        source = (
            "Use [`ReportRunner.execute()`](reference/runner.md#execute) with `--dry-run` "
            "before publishing; the preview records every selected input, and the final pass "
            "reuses that snapshot so reviewers can compare the two operations.\n"
        )
        options = BreakOptions(target_segment_chars=72, min_segment_chars=18)

        result = format_markdown(source, self.engine, options)

        self.assertTrue(all(len(line) <= 72 for line in result.splitlines()))


def _sentence_boundaries(text: str) -> list[BreakBoundary]:
    boundaries: list[BreakBoundary] = []
    index = 0

    while index < len(text):
        if text[index] not in ".!?":
            index += 1
            continue

        offset = _after_closing_punctuation(text, index + 1)
        if offset < len(text) and text[offset].isspace():
            boundaries.append(BreakBoundary(offset=offset, penalty=0, mandatory=True))
        index = offset + 1

    return boundaries


def _whitespace_boundaries(text: str) -> list[BreakBoundary]:
    return [
        BreakBoundary(offset=index, penalty=1)
        for index, char in enumerate(text)
        if char.isspace() and 0 < index < len(text) - 1
    ]


def _fake_tree(
    source: str,
    words: list[str],
    heads: list[int],
    parts_of_speech: list[str] | None = None,
) -> FakeDoc:
    tokens: list[FakeToken] = []
    cursor = 0
    if parts_of_speech is None:
        parts_of_speech = ["NOUN"] * len(words)

    for index, (word, pos) in enumerate(zip(words, parts_of_speech, strict=True)):
        offset = source.index(word, cursor)
        tokens.append(FakeToken(word, offset, index, pos))
        cursor = offset + len(word)

    for token, head in zip(tokens, heads, strict=True):
        token.head = tokens[head]

    return FakeDoc(tokens)


def _after_closing_punctuation(text: str, offset: int) -> int:
    while offset < len(text) and text[offset] in "\"')]}":
        offset += 1
    return offset


if __name__ == "__main__":
    unittest.main()
