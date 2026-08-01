# REFERENCE_POINTS — the citation grammar (canonical spec)

This is the design reference for the `reference-points` engine. The README is the
user-facing quick start; this doc is the normative grammar + the resolved design
decisions + the worked example the golden test reproduces.

## Purpose

Point at the *exact* object in a chat message — a table row, a sentence — with an
address that **resolves exactly or fails loudly**. The failure mode this exists to
prevent is *silent mis-resolution*: a prose pointer ("that second table") that each
side resolves to a different object. An address is mechanical; a bad one is rejected
with a named reason.

## The single primitive

One deterministic function, `decompose(markdown) -> Message`, segments a message
into `Section → Entity → Location`. Everything else is a view or a query over that
one tree:

- **label** a message = decompose + `render_inline`
- **resolve** an address = decompose + `parse_ref` + walk
- **overlay** = decompose + `render_map`

Because the *same* decomposition backs both labeling and resolution, a label the
renderer emits and the address the resolver computes are identical **by
construction** — they cannot drift.

Block structure comes from `markdown-it-py`, a CommonMark parser, configured once
as `MarkdownIt("commonmark").enable("table").disable("inline")` with no knob and
no second decomposer to disagree with. `decompose` maps its token stream onto the
entity alphabet, so setext headings, loose lists, lazy continuation, nesting depth
and link reference definitions are the parser's problem rather than rediscovered
one bug at a time. Adding a construct is a row in that mapping.

## Grammar

```
address := N <n> [ "-" S <n> ] { "." entity } [ "." location ]
```

An address reads **turN · Section · Entity · Location**: `N27-S1.T2.3`.

| Part | Form | Rule |
|------|------|------|
| turn | `N<n>` | **mandatory** unless the reader supplies it — see below |
| section | `S<n>` | optional; whole message is `S1` when it has no headings |
| entity | `<Letter><n>` | indexed **per type within its section**: `T2` = 2nd table |
| location | see below | legal shape depends on the terminal entity's type |

A location attaches only to the **terminal** entity in the path. Container
entities (`S`, `Q`) nest: `N1-S1.Q1.P1.2` = turn 1, section 1, blockquote 1,
its paragraph 1, sentence 2.

### The turn is mandatory in prose, not in a call

An address written down has to name its turn, or it means different things in
different weeks — that is the whole reason `N` exists. But a caller resolving an
address is *holding the message*, so it already knows which turn that is:
`parse_ref(raw, turn=…)` accepts a turn-less address and `decompose(md, turn=…)`
records the answer on the `Message`. Two things follow, and both are load-bearing:

1. **The fragments `render_inline` emits resolve as written.** A block label is a
   fragment by design (`.P1`, `·T2`) — only a section header carries the full
   prefix. Without a supplied turn those labels are unresolvable without being
   re-typed, which breaks the round-trip the whole engine rests on.
2. **An address for another turn is a miss.** `ref.turn` used to be parsed and
   discarded, so `N27-S1.P1` resolved happily against turn 5's message and
   returned turn 5's first paragraph — silent mis-resolution, arriving through
   the one component that exists to prevent it.

### Entity alphabet

| Letter | Entity | Location | Notes |
|--------|--------|----------|-------|
| `P` | Paragraph | `.<sentence>` | sentence index within the paragraph |
| `T` | Table | `.<row>` · `.<row>,<col>` · `.,<col>` | row, cell, or whole column |
| `L` | List | `.<item>` | item index |
| `C` | Verbatim block | `.<line>` | fenced, indented, or raw HTML; `\n`-delimited logical line |
| `Q` | Quote | *(container)* | blockquote; nests inner entities |
| `S` | Subsection | *(container)* | markdown heading, ATX or setext; nests |
| `D` | Diagram | `.<line>` | a mermaid/dot fence is a fence: same shape as `C` |
| `R` | Reference | **none** | link reference definition; addressable, never labeled inline |

### Match strings (address by content instead of index)

- `(/text/)` — the **single** match in scope; >1 match → `AMBIGUOUS`.
- `(g/text/)` — **every** match in scope.

E.g. `N27-S1.T2.(/Team/)` = the row in table 2 that uniquely contains "Team".

A match may also stand in for an entity's **index**, naming *which* entity the
address means rather than a location within one: `N1-S1.S(/Costs/)` is the
subsection headed Costs, `N1-S1.P(/caching/)` the paragraph about caching. A
section matches on its heading as well as its body — the heading is what a reader
names it by. This is the same `(/…/)` syntax, so it falls out for every letter and
for `g`: `N1-S1.P(g/pricing/)` is **every** matching paragraph, joined, exactly as
a global location returns every row. A selector takes no further location, having
spent itself on the choice.

