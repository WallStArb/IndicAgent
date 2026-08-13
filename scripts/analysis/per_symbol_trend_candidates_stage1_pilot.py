#!/usr/bin/env python3
"""Stage 1 (mechanism build + validation) for todo 303 -- Hurst exponent and
autocorrelation-sign, the two per-symbol trend candidates whose Gate 0 rejection
(structural redundancy with the incumbent HMM's assumed trend-capture) needs
re-examination now that Phase 171/172 proved that assumption false.

Same discipline as scripts/analysis/per_symbol_regime_candidates_stage1_pilot.py
(todo 304's sibling): confirms the mechanism is causal and non-degenerate using
already-backfilled raw OHLCV, zero dependency on feature_vectors/regime_volatility/
the concurrent corpus pipeline. NOT the substitution test -- no IC target touched.

Both raw measures pass through the same rolling-z-score-then-causal-expanding-rank
template as vix_pct/volatility_pct/skew_tail/volume_pct, for consistency and because
even a naturally-bounded statistic (Hurst in [0,1], autocorr in [-1,1]) can still
drift in its own baseline level over market eras -- ranking removes that dependence
the same way it does for realized vol.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from services.backfill_feature_factory import _connect_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.intelligence.regime_signals.causal_rank import causal_expanding_rank  # noqa: E402

_Z_WINDOW = 60
_HURST_WINDOW = 60  # R/S needs enough points per window for a stable estimate
_AUTOCORR_WINDOW = 20
_AUTOCORR_LAG = 1

_SAMPLE_SYMBOLS = ["SPY", "AAPL", "XOM", "JPM", "TLT"]


def _fetch_daily_close(conn, symbol: str) -> pd.Series:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT timestamp, close
            FROM market_data_ohlcv_tradeable
            WHERE symbol = %s AND timeframe = '1d'
            ORDER BY timestamp
            """,
            (symbol,),
        )
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["ts", "close"]).set_index("ts")
    return df["close"]


def _rank_of_zscore(raw: pd.Series) -> pd.Series:
    mean = raw.rolling(window=_Z_WINDOW, min_periods=_Z_WINDOW).mean()
    std = raw.rolling(window=_Z_WINDOW, min_periods=_Z_WINDOW).std()
    z = (raw - mean) / std.where(std > 1e-10)
    return causal_expanding_rank(z)


def _single_window_hurst(window: np.ndarray) -> float:
    """Classic rescaled-range (R/S) single-scale Hurst estimate over one window.

    H = log(R/S) / log(n). A simple, standard single-scale estimator -- not the
    full multi-scale regression version production code would want, but adequate
    for a Stage 1 mechanism check (causal, bounded, non-degenerate).
    """
    n = len(window)
    mean = window.mean()
    deviations = np.cumsum(window - mean)
    r = deviations.max() - deviations.min()
    s = window.std()
    if s < 1e-12 or r < 1e-12:
        return np.nan
    return float(np.log(r / s) / np.log(n))


def _rolling_hurst(log_ret: pd.Series, window: int) -> pd.Series:
    return log_ret.rolling(window=window, min_periods=window).apply(_single_window_hurst, raw=True)


def _rolling_autocorr(log_ret: pd.Series, window: int, lag: int) -> pd.Series:
    return log_ret.rolling(window=window, min_periods=window).apply(
        lambda x: pd.Series(x).autocorr(lag=lag), raw=False
    )


def _measure(symbol: str, close: pd.Series) -> None:
    if len(close) < max(_Z_WINDOW, _HURST_WINDOW) + 50:
        print(f"{symbol}: insufficient history ({len(close)} rows) -- skipped")
        return

    log_ret = np.log(close).diff()

    hurst_raw = _rolling_hurst(log_ret, _HURST_WINDOW)
    hurst_rank = _rank_of_zscore(hurst_raw)

    autocorr_raw = _rolling_autocorr(log_ret, _AUTOCORR_WINDOW, _AUTOCORR_LAG)
    autocorr_rank = _rank_of_zscore(autocorr_raw)

    print(f"\n{symbol}: {len(close)} daily bars")
    raw_map = {"hurst_rank": hurst_raw, "autocorr_rank": autocorr_raw}
    for name, series in [("hurst_rank", hurst_rank), ("autocorr_rank", autocorr_rank)]:
        valid = series.dropna()
        if valid.empty:
            print(f"  {name}: no valid values -- MECHANISM FAILURE")
            continue
        raw_valid = raw_map[name].reindex(valid.index)
        print(
            f"  {name}: n={len(valid)}, rank mean={valid.mean():.3f}, std={valid.std():.3f}, "
            f"pct_below_0.1={100 * (valid < 0.1).mean():.1f}%, "
            f"pct_above_0.9={100 * (valid > 0.9).mean():.1f}% | "
            f"raw {name.split('_')[0]} mean={raw_valid.mean():.3f}, "
            f"min={raw_valid.min():.3f}, max={raw_valid.max():.3f}"
        )
        if valid.std() < 0.15:
            print(
                f"    WARNING: {name} distribution looks too narrow (std={valid.std():.3f}) -- investigate"
            )

        raw = raw_map[name]
        cutoff = len(raw) - 100
        truncated_rank = _rank_of_zscore(raw.iloc[:cutoff])
        full_rank = series.iloc[:cutoff]
        diff = (truncated_rank - full_rank).abs().dropna()
        max_diff = diff.max() if not diff.empty else 0.0
        status = "PASS" if max_diff < 1e-9 else "FAIL -- LOOK-AHEAD LEAK"
        print(
            f"    causality check ({name}): max diff on truncated-vs-full prefix = {max_diff:.2e} [{status}]"
        )


def main() -> None:
    settings = Settings()
    conn = _connect_db(settings)
    for symbol in _SAMPLE_SYMBOLS:
        close = _fetch_daily_close(conn, symbol)
        _measure(symbol, close)
    conn.close()

    print(
        "\nStage 1 (mechanism build + validation) only, todo 303's Hurst/autocorrelation-sign "
        "candidates -- do NOT proceed to Stage 2 (re-examine the Gate 0 redundancy rejection, "
        "orthogonality vs. regime_volatility) until the concurrent corpus pipeline finishes."
    )


if __name__ == "__main__":
    main()
