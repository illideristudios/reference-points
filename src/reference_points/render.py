"""Render a decomposed :class:`Message` into labeled views.

``render_inline`` injects labels into the *original source*, so the reply keeps its
exact formatting; ``render_map`` is a compact address→excerpt overlay instead. A
section header carries the full prefix and every other entity only its fragment —
full paths are for references, fragments for labels. Both styles parse.
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

# Label safety only — decompose gets breaks as tokens. A label written onto one
# would turn it into a setext heading.
THEMATIC_BREAK_RE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")


@dataclass(frozen=True)
class LabelStyle:
    """Display-only: both styles parse."""

    turn: str
    section: str
    joiner: str
    entity: str


ASCII = LabelStyle(turn="N", section="S", joiner="-", entity=".")
GLYPH = LabelStyle(turn="◆", section="§", joiner=" ", entity="·")


def _entity_letter(entity: Entity) -> str:
    return type(entity).__name__[0]  # Paragraph→P, Table→T, ListBlock→L, ... Section→S


def _section_prefix(section: Section, turn: int, style: LabelStyle) -> str:
    """``N27-S1``, without the heading text."""
    return f"{style.turn}{turn}{style.joiner}{style.section}{section.index}"


def _section_header(section: Section, turn: int, style: LabelStyle) -> str:
    head = _section_prefix(section, turn, style)
    return f"{head} {section.heading}" if section.heading else head


def _is_position_sensitive(line: str) -> bool:
    """Indented code, a thematic break, the start of an HTML block: a label written
    onto or immediately above one destroys the construct."""
    return (
        line.startswith(("    ", "\t"))
        or THEMATIC_BREAK_RE.match(line) is not None
        or line.lstrip().startswith("<")
    )


@dataclass
class _LabelPlan:
    """Line-indexed edits: markers above a line, an inline prefix, or a replacement."""

    lines: list[str]
    before: defaultdict[int, list[str]] = field(default_factory=lambda: defaultdict(list))
    prefix: dict[int, str] = field(default_factory=dict[int, str])
    replace: dict[int, str] = field(default_factory=dict[int, str])

    def label_above(self, line: int, tag: str) -> None:
        """The blank line is the rule: without it the block below becomes a lazy
        continuation of the label's paragraph — indented code turns into prose,
        ``---`` into a setext heading."""
        self.before[line].append(tag)
        if self._is_sensitive(line):
            self.before[line].append("")

    def label_paragraph(self, line: int, tag: str) -> None:
        """Above instead when prefixing would corrupt the line."""
        if self._is_sensitive(line):
            self.label_above(line, tag)
        else:
            self.prefix[line] = tag

    def _is_sensitive(self, line: int) -> bool:
        return line < len(self.lines) and _is_position_sensitive(self.lines[line])


def _label_heading(section: Section, label: str, plan: _LabelPlan) -> None:
    """ATX rebuilds the line from its markers; setext only prefixes, since
    rebuilding would strand the underline and duplicate a multi-line heading."""
    if section.markup.startswith("#"):
        text = f"{label} {section.heading}" if section.heading else label
        plan.replace[section.line] = f"{section.markup} {text}"
    else:
        plan.prefix[section.line] = label


def _label_entity(entity: Entity, style: LabelStyle, plan: _LabelPlan) -> None:
    if isinstance(entity, Reference):
        # Labeling one stops it being a definition, so every [key] in the copy
        # becomes literal text. Its address lives in render_map instead.
        return
    tag = f"{style.entity}{_entity_letter(entity)}{entity.index}"
    if isinstance(entity, Paragraph):
        plan.label_paragraph(entity.line, tag)
    elif isinstance(entity, Section):
        _label_heading(entity, tag, plan)
        for child in entity.entities:
            _label_entity(child, style, plan)
    else:
        # v1: a quote's inner entities resolve but are not sub-labeled inline.
        plan.label_above(entity.line, tag)


def _anchor_line(section: Section) -> int:
    """The first entity that can carry the implicit S1's marker. Not a reference
    definition: a marker above it makes the definition a lazy continuation, and
    every link through it renders as text."""
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
    """The source with labels injected, formatting preserved."""
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
    """A compact ``address → excerpt`` index for the whole message."""
    out: list[str] = []
    for section in msg.sections:
        out.append(_section_header(section, turn, style))
        out.extend(_map_lines(section.entities, "  ", style))
    return "\n".join(out)
