#!/usr/bin/env python3
"""Stage 2 (orthogonality study) for todos 303/304 -- the shared Pearson/mutual-info
primitive both sibling design docs call for ("write once, share"):
docs/research/measurement-per-symbol-trend-regime.md and
docs/research/measurement-per-symbol-percentile-rank-candidates.md.

Tests whether five per-symbol candidates -- hurst_rank, autocorr_rank (todo 303),
volatility_pct, skew_tail, volume_pct (todo 304) -- are structurally redundant with
feature_vectors.regime_volatility (K=3 HMM: calm/elevated/turbulent), the live,
null-arm-validated incumbent stratification axis. Gate 0's prior redundancy rejection
no longer holds (Phase 171/172 proved the legacy K=5 `regime` labels never actually
separated on trend); this is the re-examination both docs pre-registered.

NOT the substitution/falsification test (Stage 3) -- no IC target touched here. This
script only measures correlation/mutual-information against regime_volatility and
reports it. alpha.regime_stratification.max_correlation has no APR default yet --
this run is the first measurement that informs setting one, not a guessed threshold
being checked against.

Data dependency (per both docs): feature_vectors.regime_volatility populated by
regime_writer.py's --regime-column regime_volatility pass. Refuses to run against a
partial/in-flight write (a live regime_writer process still running, or zero rows
populated) -- reading partial cross-symbol state here would repeat the exact hazard
check_regime_consistency() exists to catch for full-pipeline runs.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import pearsonr  # noqa: E402
from sklearn.metrics import normalized_mutual_info_score  # noqa: E402

from services.backfill_feature_factory import _connect_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.intelligence.regime_signals.causal_rank import causal_expanding_rank  # noqa: E402

_Z_WINDOW = 60
_HURST_WINDOW = 60
_AUTOCORR_WINDOW = 20
_AUTOCORR_LAG = 1
_VOL_WINDOW = 20
_SKEW_WINDOW = 20
_VOLUME_MA_WINDOW = 20
_NMI_BINS = 3  # match regime_volatility's own K=3 cardinality for a fair MI comparison

# Same mechanism check sample as both Stage 1 pilots -- not a corpus-wide measurement.
_SAMPLE_SYMBOLS = ["SPY", "AAPL", "XOM", "JPM", "TLT"]


def _regime_writer_still_running() -> bool:
    # Bare substring, not "services/regime_writer.py" -- the documented recovery invocation
    # (todo 306, `.venv/bin/python -m services.regime_writer ...`) runs as a dotted module,
    # whose cmdline never contains a literal "/"+".py" and silently missed the old pattern
    # (confirmed 2026-08-14: pgrep -f "services/regime_writer.py" found zero matches against
    # a live, actually-running `-m services.regime_writer` process -- this guard was dead code
    # from day one for that invocation style, the only one this project's runbook uses).
    result = subprocess.run(
        ["pgrep", "-f", "regime_writer"],
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(result.stdout.strip())


def _check_data_ready(conn) -> None:
    if _regime_writer_still_running():
        print(
            "FATAL: a regime_writer process is currently running -- refusing to read "
            "feature_vectors.regime_volatility while it may still be writing (partial, "
            "in-flight cross-symbol state). Wait for it to finish and re-run.",
            file=sys.stderr,
        )
        sys.exit(1)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FILTER (WHERE regime_volatility IS NOT NULL), count(*) "
            "FROM feature_vectors WHERE tf = '1d'"
        )
        populated, total = cur.fetchone()

    if not populated:
        print(
            "FATAL: feature_vectors.regime_volatility is 0-populated at tf='1d' -- "
            "regime_writer's volatility pass has not completed. Nothing to measure "
            "against yet.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        f"Data-readiness gate: regime_volatility populated on {populated}/{total} 1d rows, "
        f"no regime_writer process currently running -- proceeding.\n"
    )


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
    return pd.DataFrame(rows, columns=["ts", "close", "volume"]).set_index("ts")


def _fetch_regime_volatility(conn, symbol: str) -> pd.Series:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT bar_ts, regime_volatility
            FROM feature_vectors
            WHERE symbol = %s AND tf = '1d' AND regime_volatility IS NOT NULL
            ORDER BY bar_ts
            """,
            (symbol,),
        )
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["ts", "regime_volatility"]).set_index("ts")
    return df["regime_volatility"]


