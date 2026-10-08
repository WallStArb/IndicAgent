"""Split inference from overlapping D1 observations (phase 185 plan 22, D-21).

The fetcher's update lane re-asks the last infra.backfill.update_overlap_sessions_1d sessions,
so every fresh SMART TRADES observation overlaps an earlier one in D1. IBKR re-scales history
when a split happens: the earlier observation of a date stays on the old scale while the fresh
fetch is on the new one, so the stored/fresh close ratio is the split factor over the whole
overlap
(src/intelligence/bars/seams.py). A constant run is inferred as a split
(src/intelligence/bars/corporate_actions.py); sizeable differences that are not a constant run
are reported as unexplained and never recorded as a split. Volume never enters the decision.

This module only reads D1 and decides. The fetcher (ibkr_history_fetcher.py) records, re-fetches
and re-derives in its own run (plan 189-10, todo 507); ops_split_detect.py does it by hand.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np

from src.intelligence.bars.corporate_actions import infer_split
from src.intelligence.bars.seams import find_seams


@dataclass(frozen=True)
class DetectedSplit:
    """A split inferred from the overlap, or a difference it cannot explain.

    factor is the stored/fresh ratio snapped to a rational for a split (2.0 = 2-for-1,
    0.125 = 1-for-8) and the median ratio of the differing days when unexplained.
    effective_date is the last day on the old scale. request_ids are the new and the
    earlier observations' requests behind the decision.
    """

    symbol: str
    effective_date: date
    factor: float
    request_ids: tuple[str, ...]
    unexplained: bool


# Each overlapping date of this run's SMART TRADES answers, paired with the latest earlier
# SMART TRADES observation of that date from another run. Test callers never count (D1 is
# append-only, so their rows stay; bar_derivation excludes them the same way).
_OVERLAP_PAIRS_SQL = """
WITH new AS (
    SELECT o.symbol, o.bar_date, o.close, o.request_id::text AS request_id, q.answered_at
    FROM ohlcv_observation o
    JOIN ohlcv_request q ON q.request_id = o.request_id
    WHERE q.fetch_run_id = $1::uuid AND q.route = 'SMART' AND q.what_to_show = 'TRADES'
      AND q.outcome = 'bars' AND q.timeframe = '1d' AND q.caller NOT LIKE 'test-%'
), prev AS (
    SELECT DISTINCT ON (n.symbol, n.bar_date)
           n.symbol, n.bar_date, o.close AS prev_close, o.request_id::text AS request_id
    FROM new n
    JOIN ohlcv_observation o
      ON o.symbol = n.symbol AND o.bar_date = n.bar_date AND o.what_to_show = 'TRADES'
    JOIN ohlcv_request q ON q.request_id = o.request_id
    WHERE q.route = 'SMART' AND q.fetch_run_id <> $1::uuid AND q.answered_at < n.answered_at
      AND q.caller NOT LIKE 'test-%'
    ORDER BY n.symbol, n.bar_date, o.fetched_at DESC
)
SELECT n.symbol, n.bar_date, p.prev_close, n.close AS new_close,
       n.request_id AS new_request_id, p.request_id AS prev_request_id, n.answered_at
FROM new n JOIN prev p ON p.symbol = n.symbol AND p.bar_date = n.bar_date
ORDER BY n.symbol, n.bar_date
"""


def _evidence(rows: list[Any]) -> tuple[str, ...]:
    ids = {r["new_request_id"] for r in rows} | {r["prev_request_id"] for r in rows}
    return tuple(sorted(ids))


def _judge_symbol(
    symbol: str,
    rows: list[Any],
    *,
    rel_tol: float,
    min_run: int,
    ratio_snap_tol: float,
) -> list[DetectedSplit]:
    days = [r["bar_date"] for r in rows]
    prev = np.array([r["prev_close"] for r in rows], dtype=float)
    new = np.array([r["new_close"] for r in rows], dtype=float)
    try:
        seams = find_seams(days, prev, new, rel_tol=rel_tol, min_run=min_run)
    except ValueError as error:
        raise ValueError(f"{symbol}: overlap pairs are unusable: {error}") from error

    found: list[DetectedSplit] = []
    explained: set[date] = set()
    for seam in seams:
        in_seam = [r for r in rows if seam.start <= r["bar_date"] <= seam.end]
        explained.update(r["bar_date"] for r in in_seam)
        inference = infer_split(seam, ratio_snap_tol=ratio_snap_tol)
        if inference is not None:
            found.append(
                DetectedSplit(
                    symbol, inference.effective_date, inference.factor, _evidence(in_seam), False
                )
            )
        else:
            found.append(DetectedSplit(symbol, seam.end, seam.factor, _evidence(in_seam), True))

    residual = [
        (r, p / n)
        for r, p, n in zip(rows, prev, new, strict=True)
        if r["bar_date"] not in explained and abs(p / n - 1.0) > rel_tol
    ]
    if len(residual) >= min_run:
        residual_rows = [r for r, _ratio in residual]
        found.append(
            DetectedSplit(
                symbol,
                max(r["bar_date"] for r in residual_rows),
                float(np.median([ratio for _r, ratio in residual])),
                _evidence(residual_rows),
                True,
            )
        )
    return found


async def overlap_pairs(conn: Any, fetch_run_id: str) -> dict[str, list[Any]]:
    """`fetch_run_id`'s overlap pairs per symbol: each fresh SMART TRADES close of a completed
    session with the most recent earlier observation of that date. The session of the
    answer's own UTC date is left out because it may still be forming."""
    rows = await conn.fetch(_OVERLAP_PAIRS_SQL, fetch_run_id)
    by_symbol: dict[str, list[Any]] = defaultdict(list)
    for row in rows:
        if row["bar_date"] < row["answered_at"].date():
            by_symbol[row["symbol"]].append(row)
    return dict(by_symbol)


def judge_overlap_pairs(
    by_symbol: dict[str, list[Any]],
    *,
    rel_tol: float,
    min_run: int,
    ratio_snap_tol: float,
) -> list[DetectedSplit]:
    """Splits and unexplained differences in overlap pairs (overlap_pairs). A symbol with
    fewer than `min_run` overlapping complete sessions cannot be judged and yields nothing."""
    detected: list[DetectedSplit] = []
    for symbol in sorted(by_symbol):
        pairs = by_symbol[symbol]
        if len(pairs) < min_run:
            continue
        detected.extend(
            _judge_symbol(
                symbol, pairs, rel_tol=rel_tol, min_run=min_run, ratio_snap_tol=ratio_snap_tol
            )
        )
    return detected


async def detect_overlap_splits(
    conn: Any,
    *,
    fetch_run_id: str,
    rel_tol: float,
    min_run: int,
    ratio_snap_tol: float,
) -> list[DetectedSplit]:
    """Splits and unexplained differences in `fetch_run_id`'s overlap with earlier fetches.

    Pairs each date's new close with the most recent earlier observation of it and judges the
    stored/fresh ratio per symbol (overlap_pairs, then judge_overlap_pairs). Thresholds come
    from APR threshold.seam.*.
    """
    return judge_overlap_pairs(
        await overlap_pairs(conn, fetch_run_id),
        rel_tol=rel_tol,
        min_run=min_run,
        ratio_snap_tol=ratio_snap_tol,
    )
