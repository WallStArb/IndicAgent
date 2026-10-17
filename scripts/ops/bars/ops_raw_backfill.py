"""One-shot backfill of ohlcv_raw from the three old stores (phase 191 plan 03).

TEMPORARY: deleted at phase 191 close (plan 17), together with its APR key
`infra.raw_backfill.statement_timeout_s`.

Reads `ohlcv_intraday_raw_archive`, `ohlcv_observation` and the vendor-labelled rows of
`market_data_ohlcv`; writes `ohlcv_raw` only. It never refetches and never writes the old stores,
so it runs while the fetcher timer runs. Pass order is archive, observation, canonical, all
`INSERT ... ON CONFLICT (timestamp, symbol, timeframe, vendor, kind) DO NOTHING`: the stores that
know the true arrival time (archive `archived_at`, observation `fetched_at` and `request_id`) win a
duplicate key over canonical rows, which carry none. A rerun is idempotent. No id and no timestamp
is invented: `served_at`, `request_id` and `load_id` are NULL unless the source store holds them.

Modes: `--bulk` and `--delta` (the same windowed pass; a window is skipped when its three source
counts equal those recorded in the progress file when it was last loaded, so a kill resumes and a
delta reloads only windows the live writers have grown), `--check` (the balance report).
`--revisions` reconstructs ohlcv_revision from the observation history (plan 04, D-191-E); a value
run first served before its bar's session closed is a forming bar and is not logged (D-191-J).
`--prune-forming-revisions` rebuilds the reconstruction of symbols that hold such rows. `--bulk`,
`--delta`, `--revisions` and `--prune-forming-revisions` are dry runs unless `--apply`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import re
import shutil
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import psycopg
from psycopg import IsolationLevel

from services.ohlcv_raw_writer import CANONICAL_ONLY_KINDS
from src.config.config_service import ConfigService
from src.config.settings import get_settings
from src.intelligence.bars.sessions import nyse_sessions
from src.intelligence.bars.vendor_kind import (
    DERIVED_PAIR,
    LABEL_TO_VENDOR_KIND,
    VENDOR_DERIVED,
    VENDOR_KIND_TO_LABEL,
    observation_kind,
    pair_token,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOG_DIR = _REPO_ROOT / "logs"
_PROGRESS_FILE = _LOG_DIR / "raw_backfill_progress.jsonl"

_BATCH_ROWS_KEY = "infra.ohlcv_observation.copy_batch_rows"
_TIMEOUT_KEY = "infra.raw_backfill.statement_timeout_s"

_FIRST_YEAR = 1999  # earliest bar in any old store is 1999-01 (observation); empty windows are free
_TEST_CALLER = "test-%%"  # doubled: every statement runs with parameters
_EXCLUDED_DERIVED_LABEL = "derived_5m"
_EXCLUDED_SYNTHETIC_LABEL = "synthetic_fill"

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_]+$")

_RAW_COLS = (
    "timestamp, symbol, timeframe, vendor, kind, open, high, low, close, volume, "
    "served_at, request_id, load_id"
)
_CONFLICT = "ON CONFLICT (timestamp, symbol, timeframe, vendor, kind) DO NOTHING"
_VALUES5 = "(open, high, low, close, volume)"


# --------------------------------------------------------------------------------------
# SQL builders (pure; the label and observation mappings come from vendor_kind only)
# --------------------------------------------------------------------------------------


def _lit(token: str) -> str:
    """A SQL string literal for a code constant; refuses anything but a plain token."""
    if not _SAFE_TOKEN.match(token):
        raise ValueError(f"refusing to render {token!r} into SQL")
    return f"'{token}'"


def vendor_labels() -> dict[str, tuple[str, str]]:
    """Label to (vendor, kind) for every raw-eligible source label (derived rows are not raw)."""
    return {
        label: pair
        for label, pair in LABEL_TO_VENDOR_KIND.items()
        if pair[0] != VENDOR_DERIVED and pair[1] not in CANONICAL_ONLY_KINDS
    }


def build_raw_pairs_values_sql() -> str:
    """VALUES rows (vendor, kind) of every raw-eligible pair, for the canonical reads: the
    table carries the pair since the 191-14 swap, so raw eligibility is a pair membership
    test, never a join on a source label."""
    rows = [
        f"({_lit(vendor)}, {_lit(kind)})" for vendor, kind in sorted(set(vendor_labels().values()))
    ]
    return ",\n        ".join(rows)


def build_vendor_kind_values_sql() -> str:
    """VALUES rows (label, vendor, kind) rendered from the vendor_kind label map."""
    rows = [
        f"({_lit(label)}, {_lit(vendor)}, {_lit(kind)})"
        for label, (vendor, kind) in vendor_labels().items()
    ]
    return ",\n        ".join(rows)


def map_observation_triples(triples: list[tuple[str, str, str]]) -> list[tuple[str, str, str, str]]:
    """(source, route, what_to_show) to (..., kind) through observation_kind; vendor is source.

    observation_kind raises ValueError for an unmapped triple: the backfill stops there rather
    than guessing a kind.
    """
    return [(s, r, w, observation_kind(s, r, w)) for s, r, w in sorted(set(triples))]


def build_observation_values_sql(mapped: list[tuple[str, str, str, str]]) -> str:
    """VALUES rows (source, route, what_to_show, vendor, kind) for the observation join."""
    rows = [
        f"({_lit(source)}, {_lit(route)}, {_lit(wts)}, {_lit(source)}, {_lit(kind)})"
        for source, route, wts, kind in mapped
    ]
    if not rows:
        raise ValueError("no observation (source, route, what_to_show) triples to map")
    return ",\n        ".join(rows)


def archive_select_sql() -> str:
    """Archive rows of vendor labels; served_at is the true archived_at."""
    return f"""
    SELECT a.timestamp, a.symbol, a.timeframe, l.vendor, l.kind,
           a.open, a.high, a.low, a.close, a.volume,
           a.archived_at AS served_at, NULL::uuid AS request_id, NULL::uuid AS load_id
      FROM ohlcv_intraday_raw_archive a
      JOIN (VALUES
        {build_vendor_kind_values_sql()}
      ) AS l(label, vendor, kind) ON l.label = a.source
     WHERE a.symbol = %(symbol)s AND a.timestamp >= %(lo)s AND a.timestamp < %(hi)s"""


def canonical_select_sql() -> str:
    """Vendor-labelled canonical rows outside 1d; every provenance column NULL (none is known).

    1d canonical rows are daily-rule outputs derived from observations, not raw sources, so the
    whole 1d timeframe is excluded; the derived pair and every canonical-only kind fail the
    raw-pair membership test."""
    return f"""
    SELECT m.timestamp, m.symbol, m.timeframe, m.vendor, m.kind,
           m.open, m.high, m.low, m.close, m.volume,
           NULL::timestamptz AS served_at, NULL::uuid AS request_id, NULL::uuid AS load_id
      FROM market_data_ohlcv m
     WHERE m.symbol = %(symbol)s AND m.timestamp >= %(lo)s AND m.timestamp < %(hi)s
       AND m.timeframe <> '1d'
       AND (m.vendor, m.kind) IN (VALUES
         {build_raw_pairs_values_sql()}
       )"""


def _observation_rows_cte(obs_values_sql: str, *, windowed: bool = True) -> str:
    window = (
        "AND o.bar_date >= %(lo)s::date AND o.bar_date < %(hi)s::date\n           "
        if windowed
        else ""
    )
    return f"""
    obs AS (
        SELECT o.request_id, o.symbol, o.bar_date, m.vendor, m.kind,
               o.open, o.high, o.low, o.close, o.volume, o.fetched_at
          FROM ohlcv_observation o
          JOIN ohlcv_request r ON r.request_id = o.request_id
          JOIN (VALUES
            {obs_values_sql}
          ) AS m(source, route, what_to_show, vendor, kind)
            ON m.source = o.source AND m.route = o.route AND m.what_to_show = o.what_to_show
         WHERE o.symbol = %(symbol)s
           {window}AND r.caller NOT LIKE '{_TEST_CALLER}'
    )"""


def observation_current_cte(obs_values_sql: str) -> str:
    """CTE chain ending in `current_obs`: per (symbol, bar_date, vendor, kind) the latest value and
    the request that first served that value (the first row of the latest run of equal values).

    The latest run starts after the last differing value, so a value that changed and reverted is
    stamped with the revert, not the original serve."""
    return f"""
    {_observation_rows_cte(obs_values_sql)},
    flagged AS (
        SELECT obs.*,
               CASE WHEN ROW(open, high, low, close, volume) IS DISTINCT FROM ROW(
                        lag(open) OVER w, lag(high) OVER w, lag(low) OVER w,
                        lag(close) OVER w, lag(volume) OVER w)
                    THEN 1 ELSE 0 END AS chg
          FROM obs
        WINDOW w AS (PARTITION BY symbol, bar_date, vendor, kind ORDER BY fetched_at, request_id)
    ),
    runs AS (
        SELECT flagged.*,
               sum(chg) OVER (PARTITION BY symbol, bar_date, vendor, kind
                              ORDER BY fetched_at, request_id) AS run
          FROM flagged
    ),
    last_run AS (
        SELECT runs.*,
               run = max(run) OVER (PARTITION BY symbol, bar_date, vendor, kind) AS is_last
          FROM runs
    ),
    current_obs AS (
        SELECT DISTINCT ON (symbol, bar_date, vendor, kind)
               (bar_date::timestamp AT TIME ZONE 'UTC') AS timestamp,
               symbol, '1d'::text AS timeframe, vendor, kind,
               open, high, low, close, volume,
               fetched_at AS served_at, request_id, NULL::uuid AS load_id
          FROM last_run
         WHERE is_last
         ORDER BY symbol, bar_date, vendor, kind, fetched_at, request_id
    )"""


def observation_select_sql(obs_values_sql: str) -> str:
    """Observation rows as raw rows: current value, served_at and request_id of its first serve."""
    return (
        f"WITH {observation_current_cte(obs_values_sql)}\n    SELECT {_RAW_COLS} FROM current_obs"
    )


def insert_sql(select_sql: str) -> str:
    """INSERT ... SELECT ... ON CONFLICT DO NOTHING around one pass's select."""
    return f"INSERT INTO ohlcv_raw ({_RAW_COLS}) {select_sql} {_CONFLICT}"


