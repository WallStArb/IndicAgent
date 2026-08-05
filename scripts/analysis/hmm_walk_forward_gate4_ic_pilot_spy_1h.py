"""Todo 026's Gate 4 -- the actual decision measurement, not another instability read.

Todo 026 (P4a) set a pre-registered bar in 2026-06-28: "Rolling refit pilot shows >=10% IC
improvement (shadow mode, p<0.05)" before the real production fix is authorized. Everything run
so far (`hmm_regime_parameter_lookahead_pilot_spy_1h.py` and its TLT/1h, SPY/15m siblings) measured
*label disagreement*, not whether the walk-forward labels are actually BETTER at separating
returns than production's. This script runs that comparison.

**Regime score, made ordinal for a well-defined IC.** `_build_label_map`'s 5 labels have a
natural order (trending_down < transition_down < ranging < transition_up < trending_up, by
construction -- see its own docstring). Mapping each label to {-2,-1,0,1,2} turns "does the
regime label predict returns" into a single Spearman IC, directly comparable via the same
paired circular-block-bootstrap machinery this session already used for the CTF pilots
(`scripts/analysis/_nonlinear_interaction_combiner_shared.py`'s `bootstrap_ic_stats`/
`paired_bootstrap_ic_difference`) -- same evidence standard as everything else in this corpus,
not a bespoke metric invented for this one question.

**Scope, stated honestly:** single symbol/tf (SPY/1h, the timeframe tonight's broader pilot
found the worst instability at), not a full corpus-wide `ic_engine`-style re-run across all ~80
symbols. This is the cheap first pass the fix design in todo 248 calls for ("point it at 1h
first") -- a corpus-wide Gate 4 run is real, expensive, separate work, gated on this result being
promising enough to justify it.

tf-calibrated walk-forward params: refit_every_bars=1650 (~1 trading year), initial_warmup_bars=
3300 (~2 years) -- same convention as the earlier SPY/1h instability pilot, same live APR values
for every other HMM hyperparameter (n_components=5, covariance_type='full', n_iter=200,
hmm_random_state=42, full_cov_min_obs=500, min_hold_bars=3), confirmed in config_state 2026-08-03.

Usage: .venv/bin/python scripts/analysis/hmm_walk_forward_gate4_ic_pilot_spy_1h.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import psycopg

from scripts.analysis._nonlinear_interaction_combiner_shared import (  # noqa: E402
    bootstrap_ic_stats,
    paired_bootstrap_ic_difference,
)
from services.regime_writer import (  # noqa: E402
    _LABEL_RANGING,
    _LABEL_TRANSITION_DOWN,
    _LABEL_TRANSITION_UP,
    _LABEL_TRENDING_DOWN,
    _LABEL_TRENDING_UP,
    _build_obs_matrix,
    _walk_forward_hmm_labels,
)
from src.config.settings import Settings  # noqa: E402

_SYMBOL = "SPY"
_TF = "1h"

_N_COMPONENTS = 5
_COVARIANCE_TYPE = "full"
_N_ITER = 200
_HMM_RANDOM_STATE = 42
_FULL_COV_MIN_OBS = 500
_MIN_HOLD_BARS = 3
_VOL_WINDOW = 20
_MOMENTUM_WINDOW = 20
_VOL_OF_VOL_WINDOW = 20

_REFIT_EVERY_BARS = 1650
_INITIAL_WARMUP_BARS = 2 * _REFIT_EVERY_BARS

_BOOTSTRAP_BLOCK_SIZE = 10  # matches live alpha.ic.bootstrap_block_size.1h
_N_BOOT = 500
_BOOTSTRAP_SEED = 42

_ORDINAL_SCORE = {
    _LABEL_TRENDING_DOWN: -2,
    _LABEL_TRANSITION_DOWN: -1,
    _LABEL_RANGING: 0,
    _LABEL_TRANSITION_UP: 1,
    _LABEL_TRENDING_UP: 2,
}

_FETCH_PRODUCTION_REGIME_SQL = """
SELECT bar_ts, regime
FROM feature_vectors
WHERE symbol = %s AND tf = %s AND regime IS NOT NULL
"""

_FETCH_FORWARD_RETURNS_SQL = """
SELECT bar_ts, return_fast
FROM forward_returns
WHERE symbol = %s AND tf = %s
  AND return_type = 'executable_open_to_open'
  AND complete_fast = true
