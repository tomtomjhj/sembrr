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
    _spacy_phrase_candidates,
    format_prose,
    select_breaks,
)
from sembrr.cli import main
from sembrr.markdown import format_markdown, format_text


class FixtureEngine:
    def break_candidates(
        self,
        text: str,
        *,
        include_clauses: bool,
        include_phrases: bool = False,
    ) -> tuple[list[BreakCandidate], list[BreakCandidate]]:
        sentence_breaks = self.sentence_candidates(text)
        optional_breaks = self.clause_candidates(text) if include_clauses else []
        if include_phrases:
            optional_breaks.extend(self.phrase_candidates(text))
        return sentence_breaks, optional_breaks

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

    def phrase_candidates(self, text: str) -> list[BreakCandidate]:
        candidates: list[BreakCandidate] = []

        like = text.find(" like ")
        if like >= 0:
            candidates.append(
                BreakCandidate(
                    offset=like + 1,
                    kind="example_phrase",
                    confidence=0.55,
                    reason="fixture example phrase boundary",
                )
            )

        or_splitting = text.find(" or splitting")
        if or_splitting >= 0:
            candidates.append(
                BreakCandidate(
                    offset=or_splitting + 1,
                    kind="gerund_coordinate",
                    confidence=0.55,
                    reason="fixture gerund coordinate boundary",
                )
            )

        finite_coordinate = text.find(" and every ")
        if finite_coordinate >= 0:
            candidates.append(
                BreakCandidate(
                    offset=finite_coordinate + 1,
                    kind="finite_coordinate",
                    confidence=0.65,
                    reason="fixture finite coordinate boundary",
                )
            )

        nominal_coordinate = text.find(" and the static-analysis ")
        if nominal_coordinate >= 0:
            candidates.append(
                BreakCandidate(
                    offset=nominal_coordinate + 1,
                    kind="nominal_coordinate",
                    confidence=0.5,
                    reason="fixture nominal coordinate boundary",
                )
            )

        to_preserve = text.find(" to preserve ")
        if to_preserve >= 0:
            candidates.append(
                BreakCandidate(
                    offset=to_preserve + 1,
                    kind="infinitive_phrase",
                    confidence=0.45,
                    reason="fixture infinitive phrase boundary",
                )
            )

        using_parser = text.find(" using parser ")
        if using_parser >= 0:
            candidates.append(
                BreakCandidate(
                    offset=using_parser + 1,
                    kind="participial_phrase",
                    confidence=0.45,
                    reason="fixture participial phrase boundary",
                )
            )

        cursor = text.find(",")
        while cursor >= 0:
            candidates.append(
                BreakCandidate(
                    offset=cursor + 1,
                    kind="comma_phrase",
                    confidence=0.35,
                    reason="fixture comma phrase boundary",
                )
            )
            cursor = text.find(",", cursor + 1)

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

        comma_so = text.find(", so ")
        if comma_so >= 0:
            candidates.append(
                BreakCandidate(
                    offset=comma_so + 2,
                    kind="comma_clause",
                    confidence=0.78,
                    reason="fixture comma-led finite clause boundary",
                )
            )

        return candidates


ENGINE = FixtureEngine()


