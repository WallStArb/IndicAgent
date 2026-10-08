"""BarHold: the one definition of a held name (phase 185 plan 51, todo 515; migration 461).

A name is held for a timeframe while ``bar_hold_current`` has a row for it: its canonical bars
stay as they are until a decision releases it. Today the one reason is ``unclassified_rescale``,
a vendor rescale of the name's history whose factor is no recognised split ratio
(src/intelligence/bars/corporate_actions.recognised_split_ratio), for example CTVA's 39/7 after
the Vylor spin-off. Such a rescale is never written to corporate_action; applying the vendor's
rewrite would record a spin-off as a split.

One writer: ``record_hold`` and ``release_hold`` here, under bar_derivation_writer. Callers are
the fetcher's in-process overlap judge and scripts/ops/bars/ops_split_detect.py (both through
its act_on_detections and its by-hand flags). ``bar_hold`` is append-only (UPDATE, DELETE and
TRUNCATE raise); a release is a new row whose ``releases`` names the hold.

Readers of ``held``: the daily stage (services/bar_derivation.py skips a held name, scoped or
not, so no rewrite is applied), the overlap judge (``record_hold`` is idempotent per symbol and
factor, so the same rescale is not held twice) and D7 (services/bar_reconciliation_audit.py
reports every hold and names it beside a failing freshness_1d).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from uuid import uuid4

REASON_UNCLASSIFIED_RESCALE = "unclassified_rescale"
_REASON_RELEASE = "release"
_HOLD_REASONS = frozenset({REASON_UNCLASSIFIED_RESCALE})
_WRITER_ROLE_SQL = "SET LOCAL ROLE bar_derivation_writer"

_COLUMNS = (
    "hold_id::text AS hold_id, symbol, timeframe, reason, factor, first_affected_date, "
    "last_affected_date, action_id::text AS action_id, detail, recorded_by, recorded_at"
)

_SELECT_HELD_SQL = f"""
SELECT {_COLUMNS}
FROM bar_hold_current
WHERE timeframe = $1
ORDER BY symbol, recorded_at
"""

_SELECT_OPEN_FACTORS_SQL = """
SELECT factor FROM bar_hold_current
WHERE symbol = $1 AND timeframe = $2 AND reason = $3
"""

_SELECT_OPEN_HOLD_SQL = f"""
SELECT {_COLUMNS}
FROM bar_hold_current
WHERE hold_id = $1::uuid
"""

_INSERT_SQL = """
INSERT INTO bar_hold
    (hold_id, symbol, timeframe, reason, factor, first_affected_date, last_affected_date,
     action_id, detail, recorded_by, releases)
VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, $8::uuid, $9::text::jsonb, $10, $11::uuid)
"""

# Each route's latest TRADES answer against the canonical bar of the same date, over the
# affected dates ($2 NULL: from the first canonical bar). The rescale a vendor applied reads as
# canonical/latest; first and last date are where it differs from 1 by more than $4. Canonical
# is the tradeable view (compute and measurement never read the raw table).
_VENDOR_RATIOS_SQL = """
WITH canon AS (
    SELECT ("timestamp" AT TIME ZONE 'UTC')::date AS bar_date, close
    FROM market_data_ohlcv_tradeable
    WHERE symbol = $1 AND timeframe = '1d'
      AND ($2::date IS NULL OR "timestamp" >= ($2::date)::timestamp AT TIME ZONE 'UTC')
      AND "timestamp" < ($3::date + 1)::timestamp AT TIME ZONE 'UTC'
), latest AS (
    SELECT DISTINCT ON (o.route, o.bar_date) o.route, o.bar_date, o.close
    FROM ohlcv_observation o
    JOIN ohlcv_request q ON q.request_id = o.request_id
    WHERE o.symbol = $1 AND o.timeframe = '1d' AND o.what_to_show = 'TRADES'
      AND o.route IN ('SMART', 'TRADIER') AND q.caller NOT LIKE 'test-%'
      AND ($2::date IS NULL OR o.bar_date >= $2::date) AND o.bar_date <= $3::date
    ORDER BY o.route, o.bar_date, o.fetched_at DESC
)
SELECT l.route,
       count(*) AS n_dates,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY c.close / l.close) AS median_ratio,
       min(l.bar_date) FILTER (WHERE abs(c.close / l.close - 1) > $4) AS first_date,
       max(l.bar_date) FILTER (WHERE abs(c.close / l.close - 1) > $4) AS last_date
