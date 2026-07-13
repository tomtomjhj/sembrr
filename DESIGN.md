# Sembrr Design

Sembrr adds *semantic line breaks* to Markdown and plain text.
These breaks follow grammatical structure
while accounting for target line length.
In Markdown mode,
those breaks preserve rendered meaning.

## Key Ideas

Sembrr separates source safety,
linguistic analysis,
and line layout.
For each paragraph that can be changed safely,
it performs five steps:

1. Project source into prose.
   In Markdown mode,
   replace indivisible source ranges with single-token placeholders.
2. Ask spaCy for sentence boundaries and a dependency tree.
3. Treat sentence boundaries as mandatory
   and score every safe space between tokens as an optional boundary.
4. Select the lowest-cost complete line layout.
5. Map selected boundaries back to the original source.

A sentence remains on one line when it fits the target.
For a longer sentence,
low dependency-cut penalties favor boundaries between loosely connected phrases.
Line-length costs prevent those local scores
from deciding each break in isolation.

## Source Preservation

*Source preservation* limits changes outside inline code spans
to prose whitespace.
Inside an inline code span,
each line ending may become one ASCII space.

The formatter does not round-trip Markdown through a renderer or serializer.
It rewrites the original source directly,
using parser output to find safe ranges and source character positions.

Sembrr calls an indivisible Markdown source range an *atomic span*.
Atomic spans remain byte-for-byte unchanged,
except that Sembrr may replace each line ending inside an inline code span
with one ASCII space.
Surrounding code-span whitespace remains unchanged.
The formatter never inserts a break inside an atomic span.
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

Sembrr uses tree-sitter to select *format-safe paragraphs*.
These paragraphs have source positions
that Sembrr can map without ambiguity.
It formats paragraphs in normal flow,
blockquotes,
and list items.
It preserves list and blockquote prefixes on continuation lines.

Headings,
tables,
code blocks,
front matter,
and link reference definitions remain unchanged.

Some paragraph content also prevents formatting.
A *Markdown hard break* is a line ending explicitly marked to render as a break.
A paragraph containing one remains unchanged.
In an otherwise format-safe paragraph,
multiline inline code is normalized to one source line before analysis.
The paragraph remains unchanged
when any inline atomic span is still multiline after that normalization.

For inline formatting,
a *projected prose view* is a copy of the paragraph prepared
for *natural-language processing (NLP)*:

- Normal prose is copied.
- Emphasis and strikethrough delimiters are omitted.
- An inline atomic span becomes a collision-safe alphabetic *placeholder*.

Each placeholder is one NLP token.
Each projected character position maps back
to an original source character position.
Selected projected boundaries can therefore be applied to the source
without serializing Markdown syntax.

tree-sitter does not identify bare URLs as indivisible source ranges.
A small text matcher protects those URLs
and leaves their sentence punctuation outside the atomic span.

Plain text mode groups lines into paragraphs at blank lines.
Its prose projection is the input text itself,
so Markdown syntax has no special status.

## NLP Engine

Sembrr uses spaCy with `en_core_web_sm`.
The model provides sentence boundaries
and a dependency tree.

A *token* is a word,
punctuation mark,
or other text unit that spaCy analyzes.
A *dependency tree* connects tokens according to their grammatical relationships.
Each connection is a *dependency edge*.
For example,
in `the model runs`,
one edge connects `the` to `model`,
and another connects `model` to `runs`.

Installing Sembrr also installs the default model.
A model selected with `--model` must already be installed.
Every mode requires sentence boundaries.
Semantic and strict modes also require a *dependency parser*,
the model component that builds the dependency tree.

The formatter collects projected paragraphs before analysis.
`SentenceEngine` processes the batch with `nlp.pipe()`.
Model components unrelated to sentence and dependency analysis are excluded.

The scoring model is English-specific.
Selecting another spaCy model does not make the formatter language-independent.

## Boundary Discovery

### Candidate Boundaries

A *mandatory boundary* must appear in the output.
Sentence boundaries are mandatory.
A *token gap* is the whitespace between adjacent projected tokens.
An *optional boundary* is a token gap that the layout may select.
Inline atomic spans appear as single tokens,
so no optional boundary can occur inside them.

### Dependency-Cut Penalties

Each optional boundary receives a numeric *dependency-cut penalty*.
An edge crosses a token gap when its connected tokens lie on opposite sides.
If those tokens are `d` positions apart,
the edge contributes `1 / d²` to that token gap's penalty.

Short edges represent local grammatical cohesion
and contribute most to the penalty.
Long edges between clauses contribute less.
A low penalty therefore identifies a token gap that cuts little local structure.