def count_sql(select_sql: str) -> str:
    """Row count of a pass's select (dry run)."""
    return f"SELECT count(*) FROM ({select_sql}) AS s"


def split_range(lo: datetime, hi: datetime, parts: int) -> list[tuple[datetime, datetime]]:
    """Split [lo, hi) into `parts` day-aligned sub-ranges (an observation key never straddles)."""
    parts = max(1, parts)
    days = max(1, (hi - lo).days)
    parts = min(parts, days)
    edges = [lo + (hi - lo) * i // parts for i in range(parts)]
    edges = [e.replace(hour=0, minute=0, second=0, microsecond=0) for e in edges]
    edges = sorted(set(edges)) + [hi]
    return list(zip(edges[:-1], edges[1:], strict=True))


def window_bounds(year: int) -> tuple[datetime, datetime]:
    return datetime(year, 1, 1, tzinfo=UTC), datetime(year + 1, 1, 1, tzinfo=UTC)


# --------------------------------------------------------------------------------------
# Windowed load
# --------------------------------------------------------------------------------------


@dataclass
class WindowCounts:
    canonical: int
    archive: int
    observation: int

    def total(self) -> int:
        return self.canonical + self.archive + self.observation

    def as_dict(self) -> dict[str, int]:
        return {
            "canonical": self.canonical,
            "archive": self.archive,
            "observation": self.observation,
        }


def count_window(cur: psycopg.Cursor, obs_values_sql: str, symbol: str, lo, hi) -> WindowCounts:
    params = {"symbol": symbol, "lo": lo, "hi": hi}
    cur.execute(count_sql(canonical_select_sql()), params)
    canonical = cur.fetchone()[0]
    cur.execute(count_sql(archive_select_sql()), params)
    archive = cur.fetchone()[0]
    cur.execute(
        f"""WITH {_observation_rows_cte(obs_values_sql)} SELECT count(*) FROM obs""", params
    )
    observation = cur.fetchone()[0]
    return WindowCounts(canonical, archive, observation)


def load_progress(path: Path) -> dict[tuple[str, int], dict[str, int]]:
    """Last recorded source counts per (symbol, year) window."""
    done: dict[tuple[str, int], dict[str, int]] = {}
    if not path.exists():
        return done
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        done[(rec["symbol"], rec["year"])] = rec["counts"]
    return done


def window_is_current(
    done: dict[tuple[str, int], dict[str, int]], symbol: str, year: int, counts: WindowCounts
) -> bool:
    """True when the window was loaded and its three source counts have not changed since."""
    return done.get((symbol, year)) == counts.as_dict()


@dataclass
class RunTotals:
    windows_seen: int = 0
    windows_skipped: int = 0
    windows_loaded: int = 0
    inserted: dict[str, int] = field(
        default_factory=lambda: {"archive": 0, "observation": 0, "canonical": 0}
    )
    candidates: dict[str, int] = field(
        default_factory=lambda: {"archive": 0, "observation": 0, "canonical": 0}
    )


def check_disk(min_free_gb: float) -> None:
    free_gb = shutil.disk_usage("/").free / 1024**3
    if free_gb < min_free_gb:
        raise SystemExit(f"STOP: free disk {free_gb:.0f} GB below --min-free-gb {min_free_gb}")


def run_windows(
    conn: psycopg.Connection,
    *,
    symbols: list[str],
    years: range,
    obs_values_sql: str,
    batch_rows: int,
    apply: bool,
    min_free_gb: float,
    progress_path: Path,
    passes: frozenset[str] = frozenset({"archive", "observation", "canonical"}),
    force: bool = False,
) -> RunTotals:
    done = {} if force else load_progress(progress_path)
    totals = RunTotals()
    t0 = time.monotonic()
    for sym_i, symbol in enumerate(symbols):
        if apply:
            check_disk(min_free_gb)
        for year in years:
            lo, hi = window_bounds(year)
            totals.windows_seen += 1
            with conn.cursor() as cur:
                # counts and inserts share one snapshot so the recorded counts are what was read
                counts = count_window(cur, obs_values_sql, symbol, lo, hi)
                if counts.total() == 0:
                    conn.rollback()
                    continue
                if window_is_current(done, symbol, year, counts):
                    totals.windows_skipped += 1
                    conn.rollback()
                    continue
                parts = math.ceil(counts.total() / max(1, batch_rows))
                selects = (
                    ("archive", archive_select_sql()),
                    ("observation", observation_select_sql(obs_values_sql)),
                    ("canonical", canonical_select_sql()),
                )
                for name, select in selects:
                    if name not in passes:
                        continue
                    for sub_lo, sub_hi in split_range(lo, hi, parts):
                        params = {"symbol": symbol, "lo": sub_lo, "hi": sub_hi}
                        if apply:
                            cur.execute(insert_sql(select), params)
                            totals.inserted[name] += max(0, cur.rowcount)
                        else:
                            cur.execute(count_sql(select), params)
                            totals.candidates[name] += cur.fetchone()[0]
            if apply:
                conn.commit()
                if passes != frozenset({"archive", "observation", "canonical"}):
                    totals.windows_loaded += 1
                    continue
                with progress_path.open("a") as fh:
                    fh.write(
                        json.dumps(
                            {
                                "symbol": symbol,
                                "year": year,
                                "counts": counts.as_dict(),
                                "at": datetime.now(UTC).isoformat(),
                            }
                        )
                        + "\n"
                    )
                done[(symbol, year)] = counts.as_dict()
            else:
                conn.rollback()
            totals.windows_loaded += 1
        if (sym_i + 1) % 10 == 0 or sym_i + 1 == len(symbols):
            print(
                f"[{datetime.now(UTC):%H:%M:%S}] {sym_i + 1}/{len(symbols)} symbols "
                f"({symbol}) loaded={totals.windows_loaded} skipped={totals.windows_skipped} "
                f"inserted={totals.inserted} elapsed={time.monotonic() - t0:.0f}s",
                flush=True,
            )
    return totals


# --------------------------------------------------------------------------------------
# Revision reconstruction (D-191-E)
# --------------------------------------------------------------------------------------

_REVISION_CALLER = "raw-backfill-191"
_REVISION_DETAIL = "raw-backfill-191 revisions ordinal={ordinal}; bar_date {first} to {last}"
_REVISION_ORDINAL = re.compile(r"revisions ordinal=(\d+);")
_REVISION_BATCH = 1000


_SESSION_CLOSE_FIRST_YEAR = 1999


@lru_cache(maxsize=1)
def session_close_values_sql() -> str:
    """VALUES rows (bar_date, close instant) of every NYSE session through today (D-191-J)."""
    sessions = nyse_sessions(date(_SESSION_CLOSE_FIRST_YEAR, 1, 1), datetime.now(UTC).date())
    return ",\n            ".join(
        f"('{day.isoformat()}'::date, '{close.isoformat()}'::timestamptz)"
        for day, (_open, close) in sorted(sessions.items())
    )


def superseded_runs_cte(obs_values_sql: str) -> str:
    """CTE chain ending in `superseded`: one row per value run that a later run replaced.

    A run is a maximal sequence of equal OHLCV values of one (symbol, bar_date, vendor, kind) in
    arrival order (fetched_at, request_id). `run` counts from 1; the restatement that replaced
    run N is restatement ordinal N. request_id is the request that first served the run.

    A run first served before the bar's NYSE session closed is a forming bar, not a vendor
    restating its own history: it is never superseded evidence (D-191-J). Run numbers are kept,
    so the surviving rows keep their ordinals."""
    return f"""
    {_observation_rows_cte(obs_values_sql, windowed=False)},
    flagged AS (
        SELECT obs.*,
               CASE WHEN ROW(open, high, low, close, volume) IS DISTINCT FROM ROW(
                        lag(open) OVER w, lag(high) OVER w, lag(low) OVER w,
                        lag(close) OVER w, lag(volume) OVER w)
                    THEN 1 ELSE 0 END AS chg
          FROM obs
        WINDOW w AS (PARTITION BY symbol, bar_date, vendor, kind ORDER BY fetched_at, request_id)
    ),
    runs AS (
        SELECT flagged.*,
               sum(chg) OVER (PARTITION BY symbol, bar_date, vendor, kind
                              ORDER BY fetched_at, request_id) AS run
          FROM flagged
    ),
    grouped AS (
        SELECT symbol, bar_date, vendor, kind, run,
               min(fetched_at) AS first_fetched_at,
               (array_agg(request_id ORDER BY fetched_at, request_id))[1] AS request_id,
               (array_agg(open ORDER BY fetched_at, request_id))[1] AS open,
               (array_agg(high ORDER BY fetched_at, request_id))[1] AS high,
               (array_agg(low ORDER BY fetched_at, request_id))[1] AS low,
               (array_agg(close ORDER BY fetched_at, request_id))[1] AS close,
               (array_agg(volume ORDER BY fetched_at, request_id))[1] AS volume
          FROM runs
         GROUP BY symbol, bar_date, vendor, kind, run
    ),
    superseded AS (
        SELECT g.* FROM (
            SELECT grouped.*,
                   max(run) OVER (PARTITION BY symbol, bar_date, vendor, kind) AS last_run
              FROM grouped
        ) g
          LEFT JOIN (VALUES
            {session_close_values_sql()}
          ) AS sc(bar_date, close_at) ON sc.bar_date = g.bar_date
         WHERE g.run < g.last_run
           AND (sc.close_at IS NULL OR g.first_fetched_at >= sc.close_at)
    )"""


def superseded_runs_sql(obs_values_sql: str) -> str:
    return (
        f"WITH {superseded_runs_cte(obs_values_sql)}\n"
        "    SELECT bar_date, vendor, kind, run, request_id, open, high, low, close, volume\n"
        "      FROM superseded ORDER BY vendor, run, bar_date, kind"
    )


@dataclass
class RevisionLoadPlan:
    """One ohlcv_load row (symbol, vendor, restatement ordinal) and the revision rows under it."""

    symbol: str
    vendor: str
    ordinal: int
    rows: list[tuple] = field(default_factory=list)  # (bar_date, kind, request_id, o, h, l, c, v)

    @property
    def first_bar(self):
        return min(r[0] for r in self.rows)

    @property
    def last_bar(self):
        return max(r[0] for r in self.rows)

    @property
    def detail(self) -> str:
        return _REVISION_DETAIL.format(
            ordinal=self.ordinal, first=self.first_bar, last=self.last_bar
        )


def plan_revision_loads(symbol: str, runs: list[tuple]) -> list[RevisionLoadPlan]:
    """Group superseded runs (bar_date, vendor, kind, run, request_id, o, h, l, c, v) into one
    load per (vendor, ordinal), ordered by (vendor, ordinal)."""
    plans: dict[tuple[str, int], RevisionLoadPlan] = {}
    for bar_date, vendor, kind, run, request_id, o, h, low, c, v in runs:
        key = (vendor, int(run))
        plan = plans.setdefault(key, RevisionLoadPlan(symbol, vendor, int(run)))
        plan.rows.append((bar_date, kind, request_id, o, h, low, c, v))
    return [plans[k] for k in sorted(plans)]


def existing_revision_ordinals(cur: psycopg.Cursor, symbol: str) -> set[tuple[str, int]]:
    """(vendor, ordinal) of reconstruction loads already written for the symbol."""
    cur.execute(
        "SELECT source, detail FROM ohlcv_load "
        "WHERE caller = %s AND destination = 'raw' AND symbol = %s",
        (_REVISION_CALLER, symbol),
    )
    found: set[tuple[str, int]] = set()
    for source, detail in cur.fetchall():
        match = _REVISION_ORDINAL.search(detail or "")
        if match:
            found.add((source, int(match.group(1))))
    return found


def write_revision_loads(
    cur: psycopg.Cursor, plans: list[RevisionLoadPlan], done: set[tuple[str, int]]
) -> tuple[int, int]:
    """Insert each not-yet-written plan: its ohlcv_load row, then its ohlcv_revision rows.
    Returns (loads_written, revisions_written). The caller owns the transaction."""
    loads = revisions = 0
    for plan in plans:
        if (plan.vendor, plan.ordinal) in done:
            continue
        load_id = uuid.uuid4()
        n = len(plan.rows)
        cur.execute(
            "INSERT INTO ohlcv_load (load_id, symbol, timeframe, source, requested_start, "
            "requested_end, outcome, n_bars, n_new, n_changed, first_bar, last_bar, detail, "
            "caller, destination, n_unchanged, n_removed, n_archived) "
            "VALUES (%s, %s, '1d', %s, %s, %s, 'applied', %s, 0, %s, %s, %s, %s, %s, 'raw', "
            "0, 0, 0)",
            (
                load_id,
                plan.symbol,
                plan.vendor,
                plan.first_bar,
                plan.last_bar,
                n,
                n,
                plan.first_bar,
                plan.last_bar,
                plan.detail,
                _REVISION_CALLER,
            ),
        )
        loads += 1
        for start in range(0, n, _REVISION_BATCH):
            chunk = plan.rows[start : start + _REVISION_BATCH]
            values = ",".join(
                [
                    "(%s,%s,'1d',(%s::date::timestamp AT TIME ZONE 'UTC'),%s,%s,%s,%s,%s,%s,%s,%s,%s,'raw')"
                ]
                * len(chunk)
            )
            params: list[Any] = []
            for bar_date, kind, request_id, o, h, low, c, v in chunk:
                label = VENDOR_KIND_TO_LABEL.get((plan.vendor, kind), plan.vendor)
                params += [
                    load_id,
                    plan.symbol,
                    bar_date,
                    o,
                    h,
                    low,
                    c,
                    v,
                    label,
                    plan.vendor,
                    kind,
                    request_id,
                ]
            cur.execute(
                'INSERT INTO ohlcv_revision (load_id, symbol, timeframe, "timestamp", old_open, '
                "old_high, old_low, old_close, old_volume, old_source, vendor, kind, request_id, "
                "origin) VALUES " + values,
                params,
            )
            revisions += len(chunk)
    return loads, revisions


def forming_revision_symbols_sql() -> str:
    """Symbols holding a reconstruction revision whose run was first served before its session
    closed (D-191-J): the rows the old, unfiltered reconstruction wrote from forming bars."""
    return f"""
    SELECT DISTINCT r.symbol
      FROM ohlcv_revision r
      JOIN ohlcv_load l ON l.load_id = r.load_id
      JOIN ohlcv_observation o
        ON o.request_id = r.request_id AND o.symbol = r.symbol
       AND o.bar_date = (r."timestamp" AT TIME ZONE 'UTC')::date
      JOIN (VALUES
            {session_close_values_sql()}
      ) AS sc(bar_date, close_at) ON sc.bar_date = o.bar_date
     WHERE l.caller = '{_REVISION_CALLER}' AND l.detail LIKE '%%revisions ordinal=%%'
       AND r.origin = 'raw' AND r.timeframe = '1d'
       AND o.fetched_at < sc.close_at
     ORDER BY r.symbol"""


def rebuild_symbol_revisions(
    conn: psycopg.Connection, symbol: str, *, obs_values_sql: str
) -> tuple[int, int]:
    """One transaction: delete the symbol's reconstruction loads (their revisions cascade), then
    rewrite them from the filtered superseded runs. Returns (loads, revisions) written."""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM ohlcv_load WHERE caller = %s AND destination = 'raw' AND symbol = %s",
            (_REVISION_CALLER, symbol),
        )
        cur.execute(superseded_runs_sql(obs_values_sql), {"symbol": symbol})
        runs = cur.fetchall()
        loads, revisions = write_revision_loads(cur, plan_revision_loads(symbol, runs), set())
    conn.commit()
    return loads, revisions


