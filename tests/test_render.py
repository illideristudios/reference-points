"""Tests for rendering: inline labels (golden) and the address map."""

from __future__ import annotations

from reference_points.decompose import Message, decompose
from reference_points.grammar import parse_ref
from reference_points.render import GLYPH, render_inline, render_map
from reference_points.resolve import resolve

GOLDEN_INLINE = """\
N27-S1 Costs

.P1 The pricing tiers changed last quarter. Here is the current breakdown.

.T1
| Tier | Price | Seats |
|------|-------|-------|
| Free | $0 | 1 |
| Pro | $12 | 5 |
| Team | $40 | 20 |

.P2 Enterprise pricing is negotiated separately."""


def test_render_inline_matches_the_golden_worked_example(worked_msg: Message) -> None:
    assert render_inline(worked_msg, turn=27) == GOLDEN_INLINE


def test_message_with_no_heading_gets_a_turn_marker() -> None:
    msg = decompose("First paragraph here.\n\nSecond paragraph here.\n")
    out = render_inline(msg, turn=3)
    assert out.splitlines()[0] == "N3-S1"
    assert ".P1 First paragraph here." in out
    assert ".P2 Second paragraph here." in out


def test_render_map_lists_every_addressable_block(worked_msg: Message) -> None:
    out = render_map(worked_msg, turn=27)
    assert "N27-S1 Costs" in out
    assert ".P1" in out
    assert ".T1" in out
    assert ".P2" in out


def test_glyph_style_renders_the_alternate_marker_set(worked_msg: Message) -> None:
    out = render_inline(worked_msg, turn=27, style=GLYPH)
    assert out.splitlines()[0] == "◆27 §1 Costs"
    assert "·P1 The pricing tiers changed last quarter." in out
    assert "·T1" in out


def test_glyph_style_applies_to_the_map_too(worked_msg: Message) -> None:
    out = render_map(worked_msg, turn=27, style=GLYPH)
    assert "◆27 §1 Costs" in out
    assert "·P1" in out


def test_glyph_labels_resolve_back(worked_msg: Message) -> None:
    # The round-trip invariant must hold in whichever style emitted the label.
    out = render_inline(worked_msg, turn=27, style=GLYPH)
    assert out.splitlines()[0] == "◆27 §1 Costs"
    assert resolve(parse_ref("◆27 §1 ·T1.4,2"), worked_msg).content == "$40"


def test_glyph_addresses_still_parse(worked_msg: Message) -> None:
    # Labels are ASCII now, but old transcripts are full of glyph-form addresses.
    assert resolve(parse_ref("◆27 §1 ·T1.4,2"), worked_msg).content == "$40"


def test_every_emitted_label_resolves_back(worked_msg: Message) -> None:
    # Round-trip invariant: the canonical address of every leaf entity resolves.
    for section in worked_msg.sections:
        for entity in section.entities:
            letter = type(entity).__name__[0]
            address = f"N27-S{section.index}.{letter}{entity.index}"
            resolve(parse_ref(address), worked_msg)  # must not raise
