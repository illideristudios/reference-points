"""Tests for rendering: inline labels (golden) and the address map."""

from __future__ import annotations

import re
from itertools import zip_longest
from typing import Any

from markdown_it import MarkdownIt

from reference_points.decompose import Entity, Message, Quote, Section, decompose
from reference_points.grammar import AMBIGUOUS, parse_ref
from reference_points.render import (
    GLYPH,
    LINK_BASE,
    LINKED,
    quote_prompt,
    render_blocks,
    render_inline,
    render_map,
    render_transcript,
    render_transcript_map,
)
from reference_points.resolve import ResolveError, resolve, resolve_entity, resolve_in
from reference_points.transcript import Transcript, Turn

GOLDEN_INLINE = """\
## N27-S1 Costs

.P1 The pricing tiers changed last quarter. Here is the current breakdown.

.T1
| Tier | Price | Seats |
|------|-------|-------|
| Free | $0 | 1 |
| Pro | $12 | 5 |
| Team | $40 | 20 |

.P2 Enterprise pricing is negotiated separately."""


def test_render_inline_matches_the_golden_worked_example(worked_msg: Message) -> None:
    assert render_inline(worked_msg) == GOLDEN_INLINE


def test_message_with_no_heading_gets_a_turn_marker() -> None:
    msg = decompose("First paragraph here.\n\nSecond paragraph here.\n", turn=3)
    out = render_inline(msg)
    assert out.splitlines()[0] == "N3-S1"
    assert ".P1 First paragraph here." in out
    assert ".P2 Second paragraph here." in out


def test_render_map_lists_every_addressable_block(worked_msg: Message) -> None:
    # A standalone index, not a renderable copy: no heading markers.
    out = render_map(worked_msg)
    assert "N27-S1 Costs" in out
    assert "## N27-S1" not in out
    assert ".P1" in out
    assert ".T1" in out
    assert ".P2" in out


def test_labeling_preserves_every_heading_level() -> None:
    # Drop the ATX markers and every heading collapses into a paragraph.
    msg = decompose("# One\n\nalpha.\n\n### Three\n\nbeta.\n\n###### Six\n\ngamma.\n", turn=9)
    out = render_inline(msg)
    assert "# N9-S1 One" in out
    assert "### .S1 Three" in out
    assert "###### .S1 Six" in out


def test_position_sensitive_blocks_keep_their_own_label_line() -> None:
    # These first lines mean something *because* of their leading characters. The
    # blank line after the label is load-bearing: without it the construct below
    # becomes a lazy continuation of the label's own paragraph.
    for source, first_line in (
        ("alpha.\n\n    indented code\n", "    indented code"),
        ("alpha.\n\n<details>\n<summary>s</summary>\n", "<details>"),
    ):
        lines = render_inline(decompose(source)).splitlines()
        assert first_line in lines, f"{first_line!r} was mutated: {lines!r}"
        at = lines.index(first_line)
        assert not lines[at - 1], f"no blank line after label: {lines!r}"
        assert lines[at - 2] == ".C1", f"expected a code label above: {lines!r}"


def test_no_label_lands_inside_a_verbatim_block() -> None:
    src = "    indented line one\n    indented line two\n"
    lines = render_inline(decompose(src)).splitlines()
    at = lines.index("    indented line one")
    assert lines[at + 1] == "    indented line two"

    lines = render_inline(decompose("<details>\n<summary>s</summary>\n")).splitlines()
    at = lines.index("<details>")
    assert lines[at + 1] == "<summary>s</summary>"


def test_a_thematic_break_gets_no_label() -> None:
    lines = render_inline(decompose("alpha.\n\n---\n\nbeta.\n")).splitlines()
    at = lines.index("---")
    assert not lines[at - 1], f"the break's surroundings were edited: {lines!r}"
    assert ".P2 beta." in lines


def test_ordinary_paragraph_label_stays_inline() -> None:
    out = render_inline(decompose("alpha one.\n\nbeta two.\n"))
    assert ".P2 beta two." in out


def test_implicit_section_marker_is_not_a_heading() -> None:
    # No heading line to preserve, so no '#' is invented.
    msg = decompose("Just a paragraph.\n", turn=9)
    assert render_inline(msg).splitlines()[0] == "N9-S1"


