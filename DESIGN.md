# Sembrr Design

Sembrr rewrites Markdown and plain text source
to add semantic line breaks without changing rendered Markdown.

## Source Preservation

Source preservation is a hard requirement.
Sembrr should change only whitespace needed for accepted line breaks.

The formatter must not round-trip Markdown through a renderer or serializer.
It rewrites the original source text directly,
using parser output to find safe ranges and source offsets.

Inline formatting uses a projected prose view.
The projected text is the string passed to spaCy.
It omits Markdown emphasis delimiters,
and it replaces atomic source spans with placeholders.
Each projected offset maps back to an offset in the source text,
so selected line breaks are applied to the original source.

Atomic source spans are preserved byte-for-byte.
Atomic spans include:

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
The inline parser builds the projected prose view for each paragraph.

The inline projection handles three kinds of source:

- Normal prose is copied into the projected text.
- Emphasis, strong emphasis, and strikethrough delimiters are skipped.
- Code, links, images, autolinks, raw URLs, and inline HTML become atomic placeholders.

The projection keeps a source offset map.
When spaCy reports a break after projected text such as `Removed sentence.`,
the mapped source offset can land after Markdown closing delimiters,
such as the closing `~~` in `~~Removed sentence.~~`.

Link text remains atomic.
This keeps link syntax byte-for-byte stable,
and it avoids line breaks inside link labels or destinations.

Bare URLs still need a small text matcher.
Tree-sitter recognizes autolinks such as `<https://example.com>`,
but it does not expose bare `https://example.com` text as an inline node.

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
or multi-line atomic inline spans.

## NLP Engine

Sembrr uses spaCy with `en_core_web_sm`.
The model provides sentence boundaries,
POS tags,
and dependency labels.

The default model is a project dependency.
Other requested models are hard runtime requirements.

Clause, phrase, and strict modes require a model with the parser pipeline enabled,
because their candidates depend on POS tags and dependency labels.

spaCy cold start dominates short interactive runs.
Importing spaCy and loading the model costs far more than formatting
a small Markdown selection.
Sembrr excludes unused model components such as NER and lemmatization,
but a fresh CLI process should still expect noticeable startup latency.

## Linebreaking Algorithm

Linebreaking has five phases:

1. Project source to prose text.
2. Discover candidate breaks in the projected text.
3. Convert candidates into ranked layout breakpoints.
4. Choose which breakpoints to print.
5. Map selected break offsets back to source offsets.

Candidate discovery uses projected prose and spaCy tokens.
It marks sentence boundaries as mandatory,
and it marks semicolon, colon, dash,
and dependency-based clause boundaries as optional.
Phrase and strict modes also mark selected phrase boundaries as optional.
Strict mode also permits fallback comma and word-boundary breakpoints.

Candidate selection uses source offsets.
Segment length checks include Markdown marker characters,
so `target_segment_chars` describes the source line that will be printed,
not only the prose seen by spaCy.

The selector is a ranked breakpoint pass.
Sentence breaks are mandatory.
Other breakpoints are optional,
and the active mode controls which levels are available:

- Semantic breakpoints use clause and phrase priorities.
  They must satisfy `min_clause_chars`.
- Strict comma fallback breakpoints reuse comma phrase candidates
  after semantic breakpoints fail.
- Strict word fallback breakpoints are generated from word boundaries.
  They are last resort breakpoints.

Candidate selection is deterministic and greedy:

1. Always emit mandatory sentence breaks.
2. Find the first segment that exceeds `target_segment_chars`.
3. Choose the highest-ranked eligible breakpoint in that segment.
4. Prefer stronger semantic kinds before weaker semantic kinds.
5. Prefer higher confidence inside the same semantic kind.
6. Prefer fallback breakpoints before the target when possible.
7. Repeat until no over-target segment has an eligible breakpoint.

The current selector is not a linear Oppen pretty printer.
It repeatedly finds the first over-target segment
and scans ranked breakpoints for that segment.
In strict mode, word boundaries can make the breakpoint set proportional to input length,
so pathological paragraphs can take quadratic time or worse.
Interactive use is normally dominated by spaCy startup and parsing,
but the selector should be improved before treating strict mode as a general wrapper.

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
- Before or after matched parenthetical spans.
- Before coordinating conjunctions when both sides contain finite verbs.
- Before comma-led spans that spaCy parses as standalone finite clauses.
- Before subordinate clauses when both sides are long enough.

Rejected candidates:

- Inside atomic source spans.
- Inside matched parenthetical spans.
- Inside URLs or paths.
- Inside numbers or versions.
- Near very short fragments.

## Phrase Mode

Phrase mode adds more breaks inside long sentences.
It keeps clause mode behavior
and adds weaker phrase-level candidates.

Accepted phrase candidates:

- Before example phrases such as `like ...` or `including ...`.
- Before coordinated gerund phrases such as `or splitting ...`.
- Before bare coordinating conjunctions
  when the following conjunct has its own subject and finite verb.
- Before non-comma-led coordinated noun phrase tails.
- Before infinitive and participial phrase tails.
- After commas as a last-resort phrase boundary.

Phrase candidates are lower-priority because they are not full clauses.
They still must satisfy the same fragment-length checks as clause candidates.
They are not added inside matched parenthetical spans.

## Strict Mode

Strict mode uses phrase mode candidates first.
If any segment still exceeds `target_segment_chars`,
it tries remaining comma phrase candidates,
then adds breaks at word boundaries.
Protected Markdown atoms stay indivisible,
so an atom longer than `target_segment_chars` can still produce a longer line.

## Defaults

```text
mode = phrase
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
- Emphasis and strikethrough markers are preserved.
- Hard breaks are preserved.
- Tables are preserved byte-for-byte.
- Front matter is preserved byte-for-byte.
