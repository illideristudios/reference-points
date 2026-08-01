"""Shared fixtures — the worked example from REFERENCE_POINTS.md, and the
torture document that exercises every construct the parser has to get right."""

from __future__ import annotations

from pathlib import Path

import pytest

from reference_points.decompose import Message, decompose

TORTURE_PATH = Path(__file__).parent / "fixtures" / "torture.md"

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
    return decompose(WORKED_MD)


@pytest.fixture
def torture_md() -> str:
    return TORTURE_PATH.read_text(encoding="utf-8")


@pytest.fixture
def torture_msg(torture_md: str) -> Message:
    return decompose(torture_md)
