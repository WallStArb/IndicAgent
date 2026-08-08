#!/usr/bin/env python3
"""Effective breadth diagnostic -- first real measurement of docs/research/data-edge-
source-thesis.md's "Breadth Is the Binding Constraint" section, which asserted
effective breadth ~8-15 (2026-07-01) without ever computing it from this project's own
data. Universe has since grown 80->231 active instruments; raw count is not effective
breadth (a prior ETF-only expansion "barely moved it" per the same doc section, because
more sector funds are more of the same bet -- this script checks whether the 2026-08-05/06
expansion, explicitly built against a distinctness test, actually did better).

Method: participation-ratio effective breadth on the daily log-return correlation
matrix -- N_eff = (sum(lambda))^2 / sum(lambda^2) over the correlation matrix's
eigenvalues. N_eff = N when returns are uncorrelated (identity correlation matrix, all
eigenvalues = 1); N_eff = 1 when everything moves together (one eigenvalue = N, rest 0).
This is the standard operationalization of "breadth" in IR = IC * sqrt(breadth) --
counts independent bets, not raw instrument count.

Uses market_data_ohlcv_tradeable (1d) only -- daily bars fetch first in the backfill
pipeline, so this doesn't need to wait for the in-flight intraday backfill to finish.
Read-only diagnostic -- no writes, exit code always 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from services.backfill_feature_factory import _connect_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402

_NEW_INSTRUMENT_CUTOFF = "2026-08-05"


def _participation_ratio_breadth(corr: pd.DataFrame) -> tuple[float, int]:
    eigvals = np.linalg.eigvalsh(corr.to_numpy())
    eigvals = np.clip(eigvals, 0.0, None)  # guard tiny negative noise from float error
    n_eff = float((eigvals.sum() ** 2) / (eigvals**2).sum())
    return n_eff, corr.shape[0]


def _measure(returns: pd.DataFrame, label: str) -> None:
    corr = returns.corr()
    n_eff, n = _participation_ratio_breadth(corr)
    avg_pairwise = (corr.to_numpy().sum() - n) / (n * (n - 1))
    print(
        f"{label}: N={n} symbols, {len(returns)} trading days, "
        f"avg_pairwise_corr={avg_pairwise:.3f}, effective_breadth={n_eff:.1f}"
    )


def main() -> None:
    settings = Settings()
    conn = _connect_db(settings)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT o.symbol, o.timestamp, o.close, i.created_at
            FROM market_data_ohlcv_tradeable o
            JOIN instruments i ON i.symbol = o.symbol
            WHERE o.timeframe = '1d' AND i.is_active = true
            ORDER BY o.symbol, o.timestamp
            """)
        rows = cur.fetchall()
    conn.close()

    df = pd.DataFrame(rows, columns=["symbol", "ts", "close", "created_at"])
    df["date"] = pd.to_datetime(df["ts"]).dt.date
    wide = df.pivot_table(index="date", columns="symbol", values="close", aggfunc="last")
    log_ret = np.log(wide).diff().dropna(how="all")

    is_new = df.groupby("symbol")["created_at"].first().astype(str) >= _NEW_INSTRUMENT_CUTOFF
    old_symbols = is_new[~is_new].index.tolist()
    new_symbols = is_new[is_new].index.tolist()
    print(
        f"Universe: {len(old_symbols)} pre-existing symbols, {len(new_symbols)} new (>= {_NEW_INSTRUMENT_CUTOFF})"
    )

    # Window 1: maximal common window across the FULL current universe (229 symbols),
    # bounded by the shortest-history symbol -- includes everyone, no survivorship pick.
    full_cols = [c for c in log_ret.columns if c in set(old_symbols) | set(new_symbols)]
    full = log_ret[full_cols].dropna(how="any")
    if len(full) >= 60:
        _measure(full, "FULL universe, common window (all symbols incl. newest)")
    else:
        print(f"FULL universe common window too short ({len(full)} days) -- skipped")

    # Window 2: old-universe-only, same window length as window 1, for apples-to-apples
    # comparison against the pre-expansion baseline the "~8-15" figure described.
    old_cols = [c for c in log_ret.columns if c in set(old_symbols)]
    old_same_window = (
        log_ret.loc[full.index, old_cols].dropna(how="any") if len(full) else pd.DataFrame()
    )
    if len(old_same_window) >= 60:
        _measure(old_same_window, "OLD universe only, SAME window (apples-to-apples baseline)")

    # Window 3: longer 2yr window, dropping symbols too new to have that much history
    # (drops the shortest-history additions, e.g. recent crypto/biotech), to check
    # whether window 1's result is being compressed by a handful of short histories.
    min_days_2yr = 500
    long_enough = [c for c in log_ret.columns if log_ret[c].notna().sum() >= min_days_2yr]
    long_window = log_ret[long_enough].tail(min_days_2yr).dropna(how="any")
    if len(long_window) >= 60:
        _measure(long_window, f"2yr window, symbols with >= {min_days_2yr}d history only")

    print(
        "\nInterpretation: effective_breadth compares against the thesis doc's assumed "
        "~8-15 figure (never previously computed). avg_pairwise_corr close to the old "
        "baseline means the new instruments are NOT meaningfully diversifying (same "
        "pattern as the earlier ETF-only expansion); a materially lower avg_pairwise_corr "
        "and higher effective_breadth means the distinctness-tested 2026-08-05/06 "
        "expansion is doing what it was designed to do."
    )


if __name__ == "__main__":
    main()