def _fetch_ordinal_map(conn) -> dict[str, int]:
    """CVR sort_order for regime_volatility codes -- queried, not hardcoded, per the
    Controlled Vocabulary Registry (codes/order can change; this script must not
    assume calm=1/elevated=2/turbulent=3 as a guessed constant)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT code, sort_order FROM controlled_vocabulary "
            "WHERE namespace = 'regime_volatility' ORDER BY sort_order"
        )
        rows = cur.fetchall()
    return dict(rows)


def _rank_of_zscore(raw: pd.Series) -> pd.Series:
    mean = raw.rolling(window=_Z_WINDOW, min_periods=_Z_WINDOW).mean()
    std = raw.rolling(window=_Z_WINDOW, min_periods=_Z_WINDOW).std()
    z = (raw - mean) / std.where(std > 1e-10)
    return causal_expanding_rank(z)


def _single_window_hurst(window: np.ndarray) -> float:
    n = len(window)
    mean = window.mean()
    deviations = np.cumsum(window - mean)
    r = deviations.max() - deviations.min()
    s = window.std()
    if s < 1e-12 or r < 1e-12:
        return np.nan
    return float(np.log(r / s) / np.log(n))


def _rolling_autocorr(series: pd.Series, window: int, lag: int) -> pd.Series:
    """Vectorized replacement for a per-window Python callback
    (`.rolling().apply(lambda w: pd.Series(w).autocorr(lag=lag))`) that measured 34.0s
    for a single 392K-row symbol (2026-08-22 benchmark) -- by far the dominant cost in
    _compute_candidates, which itself sits in Stage 3's 200x null-arm falsification loop.

    Exactly equivalent, not approximate: within a length-`window` slice w, lag-`lag`
    autocorr via w.corr(w.shift(lag)) uses pairs (w[k], w[k-lag]) for k=lag..window-1 --
    i.e. window-lag pairs (x[j], x[j-lag]) for j spanning the slice's last window-lag
    positions. That is precisely what `series.rolling(window-lag).corr(series.shift(lag))`
    computes globally, so this reproduces the per-window callback bit-for-bit (verified:
    max abs diff ~1e-14, float-precision noise, across both synthetic and real
    log-return data with leading NaNs from .diff()) while running ~1,170x faster
    (0.029s vs 34.0s at 392K rows) by staying in pandas' C-level rolling ops instead of
    calling into Python once per window.

    Raises ValueError if lag >= window: `effective_window = window - lag` would be <= 0,
    and pandas' `.rolling(window=0, ...).corr(...)` silently returns an all-NaN series
    with no exception (confirmed empirically) -- a silent-wrong-answer failure mode this
    project's design mindset explicitly treats as worse than a loud crash. Today's only
    caller (_compute_candidates, _AUTOCORR_WINDOW=20/_AUTOCORR_LAG=1) never hits this,
    but this function has no other input validation to catch it if that ever changes.
    """
    if lag >= window:
        raise ValueError(
            f"_rolling_autocorr: lag ({lag}) must be < window ({window}) -- "
            "otherwise effective_window <= 0 and pandas silently returns all-NaN "
            "instead of raising"
        )
    effective_window = window - lag
    return series.rolling(window=effective_window, min_periods=effective_window).corr(
        series.shift(lag)
    )


def _compute_candidates(df: pd.DataFrame) -> dict[str, pd.Series]:
    close, volume = df["close"], df["volume"]
    log_ret = np.log(close).diff()

    hurst_raw = log_ret.rolling(window=_HURST_WINDOW, min_periods=_HURST_WINDOW).apply(
        _single_window_hurst, raw=True
    )
    autocorr_raw = _rolling_autocorr(log_ret, window=_AUTOCORR_WINDOW, lag=_AUTOCORR_LAG)
    realized_vol = log_ret.rolling(window=_VOL_WINDOW, min_periods=_VOL_WINDOW).std()
    skew = log_ret.rolling(window=_SKEW_WINDOW, min_periods=_SKEW_WINDOW).skew()
    vol_ma = volume.rolling(window=_VOLUME_MA_WINDOW, min_periods=_VOLUME_MA_WINDOW).mean()
    rel_volume = volume / vol_ma.where(vol_ma > 0)

    return {
        "hurst_rank": _rank_of_zscore(hurst_raw),
        "autocorr_rank": _rank_of_zscore(autocorr_raw),
        "volatility_pct": _rank_of_zscore(realized_vol),
        "skew_tail": _rank_of_zscore(skew),
        "volume_pct": _rank_of_zscore(rel_volume),
    }


def _orthogonality(
    candidate_rank: pd.Series, regime_vol: pd.Series, ordinal_map: dict[str, int]
) -> dict | None:
    joined = (
        pd.DataFrame({"rank": candidate_rank})
        .join(pd.DataFrame({"label": regime_vol}), how="inner")
        .dropna()
    )
    if len(joined) < 30:
        return None

    ordinal = joined["label"].map(ordinal_map)
    pearson_r, pearson_p = pearsonr(joined["rank"], ordinal)

    # Discretize the continuous candidate rank into K=3 bins for a like-for-like NMI
    # comparison against regime_volatility's own K=3 cardinality.
    rank_bins = pd.qcut(joined["rank"], q=_NMI_BINS, labels=False, duplicates="drop")
    nmi = normalized_mutual_info_score(rank_bins, joined["label"])

    return {"n": len(joined), "pearson_r": pearson_r, "pearson_p": pearson_p, "nmi": nmi}


def main() -> None:
    settings = Settings()
    conn = _connect_db(settings)
    _check_data_ready(conn)
    ordinal_map = _fetch_ordinal_map(conn)
    print(f"regime_volatility ordinal map (from controlled_vocabulary): {ordinal_map}\n")

    all_results: dict[str, list[dict]] = {
        name: []
        for name in ["hurst_rank", "autocorr_rank", "volatility_pct", "skew_tail", "volume_pct"]
    }

    for symbol in _SAMPLE_SYMBOLS:
        df = _fetch_daily(conn, symbol)
        if len(df) < max(_Z_WINDOW, _HURST_WINDOW) + 50:
            print(f"{symbol}: insufficient history ({len(df)} rows) -- skipped")
            continue
        regime_vol = _fetch_regime_volatility(conn, symbol)
        if regime_vol.empty:
            print(f"{symbol}: no regime_volatility rows -- skipped")
            continue

        candidates = _compute_candidates(df)
        print(f"\n{symbol}: {len(df)} daily bars, {len(regime_vol)} regime_volatility rows")
        for name, rank_series in candidates.items():
            result = _orthogonality(rank_series, regime_vol, ordinal_map)
            if result is None:
                print(f"  {name}: insufficient overlap with regime_volatility -- skipped")
                continue
            all_results[name].append(result)
            print(
                f"  {name}: n={result['n']}, pearson_r={result['pearson_r']:+.3f} "
                f"(p={result['pearson_p']:.3g}), nmi={result['nmi']:.3f}"
            )

    conn.close()

    print("\n" + "=" * 70)
    print("Stage 2 summary (across the 5 sample symbols) -- first measurement, no")
    print("alpha.regime_stratification.max_correlation APR default asserted yet:")
    print("=" * 70)
    for name, results in all_results.items():
        if not results:
            print(f"  {name}: no valid measurements")
            continue
        abs_r = [abs(r["pearson_r"]) for r in results]
        nmis = [r["nmi"] for r in results]
        print(
            f"  {name}: mean|pearson_r|={np.mean(abs_r):.3f}, max|pearson_r|={np.max(abs_r):.3f}, "
            f"mean_nmi={np.mean(nmis):.3f}, max_nmi={np.max(nmis):.3f} "
            f"(n_symbols={len(results)})"
        )

    print(
        "\nStage 2 (orthogonality) only -- no threshold decision made here. Once these "
        "numbers are reviewed and alpha.regime_stratification.max_correlation is set, "
        "proceed to Stage 3 (substitution/falsification test, "
        "per_symbol_regime_candidates_stage3_falsification.py) -- corrected 2026-08-14: "
        "does NOT need ic_engine/feature_ic_scores after all, just forward_returns + "
        "momentum_z_fast/momentum_z_mid (both already-populated pipeline stages)."
    )


if __name__ == "__main__":
    main()
