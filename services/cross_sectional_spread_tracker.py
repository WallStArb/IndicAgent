#!/usr/bin/env python3
"""CrossSectionalSpreadTracker — pure construction primitives for Phase 167's dollar-neutral
decile long-short spread.

This module is the productionization of
`scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py` — the Edge Source
Thesis T3 falsification script that passed decisively (STATE.md, 2026-07-26). Everything here
is a pure, side-effect-free function with no DB or Kafka I/O, so equivalence to the proof
script's ranking mechanic can be asserted directly in a unit test, and Plan 03's service becomes
thin orchestration over already-proven math.

CORRECTNESS INVARIANTS:
- Legs are FLAT equal-weight, never vol-scaled (design decision 1, RESEARCH.md Pitfall 1). The
  design doc's Minimal Design step 3 says "vol-scaled per symbol," but the T3 script that
  actually earned this phase uses `long_leg[return_col].mean() - short_leg[return_col].mean()`.
  Build exactly what was proven; vol-scaling is a separate, testable enhancement with its own
  before/after comparison, never a silent upgrade folded in here.
- The ranked feature is `ctf_momentum` directly, never `ensemble_alpha` (D-01/D-02) — a single
  feature, no composite score. This module never reads `ensemble_alpha`.
- `decile_legs` breaks ties deterministically by `(feature_value, symbol)` ascending (design
  decision 2). This is a RECORDED REPRODUCIBILITY DIVERGENCE from the T3 proof script, which
  ranks via pandas `sort_values(feature)` whose tie order depends on input row order. On a
  continuous z-scored feature exact ties are effectively measure-zero, so this does not change
  what T3 proved — it makes the persisted output reproducible across runs. If a future feature
  with a discrete or heavily-quantized distribution is ever ranked by this machinery, that
  "ties are irrelevant" judgment must be re-examined (Codex review, MEDIUM).
- `one_way_turnover` returns `None`, never `0.0`, when no predecessor legs exist (design
  decision 3, RESEARCH.md Pitfall 4). A turnover of exactly 0.0 or 1.0 at every incremental run
  boundary is Pitfall 4's stated symptom of a service that treats "first bar this run" as having
  no predecessor; returning `None` makes that failure mode structurally detectable instead of
  indistinguishable from a legitimate zero-turnover bar.
- `net_spread_by_cost_bps` computes every cost tier LIVE from realized turnover, every run
  (D-05) — never a cached "it survives" conclusion, and never reads the directional-trade
  cost-hurdle APR key (RESEARCH.md Pitfall 5 — that key belongs to a different mechanism with
  different cost dynamics; see this function's docstring for the exact key name).
- A missing (`None`) or non-finite (NaN / +-inf) feature value entering `decile_legs` raises
  `ValueError` naming the offending symbol rather than being silently sorted (design decision
  5). Python's tuple sort on a NaN key is partition-dependent and non-transitive — it raises
  nothing and produces a plausible-looking but arbitrary leg assignment, exactly the "silent
  wrong answer" CLAUDE.md forbids.

MANUAL/ON-DEMAND ONLY (design decision 1): `CrossSectionalSpreadTracker` is deliberately NOT
registered on a systemd timer and NOT added to `service_auditor._DAG_ORDER` -- mirroring
`alpha_scorer.py`'s own module-docstring precedent. Four reasons: (a) `alpha_scorer.py`,
`counterfactual_tracker.py`, and `tag_calibrator.py` are all manual/on-demand with no systemd
unit -- a registered timer here would make this service the outlier; (b) CLAUDE.md's "prove
edge before production infra" -- a construction that has not yet cleared its own Validation
Gates does not earn scheduled infrastructure; (c) CLAUDE.md records that all indicagent
systemd timers are confirmed disabled as of 2026-07-02, so a registered timer would create a
false impression of a cadence that does not actually run; (d) the `--backfill` pass populates
the full 2006-2026 history in one shot, handing Gate 1 roughly 130 OOS day-clusters
immediately rather than waiting on calendar time. Revisit only if this construction clears all
three Validation Gates.

RECOVERY (design decision 5): a crashed run's watermark and prior-leg turnover seed both
derive only from COMMITTED `construction_spreads` rows, never from anything the crashed run
held only in memory. Because writes are flushed in `bar_ts` order in fixed-size chunks, a
crash can only ever truncate a contiguous TAIL of the intended row set -- the next incremental
run recomputes exactly those bars, seeding turnover from the last surviving persisted row, and
produces a table identical to an uninterrupted run.

Usage:
    python services/cross_sectional_spread_tracker.py             # incremental compute-and-persist
    python services/cross_sectional_spread_tracker.py --backfill  # full-corpus first pass
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import asyncpg  # noqa: E402
import structlog  # noqa: E402

from services._batch_utils import cfg as _cfg  # noqa: E402
from services._batch_utils import load_apr_dict_async as _load_apr  # noqa: E402
from services.counterfactual_tracker import _DEFAULT_BOOTSTRAP_RANDOM_STATE  # noqa: E402,F401
from src.config.settings import Settings  # noqa: E402
from src.core.agent.base_batch import BaseBatch  # noqa: E402
from src.observability.corpus_manifest import CorpusManifest  # noqa: E402
from src.observability.otel import OTelInitError, init_otel_providers  # noqa: E402

_logger = structlog.get_logger(__name__)

# D-04: the only timeframe this phase measures.
_TF = "15m"

# D-01/D-02: ranked directly, never ensemble_alpha. A single feature, no composite score.
_FEATURE = "ctf_momentum"

# construction_spreads.construction_name — identifies this construction among future ones.
_CONSTRUCTION_NAME = "ctf_momentum_decile_ls"


def decile_legs(
    ranked_symbols: Sequence[str],
    feature_values: Sequence[float],
    decile_fraction: float,
) -> tuple[list[str], list[str]] | None:
    """Split a cross-section into a dollar-neutral (short_leg, long_leg) pair.

    Reproduces the T3 script's `_decile_spread_per_bar`/`_legs_per_bar` ranking mechanic
    exactly: `n_leg = max(1, round(n * decile_fraction))`, `None` returned when
    `n < 2 * n_leg` (too few symbols to form two disjoint legs). The T3 script ranks ascending
    via `sort_values(feature_col)`, so `iloc[:n_leg]` (the lowest feature values) is the SHORT
    leg and `iloc[-n_leg:]` (the highest) is the LONG leg — this function preserves that
    short-is-lowest / long-is-highest correspondence.

    Tie-break: symbols are sorted by `(feature_value, symbol)` ascending, not just
    `feature_value`. This is an intentional, RECORDED REPRODUCIBILITY DIVERGENCE from the T3
    script (design decision 2) — pandas `sort_values` on a single column leaves tie order
    dependent on input row order, which is fine for a one-off script but not for a persisted,
    reproducible table. The judgment that exact ties are effectively measure-zero rests on
    `ctf_momentum` being a continuous z-scored feature; it would need re-examination before this
    machinery ranks a discrete or heavily-quantized feature.

    A `None` or non-finite (NaN / +-inf) feature value raises `ValueError` naming the offending
    symbol rather than being sorted (design decision 5) — an unguarded sort on a NaN key is
    partition-dependent and non-transitive, silently producing a plausible-looking but arbitrary
    split.

    Raises:
        ValueError: if `len(ranked_symbols) != len(feature_values)`, or if any feature value is
            `None` or fails `math.isfinite`.

    Returns:
        `(short_leg, long_leg)` symbol lists, or `None` if the cross-section is too small to
        form two disjoint legs.
    """
    if len(ranked_symbols) != len(feature_values):
        raise ValueError(
            "ranked_symbols and feature_values must be the same length, got "
            f"{len(ranked_symbols)} and {len(feature_values)}"
        )

    for symbol, value in zip(ranked_symbols, feature_values, strict=True):
        if value is None or not math.isfinite(value):
            raise ValueError(
                f"feature value for symbol {symbol!r} is missing or non-finite: {value!r}"
            )

    n = len(ranked_symbols)
    n_leg = max(1, int(round(n * decile_fraction)))
    if n < 2 * n_leg:
        return None

    ranked = sorted(zip(feature_values, ranked_symbols, strict=True))
    short_leg = [symbol for _, symbol in ranked[:n_leg]]
    long_leg = [symbol for _, symbol in ranked[-n_leg:]]
    return short_leg, long_leg


def spread_from_legs(
    returns_by_symbol: Mapping[str, float | None],
    long_leg: Sequence[str],
    short_leg: Sequence[str],
) -> float | None:
    """Dollar-neutral flat equal-weight spread: mean(long returns) - mean(short returns).

    Symbols whose return is `None` (or absent from `returns_by_symbol`) are skipped, never
    coerced to `0.0` — a fabricated zero return would silently distort the leg mean. Returns
    `None` if either leg ends up with zero usable returns, never a spread computed against an
    empty leg.
    """
    long_returns = [r for s in long_leg if (r := returns_by_symbol.get(s)) is not None]
    short_returns = [r for s in short_leg if (r := returns_by_symbol.get(s)) is not None]
    if not long_returns or not short_returns:
        return None
    return (sum(long_returns) / len(long_returns)) - (sum(short_returns) / len(short_returns))


def one_way_turnover(
    prev_long: frozenset[str],
    prev_short: frozenset[str],
    cur_long: frozenset[str],
    cur_short: frozenset[str],
) -> float | None:
    """Mean one-way leg turnover between the prior bar's legs and the current bar's legs.

    Matches the T3 script's `_cost_hurdle_check` exactly: `n_leg = len(cur_long)` (the CURRENT
    universe size, never `len(prev_long)` — the universe can change bar to bar, and the script's
    choice is the one whose result was measured), `long_changed = len(cur_long - prev_long) /
    n_leg`, `short_changed = len(cur_short - prev_short) / n_leg`, returning their mean.

    Returns `None`, never `0.0`, when both `prev_long` and `prev_short` are empty (design
    decision 3) — that is the "no predecessor bar exists" case (the first bar of an incremental
    run), and RESEARCH.md Pitfall 4 names a turnover of exactly `0.0` at every run boundary as
    the symptom of a service that fakes this case as a legitimate zero-turnover bar. Also
    returns `None` if `cur_long` is empty (undefined denominator).
    """
    if not prev_long and not prev_short:
        return None
    n_leg = len(cur_long)
    if n_leg == 0:
        return None
    long_changed = len(cur_long - prev_long) / n_leg
    short_changed = len(cur_short - prev_short) / n_leg
    return (long_changed + short_changed) / 2


def net_spread_by_cost_bps(
    gross_spread: float | None,
    turnover: float | None,
    cost_bps: Sequence[int],
) -> dict[str, float] | None:
    """Todo-030 cost-hurdle sweep computed LIVE from realized turnover (D-05).

    Returns `{str(bps): gross_spread - (bps / 10000.0) * turnover for bps in cost_bps}`. Keys
    are `str(bps)` because this dict is persisted as `jsonb` and JSON object keys must be
    strings. This is computed fresh every run from the ACTUAL turnover this specific
    construction realized — never a cached "it survives" conclusion, and never reads the
    per-tf directional-trade cost-hurdle key (namespace `alpha.quant`, config key
    `cost_hurdle` + `.<tf>` suffix — RESEARCH.md Pitfall 5: that key belongs to a different
    mechanism with different cost dynamics).

    Returns `None` if either `gross_spread` or `turnover` is `None` — never a dict of
    zero-cost-adjusted values that would look like a real (and misleadingly favorable) result.
    """
    if gross_spread is None or turnover is None:
        return None
    return {str(bps): gross_spread - (bps / 10000.0) * turnover for bps in cost_bps}


def validate_construction_config(
    decile_fraction: float,
    cost_bps: Sequence[int],
    null_shuffles: int,
    attribution_max_static_r2: float,
) -> None:
    """Range-validate the construction's APR-bound parameters (T-167-01, ASVS V5).

    Raises `ValueError` naming the offending key and its observed value on any out-of-range
    input. Never clamps, never logs a warning and continues — CLAUDE.md: "silent wrong answers
    are worse than loud crashes."

    Raises:
        ValueError: if `decile_fraction` is not in `(0, 0.5]` (at exactly 0.5 the two legs
            consume the entire universe; above it they would overlap); if `cost_bps` is empty or
            contains any non-positive value; if `null_shuffles < 1`; if
            `attribution_max_static_r2` is not in the open interval `(0, 1)`.
    """
    if not (0 < decile_fraction <= 0.5):
        raise ValueError(f"decile_fraction must be in (0, 0.5], got {decile_fraction}")
    if not cost_bps:
        raise ValueError("cost_bps must not be empty")
    for bps in cost_bps:
        if bps <= 0:
            raise ValueError(f"cost_bps entries must all be positive, got {bps}")
    if null_shuffles < 1:
        raise ValueError(f"null_shuffles must be >= 1, got {null_shuffles}")
    if not (0 < attribution_max_static_r2 < 1):
        raise ValueError(
            "attribution_max_static_r2 must be in (0, 1), got " f"{attribution_max_static_r2}"
        )


# ---------------------------------------------------------------------------
# Panel query (reproduces the T3 script's `_FV_SQL`, scripts/analysis/
# t3_cross_sectional_long_short_ctf_momentum_check.py lines 63-78, exactly).
# ---------------------------------------------------------------------------
#
# Two fixed substitutions computed ONCE at import, never runtime interpolation of
# caller-supplied values (threat T-167-04): every filter value is bound as a $1/$2 asyncpg
# placeholder, never string-interpolated into the SQL text itself.
_PANEL_SQL_TEMPLATE = """
    SELECT fv.symbol, fv.bar_ts, fv.ctf_momentum,
           fr.return_fast, fr.return_slow
    FROM feature_vectors fv
    JOIN forward_returns fr
      ON fr.symbol = fv.symbol AND fr.tf = fv.tf AND fr.bar_ts = fv.bar_ts
    JOIN instruments i ON i.symbol = fv.symbol
    WHERE fv.tf = $1
      AND fv.ctf_momentum IS NOT NULL
      AND fr.return_type = 'executable_open_to_open'
      AND fr.complete_fast = true
      AND fr.complete_slow = true
      AND i.is_active = true
      AND i.contract_details->>'asset_class' = 'equity'
      {watermark_clause}
    ORDER BY fv.bar_ts ASC
