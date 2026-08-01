"""Resolve a parsed :class:`Ref` against a decomposed :class:`Message`.

Walks to the addressed node and returns its content, or raises
:class:`ResolveError` naming the miss. The turn selects *which* message the
address is about, so an address for another turn is a miss here rather than a
confident wrong answer against whatever this message happens to hold.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from reference_points.decompose import (
    CodeBlock,
    Diagram,
    Entity,
    ListBlock,
    Message,
    Paragraph,
    Quote,
    Reference,
    Section,
    Table,
)
from reference_points.grammar import (
    AMBIGUOUS,
    INVALID,
    MISSING,
    REJECTED,
    format_failure,
    location_form,
)

if TYPE_CHECKING:
    from reference_points.grammar import EntityStep, Location, MatchLoc, Ref, TableLoc
    from reference_points.transcript import Transcript

_LETTER_TO_TYPE: dict[str, type[Entity]] = {
    "P": Paragraph,
    "T": Table,
    "L": ListBlock,
    "C": CodeBlock,
    "D": Diagram,
    "R": Reference,
    "Q": Quote,
    "S": Section,
}


class ResolveError(Exception):
    """A well-formed address that points at nothing, at more than one thing, or at
    the wrong shape. ``kind`` and ``hint`` are both required, so no message ships
    uncategorized or without a remedy."""

    def __init__(self, kind: str, message: str, hint: str) -> None:
        super().__init__(format_failure(kind, message, hint))


_SHOWN = 8  # a typo should not paginate the terminal
_SHOWN_WIDTH = 72


def _listing(items: list[str]) -> str:
    """The candidates themselves, indented under the message. Choosing between
    them is impossible without seeing them, which is the whole of an AMBIGUOUS."""
    lines = [f"     {_clip(item)}" for item in items[:_SHOWN]]
    if len(items) > _SHOWN:
        lines.append(f"     … and {len(items) - _SHOWN} more")
    return "\n".join(lines)


def _clip(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= _SHOWN_WIDTH else flat[: _SHOWN_WIDTH - 1] + "…"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _every(match: MatchLoc) -> str:
    return f"(g/{match.text}/)"


@dataclass(frozen=True)
class Resolution:
    """What kind of node, and its content."""

    kind: str
    content: str


def _format_row(cells: tuple[str, ...]) -> str:
    return "| " + " | ".join(cells) + " |"


def _fmt_match(match: MatchLoc) -> str:
    prefix = "g/" if match.every else "/"
    return f"({prefix}{match.text}/)"


def _compile(match: MatchLoc, *, ignore_case: bool = False) -> re.Pattern[str]:
    """``ignore_case`` is for a :class:`Reference`: CommonMark normalizes link
    labels case-insensitively, so ``(/mdit/)`` must name ``[MDIT]``."""
    try:
        return re.compile(match.text, re.IGNORECASE if ignore_case else 0)
    except re.error as err:
        raise ResolveError(
            INVALID,
            f"regex {_fmt_match(match)}: {err}",
            "a match body is a regex — escape the metacharacters you meant "
            r"literally, as in (/\$40/)",
        ) from err


def _apply_match(matches: list[str], match: MatchLoc, scope: str) -> str:
    if not matches:
        raise ResolveError(
            MISSING,
            f"no match for {_fmt_match(match)} in {scope}",
            "matching is case-sensitive; use (/(?i:word)/) to ignore case",
        )
    if match.every:
        return "\n".join(matches)
    if len(matches) > 1:
        raise ResolveError(
            AMBIGUOUS,
            f"{len(matches)} matches for {_fmt_match(match)} in {scope}\n{_listing(matches)}",
            f"use {scope}.{_every(match)} for all {len(matches)}, or narrow the pattern",
        )
    return matches[0]


def _narrow(units: tuple[str, ...], location: Location, kind: str, label: str) -> tuple[str, ...]:
    """Candidates for a content match: the one at ``location``, or all of them.
    Cell/column locations never reach here — the grammar rejects those."""
    if location is None:
        return units
    if not isinstance(location, int) or not 1 <= location <= len(units):
        raise ResolveError(
            MISSING,
            f"no such {kind} {location} in {label}",
            f"{label} has {_plural(len(units), kind)}",
        )
    return (units[location - 1],)


def _match_units(units: tuple[str, ...], match: MatchLoc, kind: str, label: str) -> Resolution:
    pattern = _compile(match)
    hits = [u for u in units if pattern.search(u)]
    return Resolution(kind, _apply_match(hits, match, label))


def _find_section(msg: Message, index: int) -> Section:
    for section in msg.sections:
        if section.index == index:
            return section
    available = ", ".join(f"S{section.index}" for section in msg.sections)
    raise ResolveError(
        MISSING, f"no section {index} in this message", f"this message has {available}"
    )


def _inventory(entities: tuple[Entity, ...]) -> str:
    """What is addressable at this level, in order — the answer to "then what *is*
    here?", which is the only question a missing entity leaves you with."""
    if not entities:
        return "nothing is addressable at this level"
    return "in scope, in order: " + ", ".join(f"{type(e).__name__[0]}{e.index}" for e in entities)


