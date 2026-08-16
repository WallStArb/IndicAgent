#!/usr/bin/env python3
"""Stage 3 (falsification bar + mandatory null-arm control) for todos 303/304 -- the
shared substitution-test primitive both sibling design docs call for:
docs/research/measurement-per-symbol-trend-regime.md and
docs/research/measurement-per-symbol-percentile-rank-candidates.md.

Protocol: docs/research/stratification-dimension-unification.md's Gate 2 (Substitution
Test) --

    IC_partial = Corr(X_bar, Y_forward | S_candidate)

Tests whether each of five per-symbol candidates -- hurst_rank, autocorr_rank (todo 303),
volatility_pct, skew_tail, volume_pct (todo 304) -- sharpens IC beyond what
feature_vectors.regime_volatility (K=3 HMM: calm/elevated/turbulent) already provides, for
two X_bar predictors (momentum_z_fast, momentum_z_mid -- always-live core primitives,
same pair for all 5 candidates so results are directly comparable).

Timeframe (2026-08-14 correction): the pre-registered N > 20,000-bars-per-cell pass
criterion is a full-corpus/intraday-scale threshold -- unreachable at Stage 1/2's 1d-only,
5-symbol probe scale (5 symbols x a few thousand daily bars each, split across up to 9
joint cells, tops out in the low hundreds per cell). Extended here to 5m/15m (never 1m --
this corpus doesn't use 1m for anything) instead, where real bar counts clear the gate:
confirmed live 2026-08-14, ~390K 5m bars and ~130K 15m bars per symbol for 4/5 sample
symbols (TLT shorter at ~205K/68K). A single symbol's 5m bars alone clear N > 20,000 per
joint cell (9 cells: 3 regime_volatility codes x 3 candidate terciles); 15m needs the full
5-symbol pool, which the protocol already calls for ("joint cells on the 5 sample symbols").

IC Sharpe definition (matches src/intelligence/statistics/ic_math.py's
_compute_ic_rolling_metrics exactly, not reinvented): mean(window_ICs) / std(window_ICs)
over non-overlapping windows. Window size/min-windows here (_SHARPE_WINDOW_SIZE=500,
_SHARPE_MIN_WINDOWS=10) are probe-scale constants sized off this script's own real N, NOT
ic_engine.py's production APR values (alpha.ic.sharpe_window_size_subsampled=2000 raw
bars) -- those assume full-corpus scale and are exactly why the N>20,000 criterion doesn't
fit a 5-symbol probe at 1d. The full _compute_ic_rolling_metrics machinery (Protocol config,
complete_mask, non_degenerate_mask) is tightly coupled to ic_engine's pipeline conventions
and deliberately not reused here -- Stage 1/2 already established the lighter-weight
"reuse pure computational primitives, not the whole pipeline" pattern this script follows
(causal_expanding_rank, _circular_block_bootstrap_ic, apply_bh_fdr are pure functions
reused directly below; the rolling-Sharpe loop is a small, direct reimplementation of the
cited formula, not a fork of it).

NOT a full Gate 2 verdict on first run -- this is the "5 sample symbols first" probe the
protocol itself mandates before any full-corpus commitment ("never commit to a full-corpus
run on an unvalidated candidate"). A PASS here (including the null-arm control) licenses a
full-corpus re-run with the candidate's column baked in, per the protocol's own promotion
boundary; it does not by itself promote anything to production.

Data dependency: feature_vectors.regime_volatility populated (regime_writer.py's
--regime-column regime_volatility pass) at tf IN ('5m','15m'), plus forward_returns
(return_fast, complete_fast, return_type='executable_open_to_open' -- Invariant 1) and
feature_vectors.momentum_z_fast/momentum_z_mid, both already-populated pipeline stages,
no ic_engine corpus run needed. Refuses to run against a partial/in-flight regime_writer
write, same guard as Stage 2 (fixed 2026-08-14 to match the -m services.regime_writer
module-invocation form, not just the direct-script path).

The null-arm control (mandatory, pre-registered in both sibling docs before any Stage 3
run -- no separation number gets cited as real evidence without clearing this first):
per-symbol IID time-permutation, mirroring the null arm already validated in this codebase
for exactly this failure shape (hmm_candidate_regime_axes_identifiability_sweep.py's
"THE NULL ARM" section, the mechanism that caught Phase 171/172's HMM mislabeling).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy.stats import spearmanr  # noqa: E402

from scripts.analysis.per_symbol_regime_candidates_stage2_orthogonality import (  # noqa: E402
    _compute_candidates,
    _fetch_ordinal_map,
)
from services.backfill_feature_factory import _connect_db  # noqa: E402
from src.config.settings import Settings  # noqa: E402
from src.core.rng import hash_key_to_int  # noqa: E402
from src.intelligence.statistics.ic_math import apply_bh_fdr  # noqa: E402

_SAMPLE_SYMBOLS = ["SPY", "AAPL", "XOM", "JPM", "TLT"]
_TFS = ["5m", "15m"]  # never 1m -- this corpus doesn't use 1m for anything
_X_BAR_COLUMNS = ["momentum_z_fast", "momentum_z_mid"]
_CANDIDATE_NAMES = ["hurst_rank", "autocorr_rank", "volatility_pct", "skew_tail", "volume_pct"]

_N_TERCILES = 3
_SHARPE_WINDOW_SIZE = 500  # probe-scale; see module docstring
_SHARPE_MIN_WINDOWS = 10
_N_MIN_PER_JOINT_CELL = 20_000  # pre-registered pass criterion, pooled across 5 symbols
_IC_SHARPE_UPLIFT_THRESHOLD = 0.10  # 10%
_N_NULL_REPLICATES = 200  # matches alpha_score_residual_diagnostic_15m.py's null_shuffles
_NULL_P_THRESHOLD = 0.05
_FDR_ALPHA = 0.05


def _regime_writer_still_running() -> bool:
    # Bare substring, not "services/regime_writer.py" -- see Stage 2's identical guard
    # (fixed 2026-08-14) for why: the documented recovery invocation
    # (`python -m services.regime_writer ...`) never contains a literal "/"+".py".
    result = subprocess.run(
        ["pgrep", "-f", "regime_writer"], capture_output=True, text=True, check=False
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
            "SELECT tf, count(*) FILTER (WHERE regime_volatility IS NOT NULL), count(*) "
            "FROM feature_vectors WHERE tf = ANY(%s) GROUP BY tf",
            (_TFS,),
        )
        rows = cur.fetchall()
    populated_by_tf = {tf: (populated, total) for tf, populated, total in rows}

    for tf in _TFS:
        populated, total = populated_by_tf.get(tf, (0, 0))
        if not populated:
            print(
                f"FATAL: feature_vectors.regime_volatility is 0-populated at tf={tf!r} -- "
                "regime_writer's volatility pass has not completed there. Nothing to "
                "measure against yet.",
                file=sys.stderr,
            )
            sys.exit(1)
        print(
            f"Data-readiness gate: regime_volatility populated on {populated}/{total} "
            f"{tf} rows."
        )
    print("No regime_writer process currently running -- proceeding.\n")


def _fetch_ohlcv_volume(conn, symbol: str, tf: str) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT timestamp, close, volume
            FROM market_data_ohlcv_tradeable
            WHERE symbol = %s AND timeframe = %s
            ORDER BY timestamp
            """,
            (symbol, tf),
        )
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=["ts", "close", "volume"]).set_index("ts")


