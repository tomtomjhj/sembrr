#!/usr/bin/env python3
"""Measure Sembrr startup, throughput, scaling, and resident latency."""

from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import socket
import statistics
import struct
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FRAME_LENGTH = struct.Struct("!Q")

ORDINARY_PARAGRAPH = (
    "Sembrr formats semantic line breaks in Markdown while preserving rendered meaning. "
    "It protects [`atomic spans`](guide.md), inline code such as `python -m sembrr`, and "
    "bare URLs such as https://example.com/a/long/path. The formatter scores dependency "
    "cuts and uses global optimization to choose readable lines without changing source "
    "constructs. This representative paragraph contains several sentences and enough words "
    "to require optional breaks under the default target."
)

LONG_SENTENCE_WORDS = (
    "the",
    "careful",
    "editor",
    "reviews",
    "technical",
    "prose",
    "and",
    "improves",
    "clarity",
)

RESIDENT_CLIENT = """
import socket
import struct
import sys

length_struct = struct.Struct("!Q")
source = sys.stdin.buffer.read()
with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
    connection.connect(sys.argv[1])
    connection.sendall(length_struct.pack(len(source)) + source)
    header = bytearray()
    while len(header) < length_struct.size:
        chunk = connection.recv(length_struct.size - len(header))
        if not chunk:
            raise EOFError("service closed before the response header")
        header.extend(chunk)
    remaining = length_struct.unpack(header)[0]
    response = bytearray()
    while len(response) < remaining:
        chunk = connection.recv(remaining - len(response))
        if not chunk:
            raise EOFError("service closed before the response body")
        response.extend(chunk)
sys.stdout.buffer.write(response)
"""


@dataclass(frozen=True)
class Measurement:
    name: str
    category: str
    median_ms: float
    minimum_ms: float
    maximum_ms: float
    samples_ms: list[float]
    workload_size: int | None = None
    workload_unit: str | None = None
    rate_per_second: float | None = None


class NoopEngine:
    """Remove NLP analysis from Markdown pipeline measurements."""

    def break_boundaries_batch(
        self,
        texts: Iterable[str],
        *,
        include_optional: bool,
    ) -> list[list[Any]]:
        return [[] for _ in texts]


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure repeatable Sembrr performance workloads.",
    )
    parser.add_argument(
        "--repeats",
        type=_positive_int,
        default=5,
        help="timed samples for warm and resident measurements (default: 5)",
    )
    parser.add_argument(
        "--cold-repeats",
        type=_positive_int,
        default=3,
        help="timed fresh-process samples (default: 3)",
    )
    parser.add_argument(
        "--long-sizes",
        type=_positive_int,
        nargs="+",
        default=[50, 100, 200, 400],
        metavar="TOKENS",
        help="long-sentence word counts (default: 50 100 200 400)",
    )
    parser.add_argument(
        "--skip-cold",
        action="store_true",
        help="skip fresh-process measurements",
    )
    parser.add_argument(
        "--skip-resident",
        action="store_true",
        help="skip the Unix-socket resident prototype",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON instead of a table",
    )
    return parser


def _ordinary_document(paragraphs: int) -> str:
    return "\n\n".join(ORDINARY_PARAGRAPH for _ in range(paragraphs)) + "\n"


def _markdown_heavy_document(sections: int = 30) -> str:
    parts: list[str] = []
    for index in range(sections):
        parts.append(
            f"""### Section {index}

Use **strong prose**, *emphasis*, ~~edits~~, and `inline.code({index})` with
[`linked code`](guide-{index}.md), ![an image](image-{index}.png),
<https://example.com/{index}>, and https://example.org/a/{index}?query=value.
Another sentence keeps this paragraph long enough to require semantic breaks.

> A quoted paragraph contains **markup**, `code`, and [a link](quote-{index}.md).
> Its second sentence exercises continuation prefixes and source offset mapping.

- A list paragraph uses `item_{index}` and [documentation](list-{index}.md).
  Its second sentence exercises synthesized continuation prefixes.

| Construct | Source |
| --- | --- |
| Code | `value_{index}` |
| Link | [target](table-{index}.md) |

```python
print("section {index}")
```

"""
        )
    return "".join(parts)


def _long_sentence(words: int) -> str:
    tokens = (LONG_SENTENCE_WORDS[index % len(LONG_SENTENCE_WORDS)] for index in range(words))
    return " ".join(tokens) + "."


