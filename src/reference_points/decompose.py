"""Decompose a markdown message into a ``Section → Entity → Location`` tree.

This is the single source of truth for addresses: the same tree is rendered into
labels and walked to resolve a reference, so a label and its lookup agree by
construction. Parsing runs on the markdown *source* — sound because GFM rendering
preserves block-level structure (see ``REFERENCE_POINTS.md``).

Block structure comes from ``markdown-it-py``, a CommonMark parser, so setext
headings, loose lists, lazy continuation, nesting depth and link reference
definitions are the parser's problem. What lives here is the mapping from its
token stream onto the entity alphabet — a new construct is a row in that mapping,
not a new scanner branch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, cast

from markdown_it import MarkdownIt

if TYPE_CHECKING:
    from collections.abc import Mapping

    from markdown_it.token import Token

# CommonMark plus tables — deliberately not the ``gfm-like`` preset, which turns
# on linkify and raises ModuleNotFoundError unless ``linkify-it-py`` is installed
# alongside. ``inline`` is disabled because only block structure is consumed
# here: the inline token's ``.content`` (the raw markdown this module reads) is
# set by the *block* parser and survives; only its ``.children`` goes empty.
_MD = MarkdownIt("commonmark").enable("table").disable("inline")

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")

_DIAGRAM_LANGS = frozenset({"mermaid", "dot", "graphviz"})
_LIST_OPENS = frozenset({"bullet_list_open", "ordered_list_open"})


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
    """A verbatim block — fenced, indented, or raw HTML. Its content is preserved
    exactly, so the location is a 1-indexed logical (``\\n``-delimited) line."""

    index: int
    line: int
    lang: str | None
    lines: tuple[str, ...]


@dataclass(frozen=True)
class ListBlock:
    """A list. Location = 1-indexed item, counting every bullet at every depth."""

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
class Reference:
    """A link reference definition (``[key]: destination "title"``).

    Addressable but never labeled inline: the definition renders to *nothing*, so
    a label would put visible text where the reader saw none. ``key`` is the
    CommonMark-normalized label, which is what makes ``[MDIT]``, ``[ mdit ]`` and
    ``[mdit]`` one reference. Takes no location.
    """

    index: int
    line: int
    key: str
    destination: str
    title: str

    @property
    def text(self) -> str:
        """The definition as one line — what an address to it resolves to, and
        what a ``(/…/)`` selector matches against (key, destination and title)."""
        title = f' "{self.title}"' if self.title else ""
        return f"[{self.key}]: {self.destination}{title}"


@dataclass(frozen=True)
class Quote:
    """A blockquote — a container that nests inner entities."""

    index: int
    line: int
    entities: tuple[Entity, ...]


@dataclass(frozen=True)
class Section:
    """A section (markdown heading, or the implicit whole-message S1). Container.

    ``line`` is the 0-based source line of the heading, or ``-1`` for the implicit
    S1. ``markup`` is the literal marker — ``'##'`` for ATX, ``'='`` / ``'-'`` for
    setext — which is what tells the renderer whether to rebuild the line or to
    prefix the label and leave the underline alone. ``level`` is not derivable
    from it: ``len('###')`` is 3, but a setext **h2** has ``markup == '-'``.
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


class _Counter:
    """Per-type entity indexing within one container."""

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def next(self, letter: str) -> int:
        self._counts[letter] = self._counts.get(letter, 0) + 1
        return self._counts[letter]


# --- link reference definitions ------------------------------------------
# They emit no tokens at all, so they are read from the parser's collected
# reference table and interleaved back into the token spans by source line.


@dataclass(frozen=True)
class _RawRef:
    """One entry of the parser's reference table, before it is indexed."""

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
    """Read the parser's reference table into source order."""
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
    """Reference definitions in source order, handed out by line.

    The walker asks for everything that starts before the next token span, so a
    definition lands between the blocks it sits between; a container takes a
    sub-feed of the definitions that fall inside its own line range.
    """

    def __init__(self, refs: list[_RawRef]) -> None:
        self._refs = refs
        self._at = 0

    def take_before(self, limit: int | None) -> list[_RawRef]:
        """Definitions starting before ``limit`` (``None`` = all that are left)."""
        start = self._at
        while self._at < len(self._refs) and (limit is None or self._refs[self._at].line < limit):
            self._at += 1
        return self._refs[start : self._at]

    def split(self, limit: int | None) -> _RefFeed:
        """Hand a nested container its own feed, consuming those definitions here."""
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
    """Group a flat token list into top-level block spans (each open…close run)."""
    spans: list[list[Token]] = []
    current: list[Token] = []
    depth = 0
    for token in tokens:
        current.append(token)
        depth += token.nesting
        if depth == 0:
            spans.append(current)
            current = []
    if current:  # unbalanced input: keep the tail rather than dropping it
        spans.append(current)
    return spans


