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
    Reference,
    Section,
    Table,
)

_MAP_EXCERPT = 60

# Purely a label-safety heuristic now: the decomposer gets thematic breaks as
# tokens, but a label written onto one would turn it into a setext heading.
THEMATIC_BREAK_RE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")


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


def _section_prefix(section: Section, turn: int, style: LabelStyle) -> str:
    """The section's full address — ``N27-S1``, without its heading text."""
    return f"{style.turn}{turn}{style.joiner}{style.section}{section.index}"


def _section_header(section: Section, turn: int, style: LabelStyle) -> str:
    head = _section_prefix(section, turn, style)
    return f"{head} {section.heading}" if section.heading else head


def _is_position_sensitive(line: str) -> bool:
    """True when a line means what it means *because of* its leading characters,
    so a label written onto or immediately above it would destroy the construct —
    an indented code block, a thematic break, or the start of an HTML block."""
    return (
        line.startswith(("    ", "\t"))
        or THEMATIC_BREAK_RE.match(line) is not None
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

    def label_above(self, line: int, tag: str) -> None:
        """Put the tag on its own line above ``line``, plus a blank line when the
        target's leading characters are load-bearing.

        That blank line is the whole rule: without it the construct below becomes
        a lazy continuation of the label's paragraph, which turns an indented
        block into ordinary prose and ``---`` into a setext heading.
        """
        self.before[line].append(tag)
        if self._is_sensitive(line):
            self.before[line].append("")

    def label_paragraph(self, line: int, tag: str) -> None:
        """Inline prefix by default; above when prefixing would corrupt the line."""
        if self._is_sensitive(line):
            self.label_above(line, tag)
        else:
            self.prefix[line] = tag

    def _is_sensitive(self, line: int) -> bool:
        return line < len(self.lines) and _is_position_sensitive(self.lines[line])


def _label_heading(section: Section, label: str, plan: _LabelPlan) -> None:
    """Write ``label`` onto a heading line, keeping the line a heading.

    ATX rebuilds the line from its own markers. Setext prefixes the label onto the
    heading text and leaves the underline alone — rebuilding would strand the
    underline, and on a multi-line setext heading it would duplicate the text.
    """
    if section.markup.startswith("#"):
        text = f"{label} {section.heading}" if section.heading else label
        plan.replace[section.line] = f"{section.markup} {text}"
    else:
        plan.prefix[section.line] = label


def _label_entity(entity: Entity, style: LabelStyle, plan: _LabelPlan) -> None:
    if isinstance(entity, Reference):
        # A link reference definition renders to nothing, so an inline label would
        # put visible text where the reader saw none — and would stop the line
        # being a definition at all. Addressable, never labeled: see render_map.
        return
    tag = f"{style.entity}{_entity_letter(entity)}{entity.index}"
    if isinstance(entity, Paragraph):
        plan.label_paragraph(entity.line, tag)
    elif isinstance(entity, Section):
        _label_heading(entity, tag, plan)
        for child in entity.entities:
            _label_entity(child, style, plan)
    else:
        # Table, CodeBlock, ListBlock, Diagram, Quote: label on its own line above.
        # (v1: quote inner entities resolve but are not sub-labeled inline.)
        plan.label_above(entity.line, tag)


def _anchor_line(section: Section) -> int:
    """The line the implicit S1's marker sits above: the first entity that can
    carry one. A reference definition cannot — a marker written above it makes the
    definition a lazy continuation of the marker's paragraph, so it stops being a
    definition and every link through it renders as literal text.
    """
    lines = [e.line for e in section.entities if e.line >= 0 and not isinstance(e, Reference)]
    return min(lines, default=-1)


def _label_section(section: Section, turn: int, style: LabelStyle, plan: _LabelPlan) -> None:
    if section.line >= 0:
        _label_heading(section, _section_prefix(section, turn, style), plan)
    else:  # implicit S1 — no heading line, anchor the marker above the first block
        anchor = _anchor_line(section)
        if anchor >= 0:  # nothing to anchor to: emit no marker rather than line 0
            plan.before[anchor].insert(0, _section_header(section, turn, style))
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


def _excerpt(entity: Entity) -> str:  # ruff: ignore[too-many-return-statements]
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
    if isinstance(entity, Reference):
        return f"{entity.key} → {entity.destination}"
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
