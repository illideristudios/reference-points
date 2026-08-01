"""Render a decomposed :class:`Message` into labeled views.

``render_inline`` injects labels into the *original source* (so the reply keeps
its exact formatting — tables, code, wrapping — with labels added). ``render_map``
produces a compact address→excerpt index as an alternative overlay.

Both take a :class:`LabelStyle`. A section header carries the full prefix, every
other entity carries only its fragment — full paths are for references, fragments
are for labels. Two styles ship: :data:`ASCII` (default, ``N27-S1`` / ``.P1``) and
:data:`GLYPH` (``◆27 §1`` / ``·P1``). :func:`reference_points.grammar.parse_ref`
accepts either, so a label always resolves in whichever style emitted it.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from reference_points.decompose import (
    CodeBlock,
    Diagram,
    Entity,
    ListBlock,
    Message,
    Paragraph,
    Quote,
    Section,
    Table,
)

_MAP_EXCERPT = 60


@dataclass(frozen=True)
class LabelStyle:
    """The marker set a label is drawn with. Display-only: both styles parse."""

    turn: str
    section: str
    joiner: str
    entity: str


ASCII = LabelStyle(turn="N", section="S", joiner="-", entity=".")
GLYPH = LabelStyle(turn="◆", section="§", joiner=" ", entity="·")


def _entity_letter(entity: Entity) -> str:
    return type(entity).__name__[0]  # Paragraph→P, Table→T, ListBlock→L, ... Section→S


def _section_header(section: Section, turn: int, style: LabelStyle) -> str:
    head = f"{style.turn}{turn}{style.joiner}{style.section}{section.index}"
    return f"{head} {section.heading}" if section.heading else head


_THEMATIC_BREAK_RE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")


def _is_position_sensitive(line: str) -> bool:
    """True when a line means what it means *because of* its leading characters,
    so prefixing a label onto it would destroy the construct — an indented code
    block, a thematic break, or the start of an HTML block."""
    return (
        line.startswith(("    ", "\t"))
        or _THEMATIC_BREAK_RE.match(line) is not None
        or line.lstrip().startswith("<")
    )


@dataclass
class _LabelPlan:
    """Line-indexed edits to apply to ``lines``: markers inserted above a line, an
    inline prefix on a line, or a whole-line replacement."""

    lines: list[str]
    before: defaultdict[int, list[str]] = field(default_factory=lambda: defaultdict(list))
    prefix: dict[int, str] = field(default_factory=dict[int, str])
    replace: dict[int, str] = field(default_factory=dict[int, str])

    def label_paragraph(self, line: int, tag: str) -> None:
        """Inline prefix by default; own line above when prefixing would corrupt.

        The blank line is load-bearing: without it the construct below becomes a
        lazy continuation of the label's paragraph, which turns ``---`` into a
        setext heading and an indented block into ordinary prose."""
        if line < len(self.lines) and _is_position_sensitive(self.lines[line]):
            self.before[line].extend((tag, ""))
        else:
            self.prefix[line] = tag


def _heading_line(level: int, label: str, heading: str) -> str:
    """Rebuild a heading line so the labeled copy still renders as markdown — the
    ATX markers are kept and the label joins the heading text."""
    text = f"{label} {heading}" if heading else label
    return f"{'#' * level} {text}" if level else text


def _label_entity(entity: Entity, style: LabelStyle, plan: _LabelPlan) -> None:
    tag = f"{style.entity}{_entity_letter(entity)}{entity.index}"
    if isinstance(entity, Paragraph):
        plan.label_paragraph(entity.line, tag)
    elif isinstance(entity, Section):
        plan.replace[entity.line] = _heading_line(entity.level, tag, entity.heading)
        for child in entity.entities:
            _label_entity(child, style, plan)
    else:
        # Table, CodeBlock, ListBlock, Diagram, Quote: label on its own line above.
        # (v1: quote inner entities resolve but are not sub-labeled inline.)
        plan.before[entity.line].append(tag)


def _label_section(section: Section, turn: int, style: LabelStyle, plan: _LabelPlan) -> None:
    header = _section_header(section, turn, style)
    if section.line >= 0:
        plan.replace[section.line] = _heading_line(section.level, header, "")
    else:  # implicit S1 — no heading line, anchor the marker above the first block
        anchor = min((e.line for e in section.entities if e.line >= 0), default=0)
        plan.before[anchor].insert(0, header)
    for entity in section.entities:
        _label_entity(entity, style, plan)


def render_inline(msg: Message, turn: int, style: LabelStyle = ASCII) -> str:
    """Return the message source with labels injected (formatting preserved)."""
    plan = _LabelPlan(msg.source.splitlines())
    for section in msg.sections:
        _label_section(section, turn, style, plan)

    out: list[str] = []
    for idx, line in enumerate(plan.lines):
        out.extend(plan.before.get(idx, []))
        if idx in plan.replace:
            out.append(plan.replace[idx])
        elif idx in plan.prefix:
            out.append(f"{plan.prefix[idx]} {line}")
        else:
            out.append(line)
    return "\n".join(out)


def _excerpt(entity: Entity) -> str:
    if isinstance(entity, Paragraph):
        text = entity.text
        return text if len(text) <= _MAP_EXCERPT else text[: _MAP_EXCERPT - 1] + "…"
    if isinstance(entity, Table):
        cols = len(entity.rows[0]) if entity.rows else 0
        return f"{len(entity.rows)} rows x {cols} cols"
    if isinstance(entity, CodeBlock):
        return f"{len(entity.lines)} lines ({entity.lang or 'code'})"
    if isinstance(entity, ListBlock):
        return f"{len(entity.items)} items"
    if isinstance(entity, Diagram | Quote):
        return type(entity).__name__.lower()  # "diagram" / "quote"
    return entity.heading or "(untitled)"  # Section


def _map_lines(entities: tuple[Entity, ...], indent: str, style: LabelStyle) -> list[str]:
    rows: list[str] = []
    for entity in entities:
        tag = f"{style.entity}{_entity_letter(entity)}{entity.index}"
        rows.append(f"{indent}{tag}  {_excerpt(entity)}")
        if isinstance(entity, Section | Quote):
            rows.extend(_map_lines(entity.entities, indent + "  ", style))
    return rows


def render_map(msg: Message, turn: int, style: LabelStyle = ASCII) -> str:
    """Return a compact ``address → excerpt`` index for the whole message."""
    out: list[str] = []
    for section in msg.sections:
        out.append(_section_header(section, turn, style))
        out.extend(_map_lines(section.entities, "  ", style))
    return "\n".join(out)
