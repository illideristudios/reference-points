"""The address grammar: parse a reference string into a structured ``Ref``.

An address reads **turN · Section · Entity · Location** — ``N27-S1.T2.3``. Only
structure and *static* legality are checked here; range and ambiguity need the
message in hand, so they belong to :mod:`reference_points.resolve`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Name and legal location shape per letter, spelled with the caller's own entity
# so a hint reads back as an address they can paste. One table, so a new entity
# cannot arrive with a letter but no way to say what goes inside it.
_ENTITIES: dict[str, tuple[str, str]] = {
    "P": ("paragraph", "{e}.2 for a sentence, or {e}.(/word/) to match inside it"),
    "T": ("table", "{e}.3 for a row, {e}.3,2 for a cell, {e}.,2 for a column"),
    "L": ("list", "{e}.2 for an item"),
    "C": ("verbatim block", "{e}.5 for a line"),
    "Q": ("quote", "{e}.P1 for a paragraph inside it"),
    "S": ("section", "{e}.P1 for a paragraph inside it"),
    "D": ("diagram", "{e}.3 for a line"),
    "R": ("reference", "{e} on its own — a definition has no addressable parts"),
}

_ENTITY_LETTERS = frozenset(_ENTITIES)
_CONTAINER_LETTERS = frozenset("QS")
_SINGLE_NUMBER_ENTITIES = frozenset("PLCD")
_NO_LOCATION_ENTITIES = frozenset("R")  # a definition renders to nothing to point into

_TURN_RE = re.compile(r"^N(\d+)")
_SECTION_RE = re.compile(r"^-S(\d+)")
_BARE_SECTION_RE = re.compile(r"^-?S\d+")
# The index is optional — a step may be selected by the trailing match instead.
_ENTITY_RE = re.compile(r"([A-Za-z])(\d*)$")
_MATCH_TAIL_RE = re.compile(r"\.?\((g?)/(.*)/\)$")
_ROW_COL_RE = re.compile(r"(\d+),(\d+)$")
_COL_ONLY_RE = re.compile(r",(\d+)$")


# The failure vocabulary, shared with :mod:`reference_points.resolve`. Every
# message an address can produce starts with one of these, so a caller can sort
# "you typed it wrong" from "it is not there" without parsing prose.
REJECTED = "REJECTED"  # the address violates the grammar, or the shape it found
INVALID = "INVALID"  # the address is well-formed but its regex is not
MISSING = "MISSING"  # well-formed, and nothing is there
AMBIGUOUS = "AMBIGUOUS"  # well-formed, and more than one thing is there


def format_failure(kind: str, message: str, hint: str) -> str:
    """One shape for every failure: the category, what happened, then what to type
    instead. The hint is what turns a rejection into the next address."""
    return f"{kind}: {message}\n  -> {hint}"


def location_form(letter: str, index: int | None = None) -> str:
    """How to address inside this entity, spelled with its own index."""
    form = _ENTITIES[letter][1]
    return form.format(e=f"{letter}{index if index is not None else 1}")


def entity_menu() -> str:
    return ", ".join(f"{letter} {name}" for letter, (name, _) in _ENTITIES.items())


class RefError(Exception):
    """A malformed address. Always ``REJECTED`` — a static defect, caught without
    ever seeing a message. ``hint`` is required, so none ships without a remedy."""

    def __init__(self, message: str, hint: str) -> None:
        super().__init__(format_failure(REJECTED, message, hint))


@dataclass(frozen=True)
class EntityStep:
    """``index`` is ``None`` when the match selects the step: ``R(/mdit/)``, not ``R1``."""

    letter: str
    index: int | None


@dataclass(frozen=True)
class TableLoc:
    """A row, a cell (``row,col``), or a whole column (``,col``)."""

    row: int | None
    col: int | None


@dataclass(frozen=True)
class MatchLoc:
    """``(/text/)`` (single) or ``(g/text/)`` (every)."""

    text: str
    every: bool


Location = int | TableLoc | None


@dataclass(frozen=True)
class Ref:
    """``location`` and ``match`` both attach to the terminal step and compose: a
    structural coordinate, then a regex scoping finer within it."""

    turn: int
    section: int | None
    path: tuple[EntityStep, ...]
    location: Location
    match: MatchLoc | None
    raw: str = field(compare=False)


def _normalize_glyphs(raw: str) -> str:
    """Fold the glyphs to ASCII and drop separator spaces — but not inside a
    trailing ``(/…/)``, where they are part of the pattern."""
    s = raw.replace("◆", "N").replace("§", "-S").replace("·", ".")
    open_paren = s.find("(")
    if open_paren != -1 and s.rstrip().endswith(")"):
        return s[:open_paren].replace(" ", "") + s[open_paren:].rstrip()
    return s.replace(" ", "")


def _parse_numeric_location(comp: str) -> Location:
    if comp.isdigit():
        return int(comp)
    row_col = _ROW_COL_RE.fullmatch(comp)
    if row_col:
        return TableLoc(int(row_col.group(1)), int(row_col.group(2)))
    col_only = _COL_ONLY_RE.fullmatch(comp)
    if col_only:
        return TableLoc(None, int(col_only.group(1)))
    raise RefError(
        f"malformed location {comp!r}",
        "a location is a number (3), a cell (3,2), or a column (,2)",
    )


def _check_location_legal(step: EntityStep, location: Location) -> None:
    letter = step.letter
    inside = f"use {location_form(letter, step.index)}"
    if letter in _NO_LOCATION_ENTITIES:
        raise RefError(f"{letter}{step.index} takes no location", inside)
    if letter in _CONTAINER_LETTERS:
        raise RefError(f"{letter}{step.index} is a container, not a leaf", inside)
    if letter in _SINGLE_NUMBER_ENTITIES and isinstance(location, TableLoc):
        raise RefError(f"{letter}{step.index} takes a single number, not a cell", inside)


def _check_match_legal(step: EntityStep, location: Location) -> None:
    letter = step.letter
    inside = f"use {location_form(letter, step.index)}"
    if letter in _NO_LOCATION_ENTITIES:
        raise RefError(f"{letter}{step.index} takes no match", inside)
    if letter in _CONTAINER_LETTERS:
        raise RefError(f"{letter}{step.index} is a container, not a leaf", inside)
    if isinstance(location, TableLoc):
        raise RefError(
            "a match cannot compose with a cell or column reference",
            "match a whole row instead, as in T1.(/word/)",
        )


def _check_selector_legal(step: EntityStep, location: Location, match: MatchLoc | None) -> None:
    """A step with no index needs the match and takes no location, having spent the
    match on choosing the entity. Both match forms are legal there."""
    letter = step.letter
    if match is None:
        raise RefError(
            f"entity {letter} needs an index",
            f"use {letter}1, or {letter}(/word/) to select it by content",
        )
    if location is not None:
        raise RefError(
            f"{letter}(/…/) selects an entity; it takes no location",
            f"drop the location: {letter}(/{match.text}/)",
        )


def _supply_turn(s: str, turn: int) -> str:
    """Front a turn-less address with the turn of the message it is being read
    against, so the fragments ``render_inline`` emits — ``.P1``, ``·T2`` — resolve
    exactly as they are written instead of having to be re-typed in full."""
    if _BARE_SECTION_RE.match(s):
        joiner = "" if s.startswith("-") else "-"
    else:
        joiner = "" if s.startswith(".") else "."
    return f"N{turn}{joiner}{s}"


def _split_turn_section(s: str) -> tuple[int, int | None, str]:
    """Peel the mandatory ``N<n>`` and optional ``-S<n>`` off the front."""
    turn_match = _TURN_RE.match(s)
    if not turn_match:
        raise RefError(
            "missing turn number",
            f"every address starts with the turn it points into: N1-{s or 'S1.P1'}",
        )
    turn = int(turn_match.group(1))
    body = s[turn_match.end() :]

    section: int | None = None
    section_match = _SECTION_RE.match(body)
    if section_match:
        section = int(section_match.group(1))
        body = body[section_match.end() :]

    if body.startswith("-"):
        raise RefError(
            "unexpected '-' after the turn/section",
            "the dash only separates turn from section, as in N1-S1.P1",
        )
    if body and not body.startswith("."):
        raise RefError(
            f"unexpected {body[0]!r} after the turn/section",
            "entities follow a dot, as in N1-S1.P1",
        )
    return turn, section, body


def _peel_match_location(body: str) -> tuple[MatchLoc | None, str]:
    """Peel a trailing ``(/…/)`` / ``(g/…/)`` off ``body``."""
    match_tail = _MATCH_TAIL_RE.search(body)
    if not match_tail:
        return None, body
    text = match_tail.group(2)
    if not text:
        raise RefError("empty match string", "put a pattern between the slashes: (/word/)")
    return MatchLoc(text, every=match_tail.group(1) == "g"), body[: match_tail.start()]


def _parse_path(components: list[str]) -> tuple[tuple[EntityStep, ...], Location]:
    path: list[EntityStep] = []
    location: Location = None
    for i, comp in enumerate(components):
        if comp[0].isalpha():
            entity_match = _ENTITY_RE.fullmatch(comp)
            if not entity_match:
                raise RefError(
                    f"malformed entity {comp!r}",
                    "an entity is a letter and a number (P1, T2), or a letter and a "
                    "match (P(/word/))",
                )
            letter = entity_match.group(1).upper()
            if letter not in _ENTITY_LETTERS:
                raise RefError(f"unknown entity {letter!r}", f"known entities: {entity_menu()}")
            index = entity_match.group(2)
            path.append(EntityStep(letter, int(index) if index else None))
        elif i != len(components) - 1:
            raise RefError(
                f"location {comp!r} must be the final part of the address",
                f"one location, at the end: put {comp!r} last or drop it",
            )
        else:
            location = _parse_numeric_location(comp)
    return tuple(path), location


def parse_ref(raw: str, turn: int | None = None) -> Ref:
    """Or raise :class:`RefError` naming the defect and what to type instead.

    ``turn`` is the turn of the message this address will be read against. Supply
    it and a turn-less address is legal, because the caller already knows the
    answer; omit it and the turn stays mandatory.
    """
    s = _normalize_glyphs(raw).strip()
    if not s:
        raise RefError("empty address", "an address is at least a turn: N1")
    if turn is not None and not _TURN_RE.match(s):
        s = _supply_turn(s, turn)

    parsed_turn, section, body = _split_turn_section(s)
    match_location, body = _peel_match_location(body)
    components = [c for c in body.split(".") if c]
    path, location = _parse_path(components)
    for step in path[:-1]:  # only the terminal step may be selected by a match
        if step.index is None:
            raise RefError(
                f"entity {step.letter} needs an index",
                f"use {step.letter}1 — only the last entity may be selected by a match",
            )

    if not path:
        if location is not None:
            raise RefError(
                "a location needs an entity to attach to",
                f"name the entity first, as in N{parsed_turn}-S1.P1.{_render(location)}",
            )
        if match_location is not None:
            raise RefError(
                "a match needs an entity to attach to",
                f"name the entity first, as in N{parsed_turn}-S1.P1.(/{match_location.text}/)",
            )
    elif path[-1].index is None:
        _check_selector_legal(path[-1], location, match_location)
    else:
        if location is not None:
            _check_location_legal(path[-1], location)
        if match_location is not None:
            _check_match_legal(path[-1], location)

    return Ref(
        turn=parsed_turn,
        section=section,
        path=path,
        location=location,
        match=match_location,
        raw=raw,
    )


def _render(location: Location) -> str:
    if isinstance(location, TableLoc):
        row = "" if location.row is None else location.row
        return f"{row},{location.col}"
    return str(location)
