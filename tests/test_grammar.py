"""Tests for the address grammar: parse_ref and RefError."""

from __future__ import annotations

import pytest

from reference_points.grammar import (
    EntityStep,
    MatchLoc,
    RefError,
    TableLoc,
    find_refs,
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
    # Orthogonal, separate fields — they compose.
    ref = parse_ref("N27-S1.P1.2(/foo/)")
    assert ref.location == 2
    assert ref.match == MatchLoc("foo", every=False)


def test_match_on_cell_reference_is_rejected() -> None:
    with pytest.raises(RefError, match="cannot compose with a cell or column"):
        parse_ref("N1-S1.T2.3,4(/x/)")


def test_match_binds_without_a_dot() -> None:
    # The no-dot form is canonical; the dot is tolerated.
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


def test_reference_entity_parses() -> None:
    assert parse_ref("N1-S1.R1").path == (EntityStep("R", 1),)


def test_a_match_may_select_the_entity_instead_of_an_index() -> None:
    ref = parse_ref("N1-S1.R(/mdit/)")
    assert ref.path == (EntityStep("R", None),)
    assert ref.match == MatchLoc("mdit", every=False)
    assert ref.location is None


def test_entity_selection_by_match_is_not_reference_specific() -> None:
    # The same relaxation for every letter.
    ref = parse_ref("N1-S1.P(/caching/)")
    assert ref.path == (EntityStep("P", None),)
    assert ref.match == MatchLoc("caching", every=False)


def test_a_global_match_may_select_entities() -> None:
    # `g` means "every match in scope" here as anywhere else.
    ref = parse_ref("N1-S1.R(g/https/)")
    assert ref.path == (EntityStep("R", None),)
    assert ref.match == MatchLoc("https", every=True)


def test_glyph_form_equivalent_to_ascii() -> None:
    assert parse_ref("◆27 §1 ·T2") == parse_ref("N27-S1.T2")


def test_glyph_form_with_location() -> None:
    assert parse_ref("◆27 §1 ·T2.3,4") == parse_ref("N27-S1.T2.3,4")


def test_a_match_body_is_never_glyph_folded() -> None:
    # The pattern is the user's, verbatim. Folding · to . widens it to "any
    # character" and § to -S rewrites it outright — a silently different regex,
    # matching text the address never asked for.
    for raw, pattern in (("N1-S1.P1(/a·b/)", "a·b"), ("N1-S1.P1(/§40/)", "§40")):
        ref = parse_ref(raw)
        assert ref.match is not None
        assert ref.match.text == pattern


def test_a_glyph_address_still_folds_around_its_match() -> None:
    # Only the body is off limits; the address in front of it still normalizes.
    assert parse_ref("◆27 §1 ·T2(/Team/)") == parse_ref("N27-S1.T2(/Team/)")


# --- rejections ----------------------------------------------------------


def test_reference_definition_with_location_is_rejected() -> None:
    # R is the only letter with nothing to point into: it renders to nothing.
    with pytest.raises(RefError, match="R1 takes no location"):
        parse_ref("N1-S1.R1.2")


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


def test_reference_with_location_is_rejected() -> None:
    with pytest.raises(RefError, match="R1 takes no location"):
        parse_ref("N1-S1.R1.2")


def test_entity_without_an_index_or_a_match_is_rejected() -> None:
    with pytest.raises(RefError, match="needs an index"):
        parse_ref("N1-S1.P")


def test_only_the_terminal_step_may_be_selected_by_a_match() -> None:
    with pytest.raises(RefError, match="needs an index"):
        parse_ref("N1-S1.Q.P1(/x/)")


def test_a_match_selected_entity_takes_no_location() -> None:
    with pytest.raises(RefError, match="takes no location"):
        parse_ref("N1-S1.P.2(/x/)")


def test_stray_dash_is_rejected() -> None:
    with pytest.raises(RefError):
        parse_ref("N1-S1.P1-S2")


def test_an_unknown_letter_lists_the_ones_that_exist() -> None:
    with pytest.raises(RefError, match=r"P paragraph, T table"):
        parse_ref("N1-S1.X1")


def test_a_container_hint_names_a_legal_way_in() -> None:
    with pytest.raises(RefError, match=r"use Q1\.P1 for a paragraph inside it"):
        parse_ref("N1-S1.Q1.3")


def test_a_diagram_takes_a_line_like_any_other_fence() -> None:
    assert parse_ref("N1-S1.D1.3").location == 3


def test_a_cell_reference_on_a_diagram_is_rejected() -> None:
    with pytest.raises(RefError, match=r"D1 takes a single number"):
        parse_ref("N1-S1.D1.3,2")


# --- finding addresses in free text -------------------------------------


def test_find_refs_picks_full_addresses_out_of_prose() -> None:
    refs = find_refs("Compare N27-S1.T2.3 with N3.P2 please")
    assert [r.raw for r in refs] == ["N27-S1.T2.3", "N3.P2"]


def test_find_refs_leaves_prose_that_merely_starts_with_n_alone() -> None:
    # A bare turn is a legal address but not a recognizable one: "N2 gas" and
    # "N95 masks" are not citations, and a prompt must not be hijacked by them.
    assert find_refs("N2 gas, N95 masks, and N1-ish things") == ()


def test_find_refs_strips_the_punctuation_a_sentence_puts_after_an_address() -> None:
    refs = find_refs("See N1-S1.P2. Then (N2-S1.L1), and N3-S2.P1, finally N4.P1?")
    assert [r.raw for r in refs] == ["N1-S1.P2", "N2-S1.L1", "N3-S2.P1", "N4.P1"]


def test_find_refs_keeps_a_match_location_whole() -> None:
    (ref,) = find_refs("what about N5-S1.P1.(/two words/) there")
    assert ref.raw == "N5-S1.P1.(/two words/)"
    assert ref.match == MatchLoc("two words", every=False)


def test_find_refs_reads_the_glyph_style_without_separator_spaces() -> None:
    (ref,) = find_refs("see \u25c627\u00a71\u00b7P2")
    assert (ref.turn, ref.section, ref.path) == (27, 1, (EntityStep("P", 2),))


def test_find_refs_reports_each_address_once_in_order() -> None:
    refs = find_refs("N1.P1 then N2.P1 then N1.P1 again")
    assert [r.raw for r in refs] == ["N1.P1", "N2.P1"]


def test_find_refs_fails_loud_on_an_address_shaped_token_that_does_not_parse() -> None:
    with pytest.raises(RefError, match="unknown entity 'X'"):
        find_refs("look at N1-S1.X1 for me")


def test_find_refs_ignores_a_token_glued_to_a_word() -> None:
    assert find_refs("version-N1.P1 and ABN2-S1.P1") == ()


def test_find_refs_reads_an_address_wrapped_in_markdown_or_quotes() -> None:
    for wrapped in (
        "`N1-S1.P2`",
        "**N1-S1.P2**",
        '"N1-S1.P2"',
        "[N1-S1.P2]",
        "N1-S1.P2's",
        "N1-S1.P2\u2014x",
    ):
        assert [r.raw for r in find_refs(f"see {wrapped} here")] == ["N1-S1.P2"], wrapped


def test_find_refs_does_not_take_a_filename_for_an_address() -> None:
    assert find_refs("open N1.md, N2.Net and N5.py now") == ()


def test_find_refs_reads_the_spaced_glyph_style_the_labels_print() -> None:
    (ref,) = find_refs("quote \u25c627 \u00a71 \u00b7T2.3,4 for me")
    assert ref == parse_ref("N27-S1.T2.3,4")


def test_find_refs_reads_every_location_form() -> None:
    forms = [
        "N1-S1.T2.3,4",
        "N1-S1.T2.,4",
        "N1-S1.P1.2",
        "N1-S1.Q1.P2",
        "N1-S1.P1.2(/a b/)",
        "N1-S1.T2(g/x/)",
    ]
    assert [r.raw for r in find_refs("; ".join(forms) + ".")] == forms


@pytest.mark.parametrize(
    "written", ["N3-S1.P1.2-4", "N3-S1.T1.2,3,4", "N3-S1.P1.2.5", "N3-S1.P1.*", "N3-S1.R1.foo"]
)
def test_find_refs_never_resolves_a_prefix_of_what_was_written(written: str) -> None:
    # The valid-looking front of a malformed address is not what the writer cited.
    with pytest.raises(RefError):
        find_refs(f"see {written} please")


def test_find_refs_still_splits_addresses_run_together_with_a_comma() -> None:
    assert [r.raw for r in find_refs("compare N1-S1.P1,N1-S1.P2 now")] == ["N1-S1.P1", "N1-S1.P2"]
