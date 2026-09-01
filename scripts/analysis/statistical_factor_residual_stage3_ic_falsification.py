#!/usr/bin/env python3
"""Stage 3 (IC falsification) for statistical_factor_residual. Pre-registered design:
docs/research/measurement-statistical-factor-residual.md. Design locked in this docstring
BEFORE any IC number is computed (same discipline as Stages 1-2) -- decisions below were
made from the schema/precedent alone, not from a peek at the result.

Question: does ctf_momentum computed on the residual return series (Stage 2's walk-forward
PCA residual) show a materially higher IC than the same statistic computed on raw returns,
against the bar of raw per-symbol IC + existing pooled/cross-sectional IC?

Design decisions locked before running:

1. ctf_momentum reconstruction. Per feature_factory.py's own documented equivalence
   (ctf_higher_tf_map: "1d" -> "1d", "ctf_momentum degenerates into a same-tf RSI oscillator"
   at the daily tf, todo 189) -- exactly Stage 2's tf -- ctf_momentum at 1d already IS a
   same-timeframe Wilder RSI, normalized (RSI-50)/50. No invented mechanic needed: reuse
   `_wilder_rsi_series` (src/intelligence/feature_cache.py), the SAME production primitive
   backfill_feature_factory.py calls, on a synthetic log-price built by cumsum-ing each
   return series (raw or residual) -- diff(cumsum(x)) == x exactly, so this reproduces
   RSI's up/down-move split with zero information loss vs. feeding it real closes.

2. Comparison bar. `feature_ic_scores` for (ctf_momentum, tf=1d) holds 117 POOLED rows alone
   across mixed regime/window/lookahead cells (checked live) -- no single "the" baseline
   number exists without an arbitrary cell pick, which would itself be an undisciplined
   researcher-degree-of-freedom. Primary comparison is instead a LOCALLY, IDENTICALLY
   recomputed raw ctf_momentum (same script, same universe, same dates, same RSI primitive,
   same lookahead) vs. the residual version -- true apples-to-apples, zero cell-selection
   freedom. The historical feature_ic_scores POOLED numbers are printed for context only,
   never used as the pass/fail bar.

3. Lookahead / return target. `return_mid` (APR alpha.ic.lookahead.mid=5 trading days),
   tf=1d, return_type='executable_open_to_open' (Invariant 1), complete_mid=true only.

4. Three measurement axes, matching the design doc's "raw per-symbol IC and existing
   pooled/cross-sectional IC" bar exactly:
   - per-symbol: time-series Spearman IC within each symbol in the universe
   - pooled: all (symbol, day) pairs pooled into one vector, correlated directly
     (matches feature_ic_scores' is_pooled=true, regime_scope='pooled')
   - cross_sectional: same-day rank of momentum vs. same-day rank of forward return,
     pooled across days (matches regime_scope='cross_sectional')
   Day-clustered circular block bootstrap CI (ic_math._circular_block_bootstrap_ic,
   block_size=10 from APR alpha.ic.bootstrap_block_size.1d) on every cell. BH-FDR
   (ic_math.apply_bh_fdr) applied within the per-symbol family only -- pooled
   and cross_sectional are single cells each, not part of that family, same convention
   feature_ic_scores itself uses (separate regime_scope rows, not FDR-corrected against
   each other).

5. Warmup asymmetry (stated, not hidden, and biased AGAINST the residual clearing the
   bar): raw RSI gets the synthetic price's full pre-existing history for its Wilder
   warmup (no cold-start artifact). Residual RSI can only start at Stage 2's first
   walk-forward boundary (day 252) -- it must cold-start its OWN period+1-bar warmup
   there, and those cold-start bars (flat RSI=50.0, per _wilder_rsi_series's documented
   convention) are dropped before IC is computed, not treated as real signal. Both series
   are then trimmed to the exact same (symbol, date) index before any IC computation, so
   every comparison is on identical dates -- this costs the residual side extra history
   the raw side keeps, which can only work against finding a residual edge, never for it.

Verdict rule (pre-registered): if no measurement axis shows the residual's CI clearing
zero with an IC materially larger than the raw axis's own IC on the identical dates,
statistical_factor_residual is dead -- consistent with Stage 3's original framing in the
design doc.

Read-only: reads market_data_ohlcv_tradeable, forward_returns, config_state (via ConfigService),
and feature_ic_scores (context only). No writes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import rankdata  # noqa: E402

from services._batch_utils import cfg as _cfg  # noqa: E402
from services._batch_utils import load_config_service_sync  # noqa: E402
from services.backfill_feature_factory import _connect_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.intelligence.feature_cache import _wilder_rsi_series  # noqa: E402
from src.intelligence.statistics.ic_math import (  # noqa: E402
    _circular_block_bootstrap_ic,
    _p_values_from_ic,
    apply_bh_fdr,
)

# Reuse Stage 2's exact universe/window/walk-forward construction -- no reimplementation.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from statistical_factor_residual_stage2_causal_fit import (  # noqa: E402
    _INITIAL_WARMUP_BARS,
    _fetch_universe,
    walk_forward_residuals,
)

_TF = "1d"
_RETURN_COL = "return_mid"
_COMPLETE_COL = "complete_mid"
_FDR_ALPHA = 0.05


def _synthetic_log_price(log_returns: pd.Series) -> np.ndarray:
    """cumsum of log returns -- diff() reproduces the input exactly, so
    _wilder_rsi_series computed on this array reflects the return series with zero
    information loss (see design decision 1 above)."""
    return np.concatenate(([0.0], np.cumsum(log_returns.to_numpy())))


def _ctf_momentum(log_price: np.ndarray, period: int) -> np.ndarray:
    """Wilder RSI normalized to [-1, +1], the production ctf_momentum formula
    (backfill_feature_factory.py's _build_ctf_series, same-tf case). log_price has one
    more element than the return series it derives from (leading 0.0); slice [1:] to
    re-align with the return-series index."""
    rsi = _wilder_rsi_series(log_price, period)
    return np.clip((rsi[1:] - 50.0) / 50.0, -1.0, 1.0)


def _fetch_forward_returns(conn, symbols: list[str]) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT symbol, bar_ts, {_RETURN_COL}
            FROM forward_returns
            WHERE tf = %s AND return_type = 'executable_open_to_open'
              AND {_COMPLETE_COL} = true AND symbol = ANY(%s)
            """,
            (_TF, symbols),
        )
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["symbol", "bar_ts", "fwd_ret"])
    df["date"] = pd.to_datetime(df["bar_ts"], utc=True).dt.date
    return df.drop(columns=["bar_ts"])


