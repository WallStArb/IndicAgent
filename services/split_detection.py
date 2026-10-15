"""Split inference from overlapping 1d answers (phase 185 plan 22, D-21; over raw since 191-10).

The fetcher's update lane re-asks the last infra.backfill.update_overlap_sessions_1d sessions,
so every fresh SMART TRADES observation overlaps an earlier one in D1. IBKR re-scales history
when a split happens: the earlier observation of a date stays on the old scale while the fresh
fetch is on the new one, so the stored/fresh close ratio is the split factor over the whole
overlap
(src/intelligence/bars/seams.py). A constant run is inferred as a split
(src/intelligence/bars/corporate_actions.py) only when its measured factor is a recognised split
ratio (recognised_split_ratio, APR infra.backfill.split_ratio_*; plan 185-51, todo 515); a
constant run that is no split ratio (CTVA's 39/7 spin-off rescale) is an unclassified rescale,
which the caller holds and never records as a split. Sizeable differences that are not a
constant run are reported as unexplained. Volume never enters the decision.

This module only reads ohlcv_raw, ohlcv_revision and ohlcv_request and decides. The fetcher (ohlcv_history_fetcher.py) records, re-fetches
and re-derives in its own run (plan 189-10, todo 507); ops_split_detect.py does it by hand.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import numpy as np

from src.intelligence.bars.corporate_actions import (
    SplitRatioRule,
    infer_split,
    recognised_split_ratio,
)
from src.intelligence.bars.seams import find_seams


@dataclass(frozen=True)
class DetectedSplit:
    """A split inferred from the overlap, a rescale that is no split, or a difference it
    cannot explain.

    factor is the recognised split ratio for a split (2.0 = 2-for-1, 0.125 = 1-for-8), the
    measured median ratio of the run for an unclassified rescale, and the median ratio of the
    differing days when unexplained. effective_date is the last day on the old scale seen in the
    overlap, first_date the first. request_ids are the new-scale requests for a split (d2-v2
    counts them as current), and the new and the earlier requests otherwise.
    """

    symbol: str
    effective_date: date
    factor: float
    request_ids: tuple[str, ...]
    unexplained: bool
    first_date: date | None = None
    unclassified: bool = False


# Overlap pairs over raw (plan 191-10). Raw is last-wins by serve time (D-191-N), so a
# request's 1d SMART TRADES answers live in two places: the current ohlcv_raw row it wrote, and
# the ohlcv_revision rows holding values it served that a later serve displaced (a revision's
# request_id is the request that served old_*; origin superseded holds an offer older than
# raw). Answers are ordered by ohlcv_request.answered_at reached through request_id, never by
# ohlcv_load.loaded_at (the plan 04 reconstructed loads were all written at backfill time).
# Test callers never count.

# The run's 1d SMART TRADES requests and the dates each one asked (window bounds, UTC dates;
# a NULL window_start asked all history).
_RUN_REQUESTS_SQL = """
SELECT q.request_id::text AS request_id, q.symbol, q.answered_at,
       (q.window_start AT TIME ZONE 'UTC')::date AS lo,
       (q.window_end AT TIME ZONE 'UTC')::date AS hi
FROM ohlcv_request q
WHERE q.fetch_run_id = $1::uuid AND q.route = 'SMART' AND q.what_to_show = 'TRADES'
  AND q.outcome = 'bars' AND q.timeframe = '1d' AND q.caller NOT LIKE 'test-%'
"""

# Names where the run wrote a value over an earlier one: a revision row holds the run's own
# (later displaced) answer, or the current raw row at a revised key is the run's. A name the
# run left unchanged has ratio 1 on every date and nothing to judge; skipping it keeps a
# full-history run off a full scan of raw.
_CHANGED_SYMBOLS_SQL = """
WITH revised AS (
    SELECT v.symbol, v."timestamp", v.request_id
    FROM ohlcv_revision v
    WHERE v.timeframe = '1d' AND v.vendor = 'ibkr' AND v.kind = 'smart_trades'
      AND v.symbol = ANY($2::text[])
)
SELECT v.symbol FROM revised v WHERE v.request_id = ANY($1::uuid[])
UNION
SELECT v.symbol FROM revised v
JOIN ohlcv_raw r ON r.symbol = v.symbol AND r."timestamp" = v."timestamp"
 AND r.timeframe = '1d' AND r.vendor = 'ibkr' AND r.kind = 'smart_trades'
