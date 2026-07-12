from __future__ import annotations

import argparse
import os
import sys

from .engine import SentenceEngine, SentenceEngineError
from .markdown import format_markdown, format_text
from .models import MODES, BreakOptions

_DEFAULT_OPTIONS = BreakOptions()


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
        default=_DEFAULT_OPTIONS.mode,
        help=(
            "breaking policy: sentence emits only sentence boundaries; "
            "semantic adds syntax-scored breaks; strict enforces the target "
            "(default: semantic)"
        ),
    )
    parser.add_argument(
        "--text",
        action="store_true",
        help="treat stdin as plain text; Markdown syntax has no special meaning",
    )
    parser.add_argument(
        "--model",
        default="en_core_web_sm",
        help=(
            "English spaCy model; semantic and strict modes require a dependency parser "
            "(default: en_core_web_sm)"
        ),
    )
    parser.add_argument(
        "-t",
        "--target-chars",
        type=_positive_int,
        default=_DEFAULT_OPTIONS.target_chars,
        help=(
            "target printed characters per line; semantic mode may exceed it "
            f"(default: {_DEFAULT_OPTIONS.target_chars})"
        ),
    )
    parser.add_argument(
        "--min-chars",
        type=_positive_int,
        help=(
            "soft minimum printed characters per line; defaults to "
            f"{_DEFAULT_OPTIONS.min_chars}, or the target when lower"
        ),
    )
    return parser


def _silence_stdout() -> None:
    try:
        stdout_fd = sys.stdout.fileno()
    except (AttributeError, OSError, TypeError, ValueError):
        return

    try:
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull_fd, stdout_fd)
        finally:
            os.close(devnull_fd)
    except (OSError, TypeError, ValueError):
        return


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        options = BreakOptions(
            mode=args.mode,
            target_chars=args.target_chars,
            min_chars=(
                args.min_chars
                if args.min_chars is not None
                else min(_DEFAULT_OPTIONS.min_chars, args.target_chars)
            ),
        )
    except ValueError as error:
        parser.error(str(error))

    try:
        source = sys.stdin.read()
        engine = SentenceEngine(model=args.model)
        if args.text:
            result = format_text(source, engine, options)
        else:
            result = format_markdown(source, engine, options)
        sys.stdout.write(result)
        sys.stdout.flush()
    except BrokenPipeError:
        _silence_stdout()
        return 0
    except KeyboardInterrupt:
        return 130
    except SentenceEngineError as error:
        print(f"sembrr: {error}", file=sys.stderr)
        return 2

    return 0