def run_prune_forming_revisions(
    conn: psycopg.Connection, *, symbols: list[str], obs_values_sql: str, apply: bool
) -> dict[str, int]:
    """Rebuild reconstruction revisions for every symbol that holds forming-bar rows."""
    with conn.cursor() as cur:
        cur.execute(forming_revision_symbols_sql())
        affected = [r[0] for r in cur.fetchall()]
    conn.rollback()
    wanted = set(symbols)
    affected = [s for s in affected if s in wanted]
    totals = {"affected_symbols": len(affected), "loads": 0, "revisions": 0}
    if apply:
        for symbol in affected:
            loads, revisions = rebuild_symbol_revisions(conn, symbol, obs_values_sql=obs_values_sql)
            totals["loads"] += loads
            totals["revisions"] += revisions
    return totals


def revision_balance_sql(obs_values_sql: str) -> str:
    """Superseded runs, those with no matching revision row, and revision rows by this caller."""
    return f"""
    WITH {superseded_runs_cte(obs_values_sql)}
    SELECT (SELECT count(*) FROM superseded) AS runs,
           (SELECT count(*) FROM superseded s
             WHERE NOT EXISTS (
                SELECT 1 FROM ohlcv_revision r
                  JOIN ohlcv_load l ON l.load_id = r.load_id
                 WHERE l.caller = '{_REVISION_CALLER}' AND r.symbol = s.symbol
                   AND r.timeframe = '1d'
                   AND r."timestamp" = (s.bar_date::timestamp AT TIME ZONE 'UTC')
                   AND r.vendor = s.vendor AND r.kind = s.kind
                   AND r.request_id = s.request_id AND r.origin = 'raw'
                   AND ROW(r.old_open, r.old_high, r.old_low, r.old_close, r.old_volume)
                       IS NOT DISTINCT FROM ROW(s.open, s.high, s.low, s.close, s.volume))
           ) AS missing,
           (SELECT count(*) FROM ohlcv_revision r
              JOIN ohlcv_load l ON l.load_id = r.load_id
             WHERE l.caller = '{_REVISION_CALLER}' AND l.detail LIKE '%%revisions ordinal=%%'
               AND r.symbol = %(symbol)s) AS stored"""