def _find_entity(entities: tuple[Entity, ...], letter: str, index: int) -> Entity:
    expected = _LETTER_TO_TYPE[letter]
    for entity in entities:
        if isinstance(entity, expected) and entity.index == index:
            return entity
    raise ResolveError(MISSING, f"no {letter}{index} here", _inventory(entities))


def _entity_text(entity: Entity) -> str:
    """What a selector match is tested against. A section carries its heading —
    that is what a reader names it by — ahead of its body."""
    body = resolve_entity(entity, None, None).content
    if isinstance(entity, Section) and entity.heading:
        return f"{entity.heading}\n{body}"
    return body


def _select_entities(
    entities: tuple[Entity, ...], step: EntityStep, match: MatchLoc | None
) -> list[Entity]:
    """With no index the match picks among entities of that type: ``(/…/)`` is
    ``AMBIGUOUS`` on more than one hit, ``(g/…/)`` names every hit."""
    if step.index is not None:
        return [_find_entity(entities, step.letter, step.index)]
    if match is None:  # parse_ref forbids this; keep the walk total, never guess
        raise ResolveError(
            REJECTED,
            f"{step.letter} needs an index or a match",
            f"use {step.letter}1, or {step.letter}(/word/) to select it by content",
        )
    expected = _LETTER_TO_TYPE[step.letter]
    pattern = _compile(match, ignore_case=expected is Reference)
    hits = [e for e in entities if isinstance(e, expected) and pattern.search(_entity_text(e))]
    scope = f"the {step.letter} entities here"
    if not hits:
        raise ResolveError(
            MISSING, f"no match for {_fmt_match(match)} in {scope}", _inventory(entities)
        )
    if len(hits) > 1 and not match.every:
        shown = [f"{step.letter}{e.index}  {_entity_text(e)}" for e in hits]
        raise ResolveError(
            AMBIGUOUS,
            f"{len(hits)} matches for {_fmt_match(match)} in {scope}\n{_listing(shown)}",
            f"use {step.letter}{_every(match)} for all {len(hits)}, or address one by index",
        )
    return hits


def _walk(section: Section, ref: Ref) -> list[Entity]:
    """One entity, unless a terminal ``(g/…/)`` selected several — only the terminal
    step may carry a match, so every step descended into names one container."""
    current: list[Entity] = [section]
    entities = section.entities
    for i, step in enumerate(ref.path):
        current = _select_entities(entities, step, ref.match)
        if i < len(ref.path) - 1:
            inner = current[0]
            if not isinstance(inner, Section | Quote):
                raise ResolveError(
                    REJECTED,
                    f"{step.letter}{step.index} is not a container; cannot address inside it",
                    f"use {location_form(step.letter, step.index)}",
                )
            entities = inner.entities
    return current


def _resolve_paragraph(para: Paragraph, location: Location, match: MatchLoc | None) -> Resolution:
    if match is not None:
        units = _narrow(para.sentences, location, "sentence", f"P{para.index}")
        return _match_units(units, match, "sentence", f"P{para.index}")
    if location is None:
        return Resolution("paragraph", para.text)
    if isinstance(location, int):
        if not 1 <= location <= len(para.sentences):
            raise ResolveError(
                MISSING,
                f"no such sentence {location} in P{para.index}",
                f"P{para.index} has {_plural(len(para.sentences), 'sentence')}",
            )
        return Resolution("sentence", para.sentences[location - 1])
    raise ResolveError(
        REJECTED,
        f"P{para.index} takes a sentence number, not a cell reference",
        f"use {location_form('P', para.index)}",
    )


def _table_rows_hint(table: Table) -> str:
    return f"T{table.index} has {_plural(len(table.rows), 'row')}, counting the header as row 1"


def _resolve_table_cell(table: Table, loc: TableLoc) -> Resolution:
    width = len(table.rows[0]) if table.rows else 0
    if loc.col is not None and not 1 <= loc.col <= width:
        raise ResolveError(
            MISSING,
            f"no such column {loc.col} in T{table.index}",
            f"T{table.index} has {_plural(width, 'column')}",
        )
    if loc.row is None:  # whole column
        column = [
            row[loc.col - 1] for row in table.rows if loc.col is not None and loc.col <= len(row)
        ]
        return Resolution("column", "\n".join(column))
    if not 1 <= loc.row <= len(table.rows):
        raise ResolveError(
            MISSING, f"no such row {loc.row} in T{table.index}", _table_rows_hint(table)
        )
    cell = table.rows[loc.row - 1][loc.col - 1] if loc.col is not None else ""
    return Resolution("cell", cell)


