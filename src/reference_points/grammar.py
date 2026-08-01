"""The address grammar: parse a reference string into a structured ``Ref``.

An address reads **turN · Section · Entity · Location** — ``N27-S1.T2.3``. Only
structure and *static* legality are checked here; range and ambiguity need the
message in hand, so they belong to :mod:`reference_points.resolve`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_ENTITY_LETTERS = frozenset("PTLCQSDR")
_CONTAINER_LETTERS = frozenset("QS")
_SINGLE_NUMBER_ENTITIES = frozenset("PLC")
_NO_LOCATION_ENTITIES = frozenset("DR")  # a diagram and a ref def have no sub-units

_TURN_RE = re.compile(r"^N(\d+)")
_SECTION_RE = re.compile(r"^-S(\d+)")
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


class RefError(Exception):
    """A malformed address. Always ``REJECTED`` — a static defect, caught without
    ever seeing a message."""

    def __str__(self) -> str:
        return f"{REJECTED}: {super().__str__()}"


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
    raise RefError(f"malformed location {comp!r}")


def _check_location_legal(step: EntityStep, location: Location) -> None:
    letter = step.letter
    if letter in _NO_LOCATION_ENTITIES:
        raise RefError(f"{letter}{step.index} takes no location")
    if letter in _CONTAINER_LETTERS:
        raise RefError(
            f"{letter}{step.index} is a container; address an entity inside it, not a bare location"
        )
    if letter in _SINGLE_NUMBER_ENTITIES and isinstance(location, TableLoc):
        raise RefError(f"{letter}{step.index} takes a single number, not a cell reference")


def _check_match_legal(step: EntityStep, location: Location) -> None:
    letter = step.letter
    if letter in _NO_LOCATION_ENTITIES:
        raise RefError(f"{letter}{step.index} takes no match")
    if letter in _CONTAINER_LETTERS:
        raise RefError(
            f"{letter}{step.index} is a container; address an entity inside it, not a bare match"
        )
    if isinstance(location, TableLoc):
        raise RefError("a content match cannot compose with a cell or column reference")


def _check_selector_legal(step: EntityStep, location: Location, match: MatchLoc | None) -> None:
    """A step with no index needs the match and takes no location, having spent the
    match on choosing the entity. Both match forms are legal there."""
    if match is None:
        raise RefError(f"entity {step.letter} needs an index")
    if location is not None:
        raise RefError(f"{step.letter}(/…/) selects an entity; it takes no location")


def _split_turn_section(s: str) -> tuple[int, int | None, str]:
    """Peel the mandatory ``N<n>`` and optional ``-S<n>`` off the front."""
    turn_match = _TURN_RE.match(s)
    if not turn_match:
        raise RefError("missing turn number")
    turn = int(turn_match.group(1))
    body = s[turn_match.end() :]

    section: int | None = None
    section_match = _SECTION_RE.match(body)
    if section_match:
        section = int(section_match.group(1))
        body = body[section_match.end() :]

    if body.startswith("-"):
        raise RefError("unexpected '-' (dash is only allowed between turn and section)")
    if body and not body.startswith("."):
        raise RefError(f"unexpected {body[0]!r} after the turn/section")
    return turn, section, body


def _peel_match_location(body: str) -> tuple[MatchLoc | None, str]:
    """Peel a trailing ``(/…/)`` / ``(g/…/)`` off ``body``."""
    match_tail = _MATCH_TAIL_RE.search(body)
    if not match_tail:
        return None, body
    text = match_tail.group(2)
    if not text:
        raise RefError("empty match string")
    return MatchLoc(text, every=match_tail.group(1) == "g"), body[: match_tail.start()]


def _parse_path(components: list[str]) -> tuple[tuple[EntityStep, ...], Location]:
    path: list[EntityStep] = []
    location: Location = None
    for i, comp in enumerate(components):
        if comp[0].isalpha():
            entity_match = _ENTITY_RE.fullmatch(comp)
            if not entity_match:
                raise RefError(f"malformed entity {comp!r}")
            letter = entity_match.group(1).upper()
            if letter not in _ENTITY_LETTERS:
                raise RefError(f"unknown entity {letter!r}")
            index = entity_match.group(2)
            path.append(EntityStep(letter, int(index) if index else None))
        elif i != len(components) - 1:
            raise RefError(f"location {comp!r} must be the final part of the address")
        else:
            location = _parse_numeric_location(comp)
    return tuple(path), location


def parse_ref(raw: str) -> Ref:
    """Or raise :class:`RefError` naming the defect."""
    s = _normalize_glyphs(raw).strip()
    if not s:
        raise RefError("empty address")

    turn, section, body = _split_turn_section(s)
    match_location, body = _peel_match_location(body)
    components = [c for c in body.split(".") if c]
    path, location = _parse_path(components)
    for step in path[:-1]:  # only the terminal step may be selected by a match
        if step.index is None:
            raise RefError(f"entity {step.letter} needs an index")

    if not path:
        if location is not None:
            raise RefError("a location needs an entity to attach to")
        if match_location is not None:
            raise RefError("a match needs an entity to attach to")
    elif path[-1].index is None:
        _check_selector_legal(path[-1], location, match_location)
    else:
        if location is not None:
            _check_location_legal(path[-1], location)
        if match_location is not None:
            _check_match_legal(path[-1], location)

    return Ref(
        turn=turn, section=section, path=path, location=location, match=match_location, raw=raw
    )
