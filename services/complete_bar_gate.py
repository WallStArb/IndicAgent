"""The complete-bar gate at the edge of every fetch path (second review of plan 191-07, finding 5).

Every vendor answer passes through here before it is offered to ohlcv_raw: the IBKR fetcher's
persister (judged per request against that request's answer time and window end), the nightly
capture runner (Alpaca and any later vendor leaf) and the ad hoc `store_bars` callers. The rule
itself is the pure, vendor-agnostic `src/intelligence/bars/complete_bars.py`; this module adds
the APR read (the session-close settle delay) and the one log shape for what was held back.

A partial bar is never dropped silently: the caller records it on its ledger row
(`ohlcv_request.partial_bars` through the sink's `note_partial`) when it has one, and every
caller gets one structured log line carrying the values. The gap planner does not count a
recorded partial slot as answered, so the slot is asked again once the bar is complete.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

import structlog

from src.intelligence.bars.complete_bars import partial_json, split_complete

logger = structlog.get_logger(__name__)

SETTLE_KEY = "threshold.bar_integrity.session_close_settle_s"


def read_settle(cur: Any) -> timedelta:
    """The session-close settle delay from config_state (migration 479); missing is loud."""
    cur.execute("SELECT config_value FROM config_state WHERE config_key = %s", (SETTLE_KEY,))
    row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"{SETTLE_KEY} missing from config_state (migration 479)")
    return timedelta(seconds=int(float(row[0])))


def keep_complete[T](
    bars: Sequence[T],
    timeframe: str,
    *,
    answered_at: datetime,
    request_end: datetime | None,
    settle: timedelta,
    symbol: str,
    caller: str,
) -> tuple[list[T], list[T], str | None]:
    """(complete, partial, partial_json_text). The text is what the caller writes to its ledger
    row (None when nothing was held back); one warning line carries the same values."""
    complete, partial = split_complete(
        bars, timeframe, answered_at=answered_at, request_end=request_end, settle=settle
    )
    if not partial:
        return complete, partial, None
    values = partial_json(partial)
    logger.warning(
        "complete_bar_gate.partial_bars_held_back",
        caller=caller,
        symbol=symbol,
        timeframe=timeframe,
        answered_at=answered_at.isoformat(),
        request_end=None if request_end is None else request_end.isoformat(),
        n=len(partial),
        bars=values,
    )
    return complete, partial, json.dumps(values)
