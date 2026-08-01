# Project: reference-points
A citation grammar engine — parse/resolve `<N>-<S>.<E>.<L>` addresses against markdown message content, resolving exactly or failing loudly.

> This file is the project-specific overlay. Whatever global workflow rules your setup already applies still hold; nothing here depends on them.

## Core Principles (project-specific)
- **One decomposer, single source of truth.** `decompose()` both labels a message and provides the tree that `resolve()` walks. A label emitted by the renderer and the address the resolver computes are identical *by construction* — never maintain two code paths that could disagree.
- **Fail loud, never guess.** Every parse/resolve failure raises a typed error naming the specific defect (missing turn, illegal location for entity, ambiguous match, out-of-range). Silent mis-resolution is the one bug this project exists to prevent.
- **Pure functions.** `grammar`, `decompose`, `resolve`, `render` are side-effect-free and independently testable; only `__main__` does I/O.
- **YAGNI.** Build for the grammar as specified. No speculative entity types or config knobs.

## Stack
- **Language**: Python 3.13 (`from __future__ import annotations` on every module)
- **Runtime dependency**: `markdown-it-py` (MIT, plus `mdurl`) — the CommonMark parser `decompose` maps onto the entity alphabet. One module-level `_MD` constant, no knob, no fallback decomposer.
- **Package manager**: `uv` (uv.lock committed)
- **Test framework**: `pytest` (+ `pytest-xdist`)
- **Lint / format**: `ruff` (strict select-list)
- **Type checker**: `pyright` (`typeCheckingMode = "strict"` on `src`)

## Build & Test Commands
- **Install**: `uv sync`
- **Run CLI**: `uv run python -m reference_points <cmd> [args]`
- **Unit tests**: `uv run pytest`
- **Lint**: `uv run ruff check .`  · **Format**: `uv run ruff format .`
- **Type-check**: `uv run pyright`

## TDD — Project-specific Red → Green → Refactor commands
- **Inner Red→Green loop** (scoped): `uv run pytest tests/test_<module>.py -x`
- **Post-Refactor confidence check**: `uv run pytest -n auto`
- **Pre-commit gate**: `uv run ruff check . && uv run ruff format --check . && uv run pyright && uv run pytest`

### Testing — Hard Rules
- New behavior MUST have a failing test first (watch it fail for the right reason).
- The **round-trip invariant** is load-bearing: every address `render_inline` emits MUST resolve back to the exact block it labels. `test_every_address_in_the_torture_document_resolves_to_its_own_entity` enforces it at every depth by comparing *content*, not by asserting no-raise — an off-by-one inside a blockquote or a list resolves to the wrong block and still raises nothing.
- Match parser tests to the grammar table in the README — every valid form and every rejection form has a test.

## Code Organization
- **One module per concern** under `src/reference_points/`:
  `grammar.py` (Ref dataclass + `parse_ref` + `RefError`), `decompose.py`
  (`decompose` + `split_sentences`), `resolve.py`, `render.py`
  (`render_inline` + `render_map`), `__main__.py` (CLI only).
- One test module per source module: `tests/test_<module>.py`.
- Dataclasses for AST nodes; `pathlib` for file I/O.

## Documentation Checklist (Required with Every Code Change)
1. **README.md** — repo root (always required; human-facing; grammar table stays in sync with `grammar.py`).
2. **REFERENCE_POINTS.md** — the canonical spec; update when a grammar decision changes.

## Project-Specific Gotchas
- **A labeled message MUST still render as markdown.** This is the constraint that shapes `render_inline`: heading markers are re-emitted, and a label never gets prefixed onto a line whose leading characters carry meaning (indented code, thematic break, HTML block) — it goes above, with a blank line. Verify a change by rendering source and labeled output through a GFM renderer and diffing the block skeletons; don't eyeball it. `test_labeling_preserves_the_block_skeleton` in `tests/test_render.py` is that ritual, run over `tests/fixtures/torture.md` with the parser the decomposer already depends on — extend the fixture rather than checking by hand.
- **A verbatim block stays verbatim.** Fenced, indented, and raw-HTML blocks are all `C` entities: their lines are stored exactly as written and addressed by *line* (or `(/match/)`), never by sentence. Adding a construct means adding a row to the token→entity mapping in `_leaf_entity`, not a scanner branch — what may interrupt a paragraph is the parser's problem now, not ours. Keep the fallback at the end of that dispatch lossless: an unmapped block becomes a verbatim `C` rather than being dropped.
- **`R` is addressable but never labeled inline.** It is the only entity of which that is true. A link reference definition renders to nothing, so `_label_entity` returns early for it and `_anchor_line` refuses to anchor the implicit-S1 marker above one — a marker there makes the definition a lazy continuation of the marker's paragraph, and every `[key]` in the labeled copy silently becomes literal text. `render_map` is where its address lives.
- **`split_sentences` is a heuristic** — imperfection is acceptable *because* the same function runs at label-time and resolve-time, so labels and lookups stay self-consistent. Don't "fix" it toward linguistic correctness at the cost of determinism.
- **The marker set is a `LabelStyle`, not a hard-coded string.** `ASCII` is the default (`N27-S1` / `.P1`); `GLYPH` (`◆27 §1` / `·P1`) is opt-in via `--glyphs`. Adding a style means adding a constant, not branching in the renderer. `parse_ref` accepts every style's output — `_normalize_glyphs` is what makes that true, so don't delete it.

## Gitignore Must-Haves
`.venv/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, `dist/`, `*.egg-info/`, `_scratch/`.