A token gap after a preposition,
auxiliary,
conjunction,
determiner,
or particle receives one additional fixed penalty.
This penalty discourages those words from ending a line.
Other local grammatical relationships receive protection
from the inverse-square contributions of their dependency edges.

The scorer does not assign separate categories to semicolons,
dashes,
parentheticals,
subordinate clauses,
or coordination.
Those structures affect the shape of the dependency tree
and therefore the dependency-cut penalty.

### Scoring Exceptions

Most dependency edges contribute their normal penalty
wherever they cross a token gap.
Two edges are excluded at one token gap
because they would make a useful boundary look too expensive.
In the examples below,
`|` marks the token gap being scored.

Consider a token gap after punctuation:

`the check passes; | the release proceeds`

spaCy can attach the punctuation token to a word across that token gap.
That edge records where punctuation belongs in the parse.
It does not make the clauses more closely related.
When Sembrr scores the token gap immediately after punctuation,
the punctuation token's own edge does not contribute.

A *coordinating conjunction* joins parallel words,
phrases,
or clauses.
Now consider a token gap before one:

`the reader validates input | and records output`

spaCy connects `and` to the phrase before it
and labels that edge `cc`,
for coordinating conjunction.
That edge identifies the coordination
and therefore supports a break before the conjunction.
When Sembrr scores that token gap,
the conjunction token's own edge does not contribute.

Each exclusion applies only at the illustrated token gap.
The edge still contributes at any other token gap that it crosses,
and every other dependency edge keeps its normal penalty.
Removing one contribution lowers an optional boundary's penalty.
It does not make the boundary mandatory.

## Global Selection

For selection,
the paragraph start and end act like sentence boundaries.
The text between consecutive boundaries is a *sentence segment*.
Selection operates independently within each segment.
A segment that already fits `target_chars` remains on one line.

For a longer segment,
the start,
optional boundaries,
and end form a directed acyclic graph.
A graph edge represents one possible printed line.
Exact dynamic programming finds the minimum-cost path through that graph.

Every graph edge receives costs based on printed line length:

- *overflow cost*, based on the squared character count beyond `target_chars`;
- *shortfall cost*, based on the squared character count below `min_chars`;
- *raggedness cost*, based on unused space below `target_chars`.

A line that ends at an optional boundary also receives a fixed break cost
and that boundary's dependency-cut penalty.

Final-line underfill receives a larger raggedness cost
to avoid stranding a short sentence tail.
The minimum line length is soft,
so a strong boundary can produce a short but coherent line.

Semantic mode sums these costs directly.
Its overflow term is an ordinary squared cost,
so it can leave a slightly over-target line intact
when every available boundary is weak.

Strict mode compares paths first by total squared overflow,
then by the remaining layout cost.
This comparison selects a zero-overflow path whenever one exists.
An atomic span can still exceed the target.

The optimizer uses printed source lengths.
Markdown delimiters count toward the target
even though they are omitted or replaced in the NLP projection.

For `N` source characters and `B` optional boundaries in a sentence,
selection takes `O(N + B²)` time and `O(B)` extra space.
Dependency scoring is also at most quadratic in the sentence token count.
Typical use remains dominated by spaCy startup and parsing.

## Modes

- `sentence` emits only sentence boundaries.
- `semantic` uses dependency-cut penalties and soft length costs.
- `strict` enforces the target whenever safe boundaries permit.

## Defaults

```text
mode = semantic
input = Markdown
model = en_core_web_sm
target_chars = 88
min_chars = 24
```

## Guarantees

Tests cover these guarantees:

- Formatting is idempotent.
- The CLI reads stdin,
  writes stdout,
  and never edits input files.
- Atomic spans remain byte-for-byte unchanged,
  except for permitted multiline code-span normalization.
- Paragraphs remain unchanged when they contain a hard break
  or an inline atomic span that remains multiline after normalization.
- List and blockquote prefixes on continuation lines are preserved.
- Every selected optional boundary maps to source whitespace.

## References

These works provide background for the current design:

- Donald E. Knuth and Michael F. Plass,
  [Breaking Paragraphs into Lines](https://doi.org/10.1002/spe.4380111102),
  for global line-layout optimization.
- Jesús Calleja,
  Thierry Etchegoyhen,
  and David Ponce,
  [Automating Easy Read Text Segmentation](https://aclanthology.org/2024.findings-emnlp.694.pdf),
  for automatic semantic text segmentation.
- Yikang Shen and others,
  [Straight to the Tree: Constituency Parsing with Neural Syntactic Distance](https://aclanthology.org/P18-1108/),
  for syntax-derived boundary scoring.