def revision_unexplained(runs: int, missing: int, stored: int) -> int:
    """Superseded runs without a revision row, plus revision rows beyond the runs."""
    return missing + max(0, stored - (runs - missing))


def run_revisions(
    conn: psycopg.Connection, *, symbols: list[str], obs_values_sql: str, apply: bool
) -> dict[str, int]:
    totals = {"symbols_with_runs": 0, "runs": 0, "loads": 0, "revisions": 0}
    sql = superseded_runs_sql(obs_values_sql)
    for symbol in symbols:
        with conn.cursor() as cur:
            cur.execute(sql, {"symbol": symbol})
            runs = cur.fetchall()
            if not runs:
                conn.rollback()
                continue
            plans = plan_revision_loads(symbol, runs)
            totals["symbols_with_runs"] += 1
            totals["runs"] += len(runs)
            if apply:
                loads, revisions = write_revision_loads(
                    cur, plans, existing_revision_ordinals(cur, symbol)
                )
                totals["loads"] += loads
                totals["revisions"] += revisions
        conn.commit() if apply else conn.rollback()
    return totals


# --------------------------------------------------------------------------------------
# Reconcile: a later serve replaces raw (old value logged), canonical-only values are logged
# --------------------------------------------------------------------------------------

_RECONCILE_DETAIL = "raw-backfill-191 reconcile {pass_name}; {n} rows"
_VALUES_DIFFER = (
    "ROW(r.open, r.high, r.low, r.close, r.volume) "
    "IS DISTINCT FROM ROW(s.open, s.high, s.low, s.close, s.volume)"
)
_KEY_JOIN = (
    "r.timestamp = s.timestamp AND r.symbol = s.symbol AND r.timeframe = s.timeframe "
    "AND r.vendor = s.vendor AND r.kind = s.kind"
)
_OLD_COLS = (
    "r.timestamp, r.symbol, r.timeframe, r.vendor, r.kind, r.open, r.high, r.low, r.close, "
    "r.volume, r.request_id"
)
_SRC_COLS = (
    "s.timestamp, s.symbol, s.timeframe, s.vendor, s.kind, s.open, s.high, s.low, s.close, "
    "s.volume, NULL::uuid"
)
# a later serve replaces raw: the source holds a true serve time and raw has none or an earlier one
_LATER_SERVE = "s.served_at IS NOT NULL AND (r.served_at IS NULL OR s.served_at > r.served_at)"
_NO_LOGGED_TWIN = f"""NOT EXISTS (
    SELECT 1 FROM ohlcv_revision v JOIN ohlcv_load l ON l.load_id = v.load_id
     WHERE l.caller = '{_REVISION_CALLER}' AND v.symbol = s.symbol AND v.timeframe = s.timeframe
       AND v."timestamp" = s.timestamp AND v.vendor = s.vendor AND v.kind = s.kind
       AND ROW(v.old_open, v.old_high, v.old_low, v.old_close, v.old_volume)
           IS NOT DISTINCT FROM ROW(s.open, s.high, s.low, s.close, s.volume))"""


