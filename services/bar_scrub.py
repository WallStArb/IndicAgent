"""D2a scrub pass: run plan 05's rules over bars and write bar_quality_flag rows.

Phase 185 plan 10 (D-08 through D-14). This module is the one library both the
historical pass (scripts/ops/bars/ops_scrub_historical_pass.py) and plan 17's
nightly derivation call, so the historical and nightly rules are identical by
construction (D-12). Reads come from market_data_ohlcv_scrub_input (plan 04's
scrub-stage boundary view: every traded bar, quarantined included) so no
raw-table read is added; writes touch bar_quality_flag only, one transaction per
symbol under SET LOCAL ROLE bar_derivation_writer. market_data_ohlcv rows are
never UPDATEd or DELETEd (D-09).

The pass runs in three phases so cross-symbol corroboration spans the whole run
rather than a fetch chunk:

1. per symbol (chunked by infra.bar_scrub.symbol_batch): fetch bars as numpy
   arrays, run the single-symbol rules, convert flags to FlagRows, keep each
   symbol's price_sanity candidates as (array index, verdict) plus epoch seconds;
2. once, across every symbol collected: count_corroborating + corroborated_verdict
   behind the D-11 ceiling, dropping the price_sanity flags that downgrade to
   MARKET_EVENT;
3. per symbol: write_flags (delete-then-insert of the evaluated rules).

A symbol whose read fails is collected and reported in one RuntimeError at the
end; every other symbol still completes. Counts are accumulated per rule and
returned -- never logged per bar (CLAUDE.md loop-logging rule).
"""

from __future__ import annotations

import calendar
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, NamedTuple

import numpy as np
import structlog

from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async
from src.intelligence.bars.scrub_rules import (
    RULE_VERSION,
    BarFlag,
    ScrubParams,
    SymbolBars,
    corroborated_verdict,
    count_corroborating,
    gap_before_next,
    non_positive_price,
    ohlc_invariant,
    price_sanity,
    return_magnitude,
    stale_print,
    vol_scaled_jump,
    volume_outlier,
)

_logger = structlog.get_logger(__name__)

# view_disagreement is deliberately absent: it is cross-view, not single-symbol,
# and plans 12/17 call it directly with both price series. legacy_price_sanity_status
# is the migration-381 copy, owned by no rule code.
_D14_INTRADAY_RULES = frozenset({"return_magnitude", "gap_before_next"})
_ALL_1D_RULES = (
    frozenset(
        {
            "ohlc_invariant",
            "non_positive_price",
            "price_sanity",
            "vol_scaled_jump",
            "stale_print",
            "volume_outlier",
        }
    )
    | _D14_INTRADAY_RULES
)
_PROTECTED_RULES = frozenset({"legacy_price_sanity_status", "view_disagreement"})

_DEFAULT_SYMBOL_BATCH = 50

_DISCOVER_SYMBOLS_SQL = """
SELECT DISTINCT symbol FROM market_data_ohlcv_scrub_input WHERE timeframe = $1 ORDER BY symbol
"""

_SELECT_BARS_SQL = """
SELECT "timestamp", open, high, low, close, volume
FROM market_data_ohlcv_scrub_input
WHERE symbol = $1 AND timeframe = $2
  AND ($3::timestamptz IS NULL OR "timestamp" >= $3)
  AND ($4::timestamptz IS NULL OR "timestamp" < $4)
ORDER BY "timestamp"
"""

_SET_WRITER_ROLE_SQL = "SET LOCAL ROLE bar_derivation_writer"

# NULL-tolerant bounds so one statement serves full-history and windowed runs:
# a NULL bound disables that side (historical pass: both NULL).
_DELETE_EVALUATED_SQL = """
DELETE FROM bar_quality_flag
WHERE symbol = $1 AND timeframe = $2
  AND rule = ANY($3::text[])
  AND ($4::timestamptz IS NULL OR "timestamp" >= $4)
  AND ($5::timestamptz IS NULL OR "timestamp" < $5)
"""

_DELETE_STALE_SQL = """
DELETE FROM bar_quality_flag
WHERE symbol = $1 AND timeframe = $2
  AND rule <> ALL($3::text[])
  AND rule NOT IN ('legacy_price_sanity_status', 'split_seam')
  AND ($4::timestamptz IS NULL OR "timestamp" >= $4)
  AND ($5::timestamptz IS NULL OR "timestamp" < $5)
"""

