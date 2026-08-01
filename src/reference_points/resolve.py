"""Resolve a parsed :class:`Ref` against a decomposed :class:`Message`.

Walks the decomposition to the addressed node and returns its content, or raises
:class:`ResolveError` naming the miss (out of range, no match, ambiguous). The
turn number is the caller's concern — it selects *which* message to decompose;
resolution works within that one message via section · path · location.
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

if TYPE_CHECKING:
    from reference_points.grammar import EntityStep, Location, MatchLoc, Ref, TableLoc

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
    """Raised when a well-formed address points at nothing (or at more than one thing)."""


@dataclass(frozen=True)
class Resolution:
    """A successful lookup: what kind of node, and its content."""

    kind: str
    content: str


def _format_row(cells: tuple[str, ...]) -> str:
    return "| " + " | ".join(cells) + " |"


def _fmt_match(match: MatchLoc) -> str:
    prefix = "g/" if match.every else "/"
    return f"({prefix}{match.text}/)"


def _compile(match: MatchLoc, *, ignore_case: bool = False) -> re.Pattern[str]:
    """Compile the match body as a regex, failing loud on a malformed pattern.

    ``ignore_case`` is for selecting a :class:`Reference`: CommonMark normalizes
    link labels case-insensitively, so ``(/mdit/)`` must name ``[MDIT]``.
    """
    try:
        return re.compile(match.text, re.IGNORECASE if ignore_case else 0)
    except re.error as err:
        raise ResolveError(f"invalid regex {_fmt_match(match)}: {err}") from err


def _apply_match(matches: list[str], match: MatchLoc, scope: str) -> str:
    if not matches:
        raise ResolveError(f"no match for {_fmt_match(match)} in {scope}")
    if match.every:
        return "\n".join(matches)
    if len(matches) > 1:
        raise ResolveError(f"AMBIGUOUS: {len(matches)} matches for {_fmt_match(match)} in {scope}")
    return matches[0]


def _narrow(units: tuple[str, ...], location: Location, kind: str, label: str) -> tuple[str, ...]:
    """Candidate sub-units for a content match: the one at ``location`` (a single
    number) or all of them (``location`` absent). Cell/column locations never reach
    here — the grammar rejects composing a match with them."""
    if location is None:
        return units
    if not isinstance(location, int) or not 1 <= location <= len(units):
        raise ResolveError(f"no such {kind} {location} in {label} (has {len(units)})")
    return (units[location - 1],)


def _match_units(units: tuple[str, ...], match: MatchLoc, kind: str, label: str) -> Resolution:
    pattern = _compile(match)
    hits = [u for u in units if pattern.search(u)]
    return Resolution(kind, _apply_match(hits, match, label))


def _find_section(msg: Message, index: int) -> Section:
    for section in msg.sections:
        if section.index == index:
            return section
    raise ResolveError(f"no section {index} in this message")


def _find_entity(entities: tuple[Entity, ...], letter: str, index: int) -> Entity:
    expected = _LETTER_TO_TYPE[letter]
    for entity in entities:
        if isinstance(entity, expected) and entity.index == index:
            return entity
    raise ResolveError(f"no {letter}{index} here")


def _entity_text(entity: Entity) -> str:
    """An entity's whole content — what a selector match is tested against."""
    return resolve_entity(entity, None, None).content


def _select_entities(
    entities: tuple[Entity, ...], step: EntityStep, match: MatchLoc | None
) -> list[Entity]:
    """The entities a step names: the one at ``step.index``, or — when the step
    carries no index — those of its type whose content matches.

    The two match forms mean here what they mean everywhere else: ``(/…/)`` names
    the single hit and is ``AMBIGUOUS`` on more, ``(g/…/)`` names every hit.
    """
    if step.index is not None:
        return [_find_entity(entities, step.letter, step.index)]
    if match is None:  # parse_ref forbids this; keep the walk total, never guess
        raise ResolveError(f"{step.letter} needs an index or a match")
    expected = _LETTER_TO_TYPE[step.letter]
    pattern = _compile(match, ignore_case=expected is Reference)
    hits = [e for e in entities if isinstance(e, expected) and pattern.search(_entity_text(e))]
    scope = f"the {step.letter} entities here"
    if not hits:
        raise ResolveError(f"no match for {_fmt_match(match)} in {scope}")
    if len(hits) > 1 and not match.every:
        raise ResolveError(f"AMBIGUOUS: {len(hits)} matches for {_fmt_match(match)} in {scope}")
    return hits


