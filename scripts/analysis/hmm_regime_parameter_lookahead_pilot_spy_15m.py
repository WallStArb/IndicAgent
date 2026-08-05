"""Todo 026 (P4a)'s validation pilot -- has anyone ever checked whether it matters?

`regime_writer.py` fits one `GaussianHMM` per (symbol, tf) on the ENTIRE available history in a
single batch call (`_compute_symbol_tf`'s `candidate.fit(obs_matrix)`, no date bound on the OHLCV
fetch), then decodes every bar causally (forward alpha-pass only, confirmed at
`_alpha_pass_jit` call site). The decode is genuinely causal -- bar t's label uses no data after
t. But the model's own parameters (5 emission means, 5x5 covariances, 5x5 transition matrix) were
estimated using the WHOLE series, including bars far in the future relative to any early
timestamp. This is a narrower, parameter-level form of lookahead, tracked since 2026-06-28 as
todo 026's P4a and explicitly GATED on exactly the test this script runs (see
`.planning/todos/deferred/026-hmm-regime-audit-optimization.md` and its superseded sibling
`.planning/todos/completed/034-hmm-walk-forward-refit.md`): "Validate the practical impact first
... if the shift is negligible, deprioritize; if IC materially changes, this must land before any
regime-stratified result is trusted." That validation has never been run.

This script runs it, cheaply, on one symbol/tf (SPY/15m, broadening todo 248's SPY/1h pilot to a
different timeframe) -- no production code changes, no corpus writes, no full-fix engineering.
Two labelings, both fully causal at decode time, differing only
in how much future data the model's PARAMETERS were allowed to see:

  Approach A (production, unmodified): `_compute_symbol_tf` called directly, real live APR
    values (n_components=5, vol_window=20, momentum_window=20, vol_of_vol_window=20, n_iter=200,
    hmm_random_state=42, covariance_type='full', min_hold_bars=3, full_cov_min_obs=500,
    min_state_occupation=0.05, churn_window=10, min_obs_factor=50, n_restarts=1 -- confirmed
    live in config_state 2026-08-03). Model parameters see the full series.

  Approach B (expanding-window periodic refit): same hyperparameters, same helper functions
    (`_build_obs_matrix`, `alpha_pass_jit`, `_smooth_states`, `_build_label_map`,
    `_stationary_distribution`, `_log_emit_full`/`_log_emit_diag`), but the HMM is refit at each
    `_REFIT_EVERY_BARS`-bar boundary using ONLY the training-slice prefix up to that boundary,
    then decodes the next segment forward with that period's fitted model before refitting again.
    At any bar t, the model used to label it was fit using only data <= the most recent refit
    boundary <= t -- eliminates the parameter-level lookahead channel entirely. `StandardScaler`
    is also refit per segment (not once on the full series), since a globally-fit scaler is the
    same class of leak in miniature. Each segment's own `_build_label_map` is applied before
    concatenating STRING labels (not raw state indices, which are not comparable across
    independently-fit models -- state 0 can mean a different regime in each segment's fit).

Comparison: label agreement rate between A and B over B's causal-coverage region (B has no labels
before its first refit boundary), and regime-stratified mean executable open-to-open forward
return for both labelings side by side -- the same "regime-stratified IC/return before vs after"
comparison todo 034 specified.

Usage: .venv/bin/python scripts/analysis/hmm_regime_parameter_lookahead_pilot_spy_15m.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import psycopg
from hmmlearn.hmm import GaussianHMM
from sklearn.preprocessing import StandardScaler

from services.regime_writer import (  # noqa: E402
    _build_label_map,
    _build_obs_matrix,
    _compute_symbol_tf,
    _log_emit_diag,
    _log_emit_full,
    _smooth_states,
    _stationary_distribution,
)
from src.config.settings import Settings  # noqa: E402
from src.intelligence.hmm_jit import alpha_pass_jit as _alpha_pass_jit  # noqa: E402

_SYMBOL = "SPY"
_TF = "15m"

# Live config_state values, confirmed 2026-08-03 -- identical to what regime_writer.py itself uses.
_N_COMPONENTS = 5
_VOL_WINDOW = 20
_MOMENTUM_WINDOW = 20
_VOL_OF_VOL_WINDOW = 20
_N_ITER = 200
_HMM_RANDOM_STATE = 42
_COVARIANCE_TYPE = "full"
_MIN_HOLD_BARS = 3
_FULL_COV_MIN_OBS = 500
_MIN_STATE_OCCUPATION = 0.05
_CHURN_WINDOW = 10
_MIN_OBS_FACTOR = 50
_N_RESTARTS = 1
_HELDOUT_FRACTION = 0.2

# Approach B's refit cadence: ~1 trading year of 1h bars (6.5h RTH * 252 days ~= 1638), rounded.
# "Periodic refit" per todo 034's Option A -- not tuned, a defensible round number.
_REFIT_EVERY_BARS = 6600  # 4x 1h's 1650 -- 15m has 4x the bar density of 1h
# Minimum initial training window before the first refit -- ~2 years, so the first fit isn't
# starved. Segments before this point have no Approach-B label (excluded from comparison).
_INITIAL_WARMUP_BARS = 2 * _REFIT_EVERY_BARS

_FETCH_FORWARD_RETURNS_SQL = """
SELECT bar_ts, return_fast
FROM forward_returns
WHERE symbol = %s AND tf = %s
  AND return_type = 'executable_open_to_open'
  AND complete_fast = true
