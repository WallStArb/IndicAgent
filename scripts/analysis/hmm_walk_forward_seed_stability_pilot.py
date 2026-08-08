"""REQ-5's real-data exercise of `_hmm_seed_stability_check` (Phase 171, D-01 staged pilot).

RESEARCH.md confirmed `_hmm_seed_stability_check` (`services/regime_writer.py`) had zero call
sites outside its two synthetic unit tests -- exactly the "invoked-nowhere" state REQ-5
forbids. This script closes that gap by running the check against real corpus OHLCV, at the
walk-forward TRAINING PREFIXES `_walk_forward_hmm_labels` actually fits (not the full series),
for a cell set spanning bar-density and liquidity: SPY (deepest history, highest liquidity),
IWM (small-cap beta), TLT (thinnest 1d history in the candidate set, ~2,381 bars -- the
density-stress case), GLD (commodity), XLE (sector), EEM (international), FXY (currency,
thinnest 5m history, ~276k bars), SMH (shortest overall history, ~3,415 1d bars).

Gate: FAIL when `min_pairwise_agreement <= 0.25` -- at or below the ~21.7-22.1% five-label
chance baseline migration 292's own descriptions record, meaning the labels are seed noise,
not a regime measurement. Values above 0.25 are recorded as evidence and do NOT fail: this
phase ships regardless of the Gate 4 ordinal-IC result per the ROADMAP -- this gate's job is
catching a degenerate cell before the 231-symbol blast radius, not re-litigating the fix.
Corpus-wide headline is the MINIMUM `min_pairwise_agreement` across cells/boundaries, not an
average -- an average would hide exactly the degenerate cell this check exists to find.

A thin training prefix at exactly the full-covariance threshold (full_cov_min_obs) can make
GaussianHMM's EM produce a non-positive-definite covariance mid-fit (observed live on
TLT/1d's first boundary at 504 obs, 5 components, full covariance -- hmmlearn's own min_covar
regularization isn't always enough at this sample-per-state density). That crash is itself
evidence of instability, not a script bug to hide: this pilot catches it per-boundary and
records `min_pairwise_agreement=0.0` (below the FAIL gate) rather than aborting the whole run,
so one numerically degenerate cell doesn't block every other cell's read out. `regime_writer.py`
is never modified to work around this -- the catch lives entirely in this script.

Read-only diagnostic: no `feature_vectors` writes, no `regime_writer.py` CLI invocation.

Usage:
    .venv/bin/python scripts/analysis/hmm_walk_forward_seed_stability_pilot.py
    .venv/bin/python scripts/analysis/hmm_walk_forward_seed_stability_pilot.py --symbols TLT --tf 1d --boundaries first
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

from services.regime_writer import (
    _build_obs_matrix,  # noqa: E402
    _hmm_seed_stability_check,  # noqa: E402
)
from src.config.settings import Settings  # noqa: E402

# ---------------------------------------------------------------------------
# Pilot scope
# ---------------------------------------------------------------------------

_DEFAULT_SYMBOLS = ["SPY", "IWM", "TLT", "GLD", "XLE", "EEM", "FXY", "SMH"]
# Cheap timeframes (fewest bars) first, so a run reports early feedback before the
# expensive 5m cells (walk-forward prefixes up to ~390k rows).
_DEFAULT_TFS = ["1d", "1h", "15m", "5m"]

_DEGENERATE_GATE_THRESHOLD = 0.25  # ~21.7-22.1% is the 5-label chance baseline (migration 292)

_RESULTS_PATH = Path("cache/hmm_seed_stability_pilot_results.json")

# APR fallback defaults -- live values are read from config_state at startup; these are
# used only if a key is missing there (see interfaces block of 171-04-PLAN.md, confirmed
# live 2026-08-07).
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
}

_FETCH_OHLCV_SQL = """
SELECT timestamp, close, volume
FROM market_data_ohlcv_tradeable
WHERE symbol = %s AND timeframe = %s
ORDER BY timestamp ASC
"""


def _load_config(conn: psycopg.Connection) -> dict[str, str]:
    """Plain SELECT against config_state -- read-only analysis script, so a live
    ConfigService instance isn't warranted. Falls back to _APR_FALLBACKS for any
    missing key so this script never silently diverges from what production runs when a
    key happens to be absent (never observed live, but defensive)."""
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


def _segment_boundaries(n: int, initial_warmup_bars: int, refit_every_bars: int) -> list[int]:
    """Same boundary schedule `_walk_forward_hmm_labels` actually steps through -- each
    entry is the size of the training prefix used to fit that segment's model."""
    boundaries: list[int] = []
    b = initial_warmup_bars
    while b < n:
        boundaries.append(b)
        b = min(b + refit_every_bars, n)
    return boundaries