def _measure(
    name: str,
    category: str,
    operation: Callable[[], object],
    *,
    repeats: int,
    warmups: int = 1,
    workload_size: int | None = None,
    workload_unit: str | None = None,
) -> Measurement:
    for _ in range(warmups):
        operation()

    samples: list[float] = []
    for _ in range(repeats):
        gc.collect()
        started = time.perf_counter()
        operation()
        samples.append((time.perf_counter() - started) * 1000)

    median_ms = statistics.median(samples)
    rate = None
    if workload_size is not None:
        rate = workload_size / (median_ms / 1000)

    return Measurement(
        name=name,
        category=category,
        median_ms=median_ms,
        minimum_ms=min(samples),
        maximum_ms=max(samples),
        samples_ms=samples,
        workload_size=workload_size,
        workload_unit=workload_unit,
        rate_per_second=rate,
    )


def _run_formatter_process(source: str) -> str:
    result = subprocess.run(
        [sys.executable, "-m", "sembrr"],
        cwd=ROOT,
        input=source,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    if not result.stdout:
        raise RuntimeError("cold formatter process returned no output")
    return result.stdout


def _recv_exact(connection: socket.socket, length: int) -> bytes:
    pieces: list[bytes] = []
    remaining = length
    while remaining:
        piece = connection.recv(remaining)
        if not piece:
            raise EOFError("connection closed before the frame was complete")
        pieces.append(piece)
        remaining -= len(piece)
    return b"".join(pieces)


def _run_resident_client(socket_path: Path, source: str) -> bytes:
    result = subprocess.run(
        [sys.executable, "-c", RESIDENT_CLIENT, str(socket_path)],
        input=source.encode(),
        capture_output=True,
        check=True,
        timeout=30,
    )
    if not result.stdout:
        raise RuntimeError("resident client returned no output")
    return result.stdout


def _measure_resident_round_trips(
    engine: object,
    source: str,
    *,
    repeats: int,
) -> Measurement:
    from sembrr.markdown import format_markdown
    from sembrr.models import BreakOptions

    errors: list[BaseException] = []
    ready = threading.Event()
    request_count = repeats + 1

    with tempfile.TemporaryDirectory(prefix="sembrr-benchmark-") as directory:
        socket_path = Path(directory) / "resident.sock"

        def serve() -> None:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                    listener.bind(str(socket_path))
                    listener.listen()
                    listener.settimeout(30)
                    ready.set()
                    for _ in range(request_count):
                        connection, _ = listener.accept()
                        with connection:
                            source_length = FRAME_LENGTH.unpack(
                                _recv_exact(connection, FRAME_LENGTH.size)
                            )[0]
                            request_source = _recv_exact(connection, source_length).decode()
                            result = format_markdown(
                                request_source,
                                engine,  # type: ignore[arg-type]
                                BreakOptions(),
                            ).encode()
                            connection.sendall(FRAME_LENGTH.pack(len(result)) + result)
            except BaseException as error:
                errors.append(error)
                ready.set()

        server = threading.Thread(target=serve, name="sembrr-benchmark-server", daemon=True)
        server.start()
        if not ready.wait(timeout=30):
            raise TimeoutError("resident benchmark server did not become ready")
        if errors:
            raise errors[0]

        measurement = _measure(
            "resident_prototype_310_words",
            "resident",
            lambda: _run_resident_client(socket_path, source),
            repeats=repeats,
            warmups=1,
            workload_size=len(source.split()),
            workload_unit="words",
        )

        server.join(timeout=30)
        if server.is_alive():
            raise TimeoutError("resident benchmark server did not stop")
        if errors:
            raise errors[0]
        return measurement


def _package_version(distribution: str) -> str:
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "not installed"


def _git_value(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _environment() -> dict[str, object]:
    thread_variables = {
        name: os.environ[name]
        for name in (
            "BLIS_NUM_THREADS",
            "MKL_NUM_THREADS",
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
        )
        if name in os.environ
    }
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "sembrr": _package_version("sembrr"),
        "spacy": _package_version("spacy"),
        "model": _package_version("en-core-web-sm"),
        "git_revision": _git_value("rev-parse", "--short", "HEAD"),
        "working_tree_dirty": bool(_git_value("status", "--porcelain")),
        "thread_environment": thread_variables,
    }


def _run_benchmarks(args: argparse.Namespace) -> list[Measurement]:
    measurements: list[Measurement] = []
    ordinary_small = _ordinary_document(5)

    if not args.skip_cold:
        measurements.append(
            _measure(
                "cold_process_310_words",
                "startup",
                lambda: _run_formatter_process(ordinary_small),
                repeats=args.cold_repeats,
                warmups=1,
                workload_size=len(ordinary_small.split()),
                workload_unit="words",
            )
        )

    from sembrr.candidates import spacy_optional_boundaries
    from sembrr.engine import SentenceEngine
    from sembrr.layout import select_breaks
    from sembrr.markdown import format_markdown, format_text
    from sembrr.models import BreakOptions

    engine = SentenceEngine()
    options = BreakOptions()

    for paragraphs in (5, 20, 200):
        source = _ordinary_document(paragraphs)
        words = len(source.split())
        measurements.append(
            _measure(
                f"warm_markdown_{words}_words",
                "warm",
                lambda source=source: format_markdown(source, engine, options),
                repeats=args.repeats,
                workload_size=words,
                workload_unit="words",
            )
        )

    markdown_heavy = _markdown_heavy_document()
    markdown_words = len(markdown_heavy.split())
    measurements.append(
        _measure(
            f"markdown_heavy_{markdown_words}_words",
            "markdown",
            lambda: format_markdown(markdown_heavy, engine, options),
            repeats=args.repeats,
            workload_size=markdown_words,
            workload_unit="words",
        )
    )
    measurements.append(
        _measure(
            f"markdown_projection_{markdown_words}_words",
            "markdown",
            lambda: format_markdown(markdown_heavy, NoopEngine(), options),
            repeats=args.repeats,
            workload_size=markdown_words,
            workload_unit="words",
        )
    )

    for requested_size in args.long_sizes:
        text = _long_sentence(requested_size)
        doc = engine._nlp(text)
        token_count = len(doc)
        boundaries = spacy_optional_boundaries(text, doc)
        measurements.append(
            _measure(
                f"long_sentence_candidates_{token_count}_tokens",
                "long_sentence",
                lambda text=text, doc=doc: spacy_optional_boundaries(text, doc),
                repeats=args.repeats,
                workload_size=token_count,
                workload_unit="tokens",
            )
        )
        measurements.append(
            _measure(
                f"long_sentence_layout_{token_count}_tokens",
                "long_sentence",
                lambda text=text, boundaries=boundaries: select_breaks(
                    text,
                    boundaries,
                    options,
                ),
                repeats=args.repeats,
                workload_size=token_count,
                workload_unit="tokens",
            )
        )

    largest_sentence = _long_sentence(max(args.long_sizes))
    largest_words = len(largest_sentence.split())
    measurements.append(
        _measure(
            f"long_sentence_end_to_end_{largest_words}_words",
            "long_sentence",
            lambda: format_text(largest_sentence, engine, options),
            repeats=args.repeats,
            workload_size=largest_words,
            workload_unit="words",
        )
    )

    if not args.skip_resident:
        if not hasattr(socket, "AF_UNIX"):
            raise RuntimeError("resident benchmark requires Unix-domain sockets")
        measurements.append(
            _measure_resident_round_trips(
                engine,
                ordinary_small,
                repeats=args.repeats,
            )
        )

    return measurements


def _print_human(environment: dict[str, object], measurements: Sequence[Measurement]) -> None:
    print("Sembrr performance benchmark")
    print(f"revision: {environment['git_revision']} (dirty={environment['working_tree_dirty']})")
    print(f"python: {environment['python']}  platform: {environment['platform']}")
    print(
        f"sembrr: {environment['sembrr']}  spaCy: {environment['spacy']}  "
        f"model: {environment['model']}"
    )
    if environment["thread_environment"]:
        print(f"thread environment: {environment['thread_environment']}")
    print()
    print(f"{'measurement':48} {'median':>10} {'range':>21} {'rate':>18}")
    print(f"{'-' * 48} {'-' * 10} {'-' * 21} {'-' * 18}")
    for measurement in measurements:
        timing_range = f"{measurement.minimum_ms:.2f}–{measurement.maximum_ms:.2f} ms"
        rate = ""
        if measurement.rate_per_second is not None:
            rate = f"{measurement.rate_per_second:,.0f} {measurement.workload_unit}/s"
        print(
            f"{measurement.name:48} {measurement.median_ms:9.2f} ms {timing_range:>21} {rate:>18}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    environment = _environment()
    measurements = _run_benchmarks(args)

    if args.json:
        print(
            json.dumps(
                {
                    "environment": environment,
                    "measurements": [asdict(measurement) for measurement in measurements],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        _print_human(environment, measurements)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
