"""Tests for resolving an address against a decomposed message."""

from __future__ import annotations

import pytest

from reference_points.decompose import Message, decompose
from reference_points.grammar import RefError, parse_ref
from reference_points.resolve import ResolveError, resolve


def test_resolves_a_paragraph_sentence(worked_msg: Message) -> None:
    result = resolve(parse_ref("N27-S1.P1.2"), worked_msg)
    assert result.content == "Here is the current breakdown."


def test_out_of_range_sentence_fails_loudly(worked_msg: Message) -> None:
    with pytest.raises(ResolveError, match="no such sentence 9"):
        resolve(parse_ref("N27-S1.P1.9"), worked_msg)


# --- tables --------------------------------------------------------------


def test_resolves_a_table_row(worked_msg: Message) -> None:
    assert resolve(parse_ref("N27-S1.T1.4"), worked_msg).content == "| Team | $40 | 20 |"


def test_resolves_a_table_cell(worked_msg: Message) -> None:
    assert resolve(parse_ref("N27-S1.T1.4,2"), worked_msg).content == "$40"


def test_resolves_a_whole_column(worked_msg: Message) -> None:
    assert resolve(parse_ref("N27-S1.T1.,2"), worked_msg).content == "Price\n$0\n$12\n$40"


def test_resolves_a_row_by_unique_match(worked_msg: Message) -> None:
    assert resolve(parse_ref("N27-S1.T1.(/Team/)"), worked_msg).content == "| Team | $40 | 20 |"


def test_ambiguous_single_match_fails_loudly(worked_msg: Message) -> None:
    # `$` is an end-anchor under regex; the literal dollar is `\$`.
    with pytest.raises(ResolveError, match="AMBIGUOUS: 3 matches"):
        resolve(parse_ref(r"N27-S1.T1.(/\$/)"), worked_msg)


def test_global_match_returns_every_row(worked_msg: Message) -> None:
    content = resolve(parse_ref(r"N27-S1.T1.(g/\$/)"), worked_msg).content
    assert content == "| Free | $0 | 1 |\n| Pro | $12 | 5 |\n| Team | $40 | 20 |"


def test_no_match_fails_loudly(worked_msg: Message) -> None:
    with pytest.raises(ResolveError, match="no match"):
        resolve(parse_ref("N27-S1.T1.(/nonesuch/)"), worked_msg)


def test_regex_metacharacter_matches(worked_msg: Message) -> None:
    # A regex, so `.` is any-char.
    assert resolve(parse_ref("N27-S1.T1.(/F.ee/)"), worked_msg).content == "| Free | $0 | 1 |"


def test_match_is_case_sensitive(worked_msg: Message) -> None:
    # No implicit `i` flag.
    with pytest.raises(ResolveError, match="no match"):
        resolve(parse_ref("N27-S1.T1.(/free/)"), worked_msg)


def test_inline_flag_enables_case_insensitivity(worked_msg: Message) -> None:
    # Flags ride inside the pattern.
    assert resolve(parse_ref("N27-S1.T1.(/(?i:free)/)"), worked_msg).content == "| Free | $0 | 1 |"


def test_invalid_regex_fails_loudly(worked_msg: Message) -> None:
    with pytest.raises(ResolveError, match=r"INVALID: regex"):
        resolve(parse_ref("N27-S1.T1.(/[/)"), worked_msg)


def test_location_and_match_compose_within_a_sentence(worked_msg: Message) -> None:
    # The location narrows first, then the regex matches within it.
    assert (
        resolve(parse_ref("N27-S1.P1.2(/current/)"), worked_msg).content
        == "Here is the current breakdown."
    )


def test_composed_match_that_misses_the_located_scope_fails(worked_msg: Message) -> None:
    # "tiers" lives in sentence 1, so scoping to sentence 2 is a loud no-match.
    with pytest.raises(ResolveError, match="no match"):
        resolve(parse_ref("N27-S1.P1.2(/tiers/)"), worked_msg)


def test_location_and_match_compose_within_a_table_row(worked_msg: Message) -> None:
    assert resolve(parse_ref("N27-S1.T1.2(/Free/)"), worked_msg).content == "| Free | $0 | 1 |"


def test_composed_match_that_misses_the_located_row_fails(worked_msg: Message) -> None:
    with pytest.raises(ResolveError, match="no match"):
        resolve(parse_ref("N27-S1.T1.2(/Team/)"), worked_msg)


def test_out_of_range_row_fails_loudly(worked_msg: Message) -> None:
    with pytest.raises(ResolveError, match="no such row 9"):
        resolve(parse_ref("N27-S1.T1.9"), worked_msg)


# --- paragraphs & sections ----------------------------------------------


def test_resolves_second_paragraph_first_sentence(worked_msg: Message) -> None:
    result = resolve(parse_ref("N27-S1.P2.1"), worked_msg)
    assert result.content == "Enterprise pricing is negotiated separately."


