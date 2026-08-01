"""Shared fixtures — the worked example from REFERENCE_POINTS.md."""

from __future__ import annotations

import pytest

from reference_points.decompose import Message, decompose

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