def _walk(section: Section, ref: Ref) -> list[Entity]:
    """The addressed entities — one, unless a terminal ``(g/…/)`` selected several.

    Only the terminal step may be selected by a match, so every step that is
    descended into names exactly one container.
    """
    current: list[Entity] = [section]
    entities = section.entities
    for i, step in enumerate(ref.path):
        current = _select_entities(entities, step, ref.match)
        if i < len(ref.path) - 1:
            inner = current[0]
            if not isinstance(inner, Section | Quote):
                raise ResolveError(
                    f"{step.letter}{step.index} is not a container; cannot address inside it"
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
                f"no such sentence {location} in P{para.index} (has {len(para.sentences)})"
            )
        return Resolution("sentence", para.sentences[location - 1])
    raise ResolveError(f"P{para.index} takes a sentence number, not a cell reference")


def _resolve_table_cell(table: Table, loc: TableLoc) -> Resolution:
    width = len(table.rows[0]) if table.rows else 0
    if loc.col is not None and not 1 <= loc.col <= width:
        raise ResolveError(f"no such column {loc.col} in T{table.index} (has {width})")
    if loc.row is None:  # whole column
        column = [
            row[loc.col - 1] for row in table.rows if loc.col is not None and loc.col <= len(row)
        ]
        return Resolution("column", "\n".join(column))
    if not 1 <= loc.row <= len(table.rows):
        raise ResolveError(f"no such row {loc.row} in T{table.index} (has {len(table.rows)})")
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
            raise ResolveError(f"no such row {location} in T{table.index} (has {len(table.rows)})")
        return Resolution("row", rows[location - 1])
    return _resolve_table_cell(table, location)


def _resolve_indexed(
    items: tuple[str, ...], location: Location, match: MatchLoc | None, kind: str, label: str
) -> Resolution:
    if match is not None:
        units = _narrow(items, location, kind, label)
        return _match_units(units, match, kind, label)
    if location is None:
        return Resolution(kind, "\n".join(items))
    if isinstance(location, int):
        if not 1 <= location <= len(items):
            raise ResolveError(f"no such {kind} {location} in {label} (has {len(items)})")
        return Resolution(kind, items[location - 1])
    raise ResolveError(f"{label} takes a single number, not a cell reference")


def _resolve_container(entity: Section | Quote, location: Location) -> Resolution:
    if location is not None:  # parse should have rejected this already
        raise ResolveError("a container takes no direct location")
    parts = [resolve_entity(child, None, None).content for child in entity.entities]
    kind = "section" if isinstance(entity, Section) else "quote"
    return Resolution(kind, "\n".join(parts))


def resolve_entity(  # ruff: ignore[too-many-return-statements]
    entity: Entity, location: Location, match: MatchLoc | None
) -> Resolution:
    """Apply ``location`` (structural) and ``match`` (content regex) to an
    already-located ``entity``. They compose: the location narrows the scope, the
    match then filters within it. Either may be absent."""
    if isinstance(entity, Paragraph):
        return _resolve_paragraph(entity, location, match)
    if isinstance(entity, Table):
        return _resolve_table(entity, location, match)
    if isinstance(entity, ListBlock):
        return _resolve_indexed(entity.items, location, match, "item", f"L{entity.index}")
    if isinstance(entity, CodeBlock):
        return _resolve_indexed(entity.lines, location, match, "line", f"C{entity.index}")
    if isinstance(entity, Diagram):
        return Resolution("diagram", "\n".join(entity.lines))
    if isinstance(entity, Reference):
        return Resolution("reference", entity.text)
    return _resolve_container(entity, location)


def resolve(ref: Ref, msg: Message) -> Resolution:
    """Resolve ``ref`` against ``msg`` or raise :class:`ResolveError` naming the miss."""
    section = _find_section(msg, ref.section if ref.section is not None else 1)
    targets = _walk(section, ref)
    if ref.path and ref.path[-1].index is None:
        # The match chose the entities; it does not also narrow inside them. A
        # global selector joins them, exactly as a global location joins its rows.
        parts = [resolve_entity(entity, None, None) for entity in targets]
        return Resolution(parts[0].kind, "\n".join(part.content for part in parts))
    return resolve_entity(targets[0], ref.location, ref.match)