"""


def _fit_hmm(obs_matrix: np.ndarray, seed: int) -> GaussianHMM:
    eff_cov_type = _COVARIANCE_TYPE if len(obs_matrix) >= _FULL_COV_MIN_OBS else "diag"
    model = GaussianHMM(
        n_components=_N_COMPONENTS,
        covariance_type=eff_cov_type,
        n_iter=_N_ITER,
        random_state=seed,
    )
    model.fit(obs_matrix)
    return model


def _decode_segment(model: GaussianHMM, obs_segment: np.ndarray) -> tuple[np.ndarray, dict]:
    """Causal alpha-pass decode of obs_segment under model, fresh stationary prior."""
    pi0 = _stationary_distribution(model.transmat_)
    if model.covariance_type == "full":
        log_emit = _log_emit_full(obs_segment, model.means_, model.covars_)
    else:
        d = model.means_.shape[1]
        covars_diag = (
            model.covars_[:, np.arange(d), np.arange(d)]
            if model.covars_.ndim == 3
            else model.covars_
        )
        log_emit = _log_emit_diag(obs_segment, model.means_, covars_diag)
    log_A = np.log(np.maximum(model.transmat_, 1e-300))
    raw_states, _ = _alpha_pass_jit(log_emit, log_A, pi0)
    label_map = _build_label_map(model.means_)
    return raw_states, label_map


def approach_b_expanding_refit(
    timestamps: list, closes: list[float], volumes: list[float]
) -> tuple[list, list[str]]:
    """Expanding-window periodic refit: the model used to label any bar t was fit using only
    data through the most recent refit boundary <= t. Returns (valid_ts_covered, labels) for
    bars from the first refit boundary onward -- bars before that have no Approach-B label.

    Smoothing (`_smooth_states`) runs per segment, not on a global concatenated index array --
    state indices are only meaningful within the model that produced them (state 0 in one
    segment's fit is not state 0 in the next), so cross-segment index concatenation before
    smoothing would silently compare unrelated cluster IDs. STRING labels concatenate safely
    since `_build_label_map` normalizes each segment's clusters onto the same 5 semantic names.
    """
    full_obs, full_ts = _build_obs_matrix(
        timestamps,
        closes,
        volumes,
        vol_window=_VOL_WINDOW,
        momentum_window=_MOMENTUM_WINDOW,
        vol_of_vol_window=_VOL_OF_VOL_WINDOW,
    )
    n = len(full_obs)
    if n < _INITIAL_WARMUP_BARS + _N_COMPONENTS * _MIN_OBS_FACTOR:
        raise RuntimeError(f"Insufficient history for Approach B: {n} obs")

    out_ts: list = []
    out_labels: list[str] = []
    boundary = _INITIAL_WARMUP_BARS
    n_refits = 0
    while boundary < n:
        train_slice = full_obs[:boundary]
        scaler = StandardScaler()
        train_scaled = scaler.fit_transform(train_slice)
        model = _fit_hmm(train_scaled, seed=_HMM_RANDOM_STATE)
        n_refits += 1

        seg_end = min(boundary + _REFIT_EVERY_BARS, n)
        seg_scaled = scaler.transform(full_obs[boundary:seg_end])
        raw_states, label_map = _decode_segment(model, seg_scaled)
        smoothed = _smooth_states(raw_states, _MIN_HOLD_BARS)
        out_ts.extend(full_ts[boundary:seg_end])
        out_labels.extend(label_map[int(s)] for s in smoothed)
        boundary = seg_end

    print(f"  Approach B: {n_refits} refits, {len(out_labels)} labeled bars")
    return out_ts, out_labels


def main() -> None:
    settings = Settings()
    conn = psycopg.connect(settings.database_url)
    # No autocommit: named (server-side) cursors, used here and inside _compute_symbol_tf,
    # require an active transaction block (matches regime_writer.py's own connection setup).

    print(f"Fetching {_SYMBOL} {_TF} OHLCV...")
    timestamps: list = []
    closes: list[float] = []
    volumes: list[float] = []
    with conn.cursor("ohlcv_stream_pilot") as cur:
        cur.execute(
            "SELECT timestamp, close, volume FROM market_data_ohlcv_tradeable "
            "WHERE symbol = %s AND timeframe = %s ORDER BY timestamp ASC",
            (_SYMBOL, _TF),
        )
        while True:
            batch = cur.fetchmany(10000)
            if not batch:
                break
            for r in batch:
                timestamps.append(r[0])
                closes.append(float(r[1]))
                volumes.append(float(r[2]))
    print(f"  {len(timestamps)} bars")

    print("Running Approach A (production, unmodified _compute_symbol_tf -- full-series fit)...")
    result_a = _compute_symbol_tf(
        conn,
        _SYMBOL,
        _TF,
        n_components=_N_COMPONENTS,
        vol_window=_VOL_WINDOW,
        n_iter=_N_ITER,
        hmm_random_state=_HMM_RANDOM_STATE,
        momentum_window=_MOMENTUM_WINDOW,
        vol_of_vol_window=_VOL_OF_VOL_WINDOW,
        covariance_type=_COVARIANCE_TYPE,
        min_hold_bars=_MIN_HOLD_BARS,
        heldout_fraction=_HELDOUT_FRACTION,
        full_cov_min_obs=_FULL_COV_MIN_OBS,
        min_state_occupation=_MIN_STATE_OCCUPATION,
        churn_window=_CHURN_WINDOW,
        min_obs_factor=_MIN_OBS_FACTOR,
        n_restarts=_N_RESTARTS,
    )
    if result_a is None:
        print("ABORT: Approach A returned None (degenerate/insufficient fit).")
        return
    update_rows_a, converged_a, _ = result_a
    labels_a_by_ts = {row[10]: row[0] for row in update_rows_a}
    print(f"  Approach A: {len(labels_a_by_ts)} labeled bars, converged={converged_a}")

    print(f"Running Approach B (expanding-window refit every {_REFIT_EVERY_BARS} bars)...")
    ts_b, labels_b = approach_b_expanding_refit(timestamps, closes, volumes)
    labels_b_by_ts = dict(zip(ts_b, labels_b))

    print("Fetching executable open-to-open forward returns...")
    with conn.cursor() as cur:
        cur.execute(_FETCH_FORWARD_RETURNS_SQL, (_SYMBOL, _TF))
        fr_rows = cur.fetchall()
    fr_by_ts = {r[0] if r[0].tzinfo else r[0]: float(r[1]) for r in fr_rows if r[1] is not None}
    print(f"  {len(fr_by_ts)} forward-return rows")

    common_ts = sorted(set(labels_a_by_ts) & set(labels_b_by_ts) & set(fr_by_ts))
    n_common = len(common_ts)
    print(
        f"\n{'=' * 80}\nComparison over {n_common} bars where A, B, and forward_returns all overlap"
    )
    print("=" * 80)

    agree = sum(1 for ts in common_ts if labels_a_by_ts[ts] == labels_b_by_ts[ts])
    print(f"Label agreement rate (A == B): {agree}/{n_common} = {agree / n_common:.4f}")

    print(f"\n{'Regime':<16}{'A: N':>8}{'A: mean_ret':>14}{'B: N':>8}{'B: mean_ret':>14}")
    all_labels = sorted(
        set(labels_a_by_ts[ts] for ts in common_ts) | set(labels_b_by_ts[ts] for ts in common_ts)
    )
    for lbl in all_labels:
        a_rets = [fr_by_ts[ts] for ts in common_ts if labels_a_by_ts[ts] == lbl]
        b_rets = [fr_by_ts[ts] for ts in common_ts if labels_b_by_ts[ts] == lbl]
        a_mean = np.mean(a_rets) if a_rets else float("nan")
        b_mean = np.mean(b_rets) if b_rets else float("nan")
        print(f"{lbl:<16}{len(a_rets):>8}{a_mean:>14.6f}{len(b_rets):>8}{b_mean:>14.6f}")

    print("=" * 80)


if __name__ == "__main__":
    main()
