#!/usr/bin/env python3
"""
ops_lookahead_horizon_response.py -- Q1 (todo 091/097 follow-up) horizon-response
diagnostic: how does forward-return coverage and IC actually behave across a dense,
session-feasible per-tf horizon grid, instead of the four fixed 1/5/20/60-bar
`[initial_estimate]` lookahead points production uses today?

Design: Fable 5's 2026-07-19 review
(docs/research/fable-2026-07-19-lookahead-and-target-calibration-review.md), Q1(c)
Step 1. That review found the uniform 1/5/20/60-bar grid (identical bar counts on
every tf, never scaled per-tf the way _tf_window() scales day-denominated window
params) structurally amputates the design grid on intraday tfs: 1h slow/extended and
15m extended have ZERO forward-return rows (the intraday same-ET-session completeness
gate, a deliberate and correct Invariant-1 constraint, has nothing left to measure at
those horizons), and 5m extended silently measures only first-~90-minutes bars (a
morning-entry selection bias with no downstream signal that it happened). This script
is the empirical instrument to replace those four guessed bar-counts with a real
IC-decay curve per tf, dense enough to show where coverage collapses and whether IC is
still rising or already flat at the session boundary.

Read-only, no persistence. Computes forward returns itself via the SAME LEAD()-based
construction and same-ET-session completeness gate as
forward_return_writer._build_forward_return_sql (deliberately re-derived here rather
than imported, since that function's column-naming is hard-coupled to the fixed
fast/mid/slow/extended forward_returns schema -- this script needs an arbitrary
per-tf grid of raw bar counts). Reads from market_data_ohlcv_tradeable (the
CLAUDE.md-mandated volume>0 view for measurement reads), not the raw table.

Deliberately NOT regime-stratified (a difference from Fable's suggested design):
horizon-response is a property of the return-generating process and the session-
completeness gate at a given tf, not a regime-conditional question -- pooling every
regime maximizes power for what is otherwise a small, thin diagnostic sample. Component
F's regime-conditional question is a separate, already-built script
(ops_vol_normalized_target_ab.py).

IC magnitude and CI width are reported as SEPARATE columns (median |IC| across all
`_FEATURE_NAMES`, and median Fisher-z CI half-width across the same features) so power
(N, hence CI width) and signal (IC magnitude) are never conflated when reading the
curve -- exactly Fable's stated requirement. Fisher-z (not bootstrap) is used
deliberately: this is a cheap, non-gating, one-shot diagnostic script (not a second
corpus-wide re-run), and todo 091 already established Fisher-z is directionally usable
even where its exact width is imperfect for some autocorrelation-heavy features -- a
diagnostic curve does not need the same rigor as a promotion gate.

No production writes, no config_state changes. Exit code always 0 -- informational,
matching ops_ic_null_calibration.py's house style.

Usage:
    python scripts/ops/alpha/ops_lookahead_horizon_response.py
    python scripts/ops/alpha/ops_lookahead_horizon_response.py --tf 1h
    python scripts/ops/alpha/ops_lookahead_horizon_response.py --max-symbols 20
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import asyncpg
import numpy as np
from scipy.stats import rankdata

from services.ic_engine import _FEATURE_NAMES
from src.config.settings import Settings
from src.intelligence.statistics.ic_math import _fisher_z_ci, _vectorized_ic

# Per-tf dense horizon grid, denominated in session-feasible bar counts (Fable 5
# Q1c Step 1). Bars-per-session: 5m=78, 15m=26, 1h=7 (from
# src/intelligence/regime_signals/tf_window.py's _BARS_PER_DAY, the project's own
# existing per-tf bar-count constant). 1d has no session boundary.
_HORIZON_GRIDS: dict[str, tuple[int, ...]] = {
    "5m": (1, 3, 6, 12, 26, 39, 66),
    "15m": (1, 2, 5, 10, 22),
    "1h": (1, 2, 4, 6),
    "1d": (1, 2, 5, 10, 20, 40, 60, 90),
}
_TFS = ("5m", "15m", "1h", "1d")
_DEFAULT_MAX_SYMBOLS = 30
_MIN_RELIABLE_N_DEFAULT = 100

_LATEST_VINTAGE_SQL = "SELECT max(training_window_end) FROM feature_ic_scores"
_SYMBOLS_SQL = """
    SELECT DISTINCT symbol FROM feature_vectors WHERE tf = $1 ORDER BY symbol LIMIT $2