def reconcile_displaced_sql(src_cte: str) -> str:
    """Raw rows a later serve of the same store is about to replace (their old values)."""
    return f"""WITH {src_cte}
    SELECT {_OLD_COLS} FROM src s JOIN ohlcv_raw r ON {_KEY_JOIN}
     WHERE {_VALUES_DIFFER} AND {_LATER_SERVE}"""


def reconcile_update_sql(src_cte: str) -> str:
    return f"""WITH {src_cte}
    UPDATE ohlcv_raw r
       SET open = s.open, high = s.high, low = s.low, close = s.close, volume = s.volume,
           served_at = s.served_at, request_id = s.request_id
      FROM src s
     WHERE {_KEY_JOIN} AND {_VALUES_DIFFER} AND {_LATER_SERVE}"""


def canonical_disagreeing_select_sql() -> str:
    """Canonical vendor rows whose archive twin (same key, same label) holds other values: the
    only canonical values raw can lack, because raw keeps the archive's later serve."""
    return f"""
    SELECT m.timestamp, m.symbol, m.timeframe, l.vendor, l.kind,
           m.open, m.high, m.low, m.close, m.volume,
           NULL::timestamptz AS served_at, NULL::uuid AS request_id, NULL::uuid AS load_id
      FROM ohlcv_intraday_raw_archive a
      JOIN (VALUES
        {build_vendor_kind_values_sql()}
      ) AS l(label, vendor, kind) ON l.label = a.source
      JOIN market_data_ohlcv m
        ON m.timestamp = a.timestamp AND m.symbol = a.symbol AND m.timeframe = a.timeframe
       AND m.vendor = l.vendor AND m.kind = l.kind
     WHERE a.symbol = %(symbol)s AND a.timestamp >= %(lo)s AND a.timestamp < %(hi)s
       AND m.timeframe <> '1d'
       AND ROW(a.open, a.high, a.low, a.close, a.volume)
           IS DISTINCT FROM ROW(m.open, m.high, m.low, m.close, m.volume)"""


def reconcile_canonical_only_sql(src_cte: str) -> str:
    """Canonical values that raw does not hold (raw keeps the archive's later serve). The
    canonical value is logged as the superseded one, with its values and no request."""
    return f"""WITH {src_cte}
    SELECT {_SRC_COLS} FROM src s JOIN ohlcv_raw r ON {_KEY_JOIN}
     WHERE {_VALUES_DIFFER} AND {_NO_LOGGED_TWIN}"""


def write_reconcile_revisions(
    cur: psycopg.Cursor, symbol: str, pass_name: str, rows: list[tuple]
) -> int:
    """Log `rows` (timestamp, symbol, timeframe, vendor, kind, o, h, l, c, v, request_id) as
    origin raw revisions, one reconstruction load per (vendor, timeframe)."""
    by_load: dict[tuple[str, str], list[tuple]] = {}
    for row in rows:
        by_load.setdefault((row[3], row[2]), []).append(row)
    written = 0
    for (vendor, timeframe), group in sorted(by_load.items()):
        load_id = uuid.uuid4()
        first = min(r[0] for r in group).date()
        last = max(r[0] for r in group).date()
        cur.execute(
            "INSERT INTO ohlcv_load (load_id, symbol, timeframe, source, requested_start, "
            "requested_end, outcome, n_bars, n_new, n_changed, first_bar, last_bar, detail, "
            "caller, destination, n_unchanged, n_removed, n_archived) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'applied', %s, 0, %s, %s, %s, %s, %s, 'raw', 0, 0, 0)",
            (
                load_id,
                symbol,
                timeframe,
                vendor,
                first,
                last,
                len(group),
                len(group),
                first,
                last,
                _RECONCILE_DETAIL.format(pass_name=pass_name, n=len(group)),
                _REVISION_CALLER,
            ),
        )
        for start in range(0, len(group), _REVISION_BATCH):
            chunk = group[start : start + _REVISION_BATCH]
            values = ",".join(["(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'raw')"] * len(chunk))
            params: list[Any] = []
            for ts, sym, tf, vend, kind, o, h, low, c, v, request_id in chunk:
                label = VENDOR_KIND_TO_LABEL.get((vend, kind), vend)
                params += [load_id, sym, tf, ts, o, h, low, c, v, label, vend, kind, request_id]
            cur.execute(
                'INSERT INTO ohlcv_revision (load_id, symbol, timeframe, "timestamp", '
                "old_open, old_high, old_low, old_close, old_volume, old_source, vendor, kind, "
                "request_id, origin) VALUES " + values,
                params,
            )
            written += len(chunk)
    return written


def _store_has_rows(cur: psycopg.Cursor, sql: str, params: dict) -> bool:
    cur.execute(sql, params)
    return cur.fetchone() is not None


_ARCHIVE_ANY = (
    "SELECT 1 FROM ohlcv_intraday_raw_archive WHERE symbol = %(symbol)s "
    "AND timestamp >= %(lo)s AND timestamp < %(hi)s LIMIT 1"
)
_ARCHIVE_SINCE = (
    "SELECT 1 FROM ohlcv_intraday_raw_archive WHERE symbol = %(symbol)s "
    "AND timestamp >= %(lo)s AND timestamp < %(hi)s AND archived_at >= %(since)s LIMIT 1"
)
_OBSERVATION_SINCE = (
    "SELECT 1 FROM ohlcv_observation WHERE symbol = %(symbol)s "
    "AND bar_date >= %(lo)s::date AND bar_date < %(hi)s::date AND fetched_at >= %(since)s LIMIT 1"
)


