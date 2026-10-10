---
name: reference-points
description: Use when an address like N27-S1.T2.3 or a bare fragment like .P4 appears in a message, when you need to point at one exact block of an earlier reply, and when numbering the sections of the reply you are writing. Recalling what a turn said resolves to the wrong block silently, which is what these commands exist to stop.
---

# reference-points

`N27-S1.T2.3` means turn 27, section 1, table 2, row 3. An address resolves to
**exactly one block or fails with a named category** — it never lands on a
different block than the one meant.

That guarantee belongs to the parser, not to you. Reading the transcript and
deciding which paragraph "P4" probably means throws it away and reintroduces the
exact failure the grammar was built to remove.

**Run the command. Do not recall the block.**

## Setup — one variable per session

```bash
S=$(reference-points-session)      # this conversation's transcript
```

Both commands are on `PATH` once the plugin is installed. `reference-points`
prints results to stdout and failures to stderr with a non-zero exit.

## When the mod is loaded

The plugin also ships a Claude Code mod that does this work in code. It is loaded when the first prompt of a conversation carries a line beginning `[reference-points mod active]`.

With the mod loaded, do not write `N<turn>-S<n>` labels in your replies, because the viewer draws them and a second set would double them. An address in a prompt arrives already resolved, in a block headed `[N27-S1.P2]` after the prompt: quote that block and do not run `resolve` for it. A prompt holding a bad address never reaches you, because the mod refuses it with the engine's message.

Everything below still applies without that line, and for any address that did not arrive resolved.

## Someone hands you an address

```bash
reference-points resolve 'N27-S1.T2.3' "$S" -T          # full address: N does the lookup
reference-points resolve '.P4' "$S" -T --turn 39        # bare fragment: supply the turn
```

A bare fragment (`.P4`, `.T1`) means *the reply it was written under* — normally
your most recent one. Get that number, never guess it:

```bash
reference-points turns "$S"                             # replies so far, e.g. 39
```

Quote the resolved content back before answering about it. That is the whole
point: both sides are now looking at the same bytes.

## Numbering the reply you are writing

Your sections are labeled `N<turn>-S<n>`. Counting your own replies is the same
recall error one level up, and it is silently wrong — a long session drifts by
tens.

```bash
echo $(( $(reference-points turns "$S") + 1 ))          # the turn you are writing
```

Run it **before you emit any prose this turn**. Once you have written text, that
text is already in the transcript and `turns` counts it — your number is the
count itself, not one past it.

## Reading a whole conversation

```bash
reference-points label "$S" -T          # the viewer: every reply labeled, prompts quoted between
reference-points map "$S" -T            # the compact address -> excerpt overlay
reference-points map "$S" -T --turn 39  # one reply's addresses, cheapest way to find one
```

## The grammar

`N<turn>-S<section>.<Entity><n>[.location]` — turN · Section · Entity · Location.

| Letter | Entity | Location | Example |
|---|---|---|---|
| `P` | Paragraph | sentence | `P1.4` |
| `T` | Table | `row`, `row,col`, `,col` | `T2.3` · `T2.3,4` · `T2.,4` |
| `L` | List | item | `L1.2` |
| `C` | Verbatim block (fence, indent, raw HTML) | line | `C1.5` |
| `D` | Diagram (mermaid/dot) | line | `D1.3` |
| `Q` | Quote | *container* — nests | `Q1.P1.2` |
| `S` | Subsection | *container* — nests | `S2.P1` |
| `R` | Link reference definition | **none** | `R1` |

Address by content instead of by number with `(/regex/)` for the single match, or
`(g/regex/)` for every match. A selector can name *which* entity as well as a
spot inside one: `S(/Costs/)`, `P(/caching/)`, `T(g/\$/)`.

## When it fails

Every failure names a category and ends in the address to type instead. Read the
`->` line; it is the answer, not commentary.

| Prefix | Means | Your next move |
|---|---|---|
| `REJECTED:` | breaks the grammar, or the shape it landed on | fix the address as the hint says |
| `INVALID:` | address is fine, its regex is not | escape the metacharacters |
| `MISSING:` | well-formed, nothing there | the hint lists what *is* there — pick from it |
| `AMBIGUOUS:` | well-formed, more than one match | the hint shows the candidates; ask which, or use `(g/…/)` |
| `UNREADABLE:` | the file, not the address | wrong path, or `$S` never got set |

Never answer past a failure. `MISSING` and `AMBIGUOUS` both mean you do not yet
know what was meant, and both hand you the material to ask a one-line question.

## Red flags

| Thought | Checksum | Reality |
|---|---|---|
| "I can see which paragraph they mean, I just read that reply." | `felt(P) ⊬ tested(P)` | Reading and counting blocks by eye is the failure mode. Run `resolve`. |
| "I know I'm on turn 22." | `knew(t₀) ⊬ knows(t₁)` | Hand-counted turn numbers drift by tens over a session. Run `turns`. |
| "`AMBIGUOUS` — I'll take the first match." | `∃x P(x) ⊬ x = the one meant` | Two candidates and no reason to prefer either. The hint printed both; ask. |
| "Shelling out for one sentence is overkill." | `↑proxy ⊬ ↑target` | The cost measured is a 100ms subprocess. The cost that matters is answering about the wrong block. |
| "No transcript here, so I'll work from memory." | `¬obs(P) ⊬ ¬P` | Did `reference-points-session` fail, or did you not run it? Run it; if it fails, say so. |
