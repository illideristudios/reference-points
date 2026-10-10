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
uv run python -m reference_points label message.md --turn 27

# the compact address→excerpt overlay instead
uv run python -m reference_points map message.md

# resolve an address against a message → prints the referenced content
uv run python -m reference_points resolve 'N27-S1.T2.3' message.md --turn 27

# the labels above are fragments; with the turn supplied they resolve as printed
uv run python -m reference_points resolve '.P1' message.md --turn 27

# validate an address string on its own
uv run python -m reference_points parse 'N1-S1.P2.4'

# print the Section/Entity tree
uv run python -m reference_points decompose message.md

# how many replies a transcript holds — the number the next one is labeled with
uv run python -m reference_points turns session.jsonl
```

Point it at a **whole conversation** with `--transcript`, and the address finds
its own turn — no `--turn`, nothing else to know:

```bash
# the viewer: every reply labeled, with the prompts it answered quoted between
uv run python -m reference_points label session.jsonl --transcript

# resolve straight out of it — N does the lookup
uv run python -m reference_points resolve 'N27-S1.P1' session.jsonl --transcript
```

Any `<file>` may be `-` to read from stdin. Without `--transcript`, **`--turn N`
(default 1) is the turn the message came from**, and it does two jobs: it makes a turn-less address legal,
so the fragments `label` prints resolve exactly as printed; and it makes an
address for a *different* turn a loud miss rather than a confident wrong answer
against whatever this message happens to hold.

## Use it from Claude Code

This repo **is** a Claude Code plugin. There is nothing to install first — the
plugin puts the CLI on `PATH` and runs it out of the checkout through `uv`, so
`uv` is the only prerequisite.

```bash
claude plugin marketplace add locriani/reference-points   # or an absolute path to a clone
claude plugin install reference-points@reference-points
```

Restart Claude Code. Two commands are then on `PATH` in every Bash call:

```bash
S=$(reference-points-session)                     # this conversation's transcript
reference-points resolve 'N27-S1.T2.3' "$S" -T    # the block turn 27 pointed at
reference-points turns "$S"                       # replies so far
```

The bundled [`reference-points` skill](skills/reference-points/SKILL.md)
fires when an address appears in a message, and makes the assistant *resolve* it
rather than remember what a turn said — which is the failure the grammar exists
to remove, one level up.

It is a skill and not an MCP server on purpose: both commands are stateless text
in, text out, which the existing Bash tool already covers. A server would add a
process and a protocol to carry two `argv` arrays.

### As a mod

The plugin also ships a [Claude Code mod](https://code.claude.com/docs/en/plugins/mods/overview) in `hooks/`, on by default from Claude Code 2.1.287. It moves the work the skill asks of the model into code, so it costs the model no tokens.

- **Labels are drawn, not written.** Each reply block is redrawn with its labels as links, and the stored reply never contains them. The model is told once per conversation not to write its own.
- **A click inserts the address.** A plain click on a label puts its full address, such as `N27-S1.P2`, in the prompt box at the cursor. Ctrl, alt and cmd clicks are not the mod's to answer, so they keep the default link behaviour, and the link target is a reserved `.invalid` host that goes nowhere.
- **Addresses in a prompt are resolved on submit.** Each one arrives with its content attached. A bad one is refused with the engine's category and the address to type instead.

- **A call costs a request, not a Python start.** The first call the mod makes runs the CLI itself and starts `reference-points serve --daemon`, which keeps the engine running behind a Unix socket (mode 600, in a mode-700 directory under your temp dir). Later calls go over it in about 10 ms instead of about 100 ms. It is the same `main` behind the socket, so there is no second code path, and it is optional: with no server the mod falls back to the CLI. The server refuses a request once the engine's source has changed on disk, so an update never gets an answer from old code, and it stops after 30 idle minutes.

Clicks are reported only in the fullscreen terminal. The mod is JavaScript but holds no grammar: it calls `reference-points expand` and `reference-points label --block <uuid>`, so the engine stays the one decomposer. Turn the mod off in `/plugin`, or per session with `--safe-mode`, and the skill takes over.

## The grammar

An address is `<N>-<S>.<E>.<L>` — **turN · Section · Entity · Location**.

| Part | Meaning | Notes |
|------|---------|-------|
| `N<n>` | turn number — the **nth assistant reply** in the conversation | **mandatory** in prose; omit it only when the reader already has the turn (see below) |
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
| `D` | Diagram (mermaid/dot fence) | line number | `D1.3` = 3rd line |
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

A match can also stand in for an entity's **index** — naming *which* entity rather
than a spot inside one:

- `S(/Costs/)` — the subsection headed Costs. A section matches on its heading as
  well as its body, because the heading is what a reader names it by.
- `P(/caching/)` — the paragraph about caching.
- `T(g/\$/)` — every table mentioning a price.

A selector takes no further location. An `R` selector runs against the whole
definition, so `(/mdit/)` finds it by key and `(/github.com/)` by URL, following
CommonMark label normalization: `[MDIT]`, `[ mdit ]` and `[mdit]` are one
reference.

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

The mod draws a third form, `LINKED`: the ASCII text with each label a markdown link to its **full** address, so `.P1` under section 2 links to `N27-S2.P1`. The printed fragment is still ambiguous across sections, and the link is not.

A table's label line also lists its size and a link for every row and column, such as `.T1 · 4 rows × 3 cols · rows [1] [2] [3] [4] · cols [1] [2] [3]`, so the table forms (`T1.3`, `T1.,2`) are discoverable by clicking. The line sits above the table, which renders unchanged, and a table past 20 rows lists the first 20. For a single cell, edit a row address to `T1.3,2`.

The choice is display-only: `parse_ref` accepts **both** forms, so a label
resolves in whichever style emitted it.

Because a fragment carries no path, it is looked for in every container at every
depth — that is what lets a label printed inside a subsection resolve at all. When
nesting prints the same fragment twice, typing it is `AMBIGUOUS` and both
candidates come back with their full addresses; the engine never picks the
shallower one for you. A full address names its own scope and is never a search.

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

A malformed or unresolvable address never guesses. Every failure names its
**category**, says what happened, and ends in the address to type instead:

```
REJECTED: missing turn number
  -> every address starts with the turn it points into: N1-S1.P1

