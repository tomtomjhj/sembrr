> [!NOTE]
> This is mostly AI-generated.

# sembrr

`sembrr` is a Unix filter that formats Markdown and plain text
with [semantic line breaks](https://sembr.org/).
It breaks paragraphs at sentence boundaries.
When a sentence exceeds the target line length,
it uses spaCy's syntax analysis to choose additional breaks.

It's like [sembr](https://github.com/admk/sembr),
but without fine-tuned transformer model.
Its break choices are probably less refined,
but they work well enough for my main use case:
formatting arbitrarily formatted Claude-generated prose
before reading and revising it in Vim.

## Installation

From a local checkout,
install the command onto your `PATH` with uv:

```sh
uv tool install .
```

`uv tool` installs executables into `uv tool dir --bin`.
Make sure that directory is on your `PATH`.

## Usage

Format Markdown from stdin:

```sh
sembrr < notes.md
```

Use plain text parsing:

```sh
sembrr --text < notes.txt
```

Use sentence-only mode:

```sh
sembrr --mode sentence < notes.md
```

Use strict mode to enforce `--target-chars`
at safe token boundaries when semantic mode permits an overlong line:

```sh
sembrr --mode strict --target-chars 80 < notes.md
```

Use `--min-chars` to discourage short lines.
The minimum is a soft preference,
so a strong syntactic boundary can still produce a shorter line.
When omitted,
the minimum defaults to 24 or `--target-chars`,
whichever is lower.
The minimum cannot exceed `--target-chars`.

## Exit Status

`sembrr` exits with status 0 after writing its output
or when a downstream command closes the pipe early.
It exits with status 2 for invalid arguments
or an unavailable spaCy model,
and with status 130 after an interrupt.

## Development

```sh
uv sync
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run python -m unittest discover -s tests
```

See [DESIGN.md](DESIGN.md) for source-preservation rules
and line-breaking policy.
