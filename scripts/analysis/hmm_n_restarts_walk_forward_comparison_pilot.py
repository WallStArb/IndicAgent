"""D-03's out-of-band n_restarts parallel-arm comparison (Phase 171, staged pilot D-01).

RESEARCH.md's Second Finding: `_walk_forward_hmm_full` / `_compute_symbol_tf_walk_forward`
accept no `n_restarts` parameter, and CONTEXT.md D-03 says the production default for
`alpha.hmm.n_restarts` is set based on what THIS pilot shows, not assumed. Threading
`n_restarts` through the production walk-forward path before this pilot has a verdict would be
building speculatively (D-00). The multi-restart arm is therefore implemented ENTIRELY inline
in this script, replicating `_compute_symbol_tf`'s existing multi-seed restart+convergence-retry
selection loop (todo 108, corrected convergence test todo 229) per walk-forward segment --
`services/regime_writer.py` is never modified to get this comparison.

Three label sequences per cell, all computed in memory, never written to `feature_vectors`:
  1. prod_labels  -- existing feature_vectors.regime (the retired full-history-fit method's
     output; exists only until plan 171-05's NULL-out, which is why this script must run
     BEFORE that NULL-out).
  2. wf_labels_r1 -- walk-forward, single seed (`_walk_forward_hmm_labels`, unmodified import
     from regime_writer.py). This is the arm the production rollout will actually run.
  3. wf_labels_rN -- walk-forward, inline multi-restart loop at --n-restarts (default 3).

Two SEPARATE verdict blocks (D-03's explicit attribution-safeguard requirement -- a single
conflated number would make the walk-forward effect and the multi-restart effect
inseparable):
  Block A "walk-forward vs production": wf_labels_r1 vs prod_labels, ordinal-score Spearman
    IC against forward_returns.return_fast (Invariant 1: executable_open_to_open only), plus
    raw label agreement.
  Block B "walk-forward n_restarts=1 vs n_restarts=N": wf_labels_r1 vs wf_labels_rN, same
    statistics.

D-03 attribution gate: the multi-restart arm is preferred only when
paired_bootstrap_ic_difference(wf_rN, wf_r1, ...)["a_significantly_better"] is True on a
STRICT MAJORITY of evaluated cells. Anything else is INCONCLUSIVE, and INCONCLUSIVE means
alpha.hmm.n_restarts stays at 1 -- burden of proof is on the change (earn-promotion-through-
proof).

A GaussianHMM full-covariance fit on a thin walk-forward training prefix can raise a
non-positive-definite covariance LinAlgError mid-EM (same pathology plan 171-04 Task 1's
seed-stability pilot found live on TLT/1d and SPY/1d). This script catches that per-candidate
in the multi-restart loop (skipping the failed seed, matching `_compute_symbol_tf`'s own
per-seed independence) and per-cell around `_walk_forward_hmm_labels` itself (aborting that
cell with a printed reason, since regime_writer.py's unmodified function has no such guard).

Do NOT write to feature_vectors. Do NOT change any config_state value from this script.

Usage:
    .venv/bin/python scripts/analysis/hmm_n_restarts_walk_forward_comparison_pilot.py
    .venv/bin/python scripts/analysis/hmm_n_restarts_walk_forward_comparison_pilot.py --symbols TLT --tf 1d --n-restarts 2 --n-boot 100
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np  # noqa: E402
import psycopg  # noqa: E402
from hmmlearn.hmm import GaussianHMM  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

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
    _alpha_pass_jit,
    _build_label_map,
    _build_obs_matrix,
    _compute_log_emit,
    _seed_prior_from_label,
    _smooth_states,
    _stationary_distribution,
    _walk_forward_hmm_labels,
)
from src.config.settings import Settings  # noqa: E402

# ---------------------------------------------------------------------------
# Pilot scope -- same 8 symbols / 4 tfs as plan 171-04 Task 1
# ---------------------------------------------------------------------------

_DEFAULT_SYMBOLS = ["SPY", "IWM", "TLT", "GLD", "XLE", "EEM", "FXY", "SMH"]
_DEFAULT_TFS = ["1d", "1h", "15m", "5m"]

_MIN_OVERLAP_BARS = 50  # matches the Gate 4 pilot's own minimum

_RESULTS_PATH = Path("cache/hmm_n_restarts_comparison_results.json")

_APR_FALLBACKS: dict[str, str] = {
    "feature.hmm.n_components": "5",
    "feature.hmm.covariance_type": "full",
    "feature.hmm.n_iter": "200",
    "alpha.hmm.random_state": "42",
    "feature.hmm.full_cov_min_obs": "500",
    "feature.hmm.min_hold_bars": "3",
    "feature.hmm.vol_window": "20",
    "feature.hmm.obs_momentum_window": "20",
    "feature.hmm.obs_vol_of_vol_window": "20",
    "alpha.hmm.walk_forward.refit_every_bars.5m": "19800",
    "alpha.hmm.walk_forward.refit_every_bars.15m": "6600",
    "alpha.hmm.walk_forward.refit_every_bars.1h": "1650",
    "alpha.hmm.walk_forward.refit_every_bars.1d": "252",
    "alpha.hmm.walk_forward.initial_warmup_bars.5m": "39600",
    "alpha.hmm.walk_forward.initial_warmup_bars.15m": "13200",
    "alpha.hmm.walk_forward.initial_warmup_bars.1h": "3300",
    "alpha.hmm.walk_forward.initial_warmup_bars.1d": "504",
    "alpha.ic.bootstrap_block_size.5m": "78",
    "alpha.ic.bootstrap_block_size.15m": "26",
    "alpha.ic.bootstrap_block_size.1h": "10",
    "alpha.ic.bootstrap_block_size.1d": "10",
}

_ORDINAL_SCORE = {
    _LABEL_TRENDING_DOWN: -2,
    _LABEL_TRANSITION_DOWN: -1,
    _LABEL_RANGING: 0,
    _LABEL_TRANSITION_UP: 1,
    _LABEL_TRENDING_UP: 2,
}

_FETCH_OHLCV_SQL = """
SELECT timestamp, close, volume
FROM market_data_ohlcv_tradeable
WHERE symbol = %s AND timeframe = %s
ORDER BY timestamp ASC
"""

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


def _load_config(conn: psycopg.Connection) -> dict[str, str]:
    """Plain SELECT against config_state -- read-only analysis script. Falls back to
    _APR_FALLBACKS for any missing key."""
    cfg = dict(_APR_FALLBACKS)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT config_key, config_value FROM config_state "
            "WHERE config_key LIKE 'feature.hmm.%' OR config_key LIKE 'alpha.hmm.%' "
            "OR config_key LIKE 'alpha.ic.bootstrap_block_size.%'"
        )
        for key, value in cur.fetchall():
            cfg[key] = value
    conn.commit()
    return cfg


def _fetch_ohlcv(
    conn: psycopg.Connection, symbol: str, tf: str
) -> tuple[list, list[float], list[float]]:
    timestamps: list = []
    closes: list[float] = []
    volumes: list[float] = []
    with conn.cursor(f"nrestarts_ohlcv_{symbol}_{tf}") as cur:
        cur.execute(_FETCH_OHLCV_SQL, (symbol, tf))
        while True:
            batch = cur.fetchmany(10000)
            if not batch:
                break
            for r in batch:
                timestamps.append(r[0])
                closes.append(float(r[1]))
                volumes.append(float(r[2]))
    conn.commit()
    return timestamps, closes, volumes


def _fit_best_of_n_restarts(
    train_scaled: np.ndarray,
    n_components: int,
    eff_cov_type: str,
    n_iter: int,
    hmm_random_state: int,
    n_restarts: int,
):
    """Replicates `_compute_symbol_tf`'s multi-seed restart + convergence-retry selection
    loop (todo 108, corrected convergence test todo 229), applied to ONE walk-forward
    segment's training prefix. Not imported from regime_writer.py -- that function has no
    n_restarts parameter today (RESEARCH.md Second Finding); this is the inline arm D-03
    asks for. Skips (rather than propagates) a candidate whose fit raises a covariance
    LinAlgError/ValueError -- the same numerical pathology plan 171-04 Task 1 found live on
    thin prefixes -- so one bad seed doesn't sink the whole segment when other seeds are
    fine. Raises RuntimeError if every candidate for this segment fails.
    """
    model = None
    converged = False
    best_ll = float("-inf")
    n_failed = 0
    for i in range(n_restarts):
        seed = hmm_random_state + i
        try:
            candidate = GaussianHMM(
                n_components=n_components,
                covariance_type=eff_cov_type,
                n_iter=n_iter,
                random_state=seed,
            )
            candidate.fit(train_scaled)
            candidate_converged = candidate.monitor_.iter < candidate.monitor_.n_iter
            if not candidate_converged:
                retry_model = GaussianHMM(
                    n_components=n_components,
                    covariance_type=eff_cov_type,
                    n_iter=n_iter * 2,
                    random_state=seed,
                )
                retry_model.fit(train_scaled)
                if retry_model.monitor_.iter < retry_model.monitor_.n_iter:
                    candidate = retry_model
                    candidate_converged = True
        except (np.linalg.LinAlgError, ValueError):
            n_failed += 1
            continue

        if n_restarts == 1:
            model = candidate
            converged = candidate_converged
            break

        candidate_ll = float(candidate.score(train_scaled))
        if model is None or (candidate_converged, candidate_ll) > (converged, best_ll):
            model = candidate
            converged = candidate_converged
            best_ll = candidate_ll

    if model is None:
        raise RuntimeError(
            f"all {n_restarts} restart candidates failed to fit (numerical instability)"
        )
    return model


def _walk_forward_hmm_labels_multi_restart(
    obs_matrix: np.ndarray,
    n_components: int,
    covariance_type: str,
    n_iter: int,
    hmm_random_state: int,
    refit_every_bars: int,
    initial_warmup_bars: int,
    min_hold_bars: int,
    full_cov_min_obs: int,
    n_restarts: int,
) -> tuple[list[str], list[tuple[int, int, int]]]:
    """Mirrors `_walk_forward_hmm_labels` (regime_writer.py) exactly -- same refit
    schedule, same label-continuity prior seeding, same per-segment StandardScaler -- with
    the single-seed fit replaced by `_fit_best_of_n_restarts`. Implemented here, not in
    regime_writer.py, per this task's explicit scope."""
    n = len(obs_matrix)
    if n < initial_warmup_bars + n_components:
        raise ValueError(
            f"Insufficient history for walk-forward HMM: {n} obs, "
            f"need >= {initial_warmup_bars + n_components}"
        )

    labels: list[str] = []
    segments: list[tuple[int, int, int]] = []
    boundary = initial_warmup_bars
    prior_label: str | None = None

    while boundary < n:
        train_slice = obs_matrix[:boundary]
        scaler = StandardScaler()
        train_scaled = scaler.fit_transform(train_slice)

        eff_cov_type = covariance_type if len(train_scaled) >= full_cov_min_obs else "diag"
        model = _fit_best_of_n_restarts(
            train_scaled, n_components, eff_cov_type, n_iter, hmm_random_state, n_restarts
        )
        label_map = _build_label_map(model.means_)

        stationary_prior = _stationary_distribution(model.transmat_)
        if prior_label is None:
            pi0 = stationary_prior
        else:
            pi0 = _seed_prior_from_label(label_map, prior_label, n_components, stationary_prior)

        seg_end = min(boundary + refit_every_bars, n)
        seg_scaled = scaler.transform(obs_matrix[boundary:seg_end])
        log_emit = _compute_log_emit(seg_scaled, model.means_, model.covars_, eff_cov_type)
        log_A = np.log(np.maximum(model.transmat_, 1e-300))
        raw_states, _ = _alpha_pass_jit(log_emit, log_A, pi0)
        smoothed = _smooth_states(raw_states, min_hold_bars)
        seg_labels = [label_map[int(s)] for s in smoothed]

        labels.extend(seg_labels)
        segments.append((boundary, boundary, seg_end))
        prior_label = seg_labels[-1]
        boundary = seg_end

    return labels, segments


