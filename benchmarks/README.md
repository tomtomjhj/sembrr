# Performance Benchmarks

Run the complete benchmark from the repository root:

```sh
uv run python benchmarks/benchmark.py
```

The benchmark reports medians and the range of raw timing samples.
It covers these paths:

- A fresh Python process that loads the model and formats non-empty Markdown.
- Warm end-to-end formatting at 310, 1,240, and 12,400 words.
- Markdown-heavy end-to-end formatting and projection without NLP analysis.
- Candidate scoring and layout selection for increasingly long sentences.
- End-to-end formatting of the largest requested long sentence.
- A resident prototype with a preloaded engine,
  a temporary Unix socket,
  and one fresh Python client process per request.

The cold samples use separate Python processes
after one untimed process has warmed the filesystem cache.
The warm samples reuse one `SentenceEngine`.
The long-sentence candidate and layout samples reuse a parsed spaCy document,
so they measure Sembrr's algorithms rather than model inference.

The resident measurement is a transport and lifecycle baseline.
Its small length-prefixed protocol is local to the benchmark
and is not a proposed public service protocol.

Use fewer samples for a smoke check:

```sh
uv run python benchmarks/benchmark.py \
  --repeats 1 \
  --cold-repeats 1 \
  --long-sizes 50
```

Emit raw samples and environment details as JSON
for storage or comparison:

```sh
uv run python benchmarks/benchmark.py --json > benchmark.json
```

Useful controls include:

- `--repeats N` for warm and resident samples.
- `--cold-repeats N` for fresh-process samples.
- `--long-sizes N ...` for long-sentence word counts.
- `--skip-cold` when investigating warm code only.
- `--skip-resident` when Unix-domain sockets are unavailable.

Compare results only across similar machines and runtime conditions.
Record CPU power policy and thread-related environment variables,
and leave the machine otherwise idle.
The benchmark records package versions,
the Git revision,
working-tree state,
platform information,
logical CPU count,
and common numerical-library thread variables.

The script does not enforce performance thresholds.
Use repeated before-and-after runs to decide whether a change is meaningful.
