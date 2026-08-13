#!/usr/bin/env python3
"""Stage 1 (mechanism build + validation) for todo 304 -- volume_pct, skew_tail,
volatility_pct. Pre-registered in docs/research/stratification-dimension-unification.md's
2026-08-12 reconciliation pass (item 16).

This script does NOT run the substitution test (Stage 3) or touch any IC target -- it only
confirms the mechanism is causal, non-degenerate, and reusable, using already-backfilled raw
OHLCV data (market_data_ohlcv_tradeable). Zero dependency on feature_vectors/regime_volatility/
the concurrent corpus pipeline -- safe to run while that pipeline is in flight (read-only,
different table, no write contention).

Mechanism, confirmed against live code this session (breadth_vol.py's vix_pct), reused not
reinvented: rolling z-score of the raw measure, then causal_rank.py::causal_expanding_rank
applied to that z-score. Never a raw z-score or whole-series pandas.rank() used directly for
bucketing (Phase 141 P0-T2's look-ahead fix exists specifically to prevent that).
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

_Z_WINDOW = 60  # trading days, matches vix_pct's rolling z-score window order of magnitude
_VOL_WINDOW = 20  # realized vol lookback
_SKEW_WINDOW = 20  # rolling skewness lookback
_VOLUME_MA_WINDOW = 20  # relative-volume baseline

# Representative sample: liquid, long-history names across a few sectors -- not the full
# universe, this is a mechanism check, not a corpus-wide measurement.
_SAMPLE_SYMBOLS = ["SPY", "AAPL", "XOM", "JPM", "TLT"]


def _fetch_daily(conn, symbol: str) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT timestamp, close, volume
            FROM market_data_ohlcv_tradeable
            WHERE symbol = %s AND timeframe = '1d'
            ORDER BY timestamp
            """,
            (symbol,),
        )
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["ts", "close", "volume"]).set_index("ts")
    return df


def _rank_of_zscore(raw: pd.Series) -> pd.Series:
    """Shared template: rolling z-score of raw measure, then causal expanding rank."""
    mean = raw.rolling(window=_Z_WINDOW, min_periods=_Z_WINDOW).mean()
    std = raw.rolling(window=_Z_WINDOW, min_periods=_Z_WINDOW).std()
    z = (raw - mean) / std.where(std > 1e-10)
    return causal_expanding_rank(z)


def _measure(symbol: str, df: pd.DataFrame) -> None:
    if len(df) < _Z_WINDOW + 50:
        print(f"{symbol}: insufficient history ({len(df)} rows) -- skipped")
        return

    log_ret = np.log(df["close"]).diff()

    realized_vol = log_ret.rolling(window=_VOL_WINDOW, min_periods=_VOL_WINDOW).std()
    volatility_pct = _rank_of_zscore(realized_vol)

    skew = log_ret.rolling(window=_SKEW_WINDOW, min_periods=_SKEW_WINDOW).skew()
    skew_tail = _rank_of_zscore(skew)

    vol_ma = df["volume"].rolling(window=_VOLUME_MA_WINDOW, min_periods=_VOLUME_MA_WINDOW).mean()
    rel_volume = df["volume"] / vol_ma.where(vol_ma > 0)
    volume_pct = _rank_of_zscore(rel_volume)

    print(f"\n{symbol}: {len(df)} daily bars")
    for name, series in [
        ("volatility_pct", volatility_pct),
        ("skew_tail", skew_tail),
        ("volume_pct", volume_pct),
    ]:
        valid = series.dropna()
        if valid.empty:
            print(f"  {name}: no valid values -- MECHANISM FAILURE")
            continue
        print(
            f"  {name}: n={len(valid)}, mean={valid.mean():.3f}, "
            f"std={valid.std():.3f}, min={valid.min():.3f}, max={valid.max():.3f}, "
            f"pct_below_0.1={100 * (valid < 0.1).mean():.1f}%, "
            f"pct_above_0.9={100 * (valid > 0.9).mean():.1f}%"
        )
        # Non-degenerate check: a working causal rank should be roughly uniform on
        # [0, 1] once past the warmup window -- flag anything wildly off (e.g.
        # clustered near 0 or 1, which would indicate the z-score step is broken).
        if valid.std() < 0.15:
            print(
                f"    WARNING: {name} distribution looks too narrow (std={valid.std():.3f}) -- investigate"
            )

        # Causality spot-check: truncate the input, rerun, confirm the overlapping
        # prefix is bit-identical -- a real test, not just a comment about intent.
        raw_map = {
            "volatility_pct": realized_vol,
            "skew_tail": skew,
            "volume_pct": rel_volume,
        }
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
        df = _fetch_daily(conn, symbol)
        _measure(symbol, df)
    conn.close()

    print(
        "\nStage 1 (mechanism build + validation) only -- per todo 304, do NOT proceed to "
        "Stage 2 (orthogonality vs. regime_volatility) until the concurrent corpus pipeline "
        "run finishes and feature_vectors.regime_volatility is populated."
    )


if __name__ == "__main__":
    main()
