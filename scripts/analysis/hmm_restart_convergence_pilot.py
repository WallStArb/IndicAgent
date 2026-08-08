"""HMM multi-start-EM restart-convergence pilot (Phase 171 follow-on).

Context: `hmm_walk_forward_seed_stability_pilot.py --full-history` proved the seed
instability found in the walk-forward candidate is NOT walk-forward-specific -- it is a
property of `_compute_symbol_tf`'s CURRENT PRODUCTION single-seed fit
(`alpha.hmm.n_restarts=1`). 10/16 tested (symbol, tf) cells failed the same
seed-stability gate at full production scope (entire history, `full_cov_min_obs=500`),
corpus-wide minimum agreement 0.0000 at XLE/1d -- i.e. `feature_vectors.regime` today may
already be an artifact of which local optimum `alpha.hmm.random_state=42`'s single EM run
happened to land in, never validated.

This is the standard, textbook engineering response to non-convex EM local optima:
multi-start fitting, keep the highest-log-likelihood winner. But "more restarts" is a
hypothesis, not an assumption -- if the likelihood surface has multiple comparably-good
optima, best-of-N-by-log-likelihood can ITSELF be seed-dependent (a different N-seed pool
picks a different "best"). The only way to know whether a given N has actually converged
is to run best-of-N selection TWICE, from two disjoint seed pools, and check whether the
two winners agree. Raw single-seed pairwise agreement (what the seed-stability pilot
measures) answers a different, easier question ("is any one seed reliable") -- this script
answers the one that actually determines a safe `alpha.hmm.n_restarts` value ("does
restart-selection itself converge").

Method per (symbol, tf, N): fit N seeds from pool A (base_seed_a + 0..N-1), keep the
highest-log-likelihood model's labels as champion_a. Repeat independently for pool B
(base_seed_b + 0..N-1) -> champion_b. cross_block_agreement = fraction of bars where
champion_a and champion_b assign the same canonical label (via _build_label_map, so raw
state-index permutation is not the metric -- same canonicalization discipline as
_hmm_seed_stability_check). Sweep N over a small grid; report the smallest N at which
cross_block_agreement clears a genuine-convergence bar (0.90) on EVERY tested cell, not
an average -- consistent with this project's "minimum, not average, is the honest signal"
convention (`_hmm_seed_stability_check`'s own docstring, `hmm_walk_forward_seed_stability_
pilot.py`'s corpus-wide summary).

Uses the SAME reusable decode primitives `_hmm_seed_stability_check` already depends on
(`_build_label_map`, `_stationary_distribution`, `_compute_log_emit`, `_alpha_pass_jit`),
imported directly from `services.regime_writer` rather than reimplementing the alpha-pass
decode math -- this script adds a different SELECTION strategy on top of the same fit/decode
primitives, it does not duplicate them.

Read-only diagnostic: no `feature_vectors` writes, no `config_state` writes, no
`regime_writer.py` CLI invocation, no modification to `services/regime_writer.py`.

Usage:
    .venv/bin/python scripts/analysis/hmm_restart_convergence_pilot.py
    .venv/bin/python scripts/analysis/hmm_restart_convergence_pilot.py --symbols SPY XLE --tf 1d --n-values 3 5 10
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np  # noqa: E402
import psycopg  # noqa: E402
from hmmlearn.hmm import GaussianHMM  # noqa: E402

from services.regime_writer import (  # noqa: E402
    _alpha_pass_jit,
    _build_label_map,
    _build_obs_matrix,
    _compute_log_emit,
    _stationary_distribution,
)
from src.config.settings import Settings  # noqa: E402

# ---------------------------------------------------------------------------
# Pilot scope -- same 8-symbol set as hmm_walk_forward_seed_stability_pilot.py,
# for direct comparability against its already-recorded full-history results.
# ---------------------------------------------------------------------------

_DEFAULT_SYMBOLS = ["SPY", "IWM", "TLT", "GLD", "XLE", "EEM", "FXY", "SMH"]
_DEFAULT_TFS = ["1d", "1h"]
_DEFAULT_N_VALUES = [3, 5, 10, 20]

# Genuine-convergence bar: cross-block winner agreement must clear this on EVERY cell
# for a given N to be declared safe. Deliberately far above the seed-stability pilot's
# 0.25 chance-baseline gate -- that gate catches noise, this one validates convergence.
_CONVERGENCE_THRESHOLD = 0.90

_RESULTS_PATH = Path("cache/hmm_restart_convergence_pilot_results.json")

_APR_FALLBACKS: dict[str, str] = {
    "feature.hmm.n_components": "5",
    "feature.hmm.covariance_type": "full",
    "feature.hmm.n_iter": "200",
    "alpha.hmm.random_state": "42",
    "feature.hmm.full_cov_min_obs": "500",
    "feature.hmm.vol_window": "20",
    "feature.hmm.obs_momentum_window": "20",
    "feature.hmm.obs_vol_of_vol_window": "20",
}

_FETCH_OHLCV_SQL = """
SELECT timestamp, close, volume
FROM market_data_ohlcv_tradeable
WHERE symbol = %s AND timeframe = %s
ORDER BY timestamp ASC
"""


def _load_config(conn: psycopg.Connection) -> dict[str, str]:
    cfg = dict(_APR_FALLBACKS)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT config_key, config_value FROM config_state "
            "WHERE config_key LIKE 'feature.hmm.%' OR config_key LIKE 'alpha.hmm.%'"
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
    with conn.cursor(f"ohlcv_stream_{symbol}_{tf}") as cur:
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


def _fit_one_seed(
    obs_matrix: np.ndarray,
    seed: int,
    n_components: int,
    covariance_type: str,
    n_iter: int,
    full_cov_min_obs: int,
) -> tuple[float, list[str]] | None:
    """Fit a single GaussianHMM at `seed`, return (log_likelihood, canonical_labels).
    Returns None on a numerical failure (non-PD covariance / nan startprob) so the
    caller can exclude this seed from champion selection rather than let it win by
    default via a fabricated -inf score."""
    eff_cov_type = covariance_type if len(obs_matrix) >= full_cov_min_obs else "diag"
    model = GaussianHMM(
        n_components=n_components,
        covariance_type=eff_cov_type,
        n_iter=n_iter,
        random_state=seed,
    )
    try:
        model.fit(obs_matrix)
        ll = float(model.score(obs_matrix))
        if not np.isfinite(ll):
            return None
        label_map = _build_label_map(model.means_)
        pi0 = _stationary_distribution(model.transmat_)
        log_emit = _compute_log_emit(obs_matrix, model.means_, model.covars_, eff_cov_type)
        log_A = np.log(np.maximum(model.transmat_, 1e-300))
        raw_states, _ = _alpha_pass_jit(log_emit, log_A, pi0)
        labels = [label_map[int(s)] for s in raw_states]
        return ll, labels
    except (np.linalg.LinAlgError, ValueError):
        return None


def _best_of_n(
    obs_matrix: np.ndarray,
    seeds: list[int],
    n_components: int,
    covariance_type: str,
    n_iter: int,
    full_cov_min_obs: int,
) -> tuple[int, float, list[str]] | None:
    """Fit every seed in `seeds`, return (winning_seed, its_log_likelihood, its_labels)
    for the highest-log-likelihood successful fit. None if every seed in this pool
    numerically failed -- a pool-wide failure is itself a finding (recorded by the
    caller), not silently treated as "no signal"."""
    best: tuple[int, float, list[str]] | None = None
    for seed in seeds:
        result = _fit_one_seed(
            obs_matrix, seed, n_components, covariance_type, n_iter, full_cov_min_obs
        )
        if result is None:
            continue
        ll, labels = result
        if best is None or ll > best[1]:
            best = (seed, ll, labels)
    return best


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=_DEFAULT_SYMBOLS)
    parser.add_argument("--tf", nargs="+", default=_DEFAULT_TFS)
    parser.add_argument(
        "--n-values",
        nargs="+",
        type=int,
        default=_DEFAULT_N_VALUES,
        help="Restart-pool sizes to sweep (each tested with two independent seed pools).",
    )
    parser.add_argument(
        "--pool-a-base",
        type=int,
        default=None,
        help="Base seed for restart pool A (default: alpha.hmm.random_state).",
    )
    parser.add_argument(
        "--pool-b-base",
        type=int,
        default=1000,
        help="Base seed for restart pool B, deliberately far from pool A's range so the "
        "two pools never overlap even at the largest --n-values swept (default 1000).",
    )
    args = parser.parse_args()

    settings = Settings()
    conn = psycopg.connect(settings.database_url)
    cfg = _load_config(conn)

    n_components = int(cfg["feature.hmm.n_components"])
    covariance_type = cfg["feature.hmm.covariance_type"]
    n_iter = int(cfg["feature.hmm.n_iter"])
    hmm_random_state = int(cfg["alpha.hmm.random_state"])
    full_cov_min_obs = int(cfg["feature.hmm.full_cov_min_obs"])
    vol_window = int(cfg["feature.hmm.vol_window"])
    momentum_window = int(cfg["feature.hmm.obs_momentum_window"])
    vol_of_vol_window = int(cfg["feature.hmm.obs_vol_of_vol_window"])

    pool_a_base = args.pool_a_base if args.pool_a_base is not None else hmm_random_state
    pool_b_base = args.pool_b_base

    print("=" * 80)
    print("HMM restart-convergence pilot (does best-of-N selection itself converge?)")
    print("=" * 80)
    print(
        f"n_components={n_components} covariance_type={covariance_type} n_iter={n_iter} "
        f"full_cov_min_obs={full_cov_min_obs}"
    )
    print(f"pool_a_base={pool_a_base} pool_b_base={pool_b_base} n_values={args.n_values}")
    print(f"convergence_threshold={_CONVERGENCE_THRESHOLD} (cross-block winner label agreement)")
    print(f"symbols={args.symbols} tfs={args.tf}")
    print("=" * 80)

    cell_results: list[dict] = []
    # Per-N, the minimum cross_block_agreement seen across every tested cell -- the
    # number that actually decides whether that N is safe corpus-wide.
    per_n_min: dict[int, float] = {n: 1.0 for n in args.n_values}
    per_n_min_cell: dict[int, tuple[str, str]] = {}

    for tf in args.tf:
        for symbol in args.symbols:
            print(f"\n--- {symbol} {tf} ---")
            timestamps, closes, volumes = _fetch_ohlcv(conn, symbol, tf)
            if not timestamps:
                print("  SKIP: no OHLCV rows")
                cell_results.append({"symbol": symbol, "tf": tf, "skipped": True})
                continue

            obs_matrix, _ = _build_obs_matrix(
                timestamps,
                closes,
                volumes,
                vol_window=vol_window,
                momentum_window=momentum_window,
                vol_of_vol_window=vol_of_vol_window,
            )
            n_obs = len(obs_matrix)
            if n_obs < n_components * 10:
                print(f"  SKIP: insufficient history n_obs={n_obs}")
                cell_results.append({"symbol": symbol, "tf": tf, "skipped": True, "n_obs": n_obs})
                continue
            print(f"  n_obs={n_obs} (full history, same scope as production single-fit)")

            n_results: dict[int, dict] = {}
            for n in args.n_values:
                t0 = time.monotonic()
                pool_a = [pool_a_base + i for i in range(n)]
                pool_b = [pool_b_base + i for i in range(n)]
                champ_a = _best_of_n(
                    obs_matrix, pool_a, n_components, covariance_type, n_iter, full_cov_min_obs
                )
                champ_b = _best_of_n(
                    obs_matrix, pool_b, n_components, covariance_type, n_iter, full_cov_min_obs
                )
                elapsed = time.monotonic() - t0

                if champ_a is None or champ_b is None:
                    print(
                        f"  N={n}: POOL FAILURE (pool_a={'ok' if champ_a else 'ALL FAILED'}, "
                        f"pool_b={'ok' if champ_b else 'ALL FAILED'}) elapsed={elapsed:.1f}s"
                    )
                    n_results[n] = {
                        "pool_failure": True,
                        "pool_a_failed": champ_a is None,
                        "pool_b_failed": champ_b is None,
                        "cross_block_agreement": 0.0,
                        "elapsed_seconds": elapsed,
                    }
                    per_n_min[n] = min(per_n_min[n], 0.0)
                    per_n_min_cell.setdefault(n, (symbol, tf))
                    if per_n_min[n] == 0.0:
                        per_n_min_cell[n] = (symbol, tf)
                    continue

                seed_a, ll_a, labels_a = champ_a
                seed_b, ll_b, labels_b = champ_b
                agree = sum(1 for x, y in zip(labels_a, labels_b) if x == y) / len(labels_a)
                print(
                    f"  N={n}: champion_a=seed{seed_a}(ll={ll_a:.1f}) "
                    f"champion_b=seed{seed_b}(ll={ll_b:.1f}) "
                    f"cross_block_agreement={agree:.4f} elapsed={elapsed:.1f}s"
                )
                n_results[n] = {
                    "pool_failure": False,
                    "champion_seed_a": seed_a,
                    "champion_ll_a": ll_a,
                    "champion_seed_b": seed_b,
                    "champion_ll_b": ll_b,
                    "cross_block_agreement": agree,
                    "elapsed_seconds": elapsed,
                }
                if agree < per_n_min[n]:
                    per_n_min[n] = agree
                    per_n_min_cell[n] = (symbol, tf)

            cell_results.append(
                {"symbol": symbol, "tf": tf, "skipped": False, "n_obs": n_obs, "by_n": n_results}
            )

    print("\n" + "=" * 80)
    print("CORPUS-WIDE SUMMARY (minimum cross_block_agreement per N -- the honest signal)")
    print("=" * 80)
    smallest_converged_n = None
    for n in args.n_values:
        worst_symbol, worst_tf = per_n_min_cell.get(n, ("(none)", "(none)"))
        verdict = "CONVERGED" if per_n_min[n] >= _CONVERGENCE_THRESHOLD else "NOT CONVERGED"
        print(
            f"N={n}: MIN cross_block_agreement={per_n_min[n]:.4f} at {worst_symbol}/{worst_tf} "
            f"-> {verdict} (bar={_CONVERGENCE_THRESHOLD})"
        )
        if verdict == "CONVERGED" and smallest_converged_n is None:
            smallest_converged_n = n
    if smallest_converged_n is not None:
        print(f"\nSMALLEST CONVERGED N: {smallest_converged_n}")
    else:
        print("\nNO TESTED N CONVERGED on every cell -- restart-count alone does not resolve this.")
    print("=" * 80)

    _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_RESULTS_PATH, "w") as f:
        json.dump(
            {
                "convergence_threshold": _CONVERGENCE_THRESHOLD,
                "n_values": args.n_values,
                "pool_a_base": pool_a_base,
                "pool_b_base": pool_b_base,
                "per_n_min_cross_block_agreement": {
                    str(n): {
                        "min_agreement": per_n_min[n],
                        "worst_cell": list(per_n_min_cell.get(n, (None, None))),
                    }
                    for n in args.n_values
                },
                "smallest_converged_n": smallest_converged_n,
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