def _select_boundaries(boundaries: list[int], names: list[str]) -> list[tuple[str, int]]:
    """Map requested boundary names (first/middle/last) to actual boundary values,
    deduplicating so a small n_segments cell (e.g. n_segments=1, all three names collide)
    isn't fit three times for the same prefix."""
    n_segments = len(boundaries)
    by_name = {
        "first": boundaries[0],
        "middle": boundaries[n_segments // 2],
        "last": boundaries[-1],
    }
    selected: list[tuple[str, int]] = []
    seen_values: set[int] = set()
    for name in names:
        value = by_name[name]
        if value in seen_values:
            continue
        seen_values.add(value)
        selected.append((name, value))
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=_DEFAULT_SYMBOLS)
    parser.add_argument("--tf", nargs="+", default=_DEFAULT_TFS)
    parser.add_argument(
        "--boundaries",
        default="first,middle,last",
        help="Comma-separated subset of {first,middle,last}",
    )
    parser.add_argument(
        "--seeds",
        nargs="+",
        type=int,
        default=None,
        help="Override seeds directly (default: hmm_random_state + 0,1,2)",
    )
    parser.add_argument(
        "--full-history",
        action="store_true",
        help=(
            "Bypass walk-forward windowing entirely and run the seed-stability check once "
            "per (symbol, tf) against the ENTIRE available obs_matrix -- i.e. the same "
            "training scope _compute_symbol_tf's production single-fit path uses. Exists "
            "to answer the question the corrected-threshold re-pilot raised: the observed "
            "seed instability persisted at N in the tens of thousands (well past any "
            "covariance-estimation floor), suggesting genuine EM local-optima multimodality "
            "independent of window size -- this flag tests whether that same multimodality "
            "is present in the CURRENTLY-RUNNING production fit, not just the walk-forward "
            "candidate's thinner windows. --boundaries is ignored when this flag is set."
        ),
    )
    parser.add_argument(
        "--full-cov-min-obs-override",
        type=int,
        default=None,
        help=(
            "Diagnostic-only override for feature.hmm.full_cov_min_obs, applied after the "
            "live config read and never written back to config_state. Exists to test the "
            "G2 seed-instability finding's root-cause hypothesis (171-PILOT-GATE.md): the "
            "live default of 500 was never validated against the full-covariance model's own "
            "free-parameter count (K=5, D=5 -> ~124 params: 25 means + 75 covariances + 20 "
            "transitions + 4 initial), so the diag-covariance fallback this override targets "
            "may simply be firing too late relative to what full covariance can support at "
            "this K/D. Zero production impact: the flag only changes this read-only pilot's "
            "in-memory threshold for this invocation."
        ),
    )
    args = parser.parse_args()
    boundary_names = [b.strip() for b in args.boundaries.split(",") if b.strip()]

    settings = Settings()
    conn = psycopg.connect(settings.database_url)

    cfg = _load_config(conn)
    n_components = int(cfg["feature.hmm.n_components"])
    covariance_type = cfg["feature.hmm.covariance_type"]
    n_iter = int(cfg["feature.hmm.n_iter"])
    hmm_random_state = int(cfg["alpha.hmm.random_state"])
    full_cov_min_obs = (
        args.full_cov_min_obs_override
        if args.full_cov_min_obs_override is not None
        else int(cfg["feature.hmm.full_cov_min_obs"])
    )
    vol_window = int(cfg["feature.hmm.vol_window"])
    momentum_window = int(cfg["feature.hmm.obs_momentum_window"])
    vol_of_vol_window = int(cfg["feature.hmm.obs_vol_of_vol_window"])

    seeds = args.seeds if args.seeds is not None else [hmm_random_state + i for i in range(3)]

    print("=" * 80)
    print("HMM walk-forward seed-stability pilot (REQ-5)")
    print("=" * 80)
    override_note = (
        f" (OVERRIDDEN from live config_state value {cfg['feature.hmm.full_cov_min_obs']})"
        if args.full_cov_min_obs_override is not None
        else ""
    )
    print(
        f"n_components={n_components} covariance_type={covariance_type} n_iter={n_iter} "
        f"hmm_random_state={hmm_random_state} full_cov_min_obs={full_cov_min_obs}{override_note}"
    )
    print(
        f"vol_window={vol_window} momentum_window={momentum_window} "
        f"vol_of_vol_window={vol_of_vol_window} seeds={seeds}"
    )
    print(f"symbols={args.symbols} tfs={args.tf} boundaries={boundary_names}")
    print("=" * 80)

    cell_results: list[dict] = []
    # (min_pairwise_agreement, symbol, tf, boundary_name) across every sampled boundary in
    # every cell -- the corpus-wide headline is the MIN of this, never an average.
    global_min: tuple[float, str, str, str] | None = None

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
        for symbol in args.symbols:
            t0 = time.monotonic()
            print(f"\n--- {symbol} {tf} ---")
            timestamps, closes, volumes = _fetch_ohlcv(conn, symbol, tf)
            if not timestamps:
                print(f"  SKIP: no OHLCV rows for {symbol}/{tf}")
                cell_results.append(
                    {"symbol": symbol, "tf": tf, "skipped": True, "skip_reason": "no_ohlcv"}
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
            min_required = initial_warmup_bars + n_components
            if n < min_required:
                reason = f"insufficient history: n={n} obs, need >= {min_required}"
                print(f"  SKIP: {reason}")
                cell_results.append(
                    {
                        "symbol": symbol,
                        "tf": tf,
                        "skipped": True,
                        "skip_reason": reason,
                        "n_obs": n,
                    }
                )
                continue

            if args.full_history:
                n_segments = 1
                selected = [("full_history", n)]
                print(f"  n_obs={n} n_segments=1 (--full-history: production-scope single fit)")
            else:
                boundaries = _segment_boundaries(n, initial_warmup_bars, refit_every_bars)
                n_segments = len(boundaries)
                selected = _select_boundaries(boundaries, boundary_names)
                print(f"  n_obs={n} n_segments={n_segments} sampled_boundaries={selected}")

            boundary_results: list[dict] = []
            cell_min: float | None = None
            for name, boundary in selected:
                try:
                    check = _hmm_seed_stability_check(
                        obs_matrix[:boundary],
                        n_components=n_components,
                        covariance_type=covariance_type,
                        n_iter=n_iter,
                        seeds=seeds,
                        full_cov_min_obs=full_cov_min_obs,
                    )
                except (np.linalg.LinAlgError, ValueError) as error:
                    # A covariance blow-up mid-fit IS a stability failure, not a script
                    # bug -- record it as the worst possible agreement (0.0) so it still
                    # drives the corpus-wide MINIMUM, rather than silently disappearing.
                    print(
                        f"  boundary={name} ({boundary} obs): NUMERICAL FAILURE "
                        f"({type(error).__name__}: {error}) -- treated as degenerate "
                        f"(min_pairwise_agreement=0.0)"
                    )
                    min_pw = 0.0
                    boundary_results.append(
                        {
                            "boundary_name": name,
                            "boundary": boundary,
                            "numerical_failure": True,
                            "error": f"{type(error).__name__}: {error}",
                            "min_pairwise_agreement": min_pw,
                        }
                    )
                    if cell_min is None or min_pw < cell_min:
                        cell_min = min_pw
                    if global_min is None or min_pw < global_min[0]:
                        global_min = (min_pw, symbol, tf, name)
                    continue

                min_pw = check["min_pairwise_agreement"]
                print(
                    f"  boundary={name} ({boundary} obs): ll_spread={check['ll_spread']:.4f} "
                    f"min_pairwise_agreement={min_pw:.4f}"
                )
                for pair, agreement in check["pairwise_label_agreement"].items():
                    print(f"    pair={pair}: agreement={agreement:.4f}")
                boundary_results.append(
                    {
                        "boundary_name": name,
                        "boundary": boundary,
                        "ll_spread": check["ll_spread"],
                        "log_likelihoods": {str(k): v for k, v in check["log_likelihoods"].items()},
                        "pairwise_label_agreement": {
                            f"{a}_{b}": v for (a, b), v in check["pairwise_label_agreement"].items()
                        },
                        "min_pairwise_agreement": min_pw,
                    }
                )
                if cell_min is None or min_pw < cell_min:
                    cell_min = min_pw
                if global_min is None or min_pw < global_min[0]:
                    global_min = (min_pw, symbol, tf, name)

            elapsed = time.monotonic() - t0
            verdict = "FAIL" if cell_min <= _DEGENERATE_GATE_THRESHOLD else "OK"
            print(
                f"  SEED STABILITY: {symbol} {tf}: {verdict} "
                f"(cell_min_pairwise_agreement={cell_min:.4f}, gate<= {_DEGENERATE_GATE_THRESHOLD}) "
                f"elapsed={elapsed:.1f}s"
            )
            cell_results.append(
                {
                    "symbol": symbol,
                    "tf": tf,
                    "skipped": False,
                    "n_obs": n,
                    "n_segments": n_segments,
                    "boundaries": boundary_results,
                    "cell_min_pairwise_agreement": cell_min,
                    "verdict": verdict,
                    "elapsed_seconds": elapsed,
                }
            )

    print("\n" + "=" * 80)
    print("CORPUS-WIDE SUMMARY (minimum, not average -- the honest signal)")
    print("=" * 80)
    if global_min is None:
        print("No cells produced a result (all skipped).")
    else:
        min_value, min_symbol, min_tf, min_boundary = global_min
        overall_verdict = "FAIL" if min_value <= _DEGENERATE_GATE_THRESHOLD else "OK"
        print(
            f"MIN min_pairwise_agreement={min_value:.4f} at {min_symbol}/{min_tf} "
            f"boundary={min_boundary}"
        )
        print(f"SEED STABILITY (corpus-wide): {overall_verdict}")
    print("=" * 80)

    _RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_RESULTS_PATH, "w") as f:
        json.dump(
            {
                "gate_threshold": _DEGENERATE_GATE_THRESHOLD,
                "seeds": seeds,
                "global_min": (
                    {
                        "min_pairwise_agreement": global_min[0],
                        "symbol": global_min[1],
                        "tf": global_min[2],
                        "boundary_name": global_min[3],
                    }
                    if global_min is not None
                    else None
                ),
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
