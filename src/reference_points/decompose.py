"""Decompose a markdown message into a ``Section → Entity → Location`` tree.

This is the single source of truth for addresses: the same tree is rendered into
labels and walked to resolve a reference, so a label and its lookup agree by
construction. Parsing runs on the markdown *source* — sound because GFM rendering
preserves block-level structure (see ``REFERENCE_POINTS.md``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_FENCE_RE = re.compile(r"^\s*(```+|~~~+)\s*([^\s`~]*)")
_LIST_ITEM_RE = re.compile(r"^\s*([-*+]|\d+[.)])\s+(.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")

_DIAGRAM_LANGS = frozenset({"mermaid", "dot", "graphviz"})


@dataclass(frozen=True)
class Paragraph:
    """A prose block. Location = sentence index. ``line`` = 0-based source line."""

    index: int
    line: int
    text: str
    sentences: tuple[str, ...]


@dataclass(frozen=True)
class Table:
    """A table. ``rows`` includes the header as row 1; the separator row is dropped."""

    index: int
    line: int
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class CodeBlock:
    """A fenced code block. Location = 1-indexed logical (``\\n``-delimited) line."""

    index: int
    line: int
    lang: str | None
    lines: tuple[str, ...]


@dataclass(frozen=True)
class ListBlock:
    """A list. Location = 1-indexed item."""

    index: int
    line: int
    items: tuple[str, ...]


@dataclass(frozen=True)
class Diagram:
    """A diagram (mermaid/dot fence). Takes no location."""

    index: int
    line: int
    lines: tuple[str, ...]


@dataclass(frozen=True)
class Quote:
    """A blockquote — a container that nests inner entities."""

    index: int
    line: int
    entities: tuple[Entity, ...]


@dataclass(frozen=True)
class Section:
    """A section (markdown heading, or the implicit whole-message S1). Container.

    ``line`` is the 0-based source line of the heading, or ``-1`` for the implicit S1.
    """

    index: int
    line: int
    heading: str
    level: int
    entities: tuple[Entity, ...]


Entity = Paragraph | Table | CodeBlock | ListBlock | Diagram | Quote | Section


@dataclass(frozen=True)
class Message:
    """A decomposed message: top-level sections plus the original source."""

    sections: tuple[Section, ...]
    source: str


def split_sentences(text: str) -> tuple[str, ...]:
    """Split a paragraph's logical text into sentences (pragmatic heuristic).

    Imperfection is acceptable *because* this same function runs at label-time and
    resolve-time, so labels and lookups stay self-consistent.
    """
    stripped = text.strip()
    if not stripped:
        return ()
    return tuple(part.strip() for part in _SENTENCE_SPLIT_RE.split(stripped) if part.strip())


def _heading(line: str) -> tuple[int, str] | None:
    match = _HEADING_RE.match(line)
    if not match:
        return None
    return len(match.group(1)), match.group(2).strip()


def _is_blank(line: str) -> bool:
    return not line.strip()


def _split_table_row(line: str) -> tuple[str, ...]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return tuple(cell.strip() for cell in stripped.split("|"))


def _looks_like_table(lines: list[str], i: int) -> bool:
    return "|" in lines[i] and i + 1 < len(lines) and bool(_TABLE_SEP_RE.match(lines[i + 1]))


class _Counter:
    """Per-type entity indexing within one container."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def next(self, letter: str) -> int:
        self._counts[letter] = self._counts.get(letter, 0) + 1
        return self._counts[letter]


def _consume_code(
    lines: list[str], start: int, counter: _Counter, offset: int
) -> tuple[Entity, int]:
    fence = _FENCE_RE.match(lines[start])
    if fence is None:  # dispatch invariant: _consume_block only routes fences here
        raise ValueError(f"expected a code fence at line {start}")
    marker, lang = fence.group(1), fence.group(2)
    body: list[str] = []
    i = start + 1
    while i < len(lines) and not lines[i].strip().startswith(marker[0] * 3):
        body.append(lines[i])
        i += 1
    end = i + 1 if i < len(lines) else i  # skip the closing fence
    line = offset + start
    if lang.lower() in _DIAGRAM_LANGS:
        return Diagram(index=counter.next("D"), line=line, lines=tuple(body)), end - start
    return CodeBlock(
        index=counter.next("C"), line=line, lang=lang or None, lines=tuple(body)
    ), end - start


