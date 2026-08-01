"""Decompose a markdown message into a ``Section → Entity → Location`` tree.

The single source of truth for addresses: the same tree is rendered into labels
and walked to resolve a reference, so the two agree by construction. Parsing the
*source* is sound because GFM preserves block structure (``REFERENCE_POINTS.md``).

Block structure comes from ``markdown-it-py``, so a new construct is a row in the
mapping below, not a scanner branch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, cast

from markdown_it import MarkdownIt

if TYPE_CHECKING:
    from collections.abc import Mapping

    from markdown_it.token import Token

# Not ``gfm-like``: it enables linkify, which raises unless ``linkify-it-py`` is
# installed. Disabling ``inline`` costs nothing — the raw source this module reads
# is ``inline.content``, set by the block parser.
_MD = MarkdownIt("commonmark").enable("table").disable("inline")

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")

_DIAGRAM_LANGS = frozenset({"mermaid", "dot", "graphviz"})
_LIST_OPENS = frozenset({"bullet_list_open", "ordered_list_open"})


@dataclass(frozen=True)
class Paragraph:
    """Location = sentence index. ``line`` is 0-based."""

    index: int
    line: int
    text: str
    sentences: tuple[str, ...]


@dataclass(frozen=True)
class Table:
    """``rows`` includes the header as row 1; the separator row is dropped."""

    index: int
    line: int
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class CodeBlock:
    """Fenced, indented, or raw HTML. Content is exact, so the location is a
    1-indexed ``\\n``-delimited line."""

    index: int
    line: int
    lang: str | None
    lines: tuple[str, ...]


@dataclass(frozen=True)
class ListBlock:
    """Location = 1-indexed item, counting every bullet at every depth."""

    index: int
    line: int
    items: tuple[str, ...]


@dataclass(frozen=True)
class Diagram:
    """A mermaid/dot fence. Takes no location."""

    index: int
    line: int
    lines: tuple[str, ...]


@dataclass(frozen=True)
class Reference:
    """Addressable, never labeled inline: it renders to nothing, so a label would
    show text where the reader saw none. ``key`` is the CommonMark-normalized
    label, which makes ``[MDIT]`` and ``[ mdit ]`` one reference. No location."""

    index: int
    line: int
    key: str
    destination: str
    title: str

    @property
    def text(self) -> str:
        """What an address resolves to, and what a selector matches."""
        title = f' "{self.title}"' if self.title else ""
        return f"[{self.key}]: {self.destination}{title}"


@dataclass(frozen=True)
class Quote:
    """A blockquote. Container."""

    index: int
    line: int
    entities: tuple[Entity, ...]


@dataclass(frozen=True)
class Section:
    """A heading, or the implicit whole-message S1 (``line == -1``).

    ``markup`` is the literal marker, which lets the renderer rebuild an ATX line
    but only prefix a setext one. ``level`` is not derivable from it — a setext
    **h2** has ``markup == '-'``.
    """

    index: int
    line: int
    heading: str
    level: int
    markup: str
    entities: tuple[Entity, ...]


Entity = Paragraph | Table | CodeBlock | ListBlock | Diagram | Reference | Quote | Section


@dataclass(frozen=True)
class Message:
    sections: tuple[Section, ...]
    source: str


def split_sentences(text: str) -> tuple[str, ...]:
    """Heuristic, and imperfection is acceptable *because* this runs at both
    label-time and resolve-time, keeping labels and lookups self-consistent."""
    stripped = text.strip()
    if not stripped:
        return ()
    return tuple(part.strip() for part in _SENTENCE_SPLIT_RE.split(stripped) if part.strip())


class _Counter:
    """Per-type entity indexing within one container."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def next(self, letter: str) -> int:
        self._counts[letter] = self._counts.get(letter, 0) + 1
        return self._counts[letter]


# --- link reference definitions ------------------------------------------
# They emit no tokens, so they come from the parser's reference table and are
# interleaved back into the spans by source line.


@dataclass(frozen=True)
class _RawRef:
    line: int
    key: str
    destination: str
    title: str


def _entry_line(entry: Mapping[str, object]) -> int:
    span = entry.get("map")
    if isinstance(span, list) and span and isinstance(span[0], int):
        return span[0]
    return 0


