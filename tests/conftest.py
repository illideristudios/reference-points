"""Shared fixtures — the worked example from REFERENCE_POINTS.md, and the torture
document that exercises every construct the parser has to get right."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from reference_points import claude_code
from reference_points.decompose import Message, decompose

if TYPE_CHECKING:
    from reference_points.transcript import Transcript

TORTURE_PATH = Path(__file__).parent / "fixtures" / "torture.md"
TRANSCRIPT_PATH = Path(__file__).parent / "fixtures" / "transcript.jsonl"

WORKED_MD = """\
## Costs

The pricing tiers changed last quarter. Here is the current breakdown.

| Tier | Price | Seats |
|------|-------|-------|
| Free | $0 | 1 |
| Pro | $12 | 5 |
| Team | $40 | 20 |

Enterprise pricing is negotiated separately.
"""


@pytest.fixture
def worked_msg() -> Message:
    return decompose(WORKED_MD, turn=27)


@pytest.fixture
def torture_md() -> str:
    return TORTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture
def torture_msg(torture_md: str) -> Message:
    return decompose(torture_md)


@pytest.fixture
def transcript_jsonl() -> str:
    return TRANSCRIPT_PATH.read_text(encoding="utf-8")


@pytest.fixture
def transcript(transcript_jsonl: str) -> Transcript:
    return claude_code.parse(transcript_jsonl)
