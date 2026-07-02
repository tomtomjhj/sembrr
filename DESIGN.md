# Sembrr Design

Sembrr rewrites Markdown and plain text source
to add semantic line breaks without changing rendered Markdown.

## Source Preservation

Source preservation is a hard requirement.
Sembrr should change only whitespace needed for accepted line breaks.

The formatter must not round-trip Markdown through a renderer or serializer.
It rewrites the original source text directly,
using parser output only to find safe regions.

Protected source slices are restored byte-for-byte.
Protected slices include:

- Fenced and indented code blocks.
- Inline code spans.
- Links and images.
- Autolinks and raw URLs.
- HTML blocks and inline HTML.
- Tables.
- Front matter.
- Link reference definitions.

## Markdown Parsing

Sembrr uses tree-sitter for Markdown structure.
The block parser selects safe paragraph ranges.
The inline parser protects source spans such as code, links, autolinks,
images, and HTML tags.

GFM support is compatibility,
not permission to rewrite every GFM construct.
Tables and task-list markers are preserved.

Sembrr formats normal prose blocks:

- Paragraphs.
- Blockquote paragraphs.
- List item paragraphs.

Sembrr skips headings by default.
Headings are often intentionally one source line.

Sembrr also skips any block whose source mapping is uncertain.
A missed formatting opportunity is better than a bad rewrite.
This includes paragraphs with Markdown hard breaks
or multi-line protected inline spans.

## NLP Engine

Sembrr uses spaCy with `en_core_web_sm`.
The model provides sentence boundaries,
POS tags,
and dependency labels.

The default model is a project dependency.
Other requested models are hard runtime requirements.

Clause mode requires a model with the parser pipeline enabled,
because clause candidates depend on POS tags and dependency labels.

## Linebreaking Algorithm

Linebreaking has two phases:

1. Discover candidate breaks.
2. Choose which candidates to print.

Candidate discovery uses Markdown-safe spans and spaCy tokens.
It marks sentence boundaries as mandatory,
and it marks semicolon, colon, dash,
and dependency-based clause boundaries as optional.

Candidate selection is deterministic and greedy:

1. Always emit mandatory sentence breaks.
2. Consider optional breaks only when a segment exceeds `target_segment_chars`.
3. Reject candidates that create fragments shorter than `min_clause_chars`.
4. Pick the strongest safe candidate in the first over-target segment.
5. Prefer higher-confidence candidates of the same kind.
6. Use distance from `target_segment_chars` as the final tiebreaker.
7. Repeat until no over-target segment has a safe candidate.

Sembrr is not a width-based wrapper.
If a sentence is long and has no safe semantic break,
leave it long.

## Clause Mode

Clause mode prefers precision over recall.
A missed break is acceptable.
A bad break hurts trust.

Accepted candidates:

- After semicolons.
- Around dash interruptions.
- After colons that introduce an explanation.
- Before coordinating conjunctions when both sides contain finite verbs.
- Before subordinate clauses when both sides are long enough.

Rejected candidates:

- Inside protected source.
- Inside URLs or paths.
- Inside numbers or versions.
- Near very short fragments.

## Defaults

```text
mode = clause
parser = markdown
model = en_core_web_sm
target_segment_chars = 100
min_clause_chars = 24
```

## Guarantees

Tests cover these guarantees:

- Formatting is idempotent.
- No files are written by default.
- Code blocks are preserved byte-for-byte.
- Inline code is preserved byte-for-byte.
- Links and URLs are preserved byte-for-byte.
- Hard breaks are preserved.
- Tables are preserved byte-for-byte.
- Front matter is preserved byte-for-byte.
