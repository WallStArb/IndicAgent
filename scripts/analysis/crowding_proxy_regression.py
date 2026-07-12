#!/usr/bin/env python3
"""Crowding proxy: alpha overlap with public-factor signals (todo 072, L7-3).

Regresses alpha_frames.alpha_score (per stratum, per weight_epoch) on three
canonical public-factor proxies computed independently from raw daily bars:
12-1 momentum, 5-day reversal, and a low-vol tilt (realized volatility).
High R^2 does not invalidate an edge, but it prices its decay risk -- alpha
explainable by the most public factors in existence is alpha the crowd
already trades. Diagnostic only: no gate, no promotion/demotion decision.

Public factors are deliberately computed from market_data_ohlcv directly
(not from feature_vectors' momentum_z_slow/momentum_reversal_z), since those
house features are not academic 12-1/5-day definitions (see todo 103) and
regressing house features against a house-feature-derived alpha_score would
be circular -- this needs an independent, "public" measuring stick.

No-lookahead alignment: each alpha observation on trading day D is joined to
factor values computed as of the daily bar STRICTLY BEFORE D (the last
close known before D's session), never D's own close.

Usage:
    .venv/bin/python scripts/analysis/crowding_proxy_regression.py
    .venv/bin/python scripts/analysis/crowding_proxy_regression.py --min-obs 50
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import pandas as pd
import statsmodels.api as sm

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import asyncpg  # noqa: E402

from src.observability.corpus_manifest import CorpusManifest  # noqa: E402

DB_URL = (
    f"postgresql://{os.getenv('POSTGRES_USER', 'postgres')}:"
    f"{os.getenv('POSTGRES_PASSWORD', 'postgres')}@"
    f"{os.getenv('POSTGRES_HOST', 'localhost')}/{os.getenv('POSTGRES_DB', 'indicagent')}"
)

_DEFAULT_REPORT_PATH = "docs/analysis/crowding-proxy-report.md"
_DEFAULT_MIN_OBS = 30  # matches setup_performance's sample_size>=30 convention

_MOMENTUM_LOOKBACK_DAYS = 252
_MOMENTUM_SKIP_DAYS = 21
_REVERSAL_LOOKBACK_DAYS = 5
_VOL_LOOKBACK_DAYS = 21

_DAILY_FACTORS_SQL = f"""
    WITH daily AS (
        SELECT
            symbol,
            timestamp::date AS dt,
            close,
            ln(close / LAG(close, 1) OVER w) AS log_ret_1d
        FROM market_data_ohlcv
        WHERE timeframe = '1d'
        WINDOW w AS (PARTITION BY symbol ORDER BY timestamp)
    )
    SELECT
        symbol,
        dt,
        ln(LAG(close, {_MOMENTUM_SKIP_DAYS}) OVER w
           / NULLIF(LAG(close, {_MOMENTUM_LOOKBACK_DAYS}) OVER w, 0)) AS momentum_12_1,
        ln(close / NULLIF(LAG(close, {_REVERSAL_LOOKBACK_DAYS}) OVER w, 0)) AS reversal_5d,
        STDDEV(log_ret_1d) OVER (
            PARTITION BY symbol ORDER BY dt
            ROWS BETWEEN {_VOL_LOOKBACK_DAYS - 1} PRECEDING AND CURRENT ROW
        ) AS low_vol_21d
    FROM daily
    WINDOW w AS (PARTITION BY symbol ORDER BY dt)
    ORDER BY symbol, dt
"""

_DAILY_ALPHA_SQL = """
    SELECT
        symbol,
        tf,
        regime,
        weight_epoch,
        bar_ts::date AS dt,
        AVG(alpha_score) AS alpha_score_avg,
        COUNT(*) AS n_frames
    FROM alpha_frames
    WHERE frame_variant = 'primary'
    GROUP BY symbol, tf, regime, weight_epoch, bar_ts::date
