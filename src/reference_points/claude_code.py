"""Read a Claude Code session transcript (JSONL) into a :class:`Transcript`.

The file interleaves the conversation with everything else the CLI records: tool
calls and their results, thinking, subagent sidechains, snapshots, slash-command
echoes. All of it has to go, and *precisely* — a record that slips through does
not add noise at the end, it shifts every turn number after it.

A turn is one **run** of consecutive assistant messages, joined. One reply that
emitted text, called a tool and emitted more text is one reply to the reader, so
it is one turn; runs of thirteen are ordinary.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, cast

from reference_points.decompose import decompose
from reference_points.transcript import Entry, Prompt, Transcript, Turn

if TYPE_CHECKING:
    from collections.abc import Iterator

_SPOKEN = frozenset({"user", "assistant"})

# A user record carrying one of these is the CLI talking, not the user: a slash
# command echo, or the caveat wrapper around a local command's output.
_CLI_ECHO = ("<command-name>", "<local-command-stdout>", "local-command-caveat")

# Injected into a real user message rather than sent by anyone. Stripped from the
# prompt text; it cannot affect numbering, since prompts are never numbered.
_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>\s*", re.DOTALL)


def _records(jsonl: str) -> Iterator[dict[str, Any]]:
    """Every well-formed record. A malformed line is skipped rather than fatal —
    a truncated final line is normal in a session still being written."""
    for line in jsonl.splitlines():
        if not line.strip():
            continue
        try:
            record: object = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            yield cast("dict[str, Any]", record)


def _texts(content: object) -> list[str]:
    """The spoken text of a message. Everything else a content block can be —
    ``thinking``, ``tool_use``, ``tool_result`` — is not spoken and is dropped."""
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    out: list[str] = []
    for block in cast("list[object]", content):
        if isinstance(block, dict):
            entry = cast("dict[str, object]", block)
            if entry.get("type") == "text":
                text = entry.get("text")
                if isinstance(text, str):
                    out.append(text)
    return out


def _visible(jsonl: str) -> list[tuple[str, str]]:
    """``(role, text)`` for every message a reader actually sees, in order."""
    seen: list[tuple[str, str]] = []
    for record in _records(jsonl):
        if record.get("type") not in _SPOKEN or record.get("isSidechain") or record.get("isMeta"):
            continue
        message = record.get("message")
        if not isinstance(message, dict):
            continue
        fields = cast("dict[str, object]", message)
        role = fields.get("role")
        if role not in _SPOKEN:
            continue
        text = "\n\n".join(part for part in _texts(fields.get("content")) if part.strip())
        if role == "user":
            if any(marker in text for marker in _CLI_ECHO):
                continue
            text = _REMINDER_RE.sub("", text)
        if text.strip():
            seen.append((cast("str", role), text.strip()))
    return seen


def _runs(messages: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Join each run of consecutive same-role messages into one."""
    runs: list[tuple[str, list[str]]] = []
    for role, text in messages:
        if runs and runs[-1][0] == role:
            runs[-1][1].append(text)
        else:
            runs.append((role, [text]))
    return [(role, "\n\n".join(parts)) for role, parts in runs]


def parse(jsonl: str) -> Transcript:
    """Read the text of a session file into a :class:`Transcript`."""
    entries: list[Entry] = []
    turn = 0
    for role, text in _runs(_visible(jsonl)):
        if role == "assistant":
            turn += 1
            entries.append(Turn(decompose(text, turn=turn)))
        else:
            entries.append(Prompt(text))
    return Transcript(tuple(entries))