_INSERT_FLAG_SQL = """
INSERT INTO bar_quality_flag
    (symbol, timeframe, "timestamp", rule, rule_version, fields, quarantine, detail, batch_id)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::uuid)
"""


class FlagRow(NamedTuple):
    """One flag ready to write: the bar's timestamp plus its rule verdict.

    quarantine is decided once, at conversion, strictly from the APR
    quarantine_rules list (D-09); detail must stay JSON-safe (finite floats).
    """

    timestamp: datetime
    rule: str
    rule_version: str
    fields: tuple[str, ...]
    quarantine: bool
    detail: dict[str, Any]


def default_rules_for_tf(tf: str) -> frozenset[str]:
    """rules=None contract: every rule at 1d, the D-14 ports at intraday.

    Intraday keeps the rules proven at 1d only (D-14): return_magnitude and
    gap_before_next carried from forward_return_writer before phase 186 deletes
    it. 15m/1h get the full set on the derived grid in plan 12.
    """
    return _ALL_1D_RULES if tf == "1d" else _D14_INTRADAY_RULES


async def load_scrub_params(conn: Any, tf: str) -> ScrubParams:
    """Build ScrubParams from config_state (alpha.* plus threshold.bar_scrub.*)."""
    apr = await load_apr_dict_async(conn, ["threshold.bar_scrub.%"])
    return ScrubParams.from_apr(apr, tf)


async def discover_scrub_symbols(conn: Any, tf: str) -> list[str]:
    """Every symbol with at least one traded bar in the scrub-input view."""
    rows = await conn.fetch(_DISCOVER_SYMBOLS_SQL, tf)
    return [row[0] for row in rows]


def _epoch_seconds(dt: datetime) -> int:
    """Epoch seconds for an aware datetime (naive is treated as UTC)."""
    if dt.tzinfo is None:
        return calendar.timegm(dt.timetuple())
    return int(dt.timestamp())


async def _fetch_symbol_bars(
    conn: Any,
    *,
    symbol: str,
    tf: str,
    start: datetime | None,
    end: datetime | None,
) -> tuple[SymbolBars, list[datetime]]:
    """One symbol's traded bars as arrays plus the raw timestamps.

    Per-symbol arrays, never a wide DataFrame (CLAUDE.md); dtypes are declared
    from the view's fixed schema (double precision OHLC, bigint volume), not
    inferred from fetched data.
    """
    rows = await conn.fetch(_SELECT_BARS_SQL, symbol, tf, start, end)
    dts = [row[0] for row in rows]
    bars = SymbolBars(
        symbol=symbol,
        tf=tf,
        ts_seconds=np.array([_epoch_seconds(d) for d in dts], dtype=np.int64),
        open=np.array([row[1] for row in rows], dtype=np.float64),
        high=np.array([row[2] for row in rows], dtype=np.float64),
        low=np.array([row[3] for row in rows], dtype=np.float64),
        close=np.array([row[4] for row in rows], dtype=np.float64),
        volume=np.array([row[5] for row in rows], dtype=np.float64),
    )
    return bars, dts


def _run_single_symbol_rules(
    bars: SymbolBars, params: ScrubParams, rules: frozenset[str]
) -> tuple[list[BarFlag], tuple[tuple[int, Any], ...]]:
    """Run only the requested single-symbol rules (run_rules runs them all)."""
    flags: list[BarFlag] = []
    candidates: tuple[tuple[int, Any], ...] = ()
    if "ohlc_invariant" in rules:
        flags.extend(ohlc_invariant(bars))
    if "non_positive_price" in rules:
        flags.extend(non_positive_price(bars))
    if "price_sanity" in rules:
        ps_flags, candidates = price_sanity(bars, params)
        flags.extend(ps_flags)
    if "vol_scaled_jump" in rules:
        flags.extend(vol_scaled_jump(bars, params))
    if "stale_print" in rules:
        flags.extend(stale_print(bars, params))
    if "volume_outlier" in rules:
        flags.extend(volume_outlier(bars, params))
    if "return_magnitude" in rules:
        flags.extend(return_magnitude(bars, params))
    if "gap_before_next" in rules:
        flags.extend(gap_before_next(bars, params))
    return flags, candidates