FROM latest l
JOIN canon c ON c.bar_date = l.bar_date
WHERE l.close > 0
GROUP BY l.route
ORDER BY l.route
"""


@dataclass(frozen=True)
class Hold:
    """One open hold (a bar_hold_current row)."""

    hold_id: str
    symbol: str
    timeframe: str
    reason: str
    factor: float | None
    first_affected_date: date | None
    last_affected_date: date | None
    action_id: str | None
    detail: dict[str, Any] = field(compare=False)
    recorded_by: str
    recorded_at: datetime

    @classmethod
    def from_record(cls, row: Any) -> Hold:
        detail = row["detail"]
        if isinstance(detail, str):  # a bare connection without the jsonb codec
            detail = json.loads(detail)
        return cls(
            hold_id=str(row["hold_id"]),
            symbol=row["symbol"],
            timeframe=row["timeframe"],
            reason=row["reason"],
            factor=None if row["factor"] is None else float(row["factor"]),
            first_affected_date=row["first_affected_date"],
            last_affected_date=row["last_affected_date"],
            action_id=row["action_id"],
            detail=dict(detail or {}),
            recorded_by=row["recorded_by"],
            recorded_at=row["recorded_at"],
        )

    def cause(self) -> str:
        """One line for logs and reports: reason, factor, affected span, since when."""
        parts = [self.reason]
        if self.factor is not None:
            parts.append(f"factor {self.factor:.4f}")
        if self.first_affected_date and self.last_affected_date:
            parts.append(f"over {self.first_affected_date}..{self.last_affected_date}")
        return f"{' '.join(parts)}, held since {self.recorded_at.date()}"


async def held(conn: Any, timeframe: str) -> dict[str, tuple[Hold, ...]]:
    """Every held name of `timeframe` with its open holds, oldest first."""
    out: dict[str, list[Hold]] = {}
    for row in await conn.fetch(_SELECT_HELD_SQL, timeframe):
        hold = Hold.from_record(row)
        out.setdefault(hold.symbol, []).append(hold)
    return {symbol: tuple(holds) for symbol, holds in out.items()}


async def record_hold(
    conn: Any,
    *,
    symbol: str,
    timeframe: str,
    reason: str,
    factor: float,
    first_affected_date: date,
    last_affected_date: date,
    detail: dict[str, Any],
    recorded_by: str,
    rel_tol: float,
    action_id: str | None = None,
) -> str | None:
    """Hold `symbol` for `reason`; the new hold_id, or None when an open hold of the same
    symbol, timeframe and reason already carries this factor within `rel_tol` (the same rescale
    seen again is not a new event). One transaction under bar_derivation_writer (a savepoint
    when the caller already holds one)."""
    if reason not in _HOLD_REASONS:
        raise ValueError(f"unknown hold reason {reason!r}")
    if not factor > 0:
        raise ValueError(f"{symbol}: a hold factor must be positive, got {factor!r}")
    async with conn.transaction():
        await conn.execute(_WRITER_ROLE_SQL)
        existing = await conn.fetch(_SELECT_OPEN_FACTORS_SQL, symbol, timeframe, reason)
        if any(
            r["factor"] is not None and abs(float(r["factor"]) / factor - 1.0) <= rel_tol
            for r in existing
        ):
            return None
        hold_id = str(uuid4())
        await conn.execute(
            _INSERT_SQL,
            hold_id,
            symbol,
            timeframe,
            reason,
            float(factor),
            first_affected_date,
            last_affected_date,
            action_id,
            json.dumps(detail, sort_keys=True, default=str),
            recorded_by,
            None,
        )
    return hold_id


async def release_hold(conn: Any, *, hold_id: str, why: str, recorded_by: str) -> str:
    """Release an open hold with a release row; returns the release row's id."""
    if not why.strip():
        raise ValueError("a release needs a reason")
    async with conn.transaction():
        await conn.execute(_WRITER_ROLE_SQL)
        row = await conn.fetchrow(_SELECT_OPEN_HOLD_SQL, hold_id)
        if row is None:
            raise LookupError(f"no open hold {hold_id}")
        release_id = str(uuid4())
        await conn.execute(
            _INSERT_SQL,
            release_id,
            row["symbol"],
            row["timeframe"],
            _REASON_RELEASE,
            None,
            None,
            None,
            None,
            json.dumps({"why": why}),
            recorded_by,
            hold_id,
        )
    return release_id


async def vendor_rescale_ratios(
    conn: Any, symbol: str, first: date | None, last: date, *, rel_tol: float
) -> dict[str, dict[str, Any]]:
    """Per route (SMART, TRADIER): median canonical/latest close over the affected dates, the
    number of dates, and the first and last date the ratio differs from 1 by more than
    `rel_tol`. CTVA 2026-10-08: SMART 5.571 (IBKR's restatement), TRADIER 6.665."""
    out: dict[str, dict[str, Any]] = {}
    for row in await conn.fetch(_VENDOR_RATIOS_SQL, symbol, first, last, rel_tol):
        out[row["route"]] = {
            "median_ratio": None if row["median_ratio"] is None else float(row["median_ratio"]),
            "n_dates": int(row["n_dates"]),
            "first_date": None if row["first_date"] is None else row["first_date"].isoformat(),
            "last_date": None if row["last_date"] is None else row["last_date"].isoformat(),
        }
    return out
