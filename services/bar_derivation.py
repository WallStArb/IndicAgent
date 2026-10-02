"""BarDerivation: the D2b derived 15m/1h grid writer (phase 185 plan 11, D-15).

Oneshot batch. For each symbol it re-derives 15m and 1h bars from the symbol's
tradeable 5m bars on session-anchored edges (plan 06's aggregate_session_grid),
and in one transaction per symbol, under SET LOCAL ROLE bar_derivation_writer
(185-01 A7 measured the role CAN DML compressed chunks):

1. archive the stored IBKR 15m/1h rows into ohlcv_intraday_raw_archive
   (synthetic-fill placeholders are never archived; they are not observations);
2. verify count and value checksums of the removable rows against the archive
   inside the same transaction -- a mismatch rolls the symbol back and nothing
   leaves market_data_ohlcv (D-09 flag-never-delete spirit: the raw answer is
   kept before the canonical row is replaced);
3. DELETE the (symbol, 15m/1h) segment, placeholders included, so readers see
   only derived rows;
4. write the derived rows (source derived_5m), the constituent_flag
   bar_quality_flag rows listing each derived bar's constituent 5m flag rules,
   and one bar_content_digest row per (tf, calendar month) for 5m, 15m and 1h
   with the rule version beside it (D-07; phase 186 reads the current view).

Quarantined 5m bars are excluded from aggregation (RESEARCH finding 11); a
symbol with no tradeable 5m bars is skipped with outcome no_5m and its stored
rows stay as they are. Default is a dry run: same computation, zero writes and
no batch row; --apply is the explicit opt-in. --changed-only skips symbols
whose 5m month digests all equal bar_content_digest_current. Plan 12 runs the
live rewrite and chains this unit from the nightly backfill.

Write method segment_delete_copy per 185-01 measurements c/d (90-111k rows/s
against compressed chunks); the APR key records that choice.
"""

from __future__ import annotations

import argparse
import asyncio
import calendar
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple

import asyncpg
import numpy as np

from scripts.infrastructure.backfill._request_coverage import AnsweredWindows
from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async
from services.bar_derivation_batch import close_batch, open_batch
from services.intraday_raw_archive import ARCHIVE_FROM_TABLE_SQL
from src.config.settings import Settings
from src.core.agent.base_batch import BaseBatch
from src.intelligence.bars.digest import DIGEST_ALGORITHM, bar_content_digest, month_ranges
from src.intelligence.bars.session_grid import GridBars, aggregate_session_grid
from src.intelligence.bars.sessions import nyse_sessions
from src.intelligence.bars.sources import GRID_RULE_VERSION, GRID_TIMEFRAMES, SOURCE_DERIVED_5M
from src.observability.metrics import counter
from src.observability.otel import OTelInitError, init_otel_providers

_JOB = "bar-derivation"
# Per-run outcomes, labeled {stage, outcome} only: never per symbol (cardinality);
# per-symbol detail (failures, outside-session drops) stays in the log.
_OUTCOME_TOTAL = counter(
    "bar_derivation_outcome_total",
    "bar_derivation per-run outcome counts: symbols derived, skipped unchanged by "
    "--changed-only, skipped with no tradeable 5m, skipped as an excluded lane, and "
    "failed. Never labeled by symbol.",
)
_WRITER_ROLE_SQL = "SET LOCAL ROLE bar_derivation_writer"
_CONSTITUENT_RULE = "constituent_flag"
# A derived bar whose constituent 5m slot is neither stored nor inside an
# answered SMART TRADES request window (todo 462): the hole stops at the
# derivation edge as a quarantine-false flag, never silently as a complete bar.
_PARTIAL_RULE = "partial_constituents"
_ANSWERED_OUTCOMES = ("bars", "no_data")
_GRID_TF_LIST = sorted(GRID_TIMEFRAMES)
_WRITE_METHOD = "segment_delete_copy"
_DEFAULT_SYMBOL_BATCH = 10
_SESSION_MARGIN_DAYS = 3