def _span_lines(spans: list[list[Token]]) -> list[int]:
    """The absolute source line of each span, narrowing ``Token.map`` *totally*.

    A head token without a map takes the previous span's line, so the entity is
    still built and still addressable — never skipped, never raised. Against
    markdown-it-py 4.x the branch is unreachable: every block rule sets ``map`` on
    its open token, and the only unmapped opens are ``th_open``/``td_open``, which
    are never a span head.
    """
    lines: list[int] = []
    last = 0
    for span in spans:
        head_map = span[0].map
        if head_map is not None:
            last = head_map[0]
        lines.append(last)
    return lines


def _content_lines(content: str) -> tuple[str, ...]:
    """Split a verbatim token's content, dropping only its terminating newline."""
    lines = content.split("\n")
    if lines and not lines[-1]:
        lines.pop()
    return tuple(lines)


def _inline_text(span: list[Token]) -> str:
    return " ".join(token.content for token in span if token.type == "inline")


def _join_lines(text: str) -> str:
    """Join a block's source lines the way a reader reads them: one space per line
    break, nothing leading or trailing."""
    return " ".join(part.strip() for part in text.split("\n")).strip()


def _table_rows(span: list[Token]) -> tuple[tuple[str, ...], ...]:
    """Rows including the header. The parser normalizes every row to the header's
    width, so a ragged source row cannot produce a short row here."""
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
    """Every bullet at every depth, depth-first — which is already token order.

    An item's text is its own *direct* paragraph content: a nested list belongs to
    the items it contains, not to its parent's text. Flattening is what keeps
    ``L1.3`` pointing at the third bullet a reader counts.
    """
    items: list[list[str]] = []
    open_at: list[int] = []  # depth at which each currently-open item started
    stack: list[int] = []  # index into `items` of each currently-open item
    depth = 0
    for token in span:
        if token.type == "list_item_open":
            items.append([])
            stack.append(len(items) - 1)
            open_at.append(depth)
        elif token.type == "list_item_close":
            stack.pop()
            open_at.pop()
        elif token.type == "inline" and stack and depth == open_at[-1] + 2:
            # +2: the item's direct paragraph, then that paragraph's inline.
            items[stack[-1]].append(_join_lines(token.content))
        depth += token.nesting
    return tuple(" ".join(parts) for parts in items)


# A flat dispatch table written as ifs — the order *is* the documentation, so it
# does not get split to satisfy a return-count threshold.
def _leaf_entity(  # ruff: ignore[too-many-return-statements]
    span: list[Token], line: int, counter: _Counter, feed: _RefFeed
) -> Entity | None:
    """Map one non-heading span onto an entity, or ``None`` if it addresses nothing."""
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
    if head.type == "code_block":  # indented — the parser has stripped the indent
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
        return None  # a thematic break is a visual rule: no content, no address
    # _MD's rule set emits nothing else. Should it ever, keep the bytes rather
    # than drop them — a verbatim block is the lossless default.
    return CodeBlock(
        index=counter.next("C"), line=line, lang=None, lines=_content_lines(head.content)
    )


def _opens_sibling_section(head: Token, level: int) -> bool:
    return head.type == "heading_open" and int(head.tag[1:]) <= level


def _parse_container(spans: list[list[Token]], feed: _RefFeed) -> list[Entity]:
    """Walk one container's spans into ordered entities (leaves, quotes, subsections).

    Every line comes from the token's own ``map`` and is already absolute in the
    source, so nothing is threaded through the recursion but the reference feed.
    """
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
    """Decompose ``markdown`` into a :class:`Message` tree.

    Content before the first heading (or a message with no headings) forms an
    implicit section ``S1``; each top-level heading is a subsequent section.
    """
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
