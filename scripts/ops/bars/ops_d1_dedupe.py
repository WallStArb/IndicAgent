"""ops_d1_dedupe.py - remove repeated identical Tradier observations from D1 (ohlcv_observation).

D1 is mutable (owner decision 2026-10-03, migration 438). Before plan 185-27 the nightly Tradier
refetch landed every bar of every name each night, so a bar that never changed has one observation
per night. A row is a victim when its values (open, high, low, close, volume) equal the row
immediately before it for the same (symbol, bar_date, route, what_to_show), ordered by fetched_at.
Consecutive duplicates only: a value that changes and later changes back keeps its history, and the
latest observation per key (what D2 reads) keeps its values. Observations a canonical_bar_lineage
row may reference (same symbol, bar date within one day of the lineage timestamp) are never
victims. The request rows stay.

Dry run by default: counts the victims and records a digest of the latest observation per key for
every source. --apply deletes in batches, then re-computes the digest and exits 3 if any latest
value changed (the deleted rows cannot be restored, so the check is on the keeper set first: the
digest is also taken over the keeper rows before the first delete). Plain VACUUM follows; the
space is reused by new D1 rows, and returning it to the OS needs VACUUM FULL, an exclusive lock
the live backfill lane's D1 capture would wait on.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(project_root))

import psycopg  # noqa: E402

from src.config.settings import Settings  # noqa: E402

_BATCH_ROWS = 500_000  # [conventional] delete batch; D1 has no compressed chunks

_PROTECTED_SQL = """
CREATE TEMP TABLE d1_protected AS
SELECT DISTINCT l.symbol, r.request_id,
       (l.timestamp AT TIME ZONE 'UTC')::date + d.offset_days AS bar_date
FROM canonical_bar_lineage l
CROSS JOIN LATERAL unnest(l.request_ids) AS r(request_id)
CROSS JOIN (VALUES (-1), (0), (1)) AS d(offset_days)
"""

_VICTIMS_SQL = """
CREATE TEMP TABLE d1_victims AS
WITH ordered AS (
    SELECT request_id, symbol, bar_date, open, high, low, close, volume,
           lag(open) OVER w AS p_open, lag(high) OVER w AS p_high, lag(low) OVER w AS p_low,
           lag(close) OVER w AS p_close, lag(volume) OVER w AS p_volume,
           lag(request_id) OVER w AS p_request
    FROM ohlcv_observation
    WHERE source = 'tradier'
    WINDOW w AS (PARTITION BY symbol, bar_date, route, what_to_show ORDER BY fetched_at, request_id)
)
SELECT o.request_id, o.bar_date, row_number() OVER () AS rn
FROM ordered o
LEFT JOIN d1_protected p ON p.symbol = o.symbol AND p.request_id = o.request_id AND p.bar_date = o.bar_date
WHERE o.p_request IS NOT NULL AND p.request_id IS NULL
  AND o.open = o.p_open AND o.high = o.p_high AND o.low = o.p_low AND o.close = o.p_close
  AND o.volume IS NOT DISTINCT FROM o.p_volume
"""

_LATEST_DIGEST_SQL = """
SELECT source, count(*), md5(string_agg(
    symbol || '|' || bar_date || '|' || route || '|' || what_to_show || '|' ||
    open || '|' || high || '|' || low || '|' || close || '|' || coalesce(volume::text, ''),
    ',' ORDER BY symbol, bar_date, route, what_to_show))
FROM (SELECT DISTINCT ON (symbol, bar_date, route, what_to_show, source)
             source, symbol, bar_date, route, what_to_show, open, high, low, close, volume
      FROM ohlcv_observation
      ORDER BY symbol, bar_date, route, what_to_show, source, fetched_at DESC, request_id DESC) latest
GROUP BY source ORDER BY source
"""


def _digest(conn: psycopg.Connection) -> dict[str, tuple[int, str]]:
    return {row[0]: (row[1], row[2]) for row in conn.execute(_LATEST_DIGEST_SQL).fetchall()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply", action="store_true", help="delete the victims (default: dry run)"
    )
    args = parser.parse_args()
    settings = Settings()
    with psycopg.connect(settings.database_url, autocommit=True) as conn:
        before = _digest(conn)
        conn.execute(_PROTECTED_SQL)
        conn.execute("ANALYZE d1_protected")
        conn.execute(_VICTIMS_SQL)
        total = conn.execute("SELECT count(*) FROM d1_victims").fetchone()[0]
        rows = conn.execute(
            "SELECT count(*) FROM ohlcv_observation WHERE source = 'tradier'"
        ).fetchone()[0]
        print(
            f"tradier observations {rows:,}; consecutive duplicates {total:,}; keep {rows - total:,}"
        )
        print(f"latest-per-key digest before: {before}")
        if not args.apply:
            print("dry run: nothing deleted (use --apply)")
            return 0
        conn.execute("CREATE INDEX ON d1_victims (rn)")
        deleted = 0
        for lo in range(1, total + 1, _BATCH_ROWS):
            hi = lo + _BATCH_ROWS
            cur = conn.execute(
                "DELETE FROM ohlcv_observation o USING d1_victims v "
                "WHERE v.rn >= %s AND v.rn < %s AND o.request_id = v.request_id AND o.bar_date = v.bar_date "
                "AND o.source = 'tradier'",
                (lo, hi),
            )
            deleted += cur.rowcount
            print(f"deleted {deleted:,} / {total:,}", flush=True)
        after = _digest(conn)
        print(f"latest-per-key digest after:  {after}")
        conn.execute("VACUUM (ANALYZE) ohlcv_observation")
        if after != before:
            print("FAIL: the latest observation per key changed")
            return 3
        print("ok: latest observation per key unchanged for every source")
    return 0


if __name__ == "__main__":
    sys.exit(main())
