"""Tests for the message decomposer and sentence splitter."""

from __future__ import annotations

from reference_points.decompose import (
    CodeBlock,
    Diagram,
    ListBlock,
    Paragraph,
    Quote,
    Section,
    Table,
    decompose,
    split_sentences,
)


def test_split_sentences_handles_terminal_and_internal_punctuation() -> None:
    assert split_sentences("First one. Second one! A third? Yes.") == (
        "First one.",
        "Second one!",
        "A third?",
        "Yes.",
    )


def test_split_sentences_does_not_split_on_a_decimal_point() -> None:
    assert split_sentences("The tier costs $3.50 per seat.") == ("The tier costs $3.50 per seat.",)


def test_single_paragraph_is_one_section_one_paragraph() -> None:
    msg = decompose("The pricing tiers changed last quarter. Here is the breakdown.")
    assert len(msg.sections) == 1
    section = msg.sections[0]
    assert section.index == 1
    assert len(section.entities) == 1
    para = section.entities[0]
    assert isinstance(para, Paragraph)
    assert para.index == 1
    assert para.sentences == (
        "The pricing tiers changed last quarter.",
        "Here is the breakdown.",
    )


WORKED = """\
## Costs

The pricing tiers changed last quarter. Here is the current breakdown.

| Tier | Price | Seats |
|------|-------|-------|
| Free | $0 | 1 |
| Pro | $12 | 5 |
| Team | $40 | 20 |

Enterprise pricing is negotiated separately.
"""


def test_heading_becomes_a_named_section() -> None:
    msg = decompose(WORKED)
    assert len(msg.sections) == 1
    assert msg.sections[0].heading == "Costs"
    assert msg.sections[0].index == 1


def test_worked_example_entity_order_and_types() -> None:
    entities = decompose(WORKED).sections[0].entities
    assert [type(e) for e in entities] == [Paragraph, Table, Paragraph]
    assert [e.index for e in entities] == [1, 1, 2]  # P1, T1, P2


def test_table_rows_include_header_exclude_separator() -> None:
    table = decompose(WORKED).sections[0].entities[1]
    assert isinstance(table, Table)
    assert table.rows == (
        ("Tier", "Price", "Seats"),
        ("Free", "$0", "1"),
        ("Pro", "$12", "5"),
        ("Team", "$40", "20"),
    )


def test_second_paragraph_gets_index_two() -> None:
    entities = decompose(WORKED).sections[0].entities
    para2 = entities[2]
    assert isinstance(para2, Paragraph)
    assert para2.index == 2
    assert para2.text == "Enterprise pricing is negotiated separately."


def test_fenced_code_block_is_line_addressable() -> None:
    md = "Here:\n\n```python\nx = 1\ny = 2\n```\n"
    entities = decompose(md).sections[0].entities
    code = entities[1]
    assert isinstance(code, CodeBlock)
    assert code.lang == "python"
    assert code.lines == ("x = 1", "y = 2")


def test_mermaid_fence_is_a_diagram_not_code() -> None:
    md = "```mermaid\ngraph TD\nA-->B\n```\n"
    entity = decompose(md).sections[0].entities[0]
    assert isinstance(entity, Diagram)
    assert entity.index == 1


def test_list_items_are_indexed() -> None:
    md = "Steps:\n\n- first\n- second\n- third\n"
    entities = decompose(md).sections[0].entities
    lst = entities[1]
    assert isinstance(lst, ListBlock)
    assert lst.items == ("first", "second", "third")


def test_blockquote_is_a_container_of_inner_entities() -> None:
    md = "> The quoted claim stands. It is well supported.\n"
    quote = decompose(md).sections[0].entities[0]
    assert isinstance(quote, Quote)
    inner = quote.entities[0]
    assert isinstance(inner, Paragraph)
    assert inner.sentences == ("The quoted claim stands.", "It is well supported.")


def test_nested_subsection_is_a_section_entity() -> None:
    md = "## Top\n\nIntro para.\n\n### Sub\n\nDeep para.\n"
    top = decompose(md).sections[0]
    assert top.heading == "Top"
    sub = [e for e in top.entities if isinstance(e, Section)]
    assert len(sub) == 1
    assert sub[0].heading == "Sub"
    assert sub[0].index == 1


def test_preamble_before_first_heading_is_implicit_section_one() -> None:
    md = "Intro sentence.\n\n## Real Heading\n\nBody.\n"
    msg = decompose(md)
    assert len(msg.sections) == 2
    assert not msg.sections[0].heading  # implicit S1 has an empty heading
    assert msg.sections[0].level == 0
    assert msg.sections[1].heading == "Real Heading"
