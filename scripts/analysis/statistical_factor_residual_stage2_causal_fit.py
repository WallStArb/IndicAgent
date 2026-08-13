#!/usr/bin/env python3
"""Stage 2 (causal factor fit) for statistical_factor_residual. Pre-registered in
docs/research/measurement-statistical-factor-residual.md before this script was written.

Walk-forward PCA, mirroring services/regime_writer.py's existing
_compute_symbol_tf_walk_forward pattern: at any bar t, the factor loadings used to
compute its residual were fit using only data through the most recent refit boundary
<= t. Expanding window (not rolling), StandardScaler refit per segment, K=9 fixed
(re-measured for this exact universe/window in the same session -- see the design
doc's "K re-measured for Stage 2" note; do NOT reuse Stage 1's K=10, that was a
different, larger, much-shorter-window universe).

PCA-specific correction the HMM precedent doesn't need: eigenvector sign ambiguity.
Each refit's components are sign-aligned to the previous refit's corresponding
component (flip if the dot product is negative) before use, so "factor 3" means the
same thing across refits instead of flipping arbitrarily.

Read-only against market_data_ohlcv_tradeable -- no dependency on feature_vectors or
the concurrent corpus pipeline, safe to run while that's in flight.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.decomposition import PCA  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

from services.backfill_feature_factory import _connect_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402

_K = 9  # re-measured for this exact universe/window this session, not Stage 1's K=10
_WINDOW_DAYS = 2000
_INITIAL_WARMUP_BARS = 252
_REFIT_EVERY_BARS = 21


def _fetch_universe(conn) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT o.symbol, o.timestamp, o.close
            FROM market_data_ohlcv_tradeable o
            JOIN instruments i ON i.symbol = o.symbol
            WHERE o.timeframe = '1d' AND i.is_active = true
            ORDER BY o.symbol, o.timestamp
            """)
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["symbol", "ts", "close"])
    df["date"] = pd.to_datetime(df["ts"]).dt.date
    wide = df.pivot_table(index="date", columns="symbol", values="close", aggfunc="last")
    log_ret = np.log(wide).diff().dropna(how="all")
    tail = log_ret.tail(_WINDOW_DAYS)
    complete = tail.dropna(axis=1, how="any")
    return complete


def _sign_align(components: np.ndarray, prev_components: np.ndarray | None) -> np.ndarray:
    """Flip each component's sign to match the previous segment's corresponding
    component (by dot-product sign) -- eigenvectors have no canonical sign, so
    without this a component could flip arbitrarily between refits.
    """
    if prev_components is None:
        return components
    aligned = components.copy()
    for k in range(components.shape[0]):
        if np.dot(components[k], prev_components[k]) < 0:
            aligned[k] = -components[k]
    return aligned


def walk_forward_residuals(
    returns: pd.DataFrame,
) -> tuple[pd.DataFrame, list[tuple[int, int, int]]]:
    """Returns (residual_df, segments). residual_df has the same shape as returns
    with the first initial_warmup_bars rows all-NaN (no walk-forward residual exists
    there -- insufficient history for even the first fit, same convention as
    regime_writer's walk-forward labels).
    """
    n, n_sym = returns.shape
    arr = returns.to_numpy()
    residual_arr = np.full_like(arr, np.nan)
    segments: list[tuple[int, int, int]] = []

    boundary = _INITIAL_WARMUP_BARS
    prev_components: np.ndarray | None = None

    while boundary < n:
        train = arr[:boundary]
        scaler = StandardScaler()
        train_scaled = scaler.fit_transform(train)

        pca = PCA(n_components=_K, random_state=42)
        pca.fit(train_scaled)
        pca.components_ = _sign_align(pca.components_, prev_components)
        prev_components = pca.components_.copy()

        seg_end = min(boundary + _REFIT_EVERY_BARS, n)
        seg = arr[boundary:seg_end]
        seg_scaled = scaler.transform(seg)

        scores = seg_scaled @ pca.components_.T
        reconstructed_scaled = scores @ pca.components_
        reconstructed_raw = reconstructed_scaled * scaler.scale_ + scaler.mean_

        residual_arr[boundary:seg_end] = seg - reconstructed_raw
        segments.append((boundary, boundary, seg_end))
        boundary = seg_end

    residual_df = pd.DataFrame(residual_arr, index=returns.index, columns=returns.columns)
    return residual_df, segments


def _causality_check(returns: pd.DataFrame) -> None:
    """A segment's residual must be identical whether or not data AFTER that
    segment exists -- truncate the input well past an early segment and confirm
    that segment's residuals don't change.
    """
    full_residual, _ = walk_forward_residuals(returns)
    cutoff = _INITIAL_WARMUP_BARS + 5 * _REFIT_EVERY_BARS  # a few segments in
    truncated_residual, _ = walk_forward_residuals(returns.iloc[: cutoff + 200])

    early_full = full_residual.iloc[_INITIAL_WARMUP_BARS:cutoff]
    early_truncated = truncated_residual.iloc[_INITIAL_WARMUP_BARS:cutoff]
    diff = (early_full - early_truncated).abs()
    max_diff = float(np.nanmax(diff.to_numpy()))
    status = "PASS" if max_diff < 1e-9 else "FAIL -- LOOK-AHEAD LEAK"
    print(
        f"Causality check: max diff on early segments, truncated-vs-full = {max_diff:.2e} [{status}]"
    )


def main() -> None:
    settings = Settings()
    conn = _connect_db(settings)
    returns = _fetch_universe(conn)
    conn.close()

    print(f"Universe: {returns.shape[1]} symbols, {returns.shape[0]} days")

    residual_df, segments = walk_forward_residuals(returns)
    print(
        f"Segments: {len(segments)} refits, first boundary={_INITIAL_WARMUP_BARS}, "
        f"last seg_end={segments[-1][2] if segments else 'n/a'}"
    )

    valid_residual = residual_df.iloc[_INITIAL_WARMUP_BARS:]
    valid_returns = returns.iloc[_INITIAL_WARMUP_BARS:]

    raw_var = valid_returns.var().mean()
    resid_var = valid_residual.var().mean()
    variance_removed_pct = 100 * (1 - resid_var / raw_var)
    print(
        f"\nMean raw return variance: {raw_var:.6e}\n"
        f"Mean residual variance:   {resid_var:.6e}\n"
        f"Variance removed by K={_K} factors: {variance_removed_pct:.1f}%"
    )

    per_symbol_removed = 1 - valid_residual.var() / valid_returns.var()
    print(
        f"Per-symbol variance-removed: min={per_symbol_removed.min():.1%}, "
        f"median={per_symbol_removed.median():.1%}, max={per_symbol_removed.max():.1%}"
    )

    print()
    _causality_check(returns)

    print(
        "\nStage 2 (causal factor fit) complete. Per the pre-registered design, do NOT "
        "proceed to Stage 3 (ctf_momentum IC comparison) in the same session this residual "
        "was first observed for K -- Stage 3 also needs feature_vectors/ctf_momentum, which "
        "is gated on the concurrent corpus pipeline finishing."
    )


if __name__ == "__main__":
    main()
