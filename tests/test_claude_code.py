"""Tests for the Claude Code session reader.

Every assertion here is about turn *numbers*, not just counts. A record that
slips through the filter does not add noise at the end — it shifts every number
after it, and an address that used to be right silently becomes wrong.
"""

from __future__ import annotations

import json

from reference_points import claude_code
from reference_points.transcript import Prompt, Turn


def _line(**record: object) -> str:
    return json.dumps(record)


def _assistant(*texts: str) -> str:
    return _line(
        type="assistant",
        message={"role": "assistant", "content": [{"type": "text", "text": t} for t in texts]},
    )


def _user(*texts: str) -> str:
    return _line(
        type="user",
        message={"role": "user", "content": [{"type": "text", "text": t} for t in texts]},
    )


def test_the_fixture_reads_to_three_turns_and_three_prompts(transcript_jsonl: str) -> None:
    transcript = claude_code.parse(transcript_jsonl)
    assert [t.message.turn for t in transcript.turns] == [1, 2, 3]
    assert sum(isinstance(e, Prompt) for e in transcript.entries) == 3
    assert [type(e).__name__ for e in transcript.entries] == [
        "Prompt",
        "Turn",
        "Prompt",
        "Turn",
        "Prompt",
        "Turn",
    ]


def test_consecutive_assistant_messages_are_one_turn(transcript_jsonl: str) -> None:
    # N1 is split across two text messages by a tool call; a reader sees one reply.
    first = claude_code.parse(transcript_jsonl).turns[0].message
    assert "The first half of the reply." in first.source
    assert "The second half of the reply." in first.source


def test_a_prompt_between_two_replies_splits_them() -> None:
    jsonl = "\n".join([_assistant("one."), _user("question?"), _assistant("two.")])
    assert [t.message.turn for t in claude_code.parse(jsonl).turns] == [1, 2]


def test_consecutive_user_messages_are_one_prompt(transcript_jsonl: str) -> None:
    prompts = [e for e in claude_code.parse(transcript_jsonl).entries if isinstance(e, Prompt)]
    assert prompts[1].text == "Second question.\n\nA follow-up."


def test_a_bare_string_message_is_read(transcript_jsonl: str) -> None:
    # Not every record wraps its content in blocks.
    prompts = [e for e in claude_code.parse(transcript_jsonl).entries if isinstance(e, Prompt)]
    assert prompts[2].text == "Third question."


# --- exclusions ----------------------------------------------------------


def test_a_sidechain_is_not_the_conversation_you_are_in() -> None:
    jsonl = "\n".join([
        _assistant("real reply."),
        _line(
            type="assistant",
            isSidechain=True,
            message={"role": "assistant", "content": [{"type": "text", "text": "subagent."}]},
        ),
        _user("question?"),
        _assistant("second real reply."),
    ])
    turns = claude_code.parse(jsonl).turns
    assert [t.message.turn for t in turns] == [1, 2]
    assert "subagent" not in turns[0].message.source


def test_tool_use_and_tool_result_are_not_spoken() -> None:
    jsonl = "\n".join([
        _line(
            type="assistant",
            message={
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "private"},
                    {"type": "tool_use", "id": "x", "name": "Bash"},
                ],
            },
        ),
        _line(
            type="user",
            message={
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "x", "content": "output"},
                ],
            },
        ),
        _assistant("the only spoken thing."),
    ])
    transcript = claude_code.parse(jsonl)
    assert [t.message.turn for t in transcript.turns] == [1]
    assert transcript.turns[0].message.source == "the only spoken thing."
    assert not [e for e in transcript.entries if isinstance(e, Prompt)]


def test_meta_records_are_not_turns() -> None:
    jsonl = "\n".join([
        _line(
            type="assistant",
            isMeta=True,
            message={"role": "assistant", "content": [{"type": "text", "text": "meta."}]},
        ),
        _assistant("spoken."),
    ])
    turns = claude_code.parse(jsonl).turns
    assert [t.message.source for t in turns] == ["spoken."]


def test_a_slash_command_echo_is_the_cli_not_the_user() -> None:
    jsonl = "\n".join([
        _user("<command-name>/clear</command-name>"),
        _user("the actual question."),
        _assistant("reply."),
    ])
    prompts = [e for e in claude_code.parse(jsonl).entries if isinstance(e, Prompt)]
    assert [p.text for p in prompts] == ["the actual question."]


def test_an_injected_system_reminder_is_stripped_from_a_prompt() -> None:
    jsonl = "\n".join([
        _user("real words.\n<system-reminder>injected</system-reminder>"),
        _assistant("reply."),
    ])
    prompts = [e for e in claude_code.parse(jsonl).entries if isinstance(e, Prompt)]
    assert prompts[0].text == "real words."


def test_non_message_record_types_are_skipped() -> None:
    jsonl = "\n".join([
        _line(type="file-history-snapshot", snapshot={}),
        _line(type="mode", mode="default"),
        _line(type="ai-title", aiTitle="t"),
        _line(type="attachment", attachment={}),
        _assistant("the reply."),
    ])
    assert [t.message.turn for t in claude_code.parse(jsonl).turns] == [1]


def test_a_malformed_line_is_skipped_not_fatal() -> None:
    # A session still being written ends in a partial line.
    jsonl = _assistant("reply.") + '\n{"type": "assist'
    assert [t.message.turn for t in claude_code.parse(jsonl).turns] == [1]


def test_an_empty_transcript_reads_clean() -> None:
    assert claude_code.parse("").entries == ()


def test_a_turn_is_decomposed_like_any_message(transcript_jsonl: str) -> None:
    second = claude_code.parse(transcript_jsonl).turns[1].message
    letters = [type(e).__name__[0] for e in second.sections[0].entities]
    assert letters == ["P", "T", "P", "C"]


def test_a_prompt_is_never_decomposed(transcript_jsonl: str) -> None:
    # Nothing can point into it, so there is nothing to decompose it for.
    entry = claude_code.parse(transcript_jsonl).entries[0]
    assert isinstance(entry, Prompt)
    assert not hasattr(entry, "message")
    assert not isinstance(entry, Turn)