def run_reconcile(
    conn: psycopg.Connection,
    *,
    symbols: list[str],
    years: range,
    obs_values_sql: str,
    apply: bool,
    since: datetime,
) -> dict[str, int]:
    """Per window: (1) a later archive or observation serve replaces the raw row, the displaced
    value logged; (2) a canonical value raw does not hold is logged as a superseded value."""
    totals = {"displaced_archive": 0, "displaced_observation": 0, "canonical_logged": 0}
    archive_src = f"src AS ({archive_select_sql()})"
    obs_src = f"{observation_current_cte(obs_values_sql)}, src AS (SELECT * FROM current_obs)"
    canonical_src = f"src AS ({canonical_disagreeing_select_sql()})"
    for symbol in symbols:
        for year in years:
            lo, hi = window_bounds(year)
            p = {"symbol": symbol, "lo": lo, "hi": hi, "since": since}
            with conn.cursor() as cur:
                # serves before `since` were read by the bulk at their final value; only a later
                # serve can displace a raw row, so only windows holding one are compared
                if _store_has_rows(cur, _ARCHIVE_SINCE, p):
                    cur.execute(reconcile_displaced_sql(archive_src), p)
                    old = cur.fetchall()
                    if old:
                        totals["displaced_archive"] += len(old)
                        if apply:
                            write_reconcile_revisions(cur, symbol, "archive", old)
                            cur.execute(reconcile_update_sql(archive_src), p)
                if _store_has_rows(cur, _ARCHIVE_ANY, p):
                    cur.execute(reconcile_canonical_only_sql(canonical_src), p)
                    logged = cur.fetchall()
                    if logged:
                        totals["canonical_logged"] += len(logged)
                        if apply:
                            write_reconcile_revisions(cur, symbol, "canonical", logged)
                if _store_has_rows(cur, _OBSERVATION_SINCE, p):
                    cur.execute(reconcile_displaced_sql(obs_src), p)
                    old = cur.fetchall()
                    if old:
                        totals["displaced_observation"] += len(old)
                        if apply:
                            write_reconcile_revisions(cur, symbol, "observation", old)
                            cur.execute(reconcile_update_sql(obs_src), p)
            conn.commit() if apply else conn.rollback()
    return totals


# --------------------------------------------------------------------------------------
# Balance check
# --------------------------------------------------------------------------------------


def _count_class_sql(source_cte: str, *, logged_is_explained: bool = False) -> str:
    """Twin comparison of a source CTE `src` against ohlcv_raw on the full key.

    With `logged_is_explained` (the canonical class) a differing twin is not counted when an
    ohlcv_revision row of the reconciliation holds exactly the source's value for the key."""
    explained = _NO_LOGGED_TWIN.replace("s.", "src.") if logged_is_explained else "TRUE"
    return f"""
    WITH {source_cte}
    SELECT count(*) AS n,
           count(*) FILTER (WHERE r.symbol IS NULL) AS missing,
           count(*) FILTER (WHERE r.symbol IS NOT NULL AND
               ROW(r.open, r.high, r.low, r.close, r.volume)
               IS NOT DISTINCT FROM ROW(src.open, src.high, src.low, src.close, src.volume))
               AS equal,
           count(*) FILTER (WHERE r.symbol IS NOT NULL AND
               ROW(r.open, r.high, r.low, r.close, r.volume)
               IS DISTINCT FROM ROW(src.open, src.high, src.low, src.close, src.volume)
               AND {explained}) AS diff
      FROM src
      LEFT JOIN ohlcv_raw r
        ON r.timestamp = src.timestamp AND r.symbol = src.symbol
       AND r.timeframe = src.timeframe AND r.vendor = src.vendor AND r.kind = src.kind"""


def _wrap_src(select_sql: str) -> str:
    return f"src AS ({select_sql})"


# Twin comparison for rows present in both canonical and archive: the raw value belongs to the
# archive (pass order), so a canonical diff is explained only when the archive holds the raw value.
_CANONICAL_VS_ARCHIVE_SQL = f"""
    SELECT count(*) AS pair_rows,
           count(*) FILTER (WHERE ROW(a.open, a.high, a.low, a.close, a.volume)
               IS DISTINCT FROM ROW(m.open, m.high, m.low, m.close, m.volume)) AS disagree
      FROM ohlcv_intraday_raw_archive a
      JOIN (VALUES
        {build_vendor_kind_values_sql()}
      ) AS l(label, vendor, kind) ON l.label = a.source
      JOIN market_data_ohlcv m
        ON m.timestamp = a.timestamp AND m.symbol = a.symbol AND m.timeframe = a.timeframe
       AND m.vendor = l.vendor AND m.kind = l.kind
     WHERE m.symbol = %(symbol)s AND m.timestamp >= %(lo)s AND m.timestamp < %(hi)s
       AND m.timeframe <> '1d'"""

_CANONICAL_DISAGREE_SAMPLE_SQL = f"""
    SELECT m.timestamp, m.symbol, m.timeframe, m.vendor, m.kind
      FROM ohlcv_intraday_raw_archive a
      JOIN (VALUES
        {build_vendor_kind_values_sql()}
      ) AS l(label, vendor, kind) ON l.label = a.source
      JOIN market_data_ohlcv m
        ON m.timestamp = a.timestamp AND m.symbol = a.symbol AND m.timeframe = a.timeframe
       AND m.vendor = l.vendor AND m.kind = l.kind
     WHERE m.symbol = %(symbol)s AND m.timestamp >= %(lo)s AND m.timestamp < %(hi)s
       AND m.timeframe <> '1d'
       AND ROW(a.open, a.high, a.low, a.close, a.volume)
           IS DISTINCT FROM ROW(m.open, m.high, m.low, m.close, m.volume)
     LIMIT %(limit)s"""

# Canonical exclusions group by (vendor, kind): the derived pair names the grid rows and any
# pair outside the raw-eligible set lands in the unlabelled bucket (which fails the run);
# synthetic fills cannot appear, the post-swap table has no kind for them.
_EXCLUSION_SQL = """
    SELECT vendor, kind, (timeframe = '1d') AS is_1d, count(*)
      FROM market_data_ohlcv
     WHERE symbol = %(symbol)s AND timestamp >= %(lo)s AND timestamp < %(hi)s
     GROUP BY 1, 2, 3"""

_ARCHIVE_EXCLUSION_SQL = """
    SELECT source, count(*)
      FROM ohlcv_intraday_raw_archive
     WHERE symbol = %(symbol)s AND timestamp >= %(lo)s AND timestamp < %(hi)s
     GROUP BY 1"""

_TEST_OBS_SQL = f"""
    SELECT count(*)
      FROM ohlcv_observation o JOIN ohlcv_request r ON r.request_id = o.request_id
     WHERE o.symbol = %(symbol)s AND o.bar_date >= %(lo)s::date AND o.bar_date < %(hi)s::date
       AND r.caller LIKE '{_TEST_CALLER}'"""

_RAW_PROVENANCE_SQL = """
    SELECT timeframe, served_at IS NULL, request_id IS NULL, load_id IS NULL, count(*)
      FROM ohlcv_raw
     WHERE symbol = %(symbol)s AND timestamp >= %(lo)s AND timestamp < %(hi)s
     GROUP BY 1, 2, 3, 4"""


def _canonical_1d_twin_sql() -> str:
    return f"""
    WITH obs_keys AS (
        SELECT DISTINCT o.symbol, o.bar_date, o.source
          FROM ohlcv_observation o JOIN ohlcv_request r ON r.request_id = o.request_id
         WHERE o.symbol = %(symbol)s AND o.bar_date >= %(lo)s::date AND o.bar_date < %(hi)s::date
           AND r.caller NOT LIKE '{_TEST_CALLER}'
    )
    SELECT m.vendor, count(*) AS n, count(k.symbol) AS with_twin
      FROM market_data_ohlcv m
      LEFT JOIN obs_keys k
        ON k.symbol = m.symbol AND k.bar_date = (m.timestamp AT TIME ZONE 'UTC')::date
       AND k.source = m.vendor
     WHERE m.symbol = %(symbol)s AND m.timestamp >= %(lo)s AND m.timestamp < %(hi)s
       AND m.timeframe = '1d'
     GROUP BY 1"""