_DISCOVER_SYMBOLS_SQL = """
SELECT DISTINCT symbol FROM market_data_ohlcv_tradeable WHERE timeframe = '5m' ORDER BY symbol
"""

_SELECT_5M_SQL = """
SELECT "timestamp", open, high, low, close, volume, base
FROM market_data_ohlcv_tradeable
WHERE symbol = $1 AND timeframe = '5m'
ORDER BY "timestamp"
"""

_SELECT_5M_FLAGS_SQL = """
SELECT "timestamp", rule, quarantine
FROM bar_quality_flag
WHERE symbol = $1 AND timeframe = '5m'
"""

_SELECT_CURRENT_DIGESTS_SQL = """
SELECT range_start, digest FROM bar_content_digest_current
WHERE symbol = $1 AND timeframe = '5m'
"""

# Answered SMART TRADES 5m windows (todo 462's coverage rule, same semantics as
# _request_coverage's psycopg loader; this asyncpg form is local until plan 18's
# shared gap planner replaces both). A `bars` answer counts only when a stored 5m
# row corroborates it: the request record and the bars still commit separately at
# 5m until plan 18 reuses the atomic persist helper, so a lost chunk must not
# make a window look covered.
_SELECT_ANSWERED_WINDOWS_SQL = """
SELECT r.window_start, r.window_end
FROM ohlcv_request r
WHERE r.symbol = $1 AND r.timeframe = '5m' AND r.route = 'SMART'
  AND r.what_to_show = 'TRADES' AND r.outcome = ANY($2::text[])
  AND r.window_start IS NOT NULL
  AND (
    r.outcome = 'no_data'
    OR EXISTS (
      SELECT 1 FROM market_data_ohlcv m
      WHERE m.symbol = r.symbol AND m.timeframe = r.timeframe
        AND m.timestamp >= r.window_start AND m.timestamp < r.window_end
    )
  )
ORDER BY r.window_start
"""

# --changed-only must also re-derive when an answered 5m window arrived after
# the symbol's last derivation: the new answer can clear a stale
# partial_constituents flag even though no stored bar changed.
_SELECT_ANSWERED_SINCE_SQL = """
SELECT EXISTS (
    SELECT 1 FROM ohlcv_request r
    WHERE r.symbol = $1 AND r.timeframe = '5m' AND r.route = 'SMART'
      AND r.what_to_show = 'TRADES' AND r.outcome = ANY($2::text[])
      AND r.answered_at IS NOT NULL
      AND r.answered_at > COALESCE(
          (SELECT max(computed_at) FROM bar_content_digest WHERE symbol = $1),
          '-infinity'::timestamptz)
) AS answered_since
"""

# Moved byte-identical to services/intraday_raw_archive.py in plan 12 (the
# table's single owner module; the archive writer-boundary CI test fails on
# any other INSERT into it).
_INSERT_ARCHIVE_SQL = ARCHIVE_FROM_TABLE_SQL

# One row comparing the removable stored segment with the archive, key by key:
# n_archived counts archive matches (NULL when a removable row was never
# archived), and the archived sums skip unmatched rows, so any missing or
# value-drifted archive row breaks the equality before the DELETE runs.
# Removable means original observations only: derived_5m rows are rebuildable
# cache (a re-derivation deletes and regenerates them), so they are excluded —
# otherwise the second pass compares its derived values against the archived
# originals under the same keys and the equality can never hold (plan 12 live
# run, 2026-10-01).
_ARCHIVE_VERIFY_SQL = """
SELECT count(*)::bigint AS n_removable,
       count(a."timestamp")::bigint AS n_archived,
       coalesce(sum(m.open + m.high + m.low + m.close), 0::double precision) AS removable_value_sum,
       coalesce(sum(a.open + a.high + a.low + a.close), 0::double precision) AS archived_value_sum,
       coalesce(sum(m.volume), 0::numeric) AS removable_volume_sum,
       coalesce(sum(a.volume), 0::numeric) AS archived_volume_sum
FROM market_data_ohlcv m
LEFT JOIN ohlcv_intraday_raw_archive a
    ON a.symbol = m.symbol AND a.timeframe = m.timeframe AND a."timestamp" = m."timestamp"
WHERE m.symbol = $1 AND m.timeframe = ANY($2::text[])
  AND m.source <> 'synthetic_fill' AND m.source <> 'derived_5m'
"""

