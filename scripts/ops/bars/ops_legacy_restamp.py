"""Re-stamp the d1 legacy import with the earliest time its corpus can have been answered
(review of 191-10, finding 1; the code fix for new imports is e9e96b2f9).

The 2026-09-30 legacy import (ops_d1_bootstrap legacy-import, caller d1-bootstrap, route
LEGACY_IMPORT, one request per name) was stamped with the import clock. Raw is last-wins by
serve time, so the stamp must be the earliest time the corpus can have been answered: the UTC
midnight after the request's last bar (window_end). Only LEGACY_IMPORT requests move; the same
run's SMART TRADES and ADJUSTED_LAST requests are real IBKR answers and keep their times.

One transaction: request requested_at/answered_at and the raw served_at of every current row
those requests wrote. Before writing it proves the change is stamp-only: no key whose current
value is a legacy one has a displaced answer (ohlcv_revision, not a superseded offer) with a
different close answered after the new stamp, i.e. last-wins by the corrected time picks the
same values. If any key would flip, it refuses (exit 3) and lists them: re-resolving values is a
separate, logged writer step. Idempotent: a re-run finds nothing to move. Dry run by default;
--apply writes; the plan and the result go to logs/legacy_restamp_<UTC stamp>.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from src.config.settings import get_settings

_SCOPE = """
CREATE TEMP TABLE legacy_restamp ON COMMIT DROP AS
SELECT request_id, symbol, answered_at AS old_stamp,
       ((window_end AT TIME ZONE 'UTC')::date + 1)::timestamp AT TIME ZONE 'UTC' AS new_stamp
FROM ohlcv_request
WHERE caller = 'd1-bootstrap' AND route = 'LEGACY_IMPORT' AND outcome = 'legacy_import'
  AND timeframe = '1d'
"""
_FLIPS = """
SELECT r.symbol, r."timestamp", r.kind, r.close, v.old_close, q.answered_at
FROM ohlcv_raw r
JOIN legacy_restamp s ON s.request_id = r.request_id
JOIN ohlcv_revision v ON v.symbol = r.symbol AND v.timeframe = r.timeframe
 AND v."timestamp" = r."timestamp" AND v.vendor = r.vendor AND v.kind = r.kind
 AND v.origin <> 'superseded'
JOIN ohlcv_request q ON q.request_id = v.request_id
WHERE r.timeframe = '1d' AND q.answered_at > s.new_stamp AND v.old_close <> r.close
ORDER BY r.symbol, r."timestamp"
"""
_COUNTS = """
SELECT
  (SELECT count(*) FROM legacy_restamp WHERE old_stamp <> new_stamp) AS requests,
  (SELECT count(*) FROM ohlcv_raw r JOIN legacy_restamp s ON s.request_id = r.request_id
    WHERE r.timeframe = '1d' AND r.served_at IS DISTINCT FROM s.new_stamp) AS raw_rows,
  (SELECT min(new_stamp) FROM legacy_restamp) AS min_stamp,
  (SELECT max(new_stamp) FROM legacy_restamp) AS max_stamp
"""
_UPDATE_REQUESTS = """
UPDATE ohlcv_request q SET requested_at = s.new_stamp, answered_at = s.new_stamp
FROM legacy_restamp s
WHERE q.request_id = s.request_id AND q.answered_at <> s.new_stamp
"""
_UPDATE_RAW = """
UPDATE ohlcv_raw r SET served_at = s.new_stamp
FROM legacy_restamp s
WHERE r.request_id = s.request_id AND r.timeframe = '1d'
  AND r.served_at IS DISTINCT FROM s.new_stamp
"""
FLIP_EXIT = 3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = parser.parse_args()
    started = datetime.now(UTC)
    report: dict = {"started_at": started.isoformat(), "apply": args.apply}
    with psycopg.connect(get_settings().database_url) as conn, conn.cursor() as cur:
        cur.execute("SET LOCAL lock_timeout = '30s'")
        cur.execute(_SCOPE)
        cur.execute(_COUNTS)
        requests, raw_rows, lo, hi = cur.fetchone()
        report.update(
            requests_to_move=requests,
            raw_rows_to_move=raw_rows,
            new_stamp_range=[str(lo), str(hi)],
        )
        cur.execute(_FLIPS)
        flips = [[str(x) for x in row] for row in cur.fetchall()]
        report["keys_that_would_flip"] = flips
        if flips:
            conn.rollback()
            print(json.dumps(report, indent=1))
            print(f"refused: {len(flips)} key(s) would change value; not a stamp-only change")
            _write(report, started)
            return FLIP_EXIT
        if args.apply:
            cur.execute(_UPDATE_REQUESTS)
            report["requests_moved"] = cur.rowcount
            cur.execute(_UPDATE_RAW)
            report["raw_rows_moved"] = cur.rowcount
            if (report["requests_moved"], report["raw_rows_moved"]) != (requests, raw_rows):
                conn.rollback()
                raise RuntimeError(f"moved counts differ from the plan: {report}")
            conn.commit()
        else:
            conn.rollback()
    _write(report, started)
    print(json.dumps(report, indent=1))
    return 0


def _write(report: dict, started: datetime) -> None:
    path = Path("logs") / f"legacy_restamp_{started.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report, indent=1) + "\n")


if __name__ == "__main__":
    sys.exit(main())
