"""A conversation: addressable replies, and the prompts they answered.

Format-agnostic — nothing here knows how a conversation is stored. A *reader*
turns some concrete file into this shape; see :mod:`reference_points.claude_code`.

Only one of the two entry types is addressable, and that asymmetry is stated in
the types rather than in a role string a caller has to remember to check.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from reference_points.decompose import Message


@dataclass(frozen=True)
class Block:
    """One stretch of a reply that arrived as its own record. ``line`` is where it
    starts in ``Turn.message.source``, which is the blocks joined by a blank line.

    A viewer that draws a reply a piece at a time knows only the piece's ``uuid``;
    this is what turns it back into a place in the reply.
    """

    uuid: str
    line: int


@dataclass(frozen=True)
class Turn:
    """An assistant reply. ``message.turn`` is the ``N`` an address names."""

    message: Message
    blocks: tuple[Block, ...] = ()


@dataclass(frozen=True)
class Prompt:
    """A user message: shown for context, never numbered, never addressed. Held as
    raw text because nothing can point into it, so there is nothing to decompose
    it for."""

    text: str


Entry = Turn | Prompt


@dataclass(frozen=True)
class Transcript:
    """The conversation in order, prompts and replies interleaved."""

    entries: tuple[Entry, ...]

    @property
    def turns(self) -> tuple[Turn, ...]:
        return tuple(entry for entry in self.entries if isinstance(entry, Turn))