_DELETE_SEGMENT_SQL = """
DELETE FROM market_data_ohlcv
WHERE symbol = $1 AND timeframe = ANY($2::text[])
"""

_INSERT_DERIVED_SQL = """
INSERT INTO market_data_ohlcv
    ("timestamp", symbol, timeframe, open, high, low, close, volume, source, base)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
"""

_INSERT_FLAG_SQL = """
INSERT INTO bar_quality_flag
    (symbol, timeframe, "timestamp", rule, rule_version, fields, quarantine, detail, batch_id)
VALUES ($1, $2, $3, $4, $5, $6::text[], $7, $8::jsonb, $9::uuid)
ON CONFLICT (symbol, timeframe, "timestamp", rule) DO UPDATE SET
    rule_version = EXCLUDED.rule_version,
    fields = EXCLUDED.fields,
    detail = EXCLUDED.detail,
    batch_id = EXCLUDED.batch_id
"""

# A rewrite replaces the segment's partial flags (a later answered window
# clears a stale one); constituent flags are upserted, this one is scoped.
_DELETE_PARTIAL_FLAGS_SQL = """
DELETE FROM bar_quality_flag
WHERE symbol = $1 AND timeframe = ANY($2::text[]) AND rule = 'partial_constituents'
"""

_INSERT_DIGEST_SQL = """
INSERT INTO bar_content_digest
    (symbol, timeframe, range_start, range_end, digest, algorithm, rule_version, n_rows, batch_id)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::uuid)
"""


class _SymbolFailure(Exception):
    """One symbol's derivation or write failed; the run continues and fails at the end."""


class _SymbolResult(NamedTuple):
    outcome: str
    error: str | None
    n_derived: int
    n_archived: int = 0


def _rowcount(status: str) -> int:
    """Parse the count out of an asyncpg command status like 'DELETE 2'."""
    try:
        return int(status.rsplit(None, 1)[-1])
    except (IndexError, ValueError) as error:
        raise ValueError(f"cannot parse rowcount from status {status!r}") from error


def _epoch_seconds(dt: datetime) -> int:
    """Epoch seconds for an aware datetime (naive is treated as UTC)."""
    if dt.tzinfo is None:
        return calendar.timegm(dt.timetuple())
    return int(dt.timestamp())