"""


async def _fetch_frames(pool: asyncpg.Pool) -> tuple[pd.DataFrame, pd.DataFrame]:
    async with pool.acquire() as conn:
        factor_rows = await conn.fetch(_DAILY_FACTORS_SQL)
        alpha_rows = await conn.fetch(_DAILY_ALPHA_SQL)
    factors = (
        pd.DataFrame(factor_rows, columns=list(factor_rows[0].keys()))
        if factor_rows
        else pd.DataFrame()
    )
    alpha = (
        pd.DataFrame(alpha_rows, columns=list(alpha_rows[0].keys()))
        if alpha_rows
        else pd.DataFrame()
    )
    return factors, alpha


def _align_no_lookahead(factors: pd.DataFrame, alpha: pd.DataFrame) -> pd.DataFrame:
    """As-of join: each alpha (symbol, dt) gets the latest factor row with
    factor.dt < alpha.dt (strictly prior trading day -- never same-day)."""
    factors = factors.dropna(subset=["momentum_12_1", "reversal_5d", "low_vol_21d"]).copy()
    factors["dt"] = pd.to_datetime(factors["dt"])
    alpha["dt"] = pd.to_datetime(alpha["dt"])

    # merge_asof requires the "on" column sorted globally (not just within each
    # "by" group) -- sort by dt first, symbol second.
    factors = factors.sort_values(["dt", "symbol"])
    alpha = alpha.sort_values(["dt", "symbol"])

    merged = pd.merge_asof(
        alpha,
        factors,
        on="dt",
        by="symbol",
        direction="backward",
        allow_exact_matches=False,  # strictly prior day only, no same-day lookahead
    )
    return merged.dropna(subset=["momentum_12_1", "reversal_5d", "low_vol_21d"])


def _run_stratum_regressions(merged: pd.DataFrame, min_obs: int) -> list[dict]:
    results = []
    for (tf, regime, weight_epoch), group in merged.groupby(["tf", "regime", "weight_epoch"]):
        n = len(group)
        row = {
            "tf": tf,
            "regime": regime,
            "weight_epoch": weight_epoch,
            "n_obs": n,
        }
        if n < min_obs:
            row["status"] = "insufficient_n"
            results.append(row)
            continue

        X = sm.add_constant(group[["momentum_12_1", "reversal_5d", "low_vol_21d"]].to_numpy())
        y = group["alpha_score_avg"].to_numpy()
        model = sm.OLS(y, X).fit()

        row.update(
            {
                "status": "ok",
                "r_squared": float(model.rsquared),
                "coef_momentum_12_1": float(model.params[1]),
                "coef_reversal_5d": float(model.params[2]),
                "coef_low_vol_21d": float(model.params[3]),
                "p_momentum_12_1": float(model.pvalues[1]),
                "p_reversal_5d": float(model.pvalues[2]),
                "p_low_vol_21d": float(model.pvalues[3]),
            }
        )
        results.append(row)
    return results


def _write_report(results: list[dict], report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    ok = [r for r in results if r["status"] == "ok"]
    skipped = [r for r in results if r["status"] != "ok"]
    ok.sort(key=lambda r: r["r_squared"], reverse=True)

    lines = [
        "# Crowding Proxy Report",
        "",
        "Todo 072 (L7-3): regresses per-stratum, per-epoch `alpha_score` on three public-factor",
        "proxies computed independently from daily bars (12-1 momentum, 5-day reversal, 21-day",
        "realized vol as a low-vol-tilt proxy). Diagnostic only -- no gate, no promotion",
        "decision. High R^2 prices decay risk (crowded alpha); it does not invalidate the edge.",
        "",
        "Factors joined no-lookahead: strictly the last daily close before each observation's",
        f"date. Min-obs gate: {_DEFAULT_MIN_OBS} symbol-days per stratum.",
        "",
        "## Strata with a fitted regression",
        "",
        "| tf | regime | epoch | n | R² | coef(mom12-1) | coef(rev5d) | coef(lowvol) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in ok:
        lines.append(
            f"| {r['tf']} | {r['regime']} | {r['weight_epoch']} | {r['n_obs']} | "
            f"{r['r_squared']:.4f} | {r['coef_momentum_12_1']:.4f} (p={r['p_momentum_12_1']:.3f}) | "
            f"{r['coef_reversal_5d']:.4f} (p={r['p_reversal_5d']:.3f}) | "
            f"{r['coef_low_vol_21d']:.4f} (p={r['p_low_vol_21d']:.3f}) |"
        )

    if skipped:
        lines += [
            "",
            "## Strata skipped (insufficient N)",
            "",
            "| tf | regime | epoch | n |",
            "|---|---|---|---|",
        ]
        for r in skipped:
            lines.append(f"| {r['tf']} | {r['regime']} | {r['weight_epoch']} | {r['n_obs']} |")

    if ok:
        max_r2 = max(r["r_squared"] for r in ok)
        lines += [
            "",
            "## Verdict",
            "",
            f"Highest stratum R² observed: **{max_r2:.4f}**"
            + (
                " -- crowding alarm: this stratum's alpha is substantially explained by public "
                "momentum/reversal/vol factors."
                if max_r2 > 0.3
                else " -- no stratum shows heavy public-factor overlap yet."
            ),
        ]

    report_path.write_text("\n".join(lines) + "\n")


async def main_async(min_obs: int, report_path: Path) -> None:
    pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=5)
    manifest = CorpusManifest("crowding_proxy_regression", CorpusManifest.DEFAULT_MANIFEST_DIR)
    manifest.set_inputs(min_obs=min_obs)
    try:
        factors, alpha = await _fetch_frames(pool)
        if factors.empty or alpha.empty:
            manifest.add_error("No data found in market_data_ohlcv (1d) or alpha_frames")
            manifest.write()
            print("No data available -- nothing to regress.")
            return

        merged = _align_no_lookahead(factors, alpha)
        results = _run_stratum_regressions(merged, min_obs)
        _write_report(results, report_path)

        ok_results = [r for r in results if r["status"] == "ok"]
        manifest.add_output(
            "crowding_proxy_regression_report",
            rows_total=len(results),
            columns_written=["tf", "regime", "weight_epoch", "n_obs", "r_squared"],
        )
        manifest.data["outputs"]["crowding_proxy_regression_report"]["strata_fitted"] = len(
            ok_results
        )
        manifest.data["outputs"]["crowding_proxy_regression_report"]["strata_skipped"] = len(
            results
        ) - len(ok_results)
        if ok_results:
            manifest.data["outputs"]["crowding_proxy_regression_report"]["max_r_squared"] = max(
                r["r_squared"] for r in ok_results
            )
        manifest.mark_success()
        manifest.write()

        print(f"Report written to {report_path}")
        print(
            f"Strata fitted: {len(ok_results)}, skipped (insufficient N): {len(results) - len(ok_results)}"
        )
        if ok_results:
            print(f"Max R^2: {max(r['r_squared'] for r in ok_results):.4f}")
    finally:
        await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-obs", type=int, default=_DEFAULT_MIN_OBS)
    parser.add_argument("--report-path", default=_DEFAULT_REPORT_PATH)
    args = parser.parse_args()
    asyncio.run(main_async(args.min_obs, Path(args.report_path)))


if __name__ == "__main__":
    main()
