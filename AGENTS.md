# Project Guidance

## Project Status

Sembrr is an unreleased prototype.
Optimize for a simple current design,
not compatibility with earlier internal versions.

- Change internal and public-looking APIs directly when the design improves.
- Delete obsolete code instead of adding adapters, deprecations, migration paths,
  compatibility fallbacks, or parallel interfaces.
- Accept implementation churn when it produces a smaller and clearer system.
- Do not add abstractions for hypothetical downstream users.
- Do not add release machinery until release work is explicitly requested.

Use the smallest implementation that satisfies the current requirement.
Explain behavior only when the explanation helps a user make a decision
or avoid a likely mistake.

## Product Invariants

Sembrr is a Unix filter.
It reads stdin,
writes stdout,
and does not edit input files in place.

Markdown formatting must preserve rendered meaning.
Atomic Markdown spans remain byte-for-byte unchanged,
except that each line ending inside an inline code span may become one ASCII space.
The formatter never inserts a break inside an atomic span,
and a paragraph with uncertain source mapping remains unchanged.
Plain-text mode uses an identity prose projection.
Markdown syntax has no special status in that mode.

The candidate rules are English-specific.
Do not imply that selecting an arbitrary spaCy model
makes the formatter language-independent.

Native Markdown parser defects belong in the parser.
Do not add heuristic input scanners or nesting limits
to hide crashes in `tree-sitter-markdown`.
Use a dependency fix, pin, or upstream report instead.

The treatment of existing prose soft breaks and surrounding whitespace
is still a product decision.
Inline code span line endings follow the normalization contract above.
Do not broaden that behavior without defining the preservation contract first.

## Architecture

Keep responsibilities aligned with the current modules:

- `models.py` defines shared formatter types and validated options.
- `engine.py` owns the engine contract and spaCy integration.
- `candidates.py` discovers semantic break candidates.
- `layout.py` selects and applies ranked breakpoints.
- `protect.py` projects Markdown inline source into prose.
- `markdown.py` finds format-safe blocks and coordinates batch analysis.
- `breaks.py` is the small public facade.

`BreakEngine` exposes single-text and batch analysis directly.
`SentenceEngine` implements batch analysis with `nlp.pipe()`.
Do not add optional batch protocols,
runtime capability detection,
or compatibility dispatchers.

Keep the CLI model lifecycle simple.
Do not add lazy model loading,
a daemon,
or another long-lived process unless explicitly requested.

## Debugging Formatting Decisions

Reproduce an unexpected break with the exact input,
options,
and spaCy model.
Inspect the formatter stages in order:

1. Check the prose sent to the engine.
   Paragraph preparation collapses existing prose soft breaks before analysis,
   so a break that appears in both input and output may have been selected again.
2. Inspect spaCy tokens,
   sentence boundaries,
   part-of-speech tags,
   dependency labels,
   and dependency heads.
3. List every candidate's source offset,
   penalty,
   mandatory status,
   and selection status.
   For a surprising penalty,
   identify each dependency edge that crosses the gap
   and its inverse-square contribution.
   Also check the left-token function-word penalty.
4. Inspect the complete selected path.
   Record its printed line lengths and layout cost,
   then compare it with the closest plausible competing path.
   A low candidate penalty does not explain a break by itself
   because `layout.py` optimizes the whole sentence.

Use the first stage that produces the unexpected result
to locate the problem:

- projection and source mapping belong in `protect.py` or `markdown.py`;
- sentence and dependency parses belong in `engine.py` or the spaCy model;
- candidate eligibility and syntax penalties belong in `candidates.py`;
- path selection and line-length tradeoffs belong in `layout.py`.

When reporting the result,
distinguish a parser error from a scoring limitation
and a scoring limitation from a layout tradeoff.
Include the effective mode,
target,
minimum,
and model when they affect the explanation.

## Tests and Commits

Run the complete verification set after code changes:

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run python -m unittest discover -s tests
```

Add focused tests for behavior and source-preservation invariants.
Avoid tests that only restate straightforward dataclass
or argument-parser validation.

Each requested item gets its own focused commit.
Do not bundle independent items.
When follow-up feedback changes an item,
amend that item's commit and replay later commits as needed.

## Writing

Describe the current system.
Include history only when it explains compatibility,
migration,
or a design constraint that still matters.
Use semantic line breaks in Markdown prose.
Avoid explanations that merely restate an obvious command or option.

## Commit message
```
type(scope): subject

Problem:
...

Solution:
...
```

* subject
  * For "fix" type, the subject should give a insightful description of the bug being fixed
  * Indicate breaking API change like this: `type(scope)!: subject`
* body
  * hard-wrap at 72 characters
  * Solution section does not need to talk about the added tests unless they are the main point of the change (in that case it maybe worth adding a separate commit for that).
