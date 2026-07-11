# sembrr

`sembrr` formats semantic line breaks in Markdown and plain text.
It is a Unix filter:
read stdin,
write stdout,
and never edit files in place.

The default mode keeps sentence boundaries
and adds syntax-scored breaks inside long sentences.
It is not a width-based wrapper.

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

Use strict mode to enforce `--target-segment-chars`
at safe token boundaries when semantic mode permits an overlong segment:

```sh
sembrr --mode strict --target-segment-chars 80 < notes.md
```

Use `--min-segment-chars` to discourage short lines.
The minimum is a soft preference,
so a strong syntactic boundary can still produce a shorter segment.

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
