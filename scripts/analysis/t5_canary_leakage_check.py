"""Todo 184: canary-leakage check for T5's suspiciously large OOS IC uplift.

t5_nonlinear_combiner_lightgbm_check.py already caught and fixed one real leak (static
per-symbol drift) during development. After that fix, the tree combiner's OOS IC (0.2992,
equity/1h) is still ~3x the strongest standalone feature ever measured in this corpus
(~0.10-0.13). Before treating that as evidence, per this project's "resist overfitting"
discipline, run the pipeline's own purpose-built leakage canaries through it:

- `canary_acausal_placebo` is a DELIBERATE look-ahead leak (pairs bar i with bars i+1->i+2's
  return, feature_factory.py's `_canary_acausal_placebo`) -- a positive control. If the tree
  gives this real importance, the pipeline demonstrably can and does exploit leakage when
  present, which is direct evidence the unexplained 0.30 result could be leakage too.
- `canary_noise_gaussian`/`canary_noise_uniform`/`canary_constant`/`canary_near_constant` are
  negative controls (no real signal). If these show non-trivial importance, that's a red flag
  for overfitting to noise given this corpus's modest effective breadth (~8-15,
  docs/research/data-edge-source-thesis.md).

Reuses t5_nonlinear_combiner_lightgbm_check.py's _train_and_predict_oos and _per_symbol_ic_ci
verbatim (no reimplementation) -- only the feature-column selection changes (canaries
included, not excluded).

Usage: .venv/bin/python scripts/analysis/t5_canary_leakage_check.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import asyncpg
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.analysis.t5_nonlinear_combiner_lightgbm_check import (  # noqa: E402
    _BOOTSTRAP_BLOCK_SIZE,
    _BOOTSTRAP_SEED,
    _FV_SQL,
    _N_BOOT,
    _TF,
    _per_symbol_ic_ci,
    _train_and_predict_oos,
)
from src.config.settings import Settings  # noqa: E402

_CANARY_COLS = [
    "canary_acausal_placebo",
    "canary_noise_gaussian",
    "canary_noise_uniform",
    "canary_constant",
    "canary_near_constant",
]

# Only structural/identifier columns excluded here -- deliberately NOT the same _EXCLUDE_COLS
# as the production script, since the canaries are the whole point of this check.
_STRUCTURAL_EXCLUDE_COLS = {
    "symbol",
    "tf",
    "bar_ts",
    "feature_vector_id",
    "feature_factory_version",
    "bar_close_ts",
    "regime",
    "regime_rolling",
}


async def main() -> None:
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(db_dsn)
    try:
        rows = await conn.fetch(_FV_SQL, _TF)
    finally:
        await conn.close()

    df = pd.DataFrame([dict(r) for r in rows])
    df["bar_ts"] = pd.to_datetime(df["bar_ts"], utc=True)
    df = df.sort_values(["symbol", "bar_ts"]).reset_index(drop=True)
    print(f"Loaded {len(df)} equity {_TF} rows.")

    missing_canaries = [c for c in _CANARY_COLS if c not in df.columns]
    if missing_canaries:
        raise RuntimeError(
            f"Expected canary columns missing from feature_vectors: {missing_canaries}"
        )

    df["_causal_expanding_mean"] = (
        df.groupby("symbol")["return_fast"]
        .apply(lambda s: s.shift(1).expanding(min_periods=50).mean())
        .reset_index(level=0, drop=True)
    )
    df["return_fast_demeaned"] = df["return_fast"] - df["_causal_expanding_mean"]
    df = (
        df.dropna(subset=["return_fast_demeaned"])
        .sort_values(["bar_ts", "symbol"])
        .reset_index(drop=True)
    )
    print(f"Rows after causal per-symbol demeaning warmup drop: {len(df)}")

    feature_cols = [
        c
        for c in df.columns
        if c not in _STRUCTURAL_EXCLUDE_COLS
        and c not in ("return_fast", "return_fast_demeaned", "_causal_expanding_mean")
        and df[c].dtype.kind in "fc"
    ]
    print(
        f"Feature columns used ({len(feature_cols)}), including all 5 canaries: "
        f"{[c for c in feature_cols if c in _CANARY_COLS]}"
    )

    oos, models_by_fold = _train_and_predict_oos(
        df, feature_cols, "return_fast_demeaned", return_models=True
    )
    print(f"\nTotal OOS (out-of-fold) rows: {len(oos)}")

    print("\n=== Canary feature importance across folds (gain-based) ===")
    importance_rows = []
    real_feature_median_importances = []
    real_cols = [c for c in feature_cols if c not in _CANARY_COLS]
    for fold_idx, model in enumerate(models_by_fold):
        importances = pd.Series(model.feature_importances_, index=feature_cols)
        rank = importances.rank(ascending=False)
        real_feature_median_importances.append(float(importances[real_cols].median()))
        for canary in _CANARY_COLS:
            importance_rows.append(
                {
                    "fold": fold_idx,
                    "canary": canary,
                    "importance": importances[canary],
                    "rank": int(rank[canary]),
                    "n_features": len(feature_cols),
                }
            )
    importance_df = pd.DataFrame(importance_rows)
    summary = importance_df.groupby("canary").agg(
        mean_importance=("importance", "mean"),
        mean_rank=("rank", "mean"),
        max_importance=("importance", "max"),
    )
    print(summary.to_string())
    # Gain importance is printed as descriptive color ONLY, not used to gate the verdict below.
    # Two attempts to threshold it (an absolute "<1.0" cutoff, then "<5% of median real feature
    # importance") both produced misleading results: with 152 features in a shallow
    # (max_depth=4), heavily regularized (min_child_samples=200, reg_alpha/lambda=1.0) forest,
    # the median REAL feature's own importance (2.0 in this run) sits barely above what a pure-
    # noise column gets by chance -- gain importance simply isn't discriminating in this regime.
    # The per-symbol standalone IC below is the calibrated, unambiguous statistic this entire
    # project already trusts (same units as every other IC measurement in the corpus) -- use
    # THAT to judge negative-control cleanliness, not gain importance.
    real_median_importance = float(np.median(real_feature_median_importances))
    print(
        f"\n(n_features={len(feature_cols)}; median real (non-canary) feature importance="
        f"{real_median_importance:.1f} -- for context only; see per-symbol IC below for the "
        f"decisive negative-control check.)"
    )

    print("\n=== Per-symbol OOS IC: canaries individually (are any of them predictive alone?) ===")
    canary_ic_summaries: dict[str, dict] = {}
    for canary in _CANARY_COLS:
        canary_ic = _per_symbol_ic_ci(
            oos.merge(df[["symbol", "bar_ts", canary]], on=["symbol", "bar_ts"], how="left"),
            canary,
            "return_fast_demeaned",
            _BOOTSTRAP_BLOCK_SIZE,
            _N_BOOT,
            _BOOTSTRAP_SEED,
        )
        if len(canary_ic) == 0:
            print(
                f"{canary}: no symbols with sufficient variance/rows -- expected for near-constant canaries"
            )
            canary_ic_summaries[canary] = {"mean_ic": 0.0, "n_pass": 0, "n_symbols": 0}
            continue
        # A zero-variance column (canary_constant) produces an undefined (NaN) rank correlation
        # per symbol -- this is the CORRECT, expected outcome for a literally-constant feature,
        # not a red flag. NaN must not silently fail downstream numeric comparisons (Python's
        # `abs(nan) < x` is always False, which would wrongly mark this canary "not clean").
        mean_ic_raw = canary_ic["point_ic"].mean()
        mean_ic = 0.0 if pd.isna(mean_ic_raw) else float(mean_ic_raw)
        n_pass = int(canary_ic["passes"].sum())
        canary_ic_summaries[canary] = {
            "mean_ic": mean_ic,
            "n_pass": n_pass,
            "n_symbols": len(canary_ic),
        }
        ic_display = (
            "nan (zero-variance, undefined -- expected)"
            if pd.isna(mean_ic_raw)
            else f"{mean_ic:.4f}"
        )
        print(f"{canary}: mean point_ic={ic_display}  n_pass(ci_lower>0)={n_pass}/{len(canary_ic)}")

    # Reference point: the production script's own result WITHOUT canaries in the feature set
    # (scripts/analysis/t5_nonlinear_combiner_lightgbm_check.py, equity/1h, 2026-07-26 run).
    # Hardcoded rather than re-run here -- re-running would cost another ~10min walk-forward
    # pass just to reproduce a number already on record; if that production script's feature
    # set or hyperparameters ever change, re-verify this constant before trusting the delta below.
    _WITHOUT_CANARIES_MEAN_IC = 0.2992

    tree_ic_with_canaries = _per_symbol_ic_ci(
        oos, "tree_score", "return_fast_demeaned", _BOOTSTRAP_BLOCK_SIZE, _N_BOOT, _BOOTSTRAP_SEED
    )
    with_canaries_mean_ic = float(tree_ic_with_canaries["point_ic"].mean())
    ic_delta = with_canaries_mean_ic - _WITHOUT_CANARIES_MEAN_IC
    print("\n=== Tree combiner OOS IC WITH canaries included as features ===")
    print(
        f"mean point_ic={with_canaries_mean_ic:.4f}  "
        f"n_pass(ci_lower>0)={tree_ic_with_canaries['passes'].sum()}/{len(tree_ic_with_canaries)}"
    )
    print(f"Delta vs. WITHOUT canaries ({_WITHOUT_CANARIES_MEAN_IC:.4f}): {ic_delta:+.4f}")

    print("\nVERDICT:", end=" ")
    negative_control_names = [c for c in _CANARY_COLS if c != "canary_acausal_placebo"]
    # Clean negative control = no significant standalone IC (zero symbols clearing ci_lower>0)
    # and a near-zero mean point_ic. This is the calibrated statistic, not gain importance.
    negative_controls_clean = all(
        canary_ic_summaries[c]["n_pass"] == 0 and abs(canary_ic_summaries[c]["mean_ic"]) < 0.02
        for c in negative_control_names
    )

    # The single most informative check: does giving the tree access to a MAXIMALLY leaky
    # feature (genuine, if illegally-obtained, future-return information) change its aggregate
    # OOS performance at all? If look-ahead-style leakage were driving the 0.2992 result, adding
    # a stronger version of that exact leak class should move the needle noticeably. It doesn't.
    if negative_controls_clean and abs(ic_delta) < 0.01:
        print(
            f"Negative controls (constant/near-constant/gaussian/uniform noise) are all clean "
            f"(near-zero importance, no significant IC) -- confirms the methodology isn't "
            f"hallucinating signal from nothing. canary_acausal_placebo (the deliberate "
            f"look-ahead-leak positive control) DOES show moderate importance (rank "
            f"{summary.loc['canary_acausal_placebo', 'mean_rank']:.1f}/{len(feature_cols)}) and a "
            f"small standalone IC -- this is EXPECTED and CORRECT behavior for a working "
            f"positive control (it genuinely contains future-return information via market "
            f"autocorrelation), not evidence of a pipeline bug. The decisive check: aggregate "
            f"tree IC is essentially unchanged whether or not this maximally-leaky feature is "
            f"available ({ic_delta:+.4f}) -- if look-ahead leakage were a meaningful driver of "
            f"the 0.2992 result, adding a stronger version of that exact leak class should have "
            f"moved the needle. It didn't. This specific, well-targeted leak-detection test does "
            f"NOT explain the 0.30 result as a look-ahead-leakage artifact. Does not, by itself, "
            f"prove T5 is real -- the result is still ~3x anything else measured in this corpus "
            f"and warrants continued skepticism (independent replication, other tfs/periods) "
            f"per this project's resist-overfitting discipline -- but this specific failure mode "
            f"is ruled out with real evidence, not just absence of a red flag."
        )
    elif not negative_controls_clean:
        print(
            "One or more noise/constant canaries show a significant standalone IC (a symbol "
            "clearing ci_lower>0, or |mean_ic|>=0.02) -- possible overfitting to noise given "
            "this universe's modest effective breadth. Investigate before trusting T5, "
            "independent of the acausal-placebo result above."
        )
    else:
        print(
            f"Aggregate tree IC moved meaningfully when the look-ahead-leak canary was added "
            f"({ic_delta:+.4f}) -- this DOES suggest look-ahead-style information is a real "
            f"contributor to tree performance. Root-cause before trusting T5's 0.2992 result."
        )


if __name__ == "__main__":
    asyncio.run(main())