def _fetch_regime_volatility(conn, symbol: str, tf: str) -> pd.Series:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT bar_ts, regime_volatility
            FROM feature_vectors
            WHERE symbol = %s AND tf = %s AND regime_volatility IS NOT NULL
            ORDER BY bar_ts
            """,
            (symbol, tf),
        )
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["ts", "regime_volatility"]).set_index("ts")
    return df["regime_volatility"]


def _fetch_xbar_and_forward_return(conn, symbol: str, tf: str) -> pd.DataFrame:
    """momentum_z_fast/momentum_z_mid (X_bar candidates) joined with the executable
    forward return (Y_forward, Invariant 1: return_type='executable_open_to_open'),
    restricted to complete_fast rows (LEAD() didn't hit a gap/end-of-data)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT fv.bar_ts, fv.momentum_z_fast, fv.momentum_z_mid, fr.return_fast
            FROM feature_vectors fv
            INNER JOIN forward_returns fr
                ON fv.symbol = fr.symbol AND fv.tf = fr.tf AND fv.bar_ts = fr.bar_ts
                AND fr.return_type = 'executable_open_to_open'
            WHERE fv.symbol = %s AND fv.tf = %s AND fr.complete_fast = true
            ORDER BY fv.bar_ts
            """,
            (symbol, tf),
        )
        rows = cur.fetchall()
    return pd.DataFrame(
        rows, columns=["ts", "momentum_z_fast", "momentum_z_mid", "return_fast"]
    ).set_index("ts")


def _window_ic_series(x: np.ndarray, y: np.ndarray, window_size: int) -> np.ndarray:
    """Spearman IC per non-overlapping window -- the raw series _ic_sharpe reduces to a
    single Sharpe value. Matches _compute_ic_rolling_metrics's definition
    (mean(window_ICs)/std(window_ICs)); this is the window-IC half of that computation."""
    n = len(x)
    ics = []
    for start in range(0, n - window_size + 1, window_size):
        xw, yw = x[start : start + window_size], y[start : start + window_size]
        if np.std(xw) < 1e-12 or np.std(yw) < 1e-12:
            continue
        ic, _ = spearmanr(xw, yw)
        if np.isfinite(ic):
            ics.append(ic)
    return np.array(ics)


def _ic_sharpe(window_ics: np.ndarray) -> float | None:
    if len(window_ics) < _SHARPE_MIN_WINDOWS:
        return None
    std = window_ics.std()
    if std < 1e-12:
        return None
    return float(window_ics.mean() / std)


def _joint_cell_uplifts(
    panel: pd.DataFrame, candidate_col: str, xbar_col: str, ordinal_map: dict[str, int]
) -> list[dict]:
    """panel: pooled-across-symbols rows with columns [candidate_col, 'regime_volatility',
    xbar_col, 'return_fast'], already time-ordered WITHIN each symbol (concatenated, not
    interleaved -- window boundaries never straddle a symbol change, see _build_panel).

    Returns one dict per (regime_volatility_code, candidate_tercile) joint cell with
    n, baseline_sharpe (X_bar vs Y_forward stratified by regime_volatility alone), joint_
    sharpe (additionally stratified by the candidate tercile), and uplift_pct.
    """
    df = panel.dropna(subset=[candidate_col, "regime_volatility", xbar_col, "return_fast"])
    if df.empty:
        return []

    # Quantile edges for _N_TERCILES equal-sized bins, e.g. [1/3, 2/3] for 3 -- matches
    # regime_volatility's own K=3 cardinality (same rationale as Stage 2's _NMI_BINS).
    edge_quantiles = [i / _N_TERCILES for i in range(1, _N_TERCILES)]
    tercile_edges = df[candidate_col].quantile(edge_quantiles).to_numpy()
    tercile = np.digitize(df[candidate_col].to_numpy(), tercile_edges)  # 0 .. _N_TERCILES-1
    df = df.assign(_tercile=tercile)

    results = []
    for regime_code, regime_group in df.groupby("regime_volatility"):
        baseline_ics = _window_ic_series(
            regime_group[xbar_col].to_numpy(),
            regime_group["return_fast"].to_numpy(),
            _SHARPE_WINDOW_SIZE,
        )
        baseline_sharpe = _ic_sharpe(baseline_ics)

        for tercile_val, cell in regime_group.groupby("_tercile"):
            n = len(cell)
            joint_ics = _window_ic_series(
                cell[xbar_col].to_numpy(), cell["return_fast"].to_numpy(), _SHARPE_WINDOW_SIZE
            )
            joint_sharpe = _ic_sharpe(joint_ics)
            if baseline_sharpe is None or joint_sharpe is None or abs(baseline_sharpe) < 1e-9:
                uplift_pct = None
            else:
                uplift_pct = (joint_sharpe - baseline_sharpe) / abs(baseline_sharpe)

            results.append(
                {
                    "regime_volatility": regime_code,
                    "tercile": int(tercile_val),
                    "n": n,
                    "baseline_sharpe": baseline_sharpe,
                    "joint_sharpe": joint_sharpe,
                    "uplift_pct": uplift_pct,
                }
            )
    return results


def _null_arm_seed(candidate_name: str, xbar_col: str, tf: str) -> int:
    """Deterministic per-(candidate, xbar, tf) seed for the null-arm RNG, via the
    shared src/core/rng.py::hash_key_to_int -- NOT builtin hash(), which Python
    randomizes per-process by default (PYTHONHASHSEED unset) and would make null_p
    non-reproducible across reruns, silently breaking this control's own
    pre-registered guarantee ("no separation number gets cited as real evidence unless
    it clears this control"). Same discipline as HMM_RANDOM_STATE=42 elsewhere in this
    codebase: any seed affecting algorithm output must be pinned deterministically.
    """
    return hash_key_to_int(f"{candidate_name}|{xbar_col}|{tf}")


def _best_cell_uplift(cells: list[dict]) -> tuple[float, dict] | tuple[None, None]:
    """The test statistic: max uplift_pct among cells clearing the N-gate. Matches the
    pass criterion's own phrasing -- "IC Sharpe increases by more than 10% in AT LEAST
    ONE joint cell" -- so the statistic under test is the max, not the mean."""
    eligible = [c for c in cells if c["n"] >= _N_MIN_PER_JOINT_CELL and c["uplift_pct"] is not None]
    if not eligible:
        return None, None
    best = max(eligible, key=lambda c: c["uplift_pct"])
    return best["uplift_pct"], best


def _build_panel(
    ohlcv_by_symbol: dict[str, pd.DataFrame],
    regime_vol_by_symbol: dict[str, pd.Series],
    xbar_by_symbol: dict[str, pd.DataFrame],
    candidate_name: str,
    permute_rng: np.random.Generator | None,
) -> pd.DataFrame:
    """Concatenate all 5 symbols' rows into one pooled panel for one candidate. When
    permute_rng is not None, each symbol's OHLCV series is independently IID-permuted
    (own log-return order shuffled, own seed draw) before the candidate is computed on it
    -- the null arm. regime_volatility/X_bar/Y_forward stay in their ORIGINAL order and
    are joined back on the ORIGINAL (unpermuted) bar_ts index, so any measured uplift
    under permutation is purely a chance alignment artifact, never real structure --
    exactly the mechanism hmm_candidate_regime_axes_identifiability_sweep.py's null arm
    uses for the same failure shape.
    """
    parts = []
    for symbol, df in ohlcv_by_symbol.items():
        regime_vol = regime_vol_by_symbol[symbol]
        xbar = xbar_by_symbol[symbol]
        if permute_rng is not None:
            order = permute_rng.permutation(len(df))
            permuted = df.copy()
            # Permute close (and volume, kept paired) -- candidates are computed from
            # these two columns only (see _compute_candidates). bar_ts index is NOT
            # permuted, so the resulting candidate series re-joins against
            # regime_vol/xbar/return_fast at their original positions.
            permuted[["close", "volume"]] = df[["close", "volume"]].to_numpy()[order]
            df = permuted

        candidates = _compute_candidates(df)
        candidate_series = candidates[candidate_name]

        joined = (
            pd.DataFrame({candidate_name: candidate_series})
            .join(pd.DataFrame({"regime_volatility": regime_vol}), how="inner")
            .join(xbar, how="inner")
        )
        parts.append(joined)
    return pd.concat(parts, axis=0)


def main() -> None:
    settings = Settings()
    conn = _connect_db(settings)
    _check_data_ready(conn)
    ordinal_map = _fetch_ordinal_map(conn)

    fdr_p_values: list[float] = []
    fdr_index: list[tuple[str, str, str]] = []
    summary_rows: list[dict] = []

    for tf in _TFS:
        print(f"\n{'=' * 78}\nTimeframe: {tf}\n{'=' * 78}")

        ohlcv_by_symbol: dict[str, pd.DataFrame] = {}
        regime_vol_by_symbol: dict[str, pd.Series] = {}
        xbar_by_symbol: dict[str, pd.DataFrame] = {}
        for symbol in _SAMPLE_SYMBOLS:
            df = _fetch_ohlcv_volume(conn, symbol, tf)
            regime_vol = _fetch_regime_volatility(conn, symbol, tf)
            xbar = _fetch_xbar_and_forward_return(conn, symbol, tf)
            if df.empty or regime_vol.empty or xbar.empty:
                print(f"  {symbol}: missing data at {tf} -- excluded from this tf's pool")
                continue
            ohlcv_by_symbol[symbol] = df
            regime_vol_by_symbol[symbol] = regime_vol
            xbar_by_symbol[symbol] = xbar[["momentum_z_fast", "momentum_z_mid", "return_fast"]]

        if len(ohlcv_by_symbol) < 2:
            print(f"  Insufficient symbols with data at {tf} -- skipping this timeframe.")
            continue

        for candidate_name in _CANDIDATE_NAMES:
            real_panel = _build_panel(
                ohlcv_by_symbol, regime_vol_by_symbol, xbar_by_symbol, candidate_name, None
            )

            for xbar_col in _X_BAR_COLUMNS:
                cells = _joint_cell_uplifts(real_panel, candidate_name, xbar_col, ordinal_map)
                real_best_uplift, real_best_cell = _best_cell_uplift(cells)

                label = f"{candidate_name} vs {xbar_col} @ {tf}"
                if real_best_uplift is None:
                    print(f"{label}: no joint cell cleared N>={_N_MIN_PER_JOINT_CELL} -- SKIP")
                    continue

                verdict_shape = "PASS" if real_best_uplift > _IC_SHARPE_UPLIFT_THRESHOLD else "fail"
                print(
                    f"{label}: best uplift={real_best_uplift:+.1%} "
                    f"(regime={real_best_cell['regime_volatility']}, "
                    f"tercile={real_best_cell['tercile']}, n={real_best_cell['n']}) "
                    f"-> {verdict_shape} (threshold-only, null-arm pending)"
                )

                if real_best_uplift <= _IC_SHARPE_UPLIFT_THRESHOLD:
                    summary_rows.append(
                        {
                            "candidate": candidate_name,
                            "xbar": xbar_col,
                            "tf": tf,
                            "best_uplift": real_best_uplift,
                            "null_p": None,
                            "verdict": "fail (threshold)",
                        }
                    )
                    continue

                # Null arm -- only run for cells that already cleared the threshold;
                # running it for every fail would be pure wasted compute (200x cost)
                # for a result that fails regardless of the null p-value.
                rng = np.random.default_rng(_null_arm_seed(candidate_name, xbar_col, tf))
                beat_count = 0
                for _ in range(_N_NULL_REPLICATES):
                    null_panel = _build_panel(
                        ohlcv_by_symbol,
                        regime_vol_by_symbol,
                        xbar_by_symbol,
                        candidate_name,
                        rng,
                    )
                    null_cells = _joint_cell_uplifts(
                        null_panel, candidate_name, xbar_col, ordinal_map
                    )
                    null_uplift, _ = _best_cell_uplift(null_cells)
                    if null_uplift is not None and null_uplift >= real_best_uplift:
                        beat_count += 1
                null_p = beat_count / _N_NULL_REPLICATES

                verdict = "PASS" if null_p < _NULL_P_THRESHOLD else "fail (null-arm)"
                print(
                    f"  null-arm: null_p={null_p:.4f} ({_N_NULL_REPLICATES} replicates) -> {verdict}"
                )

                fdr_p_values.append(null_p)
                fdr_index.append((candidate_name, xbar_col, tf))
                summary_rows.append(
                    {
                        "candidate": candidate_name,
                        "xbar": xbar_col,
                        "tf": tf,
                        "best_uplift": real_best_uplift,
                        "null_p": null_p,
                        "verdict": verdict,
                    }
                )

    conn.close()

    print(
        f"\n{'=' * 78}\nStage 3 summary (BH-FDR corrected across all threshold-clearing tests)\n{'=' * 78}"
    )
    if fdr_p_values:
        reject, p_corrected = apply_bh_fdr(fdr_p_values, _FDR_ALPHA)
        for (candidate_name, xbar_col, tf), rejected, p_corr in zip(
            fdr_index, reject, p_corrected, strict=True
        ):
            print(
                f"  {candidate_name} vs {xbar_col} @ {tf}: "
                f"bh_p={p_corr:.4f} -> {'PASS (FDR-corrected)' if rejected else 'fail (FDR-corrected)'}"
            )
    else:
        print("  No candidate cleared the uplift threshold in any cell -- nothing to FDR-correct.")

    for row in summary_rows:
        print(f"  {row}")

    print(
        "\nStage 3 (falsification + null-arm) probe complete. A PASS here licenses a "
        "full-corpus re-run per the protocol's promotion boundary -- it does not itself "
        "promote anything to production."
    )


if __name__ == "__main__":
    main()