def _union_keys_sql(obs_values_sql: str) -> str:
    """Distinct source keys of the three stores in a window (the reverse-direction count)."""
    values = build_vendor_kind_values_sql()
    return f"""
    WITH {_observation_rows_cte(obs_values_sql)}
    SELECT count(*) FROM (
        SELECT a.timestamp, a.symbol, a.timeframe, l.vendor, l.kind
          FROM ohlcv_intraday_raw_archive a
          JOIN (VALUES {values}) AS l(label, vendor, kind) ON l.label = a.source
         WHERE a.symbol = %(symbol)s AND a.timestamp >= %(lo)s AND a.timestamp < %(hi)s
        UNION
        SELECT m.timestamp, m.symbol, m.timeframe, l.vendor, l.kind
          FROM market_data_ohlcv m
          JOIN (VALUES {values}) AS l(label, vendor, kind)
            ON (l.vendor, l.kind) = (m.vendor, m.kind)
         WHERE m.symbol = %(symbol)s AND m.timestamp >= %(lo)s AND m.timestamp < %(hi)s
           AND m.timeframe <> '1d'
        UNION
        SELECT (bar_date::timestamp AT TIME ZONE 'UTC'), symbol, '1d', vendor, kind FROM obs
    ) u"""


def empty_class() -> dict[str, int]:
    return {"source_rows": 0, "twin_equal": 0, "twin_missing": 0, "twin_diff": 0}


def new_report_totals() -> dict[str, Any]:
    return {
        "canonical_vendor": empty_class(),
        "archive": empty_class(),
        "observation": empty_class(),
        "observation_provenance_mismatch": 0,
        "exclusions": {
            _EXCLUDED_DERIVED_LABEL: 0,
            _EXCLUDED_SYNTHETIC_LABEL: 0,
            "1d_canonical_with_observation_twin": 0,
            "1d_canonical_residue_no_observation_twin": 0,
            "test_caller_observations": 0,
        },
        "unlabelled_source_rows": {"canonical": {}, "archive": {}},
        "store_disagreement": {"canonical_vs_archive": 0, "pair_rows": 0, "sample": []},
        "raw_rows": 0,
        "raw_rows_without_source_key": 0,
        "raw_null_provenance": {},
        "residue_1d_by_symbol": {},
        "revisions": {"superseded_runs": 0, "missing": 0, "stored": 0},
    }


def finalize_report(totals: dict[str, Any]) -> dict[str, Any]:
    """The report's arithmetic: unexplained rows, value mismatches and the exit code."""
    can = totals["canonical_vendor"]
    unlabelled = sum(totals["unlabelled_source_rows"]["canonical"].values()) + sum(
        totals["unlabelled_source_rows"]["archive"].values()
    )
    twin_missing = can["twin_missing"] + totals["archive"]["twin_missing"]
    twin_missing += totals["observation"]["twin_missing"]
    # a canonical value diff against raw counts only when no reconciliation revision holds it
    value_mismatches = (
        totals["archive"]["twin_diff"]
        + totals["observation"]["twin_diff"]
        + totals["observation_provenance_mismatch"]
        + can["twin_diff"]
    )
    null_1d_request = sum(
        n
        for key, n in totals["raw_null_provenance"].items()
        if key.startswith("1d|") and key.split("|")[2] == "request_id_null"
    )
    unexplained = (
        twin_missing + unlabelled + totals["raw_rows_without_source_key"] + null_1d_request
    )
    rev = totals["revisions"]
    unexplained += revision_unexplained(rev["superseded_runs"], rev["missing"], rev["stored"])
    totals["unexplained"] = unexplained
    totals["value_mismatches"] = value_mismatches
    totals["exit_code"] = int(unexplained > 0 or value_mismatches > 0)
    return totals


def run_check(
    conn: psycopg.Connection,
    *,
    symbols: list[str],
    years: range,
    obs_values_sql: str,
    sample_limit: int,
) -> dict[str, Any]:
    """The balance report. Every count is read inside the caller's one REPEATABLE READ snapshot."""
    totals = new_report_totals()
    obs_current = f"{observation_current_cte(obs_values_sql)}, src AS (SELECT * FROM current_obs)"
    t0 = time.monotonic()
    with conn.cursor() as cur:
        for sym_i, symbol in enumerate(symbols):
            for year in years:
                lo, hi = window_bounds(year)
                p = {"symbol": symbol, "lo": lo, "hi": hi}
                counts = count_window(cur, obs_values_sql, symbol, lo, hi)
                cur.execute(_EXCLUSION_SQL, p)
                excl_rows = cur.fetchall()
                cur.execute(_ARCHIVE_EXCLUSION_SQL, p)
                arch_excl = cur.fetchall()
                cur.execute(_TEST_OBS_SQL, p)
                test_n = cur.fetchone()[0]
                if counts.total() == 0 and not excl_rows and not arch_excl and test_n == 0:
                    continue
                totals["exclusions"]["test_caller_observations"] += test_n
                labels = vendor_labels()
                raw_pairs = set(labels.values())
                for vendor, kind, is_1d, n in excl_rows:
                    pair = (vendor, kind)
                    if is_1d and pair in raw_pairs:
                        continue
                    if pair == DERIVED_PAIR and not is_1d:
                        totals["exclusions"][_EXCLUDED_DERIVED_LABEL] += n
                    elif pair in raw_pairs:
                        continue
                    else:
                        bucket = totals["unlabelled_source_rows"]["canonical"]
                        token = pair_token(vendor, kind)
                        bucket[token] = bucket.get(token, 0) + n
                # the archive keeps its source label column, so its exclusions stay label-keyed
                for source, n in arch_excl:
                    if source in labels:
                        continue
                    if source == _EXCLUDED_SYNTHETIC_LABEL:
                        totals["exclusions"][_EXCLUDED_SYNTHETIC_LABEL] += n
                    else:
                        bucket = totals["unlabelled_source_rows"]["archive"]
                        bucket[source] = bucket.get(source, 0) + n

                for cls, cte in (
                    ("canonical_vendor", _wrap_src(canonical_select_sql())),
                    ("archive", _wrap_src(archive_select_sql())),
                    ("observation", obs_current),
                ):
                    cur.execute(
                        _count_class_sql(cte, logged_is_explained=cls == "canonical_vendor"), p
                    )
                    n, missing, equal, diff = cur.fetchone()
                    c = totals[cls]
                    c["source_rows"] += n
                    c["twin_missing"] += missing
                    c["twin_equal"] += equal
                    c["twin_diff"] += diff
                cur.execute(
                    f"""WITH {obs_current}
                    SELECT count(*) FROM src s JOIN ohlcv_raw r
                      ON r.timestamp = s.timestamp AND r.symbol = s.symbol
                     AND r.timeframe = s.timeframe AND r.vendor = s.vendor AND r.kind = s.kind
                    WHERE r.served_at IS DISTINCT FROM s.served_at
                       OR r.request_id IS DISTINCT FROM s.request_id""",
                    p,
                )
                totals["observation_provenance_mismatch"] += cur.fetchone()[0]

                cur.execute(_CANONICAL_VS_ARCHIVE_SQL, p)
                pair_rows, disagree = cur.fetchone()
                sd = totals["store_disagreement"]
                sd["pair_rows"] += pair_rows
                sd["canonical_vs_archive"] += disagree
                if disagree and len(sd["sample"]) < sample_limit:
                    cur.execute(_CANONICAL_DISAGREE_SAMPLE_SQL, {**p, "limit": sample_limit})
                    sd["sample"].extend(
                        [[str(t), s, tf, pair_token(v, k)] for t, s, tf, v, k in cur.fetchall()][
                            : sample_limit - len(sd["sample"])
                        ]
                    )

                cur.execute(_canonical_1d_twin_sql(), p)
                for _source, n, with_twin in cur.fetchall():
                    totals["exclusions"]["1d_canonical_with_observation_twin"] += with_twin
                    residue = n - with_twin
                    totals["exclusions"]["1d_canonical_residue_no_observation_twin"] += residue
                    if residue:
                        by = totals["residue_1d_by_symbol"]
                        by[symbol] = by.get(symbol, 0) + residue

                cur.execute(_RAW_PROVENANCE_SQL, p)
                for tf, s_null, r_null, l_null, n in cur.fetchall():
                    totals["raw_rows"] += n
                    key = "|".join(
                        [
                            tf,
                            "served_at_null" if s_null else "served_at_set",
                            "request_id_null" if r_null else "request_id_set",
                            "load_id_null" if l_null else "load_id_set",
                        ]
                    )
                    d = totals["raw_null_provenance"]
                    d[key] = d.get(key, 0) + n
                cur.execute(_union_keys_sql(obs_values_sql), p)
                union_n = cur.fetchone()[0]
                cur.execute(
                    "SELECT count(*) FROM ohlcv_raw WHERE symbol = %(symbol)s "
                    "AND timestamp >= %(lo)s AND timestamp < %(hi)s",
                    p,
                )
                raw_n = cur.fetchone()[0]
                totals["raw_rows_without_source_key"] += max(0, raw_n - union_n)
            cur.execute(revision_balance_sql(obs_values_sql), {"symbol": symbol})
            n_runs, n_missing, n_stored = cur.fetchone()
            totals["revisions"]["superseded_runs"] += n_runs
            totals["revisions"]["missing"] += n_missing
            totals["revisions"]["stored"] += n_stored
            if (sym_i + 1) % 25 == 0 or sym_i + 1 == len(symbols):
                print(
                    f"[{datetime.now(UTC):%H:%M:%S}] check {sym_i + 1}/{len(symbols)} "
                    f"({symbol}) elapsed={time.monotonic() - t0:.0f}s",
                    flush=True,
                )
    return finalize_report(totals)


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------


