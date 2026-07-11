# Sembrr Design

Sembrr rewrites Markdown and plain text source
to add semantic line breaks without changing rendered Markdown.

## Source Preservation

Source preservation is a hard requirement.
Sembrr changes only whitespace used for accepted line breaks.

The formatter does not round-trip Markdown through a renderer or serializer.
It rewrites the original source directly,
using parser output to find safe ranges and source offsets.

Atomic Markdown spans remain byte-for-byte unchanged.
They include:

- Fenced and indented code blocks.
- Inline code spans.
- Links and images.
- Autolinks and raw URLs.
- HTML blocks and inline HTML.
- Tables.
- Front matter.
- Link reference definitions.

## Markdown Parsing

Sembrr uses tree-sitter to select format-safe Markdown paragraphs.
It formats paragraphs in normal flow,
blockquotes,
and list items.
It preserves the source prefixes required for continuation lines.

Headings,
tables,
code blocks,
front matter,
and link reference definitions remain unchanged.
A paragraph also remains unchanged when it contains a Markdown hard break
or a multiline atomic inline span.

Inline formatting uses a projected prose view for NLP analysis:

- Normal prose is copied.
- Emphasis and strikethrough delimiters are omitted.
- Atomic inline spans become collision-safe alphanumeric placeholders.

Each atomic placeholder is one NLP token.
Each projected offset maps back to an original source offset.
Selected projected boundaries can therefore be applied to the source
without serializing Markdown syntax.

The inline grammar does not expose bare URLs as atomic nodes.
A small text matcher protects those URLs
and leaves their sentence punctuation outside the protected span.

Plain text mode groups lines into paragraphs at blank lines.
It uses an identity projection,
so Markdown syntax has no special status.

## NLP Engine

Sembrr uses spaCy with `en_core_web_sm`.
The model provides sentence boundaries,
and a dependency tree.

The default model is a project dependency.
Another requested model is a hard runtime requirement.
Semantic and strict modes require a pipeline with a dependency parser.

The formatter collects projected paragraphs before analysis.
`SentenceEngine` processes the batch with `nlp.pipe()`.
Unused NER and lemmatizer components are excluded.

The scoring model is English-specific.
Selecting another spaCy model does not make the formatter language-independent.

## Boundary Discovery

Sentence boundaries are mandatory.
Every whitespace gap between adjacent projected tokens is an optional boundary.
Protected Markdown spans appear as single tokens,
so no optional boundary can occur inside them.

Each optional boundary receives one numeric dependency-cut penalty.
For every dependency edge that crosses the gap,
the penalty adds the inverse square of the edge's token length.

Short edges represent local grammatical cohesion
and contribute most to the penalty.
Long clause-level attachments contribute less.
A low penalty therefore identifies a gap that cuts little local structure.

The same calculation applies to every dependency edge.
One additional penalty prevents a leading function word from ending a line.
It applies to closed-class parts of speech as a group,
without dependency-label or lexical cases.
Other determiner,
modifier,
auxiliary,
and object attachments receive protection from their tree locality.

The scorer does not identify semicolons,
dashes,
parentheticals,
subordinate clauses,
or coordination as separate candidate kinds.
Those structures affect the dependency topology
and therefore the shared numeric score.

## Global Selection

Selection operates independently within each mandatory sentence segment.
A segment that already fits `target_segment_chars` remains flat.

For a longer segment,
the start,
optional boundaries,
and end form a directed acyclic graph.
An edge represents one printed segment.
Exact dynamic programming finds the minimum-cost path through that graph.

The cost of each segment combines:

- squared overflow beyond `target_segment_chars`;
- squared shortfall below `min_segment_chars`;
- raggedness costs for underfilled segments;
- a fixed break cost;
- the dependency-cut penalty.

Semantic mode sums these costs directly.
Strict mode compares paths first by total squared overflow,
then by the remaining layout cost.

Final underfill receives a larger cost
to avoid stranding a short sentence tail.
The minimum segment length is soft,
so a strong boundary can produce a short but coherent segment.

Semantic mode gives overflow a normal squared cost.
It can leave a slightly over-target segment intact
when every available boundary is weak.
Strict mode selects a zero-overflow path whenever one exists.
An indivisible Markdown atom can still exceed the target.

The optimizer uses printed source lengths.
Markdown delimiters count toward the target
even though they are omitted or replaced in the NLP projection.

For `N` source characters and `B` optional boundaries in a sentence,
selection takes `O(N + B²)` time and `O(B)` extra space.
Dependency scoring is also at most quadratic in the sentence token count.
Typical use remains dominated by spaCy startup and parsing.

## Modes

- `sentence` emits only sentence boundaries.
- `semantic` uses syntax scores and soft length costs.
- `strict` enforces the target whenever safe boundaries permit.

## Defaults

```text
mode = semantic
input = Markdown
model = en_core_web_sm
target_segment_chars = 88
min_segment_chars = 24
```

## Guarantees

Tests cover these guarantees:

- Formatting is idempotent.
- No files are written by default.
- Atomic Markdown syntax remains byte-for-byte unchanged.
- Hard breaks and uncertain multiline inline source remain unchanged.
- Structural continuation prefixes are preserved.
- Every optional break maps to source whitespace.

## References

- Donald E. Knuth and Michael F. Plass,
  [Breaking Paragraphs into Lines](https://doi.org/10.1002/spe.4380111102).
- Jesús Calleja,
  Thierry Etchegoyhen,
  and David Ponce,
  [Automating Easy Read Text Segmentation](https://aclanthology.org/2024.findings-emnlp.694.pdf).
- Yikang Shen and others,
  [Straight to the Tree: Constituency Parsing with Neural Syntactic Distance](https://aclanthology.org/P18-1108/).
