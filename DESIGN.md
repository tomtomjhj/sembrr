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

The formatter collects projected paragraphs before analysis.
The spaCy engine processes those paragraphs through `nlp.pipe()` as one batch.
Alternative engines can implement the batch interface,
or rely on the per-paragraph compatibility path.

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

The selector is a fit-based breakpoint pass.
Its model is the traditional pretty-printing `group`:
a group stays flat when it fits,
and otherwise its breakpoints become available while nested groups decide inside it.
Wadler presents this as an algorithm equivalent to Oppen's printer,
and the PrettyExpressive survey classifies Oppen-style printers
as the traditional group-based pretty-printing language.
Sentence breaks are mandatory.
Other breakpoints are optional,
and the active mode controls which levels are available:

- Semantic breakpoints use clause and phrase priorities as nesting levels.
  A stronger level splits a long segment before weaker levels run inside the pieces.
  Authored separators such as semicolons are stronger than inferred coordination.
- Comma fallback breakpoints reuse comma phrase candidates
  after semantic breakpoints fail.
  Phrase mode keeps the normal `min_clause_chars` check.
  Strict mode can use short comma fragments.
- Strict word fallback breakpoints are generated from word boundaries.
  They are the final level.

Candidate selection is deterministic and greedy:

1. Always emit mandatory sentence breaks.
2. Start each mandatory segment at the strongest semantic level.
3. Keep a segment flat when its printed source length fits `target_segment_chars`.
4. At the current level,
   choose the last eligible breakpoint whose left side still fits.
5. If no breakpoint fits before the target,
   choose the first eligible breakpoint after the target.
6. Split the segment at that breakpoint,
   then retry the same level inside both resulting chunks.
7. If the current level has no eligible breakpoints,
   try the next weaker level on the same segment.
8. Stop when a segment fits,
   or when no lower level exists.

The selector uses Oppen-style grouping,
but it is not a complete streaming Oppen printer.
Classic Oppen printers stream a document with explicit group and break commands.
Sembrr already has the full text,
the parser output,
and a flat set of ranked source offsets.
Its hierarchy comes from priority levels:
stronger breaks partition the segment,
and weaker breaks are considered only inside those partitions.
Same-level breakpoints use a fill-style decision:
the selector keeps earlier breakpoints flat while the line still fits,
so a later breakpoint wins when it gives a better filled line.
This matters for paired boundaries such as parentheticals,
where `prefix (details)` should stay flat when it fits
and the newline should fall after the closing parenthesis.

The selector indexes breakpoints by level and source offset.
Each level uses offset lookup and binary search
to find the breakpoints that satisfy fragment-length constraints
and the target line length.
After candidate discovery,
the selector is `O(n + P log P + S log S + B log B)`,
where `n` is the source length,
`P` is the number of protected Markdown spans,
`S` is the number of mandatory sentence breaks,
and `B` is the number of optional breakpoints,
including generated strict word-boundary breakpoints.
Space use is `O(n + S + B)`.
Interactive use is normally dominated by spaCy startup and parsing,
but large-document use should profile the selector separately.

References:

- Philip Wadler,
  [A prettier printer](https://homepages.inf.ed.ac.uk/wadler/papers/prettier/prettier.pdf).
- Sorawee Porncharoenwase,
  Justin Pombrio,
  and Emina Torlak,
  [A Pretty Expressive Printer](https://arxiv.org/pdf/2310.01530).

Sembrr is not a width-based wrapper.
If a sentence is long and has no safe semantic break,
leave it long.

## Clause Mode

Clause mode prefers precision over recall.
A missed break is acceptable.
A bad break hurts trust.

Accepted candidates:

- After semicolons,
  including inside matched parenthetical spans.
- Around dash interruptions.
- After colons that introduce an explanation.
- Before or after matched parenthetical spans.
- Before coordinating conjunctions when both sides contain finite verbs.
- Before comma-led spans that spaCy parses as standalone finite clauses.
- Before subordinate clauses when both sides are long enough.

Rejected candidates:

- Inside atomic source spans.
- Weaker candidates inside matched parenthetical spans.
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