def test_whole_paragraph_with_no_location(worked_msg: Message) -> None:
    result = resolve(parse_ref("N27-S1.P1"), worked_msg)
    assert result.content == (
        "The pricing tiers changed last quarter. Here is the current breakdown."
    )


# --- missing targets -----------------------------------------------------


def test_missing_section_fails_loudly(worked_msg: Message) -> None:
    with pytest.raises(ResolveError, match="no section 5"):
        resolve(parse_ref("N27-S5.P1"), worked_msg)


def test_missing_entity_fails_loudly(worked_msg: Message) -> None:
    with pytest.raises(ResolveError, match="no T2 here"):
        resolve(parse_ref("N27-S1.T2"), worked_msg)


def test_descending_into_a_leaf_fails_loudly(worked_msg: Message) -> None:
    with pytest.raises(ResolveError, match="not a container"):
        resolve(parse_ref("N27-S1.P1.T1"), worked_msg)


# --- code, lists, blockquotes -------------------------------------------


def test_resolves_a_code_line() -> None:
    msg = decompose("```python\na = 1\nb = 2\nc = 3\n```\n")
    assert resolve(parse_ref("N1-S1.C1.2"), msg).content == "b = 2"


def test_resolves_a_line_of_an_indented_code_block() -> None:
    msg = decompose("alpha.\n\n    indented line one\n    indented line two\n")
    assert resolve(parse_ref("N1-S1.C1.2"), msg).content == "indented line two"


def test_resolves_an_html_line_by_match() -> None:
    msg = decompose("<details>\n<summary>Click to expand</summary>\n")
    result = resolve(parse_ref("N1-S1.C1.(/summary/)"), msg)
    assert result.content == "<summary>Click to expand</summary>"


def test_a_verbatim_block_is_not_addressable_as_prose() -> None:
    # Prose treatment would join its lines into a "sentence".
    msg = decompose("<details>\n<summary>Click to expand</summary>\n")
    with pytest.raises(ResolveError, match="no P1 here"):
        resolve(parse_ref("N1-S1.P1"), msg)


def test_resolves_a_list_item() -> None:
    msg = decompose("- alpha\n- beta\n- gamma\n")
    assert resolve(parse_ref("N1-S1.L1.3"), msg).content == "gamma"


def test_resolves_a_sentence_nested_in_a_blockquote() -> None:
    msg = decompose("> The claim stands. It is supported.\n")
    assert resolve(parse_ref("N1-S1.Q1.P1.2"), msg).content == "It is supported."


# --- link reference definitions -----------------------------------------

REFS_MD = """\
Body text with [mdit] and [spec].

[mdit]: https://github.com/executablebooks/markdown-it-py "The parser"
[spec]: https://spec.commonmark.org
"""


def test_a_reference_resolves_to_its_definition() -> None:
    msg = decompose(REFS_MD)
    content = resolve(parse_ref("N1-S1.R1"), msg).content
    assert content == '[MDIT]: https://github.com/executablebooks/markdown-it-py "The parser"'


def test_index_and_key_name_the_same_reference() -> None:
    msg = decompose(REFS_MD)
    by_index = resolve(parse_ref("N1-S1.R1"), msg).content
    by_key = resolve(parse_ref("N1-S1.R(/mdit/)"), msg).content
    assert by_index == by_key


def test_a_reference_selector_matches_the_destination_too() -> None:
    # One match against the whole definition; no special case for key vs URL.
    msg = decompose(REFS_MD)
    assert resolve(parse_ref("N1-S1.R(/commonmark/)"), msg).content.startswith("[SPEC]:")


def test_a_reference_selector_is_case_insensitive_like_a_link_label() -> None:
    msg = decompose(REFS_MD)
    assert resolve(parse_ref("N1-S1.R(/MdIt/)"), msg).content.startswith("[MDIT]:")


def test_a_selector_hitting_two_definitions_fails_loudly() -> None:
    msg = decompose(REFS_MD)
    with pytest.raises(ResolveError, match="AMBIGUOUS: 2 matches"):
        resolve(parse_ref("N1-S1.R(/https/)"), msg)


def test_a_global_selector_returns_every_matching_reference() -> None:
    msg = decompose(REFS_MD)
    content = resolve(parse_ref("N1-S1.R(g/https/)"), msg).content
    assert content == (
        '[MDIT]: https://github.com/executablebooks/markdown-it-py "The parser"\n'
        "[SPEC]: https://spec.commonmark.org"
    )


def test_a_global_selector_works_for_any_letter(worked_msg: Message) -> None:
    content = resolve(parse_ref("N27-S1.P(g/pricing/)"), worked_msg).content
    assert content == (
        "The pricing tiers changed last quarter. Here is the current breakdown.\n"
        "Enterprise pricing is negotiated separately."
    )


