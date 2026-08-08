"""HMM regime-AXIS decomposition identifiability sweep (Phase 171 follow-on, investigation-only).

WHY THIS EXISTS
---------------
`hmm_model_complexity_identifiability_sweep.py` established that production's composite
5-column observation model is non-identifiable at K=5/full (9 of 16 (symbol, tf) cells fail
a two-pool cross-block agreement gate) and identifiable at K=3/full (16/16). It did NOT ask
*why* K=5 fails.

`_build_obs_matrix` fuses three loosely-related signal families into one joint ordinal state
chain:

    col 0  log_return    -> TREND/direction
    col 1  realized_vol  -> VOLATILITY
    col 2  momentum      -> TREND/direction
    col 3  vol_of_vol    -> VOLATILITY
    col 4  rel_volume    -> VOLUME

Hypothesis under test: the composite model's identifiability failure is driven primarily by
forcing these three families to compromise into ONE partition. Volatility clustering is one of
the most robust patterns in financial data (calm vs turbulent genuinely separate); direction is
close to a random walk and inherently far noisier; volume sits between. If that is the
mechanism, then fitting each family in isolation should show volatility identifying cleanly at
low K with large margin, volume intermediate, and trend as the hard axis -- and the composite
model's failure is then explained as the well-separated volatility signal being dragged into a
near-tied partition by the noisy directional signal.

Falsification looks like: every axis identifies just as easily as the composite K=3 model (the
family fusion was never the problem, K alone was), or trend identifies cleanly in isolation
(the noise story is wrong).

METHOD (inherited unchanged from the complexity sweep so numbers are directly comparable)
-----------------------------------------------------------------------------------------
Per (symbol, tf) x axis x (K, covariance_type):

1. Build `_build_obs_matrix`, slice the axis's columns, then `StandardScaler().fit_transform`
   (production parity -- `_compute_symbol_tf` standardizes, and StandardScaler is per-column so
   slice-then-scale and scale-then-slice are identical).
2. Fit `--max-n` seeds from pool A (base = `alpha.hmm.random_state`) and `--max-n` from a
   disjoint pool B (base 1000). Champion per pool = highest (converged, log_likelihood),
   matching `_compute_symbol_tf`'s own restart preference.
3. Decode production-faithfully: stationary prior -> `_compute_log_emit` -> `_alpha_pass_jit`
   -> `_smooth_states(min_hold_bars)` -> `_build_label_map`.
4. Cross-block agreement + Cohen's kappa between the two pools' champions.
   Bars (BOTH required): agreement >= 0.90 AND kappa >= 0.80.

Headline convention: the MINIMUM across cells and the PASS COUNT, never an average -- an
average hides exactly the non-identifiable cell this sweep exists to find.

CANONICALIZATION NOTE
---------------------
`_build_label_map` ranks states by fitted `means[:, 0]`. Column 0 of each axis slice is that
axis's primary dimension (trend -> log_return, volatility -> realized_vol, volume ->
rel_volume), so the map is a rank-ordering canonicalization on the right variable for every
axis. The emitted *strings* stay composite-flavoured ("trending_up" on the volatility axis
actually means "highest-realized-vol state"); only the ordinal rank matters for agreement, and
`_AXIS_LABEL_GLOSS` records the per-axis reading for the writeup.

MECHANISM DIAGNOSTICS (new here, beyond the complexity sweep)
-------------------------------------------------------------
* `min_state_separation` -- min over state pairs of the Mahalanobis distance between fitted
  means under the occupation-weighted pooled covariance. "How many pooled sigmas apart are the
  two closest states." Large = genuinely distinct clusters; < ~1 = overlapping blobs, which is
  the geometric precondition for a flat, multi-optimum likelihood surface.
* `distinct_solutions_a` -- number of semantically distinct labelings among pool A's own N
  fits (single-linkage clustering at >= 0.99 pairwise agreement). 1 = EM always lands on the
  same solution; >1 = genuine multimodality, and the champion choice is a coin flip among them.
* `ll_spread_relative_a` -- (max ll - min ll) / |max ll| across pool A. Near-zero spread
  alongside distinct_solutions > 1 is the formal near-tied-competing-optima signature.

Read-only diagnostic: no `feature_vectors` writes, no `config_state` writes, no
`regime_writer.py` CLI invocation, no modification to `services/regime_writer.py`.

Usage:
    .venv/bin/python scripts/analysis/hmm_regime_axis_decomposition_identifiability_sweep.py
    .venv/bin/python scripts/analysis/hmm_regime_axis_decomposition_identifiability_sweep.py \
        --axes volatility trend --symbols SPY SMH --tf 1h --max-workers 8
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np  # noqa: E402
import psycopg  # noqa: E402
from hmmlearn.hmm import GaussianHMM  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

from services._batch_utils import make_worker_pool as _make_worker_pool  # noqa: E402
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

# todo 216: BLAS thread cap, see make_worker_pool()/limit_blas_threads() -- a bare pool
# construction silently reintroduces the OpenBLAS oversubscription bug (24 cores x
# N workers x default BLAS threads); this is the project-wide fix, applied per-worker
# via the pool's initializer rather than a module-level env-var guess.
_BLAS_THREADS_PER_WORKER = 1

# ---------------------------------------------------------------------------
# Axis decomposition of `_build_obs_matrix`'s 5 columns.
# ---------------------------------------------------------------------------
# Column 0 of each slice is the axis's primary/ordering dimension -- see the
# CANONICALIZATION NOTE in the module docstring.
_AXIS_COLUMNS: dict[str, tuple[int, ...]] = {
    "composite": (0, 1, 2, 3, 4),  # control arm: production's own observation model
    "trend": (0, 2),  # log_return, momentum
    "volatility": (1, 3),  # realized_vol, vol_of_vol
    "volume": (4,),  # rel_volume
    # Follow-on question the isolated-axis results raised but didn't answer: volume never
    # identifies on its own (no K clears both bars), yet the full 5-column composite DOES
    # identify at K=3. Is volume neutral filler the composite fit tolerates, or is it an
    # actively noisy dimension quietly costing the composite headroom (fewer reliably
    # identifiable states than a volume-free model could support)? composite minus volume,
    # swept at K=3/4/5, answers it directly: same pass count as composite at K=3 -> volume
    # was neutral; passes at K=4 or K=5 where composite failed -> volume was a drag.
    "trend_volatility": (0, 1, 2, 3),  # log_return, realized_vol, momentum, vol_of_vol
}

_AXIS_LABEL_GLOSS: dict[str, str] = {
    "composite": "trending_down .. trending_up (production semantics)",
    "trend": "trending_down .. trending_up (log_return rank)",
    "volatility": "calmest .. most turbulent (realized_vol rank)",
    "volume": "lightest .. heaviest (rel_volume rank)",
    "trend_volatility": "trending_down .. trending_up, cross-cut by volatility (composite minus volume)",
}

# Per-axis K grid. Volatility/volume are hypothesized to need only 2-3 states
# (calm/elevated/turbulent, normal/elevated); trend is swept over the same range the
# composite sweep used because it is the axis most likely to still struggle. The
# composite control replicates the two configurations the complexity sweep decided
# between, so this run re-derives its headline on the same data.
_DEFAULT_AXIS_K_VALUES: dict[str, list[int]] = {
    "composite": [3, 5],
    "trend": [2, 3, 4, 5],
    "volatility": [2, 3, 4],
    "volume": [2, 3],
    # Swept up through 5 (composite's original, non-identifiable ceiling) specifically to
    # test whether dropping volume recovers headroom above composite's K=3 result.
    "trend_volatility": [3, 4, 5],
}

# Per-axis covariance grid. `volume` is 1-DIMENSIONAL: a 1x1 "full" covariance IS a
# diagonal covariance (identical free-parameter count, identical likelihood), so `full`
# there is redundant by construction. It is swept anyway, once, as an empirical check that
# hmmlearn agrees -- see the volume-axis equivalence assertion in _summarize().
_DEFAULT_AXIS_COV_TYPES: dict[str, list[str]] = {
    "composite": ["full"],
    "trend": ["full", "diag"],
    "volatility": ["full", "diag"],
    "volume": ["full", "diag"],
    # full only, matching composite/production's own choice -- diag was already shown not
    # to help on any axis tested so far, no reason to re-litigate it here.
    "trend_volatility": ["full"],
}

_DEFAULT_SYMBOLS = ["SPY", "IWM", "TLT", "GLD", "XLE", "EEM", "FXY", "SMH"]
_DEFAULT_TFS = ["1d", "1h"]
_DEFAULT_N_VALUES = [5, 10, 20]

# Bars inherited unchanged from hmm_model_complexity_identifiability_sweep.py so the two
# sweeps' verdicts are directly comparable.
_AGREEMENT_THRESHOLD = 0.90
_KAPPA_THRESHOLD = 0.80

# Two fits count as the same "solution" when their smoothed labelings agree on >= this
# fraction of bars. 0.99 is deliberately strict: near-tied optima that differ on 1% of bars
# are the same semantic partition, optima that differ on 20%+ are not.
_SOLUTION_IDENTITY_AGREEMENT = 0.99

_RESULTS_PATH = Path("cache/hmm_regime_axis_decomposition_identifiability_sweep.json")

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


def _covars_as_full(covars: np.ndarray, k: int, d: int) -> np.ndarray:
    """(K, d, d) view of a fitted model's covariances regardless of covariance_type.

    hmmlearn stores diag covars as (K, d) on some paths and (K, d, d) with zeroed
    off-diagonals on others; both are normalized here so the separation metric has one
    code path.
    """
    if covars.ndim == 3:
        return covars
    out = np.zeros((k, d, d))
    idx = np.arange(d)
    out[:, idx, idx] = covars
    return out


def _min_state_separation(means: np.ndarray, covars: np.ndarray, occupation: np.ndarray) -> float:
    """Min pairwise Mahalanobis distance between fitted state means under the
    occupation-weighted pooled covariance.

    Reads as "how many pooled standard deviations apart are the two closest states". This
    is the geometric quantity behind identifiability: states that overlap in observation
    space give a flat likelihood surface on which many different partitions score almost
    identically, which is exactly the near-tied-competing-optima pathology being diagnosed.
    """
    k, d = means.shape
    if k < 2:
        return float("inf")
    cov_full = _covars_as_full(covars, k, d)
    weights = occupation / max(occupation.sum(), 1e-12)
    pooled = np.tensordot(weights, cov_full, axes=(0, 0)) + np.eye(d) * 1e-9
    try:
        pooled_inv = np.linalg.inv(pooled)
    except np.linalg.LinAlgError:
        return float("nan")
    best = float("inf")
    for i in range(k):
        for j in range(i + 1, k):
            diff = means[i] - means[j]
            dist2 = float(diff @ pooled_inv @ diff)
            best = min(best, float(np.sqrt(max(dist2, 0.0))))
    return best


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
    -> `_alpha_pass_jit` -> `_smooth_states(min_hold_bars)` -> `_build_label_map`.
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
        occupation = np.array(
            [np.count_nonzero(smoothed_states == i) for i in range(k)], dtype=float
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
            "separation": _min_state_separation(model.means_, model.covars_, occupation),
            "codes_smoothed": code_lut[smoothed_states],
            "codes_raw": code_lut[raw_states],
        }
    except (np.linalg.LinAlgError, ValueError):
        return None


def _agreement_stats(codes_a: np.ndarray, codes_b: np.ndarray) -> dict:
    """Label agreement plus its chance correction. `chance` is the agreement two
    INDEPENDENT labelers with these same marginal label frequencies would reach by luck;
    kappa removes it, which is what makes K=2 and K=5 numbers comparable at all."""
    agreement = float(np.mean(codes_a == codes_b))
    n = len(codes_a)
    chance = 0.0
    for code in np.unique(np.concatenate([codes_a, codes_b])):
        chance += (np.count_nonzero(codes_a == code) / n) * (np.count_nonzero(codes_b == code) / n)
    kappa = (agreement - chance) / (1.0 - chance) if chance < 1.0 else 0.0
    return {"agreement": agreement, "chance": float(chance), "kappa": float(kappa)}


def _pick_champion(fits: list[dict | None], upto: int) -> dict | None:
    """Best of the first `upto` fits by (converged, log_likelihood) -- the same preference
    order `_compute_symbol_tf`'s own multi-seed restart loop applies."""
    best: dict | None = None
    for fit in fits[:upto]:
        if fit is None:
            continue
        if best is None or (fit["converged"], fit["ll"]) > (best["converged"], best["ll"]):
            best = fit
    return best