async def _read_apr() -> tuple[int, int]:
    cfg = ConfigService(get_settings().database_url)
    await cfg.initialize()
    try:
        batch_rows = int(await cfg.get(_BATCH_ROWS_KEY, 50_000))
        timeout_s = int(await cfg.get(_TIMEOUT_KEY, 7200))
    finally:
        await cfg.close()
    return batch_rows, timeout_s


def _observation_values(conn: psycopg.Connection) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT source, route, what_to_show FROM ohlcv_observation")
        triples = [(s, r, w) for s, r, w in cur.fetchall()]
    conn.rollback()
    return build_observation_values_sql(map_observation_triples(triples))


def _symbols(conn: psycopg.Connection, requested: list[str] | None) -> list[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT symbol FROM instruments ORDER BY symbol")
        known = [r[0] for r in cur.fetchall()]
    conn.rollback()
    if not requested:
        return known
    missing = sorted(set(requested) - set(known))
    if missing:
        raise SystemExit(f"unknown symbols: {missing}")
    return sorted(requested)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--bulk", action="store_true", help="load every window not yet current")
    mode.add_argument("--delta", action="store_true", help="reload windows whose counts changed")
    mode.add_argument("--check", action="store_true", help="balance report, exit 1 on failure")
    mode.add_argument(
        "--reconcile",
        action="store_true",
        help="later serves replace raw (old value logged); canonical-only values logged",
    )
    mode.add_argument(
        "--revisions", action="store_true", help="reconstruct ohlcv_revision from observations"
    )
    mode.add_argument(
        "--prune-forming-revisions",
        action="store_true",
        help="rebuild reconstruction revisions of symbols holding forming-bar rows (D-191-J)",
    )
    parser.add_argument("--apply", action="store_true", help="write (default: dry run)")
    parser.add_argument("--symbols", nargs="*", help="restrict to these symbols")
    parser.add_argument(
        "--min-free-gb", type=float, default=None, help="abort below this free disk"
    )
    parser.add_argument(
        "--passes",
        default="archive,observation,canonical",
        help="comma list of passes for --bulk/--delta (default all)",
    )
    parser.add_argument("--force", action="store_true", help="ignore the progress file")
    parser.add_argument(
        "--since",
        default="2026-10-13T06:00:00+00:00",
        help="--reconcile compares serves at or after this time (default: before the bulk began)",
    )
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument("--first-year", type=int, default=_FIRST_YEAR)
    args = parser.parse_args()
    if args.apply and args.min_free_gb is None:
        parser.error("--apply requires --min-free-gb")

    batch_rows, timeout_s = asyncio.run(_read_apr())
    years = range(args.first_year, datetime.now(UTC).year + 1)
    conn = psycopg.connect(get_settings().database_url)
    try:
        conn.isolation_level = IsolationLevel.REPEATABLE_READ
        with conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {int(timeout_s) * 1000}")
        conn.commit()
        symbols = _symbols(conn, args.symbols)
        obs_values_sql = _observation_values(conn)
        _LOG_DIR.mkdir(exist_ok=True)
        if args.check:
            report = run_check(
                conn,
                symbols=symbols,
                years=years,
                obs_values_sql=obs_values_sql,
                sample_limit=args.sample_limit,
            )
            conn.rollback()
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            out = _LOG_DIR / f"raw_backfill_balance_{stamp}.json"
            report["generated_at"] = stamp
            report["isolation"] = "REPEATABLE READ, one snapshot"
            out.write_text(json.dumps(report, indent=2, sort_keys=True))
            print(
                json.dumps(
                    {k: v for k, v in report.items() if k != "residue_1d_by_symbol"}, indent=2
                )
            )
            print(f"report: {out}")
            return int(report["exit_code"])
        if args.reconcile:
            rec = run_reconcile(
                conn,
                symbols=symbols,
                years=years,
                obs_values_sql=obs_values_sql,
                apply=args.apply,
                since=datetime.fromisoformat(args.since),
            )
            print(json.dumps({"mode": "apply" if args.apply else "dry-run", **rec}))
            return 0
        if args.prune_forming_revisions:
            prune = run_prune_forming_revisions(
                conn, symbols=symbols, obs_values_sql=obs_values_sql, apply=args.apply
            )
            print(json.dumps({"mode": "apply" if args.apply else "dry-run", **prune}))
            return 0
        if args.revisions:
            rev_totals = run_revisions(
                conn, symbols=symbols, obs_values_sql=obs_values_sql, apply=args.apply
            )
            print(json.dumps({"mode": "apply" if args.apply else "dry-run", **rev_totals}))
            return 0
        totals = run_windows(
            conn,
            symbols=symbols,
            years=years,
            obs_values_sql=obs_values_sql,
            batch_rows=batch_rows,
            apply=args.apply,
            min_free_gb=args.min_free_gb or 0.0,
            progress_path=_PROGRESS_FILE,
            passes=frozenset(args.passes.split(",")),
            force=args.force,
        )
        print(
            json.dumps(
                {
                    "mode": "apply" if args.apply else "dry-run",
                    "windows_seen": totals.windows_seen,
                    "windows_loaded": totals.windows_loaded,
                    "windows_skipped": totals.windows_skipped,
                    "inserted": totals.inserted,
                    "candidate_rows": totals.candidates,
                },
                indent=2,
            )
        )
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
