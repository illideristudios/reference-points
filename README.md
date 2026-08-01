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

# label a message with its addresses
uv run python -m reference_points label message.md

# resolve an address against a message → prints the referenced content
uv run python -m reference_points resolve 'N1-S1.T2.3' message.md

# validate an address string on its own
uv run python -m reference_points parse 'N1-S1.P2.4'
```

## The grammar

An address is `<N>-<S>.<E>.<L>` — **turN · Section · Entity · Location**.

| Part | Meaning | Notes |
|------|---------|-------|
| `N<n>` | turn number | **mandatory** — an N-less address is rejected |
| `S<n>` | section (markdown heading; whole msg = `S1` if none) | container; nests |
| `E<n>` | entity, indexed per type within its section | see table below |
| `L`   | location inside the entity | shape depends on entity type |

### Entities

| Letter | Entity | Location shape | Example |
|--------|--------|----------------|---------|
| `P` | Paragraph | sentence number | `P1.4` = 4th sentence |
| `T` | Table | `row`, `row,col`, or `,col` | `T2.3`, `T2.3,4`, `T2.,4` |
| `L` | List | item number | `L1.2` = 2nd item |
| `C` | Code block | line number (verbatim, `\n`-delimited) | `C1.5` = 5th line |
| `Q` | Quote (blockquote) | *container* — nests inner entities | `Q1.P1.2` |
| `S` | Subsection | *container* — nests | `S2.P1` |
| `D` | Diagram | **none** — `D1.<anything>` is rejected | `D1` |

### Match strings

Instead of a numeric location you can address by content:

- `(/scheme/)` — the **single** match in scope. More than one match → `AMBIGUOUS`.
- `(g/scheme/)` — **every** match in scope.

### How labels are rendered

A section header carries the **full prefix** and its heading text with no dash
between; every other block carries only its **fragment**. Full paths are for
references, fragments are for labels.

Two marker sets. ASCII is the default — labels read as the characters you type.
Pass `--glyphs` for the monochrome set instead:

| Style | Section header | Block |
|-------|----------------|-------|
| ASCII (default) | `N27-S1 Costs` | `.P1` |
| `--glyphs` | `◆27 §1 Costs` | `·P1` |

The choice is display-only: `parse_ref` accepts **both** forms, so a label
resolves in whichever style emitted it.

## Rejection is loud

A malformed or unresolvable address never guesses. It names the defect:

- `REJECTED: missing turn number` — no `N`.
- `REJECTED: D1 has no location` — diagram addressed with a location.
- `AMBIGUOUS: 3 matches for (/scheme/)` — single-match string hit more than once.
- `no such row 9 in T2` — location out of range.

## Development

```bash
uv run pytest            # tests
uv run ruff check .      # lint
uv run ruff format .     # format
uv run pyright           # typecheck (strict on src)
```

Layout: `src/reference_points/` (`grammar` · `decompose` · `resolve` · `render`
· `__main__`), one test module per source module under `tests/`. Built with the
`uv` toolchain; `uv.lock` is committed.

## License

MIT