"""


def _build_horizon_response_sql(horizons: tuple[int, ...], tf: str) -> str:
    """LEAD()-based SQL computing forward log-returns at an arbitrary set of raw bar
    counts, generalizing forward_return_writer._build_forward_return_sql (which is
    hard-coupled to the fixed fast/mid/slow/extended schema) for a dense diagnostic
    grid. Same ROWS BETWEEN explicit frame (avoids default range-frame tie semantics,
    RESEARCH.md F8), same same-ET-session completeness gate for intraday tfs, no
    session gate for 1d. Column names are h{n} (n = raw bar count), not scale names.
    """
    max_n = max(horizons)
    frame_size = max_n + 1
    is_intraday = tf in ("5m", "15m", "1h")

    lead_col_list = [f"LEAD(m.open, {n + 1}) OVER w AS open_h{n}" for n in horizons]
    lead_cols = ",\n        ".join(lead_col_list)
    lead_t1 = "LEAD(m.open, 1) OVER w AS open_entry"

    return_col_list = [
        f"CASE WHEN open_entry > 0 AND open_h{n} > 0 "
        f"THEN ln(open_h{n} / open_entry) END AS return_h{n}"
        for n in horizons
    ]
    return_cols = ",\n    ".join(return_col_list)

    if is_intraday:
        fwd_ts_col_list = [f"LEAD(m.timestamp, {n + 1}) OVER w AS fwd_ts_h{n}" for n in horizons]
        fwd_ts_cols = ",\n        ".join(fwd_ts_col_list)
        fwd_ts_select = f",\n        {fwd_ts_cols}"
        complete_col_list = [
            f"(\n        open_h{n} IS NOT NULL\n"
            f"        AND (fwd_ts_h{n} AT TIME ZONE 'America/New_York')::date\n"
            f"            = (bar_ts AT TIME ZONE 'America/New_York')::date\n"
            f"    ) AS complete_h{n}"
            for n in horizons
        ]
    else:
        fwd_ts_select = ""
        complete_col_list = [f"(open_h{n} IS NOT NULL) AS complete_h{n}" for n in horizons]

    complete_cols = ",\n    ".join(complete_col_list)

    return f"""