def _collect_references(env: Mapping[str, Any]) -> list[_RawRef]:
    table: object = env.get("references")
    if not isinstance(table, dict):
        return []
    raw: list[_RawRef] = []
    for key, value in cast("dict[object, object]", table).items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        entry = cast("dict[str, object]", value)
        raw.append(
            _RawRef(
                line=_entry_line(entry),
                key=key,
                destination=str(entry.get("href", "")),
                title=str(entry.get("title", "")),
            )
        )
    raw.sort(key=lambda ref: ref.line)
    return raw


class _RefFeed:
    """Definitions in source order, so each lands between the blocks it sits
    between."""

    def __init__(self, refs: list[_RawRef]) -> None:
        self._refs = refs
        self._at = 0

    def take_before(self, limit: int | None) -> list[_RawRef]:
        """``None`` takes everything left."""
        start = self._at
        while self._at < len(self._refs) and (limit is None or self._refs[self._at].line < limit):
            self._at += 1
        return self._refs[start : self._at]

    def split(self, limit: int | None) -> _RefFeed:
        """Consumed here, so a nested container never re-emits them."""
        return _RefFeed(self.take_before(limit))


def _references(raw: list[_RawRef], counter: _Counter) -> list[Entity]:
    return [
        Reference(
            index=counter.next("R"),
            line=ref.line,
            key=ref.key,
            destination=ref.destination,
            title=ref.title,
        )
        for ref in raw
    ]


# --- token stream → entities ---------------------------------------------


def _spans(tokens: list[Token]) -> list[list[Token]]:
    """Group a flat token list into top-level block spans (open…close runs)."""
    spans: list[list[Token]] = []
    current: list[Token] = []
    depth = 0
    for token in tokens:
        current.append(token)
        depth += token.nesting
        if depth == 0:
            spans.append(current)
            current = []
    if current:  # unbalanced input: keep the tail rather than drop it
        spans.append(current)
    return spans


def _span_lines(spans: list[list[Token]]) -> list[int]:
    """Narrows ``Token.map`` *totally*: an unmapped head takes the previous span's
    line, so the entity is still built — never skipped, never raised. Unreachable
    in markdown-it-py 4.x, where only ``th_open``/``td_open`` lack a map."""
    lines: list[int] = []
    last = 0
    for span in spans:
        head_map = span[0].map
        if head_map is not None:
            last = head_map[0]
        lines.append(last)
    return lines


def _content_lines(content: str) -> tuple[str, ...]:
    """Drops *only* the terminating newline."""
    lines = content.split("\n")
    if lines and not lines[-1]:
        lines.pop()
    return tuple(lines)


def _inline_text(span: list[Token]) -> str:
    return " ".join(token.content for token in span if token.type == "inline")


def _join_lines(text: str) -> str:
    """One space per line break — the way a reader reads it."""
    return " ".join(part.strip() for part in text.split("\n")).strip()


def _table_rows(span: list[Token]) -> tuple[tuple[str, ...], ...]:
    """The parser pads rows to the header's width, so none can come back short."""
    rows: list[tuple[str, ...]] = []
    cells: list[str] = []
    for token in span:
        if token.type == "tr_open":
            cells = []
        elif token.type == "inline":
            cells.append(_join_lines(token.content))
        elif token.type == "tr_close":
            rows.append(tuple(cells))
    return tuple(rows)


def _list_items(span: list[Token]) -> tuple[str, ...]:
    """Every bullet at every depth, depth-first (already token order), each with
    only its own direct paragraph text. Flattening keeps ``L1.3`` the third bullet
    a reader counts."""
    items: list[list[str]] = []
    opened_at: list[int] = []
    open_items: list[int] = []
    depth = 0
    for token in span:
        if token.type == "list_item_open":
            items.append([])
            open_items.append(len(items) - 1)
            opened_at.append(depth)
        elif token.type == "list_item_close":
            open_items.pop()
            opened_at.pop()
        elif token.type == "inline" and open_items and depth == opened_at[-1] + 2:
            # +2: the item's direct paragraph, then that paragraph's inline.
            items[open_items[-1]].append(_join_lines(token.content))
        depth += token.nesting
    return tuple(" ".join(parts) for parts in items)