REJECTED: D1 takes no location
  -> use D1 on its own — a diagram has no addressable parts

REJECTED: P1 is not a container; cannot address inside it
  -> use P1.2 for a sentence, or P1.(/word/) to match inside it

INVALID: regex (/[/): unterminated character set at position 0
  -> a match body is a regex — escape the metacharacters you meant literally, as in (/\$40/)

MISSING: no T2 here
  -> in scope, in order: P1, T1, P2

MISSING: no such row 9 in T1
  -> T1 has 4 rows, counting the header as row 1

AMBIGUOUS: 2 blocks are labeled .P1
     N1-S1.P1 Alpha alpha.
     N1-S1.S1.P1 Bravo bravo.
  -> use N1-S1.P1 or N1-S1.S1.P1

AMBIGUOUS: 3 matches for (/\$/) in T1
     | Free | $0 | 1 |
     | Pro | $12 | 5 |
     | Team | $40 | 20 |
  -> use T1.(g/\$/) for all 3, or narrow the pattern
```

The four categories let you sort "I typed it wrong" from "it is not there" without
reading the prose:

| Prefix | Means |
|--------|-------|
| `REJECTED:` | the address breaks the grammar, or the shape it landed on |
| `INVALID:` | the address is fine, its regex is not |
| `MISSING:` | well-formed, and nothing is there |
| `AMBIGUOUS:` | well-formed, and more than one thing is there |

An `AMBIGUOUS` lists what it found — up to eight, then a count — because choosing
between candidates is impossible without seeing them.

`parse_ref` raises `RefError` (always `REJECTED`) and `resolve` raises
`ResolveError` carrying one of the four; both take their hint as a required
argument, so none can ship without one. The CLI prints the message unchanged and
exits 1; a file it cannot read is `UNREADABLE:`, which is not an address defect.

## Development

```bash
uv run pytest            # tests
uv run ruff check .      # lint
uv run ruff format .     # format
uv run pyright           # typecheck (strict on src)
claude plugin test       # the mod's tests (hooks/register.test.ts)
```

CI runs those same four commands on every push and pull request.
[`CONTRIBUTING.md`](CONTRIBUTING.md) has the rest: the TDD rule, the two invariants
that hold the engine together, and what a grammar change has to carry.
Participation is governed by [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).

Layout: `src/reference_points/` (`grammar` · `decompose` · `resolve` · `render`
· `__main__`), `hooks/` (the mod), one test module per source module under `tests/`. Built with the
`uv` toolchain; `uv.lock` is committed. Block structure comes from
[`markdown-it-py`](https://github.com/executablebooks/markdown-it-py) —
`decompose` maps its token stream onto the entity alphabet rather than scanning
markdown itself.

## License

MIT
