"""Hold the 5m names the nightly audit's slot_coverage verdict fails (todo 565 part a).

The 5m slot_coverage verdict counts a slot with no trade as missing for the Alpaca SIP years
(D-191-P: a SIP aggregate exists only where a trade printed), so thinly traded names fail the
0.995 worst-year threshold and the verdict gate (src/intelligence/bars/verdict_gate.py,
REQUIRED_CHECKS["5m"]) blocks the 186-26 intraday rebuild stage with no disposition recorded
anywhere. This script converts those verdicts into named holds: one bar_hold row per name,
reason slot_coverage_gap (migration 552), its evidence (the failing share, the threshold, the
verdict's evaluated_at) in detail. Canonical bars are untouched.

A name is judged on its latest verdict inside the audit's freshness window
(threshold.bar_integrity.report_max_age_hours): a failing latest verdict is held, a passing one
is not. Rerunnable: services/bar_hold.record_hold skips a name already held for the reason. It
never releases: a hold ends by decision (ops_split_detect.py --release-hold). It reads
integrity_monitor and writes bar_hold only; the audit's verdict path is untouched.

The verdict gate itself still fails these names until part b (it must learn that a held name
passes), which waits for the 186-26 rebuild to finish: verdict_gate.py sits inside the
rebuild's code-key import closure.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

import asyncpg

from services import bar_hold
from src.core.service_utils import format_iso_ts
from src.intelligence.bars.verdict_gate import MONITOR_TYPE, REPORT_MAX_AGE_APR_KEY

RECORDED_BY = "ops_hold_slot_coverage_gaps"

# The latest slot_coverage verdict per subject inside the freshness window; at one instant a
# failing row beats a passing one (the same order verdict_gate's LATEST_VERDICTS_SQL uses).
_LATEST_SLOT_COVERAGE_SQL = f"""
SELECT DISTINCT ON (subject) subject, metric_value, threshold_value, evaluated_at, passed
FROM integrity_monitor
WHERE monitor_type = '{MONITOR_TYPE}' AND metric_name = 'slot_coverage'
  AND subject IS NOT NULL
  AND evaluated_at >= now() - make_interval(hours => $1)
ORDER BY subject, evaluated_at DESC, passed ASC
"""

_APR_VALUE_SQL = "SELECT config_value FROM config_state WHERE config_key = $1"


def hold_requests(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Failing latest verdicts to hold requests, one per 5m name. slot_coverage is a 5m check
    today, so a subject on any other timeframe, or whose latest verdict passes, is skipped."""
    out: list[dict[str, Any]] = []
    for row in rows:
        symbol, _, timeframe = row["subject"].rpartition("|")
        if not symbol or timeframe != "5m" or row["passed"]:
            continue
        out.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "detail": {
                    "metric_value": float(row["metric_value"]),
                    "threshold_value": (
                        None if row["threshold_value"] is None else float(row["threshold_value"])
                    ),
                    "evaluated_at": format_iso_ts(row["evaluated_at"]),
                },
            }
        )
    return sorted(out, key=lambda request: request["symbol"])


async def _report_max_age_hours(conn: Any) -> float:
    row = await conn.fetchrow(_APR_VALUE_SQL, REPORT_MAX_AGE_APR_KEY)
    if row is None:
        raise RuntimeError(f"APR key {REPORT_MAX_AGE_APR_KEY} is not set")
    return float(row[0])


async def _held_5m_symbols(conn: Any) -> set[str]:
    rows = await conn.fetch(
        "SELECT symbol FROM bar_hold_current WHERE timeframe = '5m' AND reason = $1",
        bar_hold.REASON_SLOT_COVERAGE_GAP,
    )
    return {r["symbol"] for r in rows}


async def _main() -> int:
    from src.config.settings import Settings

    conn = await asyncpg.connect(Settings().database_url)
    try:
        hours = await _report_max_age_hours(conn)
        requests = hold_requests(
            [dict(r) for r in await conn.fetch(_LATEST_SLOT_COVERAGE_SQL, hours)]
        )
        held_before = await _held_5m_symbols(conn)
        print(f"report freshness window {hours:g}h; {len(requests)} failing latest verdicts")
        recorded = existing = 0
        for request in requests:
            hold_id = await bar_hold.record_hold(
                conn,
                reason=bar_hold.REASON_SLOT_COVERAGE_GAP,
                recorded_by=RECORDED_BY,
                **request,
            )
            if hold_id is None:
                existing += 1
            else:
                recorded += 1
                print(f"held {request['symbol']} ({request['detail']['metric_value']:.4f})")
        print(f"{recorded} new holds, {existing} already held")
        passing = sorted(held_before - {r["symbol"] for r in requests})
        if passing:
            print(f"held but passing now (release by decision): {' '.join(passing)}")
        return 0
    finally:
        await conn.close()


def main() -> int:
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    asyncio.run(_main())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