def _read_exclude_file(path: str | None, logger: Any) -> frozenset[str]:
    """Symbols one-per-line from the lane-guard file; a missing file excludes nothing."""
    if not path:
        return frozenset()
    exclude_path = Path(path)
    if not exclude_path.exists():
        logger.info("bar_derivation.no_exclude_file", path=path)
        return frozenset()
    symbols = {
        line.strip()
        for line in exclude_path.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    if symbols:
        logger.info("bar_derivation.excluded_lanes", n=len(symbols))
    return frozenset(symbols)


def _derive_for_tf(
    ts_seconds: np.ndarray,
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    rules_per_row: list[tuple[str, ...]],
    sessions: dict[date, tuple[datetime, datetime]],
    minutes: int,
) -> tuple[GridBars, list[tuple[str, ...]]]:
    """Aggregate one timeframe plus, per derived bar, its constituent rule union."""
    grid = aggregate_session_grid(ts_seconds, open_, high, low, close, volume, sessions, minutes)
    constituent_rules: list[tuple[str, ...]] = []
    for first, last in zip(grid.first_index, grid.last_index):
        union: set[str] = set()
        for i in range(int(first), int(last) + 1):
            union.update(rules_per_row[i])
        constituent_rules.append(tuple(sorted(union)))
    return grid, constituent_rules


def _missing_constituent_slots(
    bar_ts_seconds: int,
    minutes: int,
    session_close: datetime | None,
    stored_slots: frozenset[int],
    answered: AnsweredWindows,
) -> list[datetime]:
    """The bar's expected 5m slots that are neither stored nor inside an
    answered SMART TRADES window (todo 462). A stored-but-quarantined slot
    counts as present (its absence from the aggregate is already flagged by
    the constituent rules); a placeholder-shaped hole is not present."""
    interval = 300
    end = bar_ts_seconds + minutes * 60
    if session_close is not None:
        end = min(end, _epoch_seconds(session_close))
    missing: list[datetime] = []
    slot = bar_ts_seconds
    while slot < end:
        if slot not in stored_slots and not answered.covers(
            datetime.fromtimestamp(slot, tz=UTC), timedelta(seconds=interval)
        ):
            missing.append(datetime.fromtimestamp(slot, tz=UTC))
        slot += interval
    return missing


def _month_digest_rows(
    ts_seconds: np.ndarray,
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    rules_per_row: list[tuple[str, ...]],
) -> list[tuple[datetime, datetime, str, int]]:
    """(range_start, range_end, digest, n_rows) per calendar month of the slice."""
    rows: list[tuple[datetime, datetime, str, int]] = []
    for start, end in month_ranges(ts_seconds):
        mask = (ts_seconds >= int(start.timestamp())) & (ts_seconds < int(end.timestamp()))
        rows.append(
            (
                start,
                end,
                bar_content_digest(
                    ts_seconds[mask],
                    open_[mask],
                    high[mask],
                    low[mask],
                    close[mask],
                    volume[mask],
                    [rules_per_row[i] for i in np.flatnonzero(mask)],
                ),
                int(mask.sum()),
            )
        )
    return rows


class BarDerivation(BaseBatch):
    """Batch service: tradeable 5m bars -> derived 15m/1h grid + digests (D2b)."""

    job_name = _JOB
    compute_version = GRID_RULE_VERSION

    def __init__(
        self,
        db_dsn: str,
        *,
        stage: str,
        symbols: list[str] | None,
        changed_only: bool,
        apply: bool,
        exclude_symbols_file: str | None,
    ) -> None:
        super().__init__(db_dsn)
        if stage != "grid":
            raise ValueError(f"unknown stage {stage!r}; only 'grid' exists (plan 17 adds daily)")
        self._stage = stage
        self._symbols = symbols
        self._changed_only = changed_only
        self._apply = apply
        self._exclude_symbols_file = exclude_symbols_file

    async def execute(self, pool: asyncpg.Pool) -> dict[str, int]:
        async with pool.acquire() as conn:
            apr = await load_apr_dict_async(conn, ["infra.bar_derivation.%"])
            symbol_batch = int(
                _cfg(apr, "infra.bar_derivation.grid_symbol_batch", _DEFAULT_SYMBOL_BATCH)
            )
            method = str(_cfg(apr, "infra.bar_derivation.grid_write_method", _WRITE_METHOD))
            if method != _WRITE_METHOD:
                raise ValueError(
                    f"infra.bar_derivation.grid_write_method={method!r}: only "
                    f"{_WRITE_METHOD!r} is implemented (185-01 measurements)"
                )
            symbols = (
                list(self._symbols)
                if self._symbols
                else [r[0] for r in await conn.fetch(_DISCOVER_SYMBOLS_SQL)]
            )
            excluded = _read_exclude_file(self._exclude_symbols_file, self.logger)
            targets = [s for s in symbols if s not in excluded]

            apr_snapshot = {k: v for k, v in apr.items() if k.startswith("infra.bar_derivation.")}
            batch_id: str | None = None
            if self._apply:
                batch_id = await open_batch(
                    conn,
                    stage="grid",
                    rule_version=GRID_RULE_VERSION,
                    apr_snapshot=apr_snapshot,
                    n_symbols=len(targets),
                )
            totals = dict.fromkeys(("derived", "unchanged", "no_5m", "excluded_lane", "failed"), 0)
            totals["excluded_lane"] = len(symbols) - len(targets)
            n_derived_rows = 0
            n_archived_rows = 0
            failed: list[str] = []
            try:
                for offset in range(0, len(targets), symbol_batch):
                    chunk = targets[offset : offset + symbol_batch]
                    for symbol in chunk:
                        result = await self._run_symbol(conn, symbol=symbol, batch_id=batch_id)
                        totals[result.outcome] += 1
                        n_derived_rows += result.n_derived
                        n_archived_rows += result.n_archived
                        if result.error:
                            failed.append(result.error)
                    self.logger.info(
                        "bar_derivation.chunk_complete",
                        stage=self._stage,
                        symbols_done=min(offset + symbol_batch, len(targets)),
                        symbols_total=len(targets),
                        failed_so_far=len(failed),
                    )
            finally:
                if batch_id is not None:
                    await close_batch(
                        conn,
                        batch_id,
                        status="failed" if failed else "completed",
                        detail={
                            "totals": {k: n for k, n in totals.items() if n},
                            "n_derived_rows": n_derived_rows,
                            # Removable (stored non-synthetic) 15m/1h rows the
                            # archive step verified and the segment DELETE took;
                            # plan 12's live check compares it with the archive.
                            "n_archive_rows": n_archived_rows,
                            "apply": self._apply,
                            "changed_only": self._changed_only,
                        },
                    )

        self.logger.info(
            "bar_derivation.done",
            stage=self._stage,
            symbols=len(symbols),
            apply=self._apply,
            changed_only=self._changed_only,
            **totals,
            derived_rows=n_derived_rows,
        )
        for outcome in ("derived", "unchanged", "no_5m", "excluded_lane", "failed"):
            if totals[outcome]:
                _OUTCOME_TOTAL.add(totals[outcome], {"stage": self._stage, "outcome": outcome})
        if failed:
            raise RuntimeError(f"bar_derivation: {len(failed)} symbol failure(s): {failed}")
        return {**totals, "derived_rows": n_derived_rows}

    async def _load_answered_windows(
        self, conn: asyncpg.Connection, symbol: str
    ) -> AnsweredWindows:
        """Answered SMART TRADES 5m windows for `symbol`, read once per symbol."""
        rows = await conn.fetch(_SELECT_ANSWERED_WINDOWS_SQL, symbol, list(_ANSWERED_OUTCOMES))
        return AnsweredWindows.from_rows([(r["window_start"], r["window_end"]) for r in rows])

    async def _run_symbol(
        self, conn: asyncpg.Connection, *, symbol: str, batch_id: str | None
    ) -> _SymbolResult:
        rows = await conn.fetch(_SELECT_5M_SQL, symbol)
        if not rows:
            return _SymbolResult("no_5m", None, 0)
        flag_rows = await conn.fetch(_SELECT_5M_FLAGS_SQL, symbol)
        quarantined = {_epoch_seconds(r["timestamp"]) for r in flag_rows if r["quarantine"]}
        rules_by_ts: dict[int, set[str]] = {}
        for r in flag_rows:
            if not r["quarantine"]:
                rules_by_ts.setdefault(_epoch_seconds(r["timestamp"]), set()).add(r["rule"])

        kept = [r for r in rows if _epoch_seconds(r["timestamp"]) not in quarantined]
        if not kept:
            # Every 5m bar is quarantined: no tradeable input, same contract as no_5m.
            return _SymbolResult("no_5m", None, 0)
        ts_seconds = np.array([_epoch_seconds(r["timestamp"]) for r in kept], dtype=np.int64)
        open_ = np.array([r["open"] for r in kept], dtype=np.float64)
        high = np.array([r["high"] for r in kept], dtype=np.float64)
        low = np.array([r["low"] for r in kept], dtype=np.float64)
        close = np.array([r["close"] for r in kept], dtype=np.float64)
        volume = np.array([r["volume"] for r in kept], dtype=np.float64)
        base = kept[0]["base"]
        rules_per_row = [tuple(sorted(rules_by_ts.get(int(ts), ()))) for ts in ts_seconds]

        sessions = nyse_sessions(
            (
                datetime.fromtimestamp(int(ts_seconds[0]), tz=UTC)
                - timedelta(days=_SESSION_MARGIN_DAYS)
            ).date(),
            (
                datetime.fromtimestamp(int(ts_seconds[-1]), tz=UTC)
                + timedelta(days=_SESSION_MARGIN_DAYS)
            ).date(),
        )
        digest_5m = _month_digest_rows(ts_seconds, open_, high, low, close, volume, rules_per_row)
        if self._changed_only:
            current = {
                r["range_start"]: r["digest"]
                for r in await conn.fetch(_SELECT_CURRENT_DIGESTS_SQL, symbol)
            }
            if current == {start: digest for start, _, digest, _ in digest_5m}:
                answered_since = await conn.fetchrow(
                    _SELECT_ANSWERED_SINCE_SQL, symbol, list(_ANSWERED_OUTCOMES)
                )
                if not answered_since["answered_since"]:
                    return _SymbolResult("unchanged", None, 0)

        derived: dict[str, tuple[GridBars, list[tuple[str, ...]]]] = {
            tf: _derive_for_tf(
                ts_seconds, open_, high, low, close, volume, rules_per_row, sessions, minutes
            )
            for tf, minutes in GRID_TIMEFRAMES.items()
        }
        n_derived = sum(grid.ts_seconds.size for grid, _ in derived.values())
        n_outside = sum(grid.n_outside_session for grid, _ in derived.values())
        if n_outside:
            self.logger.warning(
                "bar_derivation.bars_outside_session", symbol=symbol, dropped=n_outside
            )

        # Coverage-aware derivation (todo 462): flag bars over stored-but-
        # unanswered 5m holes. The windows are read once per symbol; the pure
        # merge/cover logic is _request_coverage's until plan 18's gap planner.
        stored_slots = frozenset(_epoch_seconds(r["timestamp"]) for r in rows)
        answered = await self._load_answered_windows(conn, symbol)
        session_close_by_date = {day: close for day, (_open, close) in sessions.items()}
        partial_flag_args: list[tuple] = []
        for tf, (grid, _rules) in derived.items():
            minutes = GRID_TIMEFRAMES[tf]
            for i, ts in enumerate(grid.ts_seconds):
                bar_dt = datetime.fromtimestamp(int(ts), tz=UTC)
                missing = _missing_constituent_slots(
                    int(ts),
                    minutes,
                    session_close_by_date.get(bar_dt.date()),
                    stored_slots,
                    answered,
                )
                if missing:
                    partial_flag_args.append(
                        (
                            symbol,
                            tf,
                            bar_dt,
                            _PARTIAL_RULE,
                            GRID_RULE_VERSION,
                            [],
                            False,
                            json.dumps(
                                {
                                    "missing_slots": len(missing),
                                    "n_constituents": int(grid.n_constituents[i]),
                                }
                            ),
                            batch_id,
                        )
                    )
        if not self._apply:
            return _SymbolResult("derived", None, n_derived)

        try:
            async with conn.transaction():
                await conn.execute(_WRITER_ROLE_SQL)
                await conn.execute(_INSERT_ARCHIVE_SQL, symbol, _GRID_TF_LIST, batch_id)
                verify = await conn.fetchrow(_ARCHIVE_VERIFY_SQL, symbol, _GRID_TF_LIST)
                if (
                    verify["n_removable"] != verify["n_archived"]
                    or verify["removable_value_sum"] != verify["archived_value_sum"]
                    or verify["removable_volume_sum"] != verify["archived_volume_sum"]
                ):
                    raise _SymbolFailure(
                        f"archive verify failed: removable (n={verify['n_removable']}, "
                        f"v={verify['removable_value_sum']}, vol={verify['removable_volume_sum']}) "
                        f"vs archived (n={verify['n_archived']}, "
                        f"v={verify['archived_value_sum']}, vol={verify['archived_volume_sum']})"
                    )
                await conn.execute(_DELETE_SEGMENT_SQL, symbol, _GRID_TF_LIST)
                # The rewrite replaces the segment's partial flags, so a later
                # answered window clears a stale one (todo 462).
                await conn.execute(_DELETE_PARTIAL_FLAGS_SQL, symbol, _GRID_TF_LIST)

                flag_args: list[tuple] = []
                for tf, (grid, constituent_rules) in derived.items():
                    if grid.ts_seconds.size:
                        await conn.executemany(
                            _INSERT_DERIVED_SQL,
                            (
                                (
                                    datetime.fromtimestamp(int(ts), tz=UTC),
                                    symbol,
                                    tf,
                                    float(o),
                                    float(h),
                                    float(lo),
                                    float(c),
                                    int(v),
                                    SOURCE_DERIVED_5M,
                                    base,
                                )
                                for ts, o, h, lo, c, v in zip(
                                    grid.ts_seconds,
                                    grid.open,
                                    grid.high,
                                    grid.low,
                                    grid.close,
                                    grid.volume,
                                )
                            ),
                        )
                    for i, (ts, rules) in enumerate(zip(grid.ts_seconds, constituent_rules)):
                        if not rules:
                            continue
                        n_constituents = int(grid.n_constituents[i])
                        flag_args.append(
                            (
                                symbol,
                                tf,
                                datetime.fromtimestamp(int(ts), tz=UTC),
                                _CONSTITUENT_RULE,
                                GRID_RULE_VERSION,
                                [],
                                False,
                                json.dumps(
                                    {
                                        "constituent_rules": list(rules),
                                        "n_constituents": n_constituents,
                                    }
                                ),
                                batch_id,
                            )
                        )
                if flag_args or partial_flag_args:
                    await conn.executemany(_INSERT_FLAG_SQL, flag_args + partial_flag_args)

                digest_args = [
                    (
                        symbol,
                        "5m",
                        start,
                        end,
                        digest,
                        DIGEST_ALGORITHM,
                        GRID_RULE_VERSION,
                        n,
                        batch_id,
                    )
                    for start, end, digest, n in digest_5m
                ]
                for tf, (grid, constituent_rules) in derived.items():
                    digest_args.extend(
                        (
                            symbol,
                            tf,
                            start,
                            end,
                            digest,
                            DIGEST_ALGORITHM,
                            GRID_RULE_VERSION,
                            n,
                            batch_id,
                        )
                        for start, end, digest, n in _month_digest_rows(
                            grid.ts_seconds,
                            grid.open,
                            grid.high,
                            grid.low,
                            grid.close,
                            grid.volume,
                            constituent_rules,
                        )
                    )
                if digest_args:
                    await conn.executemany(_INSERT_DIGEST_SQL, digest_args)
        except Exception as error:
            return _SymbolResult("failed", f"{symbol}: {error}", 0)
        return _SymbolResult("derived", None, n_derived, int(verify["n_removable"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive the 15m/1h grid from tradeable 5m bars")
    parser.add_argument("--stage", choices=["grid"], default="grid")
    parser.add_argument(
        "--symbols",
        nargs="*",
        default=None,
        help="limit to these symbols (default: all with tradeable 5m)",
    )
    parser.add_argument(
        "--changed-only",
        action="store_true",
        help="skip symbols whose 5m month digests equal bar_content_digest_current",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the replacement (default: dry run, compute and report only)",
    )
    parser.add_argument(
        "--exclude-symbols-file",
        default=None,
        help="one symbol per line to skip with outcome excluded_lane (plan 12's lane guard)",
    )
    args = parser.parse_args()
    # Accept both `--symbols SPY,AAPL` (the pipeline/plan convention) and
    # `--symbols SPY AAPL`; nargs="*" alone would take the comma form as one
    # bogus symbol and skip it as no_5m.
    if args.symbols:
        args.symbols = [
            sym for part in args.symbols for sym in (t.strip() for t in part.split(",")) if sym
        ]
    try:
        init_otel_providers(f"indicagent-{_JOB}")
    except OTelInitError:
        pass
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    writer = BarDerivation(
        db_dsn,
        stage=args.stage,
        symbols=args.symbols,
        changed_only=args.changed_only,
        apply=args.apply,
        exclude_symbols_file=args.exclude_symbols_file,
    )
    asyncio.run(writer.run())


if __name__ == "__main__":
    main()