def test_the_implicit_marker_does_not_swallow_the_first_paragraph() -> None:
    # Having no heading line to sit on, the marker takes its own — and without a
    # blank line after it the block below is a lazy continuation of it. The two
    # render as one paragraph reading "N9-S1 .P1 Just a paragraph.", which is the
    # marker changing what the message renders to.
    out = render_inline(decompose("Just a paragraph.\n", turn=9))
    assert [t.type for t in _MD_BLOCKS.parse(out)].count("paragraph_open") == 2


def test_glyph_style_renders_the_alternate_marker_set(worked_msg: Message) -> None:
    out = render_inline(worked_msg, style=GLYPH)
    assert out.splitlines()[0] == "## ◆27 §1 Costs"
    assert "·P1 The pricing tiers changed last quarter." in out
    assert "·T1" in out


def test_glyph_style_applies_to_the_map_too(worked_msg: Message) -> None:
    out = render_map(worked_msg, style=GLYPH)
    assert "◆27 §1 Costs" in out
    assert "·P1" in out


def test_glyph_labels_resolve_back(worked_msg: Message) -> None:
    # The round-trip must hold in whichever style emitted the label.
    out = render_inline(worked_msg, style=GLYPH)
    assert out.splitlines()[0] == "## ◆27 §1 Costs"
    assert resolve(parse_ref("◆27 §1 ·T1.4,2"), worked_msg).content == "$40"


def test_glyph_addresses_still_parse(worked_msg: Message) -> None:
    # Old transcripts are full of glyph-form addresses.
    assert resolve(parse_ref("◆27 §1 ·T1.4,2"), worked_msg).content == "$40"


def test_every_emitted_label_resolves_back(worked_msg: Message) -> None:
    for section in worked_msg.sections:
        for entity in section.entities:
            letter = type(entity).__name__[0]
            address = f"N27-S{section.index}.{letter}{entity.index}"
            resolve(parse_ref(address), worked_msg)  # must not raise


