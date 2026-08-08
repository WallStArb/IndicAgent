"""HMM model-complexity identifiability sweep (Phase 171 follow-on, investigation-only).

WHY THIS EXISTS
---------------
`hmm_restart_convergence_pilot.py` established that best-of-N restart selection does NOT
converge corpus-wide at K=5/full-covariance: no tested N in {3,5,10,20} cleared a 0.90
cross-block agreement bar on every (symbol, tf) cell, and several cells were NON-MONOTONIC
(SMH/1h: 1.0000 at N=3,5 -> 0.0279 at N=10). That is the signature of near-tied competing
local optima with different label semantics -- a MODEL-IDENTIFIABILITY problem, which no
amount of restart compute fixes. The remaining lever is model complexity: fewer states
and/or fewer covariance parameters make the likelihood surface less multimodal.

METHODOLOGICAL CORRECTION vs. THE TWO PRIOR PILOTS (load-bearing)
-----------------------------------------------------------------
Both `hmm_walk_forward_seed_stability_pilot.py` and `hmm_restart_convergence_pilot.py` fit
GaussianHMM on `_build_obs_matrix`'s RAW output. Production does not. Every production fit
path in `services/regime_writer.py` standardizes first:

  * `_compute_symbol_tf`      -> `StandardScaler().fit_transform(obs_matrix)` (line ~1197)
  * `_walk_forward_hmm_full`  -> per-segment `StandardScaler` fit on the training prefix

The raw observation dimensions span ~5 orders of magnitude in scale (log_return ~1e-3,
realized_vol ~1e-2, momentum ~O(1), vol_of_vol ~1e-3, rel_volume ~O(0.5)). Full-covariance
Gaussian EM on that is badly conditioned -- which is a plausible driver of BOTH the
`covars must be symmetric, positive-definite` crashes AND the seed instability the prior
pilots measured. This script therefore standardizes by default (`--no-standardize` reruns
the prior pilots' unscaled convention for a controlled A/B), so its numbers describe the
model production actually fits.

It also compares SMOOTHED labels (`_smooth_states(min_hold_bars)` then `_build_label_map`)
-- the exact sequence that lands in `feature_vectors.regime` -- rather than the raw
alpha-pass argmax the prior pilots compared. Raw-decode agreement is still recorded so the
two conventions stay diffable.

METHOD
------
For each (symbol, tf) cell x (K, covariance_type) config: fit `--max-n` seeds from pool A
(base = alpha.hmm.random_state) and `--max-n` from a disjoint pool B (base 1000). Champion
per pool = highest (converged, log_likelihood) lexicographically, matching
`_compute_symbol_tf`'s own restart-selection preference. Because pools are seed PREFIXES,
best-of-N for every N in `--n-values` is derived from the same fitted set -- N=10 and N=20
cost 20 fits per pool, not 30.

Cross-K comparability: raw label agreement is NOT comparable across K (K=3 has a ~1/3
chance floor, K=5 ~1/5). Every cell therefore also reports the empirical chance baseline
(sum_l p_a(l) * p_b(l) over the two champions' own marginal label distributions) and
Cohen's kappa = (agreement - chance) / (1 - chance). A config must clear BOTH bars to be
declared identifiable, so low-K cannot win by chance inflation alone.

Read-only diagnostic: no `feature_vectors` writes, no `config_state` writes, no
`regime_writer.py` CLI invocation, no modification to `services/regime_writer.py`.

Usage:
    .venv/bin/python scripts/analysis/hmm_model_complexity_identifiability_sweep.py
    .venv/bin/python scripts/analysis/hmm_model_complexity_identifiability_sweep.py \
        --symbols SPY SMH XLE TLT --tf 1h --k-values 5 --cov-types full --n-values 10 --max-n 10
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

# BLAS threading inside a ProcessPoolExecutor worker oversubscribes the box (24 cores x
# N workers x BLAS threads) and makes wall-clock WORSE. Pinned before numpy is imported.
for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_var, "1")

import numpy as np  # noqa: E402
import psycopg  # noqa: E402
from hmmlearn.hmm import GaussianHMM  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

from services.regime_writer import (  # noqa: E402
    _alpha_pass_jit,
    _build_label_map,
    _build_obs_matrix,
    _check_occupation_gate,
    _compute_log_emit,
    _smooth_states,
    _stationary_distribution,
)
from src.config.settings import Settings  # noqa: E402

# ---------------------------------------------------------------------------
# Sweep scope -- same 16 cells as hmm_restart_convergence_pilot.py, for direct
# comparability against its already-recorded K=5/full numbers.
# ---------------------------------------------------------------------------

_DEFAULT_SYMBOLS = ["SPY", "IWM", "TLT", "GLD", "XLE", "EEM", "FXY", "SMH"]
_DEFAULT_TFS = ["1d", "1h"]
_DEFAULT_K_VALUES = [3, 4, 5]
_DEFAULT_COV_TYPES = ["full", "diag"]
_DEFAULT_N_VALUES = [5, 10, 20]

# Cross-block winner agreement bar -- inherited unchanged from
# hmm_restart_convergence_pilot.py so results are directly comparable.
_AGREEMENT_THRESHOLD = 0.90
# Chance-corrected bar. Required IN ADDITION to _AGREEMENT_THRESHOLD so a low-K config
# cannot clear the sweep purely by having a higher chance floor.
_KAPPA_THRESHOLD = 0.80

_RESULTS_PATH = Path("cache/hmm_model_complexity_identifiability_sweep.json")

_APR_FALLBACKS: dict[str, str] = {
    "feature.hmm.n_components": "5",
    "feature.hmm.covariance_type": "full",
    "feature.hmm.n_iter": "200",
    "alpha.hmm.random_state": "42",
    "feature.hmm.full_cov_min_obs": "500",
    "feature.hmm.min_hold_bars": "3",
    "feature.hmm.min_state_occupation": "0.05",
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

# Canonical label -> compact integer code. Comparing int8 arrays instead of lists of
# Python strings is what makes a 36k-bar x 40-fit cell cheap enough to sweep 6 configs.
_LABEL_CODES = {
    "trending_down": 0,
    "transition_down": 1,
    "ranging": 2,
    "transition_up": 3,
    "trending_up": 4,
}


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


def _free_param_count(k: int, d: int, cov_type: str) -> int:
    """GaussianHMM free-parameter count, for BIC. means K*d; covariances K*d*(d+1)/2 (full)
    or K*d (diag); transition matrix K*(K-1); initial distribution K-1."""
    cov_params = k * d * (d + 1) // 2 if cov_type == "full" else k * d
    return k * d + cov_params + k * (k - 1) + (k - 1)


def _fit_one(
    obs: np.ndarray,
    seed: int,
    k: int,
    cov_type: str,
    n_iter: int,
    min_hold_bars: int,
    min_state_occupation: float,
) -> dict | None:
    """One GaussianHMM fit + production-faithful decode. Returns None on a numerical
    failure (non-PD covariance, non-finite score) so the caller can exclude the seed from
    champion selection rather than let it win by default with a fabricated score.

    Decode mirrors `_compute_symbol_tf` exactly: stationary prior -> `_compute_log_emit`
    -> `_alpha_pass_jit` -> `_smooth_states(min_hold_bars)` -> `_build_label_map`. Both
    the smoothed (production-truth) and raw (prior-pilot convention) label codes are
    returned so the two conventions can be compared without refitting.
    """
    model = GaussianHMM(n_components=k, covariance_type=cov_type, n_iter=n_iter, random_state=seed)
    try:
        model.fit(obs)
        ll = float(model.score(obs))
        if not np.isfinite(ll):
            return None
        # hmmlearn 0.3.3: monitor_.converged is trivially True on a cap-hit; iter < n_iter
        # is the only real tolerance-convergence signal (todo 229, same test regime_writer uses).
        converged = bool(model.monitor_.iter < model.monitor_.n_iter)
        label_map = _build_label_map(model.means_)
        pi0 = _stationary_distribution(model.transmat_)
        log_emit = _compute_log_emit(obs, model.means_, model.covars_, cov_type)
        log_A = np.log(np.maximum(model.transmat_, 1e-300))
        raw_states, _ = _alpha_pass_jit(log_emit, log_A, pi0)
        smoothed_states = _smooth_states(raw_states, min_hold_bars)
        is_degenerate, gate_info = _check_occupation_gate(
            smoothed_states, k, min_state_occupation, converged
        )
        code_lut = np.array([_LABEL_CODES[label_map[i]] for i in range(k)], dtype=np.int8)
        return {
            "seed": seed,
            "ll": ll,
            "converged": converged,
            "degenerate": is_degenerate,
            "degenerate_reason": gate_info.get("reason"),
            "min_occupation": (
                min(gate_info["occupation"].values()) if "occupation" in gate_info else 0.0
            ),
            "codes_smoothed": code_lut[smoothed_states],
            "codes_raw": code_lut[raw_states],
        }
    except (np.linalg.LinAlgError, ValueError):
        return None


def _agreement_stats(codes_a: np.ndarray, codes_b: np.ndarray) -> dict:
    """Label agreement plus its chance correction. `chance` is the agreement two
    INDEPENDENT labelers with these same marginal label frequencies would reach by luck;
    kappa removes it, which is what makes K=3 and K=5 numbers comparable at all."""
    agreement = float(np.mean(codes_a == codes_b))
    n = len(codes_a)
    chance = 0.0
    for code in np.unique(np.concatenate([codes_a, codes_b])):
        chance += (np.count_nonzero(codes_a == code) / n) * (np.count_nonzero(codes_b == code) / n)
    kappa = (agreement - chance) / (1.0 - chance) if chance < 1.0 else 0.0
    return {"agreement": agreement, "chance": float(chance), "kappa": float(kappa)}


def _pick_champion(fits: list[dict | None], upto: int) -> dict | None:
    """Best of the first `upto` fits by (converged, log_likelihood) -- the same preference
    order `_compute_symbol_tf`'s own multi-seed restart loop applies (convergence wins,
    log-likelihood is the tiebreaker within a convergence status)."""
    best: dict | None = None
    for fit in fits[:upto]:
        if fit is None:
            continue
        if best is None or (fit["converged"], fit["ll"]) > (best["converged"], best["ll"]):
            best = fit
    return best


def _run_config_cell(job: dict) -> dict:
    """One (symbol, tf, K, covariance_type) job: fit both seed pools once at max_n, then
    derive every requested N's cross-block result from those same fits. Compute-only --
    no DB handle, no writes (CLAUDE.md ProcessPoolExecutor rule)."""
    obs = job["obs"]
    k, cov_type = job["k"], job["cov_type"]
    n_obs, d = obs.shape
    # Production's own diag fallback: full covariance is not attempted below full_cov_min_obs.
    eff_cov = cov_type if n_obs >= job["full_cov_min_obs"] else "diag"

    t0 = time.monotonic()
    pools: dict[str, list[dict | None]] = {}
    for pool_name, base in (("a", job["pool_a_base"]), ("b", job["pool_b_base"])):
        pools[pool_name] = [
            _fit_one(
                obs,
                base + i,
                k,
                eff_cov,
                job["n_iter"],
                job["min_hold_bars"],
                job["min_state_occupation"],
            )
            for i in range(job["max_n"])
        ]
    fit_seconds = time.monotonic() - t0

    n_params = _free_param_count(k, d, eff_cov)
    by_n: dict[str, dict] = {}
    for n in job["n_values"]:
        if n > job["max_n"]:
            continue
        champ_a = _pick_champion(pools["a"], n)
        champ_b = _pick_champion(pools["b"], n)
        if champ_a is None or champ_b is None:
            by_n[str(n)] = {
                "pool_failure": True,
                "pool_a_failed": champ_a is None,
                "pool_b_failed": champ_b is None,
                "agreement_smoothed": 0.0,
                "kappa_smoothed": 0.0,
            }
            continue
        smoothed = _agreement_stats(champ_a["codes_smoothed"], champ_b["codes_smoothed"])
        raw = _agreement_stats(champ_a["codes_raw"], champ_b["codes_raw"])
        by_n[str(n)] = {
            "pool_failure": False,
            "champion_seed_a": champ_a["seed"],
            "champion_seed_b": champ_b["seed"],
            "champion_ll_a": champ_a["ll"],
            "champion_ll_b": champ_b["ll"],
            "ll_relative_gap": abs(champ_a["ll"] - champ_b["ll"]) / max(abs(champ_a["ll"]), 1e-9),
            "bic_a": -2.0 * champ_a["ll"] + n_params * float(np.log(n_obs)),
            "bic_b": -2.0 * champ_b["ll"] + n_params * float(np.log(n_obs)),
            "agreement_smoothed": smoothed["agreement"],
            "chance_smoothed": smoothed["chance"],
            "kappa_smoothed": smoothed["kappa"],
            "agreement_raw": raw["agreement"],
            "kappa_raw": raw["kappa"],
            "degenerate_a": champ_a["degenerate"],
            "degenerate_b": champ_b["degenerate"],
            "min_occupation_a": champ_a["min_occupation"],
            "converged_a": champ_a["converged"],
            "converged_b": champ_b["converged"],
        }

    return {
        "symbol": job["symbol"],
        "tf": job["tf"],
        "k": k,
        "cov_type": cov_type,
        "effective_cov_type": eff_cov,
        "n_obs": n_obs,
        "n_free_params": n_params,
        "obs_per_param": n_obs / n_params,
        "n_failed_a": sum(1 for f in pools["a"] if f is None),
        "n_failed_b": sum(1 for f in pools["b"] if f is None),
        "fit_seconds": fit_seconds,
        "by_n": by_n,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=_DEFAULT_SYMBOLS)
    parser.add_argument("--tf", nargs="+", default=_DEFAULT_TFS)
    parser.add_argument("--k-values", nargs="+", type=int, default=_DEFAULT_K_VALUES)
    parser.add_argument("--cov-types", nargs="+", default=_DEFAULT_COV_TYPES)
    parser.add_argument("--n-values", nargs="+", type=int, default=_DEFAULT_N_VALUES)
    parser.add_argument(
        "--max-n",
        type=int,
        default=None,
        help="Seeds actually fit per pool (default: max of --n-values). Pools are seed "
        "prefixes, so every smaller N reuses these same fits.",
    )
    parser.add_argument("--pool-a-base", type=int, default=None)
    parser.add_argument("--pool-b-base", type=int, default=1000)
    parser.add_argument("--max-workers", type=int, default=12)
    parser.add_argument(
        "--no-standardize",
        action="store_true",
        help="Skip StandardScaler, reproducing the two prior pilots' (non-production) "
        "unscaled-fit convention. Exists only for a controlled A/B against their numbers.",
    )
    parser.add_argument("--results-path", default=str(_RESULTS_PATH))
    args = parser.parse_args()

    max_n = args.max_n if args.max_n is not None else max(args.n_values)
    settings = Settings()
    conn = psycopg.connect(settings.database_url)
    cfg = _load_config(conn)

    n_iter = int(cfg["feature.hmm.n_iter"])
    full_cov_min_obs = int(cfg["feature.hmm.full_cov_min_obs"])
    min_hold_bars = int(cfg["feature.hmm.min_hold_bars"])
    min_state_occupation = float(cfg["feature.hmm.min_state_occupation"])
    vol_window = int(cfg["feature.hmm.vol_window"])
    momentum_window = int(cfg["feature.hmm.obs_momentum_window"])
    vol_of_vol_window = int(cfg["feature.hmm.obs_vol_of_vol_window"])
    pool_a_base = (
        args.pool_a_base if args.pool_a_base is not None else int(cfg["alpha.hmm.random_state"])
    )

    standardize = not args.no_standardize
    print("=" * 96)
    print("HMM model-complexity identifiability sweep")
    print("=" * 96)
    print(
        f"k_values={args.k_values} cov_types={args.cov_types} n_values={args.n_values} max_n={max_n}"
    )
    print(f"standardize={standardize} (production `_compute_symbol_tf` standardizes: True)")
    print(
        f"n_iter={n_iter} full_cov_min_obs={full_cov_min_obs} min_hold_bars={min_hold_bars} "
        f"min_state_occupation={min_state_occupation}"
    )
    print(
        f"pool_a_base={pool_a_base} pool_b_base={args.pool_b_base} max_workers={args.max_workers}"
    )
    print(f"bars: agreement>={_AGREEMENT_THRESHOLD} AND kappa>={_KAPPA_THRESHOLD} (both required)")
    print("=" * 96)

    jobs: list[dict] = []
    for tf in args.tf:
        for symbol in args.symbols:
            timestamps, closes, volumes = _fetch_ohlcv(conn, symbol, tf)
            if not timestamps:
                print(f"SKIP {symbol}/{tf}: no OHLCV rows")
                continue
            obs, _ = _build_obs_matrix(
                timestamps,
                closes,
                volumes,
                vol_window=vol_window,
                momentum_window=momentum_window,
                vol_of_vol_window=vol_of_vol_window,
            )
            if standardize:
                obs = StandardScaler().fit_transform(obs)
            if len(obs) < max(args.k_values) * 50:
                print(f"SKIP {symbol}/{tf}: insufficient history n_obs={len(obs)}")
                continue
            print(f"loaded {symbol}/{tf}: n_obs={len(obs)}")
            for k in args.k_values:
                for cov_type in args.cov_types:
                    jobs.append(
                        {
                            "symbol": symbol,
                            "tf": tf,
                            "obs": obs,
                            "k": k,
                            "cov_type": cov_type,
                            "n_iter": n_iter,
                            "full_cov_min_obs": full_cov_min_obs,
                            "min_hold_bars": min_hold_bars,
                            "min_state_occupation": min_state_occupation,
                            "pool_a_base": pool_a_base,
                            "pool_b_base": args.pool_b_base,
                            "max_n": max_n,
                            "n_values": args.n_values,
                        }
                    )
    conn.close()

    # Heaviest jobs first: with a fixed worker pool, dispatching the long tail last leaves
    # workers idle at the end. n_obs * K * (full=heavier) is a good enough cost proxy.
    jobs.sort(
        key=lambda j: -(len(j["obs"]) * j["k"] * (3 if j["cov_type"] == "full" else 1)),
    )
    print(f"\n{len(jobs)} (cell x K x cov_type) jobs queued\n")

    results: list[dict] = []
    t_start = time.monotonic()
    with ProcessPoolExecutor(max_workers=args.max_workers) as pool:
        futures = {pool.submit(_run_config_cell, job): job for job in jobs}
        for done, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            top_n = str(max(n for n in args.n_values if n <= max_n))
            entry = result["by_n"].get(top_n, {})
            print(
                f"[{done}/{len(jobs)}] {result['symbol']}/{result['tf']} "
                f"K={result['k']} cov={result['effective_cov_type']} "
                f"N={top_n} agree={entry.get('agreement_smoothed', float('nan')):.4f} "
                f"kappa={entry.get('kappa_smoothed', float('nan')):.4f} "
                f"fails={result['n_failed_a']}+{result['n_failed_b']} "
                f"obs/param={result['obs_per_param']:.0f} "
                f"({result['fit_seconds']:.0f}s)",
                flush=True,
            )
    print(f"\nall jobs done in {time.monotonic() - t_start:.0f}s")

    _summarize(results, args.k_values, args.cov_types, args.n_values, max_n)

    out_path = Path(args.results_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(
            {
                "agreement_threshold": _AGREEMENT_THRESHOLD,
                "kappa_threshold": _KAPPA_THRESHOLD,
                "standardize": standardize,
                "k_values": args.k_values,
                "cov_types": args.cov_types,
                "n_values": args.n_values,
                "max_n": max_n,
                "pool_a_base": pool_a_base,
                "pool_b_base": args.pool_b_base,
                "results": results,
            },
            f,
            indent=2,
            default=str,
        )
    print(f"\nResults written to {out_path}")


def _passes(entry: dict) -> bool:
    return (
        not entry.get("pool_failure", True)
        and entry.get("agreement_smoothed", 0.0) >= _AGREEMENT_THRESHOLD
        and entry.get("kappa_smoothed", 0.0) >= _KAPPA_THRESHOLD
    )


def _summarize(
    results: list[dict], k_values: list[int], cov_types: list[str], n_values: list[int], max_n: int
) -> None:
    """Per-config corpus-wide verdicts, then a per-cell matrix. Headline is the MINIMUM
    across cells and the PASS COUNT, never an average -- an average hides exactly the
    non-identifiable cell this sweep exists to find (same convention as
    `_hmm_seed_stability_check` and both prior pilots)."""
    tested_ns = [n for n in n_values if n <= max_n]
    print("\n" + "=" * 96)
    print("PER-CONFIG SUMMARY (min across cells + pass count; minimum is the honest signal)")
    print("=" * 96)
    print(
        f"{'K':>2} {'cov':>5} {'N':>3} {'pass/cells':>11} {'min_agree':>10} {'min_kappa':>10}  worst_cell"
    )
    config_rows: list[dict] = []
    for k in k_values:
        for cov_type in cov_types:
            cells = [r for r in results if r["k"] == k and r["cov_type"] == cov_type]
            if not cells:
                continue
            for n in tested_ns:
                entries = [(r, r["by_n"].get(str(n), {})) for r in cells]
                n_pass = sum(1 for _, e in entries if _passes(e))
                worst = min(entries, key=lambda p: p[1].get("agreement_smoothed", 0.0))
                min_kappa = min(e.get("kappa_smoothed", 0.0) for _, e in entries)
                row = {
                    "k": k,
                    "cov_type": cov_type,
                    "n": n,
                    "n_pass": n_pass,
                    "n_cells": len(cells),
                    "min_agreement": worst[1].get("agreement_smoothed", 0.0),
                    "min_kappa": min_kappa,
                    "worst_cell": f"{worst[0]['symbol']}/{worst[0]['tf']}",
                }
                config_rows.append(row)
                print(
                    f"{k:>2} {cov_type:>5} {n:>3} {n_pass:>5}/{len(cells):<5} "
                    f"{row['min_agreement']:>10.4f} {row['min_kappa']:>10.4f}  {row['worst_cell']}"
                )

    if config_rows:
        best = max(config_rows, key=lambda r: (r["n_pass"], r["min_agreement"], -r["n"]))
        print(
            f"\nBEST CONFIG BY PASS COUNT: K={best['k']} cov={best['cov_type']} N={best['n']} "
            f"-> {best['n_pass']}/{best['n_cells']} cells identifiable "
            f"(min_agreement={best['min_agreement']:.4f}, worst={best['worst_cell']})"
        )

    n_top = max(tested_ns)
    print("\n" + "=" * 96)
    print(f"PER-CELL MATRIX at N={n_top} (agreement / kappa; * = passes both bars)")
    print("=" * 96)
    configs = [(k, c) for k in k_values for c in cov_types]
    header = f"{'cell':<10}" + "".join(f"{f'K{k}/{c[:4]}':>16}" for k, c in configs)
    print(header)
    cells = sorted({(r["symbol"], r["tf"]) for r in results}, key=lambda x: (x[1], x[0]))
    for symbol, tf in cells:
        line = f"{symbol + '/' + tf:<10}"
        for k, cov_type in configs:
            match = next(
                (
                    r
                    for r in results
                    if r["symbol"] == symbol
                    and r["tf"] == tf
                    and r["k"] == k
                    and r["cov_type"] == cov_type
                ),
                None,
            )
            if match is None:
                line += f"{'-':>16}"
                continue
            entry = match["by_n"].get(str(n_top), {})
            mark = "*" if _passes(entry) else " "
            line += (
                f"{entry.get('agreement_smoothed', 0.0):>7.3f}/"
                f"{entry.get('kappa_smoothed', 0.0):>6.3f}{mark}"
            )
        print(line)

    print("\n" + "=" * 96)
    print(
        f"PER-SYMBOL BEST CONFIG at N={n_top} (does a UNIFORM K survive, or must K be per-symbol?)"
    )
    print("=" * 96)
    for symbol, tf in cells:
        options = []
        for k, cov_type in configs:
            match = next(
                (
                    r
                    for r in results
                    if r["symbol"] == symbol
                    and r["tf"] == tf
                    and r["k"] == k
                    and r["cov_type"] == cov_type
                ),
                None,
            )
            if match is None:
                continue
            entry = match["by_n"].get(str(n_top), {})
            if _passes(entry):
                options.append((k, cov_type, entry.get("bic_a", float("inf")), entry))
        if not options:
            print(f"{symbol}/{tf:<4}: NO CONFIG IDENTIFIABLE -> quarantine candidate")
            continue
        # Smallest K that identifies; BIC breaks ties within that K.
        options.sort(key=lambda o: (o[0], o[2]))
        k, cov_type, bic, entry = options[0]
        others = ", ".join(f"K{o[0]}/{o[1]}" for o in options[1:])
        print(
            f"{symbol}/{tf:<4}: smallest identifiable = K={k} cov={cov_type} "
            f"(agree={entry['agreement_smoothed']:.4f} kappa={entry['kappa_smoothed']:.4f} "
            f"BIC={bic:.0f}){'  also: ' + others if others else ''}"
        )
    print("=" * 96)


if __name__ == "__main__":
    main()
