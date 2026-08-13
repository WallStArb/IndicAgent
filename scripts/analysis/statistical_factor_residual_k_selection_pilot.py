#!/usr/bin/env python3
"""K-selection pilot for statistical_factor_residual (docs/research/data-edge-source-
thesis.md). Pre-registered per that doc: "K must be chosen via a pre-registered,
principled method... before any IC test runs, or reporting whichever K 'looks best'
post-hoc is the same p-hacking shape adaptive_combiner_weights' halflife-grid
discipline exists to prevent."

This script answers ONLY "how many statistical factors K does this universe support" --
it never touches ctf_momentum, feature_ic_scores, or any downstream IC target, so there
is no path for K to be picked to flatter a later result. The IC comparison (Stage 2,
not in this script) is a separate, later step that reads K as a fixed input.

Method: two independent, fully unsupervised criteria on the daily log-return
correlation matrix, computed the same way scripts/analysis/effective_breadth_diagnostic.py
already measured this project's effective breadth (reused query/windowing pattern):

1. Marchenko-Pastur (MP) threshold -- Random Matrix Theory: eigenvalues of a purely
   noise correlation matrix (N assets, T observations, no true common structure) are
   bounded above by lambda_max = (1 + sqrt(N/T))^2. Any real eigenvalue exceeding this
   analytical bound is unlikely to be noise. Closed-form, no simulation needed.
2. Parallel Analysis (Horn's method) -- permute each symbol's return series
   independently (destroys cross-sectional correlation, preserves each symbol's own
   marginal distribution), recompute the eigenvalue spectrum many times, and take the
   95th percentile of the permuted top-eigenvalue distribution as an empirical noise
   ceiling. Corroborates MP with a resampling-based check instead of relying on the
   analytical formula alone -- matches this project's existing bootstrap/shuffle-null
   culture (ic_math.py's circular block bootstrap, canary_acausal_placebo, etc.).

Pre-registered decision rule (written here BEFORE running): if MP's and PA's implied K
agree within 1, use MP's K (analytically cleaner, no simulation noise). If they
disagree by more than 1, use the SMALLER (more conservative) K and flag the
disagreement explicitly -- never pick whichever is larger just because a bigger K gives
the residual construction more room to show an effect.

No lookahead: computed on a single fixed trailing window per run, never refit against
future data mid-test. Read-only diagnostic, no writes, exit code always 0.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from services.backfill_feature_factory import _connect_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402

_N_PERMUTATIONS = 200
_PA_PERCENTILE = 95.0
_RANDOM_STATE = 42  # [rca_analysis] seed affecting algorithm output -- APR-exempt here:
# this is a one-shot diagnostic script, not a production daemon; matches this project's
# existing convention of citing HMM_RANDOM_STATE=42 for reproducibility, not tunability.


def _marchenko_pastur_k(eigvals: np.ndarray, n: int, t: int) -> tuple[int, float]:
    """Count eigenvalues exceeding the analytical MP noise upper bound."""
    lambda_max = (1.0 + np.sqrt(n / t)) ** 2
    k = int(np.sum(eigvals > lambda_max))
    return k, lambda_max


def _parallel_analysis_k(
    returns: pd.DataFrame, real_eigvals: np.ndarray, rng: np.random.Generator
) -> tuple[int, float]:
    """Count real eigenvalues exceeding the 95th-percentile permuted-noise top eigenvalue."""
    arr = returns.to_numpy()
    n_obs, n_sym = arr.shape
    permuted_top = np.empty(_N_PERMUTATIONS)
    for i in range(_N_PERMUTATIONS):
        shuffled = arr.copy()
        for col in range(n_sym):
            rng.shuffle(shuffled[:, col])
        corr = np.corrcoef(shuffled, rowvar=False)
        permuted_top[i] = np.linalg.eigvalsh(corr).max()
    threshold = float(np.percentile(permuted_top, _PA_PERCENTILE))
    k = int(np.sum(real_eigvals > threshold))
    return k, threshold


def _measure(returns: pd.DataFrame, label: str, rng: np.random.Generator) -> None:
    n_obs, n_sym = returns.shape
    corr = returns.corr()
    eigvals = np.linalg.eigvalsh(corr.to_numpy())[::-1]  # descending
    eigvals = np.clip(eigvals, 0.0, None)

    mp_k, mp_threshold = _marchenko_pastur_k(eigvals, n_sym, n_obs)
    pa_k, pa_threshold = _parallel_analysis_k(returns, eigvals, rng)

    print(f"\n{label}: N={n_sym} symbols, T={n_obs} trading days")
    print(f"  Top 10 eigenvalues: {np.round(eigvals[:10], 3).tolist()}")
    print(f"  Marchenko-Pastur:  lambda_max={mp_threshold:.3f} -> K={mp_k}")
    print(
        f"  Parallel Analysis: threshold={pa_threshold:.3f} (95th pctile, {_N_PERMUTATIONS} perms) -> K={pa_k}"
    )

    if abs(mp_k - pa_k) <= 1:
        chosen = mp_k
        print(
            f"  DECISION: MP and PA agree within 1 -> K={chosen} (using MP, analytically cleaner)"
        )
    else:
        chosen = min(mp_k, pa_k)
        print(
            f"  DECISION: MP and PA disagree by {abs(mp_k - pa_k)} (MP={mp_k}, PA={pa_k}) "
            f"-> K={chosen} (conservative: smaller of the two, flagged for review)"
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

    rng = np.random.default_rng(_RANDOM_STATE)

    # Same two windows as effective_breadth_diagnostic.py, for direct comparability
    # against the already-measured effective-breadth numbers (~4.5-8.4).
    is_new = df.groupby("symbol")["created_at"].first().astype(str) >= "2026-08-05"
    old_symbols = set(is_new[~is_new].index.tolist())
    all_symbols = set(is_new.index.tolist())

    full_cols = [c for c in log_ret.columns if c in all_symbols]
    full = log_ret[full_cols].dropna(how="any")
    if len(full) >= 60:
        _measure(full, "FULL universe, common window (all active symbols)", rng)
    else:
        print(f"FULL universe common window too short ({len(full)} days) -- skipped")

    old_cols = [c for c in log_ret.columns if c in old_symbols]
    old_same_window = (
        log_ret.loc[full.index, old_cols].dropna(how="any") if len(full) else pd.DataFrame()
    )
    if len(old_same_window) >= 60:
        _measure(old_same_window, "OLD (pre-expansion) universe only, SAME window", rng)

    print(
        "\nThis is Stage 1 (K-selection) only. Per the pre-registered design in "
        "docs/research/measurement-statistical-factor-residual.md, do NOT proceed to "
        "the IC comparison (Stage 2) in the same session this K was first observed --"
        " write K down, then run Stage 2 as a separate, later step."
    )


if __name__ == "__main__":
    main()
