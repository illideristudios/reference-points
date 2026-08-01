"""Tests for the transcript container."""

from __future__ import annotations

from reference_points.decompose import decompose
from reference_points.transcript import Prompt, Transcript, Turn


def test_turns_are_the_addressable_entries_only() -> None:
    transcript = Transcript((
        Prompt("a question"),
        Turn(decompose("a reply.", turn=1)),
        Prompt("another question"),
        Turn(decompose("another reply.", turn=2)),
    ))
    assert len(transcript.entries) == 4
    assert [t.message.turn for t in transcript.turns] == [1, 2]


def test_a_transcript_of_prompts_alone_has_no_turns() -> None:
    assert Transcript((Prompt("hello"),)).turns == ()