def _to_flag_rows(
    dts: list[datetime], flags: Sequence[BarFlag], params: ScrubParams
) -> tuple[list[FlagRow], dict[int, FlagRow]]:
    """Convert BarFlags to FlagRows; price_sanity rows also keyed by array index."""
    rows: list[FlagRow] = []
    ps_by_index: dict[int, FlagRow] = {}
    for flag in flags:
        row = FlagRow(
            timestamp=dts[flag.index],
            rule=flag.rule,
            rule_version=RULE_VERSION,
            fields=tuple(flag.fields),
            quarantine=flag.rule in params.quarantine_rules,
            detail=dict(flag.detail),
        )
        rows.append(row)
        if flag.rule == "price_sanity":
            ps_by_index[flag.index] = row
    return rows, ps_by_index


@dataclass
class _SymbolScrub:
    """Phase-A output for one symbol: flag rows plus corroboration inputs."""

    rows: list[FlagRow] = field(default_factory=list)
    ps_by_index: dict[int, FlagRow] = field(default_factory=dict)
    candidate_verdicts: list[Any] = field(default_factory=list)
    candidate_ts: list[int] = field(default_factory=list)


def _rowcount(status: str) -> int:
    """Parse the count out of an asyncpg command status like 'DELETE 2'."""
    try:
        return int(status.rsplit(None, 1)[-1])
    except (IndexError, ValueError) as error:
        raise ValueError(f"cannot parse rowcount from status {status!r}") from error


async def write_flags(
    conn: Any,
    *,
    tf: str,
    symbol: str,
    rules_evaluated: frozenset[str],
    flags: Sequence[FlagRow],
    start: datetime | None,
    end: datetime | None,
    batch_id: str,
    prune_stale: bool = False,
) -> int:
    """Replace the evaluated rules' flags for one (symbol, tf) span.

    One transaction whose first statement is SET LOCAL ROLE bar_derivation_writer:
    DELETE the flags of the evaluated rules in [start, end), optionally DELETE the
    flags of rules no longer evaluated (prune_stale, so a dropped rule cannot
    leave quarantine rows hiding bars -- everything except
    'legacy_price_sanity_status', which no rule code owns), then INSERT the new
    rows. Returns the number of rows inserted. Never touches market_data_ohlcv.
    """
    rules_evaluated = frozenset(rules_evaluated)
    if "legacy_price_sanity_status" in rules_evaluated:
        raise ValueError(
            "write_flags never manages 'legacy_price_sanity_status' rows; they are "
            "the migration-381 copy and survive every re-evaluation"
        )
    async with conn.transaction():
        await conn.execute(_SET_WRITER_ROLE_SQL)
        await conn.execute(_DELETE_EVALUATED_SQL, symbol, tf, sorted(rules_evaluated), start, end)
        if prune_stale:
            status = await conn.execute(
                _DELETE_STALE_SQL, symbol, tf, sorted(rules_evaluated), start, end
            )
            pruned = _rowcount(status)
            if pruned:
                _logger.info("bar_scrub.pruned_stale_flags", symbol=symbol, deleted=pruned)
        if flags:
            await conn.executemany(
                _INSERT_FLAG_SQL,
                (
                    (
                        symbol,
                        tf,
                        row.timestamp,
                        row.rule,
                        row.rule_version,
                        list(row.fields),
                        row.quarantine,
                        json.dumps(row.detail),
                        batch_id,
                    )
                    for row in flags
                ),
            )
    return len(flags)