def _count_distinct_solutions(fits: list[dict | None], upto: int) -> int:
    """Number of semantically distinct labelings among the first `upto` fits of one pool.

    Single-linkage: two fits join the same solution when they agree on
    >= _SOLUTION_IDENTITY_AGREEMENT of bars. 1 means EM always lands on the same partition
    and the champion choice is immaterial; >1 means the champion choice is picking among
    incompatible semantics, and which one wins is a property of the seed, not the data.
    """
    valid = [f for f in fits[:upto] if f is not None]
    if not valid:
        return 0
    parent = list(range(len(valid)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(len(valid)):
        for j in range(i + 1, len(valid)):
            same = np.mean(valid[i]["codes_smoothed"] == valid[j]["codes_smoothed"])
            if same >= _SOLUTION_IDENTITY_AGREEMENT:
                parent[find(i)] = find(j)
    return len({find(i) for i in range(len(valid))})


def _run_config_cell(job: dict) -> dict:
    """One (symbol, tf, axis, K, covariance_type) job: fit both seed pools once at max_n,
    then derive every requested N's cross-block result from those same fits. Compute-only --
    no DB handle, no writes (CLAUDE.md worker-pool rule)."""
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
        lls_a = [f["ll"] for f in pools["a"][:n] if f is not None]
        by_n[str(n)] = {
            "pool_failure": False,
            "champion_seed_a": champ_a["seed"],
            "champion_seed_b": champ_b["seed"],
            "champion_ll_a": champ_a["ll"],
            "champion_ll_b": champ_b["ll"],
            "ll_relative_gap": abs(champ_a["ll"] - champ_b["ll"]) / max(abs(champ_a["ll"]), 1e-9),
            "ll_spread_relative_a": (
                (max(lls_a) - min(lls_a)) / max(abs(max(lls_a)), 1e-9) if lls_a else 0.0
            ),
            "distinct_solutions_a": _count_distinct_solutions(pools["a"], n),
            "distinct_solutions_b": _count_distinct_solutions(pools["b"], n),
            "bic_a": -2.0 * champ_a["ll"] + n_params * float(np.log(n_obs)),
            "bic_b": -2.0 * champ_b["ll"] + n_params * float(np.log(n_obs)),
            "agreement_smoothed": smoothed["agreement"],
            "chance_smoothed": smoothed["chance"],
            "kappa_smoothed": smoothed["kappa"],
            "agreement_raw": raw["agreement"],
            "kappa_raw": raw["kappa"],
            "degenerate_a": champ_a["degenerate"],
            "degenerate_b": champ_b["degenerate"],
            "degenerate_reason_a": champ_a["degenerate_reason"],
            "min_occupation_a": champ_a["min_occupation"],
            "min_occupation_b": champ_b["min_occupation"],
            "separation_a": champ_a["separation"],
            "separation_b": champ_b["separation"],
            "converged_a": champ_a["converged"],
            "converged_b": champ_b["converged"],
        }

    return {
        "symbol": job["symbol"],
        "tf": job["tf"],
        "axis": job["axis"],
        "k": k,
        "cov_type": cov_type,
        "effective_cov_type": eff_cov,
        "n_obs": n_obs,
        "n_dims": d,
        "n_free_params": n_params,
        "obs_per_param": n_obs / n_params,
        "n_failed_a": sum(1 for f in pools["a"] if f is None),
        "n_failed_b": sum(1 for f in pools["b"] if f is None),
        "fit_seconds": fit_seconds,
        "by_n": by_n,
    }


def _passes(entry: dict) -> bool:
    return (
        not entry.get("pool_failure", True)
        and entry.get("agreement_smoothed", 0.0) >= _AGREEMENT_THRESHOLD
        and entry.get("kappa_smoothed", 0.0) >= _KAPPA_THRESHOLD
    )


def _parse_axis_grid(raw: str | None, default: dict[str, list[int]]) -> dict[str, list[int]]:
    """Parse an `axis:v1,v2;axis:v3` override into a per-axis grid, defaulting per axis."""
    if not raw:
        return {a: list(v) for a, v in default.items()}
    grid = {a: list(v) for a, v in default.items()}
    for chunk in raw.split(";"):
        if not chunk.strip():
            continue
        axis, _, values = chunk.partition(":")
        grid[axis.strip()] = [int(v) for v in values.split(",") if v.strip()]
    return grid


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=_DEFAULT_SYMBOLS)
    parser.add_argument("--tf", nargs="+", default=_DEFAULT_TFS)
    parser.add_argument("--axes", nargs="+", default=list(_AXIS_COLUMNS))
    parser.add_argument(
        "--axis-k-values",
        default=None,
        help="Override per-axis K grid, e.g. 'trend:2,3,4;volatility:2,3'. "
        "Unlisted axes keep their defaults.",
    )
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
    parser.add_argument("--max-workers", type=int, default=16)
    parser.add_argument("--results-path", default=str(_RESULTS_PATH))
    args = parser.parse_args()

    axis_k_values = _parse_axis_grid(args.axis_k_values, _DEFAULT_AXIS_K_VALUES)
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

    print("=" * 100)
    print("HMM regime-AXIS decomposition identifiability sweep")
    print("=" * 100)
    for axis in args.axes:
        print(
            f"  axis {axis:<11} cols={_AXIS_COLUMNS[axis]} K={axis_k_values[axis]} "
            f"cov={_DEFAULT_AXIS_COV_TYPES[axis]}  [{_AXIS_LABEL_GLOSS[axis]}]"
        )
    print(f"n_values={args.n_values} max_n={max_n}  standardize=True (production parity)")
    print(
        f"n_iter={n_iter} full_cov_min_obs={full_cov_min_obs} min_hold_bars={min_hold_bars} "
        f"min_state_occupation={min_state_occupation}"
    )
    print(f"pool_a_base={pool_a_base} pool_b_base={args.pool_b_base}")
    print(f"bars: agreement>={_AGREEMENT_THRESHOLD} AND kappa>={_KAPPA_THRESHOLD} (both required)")
    print("=" * 100)

    jobs: list[dict] = []
    for tf in args.tf:
        for symbol in args.symbols:
            timestamps, closes, volumes = _fetch_ohlcv(conn, symbol, tf)
            if not timestamps:
                print(f"SKIP {symbol}/{tf}: no OHLCV rows")
                continue
            obs_full, _ = _build_obs_matrix(
                timestamps,
                closes,
                volumes,
                vol_window=vol_window,
                momentum_window=momentum_window,
                vol_of_vol_window=vol_of_vol_window,
            )
            if len(obs_full) < 250:
                print(f"SKIP {symbol}/{tf}: insufficient history n_obs={len(obs_full)}")
                continue
            print(f"loaded {symbol}/{tf}: n_obs={len(obs_full)}")
            for axis in args.axes:
                cols = list(_AXIS_COLUMNS[axis])
                obs = StandardScaler().fit_transform(obs_full[:, cols])
                for k in axis_k_values[axis]:
                    for cov_type in _DEFAULT_AXIS_COV_TYPES[axis]:
                        jobs.append(
                            {
                                "symbol": symbol,
                                "tf": tf,
                                "axis": axis,
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
    # workers idle at the end.
    jobs.sort(
        key=lambda j: -(
            len(j["obs"]) * j["k"] * j["obs"].shape[1] * (3 if j["cov_type"] == "full" else 1)
        ),
    )
    print(f"\n{len(jobs)} (cell x axis x K x cov_type) jobs queued\n")

    results: list[dict] = []
    t_start = time.monotonic()
    with _make_worker_pool(args.max_workers, _BLAS_THREADS_PER_WORKER) as pool:
        futures = {pool.submit(_run_config_cell, job): job for job in jobs}
        for done, future in enumerate(as_completed(futures), start=1):
            result = future.result()
            results.append(result)
            top_n = str(max(n for n in args.n_values if n <= max_n))
            entry = result["by_n"].get(top_n, {})
            print(
                f"[{done}/{len(jobs)}] {result['symbol']}/{result['tf']} "
                f"axis={result['axis']:<10} K={result['k']} cov={result['effective_cov_type']:<4} "
                f"agree={entry.get('agreement_smoothed', float('nan')):.4f} "
                f"kappa={entry.get('kappa_smoothed', float('nan')):.4f} "
                f"sep={entry.get('separation_a', float('nan')):.2f} "
                f"sols={entry.get('distinct_solutions_a', -1)} "
                f"fails={result['n_failed_a']}+{result['n_failed_b']} "
                f"({result['fit_seconds']:.0f}s)",
                flush=True,
            )
    print(f"\nall jobs done in {time.monotonic() - t_start:.0f}s")

    _summarize(results, args.axes, axis_k_values, args.n_values, max_n)

    out_path = Path(args.results_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(
            {
                "agreement_threshold": _AGREEMENT_THRESHOLD,
                "kappa_threshold": _KAPPA_THRESHOLD,
                "solution_identity_agreement": _SOLUTION_IDENTITY_AGREEMENT,
                "axis_columns": {a: list(c) for a, c in _AXIS_COLUMNS.items()},
                "axis_k_values": axis_k_values,
                "axis_cov_types": _DEFAULT_AXIS_COV_TYPES,
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


def _summarize(
    results: list[dict],
    axes: list[str],
    axis_k_values: dict[str, list[int]],
    n_values: list[int],
    max_n: int,
) -> None:
    """Per-axis corpus-wide verdicts, then mechanism diagnostics. Headline is the MINIMUM
    across cells and the PASS COUNT, never an average -- an average hides exactly the
    non-identifiable cell this sweep exists to find."""
    tested_ns = [n for n in n_values if n <= max_n]
    n_top = max(tested_ns)

    print("\n" + "=" * 100)
    print("PER-AXIS x CONFIG SUMMARY (min across cells + pass count; minimum is the honest signal)")
    print("=" * 100)
    print(
        f"{'axis':<11} {'K':>2} {'cov':>5} {'N':>3} {'pass/cells':>11} {'min_agree':>10} "
        f"{'min_kappa':>10} {'min_sep':>8} {'max_sols':>8}  worst_cell"
    )
    config_rows: list[dict] = []
    for axis in axes:
        for k in axis_k_values[axis]:
            for cov_type in _DEFAULT_AXIS_COV_TYPES[axis]:
                cells = [
                    r
                    for r in results
                    if r["axis"] == axis and r["k"] == k and r["cov_type"] == cov_type
                ]
                if not cells:
                    continue
                for n in tested_ns:
                    entries = [(r, r["by_n"].get(str(n), {})) for r in cells]
                    n_pass = sum(1 for _, e in entries if _passes(e))
                    worst = min(entries, key=lambda p: p[1].get("agreement_smoothed", 0.0))
                    min_kappa = min(e.get("kappa_smoothed", 0.0) for _, e in entries)
                    seps = [
                        e.get("separation_a")
                        for _, e in entries
                        if e.get("separation_a") is not None
                        and np.isfinite(float(e.get("separation_a", np.nan)))
                    ]
                    max_sols = max(e.get("distinct_solutions_a", 0) for _, e in entries)
                    row = {
                        "axis": axis,
                        "k": k,
                        "cov_type": cov_type,
                        "n": n,
                        "n_pass": n_pass,
                        "n_cells": len(cells),
                        "min_agreement": worst[1].get("agreement_smoothed", 0.0),
                        "min_kappa": min_kappa,
                        "min_separation": float(min(seps)) if seps else float("nan"),
                        "max_distinct_solutions": max_sols,
                        "worst_cell": f"{worst[0]['symbol']}/{worst[0]['tf']}",
                    }
                    config_rows.append(row)
                    if n == n_top:
                        print(
                            f"{axis:<11} {k:>2} {cov_type:>5} {n:>3} {n_pass:>5}/{len(cells):<5} "
                            f"{row['min_agreement']:>10.4f} {row['min_kappa']:>10.4f} "
                            f"{row['min_separation']:>8.2f} {max_sols:>8}  {row['worst_cell']}"
                        )

    print("\n" + "=" * 100)
    print(f"SMALLEST IDENTIFIABLE K PER AXIS at N={n_top} (all-N table is in the JSON)")
    print("=" * 100)
    for axis in axes:
        rows = [r for r in config_rows if r["axis"] == axis and r["n"] == n_top]
        clean = [r for r in rows if r["n_pass"] == r["n_cells"] and r["n_cells"] > 0]
        if not clean:
            best = max(rows, key=lambda r: (r["n_pass"], r["min_agreement"]), default=None)
            if best is None:
                continue
            print(
                f"{axis:<11}: NO CONFIG CLEARS ALL CELLS -- best is K={best['k']}/"
                f"{best['cov_type']} at {best['n_pass']}/{best['n_cells']} "
                f"(min_agree={best['min_agreement']:.4f}, worst={best['worst_cell']})"
            )
            continue
        clean.sort(key=lambda r: (r["k"], -r["min_agreement"]))
        top = clean[0]
        also = ", ".join(f"K{r['k']}/{r['cov_type']}" for r in clean[1:])
        print(
            f"{axis:<11}: smallest all-cell-identifiable = K={top['k']} cov={top['cov_type']} "
            f"(min_agree={top['min_agreement']:.4f} min_kappa={top['min_kappa']:.4f} "
            f"min_sep={top['min_separation']:.2f}){'  also: ' + also if also else ''}"
        )

    print("\n" + "=" * 100)
    print(f"PER-CELL MATRIX at N={n_top}, per axis (agreement / kappa; * = clears both bars)")
    print("=" * 100)
    cells = sorted({(r["symbol"], r["tf"]) for r in results}, key=lambda x: (x[1], x[0]))
    for axis in axes:
        configs = [(k, c) for k in axis_k_values[axis] for c in _DEFAULT_AXIS_COV_TYPES[axis]]
        print(f"\n-- axis: {axis}  [{_AXIS_LABEL_GLOSS[axis]}]")
        print(f"{'cell':<10}" + "".join(f"{f'K{k}/{c[:4]}':>16}" for k, c in configs))
        for symbol, tf in cells:
            line = f"{symbol + '/' + tf:<10}"
            for k, cov_type in configs:
                match = next(
                    (
                        r
                        for r in results
                        if r["symbol"] == symbol
                        and r["tf"] == tf
                        and r["axis"] == axis
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

    print("\n" + "=" * 100)
    print(f"MECHANISM: state separation + solution multiplicity at N={n_top}")
    print("(separation = min pairwise Mahalanobis distance between fitted state means,")
    print(" pooled-covariance units. solutions = distinct labelings among pool A's own fits.)")
    print("=" * 100)
    print(
        f"{'axis':<11} {'K':>2} {'cov':>5} {'median_sep':>11} {'min_sep':>9} "
        f"{'cells_with_multi_solutions':>27} {'median_ll_spread':>17}"
    )
    for axis in axes:
        for k in axis_k_values[axis]:
            for cov_type in _DEFAULT_AXIS_COV_TYPES[axis]:
                entries = [
                    r["by_n"].get(str(n_top), {})
                    for r in results
                    if r["axis"] == axis and r["k"] == k and r["cov_type"] == cov_type
                ]
                entries = [e for e in entries if not e.get("pool_failure", True)]
                if not entries:
                    continue
                seps = [
                    float(e["separation_a"])
                    for e in entries
                    if e.get("separation_a") is not None and np.isfinite(float(e["separation_a"]))
                ]
                multi = sum(1 for e in entries if e.get("distinct_solutions_a", 1) > 1)
                spreads = [float(e.get("ll_spread_relative_a", 0.0)) for e in entries]
                print(
                    f"{axis:<11} {k:>2} {cov_type:>5} "
                    f"{(float(np.median(seps)) if seps else float('nan')):>11.2f} "
                    f"{(float(min(seps)) if seps else float('nan')):>9.2f} "
                    f"{multi:>21}/{len(entries):<5} {float(np.median(spreads)):>17.6f}"
                )

    print("\n" + "=" * 100)
    print(f"DEGENERACY GATE at N={n_top} (production `_check_occupation_gate`, live threshold)")
    print("=" * 100)
    for axis in axes:
        for k in axis_k_values[axis]:
            for cov_type in _DEFAULT_AXIS_COV_TYPES[axis]:
                entries = [
                    (r, r["by_n"].get(str(n_top), {}))
                    for r in results
                    if r["axis"] == axis and r["k"] == k and r["cov_type"] == cov_type
                ]
                entries = [(r, e) for r, e in entries if not e.get("pool_failure", True)]
                if not entries:
                    continue
                degen = [
                    f"{r['symbol']}/{r['tf']}({e.get('min_occupation_a', 0.0):.3f})"
                    for r, e in entries
                    if e.get("degenerate_a")
                ]
                min_occ = min(e.get("min_occupation_a", 0.0) for _, e in entries)
                print(
                    f"{axis:<11} K={k} {cov_type:<5} degenerate={len(degen):>2}/{len(entries):<3} "
                    f"min_occupation={min_occ:.3f}" + (f"  [{', '.join(degen)}]" if degen else "")
                )

    # 1D equivalence check: a 1x1 full covariance IS a diagonal covariance. If hmmlearn
    # disagrees on the volume axis, the two cov_types would produce different labels and
    # the whole "use diag for the 1D axis" simplification would be unsafe.
    vol_axis_rows = [r for r in results if r["axis"] == "volume"]
    if vol_axis_rows:
        mismatches = []
        for k in axis_k_values.get("volume", []):
            for symbol, tf in cells:
                pair = {
                    r["cov_type"]: r["by_n"].get(str(n_top), {})
                    for r in vol_axis_rows
                    if r["symbol"] == symbol and r["tf"] == tf and r["k"] == k
                }
                if len(pair) < 2:
                    continue
                d_agree = abs(
                    pair["full"].get("agreement_smoothed", 0.0)
                    - pair["diag"].get("agreement_smoothed", 0.0)
                )
                if d_agree > 1e-9:
                    mismatches.append(f"{symbol}/{tf} K={k} delta={d_agree:.2e}")
        print("\n" + "=" * 100)
        print("1D VOLUME-AXIS full-vs-diag EQUIVALENCE CHECK")
        print("=" * 100)
        print(
            "identical on all cells/K"
            if not mismatches
            else f"{len(mismatches)} MISMATCHES: {'; '.join(mismatches[:8])}"
        )
    print("=" * 100)


if __name__ == "__main__":
    main()