"""


def main() -> None:
    settings = Settings()
    conn = psycopg.connect(settings.database_url)

    print(f"Fetching {_SYMBOL} {_TF} OHLCV...")
    timestamps: list = []
    closes: list[float] = []
    volumes: list[float] = []
    with conn.cursor("ohlcv_stream_gate4") as cur:
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
    conn.commit()

    obs_matrix, valid_ts = _build_obs_matrix(
        timestamps,
        closes,
        volumes,
        vol_window=_VOL_WINDOW,
        momentum_window=_MOMENTUM_WINDOW,
        vol_of_vol_window=_VOL_OF_VOL_WINDOW,
    )

    print(
        f"Computing walk-forward labels (refit every {_REFIT_EVERY_BARS} bars, "
        f"{_INITIAL_WARMUP_BARS}-bar initial warmup)..."
    )
    wf_labels, segments = _walk_forward_hmm_labels(
        obs_matrix,
        n_components=_N_COMPONENTS,
        covariance_type=_COVARIANCE_TYPE,
        n_iter=_N_ITER,
        hmm_random_state=_HMM_RANDOM_STATE,
        refit_every_bars=_REFIT_EVERY_BARS,
        initial_warmup_bars=_INITIAL_WARMUP_BARS,
        min_hold_bars=_MIN_HOLD_BARS,
        full_cov_min_obs=_FULL_COV_MIN_OBS,
    )
    wf_ts = valid_ts[_INITIAL_WARMUP_BARS:]
    print(f"  {len(segments)} refit segments, {len(wf_labels)} walk-forward-labeled bars")
    wf_by_ts = dict(zip(wf_ts, wf_labels))

    print("Fetching production feature_vectors.regime...")
    with conn.cursor() as cur:
        cur.execute(_FETCH_PRODUCTION_REGIME_SQL, (_SYMBOL, _TF))
        prod_rows = cur.fetchall()
    prod_by_ts = {r[0] if r[0].tzinfo else r[0]: r[1] for r in prod_rows}
    print(f"  {len(prod_by_ts)} production-labeled bars")

    print("Fetching executable open-to-open forward returns...")
    with conn.cursor() as cur:
        cur.execute(_FETCH_FORWARD_RETURNS_SQL, (_SYMBOL, _TF))
        fr_rows = cur.fetchall()
    fr_by_ts = {r[0] if r[0].tzinfo else r[0]: float(r[1]) for r in fr_rows if r[1] is not None}
    print(f"  {len(fr_by_ts)} forward-return rows")

    common_ts = sorted(set(wf_by_ts) & set(prod_by_ts) & set(fr_by_ts))
    n = len(common_ts)
    print(f"\n{n} bars where walk-forward, production, and forward_returns all overlap")

    if n < 50:
        print(f"ABORT: n={n} too small for a meaningful bootstrap (need >= 50).")
        return

    wf_scores = np.array([_ORDINAL_SCORE[wf_by_ts[ts]] for ts in common_ts], dtype=float)
    prod_scores = np.array([_ORDINAL_SCORE[prod_by_ts[ts]] for ts in common_ts], dtype=float)
    actual = np.array([fr_by_ts[ts] for ts in common_ts])

    wf_stats = bootstrap_ic_stats(
        wf_scores, actual, _BOOTSTRAP_BLOCK_SIZE, _N_BOOT, _BOOTSTRAP_SEED
    )
    prod_stats = bootstrap_ic_stats(
        prod_scores, actual, _BOOTSTRAP_BLOCK_SIZE, _N_BOOT, _BOOTSTRAP_SEED
    )
    paired = paired_bootstrap_ic_difference(
        wf_scores, prod_scores, actual, _BOOTSTRAP_BLOCK_SIZE, _N_BOOT, _BOOTSTRAP_SEED
    )

    print("=" * 80)
    print(f"{_SYMBOL} {_TF}: ordinal regime score IC, walk-forward vs production, n={n}")
    print("=" * 80)
    print(
        f"PRODUCTION  point_ic={prod_stats['point_ic']:.4f}  "
        f"CI=[{prod_stats['ci_lower']:.4f}, {prod_stats['ci_upper']:.4f}]  "
        f"passes={prod_stats['passes']}"
    )
    print(
        f"WALK-FORWARD point_ic={wf_stats['point_ic']:.4f}  "
        f"CI=[{wf_stats['ci_lower']:.4f}, {wf_stats['ci_upper']:.4f}]  "
        f"passes={wf_stats['passes']}"
    )
    print(
        f"PAIRED diff (wf-prod)  point_diff={paired['point_diff']:.4f}  "
        f"CI=[{paired['ci_lower']:.4f}, {paired['ci_upper']:.4f}]  "
        f"wf_significantly_better={paired['a_significantly_better']}  "
        f"prod_significantly_better={paired['b_significantly_better']}"
    )
    if prod_stats["point_ic"] != 0:
        pct_change = (wf_stats["point_ic"] - prod_stats["point_ic"]) / abs(prod_stats["point_ic"])
        print(f"Relative change vs production: {pct_change:+.1%}")
    gate4_pass = (
        paired["a_significantly_better"]
        and prod_stats["point_ic"] != 0
        and (wf_stats["point_ic"] - prod_stats["point_ic"]) / abs(prod_stats["point_ic"]) >= 0.10
    )
    print(
        f"\nTodo 026 Gate 4 (>=10% IC improvement, p<0.05, this single-symbol pilot): "
        f"{'PASS' if gate4_pass else 'FAIL'}"
    )
    print("=" * 80)


if __name__ == "__main__":
    main()
