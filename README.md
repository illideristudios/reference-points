# reference-points

A citation grammar for pointing at the *exact* block of a chat message — a
specific table row, a specific sentence — that either **resolves exactly or
fails loudly**. It never silently resolves to the wrong object.

## Why

In a fast back-and-forth, referring to "that second table" or "the sentence
about caching" is ambiguous: by the time the reply lands, the referent has
moved, and the two sides resolve the phrase to different things. `reference-points`
replaces the prose pointer with a mechanical address (`N27-S1.T2.3` = turn 27,
section 1, table 2, row 3). One deterministic decomposer both *labels* a message
and *resolves* an address against it, so a label and its lookup agree by
construction — and a bad address is rejected with a named reason instead of a
wrong guess.

## Quick start

```bash
uv sync                                   # install (Python 3.13, dev tools)

# label a message with its addresses (--turn N, --glyphs)
uv run python -m reference_points label message.md

# the compact address→excerpt overlay instead
uv run python -m reference_points map message.md

# resolve an address against a message → prints the referenced content
uv run python -m reference_points resolve 'N1-S1.T2.3' message.md

# validate an address string on its own
uv run python -m reference_points parse 'N1-S1.P2.4'

# print the Section/Entity tree
uv run python -m reference_points decompose message.md
```

Any `<file>` may be `-` to read from stdin.

## The grammar

An address is `<N>-<S>.<E>.<L>` — **turN · Section · Entity · Location**.

| Part | Meaning | Notes |
|------|---------|-------|
| `N<n>` | turn number | **mandatory** — an N-less address is rejected |
| `S<n>` | section (markdown heading, ATX or setext; whole msg = `S1` if none) | container; nests |
| `E<n>` | entity, indexed per type within its section | see table below |
| `L`   | location inside the entity | shape depends on entity type |

### Entities

| Letter | Entity | Location shape | Example |
|--------|--------|----------------|---------|
| `P` | Paragraph | sentence number | `P1.4` = 4th sentence |
| `T` | Table | `row`, `row,col`, or `,col` | `T2.3`, `T2.3,4`, `T2.,4` |
| `L` | List | item number | `L1.2` = 2nd item |
| `C` | Verbatim block — fenced, indented, or raw HTML | line number (`\n`-delimited) | `C1.5` = 5th line |
| `Q` | Quote (blockquote) | *container* — nests inner entities | `Q1.P1.2` |
| `S` | Subsection | *container* — nests | `S2.P1` |
| `D` | Diagram | **none** — `D1.<anything>` is rejected | `D1` |
| `R` | Link reference definition (`[key]: url`) | **none** — `R1.<anything>` is rejected | `R1`, `R(/mdit/)` |

`R` is the one entity that is **addressable but never labeled inline**: a
definition renders to nothing, so a label would put visible text where the reader
saw none — and would stop the line being a definition at all. `render_inline`
leaves those lines byte-identical to the source; `render_map` carries their
addresses.

### Match strings

Instead of a numeric location you can address by content:

- `(/scheme/)` — the **single** match in scope. More than one match → `AMBIGUOUS`.
- `(g/scheme/)` — **every** match in scope.

A match can also stand in for an entity's **index**: `R(/mdit/)` is the reference
whose definition matches, `P(/caching/)` the paragraph about caching, and
`R(g/https/)` every reference that matches. A selector takes no further location.

An `R` selector runs against the whole definition, so `(/mdit/)` finds it by key
and `(/github.com/)` by URL, and it follows CommonMark label normalization:
`[MDIT]`, `[ mdit ]` and `[mdit]` are one reference.

### How labels are rendered

A section header carries the **full prefix** and its heading text with no dash
between; every other block carries only its **fragment**. Full paths are for
references, fragments are for labels.

Two marker sets. ASCII is the default — labels read as the characters you type.
Pass `--glyphs` for the monochrome set instead:

| Style | Section header | Block |
|-------|----------------|-------|
| ASCII (default) | `## N27-S1 Costs` | `.P1` |
| `--glyphs` | `## ◆27 §1 Costs` | `·P1` |

The choice is display-only: `parse_ref` accepts **both** forms, so a label
resolves in whichever style emitted it.

Anything under `C` is stored **byte-for-byte** and addressed by line or by
`(/match/)` — never split into sentences. A thematic break (`---`, `***`) is not
an entity: no content, no address, no label.

**A labeled message still renders as markdown.** Heading markers are kept, so a
heading stays a heading — an ATX line is rebuilt with its `#`s, a setext heading
gets the label prefixed onto its text and keeps its underline. Where a first line
means what it means because of its leading characters — an indented code block, a
`---` thematic break, an HTML block — the label moves to its own line with a blank
line after it rather than corrupting the construct.

## Rejection is loud

A malformed or unresolvable address never guesses. It names the defect (the CLI
prefixes these with `error: ` and exits non-zero):

- `missing turn number` — no `N`.
- `D1 takes no location` — diagram addressed with a location.
- `AMBIGUOUS: 3 matches for (/scheme/) in T2` — a single-match string hit more than once.
- `no such row 9 in T2 (has 4)` — location out of range.
- `no T2 here` — the entity does not exist in that section.

## Development

```bash
uv run pytest            # tests
uv run ruff check .      # lint
uv run ruff format .     # format
uv run pyright           # typecheck (strict on src)
```

Layout: `src/reference_points/` (`grammar` · `decompose` · `resolve` · `render`
· `__main__`), one test module per source module under `tests/`. Built with the
`uv` toolchain; `uv.lock` is committed. Block structure comes from
[`markdown-it-py`](https://github.com/executablebooks/markdown-it-py), the one
runtime dependency — `decompose` maps its token stream onto the entity alphabet
rather than scanning markdown itself.

## License

MIT