An `R` selector matches against the definition's whole text — key, destination and
title — so `(/mdit/)` finds it by key and `(/github.com/)` by URL, with no special
case for either. Key matching follows CommonMark label normalization
(case-insensitive, internal whitespace collapsed), which is what makes `[MDIT]`,
`[ mdit ]` and `[mdit]` one reference. Lookup is section-scoped, like every other
entity.

## Resolved open questions

1. **Build the parser?** Yes — this engine.
2. **Diagram location (`D.L`)?** A **line**, the same as `C`. This reversed an
   earlier "undefined", taken before `C` existed: a mermaid or dot fence *is* a
   fenced block whose content is preserved exactly, so the coordinate a reader
   has is the line. `R` is now the only letter with no location, because a link
   reference definition renders to nothing there is anything to point into.
3. **Nesting depth / does the index reset?** Arbitrary nesting; a location
   attaches only to the terminal entity, so "reset per level" is a non-issue.
4. **Do lists / code / quotes get letters?** Yes: `L`, `C`, `Q` added to the
   spec's `T·D·P·S`. **No `H` (raw-HTML) entity** — `C` is the *verbatim block*
   entity and raw HTML is one, alongside fenced and indented blocks. All three
   share the property that decides the location shape: their content is
   preserved exactly, so the coordinate is a **line**, never a sentence. An HTML
   `<table>` maps onto `T` (parsing TODO).
5. **Label density?** Every substantive block is addressable. A **thematic break**
   (`---`, `***`, `___`) is the exception: it is a visual rule with no content to
   address, so it is not an entity and carries no label. A **link reference
   definition** is the converse exception — addressable as `R<n>` but *never*
   labeled inline, the only entity of which that is true. The definition renders
   to nothing, so an inline label would put visible text where the reader saw
   none, and it would stop the line being a definition, turning every `[key]` in
   the labeled copy into literal text. `render_inline` leaves those lines
   byte-identical to the source; `render_map` carries their addresses.
6. **Rejection UX?** Fail loud, name the defect, **say what to type instead**,
   wait — never guess. Every failure has three parts:

   ```
   MISSING: no such row 9 in T1
     -> T1 has 4 rows, counting the header as row 1
   ```

   The **category** lets a caller sort the four apart without parsing prose:
   `REJECTED:` (the address breaks the grammar, or the shape it landed on),
   `INVALID:` (the address is fine, its regex is not), `MISSING:` (well-formed,
   nothing there), `AMBIGUOUS:` (well-formed, more than one thing there). The
   **hint** is what turns a rejection into the next address, so it is a required
   constructor argument on both `RefError` (always `REJECTED`) and `ResolveError`
   — a new message cannot ship uncategorized or unhelpful. Where the engine knows
   the answer it gives it: what is in scope for a missing entity, how many rows a
   table has, the legal location shape for that entity's letter. An `AMBIGUOUS`
   lists the candidates themselves, capped at eight, because choosing between them
   is impossible without seeing them. The CLI prints it unchanged and exits 1 — a
   file it cannot read is `UNREADABLE:`, outside the four, being no address defect.

## Not built: transcript mode

Everything above works on **one message at a time**. `decompose(md, turn=27)` is
handed the text and told which turn it is, which makes `N` a *check* rather than a
*lookup*: it catches an address aimed at another turn, but it cannot go and find
that turn. Reading a whole transcript is the obvious next step, and is
deliberately not built. Roughly what it needs:

- **A transcript reader.** There is no format here, and choosing one is the real
  decision — the engine has no opinion about how a conversation is stored and
  should not grow one casually.
- **Resolution across turns.** `resolve` picking the message by `ref.turn`
  instead of being handed it. At that point `N` does the job it was designed for
  and a bare `N27-S1.P1` is complete on its own, with no `--turn` beside it.
- **A viewer.** Labels are worth nothing you cannot see. A per-message
  `render_inline` does not give you a labeled conversation to read and point into,
  and that is where most of the value is.

None of this changes the grammar, which is why it is a note and not a design.
Nothing has been built toward it: `Message.turn` is the only piece already in
place, and it is there because the wrong-turn check needs it today, not as a hook
for this.

## Rendering model (why source-parsing is sound)

Everything the assistant writes is GitHub-flavored markdown rendered in a
terminal. The decomposer parses the **markdown source**, and that is correct
because GFM rendering **preserves block-level structure**: `#`→section,
blank-line-delimited prose→paragraph, `|`→table row, fence→code line,
`>`→blockquote, `-`/`1.`→list item. The blocks the decomposer sees are the blocks
the reader's eye lands on.

