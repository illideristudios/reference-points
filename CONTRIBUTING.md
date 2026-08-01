# Contributing to reference-points

This project exists to prevent exactly one bug: **an address that silently resolves
to the wrong thing.** Everything below follows from that. A change that makes the
engine more convenient at the cost of a silent mis-resolution is not a change we
want, however small.

## Setup

```bash
uv sync                              # Python 3.13, runtime + dev tools
uv run python -m reference_points --help
```

`uv.lock` is committed and CI installs with `--locked`. If your change needs a new
dependency, commit the updated lockfile in the same PR.

## The gate

Run this before every commit. CI runs the same four commands, so a red gate here is
a red PR there:

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest
```

Inner loop while you work: `uv run pytest tests/test_<module>.py -x`. Before you
push: `uv run pytest -n auto`.

## Tests come first

New behavior needs a **failing test first**, and you need to have watched it fail for
the right reason — a test that has never been red proves nothing. Fix the test, not
the assertion, when the two disagree.

Match parser tests to the grammar table in `README.md`: every valid form and every
rejection form has a test. An untested entity type is not a shipped entity type.

## The two invariants

**One decomposer.** `decompose()` both labels a message and provides the tree
`resolve()` walks. A label the renderer emits and the address the resolver computes
are identical *by construction*. Never add a second code path that could disagree —
if labeling needs to know something, teach `decompose`, don't teach the renderer.

**Round-trip.** Every address `render_inline` emits must resolve back to the exact
block it labels. `test_every_address_in_the_torture_document_resolves_to_its_own_entity`
enforces this at every depth by comparing **content**, not by asserting no-raise: an
off-by-one inside a blockquote resolves to the wrong block and raises nothing at all.

Both invariants are load-bearing. A PR that weakens either needs to say so in its
description, in those words.

## Failure messages are a feature

Every parse/resolve failure raises a typed error that:

1. carries one of the four categories — `REJECTED:` / `INVALID:` / `MISSING:` /
   `AMBIGUOUS:` (constants in `grammar.py`), and
2. ends in a `hint` — **the address to type instead**.

Both are required constructor arguments, so the type checker catches an omission
rather than a reviewer. `test_every_failure_names_its_category` and
`test_every_failure_says_what_to_type_instead` hold the line; don't route around them.

Where the engine knows the answer, the hint gives it. `MISSING: no such row 9 in T1`
is followed by `T1 has 4 rows, counting the header as row 1` — not by generic advice
about checking your input.

## Adding to the grammar

- **A new block construct** means a new row in the token→entity mapping in
  `_leaf_entity`, not a new branch in a scanner. What may interrupt a paragraph is
  `markdown-it-py`'s problem, not ours. Keep the fallback at the end of that dispatch
  lossless: an unrecognized token becomes a verbatim `C`, never nothing.
- **Verbatim stays verbatim.** Fenced, indented, and raw-HTML blocks are `C` entities:
  lines stored exactly as written, addressed by line or `(/match/)`, never split into
  sentences.
- **A new marker set** is a new `LabelStyle` constant, not a branch in the renderer.
  `parse_ref` must accept whatever the new style emits.
- **`split_sentences` is a heuristic on purpose.** It is imperfect *because* the same
  function runs at label-time and at resolve-time, so labels and lookups stay
  self-consistent. Don't push it toward linguistic correctness at the cost of
  determinism.

Labeled output must still render as markdown. Verify with
`test_labeling_preserves_the_block_skeleton` over `tests/fixtures/torture.md` — extend
the fixture rather than eyeballing a diff.

## Scope

YAGNI is enforced. No speculative entity types, no configuration knobs, no override
hooks without a caller that exists today. If a reviewer asks for a guard, the question
is whether you can write the caller that triggers the bug; if you can't, say so and
skip it.

## Docs travel with the code

Both are required with every code change:

1. **`README.md`** — human-facing; its grammar table stays in sync with `grammar.py`.
2. **`REFERENCE_POINTS.md`** — the canonical spec; update it whenever a grammar
   decision changes.

`QUESTIONS.md` is the decision log — the *why* behind the spec. Add a section when a
design question gets settled, so the reasoning outlives the conversation.

## Issues and pull requests

Blank issues are disabled: use a template. One concern per issue — "X is broken and Y
would be nice" is two issues.

Link the issue from the PR body with a **closing keyword** (`Closes #12`). Prose like
"this addresses issue 12" builds no timeline link and closes nothing. Trivial chores
(typo, dependency bump) may skip the issue.

Commits: imperative subject, present tense, 72 characters or fewer, describing the
change rather than the file. The body says *why*, not *what*. Don't bundle formatting
with behavior, or a refactor with a feature — and never commit a red tree; stash or
branch instead.

## Code of Conduct

Participation is governed by [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md).