def test_a_selector_that_hits_nothing_fails_loudly() -> None:
    msg = decompose(REFS_MD)
    with pytest.raises(ResolveError, match="no match"):
        resolve(parse_ref("N1-S1.R(/nonesuch/)"), msg)


def test_reference_lookup_is_section_scoped() -> None:
    msg = decompose("# One\n\n[a]: https://a\n\n# Two\n\n[b]: https://b\n")
    assert resolve(parse_ref("N1-S2.R(/b/)"), msg).content == "[B]: https://b"
    with pytest.raises(ResolveError, match="no match"):
        resolve(parse_ref("N1-S1.R(/b/)"), msg)


def test_a_match_selects_a_paragraph_by_its_content(worked_msg: Message) -> None:
    # Not R-specific: any letter may be selected by match.
    result = resolve(parse_ref("N27-S1.P(/Enterprise/)"), worked_msg)
    assert result.content == "Enterprise pricing is negotiated separately."


def test_a_match_selects_a_subsection_by_its_heading() -> None:
    # A reader names a section by its heading, so the selector has to see it.
    msg = decompose("# Doc\n\nintro.\n\n## Costs\n\nThe tiers changed.\n")
    assert resolve(parse_ref("N1-S1.S(/Costs/)"), msg).content == "The tiers changed."


# --- the failure vocabulary ----------------------------------------------

FAILURES = [
    ("S1.P1", "REJECTED"),  # no turn
    ("N1-S1.D1.2", "REJECTED"),  # a diagram takes no location
    ("N1-S1.P1.T1", "REJECTED"),  # descending into a leaf
    ("N1-S1.T1.(/[/)", "INVALID"),  # the regex, not the address
    ("N1-S9.P1", "MISSING"),  # no such section
    ("N1-S1.T2", "MISSING"),  # no such entity
    ("N1-S1.T1.9", "MISSING"),  # no such row
    ("N1-S1.T1.(/nonesuch/)", "MISSING"),  # nothing matched
    (r"N1-S1.T1.(/\$/)", "AMBIGUOUS"),  # more than one match
]


@pytest.mark.parametrize(("address", "prefix"), FAILURES)
def test_every_failure_names_its_category(worked_msg: Message, address: str, prefix: str) -> None:
    # A caller sorts "you typed it wrong" from "it is not there" on the prefix
    # alone, so every message has to carry one.
    with pytest.raises((RefError, ResolveError)) as caught:
        resolve(parse_ref(address), worked_msg)
    assert str(caught.value).startswith(f"{prefix}: ")


@pytest.mark.parametrize(("address", "prefix"), FAILURES)
def test_every_failure_says_what_to_type_instead(
    worked_msg: Message, address: str, prefix: str
) -> None:
    # A rejection that does not end in a next address leaves the caller guessing,
    # which is the thing this grammar exists to stop.
    with pytest.raises((RefError, ResolveError)) as caught:
        resolve(parse_ref(address), worked_msg)
    hint = str(caught.value).split("\n  -> ")
    assert len(hint) == 2, f"{prefix} for {address!r} carries no hint"
    assert hint[1].strip(), f"{prefix} for {address!r} carries an empty hint"


def test_a_missing_entity_lists_what_is_in_scope(worked_msg: Message) -> None:
    with pytest.raises(ResolveError, match=r"in scope, in order: P1, T1, P2"):
        resolve(parse_ref("N27-S1.T2"), worked_msg)


def test_an_out_of_range_row_says_how_many_there_are(worked_msg: Message) -> None:
    with pytest.raises(ResolveError, match=r"T1 has 4 rows, counting the header as row 1"):
        resolve(parse_ref("N27-S1.T1.9"), worked_msg)


def test_an_ambiguous_match_shows_the_matches_it_found(worked_msg: Message) -> None:
    # Choosing between them is impossible without seeing them.
    with pytest.raises(ResolveError) as caught:
        resolve(parse_ref(r"N27-S1.T1.(/\$/)"), worked_msg)
    shown = str(caught.value).splitlines()
    assert shown[0] == r"AMBIGUOUS: 3 matches for (/\$/) in T1"
    assert [line.strip() for line in shown[1:4]] == [
        "| Free | $0 | 1 |",
        "| Pro | $12 | 5 |",
        "| Team | $40 | 20 |",
    ]
    assert shown[4] == r"  -> use T1.(g/\$/) for all 3, or narrow the pattern"


def test_an_ambiguous_listing_is_capped() -> None:
    rows = "\n".join(f"| row {n} | x |" for n in range(1, 21))
    msg = decompose(f"| a | b |\n|---|---|\n{rows}\n")
    with pytest.raises(ResolveError, match=r"… and 12 more"):
        resolve(parse_ref("N1-S1.T1.(/row/)"), msg)