def _consume_table(
    lines: list[str], start: int, counter: _Counter, offset: int
) -> tuple[Entity, int]:
    rows: list[tuple[str, ...]] = [_split_table_row(lines[start])]
    i = start + 1
    while i < len(lines) and "|" in lines[i]:
        if not _TABLE_SEP_RE.match(lines[i]):
            rows.append(_split_table_row(lines[i]))
        i += 1
    return Table(index=counter.next("T"), line=offset + start, rows=tuple(rows)), i - start


def _consume_list(
    lines: list[str], start: int, counter: _Counter, offset: int
) -> tuple[Entity, int]:
    items: list[str] = []
    i = start
    while i < len(lines):
        match = _LIST_ITEM_RE.match(lines[i])
        if not match:
            break
        items.append(match.group(2).strip())
        i += 1
    return ListBlock(index=counter.next("L"), line=offset + start, items=tuple(items)), i - start


def _consume_quote(
    lines: list[str], start: int, counter: _Counter, offset: int
) -> tuple[Entity, int]:
    inner: list[str] = []
    i = start
    while i < len(lines) and lines[i].lstrip().startswith(">"):
        stripped = lines[i].lstrip()[1:]
        inner.append(stripped[1:] if stripped.startswith(" ") else stripped)
        i += 1
    entities = tuple(_parse_container(inner, offset + start))
    return Quote(index=counter.next("Q"), line=offset + start, entities=entities), i - start


def _consume_paragraph(
    lines: list[str], start: int, counter: _Counter, offset: int
) -> tuple[Entity, int]:
    body: list[str] = []
    i = start
    while i < len(lines) and not _is_blank(lines[i]) and not _block_starts_here(lines, i):
        body.append(lines[i].strip())
        i += 1
    text = " ".join(body)
    return Paragraph(
        index=counter.next("P"), line=offset + start, text=text, sentences=split_sentences(text)
    ), i - start


def _block_starts_here(lines: list[str], i: int) -> bool:
    """True if a non-paragraph block begins at ``i`` (used to end a paragraph run)."""
    line = lines[i]
    return (
        _heading(line) is not None
        or _FENCE_RE.match(line) is not None
        or line.lstrip().startswith(">")
        or _LIST_ITEM_RE.match(line) is not None
        or _looks_like_table(lines, i)
    )


def _consume_block(lines: list[str], i: int, counter: _Counter, offset: int) -> tuple[Entity, int]:
    line = lines[i]
    if _FENCE_RE.match(line):
        return _consume_code(lines, i, counter, offset)
    if line.lstrip().startswith(">"):
        return _consume_quote(lines, i, counter, offset)
    if _looks_like_table(lines, i):
        return _consume_table(lines, i, counter, offset)
    if _LIST_ITEM_RE.match(line):
        return _consume_list(lines, i, counter, offset)
    return _consume_paragraph(lines, i, counter, offset)


def _parse_container(lines: list[str], offset: int = 0) -> list[Entity]:
    """Parse a flat line range into ordered entities (leaves, quotes, subsections).

    ``offset`` is the absolute source line of ``lines[0]``, so every entity's
    ``line`` is absolute in the original message source.
    """
    entities: list[Entity] = []
    counter = _Counter()
    i = 0
    while i < len(lines):
        if _is_blank(lines[i]):
            i += 1
            continue
        head = _heading(lines[i])
        if head is not None:
            level, text = head
            j = i + 1
            while j < len(lines):
                deeper = _heading(lines[j])
                if deeper is not None and deeper[0] <= level:
                    break
                j += 1
            entities.append(
                Section(
                    index=counter.next("S"),
                    line=offset + i,
                    heading=text,
                    level=level,
                    entities=tuple(_parse_container(lines[i + 1 : j], offset + i + 1)),
                )
            )
            i = j
            continue
        block, consumed = _consume_block(lines, i, counter, offset)
        entities.append(block)
        i += max(consumed, 1)
    return entities


def decompose(markdown: str) -> Message:
    """Decompose ``markdown`` into a :class:`Message` tree.

    Content before the first heading (or a message with no headings) forms an
    implicit section ``S1``; each top-level heading is a subsequent section.
    """
    top = _parse_container(markdown.splitlines())
    leading = [e for e in top if not isinstance(e, Section)]
    heading_sections = [e for e in top if isinstance(e, Section)]

    sections: list[Section] = []
    if leading or not heading_sections:
        sections.append(Section(index=1, line=-1, heading="", level=0, entities=tuple(leading)))
    for hs in heading_sections:
        sections.append(replace(hs, index=len(sections) + 1))
    return Message(sections=tuple(sections), source=markdown)
