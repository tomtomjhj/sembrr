# sembrr

`sembrr` formats semantic line breaks in Markdown and plain text.
It is a Unix filter:
read stdin,
write stdout,
and never edit files in place.

The default mode keeps sentence boundaries
and adds conservative clause and phrase breaks inside long sentences.
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

Use clause mode for fewer breaks:

```sh
sembrr --mode clause < notes.md
```

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
