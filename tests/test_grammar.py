"""Tests for the address grammar: parse_ref and RefError."""

from __future__ import annotations

import pytest

from reference_points.grammar import (
    EntityStep,
    MatchLoc,
    RefError,
    TableLoc,
    parse_ref,
)


def test_parses_canonical_full_address() -> None:
    ref = parse_ref("N27-S1.T2.3")
    assert ref.turn == 27
    assert ref.section == 1
    assert ref.path == (EntityStep("T", 2),)
    assert ref.location == 3


def test_missing_turn_is_rejected_with_named_defect() -> None:
    with pytest.raises(RefError, match="missing turn number"):
        parse_ref("S1.P1")


# --- valid forms ---------------------------------------------------------


def test_bare_turn_addresses_the_whole_turn() -> None:
    ref = parse_ref("N27")
    assert ref.turn == 27
    assert ref.section is None
    assert ref.path == ()
    assert ref.location is None


def test_turn_and_section_addresses_the_whole_section() -> None:
    ref = parse_ref("N27-S1")
    assert ref.turn == 27
    assert ref.section == 1
    assert ref.path == ()


def test_section_is_optional() -> None:
    ref = parse_ref("N27.P2")
    assert ref.turn == 27
    assert ref.section is None
    assert ref.path == (EntityStep("P", 2),)


def test_cell_location_row_and_col() -> None:
    assert parse_ref("N27-S1.T2.3,4").location == TableLoc(3, 4)


def test_column_only_location() -> None:
    assert parse_ref("N27-S1.T2.,4").location == TableLoc(None, 4)


def test_paragraph_sentence_location_is_an_int() -> None:
    assert parse_ref("N27-S1.P1.4").location == 4


def test_single_match_string() -> None:
    ref = parse_ref("N27-S1.T2.(/scheme/)")
    assert ref.match == MatchLoc("scheme", every=False)
    assert ref.location is None


def test_global_match_string() -> None:
    ref = parse_ref("N27-S1.T2.(g/scheme/)")
    assert ref.match == MatchLoc("scheme", every=True)
    assert ref.location is None


def test_match_string_may_contain_dots() -> None:
    assert parse_ref("N1-S1.P1.(/3.5 tiers/)").match == MatchLoc("3.5 tiers", every=False)


def test_location_and_match_compose() -> None:
    # `[location]` and `[regex]` are orthogonal, separate fields — they compose.
    ref = parse_ref("N27-S1.P1.2(/foo/)")
    assert ref.location == 2
    assert ref.match == MatchLoc("foo", every=False)


def test_match_on_cell_reference_is_rejected() -> None:
    with pytest.raises(RefError, match="cannot compose with a cell or column"):
        parse_ref("N1-S1.T2.3,4(/x/)")


def test_match_binds_without_a_dot() -> None:
    # `p1(/rx/)` is the canonical no-dot form; the dot is optional/tolerated.
    assert parse_ref("N1-S1.P1(/x/)") == parse_ref("N1-S1.P1.(/x/)")


def test_global_match_binds_without_a_dot() -> None:
    assert parse_ref("N1-S1.T2(g/scheme/)") == parse_ref("N1-S1.T2.(g/scheme/)")


def test_nested_container_path() -> None:
    ref = parse_ref("N1-S1.Q1.P1.2")
    assert ref.path == (EntityStep("Q", 1), EntityStep("P", 1))
    assert ref.location == 2


def test_nested_subsection_path() -> None:
    ref = parse_ref("N1-S1.S2.P1")
    assert ref.path == (EntityStep("S", 2), EntityStep("P", 1))
    assert ref.location is None


def test_glyph_form_equivalent_to_ascii() -> None:
    assert parse_ref("◆27 §1 ·T2") == parse_ref("N27-S1.T2")


def test_glyph_form_with_location() -> None:
    assert parse_ref("◆27 §1 ·T2.3,4") == parse_ref("N27-S1.T2.3,4")


# --- rejections ----------------------------------------------------------


def test_diagram_with_location_is_rejected() -> None:
    with pytest.raises(RefError, match="D1 takes no location"):
        parse_ref("N1-S1.D1.2")


def test_cell_reference_on_paragraph_is_rejected() -> None:
    with pytest.raises(RefError, match="single number"):
        parse_ref("N1-S1.P1.3,4")


def test_unknown_entity_letter_is_rejected() -> None:
    with pytest.raises(RefError, match="unknown entity"):
        parse_ref("N1-S1.X1")


def test_container_with_bare_location_is_rejected() -> None:
    with pytest.raises(RefError, match="container"):
        parse_ref("N1-S1.Q1.3")


def test_location_without_entity_is_rejected() -> None:
    with pytest.raises(RefError, match="needs an entity"):
        parse_ref("N27.3")


def test_two_locations_are_rejected() -> None:
    with pytest.raises(RefError, match="final part"):
        parse_ref("N1-S1.T2.3.4")


def test_empty_match_string_is_rejected() -> None:
    with pytest.raises(RefError, match="empty match"):
        parse_ref("N1-S1.T2.(//)")


def test_stray_dash_is_rejected() -> None:
    with pytest.raises(RefError):
        parse_ref("N1-S1.P1-S2")