def test_a_line_break_is_only_what_the_decomposer_calls_one() -> None:
    # str.splitlines() also breaks on \x0c, \x85, U+2028 and five more that
    # CommonMark does not — and decompose splits on "\n" alone. Two splitters over
    # one source is two line maps: every label after such a character lands a line
    # early, onto a blank line or onto the wrong paragraph, silently.
    for char in ("\x0c", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029", "\x0b"):
        src = f"Alpha{char}beta gamma.\n\nSecond paragraph.\n\nThird paragraph."
        lines = render_inline(decompose(src, turn=1)).split("\n")
        assert ".P2 Second paragraph." in lines, f"{char!r} shifted the labels: {lines!r}"
        assert ".P3 Third paragraph." in lines, f"{char!r} shifted the labels: {lines!r}"


# --- setext headings -----------------------------------------------------


def test_a_setext_heading_keeps_its_underline_and_gains_its_label() -> None:
    lines = render_inline(decompose("Title\n=====\n\nBody.\n", turn=4)).splitlines()
    assert lines[0] == "N4-S1 Title"
    assert lines[1] == "====="


def test_a_nested_setext_heading_is_prefixed_not_rebuilt() -> None:
    lines = render_inline(decompose("# Top\n\nLower\n-----\n\nBody.\n", turn=4)).splitlines()
    assert lines[0] == "# N4-S1 Top"
    assert ".S1 Lower" in lines
    assert "-----" in lines


# --- link reference definitions -----------------------------------------

REFS_MD = """\
Body text linking to [mdit].

[mdit]: https://github.com/executablebooks/markdown-it-py "The parser"
"""


def test_reference_definition_lines_render_byte_identical_to_the_source() -> None:
    out = render_inline(decompose(REFS_MD))
    definition = REFS_MD.splitlines()[2]
    assert definition in out.splitlines()


def test_a_labeled_copy_still_defines_its_links() -> None:
    # The invariant behind the byte-identical rule: still a definition after
    # labeling, or every `[mdit]` renders as text.
    md = MarkdownIt("commonmark")

    def definitions(markdown: str) -> dict[str, str]:
        env: dict[str, Any] = {}
        md.parse(markdown, env)
        table: dict[str, dict[str, str]] = env["references"]
        return {key: entry["href"] for key, entry in table.items()}

    assert definitions(render_inline(decompose(REFS_MD))) == definitions(REFS_MD)


def test_render_map_carries_the_addresses_render_inline_does_not() -> None:
    msg = decompose(REFS_MD)
    assert ".R1" not in render_inline(msg)
    assert ".R1" in render_map(msg)


# --- round-trips over the torture fixture -------------------------------

_STRUCTURAL = frozenset({
    "fence",
    "code_block",
    "html_block",
    "hr",
    "table_open",
    "bullet_list_open",
    "ordered_list_open",
    "blockquote_open",
    "heading_open",
})


_MD_BLOCKS = MarkdownIt("commonmark").enable("table")


def _skeleton(markdown: str) -> list[tuple[str, str]]:
    """Structural tokens in order, with the bytes of every verbatim block — the
    render-and-diff ritual CLAUDE.md mandates, in the parser we already depend on.

    The link reference table is appended because a definition emits **no block
    token at all**. Labeling one turns it into a lazy continuation and every
    `[key]` in the copy silently becomes literal text — breakage a token-only
    skeleton cannot see by construction, whatever the fixture contains.
    """
    env: dict[str, Any] = {}
    tokens = _MD_BLOCKS.parse(markdown, env)
    skeleton = [
        (t.type, t.content if t.type in {"fence", "code_block", "html_block"} else t.tag)
        for t in tokens
        if t.type in _STRUCTURAL
    ]
    references: dict[str, dict[str, str]] = env.get("references", {})
    skeleton.extend(
        ("reference", f"{key} -> {entry['href']}") for key, entry in sorted(references.items())
    )
    return skeleton


def test_labeling_preserves_the_block_skeleton(torture_md: str, torture_msg: Message) -> None:
    source = _skeleton(torture_md)
    labeled = _skeleton(render_inline(torture_msg))
    drift = [(i, a, b) for i, (a, b) in enumerate(zip_longest(source, labeled)) if a != b]
    assert not drift, f"the labeled copy renders differently: {drift}"


def _addresses(entities: tuple[Entity, ...], prefix: str) -> list[tuple[str, Entity]]:
    """Every entity at every depth with its canonical address."""
    out: list[tuple[str, Entity]] = []
    for entity in entities:
        address = f"{prefix}.{type(entity).__name__[0]}{entity.index}"
        out.append((address, entity))
        if isinstance(entity, Section | Quote):
            out.extend(_addresses(entity.entities, address))
    return out


_PRINTED_LABEL_RE = re.compile(r"^(?:#{1,6} )?(?P<label>N\d+-S\d+|\.[A-Z]\d+)(?: (?P<rest>.*))?$")


def _printed_labels(rendered: str) -> list[tuple[str, str]]:
    """Every label in a labeled copy, with the rest of the line it sits on.

    Read out of ``render_inline``'s *output* on purpose. A helper that rebuilt the
    address from the tree — as ``_addresses`` below does — agrees with the resolver
    by construction and so proves nothing about what a reader actually sees.
    """
    found: list[tuple[str, str]] = []
    fenced = False
    for line in rendered.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = _PRINTED_LABEL_RE.match(line)
        if match:
            found.append((match["label"], (match["rest"] or "").strip()))
    return found


def test_every_label_render_inline_prints_resolves_or_refuses(torture_msg: Message) -> None:
    # THE invariant, tested as stated: an address copied off the labeled copy comes
    # back with the block it was sitting next to — or refuses as AMBIGUOUS, naming
    # the candidates. Quietly returning a *different* block is the one outcome the
    # engine exists to rule out. The tree-walk test below cannot see a violation:
    # it never reads a printed label.
    labels = _printed_labels(render_inline(torture_msg))
    assert len(labels) > 20, f"only {len(labels)} labels found — the scan is broken"

    printed = [label for label, _ in labels]
    resolved_count = refused_count = 0
    for label, rest in labels:
        if not label.startswith(".P"):
            continue  # only a paragraph carries its own text on the label's line
        alone = printed.count(label) == 1
        try:
            got = resolve(parse_ref(label, turn=torture_msg.turn), torture_msg)
        except ResolveError as refusal:
            assert alone is False, f"{label} is printed once but will not resolve: {refusal}"
            assert str(refusal).startswith(AMBIGUOUS), f"{label} refused as {refusal}"
            refused_count += 1
            continue
        assert alone, f"{label} is printed {printed.count(label)} times yet resolved silently"
        assert got.content.startswith(rest), (
            f"{label} is printed on {rest!r} but resolves to {got.content[:60]!r}"
        )
        resolved_count += 1
    assert resolved_count and refused_count, (
        "the fixture must exercise both halves — "
        f"{resolved_count} resolved, {refused_count} refused"
    )


def test_every_address_in_the_torture_document_resolves_to_its_own_entity(
    torture_msg: Message,
) -> None:
    # The resolver walks the same tree the decomposer built: a canonical address
    # for every entity at every depth comes back with that entity. Stronger than
    # "must not raise" — an off-by-one inside a blockquote resolves to the wrong
    # block without raising, and only comparing content catches it.
    #
    # It does NOT prove the round-trip invariant: these addresses are built from
    # the tree, not read off the labels. The test above is the one that does.
    checked = 0
    for section in torture_msg.sections:
        for address, entity in _addresses(section.entities, f"N1-S{section.index}"):
            resolved = resolve(parse_ref(address), torture_msg)
            assert resolved.content == resolve_entity(entity, None, None).content, address
            checked += 1
    assert checked > 40, f"the walk covered only {checked} entities"


# --- the viewer ----------------------------------------------------------


def test_the_viewer_shows_both_sides(transcript: Transcript) -> None:
    # A reply with no visible question cannot be searched.
    out = render_transcript(transcript)
    assert "> **you:**" in out
    assert "> First question. Please answer it." in out
    assert ".P1 The first half of the reply." in out


def test_the_viewer_labels_every_reply_and_no_prompt(transcript: Transcript) -> None:
    out = render_transcript(transcript)
    for turn in transcript.turns:
        assert render_inline(turn.message) in out
    quoted = [line for line in out.splitlines() if line.startswith(">")]
    assert quoted and not any(".P1" in line for line in quoted)


def test_a_quoted_prompt_survives_whatever_it_contains() -> None:
    # A fence or a quote inside a prompt just nests; nothing is corrupted.
    quoted = quote_prompt("look:\n\n```py\nx = 1\n```\n\n> and a quote")
    tokens = [t.type for t in _MD_BLOCKS.parse(quoted)]
    assert tokens[0] == "blockquote_open"
    assert "fence" in tokens
    assert "x = 1\n" in [t.content for t in _MD_BLOCKS.parse(quoted)]


def test_the_map_indexes_replies_only(transcript: Transcript) -> None:
    out = render_transcript_map(transcript)
    assert "N1-S1" in out and "N2-S1" in out and "N3-S1" in out
    assert "First question" not in out


def _unlabeled_view(transcript: Transcript) -> str:
    """The same assembly the viewer does, with the raw source in place of the
    labeled render — the baseline a labeled transcript has to match."""
    blocks: list[str] = []
    for entry in transcript.entries:
        blocks.append(entry.message.source if isinstance(entry, Turn) else quote_prompt(entry.text))
    return "\n\n".join(blocks)


def test_the_viewer_still_renders_as_markdown(transcript: Transcript) -> None:
    # The per-message ritual, lifted to the whole conversation: labeling a
    # transcript must not change a single block of what it renders to.
    drift = [
        (i, a, b)
        for i, (a, b) in enumerate(
            zip_longest(
                _skeleton(_unlabeled_view(transcript)), _skeleton(render_transcript(transcript))
            )
        )
        if a != b
    ]
    assert not drift, f"the labeled transcript renders differently: {drift}"


def test_every_address_the_viewer_prints_resolves_across_the_conversation(
    transcript: Transcript,
) -> None:
    # The round-trip invariant at conversation scale: an address read off the
    # viewer resolves with nothing but itself.
    checked = 0
    for turn in transcript.turns:
        for section in turn.message.sections:
            for address, entity in _addresses(
                section.entities, f"N{turn.message.turn}-S{section.index}"
            ):
                got = resolve_in(parse_ref(address), transcript)
                assert got.content == resolve_entity(entity, None, None).content, address
                checked += 1
    assert checked > 5, f"the walk covered only {checked} entities"


# --- per-block labels and linked addresses --------------------------------

BLOCKS = ["# Plan\n\nFirst para.", "- a\n- b\n\nSecond para.", "Tail para."]


def _joined(blocks: list[str], turn: int = 7) -> tuple[Message, list[int]]:
    starts: list[int] = []
    line = 0
    for block in blocks:
        starts.append(line)
        line += block.count("\n") + 2
    return decompose("\n\n".join(blocks), turn=turn), starts


def test_blocks_are_the_whole_turns_labels_cut_at_the_block_boundaries() -> None:
    msg, starts = _joined(BLOCKS)
    labeled = render_blocks(msg, starts)
    assert len(labeled) == len(BLOCKS)
    assert "\n\n".join(labeled) == render_inline(msg)


def test_a_block_carries_only_its_own_labels() -> None:
    msg, starts = _joined(BLOCKS)
    plan, middle, tail = render_blocks(msg, starts)
    assert plan.startswith("# N7-S1 Plan") and ".P1 First para." in plan
    assert middle.startswith(".L1\n- a") and ".P2 Second para." in middle
    assert tail == ".P3 Tail para."


def test_the_default_styles_stay_plain_text() -> None:
    msg, _ = _joined(BLOCKS)
    assert "](" not in render_inline(msg)
    assert "](" not in render_inline(msg, GLYPH)


_LINKED_LABEL_RE = re.compile(
    r"^(?:#{1,6} )?\[(?P<label>[^\]]+)\]\((?P<href>[^)]+)\)(?: (?P<rest>.*))?$"
)


def _linked_labels(rendered: str) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []
    fenced = False
    for line in rendered.splitlines():
        if line.lstrip().startswith("```"):
            fenced = not fenced
            continue
        match = None if fenced else _LINKED_LABEL_RE.match(line)
        if match:
            found.append((match["label"], match["href"], (match["rest"] or "").strip()))
    return found


def test_every_linked_address_resolves_to_the_block_it_labels(torture_msg: Message) -> None:
    # The printed `.P1` is ambiguous on its own; the href is not. Read off the
    # output, as the plain-label invariant above does, and compare content: a
    # link that resolved to a *different* paragraph would raise nothing.
    labels = _linked_labels(render_inline(torture_msg, LINKED))
    assert len(labels) > 20, f"only {len(labels)} linked labels found — the scan is broken"
    paragraphs = 0
    for label, href, rest in labels:
        assert href.startswith(LINK_BASE), href
        address = href.removeprefix(LINK_BASE)
        got = resolve(parse_ref(address), torture_msg)
        if label.startswith(".P"):
            assert got.content.startswith(rest), (
                f"{address} labels {rest!r}, got {got.content[:60]!r}"
            )
            paragraphs += 1
    assert paragraphs > 5


def test_linking_preserves_the_block_skeleton(torture_md: str, torture_msg: Message) -> None:
    source = _skeleton(torture_md)
    labeled = _skeleton(render_inline(torture_msg, LINKED))
    drift = [(i, a, b) for i, (a, b) in enumerate(zip_longest(source, labeled)) if a != b]
    assert not drift, f"the linked copy renders differently: {drift}"


def test_the_link_text_is_the_style_and_the_href_is_always_ascii() -> None:
    msg = decompose("para one.\n", turn=3)
    assert "[N3-S1](" in render_inline(msg, LINKED)
    assert f"[.P1]({LINK_BASE}N3-S1.P1) para one." in render_inline(msg, LINKED)


# --- tables: the label line says how to address a row, a column --------------


def test_a_linked_table_label_offers_every_row_and_column(worked_msg: Message) -> None:
    label = next(
        line for line in render_inline(worked_msg, LINKED).splitlines() if line.startswith("[.T1]")
    )
    link = LINK_BASE + "N27-S1.T1"
    assert label == (
        f"[.T1]({link}) \u00b7 4 rows \u00d7 3 cols"
        f" \u00b7 rows [1]({link}.1) [2]({link}.2) [3]({link}.3) [4]({link}.4)"
        f" \u00b7 cols [1]({link}.,1) [2]({link}.,2) [3]({link}.,3)"
    )


def test_the_plain_styles_do_not_grow_a_table_hint(worked_msg: Message) -> None:
    assert ".T1\n|" in render_inline(worked_msg)
    assert ".T1\n|" in render_inline(worked_msg, GLYPH).replace("\u00b7T1", ".T1")


def test_every_row_and_column_link_resolves_to_what_it_says(torture_msg: Message) -> None:
    rendered = render_inline(torture_msg, LINKED)
    checked = 0
    for line in rendered.splitlines():
        if not line.startswith("[.T"):
            continue
        for href in re.findall(r"\]\(([^)]+)\)", line):
            address = href.removeprefix(LINK_BASE)
            got = resolve(parse_ref(address), torture_msg)
            assert got.content, address
            checked += 1
    assert checked > 3


def test_a_long_table_offers_the_first_rows_and_says_so() -> None:
    body = "\n".join(f"| r{i} | x |" for i in range(40))
    msg = decompose(f"| h | h |\n|---|---|\n{body}\n", turn=2)
    label = next(
        line for line in render_inline(msg, LINKED).splitlines() if line.startswith("[.T1]")
    )
    assert "41 rows" in label
    assert "[20](" in label and "[21](" not in label
    assert "\u2026" in label