def _bootstrap_cell(
    x: np.ndarray, y: np.ndarray, block_size: int, n_boot: int, rng: np.random.Generator
) -> dict:
    point_ic = float(np.corrcoef(rankdata(x), rankdata(y))[0, 1])
    ci_lo, ci_hi = _circular_block_bootstrap_ic(
        x.reshape(-1, 1), y, block_size, n_boot, rng, max_workers=1
    )
    p_val = float(_p_values_from_ic(np.array([point_ic]), n=len(x))[0])
    return {
        "ic": point_ic,
        "ci_lower": float(ci_lo[0]),
        "ci_upper": float(ci_hi[0]),
        "n": len(x),
        "p_value": p_val,
        "crosses_zero": bool(ci_lo[0] <= 0.0 <= ci_hi[0]),
    }


def _print_context_baseline(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT regime_scope, count(*), avg(ic_value), avg(ic_ci_lower), avg(ic_ci_upper)
            FROM feature_ic_scores
            WHERE feature_name = 'ctf_momentum' AND tf = %s AND symbol = 'POOLED'
              AND training_window_end = (
                  SELECT max(training_window_end) FROM feature_ic_scores
                  WHERE feature_name = 'ctf_momentum' AND tf = %s
              )
            GROUP BY regime_scope
            """,
            (_TF, _TF),
        )
        rows = cur.fetchall()
    print(
        "Context only (NOT the pass/fail bar -- see design decision 2): "
        "historical feature_ic_scores POOLED rows, ctf_momentum, tf=1d, latest window"
    )
    for regime_scope, n, avg_ic, avg_lo, avg_hi in rows:
        print(
            f"  regime_scope={regime_scope}: n_cells={n} avg_ic={avg_ic:.4f} "
            f"avg_ci=[{avg_lo:.4f}, {avg_hi:.4f}]"
        )
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--n-boot",
        type=int,
        default=None,
        help="Override APR alpha.ic.bootstrap_resamples (smoke-testing only; the "
        "recorded result must use the APR default, not an ad hoc override).",
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    settings = Settings()
    conn = _connect_db(settings)
    apr = load_config_service_sync(conn)
    apr_dict = apr._cache
    period = int(_cfg(apr_dict, "feature.period.rsi.mid", 14))
    block_size = int(_cfg(apr_dict, f"alpha.ic.bootstrap_block_size.{_TF}", 10))
    min_reliable_n = int(_cfg(apr_dict, "alpha.ic.min_reliable_n", 100))
    n_boot = (
        args.n_boot
        if args.n_boot is not None
        else int(_cfg(apr_dict, "alpha.ic.bootstrap_resamples", 2000))
    )
    rng = np.random.default_rng(args.seed)

    print(f"Stage 3 (IC falsification) -- ctf_momentum, tf={_TF}, lookahead=mid (return_mid)")
    print(
        f"period={period} block_size={block_size} n_boot={n_boot} min_reliable_n={min_reliable_n}\n"
    )

    _print_context_baseline(conn)

    returns = _fetch_universe(conn)
    symbols = list(returns.columns)
    print(f"Universe: {len(symbols)} symbols, {returns.shape[0]} days (Stage 2's exact fetch)")

    residual_df, segments = walk_forward_residuals(returns)
    print(f"Walk-forward: {len(segments)} refit segments, first boundary={_INITIAL_WARMUP_BARS}\n")

    fwd = _fetch_forward_returns(conn, symbols)
    fwd_by_symbol = {sym: g.set_index("date")["fwd_ret"] for sym, g in fwd.groupby("symbol")}

    dates = returns.index  # date objects, aligned to returns' row index
    raw_momentum: dict[str, pd.Series] = {}
    resid_momentum: dict[str, pd.Series] = {}

    for sym in symbols:
        raw_log_price = _synthetic_log_price(returns[sym])
        raw_rsi = _ctf_momentum(raw_log_price, period)
        raw_series = pd.Series(raw_rsi, index=dates)

        resid_ret = residual_df[sym].iloc[_INITIAL_WARMUP_BARS:]
        resid_log_price = _synthetic_log_price(resid_ret)
        resid_rsi = _ctf_momentum(resid_log_price, period)
        resid_series = pd.Series(resid_rsi, index=resid_ret.index).iloc[period:]

        raw_momentum[sym] = raw_series
        resid_momentum[sym] = resid_series

    # Build the three measurement axes for both raw and residual, on IDENTICAL
    # (symbol, date) pairs per symbol (design decision 5).
    per_symbol_raw: dict[str, dict] = {}
    per_symbol_resid: dict[str, dict] = {}
    pooled_x_raw, pooled_x_resid, pooled_y = [], [], []
    cs_rows: list[tuple] = []  # (date, symbol, raw_mom, resid_mom, fwd_ret)

    for sym in symbols:
        fwd_sym = fwd_by_symbol.get(sym)
        if fwd_sym is None:
            continue
        common_dates = resid_momentum[sym].index.intersection(raw_momentum[sym].index)
        common_dates = common_dates.intersection(fwd_sym.index)
        if len(common_dates) < min_reliable_n:
            continue
        raw_vals = raw_momentum[sym].loc[common_dates].to_numpy()
        resid_vals = resid_momentum[sym].loc[common_dates].to_numpy()
        fwd_vals = fwd_sym.loc[common_dates].to_numpy()

        per_symbol_raw[sym] = _bootstrap_cell(raw_vals, fwd_vals, block_size, n_boot, rng)
        per_symbol_resid[sym] = _bootstrap_cell(resid_vals, fwd_vals, block_size, n_boot, rng)

        pooled_x_raw.append(raw_vals)
        pooled_x_resid.append(resid_vals)
        pooled_y.append(fwd_vals)
        for d, r, rr, f in zip(common_dates, raw_vals, resid_vals, fwd_vals, strict=True):
            cs_rows.append((d, sym, r, rr, f))

    n_symbols_tested = len(per_symbol_raw)
    print(
        f"Symbols with sufficient aligned history (n >= {min_reliable_n}): {n_symbols_tested}/{len(symbols)}\n"
    )

    # Per-symbol FDR family
    raw_pvals = [per_symbol_raw[s]["p_value"] for s in per_symbol_raw]
    resid_pvals = [per_symbol_resid[s]["p_value"] for s in per_symbol_resid]
    raw_reject, raw_padj = apply_bh_fdr(raw_pvals, _FDR_ALPHA)
    resid_reject, resid_padj = apply_bh_fdr(resid_pvals, _FDR_ALPHA)

    print("=== Per-symbol axis ===")
    print(f"{'symbol':8s} {'raw_ic':>9s} {'raw_fdr':>8s} {'resid_ic':>9s} {'resid_fdr':>9s}")
    for i, sym in enumerate(per_symbol_raw):
        r = per_symbol_raw[sym]
        rr = per_symbol_resid[sym]
        print(
            f"{sym:8s} {r['ic']:9.4f} {'PASS' if raw_reject[i] else 'fail':>8s} "
            f"{rr['ic']:9.4f} {'PASS' if resid_reject[i] else 'fail':>9s}"
        )
    n_raw_pass = int(raw_reject.sum())
    n_resid_pass = int(resid_reject.sum())
    median_raw_ic = float(np.median([per_symbol_raw[s]["ic"] for s in per_symbol_raw]))
    median_resid_ic = float(np.median([per_symbol_resid[s]["ic"] for s in per_symbol_resid]))
    print(
        f"\nPer-symbol summary: raw {n_raw_pass}/{n_symbols_tested} pass BH-FDR "
        f"(median IC={median_raw_ic:.4f}), residual {n_resid_pass}/{n_symbols_tested} "
        f"pass BH-FDR (median IC={median_resid_ic:.4f})\n"
    )

    # Pooled axis
    pooled_x_raw_arr = np.concatenate(pooled_x_raw)
    pooled_x_resid_arr = np.concatenate(pooled_x_resid)
    pooled_y_arr = np.concatenate(pooled_y)
    pooled_raw = _bootstrap_cell(pooled_x_raw_arr, pooled_y_arr, block_size, n_boot, rng)
    pooled_resid = _bootstrap_cell(pooled_x_resid_arr, pooled_y_arr, block_size, n_boot, rng)
    print("=== Pooled axis (all symbol-day pairs pooled) ===")
    print(
        f"raw:      ic={pooled_raw['ic']:.4f} ci=[{pooled_raw['ci_lower']:.4f}, "
        f"{pooled_raw['ci_upper']:.4f}] n={pooled_raw['n']} "
        f"{'CI crosses zero' if pooled_raw['crosses_zero'] else 'CI EXCLUDES ZERO'}"
    )
    print(
        f"residual: ic={pooled_resid['ic']:.4f} ci=[{pooled_resid['ci_lower']:.4f}, "
        f"{pooled_resid['ci_upper']:.4f}] n={pooled_resid['n']} "
        f"{'CI crosses zero' if pooled_resid['crosses_zero'] else 'CI EXCLUDES ZERO'}\n"
    )

    # Cross-sectional axis: same-day rank of momentum vs same-day rank of forward return,
    # pooled across days with day-block bootstrap.
    cs_df = pd.DataFrame(cs_rows, columns=["date", "symbol", "raw_mom", "resid_mom", "fwd_ret"])
    cs_raw_x, cs_resid_x, cs_y = [], [], []
    for _date, grp in cs_df.groupby("date"):
        if len(grp) < 3:  # rank-correlation on <3 names within a day is meaningless
            continue
        cs_raw_x.append(rankdata(grp["raw_mom"]))
        cs_resid_x.append(rankdata(grp["resid_mom"]))
        cs_y.append(rankdata(grp["fwd_ret"]))
    cs_raw_x_arr = np.concatenate(cs_raw_x)
    cs_resid_x_arr = np.concatenate(cs_resid_x)
    cs_y_arr = np.concatenate(cs_y)
    cs_raw = _bootstrap_cell(cs_raw_x_arr, cs_y_arr, block_size, n_boot, rng)
    cs_resid = _bootstrap_cell(cs_resid_x_arr, cs_y_arr, block_size, n_boot, rng)
    print("=== Cross-sectional axis (same-day rank, pooled across days) ===")
    print(
        f"raw:      ic={cs_raw['ic']:.4f} ci=[{cs_raw['ci_lower']:.4f}, "
        f"{cs_raw['ci_upper']:.4f}] n={cs_raw['n']} "
        f"{'CI crosses zero' if cs_raw['crosses_zero'] else 'CI EXCLUDES ZERO'}"
    )
    print(
        f"residual: ic={cs_resid['ic']:.4f} ci=[{cs_resid['ci_lower']:.4f}, "
        f"{cs_resid['ci_upper']:.4f}] n={cs_resid['n']} "
        f"{'CI crosses zero' if cs_resid['crosses_zero'] else 'CI EXCLUDES ZERO'}\n"
    )

    # Verdict (pre-registered rule, design doc + this docstring)
    resid_clears_any = (
        (not pooled_resid["crosses_zero"]) or (not cs_resid["crosses_zero"]) or n_resid_pass > 0
    )
    materially_higher = median_resid_ic > median_raw_ic and abs(pooled_resid["ic"]) > abs(
        pooled_raw["ic"]
    )
    verdict = "SURVIVES" if (resid_clears_any and materially_higher) else "DEAD"
    print(f"=== VERDICT: statistical_factor_residual is {verdict} at Stage 3 ===")
    print(
        f"Residual clears CI on >=1 axis: {resid_clears_any}. "
        f"Residual IC materially higher than raw on identical dates: {materially_higher} "
        f"(median per-symbol raw={median_raw_ic:.4f} vs resid={median_resid_ic:.4f}; "
        f"pooled |raw|={abs(pooled_raw['ic']):.4f} vs |resid|={abs(pooled_resid['ic']):.4f})."
    )
    conn.close()


if __name__ == "__main__":
    main()