def _raw_agreement(labels_a: list[str], labels_b: list[str]) -> float:
    agree = sum(1 for a, b in zip(labels_a, labels_b) if a == b)
    return agree / len(labels_a)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=_DEFAULT_SYMBOLS)
    parser.add_argument("--tf", nargs="+", default=_DEFAULT_TFS)
    parser.add_argument("--n-restarts", type=int, default=3)
    parser.add_argument("--block-size", type=int, default=None)
    parser.add_argument("--n-boot", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    settings = Settings()
    conn = psycopg.connect(settings.database_url)

    cfg = _load_config(conn)
    n_components = int(cfg["feature.hmm.n_components"])
    covariance_type = cfg["feature.hmm.covariance_type"]
    n_iter = int(cfg["feature.hmm.n_iter"])
    hmm_random_state = int(cfg["alpha.hmm.random_state"])
    full_cov_min_obs = int(cfg["feature.hmm.full_cov_min_obs"])
    min_hold_bars = int(cfg["feature.hmm.min_hold_bars"])
    vol_window = int(cfg["feature.hmm.vol_window"])
    momentum_window = int(cfg["feature.hmm.obs_momentum_window"])
    vol_of_vol_window = int(cfg["feature.hmm.obs_vol_of_vol_window"])

    print("=" * 80)
    print("D-03 out-of-band n_restarts walk-forward comparison pilot")
    print("=" * 80)
    print(
        f"n_components={n_components} covariance_type={covariance_type} n_iter={n_iter} "
        f"hmm_random_state={hmm_random_state} full_cov_min_obs={full_cov_min_obs} "
        f"min_hold_bars={min_hold_bars} n_restarts={args.n_restarts}"
    )
    print(f"symbols={args.symbols} tfs={args.tf} n_boot={args.n_boot} seed={args.seed}")
    print("=" * 80)

    cell_results: list[dict] = []
    block_b_evaluated = 0
    block_b_a_better_count = 0

    for tf in args.tf:
        refit_every_bars = int(
            cfg.get(
                f"alpha.hmm.walk_forward.refit_every_bars.{tf}",
                _APR_FALLBACKS[f"alpha.hmm.walk_forward.refit_every_bars.{tf}"],
            )
        )
        initial_warmup_bars = int(
            cfg.get(
                f"alpha.hmm.walk_forward.initial_warmup_bars.{tf}",
                _APR_FALLBACKS[f"alpha.hmm.walk_forward.initial_warmup_bars.{tf}"],
            )
        )
        block_size = args.block_size or int(
            cfg.get(
                f"alpha.ic.bootstrap_block_size.{tf}",
                _APR_FALLBACKS.get(f"alpha.ic.bootstrap_block_size.{tf}", "10"),
            )
        )

        for symbol in args.symbols:
            print(f"\n--- {symbol} {tf} ---")
            timestamps, closes, volumes = _fetch_ohlcv(conn, symbol, tf)
            if not timestamps:
                print(f"  ABORT: no OHLCV rows for {symbol}/{tf}")
                cell_results.append(
                    {"symbol": symbol, "tf": tf, "aborted": True, "reason": "no_ohlcv"}
                )
                continue

            obs_matrix, valid_ts = _build_obs_matrix(
                timestamps,
                closes,
                volumes,
                vol_window=vol_window,
                momentum_window=momentum_window,
                vol_of_vol_window=vol_of_vol_window,
            )
            n = len(obs_matrix)
            if n < initial_warmup_bars + n_components:
                reason = (
                    f"insufficient history: n={n} obs, need >= {initial_warmup_bars + n_components}"
                )
                print(f"  ABORT: {reason}")
                cell_results.append({"symbol": symbol, "tf": tf, "aborted": True, "reason": reason})
                continue

            try:
                wf_labels_r1, _ = _walk_forward_hmm_labels(
                    obs_matrix,
                    n_components=n_components,
                    covariance_type=covariance_type,
                    n_iter=n_iter,
                    hmm_random_state=hmm_random_state,
                    refit_every_bars=refit_every_bars,
                    initial_warmup_bars=initial_warmup_bars,
                    min_hold_bars=min_hold_bars,
                    full_cov_min_obs=full_cov_min_obs,
                )
            except (np.linalg.LinAlgError, ValueError) as error:
                reason = f"wf_labels_r1 fit failed: {type(error).__name__}: {error}"
                print(f"  ABORT: {reason}")
                cell_results.append({"symbol": symbol, "tf": tf, "aborted": True, "reason": reason})
                continue

            try:
                wf_labels_rN, _ = _walk_forward_hmm_labels_multi_restart(
                    obs_matrix,
                    n_components=n_components,
                    covariance_type=covariance_type,
                    n_iter=n_iter,
                    hmm_random_state=hmm_random_state,
                    refit_every_bars=refit_every_bars,
                    initial_warmup_bars=initial_warmup_bars,
                    min_hold_bars=min_hold_bars,
                    full_cov_min_obs=full_cov_min_obs,
                    n_restarts=args.n_restarts,
                )
            except (np.linalg.LinAlgError, ValueError, RuntimeError) as error:
                reason = f"wf_labels_rN fit failed: {type(error).__name__}: {error}"
                print(f"  ABORT: {reason}")
                cell_results.append({"symbol": symbol, "tf": tf, "aborted": True, "reason": reason})
                continue

            wf_ts = valid_ts[initial_warmup_bars:]
            wf_r1_by_ts = dict(zip(wf_ts, wf_labels_r1))
            wf_rN_by_ts = dict(zip(wf_ts, wf_labels_rN))

            with conn.cursor() as cur:
                cur.execute(_FETCH_PRODUCTION_REGIME_SQL, (symbol, tf))
                prod_rows = cur.fetchall()
            prod_by_ts = {r[0] if r[0].tzinfo else r[0]: r[1] for r in prod_rows}

            with conn.cursor() as cur:
                cur.execute(_FETCH_FORWARD_RETURNS_SQL, (symbol, tf))
                fr_rows = cur.fetchall()
            fr_by_ts = {
                r[0] if r[0].tzinfo else r[0]: float(r[1]) for r in fr_rows if r[1] is not None
            }

            common_ts_a = sorted(set(wf_r1_by_ts) & set(prod_by_ts) & set(fr_by_ts))
            common_ts_b = sorted(set(wf_r1_by_ts) & set(wf_rN_by_ts) & set(fr_by_ts))

            print(
                f"  n_obs={n} block_a_overlap={len(common_ts_a)} block_b_overlap={len(common_ts_b)}"
            )

            if len(common_ts_a) < _MIN_OVERLAP_BARS or len(common_ts_b) < _MIN_OVERLAP_BARS:
                reason = (
                    f"insufficient overlap: block_a={len(common_ts_a)} "
                    f"block_b={len(common_ts_b)}, need >= {_MIN_OVERLAP_BARS}"
                )
                print(f"  ABORT: {reason}")
                cell_results.append({"symbol": symbol, "tf": tf, "aborted": True, "reason": reason})
                continue

            # Block A: walk-forward (r1) vs production
            wf_r1_scores_a = np.array(
                [_ORDINAL_SCORE[wf_r1_by_ts[ts]] for ts in common_ts_a], dtype=float
            )
            prod_scores_a = np.array(
                [_ORDINAL_SCORE[prod_by_ts[ts]] for ts in common_ts_a], dtype=float
            )
            actual_a = np.array([fr_by_ts[ts] for ts in common_ts_a])

            wf_r1_stats_a = bootstrap_ic_stats(
                wf_r1_scores_a, actual_a, block_size, args.n_boot, args.seed
            )
            prod_stats_a = bootstrap_ic_stats(
                prod_scores_a, actual_a, block_size, args.n_boot, args.seed
            )
            paired_a = paired_bootstrap_ic_difference(
                wf_r1_scores_a, prod_scores_a, actual_a, block_size, args.n_boot, args.seed
            )
            raw_agreement_a = _raw_agreement(
                [wf_r1_by_ts[ts] for ts in common_ts_a], [prod_by_ts[ts] for ts in common_ts_a]
            )

            print(
                f"  Block A (walk-forward vs production), n={len(common_ts_a)}:\n"
                f"    PRODUCTION    point_ic={prod_stats_a['point_ic']:.4f} "
                f"CI=[{prod_stats_a['ci_lower']:.4f}, {prod_stats_a['ci_upper']:.4f}]\n"
                f"    WALK-FORWARD  point_ic={wf_r1_stats_a['point_ic']:.4f} "
                f"CI=[{wf_r1_stats_a['ci_lower']:.4f}, {wf_r1_stats_a['ci_upper']:.4f}]\n"
                f"    PAIRED diff (wf-prod)  point_diff={paired_a['point_diff']:.4f} "
                f"CI=[{paired_a['ci_lower']:.4f}, {paired_a['ci_upper']:.4f}] "
                f"wf_better={paired_a['a_significantly_better']} "
                f"prod_better={paired_a['b_significantly_better']}\n"
                f"    raw label agreement={raw_agreement_a:.4f}"
            )

            # Block B: walk-forward n_restarts=1 vs n_restarts=N
            wf_r1_scores_b = np.array(
                [_ORDINAL_SCORE[wf_r1_by_ts[ts]] for ts in common_ts_b], dtype=float
            )
            wf_rN_scores_b = np.array(
                [_ORDINAL_SCORE[wf_rN_by_ts[ts]] for ts in common_ts_b], dtype=float
            )
            actual_b = np.array([fr_by_ts[ts] for ts in common_ts_b])

            wf_r1_stats_b = bootstrap_ic_stats(
                wf_r1_scores_b, actual_b, block_size, args.n_boot, args.seed
            )
            wf_rN_stats_b = bootstrap_ic_stats(
                wf_rN_scores_b, actual_b, block_size, args.n_boot, args.seed
            )
            paired_b = paired_bootstrap_ic_difference(
                wf_rN_scores_b, wf_r1_scores_b, actual_b, block_size, args.n_boot, args.seed
            )
            raw_agreement_b = _raw_agreement(
                [wf_r1_by_ts[ts] for ts in common_ts_b], [wf_rN_by_ts[ts] for ts in common_ts_b]
            )

            print(
                f"  Block B (walk-forward n_restarts=1 vs n_restarts={args.n_restarts}), "
                f"n={len(common_ts_b)}:\n"
                f"    n_restarts=1  point_ic={wf_r1_stats_b['point_ic']:.4f} "
                f"CI=[{wf_r1_stats_b['ci_lower']:.4f}, {wf_r1_stats_b['ci_upper']:.4f}]\n"
                f"    n_restarts={args.n_restarts}  point_ic={wf_rN_stats_b['point_ic']:.4f} "
                f"CI=[{wf_rN_stats_b['ci_lower']:.4f}, {wf_rN_stats_b['ci_upper']:.4f}]\n"
                f"    PAIRED diff (rN-r1)  point_diff={paired_b['point_diff']:.4f} "
                f"CI=[{paired_b['ci_lower']:.4f}, {paired_b['ci_upper']:.4f}] "
                f"rN_better={paired_b['a_significantly_better']} "
                f"r1_better={paired_b['b_significantly_better']}\n"
                f"    raw label agreement={raw_agreement_b:.4f}"
            )

            block_b_evaluated += 1
            if paired_b["a_significantly_better"]:
                block_b_a_better_count += 1

            cell_results.append(
                {
                    "symbol": symbol,
                    "tf": tf,
                    "aborted": False,
                    "n_obs": n,
                    "block_a": {
                        "n": len(common_ts_a),
                        "production": prod_stats_a,
                        "walk_forward_r1": wf_r1_stats_a,
                        "paired_diff": paired_a,
                        "raw_agreement": raw_agreement_a,
                    },
                    "block_b": {
                        "n": len(common_ts_b),
                        "walk_forward_r1": wf_r1_stats_b,
                        "walk_forward_rN": wf_rN_stats_b,
                        "paired_diff": paired_b,
                        "raw_agreement": raw_agreement_b,
                        "rN_significantly_better": bool(paired_b["a_significantly_better"]),
                    },
                }
            )

    print("\n" + "=" * 80)
    print("D-03 ATTRIBUTION")
    print("=" * 80)
    if block_b_evaluated == 0:
        print("No cells evaluated (all aborted) -- INCONCLUSIVE. alpha.hmm.n_restarts stays at 1.")
        overall = "INCONCLUSIVE"
    else:
        fraction = block_b_a_better_count / block_b_evaluated
        strict_majority = fraction > 0.5
        overall = "PREFER_MULTI_RESTART" if strict_majority else "INCONCLUSIVE"
        print(
            f"n_restarts=N significantly better than n_restarts=1 on "
            f"{block_b_a_better_count}/{block_b_evaluated} evaluated cells "
            f"({fraction:.1%})"
        )
        print(f"D-03 ATTRIBUTION: {overall}")
        if overall == "INCONCLUSIVE":
            print("alpha.hmm.n_restarts stays at 1 -- burden of proof is on the change.")
        else:
            print(
                "Multi-restart arm preferred on a strict majority of cells -- still "
                "requires an explicit APR change to alpha.hmm.n_restarts; this script "
                "does not change config_state."
            )
    print("=" * 80)

    _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_RESULTS_PATH, "w") as f:
        json.dump(
            {
                "n_restarts": args.n_restarts,
                "block_b_evaluated": block_b_evaluated,
                "block_b_a_better_count": block_b_a_better_count,
                "d03_attribution": overall,
                "cells": cell_results,
            },
            f,
            indent=2,
            default=str,
        )
    print(f"\nResults written to {_RESULTS_PATH}")

    conn.close()


if __name__ == "__main__":
    main()