class RecordingEngine(FixtureEngine):
    def __init__(self) -> None:
        self.seen_text: list[str] = []

    def break_candidates(
        self,
        text: str,
        *,
        include_clauses: bool,
        include_phrases: bool = False,
    ) -> tuple[list[BreakCandidate], list[BreakCandidate]]:
        self.seen_text.append(text)
        return super().break_candidates(
            text,
            include_clauses=include_clauses,
            include_phrases=include_phrases,
        )


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
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit,\n"
            "sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.\n"
            "*Ut enim ad minim veniam*,\n"
            "quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.\n"
        )
        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_breaks_after_emphasized_sentence(self) -> None:
        source = (
            "**Lorem ipsum.** Lorem ipsum dolor sit amet, consectetur adipiscing elit, "
            "sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.\n"
        )
        expected = (
            "**Lorem ipsum.**\n"
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit,\n"
            "sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.\n"
        )
        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_breaks_after_strikethrough_sentence(self) -> None:
        source = "~~Removed sentence.~~ Remaining sentence.\n"
        expected = "~~Removed sentence.~~\nRemaining sentence.\n"
        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_breaks_inside_emphasis(self) -> None:
        source = "*One sentence. Two sentence.* Outside sentence.\n"
        expected = "*One sentence.\nTwo sentence.*\nOutside sentence.\n"
        self.assertEqual(format_markdown(source, ENGINE, BreakOptions()), expected)

    def test_passes_projected_text_to_sentence_engine(self) -> None:
        engine = RecordingEngine()
        source = "~~Removed sentence.~~ Remaining sentence.\n"

        format_markdown(source, engine, BreakOptions())

        self.assertEqual(engine.seen_text, ["Removed sentence. Remaining sentence."])

    def test_clause_selection_counts_source_markup(self) -> None:
        source = "**Writers keep context visible; readers understand the result**\n"
        expected = "**Writers keep context visible;\nreaders understand the result**\n"
        options = BreakOptions(mode="clause", target_segment_chars=59, min_clause_chars=10)

        self.assertEqual(format_markdown(source, ENGINE, options), expected)

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
            "* Lorem ipsum dolor sit amet, consectetur adipiscing elit,\n"
            "  sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.\n"
            "  Ut enim ad minim veniam,\n"
            "  quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.\n"
            "    * Duis aute irure dolor in reprehenderit in voluptate velit esse cillum "
            "dolore eu fugiat nulla pariatur.\n"
            "      Excepteur sint occaecat cupidatat non proident,\n"
            "      sunt in culpa qui officia deserunt mollit anim id est laborum.\n"
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
            "* Lorem ipsum dolor sit amet, consectetur adipiscing elit,\n"
            "  sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.\n"
            "  Ut enim ad minim veniam,\n"
            "  quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.\n"
            "\n"
            "Excepteur sint occaecat cupidatat non proident,\n"
            "sunt in culpa qui officia deserunt mollit anim id est laborum.\n"
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

    def test_clause_mode_breaks_comma_led_result_clause(self) -> None:
        source = "The renderer preserves the cached value, so the scheduler evaluates it unchanged."
        expected = (
            "The renderer preserves the cached value,\nso the scheduler evaluates it unchanged."
        )
        options = BreakOptions(mode="clause", target_segment_chars=60, min_clause_chars=24)

        self.assertEqual(format_prose(source, ENGINE, options), expected)

    def test_phrase_mode_adds_phrase_breaks(self) -> None:
        source = (
            "Use it when it looks better than other options like colons and parentheses "
            "or splitting into separate sentences."
        )
        expected = (
            "Use it when it looks better than other options\n"
            "like colons and parentheses\n"
            "or splitting into separate sentences."
        )
        options = BreakOptions(mode="phrase", target_segment_chars=60, min_clause_chars=24)

        self.assertEqual(format_prose(source, ENGINE, options), expected)

    def test_phrase_mode_adds_finite_coordinate_breaks(self) -> None:
        source = (
            "The runner keeps the intermediate output stable and every downstream "
            "check remains green."
        )
        expected = (
            "The runner keeps the intermediate output stable\n"
            "and every downstream check remains green."
        )
        options = BreakOptions(mode="phrase", target_segment_chars=60, min_clause_chars=24)

        self.assertEqual(format_prose(source, ENGINE, options), expected)

    def test_phrase_mode_prefers_finite_coordinate_over_short_parenthetical(self) -> None:
        source = (
            "The runner applies the output unchanged and every downstream gate "
            "(shape, timing) remains green."
        )
        finite_coordinate = BreakCandidate(
            offset=source.index("and"),
            kind="finite_coordinate",
            confidence=0.65,
            reason="test finite coordinate boundary",
        )
        parenthetical = BreakCandidate(
            offset=source.index("("),
            kind="parenthetical-start",
            confidence=0.94,
            reason="test parenthetical boundary",
        )
        options = BreakOptions(mode="phrase", target_segment_chars=80, min_clause_chars=24)

        selected = select_breaks(source, [], [finite_coordinate, parenthetical], options)

        self.assertEqual(selected, [finite_coordinate])

    def test_phrase_mode_formats_markdown(self) -> None:
        source = (
            "**Use it** when it looks better than other options like colons and parentheses "
            "or splitting into separate sentences.\n"
        )
        expected = (
            "**Use it** when it looks better than other options\n"
            "like colons and parentheses\n"
            "or splitting into separate sentences.\n"
        )
        options = BreakOptions(mode="phrase", target_segment_chars=60, min_clause_chars=24)

        self.assertEqual(format_markdown(source, ENGINE, options), expected)

    def test_phrase_mode_formats_markdown_nominal_coordinate(self) -> None:
        source = (
            "It is the design rationale behind [`aaa/bbb/example.py`](../bbb/example.py) "
            "and the static-analysis surface in [`architecture.md` section](architecture.md).\n"
        )
        expected = (
            "It is the design rationale behind [`aaa/bbb/example.py`](../bbb/example.py)\n"
            "and the static-analysis surface in [`architecture.md` section](architecture.md).\n"
        )
        options = BreakOptions(mode="phrase", target_segment_chars=100, min_clause_chars=24)

        self.assertEqual(format_markdown(source, ENGINE, options), expected)

    def test_phrase_mode_uses_weak_nonfinite_phrase_breaks_last(self) -> None:
        source = (
            "The formatter projects Markdown source to preserve protected spans and map "
            "offsets back."
        )
        expected = (
            "The formatter projects Markdown source\n"
            "to preserve protected spans and map offsets back."
        )
        options = BreakOptions(mode="phrase", target_segment_chars=60, min_clause_chars=24)

        self.assertEqual(format_prose(source, ENGINE, options), expected)

    def test_phrase_mode_uses_comma_break_as_last_resort(self) -> None:
        source = (
            "The formatter keeps the prose readable, even when stronger phrase candidates "
            "are absent from the sentence."
        )
        expected = (
            "The formatter keeps the prose readable,\n"
            "even when stronger phrase candidates are absent from the sentence."
        )
        options = BreakOptions(mode="phrase", target_segment_chars=70, min_clause_chars=24)

        self.assertEqual(format_prose(source, ENGINE, options), expected)

    def test_phrase_mode_rejects_short_comma_breaks(self) -> None:
        source = (
            "Short start, then the formatter keeps adding more words until the line is "
            "too long for the target."
        )
        options = BreakOptions(mode="phrase", target_segment_chars=30)

        self.assertEqual(format_prose(source, ENGINE, options), source)

    def test_phrase_mode_prefers_nonfinite_phrase_over_comma_break(self) -> None:
        source = (
            "The formatter keeps a stable projection, while using parser output to preserve "
            "source offsets."
        )
        comma = BreakCandidate(
            offset=source.index(",") + 1,
            kind="comma_phrase",
            confidence=0.35,
            reason="test comma phrase boundary",
        )
        nonfinite = BreakCandidate(
            offset=source.index("using"),
            kind="participial_phrase",
            confidence=0.45,
            reason="test participial phrase boundary",
        )
        options = BreakOptions(mode="phrase", target_segment_chars=70, min_clause_chars=24)

        selected = select_breaks(source, [], [comma, nonfinite], options)

        self.assertEqual(selected, [nonfinite])

    def test_strict_mode_enforces_target_at_word_boundaries(self) -> None:
        source = "Alpha beta gamma delta epsilon zeta eta."
        expected = "Alpha beta gamma\ndelta epsilon\nzeta eta."
        options = BreakOptions(mode="strict", target_segment_chars=16)

        self.assertEqual(format_prose(source, ENGINE, options), expected)

    def test_strict_mode_uses_short_comma_break_before_word_boundary(self) -> None:
        source = (
            "Short start, then the formatter keeps adding more words until the line is "
            "too long for the target."
        )
        expected = (
            "Short start,\n"
            "then the formatter keeps\n"
            "adding more words until the\n"
            "line is too long for the\n"
            "target."
        )
        options = BreakOptions(mode="strict", target_segment_chars=30)

        self.assertEqual(format_prose(source, ENGINE, options), expected)

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

    def test_clause_mode_discovers_spacy_comma_clause_boundary(self) -> None:
        source = "The formatter preserves the cache, so the runner evaluates the result later."
        tokens = _fake_doc(
            source,
            [
                ("The", "DET", "det", "DT"),
                ("formatter", "NOUN", "nsubj", "NN"),
                ("preserves", "VERB", "ROOT", "VBZ"),
                ("the", "DET", "det", "DT"),
                ("cache", "NOUN", "dobj", "NN"),
                (",", "PUNCT", "punct", ","),
                ("so", "ADV", "advmod", "RB"),
                ("the", "DET", "det", "DT"),
                ("runner", "NOUN", "nsubj", "NN"),
                ("evaluates", "VERB", "conj", "VBZ"),
                ("the", "DET", "det", "DT"),
                ("result", "NOUN", "dobj", "NN"),
                ("later", "ADV", "advmod", "RB"),
                (".", "PUNCT", "punct", "."),
            ],
        )

        candidates = _spacy_clause_candidates(source, tokens)

        self.assertIn(("comma_clause", source.index("so")), _candidate_summary(candidates))

    def test_clause_mode_discovers_nonlexical_comma_clause_boundary(self) -> None:
        source = "The guide explains the process, how the writer keeps readers oriented."
        tokens = _fake_doc(
            source,
            [
                ("The", "DET", "det", "DT"),
                ("guide", "NOUN", "nsubj", "NN"),
                ("explains", "VERB", "ROOT", "VBZ"),
                ("the", "DET", "det", "DT"),
                ("process", "NOUN", "dobj", "NN"),
                (",", "PUNCT", "punct", ","),
                ("how", "SCONJ", "advmod", "WRB"),
                ("the", "DET", "det", "DT"),
                ("writer", "NOUN", "nsubj", "NN"),
                ("keeps", "VERB", "ccomp", "VBZ"),
                ("readers", "NOUN", "dobj", "NNS"),
                ("oriented", "ADJ", "acomp", "JJ"),
                (".", "PUNCT", "punct", "."),
            ],
        )

        candidates = _spacy_clause_candidates(source, tokens)

        self.assertIn(("comma_clause", source.index("how")), _candidate_summary(candidates))

    def test_clause_mode_ignores_comma_led_noun_phrase_tail(self) -> None:
        source = "The guide explains the process, and the concrete check it unlocks."
        tokens = _fake_doc(
            source,
            [
                ("The", "DET", "det", "DT"),
                ("guide", "NOUN", "nsubj", "NN"),
                ("explains", "VERB", "ROOT", "VBZ"),
                ("the", "DET", "det", "DT"),
                ("process", "NOUN", "dobj", "NN"),
                (",", "PUNCT", "punct", ","),
                ("and", "CCONJ", "cc", "CC"),
                ("the", "DET", "det", "DT"),
                ("concrete", "ADJ", "amod", "JJ"),
                ("check", "NOUN", "conj", "NN"),
                ("it", "PRON", "nsubj", "PRP"),
                ("unlocks", "VERB", "relcl", "VBZ"),
                (".", "PUNCT", "punct", "."),
            ],
        )

        candidates = _spacy_clause_candidates(source, tokens)
        summary = _candidate_summary(candidates)

        self.assertNotIn(("comma_clause", source.index("and")), summary)
        self.assertNotIn(("coordinate", source.index("and")), summary)

    def test_clause_mode_prefers_parenthetical_boundaries(self) -> None:
        source = (
            "Authors ship a summary (builders create a plan: runners check it) "
            "before readers use it."
        )
        tokens = _fake_doc(
            source,
            [
                ("Authors", "NOUN", "nsubj", "NNS"),
                ("ship", "VERB", "ROOT", "VBP"),
                ("a", "DET", "det", "DT"),
                ("summary", "NOUN", "dobj", "NN"),
                ("(", "PUNCT", "punct", "-LRB-"),
                ("builders", "NOUN", "nsubj", "NNS"),
                ("create", "VERB", "relcl", "VBP"),
                ("a", "DET", "det", "DT"),
                ("plan", "NOUN", "dobj", "NN"),
                (":", "PUNCT", "punct", ":"),
                ("runners", "NOUN", "nsubj", "NNS"),
                ("check", "VERB", "conj", "VBP"),
                ("it", "PRON", "dobj", "PRP"),
                (")", "PUNCT", "punct", "-RRB-"),
                ("before", "SCONJ", "mark", "IN"),
                ("readers", "NOUN", "nsubj", "NNS"),
                ("use", "VERB", "advcl", "VBP"),
                ("it", "PRON", "dobj", "PRP"),
                (".", "PUNCT", "punct", "."),
            ],
        )

        candidates = _spacy_clause_candidates(source, tokens)
        summary = _candidate_summary(candidates)

        self.assertIn(("parenthetical-start", source.index("(")), summary)
        self.assertIn(("parenthetical-end", source.index(")") + 1), summary)
        self.assertNotIn(("colon", source.index(":") + 1), summary)

    def test_clause_mode_ignores_unmatched_parenthesis_for_depth(self) -> None:
        source = "Authors ship a draft (temporary note; readers review the result."
        tokens = _fake_doc(
            source,
            [
                ("Authors", "NOUN", "nsubj", "NNS"),
                ("ship", "VERB", "ROOT", "VBP"),
                ("a", "DET", "det", "DT"),
                ("draft", "NOUN", "dobj", "NN"),
                ("(", "PUNCT", "punct", "-LRB-"),
                ("temporary", "ADJ", "amod", "JJ"),
                ("note", "NOUN", "dobj", "NN"),
                (";", "PUNCT", "punct", ":"),
                ("readers", "NOUN", "nsubj", "NNS"),
                ("review", "VERB", "conj", "VBP"),
                ("the", "DET", "det", "DT"),
                ("result", "NOUN", "dobj", "NN"),
                (".", "PUNCT", "punct", "."),
            ],
        )

        candidates = _spacy_clause_candidates(source, tokens)

        self.assertIn(("semicolon", source.index(";") + 1), _candidate_summary(candidates))

    def test_phrase_mode_discovers_spacy_phrase_boundaries(self) -> None:
        source = (
            "Use it when it looks better than other options like colons and parentheses "
            "or splitting into separate sentences."
        )
        tokens = _fake_doc(
            source,
            [
                ("Use", "VERB", "ROOT", "VB"),
                ("it", "PRON", "dobj", "PRP"),
                ("when", "SCONJ", "advmod", "WRB"),
                ("it", "PRON", "nsubj", "PRP"),
                ("looks", "VERB", "advcl", "VBZ"),
                ("better", "ADJ", "acomp", "JJR"),
                ("than", "ADP", "prep", "IN"),
                ("other", "ADJ", "amod", "JJ"),
                ("options", "NOUN", "pobj", "NNS"),
                ("like", "ADP", "prep", "IN"),
                ("colons", "NOUN", "pobj", "NNS"),
                ("and", "CCONJ", "cc", "CC"),
                ("parentheses", "NOUN", "conj", "NNS"),
                ("or", "CCONJ", "cc", "CC"),
                ("splitting", "VERB", "conj", "VBG"),
                ("into", "ADP", "prep", "IN"),
                ("separate", "ADJ", "amod", "JJ"),
                ("sentences", "NOUN", "pobj", "NNS"),
                (".", "PUNCT", "punct", "."),
            ],
        )

        candidates = _spacy_phrase_candidates(source, tokens)
        self.assertIn(("example_phrase", source.index("like")), _candidate_summary(candidates))
        self.assertIn(
            ("gerund_coordinate", source.index("or")),
            _candidate_summary(candidates),
        )

    def test_phrase_mode_discovers_spacy_finite_coordinate_boundary(self) -> None:
        source = (
            "The runner keeps the intermediate output stable and every downstream "
            "check remains green."
        )
        tokens = _fake_doc(
            source,
            [
                ("The", "DET", "det", "DT"),
                ("runner", "NOUN", "nsubj", "NN"),
                ("keeps", "VERB", "ROOT", "VBZ"),
                ("the", "DET", "det", "DT"),
                ("intermediate", "ADJ", "amod", "JJ"),
                ("output", "NOUN", "dobj", "NN"),
                ("stable", "ADJ", "acomp", "JJ"),
                ("and", "CCONJ", "cc", "CC"),
                ("every", "DET", "det", "DT"),
                ("downstream", "ADJ", "amod", "JJ"),
                ("check", "NOUN", "nsubj", "NN"),
                ("remains", "VERB", "conj", "VBZ"),
                ("green", "ADJ", "acomp", "JJ"),
                (".", "PUNCT", "punct", "."),
            ],
        )

        candidates = _spacy_phrase_candidates(source, tokens)

        self.assertIn(
            ("finite_coordinate", source.index("and")),
            _candidate_summary(candidates),
        )

    def test_phrase_mode_discovers_spacy_nominal_coordinate_boundary(self) -> None:
        source = (
            "It is the design rationale behind a reference link and the static-analysis "
            "surface in a design note."
        )
        tokens = _fake_doc(
            source,
            [
                ("It", "PRON", "nsubj", "PRP"),
                ("is", "AUX", "ROOT", "VBZ"),
                ("the", "DET", "det", "DT"),
                ("design", "NOUN", "compound", "NN"),
                ("rationale", "NOUN", "attr", "NN"),
                ("behind", "ADP", "prep", "IN"),
                ("a", "DET", "det", "DT"),
                ("reference", "NOUN", "compound", "NN"),
                ("link", "NOUN", "pobj", "NN"),
                ("and", "CCONJ", "cc", "CC"),
                ("the", "DET", "det", "DT"),
                ("static", "NOUN", "compound", "NN"),
                ("-", "PUNCT", "punct", "HYPH"),
                ("analysis", "NOUN", "compound", "NN"),
                ("surface", "NOUN", "conj", "NN"),
                ("in", "ADP", "prep", "IN"),
                ("a", "DET", "det", "DT"),
                ("design", "NOUN", "compound", "NN"),
                ("note", "NOUN", "pobj", "NN"),
                (".", "PUNCT", "punct", "."),
            ],
        )

        candidates = _spacy_phrase_candidates(source, tokens)

        self.assertIn(
            ("nominal_coordinate", source.index("and")),
            _candidate_summary(candidates),
        )

    def test_phrase_mode_discovers_spacy_lowest_priority_phrase_boundaries(self) -> None:
        source = (
            "The formatter projects Markdown source, to preserve protected spans using "
            "parser output."
        )
        tokens = _fake_doc(
            source,
            [
                ("The", "DET", "det", "DT"),
                ("formatter", "NOUN", "nsubj", "NN"),
                ("projects", "VERB", "ROOT", "VBZ"),
                ("Markdown", "PROPN", "compound", "NNP"),
                ("source", "NOUN", "dobj", "NN"),
                (",", "PUNCT", "punct", ","),
                ("to", "PART", "aux", "TO"),
                ("preserve", "VERB", "acl", "VB"),
                ("protected", "VERB", "amod", "VBN"),
                ("spans", "NOUN", "dobj", "NNS"),
                ("using", "VERB", "xcomp", "VBG"),
                ("parser", "NOUN", "compound", "NN"),
                ("output", "NOUN", "dobj", "NN"),
                (".", "PUNCT", "punct", "."),
            ],
        )

        candidates = _spacy_phrase_candidates(source, tokens)
        summary = _candidate_summary(candidates)

        self.assertIn(("infinitive_phrase", source.index("to")), summary)
        self.assertIn(("participial_phrase", source.index("using")), summary)
        self.assertIn(("comma_phrase", source.index(",") + 1), summary)

    def test_phrase_mode_avoids_parenthetical_phrase_boundaries(self) -> None:
        source = (
            "Authors keep a guide (including tricky examples, or splitting extra cases) "
            "before readers use it."
        )
        tokens = _fake_doc(
            source,
            [
                ("Authors", "NOUN", "nsubj", "NNS"),
                ("keep", "VERB", "ROOT", "VBP"),
                ("a", "DET", "det", "DT"),
                ("guide", "NOUN", "dobj", "NN"),
                ("(", "PUNCT", "punct", "-LRB-"),
                ("including", "ADP", "prep", "VBG"),
                ("tricky", "ADJ", "amod", "JJ"),
                ("examples", "NOUN", "pobj", "NNS"),
                (",", "PUNCT", "punct", ","),
                ("or", "CCONJ", "cc", "CC"),
                ("splitting", "VERB", "conj", "VBG"),
                ("extra", "ADJ", "amod", "JJ"),
                ("cases", "NOUN", "dobj", "NNS"),
                (")", "PUNCT", "punct", "-RRB-"),
                ("before", "SCONJ", "mark", "IN"),
                ("readers", "NOUN", "nsubj", "NNS"),
                ("use", "VERB", "advcl", "VBP"),
                ("it", "PRON", "dobj", "PRP"),
                (".", "PUNCT", "punct", "."),
            ],
        )

        candidates = _spacy_phrase_candidates(source, tokens)
        summary = _candidate_summary(candidates)

        self.assertNotIn(("example_phrase", source.index("including")), summary)
        self.assertNotIn(("gerund_coordinate", source.index("or")), summary)
        self.assertNotIn(("comma_phrase", source.index(",") + 1), summary)

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