async def scrub_symbols(
    pool: Any,
    *,
    tf: str,
    symbols: Sequence[str] | None,
    rules: frozenset[str] | None,
    start: datetime | None,
    end: datetime | None,
    batch_id: str,
    write: bool = True,
    prune_stale: bool = False,
    quarantine_key_sink: list[tuple[str, str, datetime]] | None = None,
) -> dict[str, int]:
    """Scrub symbols' bars and (when write) replace their flags. Per-rule counts.

    Reads bars per symbol from market_data_ohlcv_scrub_input, runs the
    single-symbol rules, applies corroboration across ALL symbols of the run
    behind the D-11 ceiling, then writes per symbol. rules=None means every rule
    valid for the tf (all rules at 1d, the D-14 ports at intraday). write=False
    is the dry run: same computation, zero DB writes. A symbol whose read fails
    is collected; other symbols still complete and the run raises RuntimeError
    with the failure count at the end.
    """
    async with pool.acquire() as conn:
        apr = await load_apr_dict_async(conn, ["threshold.bar_scrub.%"])
        params = ScrubParams.from_apr(apr, tf)
        symbol_batch = int(_cfg(apr, "infra.bar_scrub.symbol_batch", _DEFAULT_SYMBOL_BATCH))
        if symbols is None:
            symbols = await discover_scrub_symbols(conn, tf)
        symbol_list = list(dict.fromkeys(symbols))
        rules = default_rules_for_tf(tf) if rules is None else frozenset(rules)
        protected = rules & _PROTECTED_RULES
        if protected:
            raise ValueError(
                f"rules {sorted(protected)} are not single-symbol scrub rules; "
                "view_disagreement is called separately with both price views and "
                "legacy_price_sanity_status belongs to migration 381"
            )
        if write and not batch_id:
            raise ValueError("batch_id is required when write=True (provenance, D-08)")

        # Phase A: fetch + single-symbol rules, chunked for bounded memory and
        # one progress log per chunk (never per symbol, never per bar).
        per_symbol: dict[str, _SymbolScrub] = {}
        failures: list[str] = []
        for offset in range(0, len(symbol_list), symbol_batch):
            chunk = symbol_list[offset : offset + symbol_batch]
            for symbol in chunk:
                try:
                    bars, dts = await _fetch_symbol_bars(
                        conn, symbol=symbol, tf=tf, start=start, end=end
                    )
                    flags, candidates = _run_single_symbol_rules(bars, params, rules)
                except Exception as error:
                    failures.append(f"{symbol}: {error}")
                    continue
                rows, ps_by_index = _to_flag_rows(dts, flags, params)
                state = _SymbolScrub(
                    rows=rows,
                    ps_by_index=ps_by_index,
                    candidate_verdicts=[verdict for _, verdict in candidates],
                    candidate_ts=[int(bars.ts_seconds[index]) for index, _ in candidates],
                )
                per_symbol[symbol] = state
            _logger.info(
                "bar_scrub.chunk_complete",
                tf=tf,
                symbols_done=min(offset + symbol_batch, len(symbol_list)),
                symbols_total=len(symbol_list),
                failed_so_far=len(failures),
            )

        # Phase B: corroboration across the whole run, behind the D-11 ceiling.
        n_corroborating = count_corroborating(
            {
                symbol: np.asarray(state.candidate_ts, dtype=np.int64)
                for symbol, state in per_symbol.items()
                if state.candidate_ts
            },
            window_seconds=params.corroboration_window_seconds,
        )
        n_market_event = 0
        for symbol, state in per_symbol.items():
            dropped_ts: set[int] = set()
            for verdict, ts in zip(state.candidate_verdicts, state.candidate_ts):
                if verdict.verdict != "CONFIRMED_CORRUPT":
                    continue
                final = corroborated_verdict(
                    verdict,
                    n_corroborating.get((symbol, ts), 0),
                    min_symbols=params.min_symbols,
                    max_clearable_ratio=params.corroboration_max_clearable_ratio,
                )
                if final.verdict == "MARKET_EVENT":
                    dropped_ts.add(ts)
                    n_market_event += 1
            if dropped_ts:
                state.rows = [
                    row
                    for row in state.rows
                    if not (
                        row.rule == "price_sanity" and _epoch_seconds(row.timestamp) in dropped_ts
                    )
                ]

        # Phase C: write per symbol, count per rule.
        counts = dict.fromkeys(sorted(rules), 0)
        for symbol, state in per_symbol.items():
            if write:
                await write_flags(
                    conn,
                    tf=tf,
                    symbol=symbol,
                    rules_evaluated=rules,
                    flags=state.rows,
                    start=start,
                    end=end,
                    batch_id=batch_id,
                    prune_stale=prune_stale,
                )
            for row in state.rows:
                counts[row.rule] += 1
                if quarantine_key_sink is not None and row.quarantine:
                    quarantine_key_sink.append((row.rule, symbol, row.timestamp))

        _logger.info(
            "bar_scrub.run_complete",
            tf=tf,
            rules=sorted(rules),
            symbols=len(symbol_list),
            symbols_failed=len(failures),
            flags_written=sum(counts.values()),
            price_sanity_market_event=n_market_event,
            wrote=write,
        )
        if failures:
            raise RuntimeError(f"bar_scrub: {len(failures)} symbol read failure(s): {failures}")
        return counts
