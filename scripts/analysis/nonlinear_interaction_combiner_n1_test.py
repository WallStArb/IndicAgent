"""N1 (residual-form combiner with bounded exposure) -- the recommended-first pre-registered
test from docs/research/measurement-nonlinear-interaction-combiner.md's "Pre-registered test
designs" section. Nothing about this test's design is decided here; every arm, timeframe,
hyperparameter, guardrail, and falsification threshold is fixed in that doc, written before any
number in this run existed.

All 3 shared preconditions confirmed met 2026-08-24 (see that doc's corrected Status block):
todo 243's join fix landed, todo 245's 15m/5m diagnostics closed 2026-08-04, todo 240's
linear-ensemble baseline exists. Neither N1 nor N2 has ever been run before this script.

Runs ONE (arm, tf) combination per invocation -- NOT all 6 (2 arms x 3 tfs) in one process.
Each combination's runtime is comparable to the existing per-tf diagnostic scripts (~85 min for
1h) PLUS a second, equally expensive fold-loop for G2's shuffled-null control, so a single
combination can take ~2-3x a base diagnostic run. Running all 6 sequentially in one process
would be a multi-hour uninterruptible block with no incremental result; running them as separate
invocations lets each one checkpoint its own CSV/stdout independently and lets a smoke test on
the cheapest tf (1d) validate the pipeline before committing to 15m/1h's much larger cost.

Usage:
    .venv/bin/python scripts/analysis/nonlinear_interaction_combiner_n1_test.py --tf 1d --arm a
    .venv/bin/python scripts/analysis/nonlinear_interaction_combiner_n1_test.py --tf 15m --arm b --no-g2
    .venv/bin/python scripts/analysis/nonlinear_interaction_combiner_n1_test.py --tf 1d --arm a --g3-canary-check

Writes one JSON result file per (arm, tf) to docs/analysis/n1_{tf}_{arm}.json -- a follow-up
script (nonlinear_interaction_combiner_n1_verdict.py) reads all 6 (or however many exist) and
applies the cross-run BH-FDR family correction plus the pre-registered PASS/FAIL/AMBIGUOUS
criteria, since that decision needs every run's p-value simultaneously, not one at a time.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.analysis._nonlinear_interaction_combiner_shared import (  # noqa: E402
    N1FoldGainAudit,
    fetch_group_name_map,
    run_n1_check,
)
from src.config.settings import Settings  # noqa: E402

# Per-tf calibrated constants, matching every prior published nonlinear_interaction_combiner
# number exactly (same source as nonlinear_interaction_combiner_replication_{tf}.py /
# nonlinear_interaction_combiner_ctf_leak_diagnostic_{tf}.py) -- N1 is not a fresh calibration,
# it reuses the identical fold/embargo/block-size discipline already validated at each tf.
_TF_CONFIG = {
    "1d": dict(embargo_bars=5, bootstrap_block_size=10, min_symbol_rows=100),
    "1h": dict(embargo_bars=24, bootstrap_block_size=10, min_symbol_rows=300),
    "15m": dict(embargo_bars=96, bootstrap_block_size=26, min_symbol_rows=300),
}
_N_FOLDS = 5
_MIN_RELIABLE_N = 50
_N_BOOT = 500
_BOOTSTRAP_SEED = 42
_CANARY_COLS = frozenset(
    {
        "canary_acausal_placebo",
        "canary_constant",
        "canary_near_constant",
        "canary_noise_gaussian",
        "canary_noise_uniform",
    }
)


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tf", required=True, choices=sorted(_TF_CONFIG))
    parser.add_argument(
        "--arm",
        required=True,
        choices=["a", "b", "a-capped"],
        help="a/b: original N1-a/N1-b (colsample_bytree=0.8, unchanged). a-capped: N1-a-capped "
        "(pre-registered 2026-08-25 after N1-a/N1-b both came back G1-void at 1d) -- identical "
        "to N1-a except colsample_bytree=0.10.",
    )
    parser.add_argument(
        "--no-g2",
        action="store_true",
        help="Skip G2's shuffled-null control (roughly halves runtime) -- only for a fast "
        "smoke test of the pipeline itself, never for a run whose result will be cited.",
    )
    parser.add_argument(
        "--g3-canary-check",
        action="store_true",
        help="G3: re-include the 5 canary_* columns via force_include_cols. Per the "
        "pre-registered design, run this ONCE (not per arm/tf) -- a leak that shows up here "
        "rides along regardless of which arm/tf it's checked on.",
    )
    parser.add_argument(
        "--colsample-bytree",
        type=float,
        default=None,
        help="Override N1-a-capped's default 0.10. Only meaningful with --arm a-capped. Exists "
        "for the pre-registered 'if G1 still breaches even at 0.10, the next step is a lower "
        "value' contingency (measurement-nonlinear-interaction-combiner.md) -- NOT a general "
        "escape hatch for re-tuning after seeing a result on other criteria (G4).",
    )
    args = parser.parse_args()

    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    tf_cfg = _TF_CONFIG[args.tf]

    interaction_group_map = None
    if args.arm == "b":
        print("Fetching concept_registry.group_name map for N1-b's interaction_constraints...")
        interaction_group_map = await fetch_group_name_map(db_dsn)
        print(f"Loaded group_name for {len(interaction_group_map)} features.")

    force_include = _CANARY_COLS if args.g3_canary_check else frozenset()
    if args.colsample_bytree is not None:
        colsample_bytree = args.colsample_bytree
    else:
        colsample_bytree = 0.10 if args.arm == "a-capped" else 0.8

    result = await run_n1_check(
        args.tf,
        db_dsn,
        arm_label=f"N1-{args.arm}" + (" (G3 canary check)" if args.g3_canary_check else ""),
        embargo_bars=tf_cfg["embargo_bars"],
        bootstrap_block_size=tf_cfg["bootstrap_block_size"],
        n_folds=_N_FOLDS,
        min_reliable_n=_MIN_RELIABLE_N,
        n_boot=_N_BOOT,
        bootstrap_seed=_BOOTSTRAP_SEED,
        interaction_constraints_group_map=interaction_group_map,
        force_include_cols=force_include,
        run_shuffled_null=not args.no_g2,
        colsample_bytree=colsample_bytree,
    )

    out_dir = Path("docs/analysis")
    out_dir.mkdir(parents=True, exist_ok=True)
    suffix = "_g3canary" if args.g3_canary_check else ""
    # A non-default colsample_bytree override gets its own filename -- never silently overwrite
    # the arm's canonical result file with a different-parameter run.
    default_colsample = 0.10 if args.arm == "a-capped" else 0.8
    if colsample_bytree != default_colsample:
        suffix += f"_cs{colsample_bytree:.2f}".replace(".", "")
    out_path = out_dir / f"n1_{args.tf}_{args.arm}{suffix}.json"

    # N1FoldGainAudit dataclasses aren't JSON-serializable directly.
    serializable = dict(result)
    serializable["g1_gain_audits"] = [
        {
            "fold": a.fold,
            "max_gain_share": a.max_gain_share,
            "max_gain_feature": a.max_gain_feature,
            "breach": a.breach,
        }
        for a in result["g1_gain_audits"]
        if isinstance(a, N1FoldGainAudit)
    ]
    with open(out_path, "w") as f:
        json.dump(serializable, f, indent=2, default=str)
    print(f"\nResult written to {out_path}")

    print(f"\n{'=' * 100}")
    print(
        f"N1-{args.arm} @ {args.tf}: point_diff={result['point_diff']:.4f}  "
        f"ci_lower={result['ci_lower']:.4f}  p={result['p_value']:.4f}  "
        f"g1_breach={result['g1_breach']}  g2_breach={result['g2_breach']}"
    )
    print(
        "Per-run criteria (informal -- the real verdict needs the full 6-test BH-FDR family, "
        "see nonlinear_interaction_combiner_n1_verdict.py):"
    )
    print(f"  Criterion 1 (ci_lower > 0): {'CLEAR' if result['ci_lower'] > 0 else 'FAIL'}")
    print(
        f"  Criterion 2 (point_diff >= 0.005): {'CLEAR' if result['point_diff'] >= 0.005 else 'FAIL'}"
    )
    print(
        f"  Guardrails G1/G2: {'CLEAN' if not result['g1_breach'] and not result['g2_breach'] else 'BREACH'}"
    )
    print(f"{'=' * 100}")


if __name__ == "__main__":
    asyncio.run(main())