WHERE r.request_id = ANY($1::uuid[])
"""

# Every recorded 1d SMART TRADES answer of the names in [lo, hi): raw rows and displaced values.
_ANSWERS_SQL = """
WITH served AS (
    SELECT r.symbol, r."timestamp", r.close, r.request_id
    FROM ohlcv_raw r
    WHERE r.timeframe = '1d' AND r.vendor = 'ibkr' AND r.kind = 'smart_trades'
      AND r.symbol = ANY($1::text[]) AND r."timestamp" >= $2 AND r."timestamp" < $3
      AND r.request_id IS NOT NULL
    UNION ALL
    SELECT v.symbol, v."timestamp", v.old_close, v.request_id
    FROM ohlcv_revision v
    WHERE v.timeframe = '1d' AND v.vendor = 'ibkr' AND v.kind = 'smart_trades'
      AND v.symbol = ANY($1::text[]) AND v."timestamp" >= $2 AND v."timestamp" < $3
      AND v.request_id IS NOT NULL
)
SELECT sv.symbol, (sv."timestamp" AT TIME ZONE 'UTC')::date AS bar_date, sv.close,
       sv.request_id::text AS request_id, q.answered_at, q.fetch_run_id::text AS fetch_run_id
FROM served sv JOIN ohlcv_request q ON q.request_id = sv.request_id
WHERE q.caller NOT LIKE 'test-%'
"""


def _evidence(rows: list[Any]) -> tuple[str, ...]:
    ids = {r["new_request_id"] for r in rows} | {r["prev_request_id"] for r in rows}
    return tuple(sorted(ids))


def _new_scale_evidence(rows: list[Any]) -> tuple[str, ...]:
    """A split's evidence: the requests that answered on the new scale only. d2-v2 counts every
    evidence request of a split as current-scale (daily_rule._is_current), so an earlier,
    old-scale request named here would be served unflagged for every date it answered that no
    later fetch covers (plan 185-51: the 2026-10-08 ETHA row named the 20-year d1-bootstrap
    request)."""
    return tuple(sorted({r["new_request_id"] for r in rows}))


def _judge_symbol(
    symbol: str,
    rows: list[Any],
    *,
    rel_tol: float,
    min_run: int,
    ratio_snap_tol: float,
    split_rule: SplitRatioRule,
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
        evidence = _evidence(in_seam)
        inference = infer_split(seam, ratio_snap_tol=ratio_snap_tol)
        if inference is None:
            found.append(
                DetectedSplit(symbol, seam.end, seam.factor, evidence, True, first_date=seam.start)
            )
            continue
        # The measured factor, not the snap: 39/7 snaps to itself.
        ratio = recognised_split_ratio(seam.factor, split_rule)
        if ratio is None:
            found.append(
                DetectedSplit(
                    symbol,
                    seam.end,
                    seam.factor,
                    evidence,
                    False,
                    first_date=seam.start,
                    unclassified=True,
                )
            )
        else:
            found.append(
                DetectedSplit(
                    symbol,
                    inference.effective_date,
                    ratio,
                    _new_scale_evidence(in_seam),
                    False,
                    first_date=seam.start,
                )
            )

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
                first_date=min(r["bar_date"] for r in residual_rows),
            )
        )
    return found


def pair_answers(
    fetch_run_id: str, run_requests: list[Any], answers: list[Any]
) -> dict[str, list[dict[str, Any]]]:
    """Overlap pairs per symbol from the run's requests and the recorded answers (pure).

    For each date a run request asked (the latest-answered request covering it), the fresh
    close is the run's own recorded answer, or, when the run recorded none there, the earlier
    answer itself: a re-serve equal to the stored value writes nothing (D-191-N), so the date
    is an unchanged pair. That keeps the seam runs and the overlap verdict's median on the same
    overlap the observation store gave. The earlier answer is the latest from another run
    answered before the fresh one, of a complete session (answered after the bar's UTC date):
    a forming value completing is no restatement (191-04/05 review). The fresh side leaves out
    the session of its own answer date, which may still be forming.
    """
    reqs: dict[str, list[Any]] = defaultdict(list)
    run_ids = set()
    for r in run_requests:
        reqs[r["symbol"]].append(r)
        run_ids.add(r["request_id"])
    own: dict[tuple[str, date], Any] = {}
    earlier: dict[tuple[str, date], list[Any]] = defaultdict(list)
    for a in answers:
        key = (a["symbol"], a["bar_date"])
        if a["request_id"] in run_ids:
            if key not in own or a["answered_at"] > own[key]["answered_at"]:
                own[key] = a
        elif a["fetch_run_id"] != fetch_run_id and a["bar_date"] < a["answered_at"].date():
            earlier[key].append(a)
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for key in sorted(set(own) | set(earlier)):
        symbol, bar_date = key
        covering = [
            r
            for r in reqs.get(symbol, ())
            if (r["lo"] is None or bar_date >= r["lo"]) and bar_date <= r["hi"]
        ]
        if not covering:
            continue
        mine = own.get(key)
        request = max(covering, key=lambda r: r["answered_at"])
        new_id = mine["request_id"] if mine else request["request_id"]
        answered_at = mine["answered_at"] if mine else request["answered_at"]
        if bar_date >= answered_at.date():
            continue
        prior = [e for e in earlier.get(key, ()) if e["answered_at"] < answered_at]
        if not prior:
            continue
        prev = max(prior, key=lambda e: e["answered_at"])
        by_symbol[symbol].append(
            {
                "symbol": symbol,
                "bar_date": bar_date,
                "prev_close": prev["close"],
                "new_close": mine["close"] if mine else prev["close"],
                "new_request_id": new_id,
                "prev_request_id": prev["request_id"],
                "answered_at": answered_at,
            }
        )
    return dict(by_symbol)


async def overlap_pairs(conn: Any, fetch_run_id: str) -> dict[str, list[Any]]:
    """`fetch_run_id`'s overlap pairs per symbol over ohlcv_raw and ohlcv_revision
    (pair_answers), for the names where the run changed a stored value."""
    run_requests = await conn.fetch(_RUN_REQUESTS_SQL, fetch_run_id)
    if not run_requests:
        return {}
    ids = sorted({r["request_id"] for r in run_requests})
    names = sorted({r["symbol"] for r in run_requests})
    changed = {r["symbol"] for r in await conn.fetch(_CHANGED_SYMBOLS_SQL, ids, names)}
    run_requests = [r for r in run_requests if r["symbol"] in changed]
    if not run_requests:
        return {}
    unbounded = any(r["lo"] is None for r in run_requests)
    lo = date.min if unbounded else min(r["lo"] for r in run_requests)
    hi = max(r["hi"] for r in run_requests) + timedelta(days=1)
    answers = await conn.fetch(
        _ANSWERS_SQL,
        sorted(changed),
        datetime.combine(lo, time(), tzinfo=UTC),
        datetime.combine(hi, time(), tzinfo=UTC),
    )
    return pair_answers(fetch_run_id, run_requests, answers)


def judge_overlap_pairs(
    by_symbol: dict[str, list[Any]],
    *,
    rel_tol: float,
    min_run: int,
    ratio_snap_tol: float,
    split_rule: SplitRatioRule,
) -> list[DetectedSplit]:
    """Splits, unclassified rescales and unexplained differences in overlap pairs
    (overlap_pairs). A symbol with fewer than `min_run` overlapping complete sessions cannot be
    judged and yields nothing."""
    detected: list[DetectedSplit] = []
    for symbol in sorted(by_symbol):
        pairs = by_symbol[symbol]
        if len(pairs) < min_run:
            continue
        detected.extend(
            _judge_symbol(
                symbol,
                pairs,
                rel_tol=rel_tol,
                min_run=min_run,
                ratio_snap_tol=ratio_snap_tol,
                split_rule=split_rule,
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
    split_rule: SplitRatioRule,
) -> list[DetectedSplit]:
    """Splits, unclassified rescales and unexplained differences in `fetch_run_id`'s overlap
    with earlier fetches.

    Pairs each date's new close with the most recent earlier observation of it and judges the
    stored/fresh ratio per symbol (overlap_pairs, then judge_overlap_pairs). Thresholds come
    from APR threshold.seam.* and infra.backfill.split_ratio_*.
    """
    return judge_overlap_pairs(
        await overlap_pairs(conn, fetch_run_id),
        rel_tol=rel_tol,
        min_run=min_run,
        ratio_snap_tol=ratio_snap_tol,
        split_rule=split_rule,
    )
