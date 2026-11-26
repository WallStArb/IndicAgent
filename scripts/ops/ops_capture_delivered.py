"""ops_capture_delivered.py - has the nightly capture delivered the last completed session's 1d bars?

A member verdict taken between a session's close and the next capture (the Alpaca nightly 04:40Z,
the derivations 05:20Z and 05:45Z) judges that session as missing for every name: a name under
1,000 sessions then fails session_coverage and loses its proven start, and the pin gate refuses
it (pilot run 0e020c5a, 2026-11-25; todo 675). The launchers call this before they rely on fresh
verdicts. Read-only.

    .venv/bin/python scripts/ops/ops_capture_delivered.py     # exit 0 delivered, 1 not yet
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import psycopg

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

from src.config.settings import Settings  # noqa: E402
from src.intelligence.bars.sessions import nyse_sessions  # noqa: E402

# A delivered session carries at least this share of the names the session before it carried; the
# day-to-day change in names (listings, delistings) is far below the remaining 10%, a capture still
# running is not. An operator guard, not a statistic.
_DELIVERED_SHARE = 0.9
_LOOKBACK_DAYS = 12  # calendar days: enough for the last two completed sessions across a holiday


def undelivered_session(now: datetime, names_by_session: Mapping[date, int]) -> date | None:
    """The last completed NYSE session at `now` when its 1d bars are missing or partial, else None.

    Partial means fewer names than `_DELIVERED_SHARE` of the session before it. With no earlier
    session to compare, any bar counts as delivered."""
    sessions = nyse_sessions(now.date() - timedelta(days=_LOOKBACK_DAYS), now.date())
    completed = sorted(d for d, (_, close) in sessions.items() if close <= now)
    if not completed:
        return None
    last = completed[-1]
    have = names_by_session.get(last, 0)
    if have == 0:
        return last
    before = names_by_session.get(completed[-2], 0) if len(completed) > 1 else 0
    return last if before and have < _DELIVERED_SHARE * before else None


def _names_by_session(dsn: str, since: date) -> dict[date, int]:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT timestamp::date, count(DISTINCT symbol) FROM market_data_ohlcv_tradeable "
            "WHERE timeframe = '1d' AND timestamp >= %s GROUP BY 1",
            (since,),
        )
        return {day: int(n) for day, n in cur.fetchall()}


def main() -> int:
    now = datetime.now(UTC)
    dsn = Settings().database_url.replace("postgresql+asyncpg://", "postgresql://")
    counts = _names_by_session(dsn, now.date() - timedelta(days=_LOOKBACK_DAYS))
    missing = undelivered_session(now, counts)
    if missing is None:
        print("capture delivered: the last completed session has its 1d bars")
        return 0
    print(
        f"wait for the nightly capture: the 1d bars of {missing} are missing or partial "
        f"({counts.get(missing, 0)} names)"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