def _resolve_table(table: Table, location: Location, match: MatchLoc | None) -> Resolution:
    rows = tuple(_format_row(r) for r in table.rows)
    if match is not None:
        units = _narrow(rows, location, "row", f"T{table.index}")
        return _match_units(units, match, "row", f"T{table.index}")
    if location is None:
        return Resolution("table", "\n".join(rows))
    if isinstance(location, int):
        if not 1 <= location <= len(table.rows):
            raise ResolveError(
                MISSING, f"no such row {location} in T{table.index}", _table_rows_hint(table)
            )
        return Resolution("row", rows[location - 1])
    return _resolve_table_cell(table, location)


def _resolve_indexed(
    entity: ListBlock | CodeBlock | Diagram, location: Location, match: MatchLoc | None
) -> Resolution:
    """A list's items and a verbatim block's or diagram's lines are the same shape:
    a 1-indexed run of strings, addressed by number or matched against."""
    items = entity.items if isinstance(entity, ListBlock) else entity.lines
    kind = "item" if isinstance(entity, ListBlock) else "line"
    letter = type(entity).__name__[0]
    label = f"{letter}{entity.index}"
    if match is not None:
        units = _narrow(items, location, kind, label)
        return _match_units(units, match, kind, label)
    if location is None:
        return Resolution(kind, "\n".join(items))
    if isinstance(location, int):
        if not 1 <= location <= len(items):
            raise ResolveError(
                MISSING,
                f"no such {kind} {location} in {label}",
                f"{label} has {_plural(len(items), kind)}",
            )
        return Resolution(kind, items[location - 1])
    raise ResolveError(
        REJECTED,
        f"{label} takes a single number, not a cell reference",
        f"use {location_form(letter, entity.index)}",
    )


def _resolve_container(entity: Section | Quote, location: Location) -> Resolution:
    if location is not None:  # parse should have rejected this already
        raise ResolveError(
            REJECTED,
            "a container takes no direct location",
            f"use {location_form(type(entity).__name__[0], entity.index)}",
        )
    parts = [resolve_entity(child, None, None).content for child in entity.entities]
    kind = "section" if isinstance(entity, Section) else "quote"
    return Resolution(kind, "\n".join(parts))


def resolve_entity(entity: Entity, location: Location, match: MatchLoc | None) -> Resolution:
    """They compose: the location narrows the scope, the match filters within it."""
    if isinstance(entity, Paragraph):
        return _resolve_paragraph(entity, location, match)
    if isinstance(entity, Table):
        return _resolve_table(entity, location, match)
    if isinstance(entity, ListBlock | CodeBlock | Diagram):
        return _resolve_indexed(entity, location, match)
    if isinstance(entity, Reference):
        return Resolution("reference", entity.text)
    return _resolve_container(entity, location)


def _turn_range(transcript: Transcript) -> str:
    numbers = [turn.message.turn for turn in transcript.turns]
    if not numbers:
        return "this transcript has no replies in it"
    return f"this transcript has N{min(numbers)}\u2013N{max(numbers)}"


def find_turn(transcript: Transcript, number: int) -> Message:
    """The reply an address names, or a loud miss naming the range that exists."""
    for turn in transcript.turns:
        if turn.message.turn == number:
            return turn.message
    raise ResolveError(MISSING, f"no turn N{number} in this transcript", _turn_range(transcript))


def resolve_in(ref: Ref, transcript: Transcript) -> Resolution:
    """Resolve against the whole conversation: the address's own turn picks the
    reply, which is the job ``N`` exists to do."""
    return resolve(ref, find_turn(transcript, ref.turn))


def resolve(ref: Ref, msg: Message) -> Resolution:
    if ref.turn != msg.turn:
        raise ResolveError(
            MISSING,
            f"address is for turn {ref.turn}; this message is turn {msg.turn}",
            f"resolve it against turn {ref.turn}, or re-address it to N{msg.turn}",
        )
    section = _find_section(msg, ref.section if ref.section is not None else 1)
    targets = _walk(section, ref)
    if ref.path and ref.path[-1].index is None:
        # Spent on choosing the entities, the match does not also narrow inside
        # them; a global one joins, as a global location joins its rows.
        parts = [resolve_entity(entity, None, None) for entity in targets]
        return Resolution(parts[0].kind, "\n".join(part.content for part in parts))
    return resolve_entity(targets[0], ref.location, ref.match)