# A flat dispatch table written as ifs — the order *is* the documentation.
def _leaf_entity(  # ruff: ignore[too-many-return-statements]
    span: list[Token], line: int, counter: _Counter, feed: _RefFeed
) -> Entity | None:
    head = span[0]
    if head.type == "paragraph_open":
        text = _join_lines(_inline_text(span))
        return Paragraph(
            index=counter.next("P"), line=line, text=text, sentences=split_sentences(text)
        )
    if head.type == "table_open":
        return Table(index=counter.next("T"), line=line, rows=_table_rows(span))
    if head.type == "fence":
        info = head.info.strip()
        lang = info.split(maxsplit=1)[0] if info else ""
        if lang.lower() in _DIAGRAM_LANGS:
            return Diagram(index=counter.next("D"), line=line, lines=_content_lines(head.content))
        return CodeBlock(
            index=counter.next("C"),
            line=line,
            lang=lang or None,
            lines=_content_lines(head.content),
        )
    if head.type == "code_block":  # indented — the parser stripped the indent already
        return CodeBlock(
            index=counter.next("C"), line=line, lang=None, lines=_content_lines(head.content)
        )
    if head.type == "html_block":
        return CodeBlock(
            index=counter.next("C"), line=line, lang="html", lines=_content_lines(head.content)
        )
    if head.type in _LIST_OPENS:
        return ListBlock(index=counter.next("L"), line=line, items=_list_items(span))
    if head.type == "blockquote_open":
        end = head.map[1] if head.map is not None else None
        inner = _parse_container(_spans(span[1:-1]), feed.split(end))
        return Quote(index=counter.next("Q"), line=line, entities=tuple(inner))
    if head.type == "hr":
        return None  # a visual rule: no content, no address
    # _MD emits nothing else; should it ever, keep the bytes rather than drop them.
    return CodeBlock(
        index=counter.next("C"), line=line, lang=None, lines=_content_lines(head.content)
    )


def _opens_sibling_section(head: Token, level: int) -> bool:
    return head.type == "heading_open" and int(head.tag[1:]) <= level


def _parse_container(spans: list[list[Token]], feed: _RefFeed) -> list[Entity]:
    """Lines come from the tokens' own maps and are already absolute, so nothing is
    threaded through the recursion but the reference feed."""
    entities: list[Entity] = []
    counter = _Counter()
    lines = _span_lines(spans)
    i = 0
    while i < len(spans):
        span, line = spans[i], lines[i]
        entities.extend(_references(feed.take_before(line), counter))
        head = span[0]
        if head.type == "heading_open":
            level = int(head.tag[1:])
            j = i + 1
            while j < len(spans) and not _opens_sibling_section(spans[j][0], level):
                j += 1
            end = lines[j] if j < len(spans) else None
            entities.append(
                Section(
                    index=counter.next("S"),
                    line=line,
                    heading=_join_lines(_inline_text(span)),
                    level=level,
                    markup=head.markup,
                    entities=tuple(_parse_container(spans[i + 1 : j], feed.split(end))),
                )
            )
            i = j
            continue
        entity = _leaf_entity(span, line, counter, feed)
        if entity is not None:
            entities.append(entity)
        i += 1
    entities.extend(_references(feed.take_before(None), counter))
    return entities


def decompose(markdown: str) -> Message:
    """Content before the first heading forms an implicit ``S1``; each top-level
    heading is a subsequent section."""
    env: dict[str, Any] = {}
    tokens = _MD.parse(markdown, env)
    top = _parse_container(_spans(tokens), _RefFeed(_collect_references(env)))
    leading = [e for e in top if not isinstance(e, Section)]
    heading_sections = [e for e in top if isinstance(e, Section)]

    sections: list[Section] = []
    if leading or not heading_sections:
        sections.append(
            Section(index=1, line=-1, heading="", level=0, markup="", entities=tuple(leading))
        )
    for hs in heading_sections:
        sections.append(replace(hs, index=len(sections) + 1))
    return Message(sections=tuple(sections), source=markdown)
