from __future__ import annotations

import argparse
import sys

from .breaks import BreakOptions, SentenceEngine, SentenceEngineError
from .markdown import format_markdown, format_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sembrr",
        description="Format semantic line breaks from stdin to stdout.",
    )
    parser.add_argument("--mode", choices=("sentence", "clause", "phrase"), default="clause")
    parser.add_argument("--parser", choices=("markdown", "text"), default="markdown")
    parser.add_argument("--text", action="store_true", help="alias for --parser text")
    parser.add_argument("--model", default="en_core_web_sm", help="spaCy model name")
    parser.add_argument("--target-segment-chars", type=int, default=100)
    parser.add_argument("--min-clause-chars", type=int, default=24)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    parser_name = "text" if args.text else args.parser
    options = BreakOptions(
        mode=args.mode,
        target_segment_chars=args.target_segment_chars,
        min_clause_chars=args.min_clause_chars,
        model=args.model,
    )

    source = sys.stdin.read()

    try:
        engine = SentenceEngine(model=args.model)
        if parser_name == "text":
            result = format_text(source, engine, options)
        else:
            result = format_markdown(source, engine, options)
    except SentenceEngineError as error:
        print(f"sembrr: {error}", file=sys.stderr)
        return 2

    sys.stdout.write(result)
    return 0
