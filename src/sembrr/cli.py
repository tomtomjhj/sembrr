from __future__ import annotations

import argparse
import sys

from .engine import SentenceEngine, SentenceEngineError
from .markdown import format_markdown, format_text
from .models import MODES, BreakOptions


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sembrr",
        description="Format semantic line breaks from stdin to stdout.",
    )
    parser.add_argument(
        "--mode",
        choices=MODES,
        default="semantic",
    )
    parser.add_argument("--parser", choices=("markdown", "text"), default="markdown")
    parser.add_argument("--text", action="store_true", help="alias for --parser text")
    parser.add_argument("--model", default="en_core_web_sm", help="spaCy model name")
    parser.add_argument("--target-segment-chars", type=_positive_int, default=100)
    parser.add_argument("--min-segment-chars", type=_positive_int, default=24)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    parser_name = "text" if args.text else args.parser
    try:
        options = BreakOptions(
            mode=args.mode,
            target_segment_chars=args.target_segment_chars,
            min_segment_chars=args.min_segment_chars,
        )
    except ValueError as error:
        parser.error(str(error))

    try:
        source = sys.stdin.read()
        engine = SentenceEngine(model=args.model)
        if parser_name == "text":
            result = format_text(source, engine, options)
        else:
            result = format_markdown(source, engine, options)
        sys.stdout.write(result)
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130
    except SentenceEngineError as error:
        print(f"sembrr: {error}", file=sys.stderr)
        return 2

    return 0
