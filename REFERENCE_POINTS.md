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

## Grammar

```
address := N <n> [ "-" S <n> ] { "." entity } [ "." location ]
```

An address reads **turN · Section · Entity · Location**: `N27-S1.T2.3`.

| Part | Form | Rule |
|------|------|------|
| turn | `N<n>` | **mandatory**; an N-less address is REJECTED |
| section | `S<n>` | optional; whole message is `S1` when it has no headings |
| entity | `<Letter><n>` | indexed **per type within its section**: `T2` = 2nd table |
| location | see below | legal shape depends on the terminal entity's type |

A location attaches only to the **terminal** entity in the path. Container
entities (`S`, `Q`) nest: `N1-S1.Q1.P1.2` = turn 1, section 1, blockquote 1,
its paragraph 1, sentence 2.

### Entity alphabet

| Letter | Entity | Location | Notes |
|--------|--------|----------|-------|
| `P` | Paragraph | `.<sentence>` | sentence index within the paragraph |
| `T` | Table | `.<row>` · `.<row>,<col>` · `.,<col>` | row, cell, or whole column |
| `L` | List | `.<item>` | item index |
| `C` | Code block | `.<line>` | verbatim, `\n`-delimited logical line |
| `Q` | Quote | *(container)* | blockquote; nests inner entities |
| `S` | Subsection | *(container)* | markdown heading; nests |
| `D` | Diagram | **none** | `D<n>.<anything>` is REJECTED |

### Match strings (address by content instead of index)

- `(/text/)` — the **single** match in scope; >1 match → `AMBIGUOUS`.
- `(g/text/)` — **every** match in scope.

E.g. `N27-S1.T2.(/Team/)` = the row in table 2 that uniquely contains "Team".

## Resolved open questions

1. **Build the parser?** Yes — this engine.
2. **Diagram location (`D.L`)?** Undefined. `decompose` emits `D<n>` with no
   location; `parse_ref` rejects `D<n>.<anything>` loudly.
3. **Nesting depth / does the index reset?** Arbitrary nesting; a location
   attaches only to the terminal entity, so "reset per level" is a non-issue.
4. **Do lists / code / quotes get letters?** Yes: `L`, `C`, `Q` added to the
   spec's `T·D·P·S`. **No `H` (raw-HTML) entity** — HTML that gets *displayed* is
   fenced, so it is a `C` code block; interpreted container HTML (`<details>`)
   renders as plain text in a terminal and is not emitted as an entity; an HTML
   `<table>` maps onto `T` (parsing TODO).
5. **Label density?** Every substantive block is addressable.
6. **Rejection UX?** Fail loud, name the defect, wait — never guess. Examples:
   `REJECTED: missing turn number`, `REJECTED: D1 takes no location`,
   `AMBIGUOUS: 3 matches for (/scheme/)`, `no such row 9 in T2`.

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

1. **Heading markers are preserved.** A section label rebuilds the line with its
   original ATX markers — `## N27-S1 Costs`, not `N27-S1 Costs`. Dropping them
   collapses every heading in the message into a paragraph.
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
| `N27-S1.D1` | `REJECTED: no diagram in section 1` |
| `S1.P1` | `REJECTED: missing turn number` |

Table rows are 1-indexed **including the header row**, so `T1.1` is the header and
`T1.4` is the third data row. Columns are 1-indexed left to right.