"""

_PANEL_SQL_BACKFILL = _PANEL_SQL_TEMPLATE.format(watermark_clause="")
_PANEL_SQL_INCREMENTAL = _PANEL_SQL_TEMPLATE.format(watermark_clause="AND fv.bar_ts > $2")

_INSERT_SQL = """
    INSERT INTO construction_spreads (
        construction_name, tf, bar_ts, n_universe, n_leg,
        long_leg_symbols, short_leg_symbols,
        gross_spread_fast, gross_spread_slow,
        one_way_turnover,
        net_spread_fast_by_cost_bps, net_spread_slow_by_cost_bps,
        compute_version
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
    ON CONFLICT (construction_name, tf, bar_ts) DO NOTHING
"""


class CrossSectionalSpreadTracker(BaseBatch):
    """BaseBatch oneshot: incrementally scans the 15m equity panel, forms the decile spread
    at each bar via Plan 02's pure functions, computes turnover against the previous run's
    persisted leg membership, applies the live cost-hurdle sweep, and writes one
    `construction_spreads` row per bar. See the module docstring's MANUAL/ON-DEMAND ONLY and
    RECOVERY sections for the two load-bearing design decisions this class implements."""

    job_name = "cross-sectional-spread-tracker"
    compute_version = "1.0.0"

    def __init__(self, db_dsn: str, backfill: bool = False) -> None:
        super().__init__(db_dsn)
        self.backfill = backfill

    async def execute(self, pool: asyncpg.Pool) -> None:  # type: ignore[override]
        manifest = CorpusManifest(
            "cross_sectional_spread_tracker", CorpusManifest.DEFAULT_MANIFEST_DIR
        )
        try:
            await self._execute_inner(pool, manifest)
        except Exception as error:
            manifest.add_error(str(error))
            try:
                manifest.write()
            except Exception:
                pass
            raise
        else:
            manifest.mark_success()
            manifest_path = manifest.write()
            self.logger.info(
                "cross_sectional_spread_tracker.manifest_written",
                manifest_path=str(manifest_path),
            )

    async def _execute_inner(self, pool: asyncpg.Pool, manifest: CorpusManifest) -> None:
        async with pool.acquire() as conn:
            # (1) Load APR and validate BEFORE any panel work begins (T-167-01, ASVS V5).
            cfg_dict = await _load_apr(
                conn, extra_like_patterns=["infra.cross_sectional_spread_tracker.%"]
            )
            decile_fraction = _cfg(cfg_dict, "alpha.construction.decile_fraction", 0.10)
            null_shuffles = _cfg(cfg_dict, "alpha.construction.null_shuffles", 40)
            attribution_max_static_r2 = _cfg(
                cfg_dict, "alpha.construction.attribution_max_static_r2", 0.50
            )
            itersize = _cfg(cfg_dict, "infra.cross_sectional_spread_tracker.itersize", 5000)
            chunk_size = _cfg(cfg_dict, "infra.cross_sectional_spread_tracker.chunk_size", 5000)
            # json-typed key: cfg()'s type(default)(val) cast breaks on a list default, so this
            # one key is read raw and json.loads'd directly (migration 260's design decision 5).
            raw_cost_bps = cfg_dict.get("alpha.construction.cost_hurdle_bps_round_trip")
            cost_bps = json.loads(raw_cost_bps) if raw_cost_bps is not None else [1, 3, 5, 10]
            validate_construction_config(
                decile_fraction, cost_bps, null_shuffles, attribution_max_static_r2
            )

            # (2) Resolve the watermark. An empty table and an explicit --backfill are the
            # same work (design decisions block, step 2).
            if self.backfill:
                mode = "backfill"
                watermark = None
            else:
                watermark = await conn.fetchval(
                    "SELECT MAX(bar_ts) FROM construction_spreads "
                    "WHERE construction_name = $1 AND tf = $2",
                    _CONSTRUCTION_NAME,
                    _TF,
                )
                mode = "incremental" if watermark is not None else "backfill"

            if mode == "backfill":
                panel_sql = _PANEL_SQL_BACKFILL
                panel_params: tuple[Any, ...] = (_TF,)
            else:
                panel_sql = _PANEL_SQL_INCREMENTAL
                panel_params = (_TF, watermark)

            self.logger.info(
                "cross_sectional_spread_tracker.mode_resolved",
                mode=mode,
                watermark=str(watermark) if watermark is not None else None,
            )

            # (3) Seed prior legs from committed state only (design decision 5 / RESEARCH.md
            # Pattern 2 / Pitfall 4) -- this single query is what makes crash recovery correct.
            prior_row = await conn.fetchrow(
                "SELECT bar_ts, long_leg_symbols, short_leg_symbols FROM construction_spreads "
                "WHERE construction_name = $1 AND tf = $2 ORDER BY bar_ts DESC LIMIT 1",
                _CONSTRUCTION_NAME,
                _TF,
            )
            prior_long: frozenset[str]
            prior_short: frozenset[str]
            if prior_row is None:
                prior_long = frozenset()
                prior_short = frozenset()
                prior_leg_seed_bar_ts = None
                self.logger.info(
                    "cross_sectional_spread_tracker.prior_legs_seeded",
                    source="empty_table",
                    bar_ts=None,
                )
            else:
                prior_long = frozenset(prior_row["long_leg_symbols"])
                prior_short = frozenset(prior_row["short_leg_symbols"])
                prior_leg_seed_bar_ts = prior_row["bar_ts"]
                self.logger.info(
                    "cross_sectional_spread_tracker.prior_legs_seeded",
                    source="persisted_row",
                    bar_ts=str(prior_leg_seed_bar_ts),
                )

            n_panel_rows = 0
            n_bars_processed = 0
            n_bars_skipped_degenerate = 0
            turnovers: list[float] = []
            write_buffer: list[tuple[Any, ...]] = []
            n_written = 0

            async def flush_write_buffer() -> None:
                nonlocal n_written
                if not write_buffer:
                    return
                async with pool.acquire() as wconn:
                    await wconn.executemany(_INSERT_SQL, write_buffer)
                n_written += len(write_buffer)
                write_buffer.clear()

            def process_bar(bar_ts: Any, rows: list[dict[str, Any]]) -> None:
                nonlocal prior_long, prior_short, n_bars_processed, n_bars_skipped_degenerate
                symbols = [r["symbol"] for r in rows]
                feature_values = [r["ctf_momentum"] for r in rows]
                legs = decile_legs(symbols, feature_values, decile_fraction)
                if legs is None:
                    # Too few symbols to form two disjoint legs -- skip the bar entirely,
                    # matching the T3 script's `continue` (design decisions, step 4). Never
                    # logged per-bar (CLAUDE.md: never log per-row inside a loop over the full
                    # corpus) -- counted and reported once at the end of the run.
                    n_bars_skipped_degenerate += 1
                    return
                short_leg, long_leg = legs
                cur_long = frozenset(long_leg)
                cur_short = frozenset(short_leg)
                returns_fast = {r["symbol"]: r["return_fast"] for r in rows}
                returns_slow = {r["symbol"]: r["return_slow"] for r in rows}
                gross_fast = spread_from_legs(returns_fast, long_leg, short_leg)
                gross_slow = spread_from_legs(returns_slow, long_leg, short_leg)
                turnover = one_way_turnover(prior_long, prior_short, cur_long, cur_short)
                net_fast = net_spread_by_cost_bps(gross_fast, turnover, cost_bps)
                net_slow = net_spread_by_cost_bps(gross_slow, turnover, cost_bps)
                write_buffer.append(
                    (
                        _CONSTRUCTION_NAME,
                        _TF,
                        bar_ts,
                        len(symbols),
                        len(long_leg),
                        long_leg,
                        short_leg,
                        gross_fast,
                        gross_slow,
                        turnover,
                        net_fast,
                        net_slow,
                        self.compute_version,
                    )
                )
                if turnover is not None:
                    turnovers.append(turnover)
                n_bars_processed += 1
                prior_long, prior_short = cur_long, cur_short

            # (4) Stream the panel via a server-side cursor -- peak memory stays independent
            # of corpus size (design decision 2). Accumulate the current bar's rows into a
            # small buffer; flush a completed bar the moment bar_ts changes.
            current_bar_ts: Any = None
            current_rows: list[dict[str, Any]] = []

            async with conn.transaction():
                async for record in conn.cursor(panel_sql, *panel_params, prefetch=itersize):
                    n_panel_rows += 1
                    row = dict(record)
                    if current_bar_ts is None:
                        current_bar_ts = row["bar_ts"]
                    if row["bar_ts"] != current_bar_ts:
                        process_bar(current_bar_ts, current_rows)
                        # (5) Persist in chunks, in bar_ts order -- bounds each transaction so
                        # a crash can only ever truncate a contiguous TAIL (design decision 5).
                        if len(write_buffer) >= chunk_size:
                            await flush_write_buffer()
                        current_bar_ts = row["bar_ts"]
                        current_rows = []
                    current_rows.append(row)

                # Never forget to flush the final bar after the cursor is exhausted.
                if current_rows:
                    process_bar(current_bar_ts, current_rows)

            await flush_write_buffer()

            # (6) Report. One summary log line, never per-bar.
            turnover_mean = statistics.fmean(turnovers) if turnovers else None
            turnover_median = statistics.median(turnovers) if turnovers else None
            manifest.set_inputs(
                mode=mode,
                watermark=str(watermark) if watermark is not None else None,
                prior_leg_seed_bar_ts=(
                    str(prior_leg_seed_bar_ts) if prior_leg_seed_bar_ts is not None else None
                ),
                n_panel_rows=n_panel_rows,
                n_bars_processed=n_bars_processed,
                n_bars_skipped_degenerate=n_bars_skipped_degenerate,
                turnover_mean=turnover_mean,
                turnover_median=turnover_median,
            )
            manifest.add_output(table_name="construction_spreads", rows_total=n_written)
            if n_bars_skipped_degenerate > 0:
                # design decision 6: a non-zero degenerate-skip count must be visible in the
                # manifest's status, not only in a log line that rotates away.
                manifest.add_warning(
                    f"{n_bars_skipped_degenerate} bar(s) skipped: too few symbols to form two "
                    "disjoint decile legs"
                )
            self.logger.info(
                "cross_sectional_spread_tracker.run_complete",
                mode=mode,
                n_panel_rows=n_panel_rows,
                n_bars_processed=n_bars_processed,
                n_bars_skipped_degenerate=n_bars_skipped_degenerate,
                n_written=n_written,
                turnover_mean=turnover_mean,
                turnover_median=turnover_median,
            )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Cross-Sectional Spread Tracker -- builds the T3 dollar-neutral decile "
            "long-short construction (D-03/D-04)"
        )
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help=(
            "Process the full 2006-2026 corpus in one pass. Correct only for the first run "
            "or immediately after a construction_spreads truncate -- incremental mode is the "
            "correct choice for every subsequent invocation."
        ),
    )
    args = parser.parse_args()

    try:
        init_otel_providers("indicagent-cross-sectional-spread-tracker")
    except OTelInitError as error:
        _logger.warning("cross_sectional_spread_tracker.otel_init_failed", error=str(error))

    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")

    asyncio.run(CrossSectionalSpreadTracker(db_dsn, backfill=args.backfill).run())