WITH windowed AS (
    SELECT
        m.timestamp                            AS bar_ts,
        m.symbol,
        {lead_t1},
        {lead_cols}{fwd_ts_select}
    FROM market_data_ohlcv_tradeable m
    WHERE m.symbol    = $1
      AND m.timeframe  = $2
      AND m.timestamp <= $3
    WINDOW w AS (
        PARTITION BY m.symbol
        ORDER BY m.timestamp
        ROWS BETWEEN CURRENT ROW AND {frame_size} FOLLOWING
    )
)
SELECT bar_ts, symbol, {return_cols}, {complete_cols}
FROM windowed
ORDER BY bar_ts
"""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tf", choices=_TFS, default=None, help="Restrict to one timeframe (default: all 4)."
    )
    parser.add_argument("--max-symbols", type=int, default=_DEFAULT_MAX_SYMBOLS)
    parser.add_argument("--min-reliable-n", type=int, default=None)
    return parser.parse_args()


async def _load_config_int(pool: asyncpg.Pool, key: str, default: int) -> int:
    row = await pool.fetchval("SELECT config_value FROM config_state WHERE config_key = $1", key)
    return int(row) if row is not None else default


async def _fetch_horizon_response_rows(
    pool: asyncpg.Pool, tf: str, symbol: str, vintage, horizons: tuple[int, ...]
) -> list[asyncpg.Record]:
    sql = _build_horizon_response_sql(horizons, tf)
    return await pool.fetch(sql, symbol, tf, vintage)


async def main() -> int:
    args = _parse_args()
    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)

    try:
        vintage = await pool.fetchval(_LATEST_VINTAGE_SQL)
        if vintage is None:
            print("ERROR: feature_ic_scores is empty -- no vintage to anchor the sample.")
            return 0
        min_reliable_n = args.min_reliable_n or await _load_config_int(
            pool, "alpha.ic.min_reliable_n", _MIN_RELIABLE_N_DEFAULT
        )

        tfs = (args.tf,) if args.tf else _TFS

        print("# Lookahead Horizon-Response Diagnostic\n")
        print(
            f"vintage: {vintage}, max_symbols={args.max_symbols}, "
            f"min_reliable_n={min_reliable_n}\n"
        )
        print(
            "Pooled across ALL regimes (not regime-stratified -- see module docstring). "
            "completeness = share of bars with a valid same-session forward return at "
            "that horizon. median_abs_ic / median_ci_halfwidth are medians across all "
            f"{len(_FEATURE_NAMES)} features -- read them together, not the magnitude "
            "alone: a rising median_abs_ic with a widening CI is consistent with pure "
            "noise, not real signal growth.\n"
        )

        feature_cols_sql = ", ".join(f'"{f}"' for f in _FEATURE_NAMES)
        for tf in tfs:
            horizons = _HORIZON_GRIDS[tf]
            symbol_rows = await pool.fetch(_SYMBOLS_SQL, tf, args.max_symbols)
            symbols = [r["symbol"] for r in symbol_rows]
            if not symbols:
                print(f"WARNING: no symbols found for tf={tf}")
                continue

            # Pool bar_ts+return_h{n}+complete_h{n} across symbols.
            per_horizon_returns: dict[int, list[float]] = {n: [] for n in horizons}
            per_horizon_complete: dict[int, list[bool]] = {n: [] for n in horizons}
            per_horizon_keys: dict[int, list[tuple]] = {n: [] for n in horizons}
            n_bars_total = 0

            for symbol in symbols:
                rows = await _fetch_horizon_response_rows(pool, tf, symbol, vintage, horizons)
                n_bars_total += len(rows)
                for r in rows:
                    for n in horizons:
                        per_horizon_returns[n].append(r[f"return_h{n}"])
                        per_horizon_complete[n].append(r[f"complete_h{n}"])
                        per_horizon_keys[n].append((r["bar_ts"], symbol))

            # Fetch feature_vectors ONCE per tf (not once per horizon -- the prior
            # version re-fetched and re-parsed up to 8x per tf, dominating runtime) and
            # build one X matrix + (bar_ts, symbol) -> row-index map, reused by every
            # horizon below.
            fv_rows = await pool.fetch(
                f"""
                SELECT bar_ts, symbol, {feature_cols_sql}
                FROM feature_vectors
                WHERE tf = $1 AND bar_ts <= $2 AND symbol = ANY($3::text[])
                """,
                tf,
                vintage,
                symbols,
            )
            fv_index: dict[tuple, int] = {}
            X_all = np.empty((len(fv_rows), len(_FEATURE_NAMES)), dtype=np.float64)
            for i, r in enumerate(fv_rows):
                fv_index[(r["bar_ts"], r["symbol"])] = i
                X_all[i] = [r[f] for f in _FEATURE_NAMES]

            print(
                f"## tf={tf} ({len(symbols)} symbols, {n_bars_total} bars fetched, "
                f"{len(fv_rows)} feature_vectors rows indexed)\n"
            )
            print(
                "| horizon_bars | completeness | n_valid | median_abs_ic | " "median_ci_halfwidth |"
            )
            print("|---|---|---|---|---|")

            for n in horizons:
                complete_arr = np.array(per_horizon_complete[n], dtype=bool)
                completeness = float(complete_arr.mean()) if len(complete_arr) else 0.0
                if not complete_arr.any():
                    print(f"| {n} | {completeness:.3f} | 0 | n/a | n/a |")
                    continue

                keys_valid = [k for k, c in zip(per_horizon_keys[n], complete_arr) if c]
                returns_valid = [v for v, c in zip(per_horizon_returns[n], complete_arr) if c]

                row_idx: list[int] = []
                y_valid: list[float] = []
                for key, ret in zip(keys_valid, returns_valid):
                    idx = fv_index.get(key)
                    if idx is None or ret is None:
                        continue
                    row_idx.append(idx)
                    y_valid.append(ret)

                n_valid = len(y_valid)
                if n_valid < min_reliable_n:
                    print(f"| {n} | {completeness:.3f} | {n_valid} | below floor | below floor |")
                    continue

                X = X_all[row_idx]
                Y = np.array(y_valid, dtype=np.float64)
                ranks_X = rankdata(X, axis=0)
                ranks_Y = rankdata(Y)
                ic_vec = _vectorized_ic(ranks_X, ranks_Y)
                ci_lower, ci_upper = _fisher_z_ci(ic_vec, n_valid)

                finite_ic = ic_vec[np.isfinite(ic_vec)]
                halfwidths = (ci_upper - ci_lower) / 2.0
                finite_hw = halfwidths[np.isfinite(halfwidths)]
                median_abs_ic = (
                    float(np.median(np.abs(finite_ic))) if len(finite_ic) else float("nan")
                )
                median_hw = float(np.median(finite_hw)) if len(finite_hw) else float("nan")

                print(
                    f"| {n} | {completeness:.3f} | {n_valid} | {median_abs_ic:.4f} | "
                    f"{median_hw:.4f} |"
                )
            print()

        print(
            "---\nThis is a bounded diagnostic (--max-symbols caps cost). completeness=0.000 "
            "means the same-ET-session completeness gate leaves zero rows at that horizon on "
            "this tf -- a structural ceiling, not a sample-size artifact. Use the curve to "
            "decide per-tf fast/mid/slow/extended grids where completeness/CI-width are still "
            "reasonable, per docs/research/fable-2026-07-19-lookahead-and-target-calibration-"
            "review.md Q1(c)."
        )
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
