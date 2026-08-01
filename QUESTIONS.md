# QUESTIONS — decision log

Durable record of the design questions asked during build and the answers given, so the
*why* survives when the conversation that produced it doesn't. Newest section at the
bottom. Companion to `REFERENCE_POINTS.md`, the canonical spec.

---

## Session 2026-07-17 — match semantics, address shape, and the overlay channel

The engine was already built (grammar · decompose · resolve · render · CLI, 63 tests). These
decisions came out of adopting it live and throwing real references at it.

### Q1 — Is `(/…/)` a literal substring or a regex?
**A: regex.** `(/rx/)` runs `re.search(rx, scope)` over the entity's scoped content — not a
literal `in` test. `(/F.ee/)` matches "Free".

### Q2 — Does the match bind with a dot (`p1.(/rx/)`) or directly (`p1(/rx/)`)?
**A: directly — no dot.** `p1(/rx/)` is the canonical form; the dot is optional/tolerated. The
old "malformed entity" rejection of `p1(/rx/)` was wrong.

### Q3 — Is the regex case-sensitive? Is there an `i` flag surface?
**A: case-sensitive, no implicit `i`, and we build no flag surface.** The pattern body is passed
to `re.search` verbatim, so every flag rides *inside* the pattern via inline scoped groups —
`(/(?i:five)/)`, `(?s:…)`, `(?m:…)`, `(?x:…)`. Zero grammar to maintain; full flag power for free.
```
body → re.search verbatim  ⊢  (?i:…) etc. already work  ∴  flag surface ¬needed
```

### Q4 — What is `(g/…/)`?
**A: every matching sub-unit in the current scope** (`every=True`). Distinct from a regex global
flag: our `g` is scope-granularity (keep every sentence/row/item that matches), it still calls
`re.search` per sub-unit.

### Q5 — Is a regex a *kind of location*, or separate from location?
**A: SEPARATE and orthogonal.** `[location]` is a structural coordinate (`n | row,col | ,col`);
`[regex]` is an independent, composable suffix that scopes *finer* than a location. Both optional;
they compose. `Ref` must carry **location and regex as two fields**, not one shared slot.
```
location ⊥ regex
P1           whole paragraph
P1.2         sentence 2                (location)
P1(/foo/)    match within paragraph    (regex, no location)
P1.2(/foo/)  match within sentence 2   (location THEN regex — finer)
```
Consequence: the old "two locations, rejected" verdict on `P3.1(/…/)` was an engine bug, not the
grammar. That composition is legal.

### Q6 — When a regex matches, what does `resolve` return?
**A: BOTH the matched span AND its enclosing unit — always both, not context-dependent.**
```
regex result := ⟨span, enclosingUnit⟩
  span          := the exact text the regex matched
  enclosingUnit := the [location] scope if present,
                   else the natural sub-unit containing the match  (P→sentence·T→row·L→item·C→line)
  (g/…/)        := every ⟨span, enclosingUnit⟩ pair in scope
```
The overlay highlights the span inside its unit.

### Q7 — How is the schema written so `L` isn't ambiguous?
**A: bracketed named placeholders**, never bare capitals:
```
N[turnID]-S[sectionID].[entityName][entityID][.location][regex]
```
`[sectionID]` optional; `[entityName][entityID]` repeats for nested containers (`.Q1.P1`). `L` now
appears only as an `[entityName]` value (List) — the List/Location collision was notation, not a
flaw in `L`=List.

### Q8 — Live overlay: a claude.ai Artifact, or a local thing?
**A: a local web app** (`reference-points serve`). A claude.ai Artifact is sandboxed (no filesystem,
no network under CSP) and cannot read the session log. "Artifact" here means *local artifact*. The
app auto-loads/streams the live session JSONL, renders labeled turns, and resolves via a local
endpoint that runs the **real** engine (single source of truth) — free, local, offline.

### Q9 — Interactive resolver or read-only overlay?
**A: interactive resolver** (option 1). Click a block ⇒ copy its address; type an address ⇒
highlight + show content. The read-only static overlay was rejected as less useful.

---

**Status.** Shipped from the above: Q1 (regex, not substring), Q2 (no-dot binding), Q3 (no flag
surface — flags ride inline), Q4 (`g/…/`), Q5 (`location` and `match` as separate `Ref` fields,
composable), Q7 (the bracketed-placeholder notation).

Outstanding:

- **Q6 — span *and* enclosing unit.** `Resolution` currently carries `kind` and `content` only; a
  regex hit returns the enclosing unit, and the matched span is dropped. The decision says return
  both, always.
- **Q8 / Q9 — the `serve` overlay.** Not started.

---

## Session 2026-08-01 — what the repo owes a stranger

Not grammar decisions. These settle what ships *around* the engine, asked while bringing
the repo up to open-source standard ahead of a review.

### Q10 — How wide should the community-health pass go?
**A: docs and CI both.** `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, a second issue template,
and a GitHub Actions workflow running the pre-commit gate verbatim. The alternative —
docs now, CI later — leaves the gate in `CLAUDE.md` enforced by discipline only, which
proves nothing about a pull request from someone who has never read it.
```
gate ∈ CLAUDE.md  ∧  ¬∃f(.github/workflows/*)  ⊢  enforced(gate) = discipline
```

### Q11 — Does the repo need a `SECURITY.md`?
**A: no, not yet.** A pure-function parser with no network surface has no
vulnerability class worth a private disclosure channel. Revisit when
`serve` (Q8) lands — a local web app that reads session JSONL is the first thing here
with an attack surface at all.

### Q12 — Blank issues are disabled and there was one template. What files as an issue?
**A: only a bug — which was a defect, not a policy.** `blank_issues_enabled: false` plus
`bug_report.yml` alone made a grammar proposal literally unfileable. Added
`grammar_change.yml`, which forces the two questions a new address form always owes:
what it collides with in the existing alphabet, and what a message containing both
resolves to.

### Q13 — `AGENTS.md` alongside `CLAUDE.md`?
**A: a symlink, never a copy.** `AGENTS.md → CLAUDE.md`. Two files stating one set of
rules drift, and the project's own first principle is that one source of truth is what
makes a label and its address agree by construction. The same argument applies to
instructions.

---

**Status.** Q10–Q13 shipped. Deliberately not done in this pass, both outward-facing and
the user's call: making the repo public, and setting its GitHub description and topics.