Source vs. rendered diverges only at the **inline/character** level (soft-wrap,
`**bold**` markers, link syntax). Every location is block-or-above **except**
`P.<sentence>`, and sentences are computed on the paragraph's *logical joined
text* (what the reader reads), so the grammar never crosses the divergence line.

## Label rendering

Two tiers, independent of the marker set:

| Where | Rule |
|-------|------|
| section header | the **full prefix**, then the heading text, no dash between identifier and content |
| every other block | only the **relevant fragment**, never the full path |

Full paths are for *references*; fragments are for *labels*.

### A labeled message must still render as markdown

Labels are added to the source; they must never change what it renders to. Two
rules follow, and both are load-bearing:

1. **Heading markers are preserved.** An ATX section label rebuilds the line with
   its original markers — `## N27-S1 Costs`, not `N27-S1 Costs`. Dropping them
   collapses every heading in the message into a paragraph. A **setext** heading
   is labeled by *prefix* instead: the label joins the heading's first line and
   the `===` / `---` underline is left untouched. Rebuilding would strand the
   underline, and on a multi-line setext heading it would duplicate the text.
   This is why `Section` carries `markup` (the literal marker) alongside `level`:
   `level` is not derivable from it, since a setext **h2** has `markup == '-'`.
2. **A position-sensitive first line gets its label on its own line, followed by
   a blank line.** A paragraph label is normally an inline prefix, but an
   indented code block, a thematic break (`---`, `***`, `___`), and the start of
   an HTML block all mean what they mean *because of* their leading characters.
   Prefixing destroys them. The blank line matters as much as the placement:
   without it the construct below becomes a lazy continuation of the label's
   paragraph, which turns `---` into a setext heading and an indented block into
   prose.

Verified by rendering the source and the labeled copy through a GFM renderer and
diffing the block skeletons.

**Marker set is an option.** ASCII is the default; `--glyphs` selects the
monochrome set — no color, no emoji. Redundant role letters are dropped in the
glyph form (`◆27`, not `◆N27`).

| Role | ASCII | Glyph |
|------|-------|-------|
| turn | `N` | `◆` |
| section | `-S` | `§` (space-separated) |
| entity | `.` | `·` |

| Style | Section header | Block |
|-------|----------------|-------|
| ASCII | `N27-S1 Costs` | `.P1` · `.T1` |
| glyph | `◆27 §1 Costs` | `·P1` · `·T2` |

The choice is display-only. `parse_ref` accepts **both** forms, so a label
resolves in whichever style emitted it — including addresses in older
transcripts written when glyphs were the only output.

## Worked example (golden-test fixture)

Input message (turn 27):

```markdown
## Costs

The pricing tiers changed last quarter. Here is the current breakdown.

| Tier | Price | Seats |
|------|-------|-------|
| Free | $0 | 1 |
| Pro | $12 | 5 |
| Team | $40 | 20 |

Enterprise pricing is negotiated separately.
```

`render_inline` output (turn 27) — labels are **injected into the original
source**, preserving your exact formatting: the heading keeps its `##` and gains
the section marker, a paragraph label goes inline, a block entity's label sits on
its own line above the block, blank lines are kept. The result still renders as
markdown:

```
## N27-S1 Costs

.P1 The pricing tiers changed last quarter. Here is the current breakdown.

.T1
| Tier | Price | Seats |
|------|-------|-------|
| Free | $0 | 1 |
| Pro | $12 | 5 |
| Team | $40 | 20 |

.P2 Enterprise pricing is negotiated separately.
```

`render_map` output (turn 27) — the compact overlay alternative, one row per
addressable block with an excerpt:

```
N27-S1 Costs
  .P1  The pricing tiers changed last quarter. Here is the current…
  .T1  4 rows x 3 cols
  .P2  Enterprise pricing is negotiated separately.
```

Addresses that resolve against it:

| Address | Resolves to |
|---------|-------------|
| `N27-S1.P1.2` | `Here is the current breakdown.` |
| `N27-S1.T1.4` | `\| Team \| $40 \| 20 \|` (row 4 counting the header as row 1) |
| `N27-S1.T1.4,2` | `$40` |
| `N27-S1.T1.(/Team/)` | the Team row (unique match) |
| `N27-S1.P2.1` | `Enterprise pricing is negotiated separately.` |
| `N27-S1.D1` | `MISSING: no D1 here` (hint: `in scope, in order: P1, T1, P2`) |
| `S1.P1` | `REJECTED: missing turn number` |

Table rows are 1-indexed **including the header row**, so `T1.1` is the header and
`T1.4` is the third data row. Columns are 1-indexed left to right.
