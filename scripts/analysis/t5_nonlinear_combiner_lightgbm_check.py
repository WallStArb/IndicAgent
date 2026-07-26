"""Edge Source Thesis T5 falsification test (non-linear interaction combiner).

docs/research/data-edge-source-thesis.md T5: ensemble_trainer.py's linear, shrunk-IC-weighted
combiner can express "feature X predicts returns" but structurally cannot express "feature X
predicts returns only when feature Y crosses a threshold" -- any interaction structure across
the ~150 feature_vectors columns is invisible to it by construction. Todo 179 already tested
the ONE interaction axis the system explicitly models (feature x regime, via cross-sectional
stratification) exhaustively and found nothing that survives OOS replication. This script
tests whether a non-linear combiner over the IDENTICAL features finds structure the linear
combiner can't -- same corpus, same target, no new data, no new features.

Design, per docs/ideas/measurement-nonlinear-interaction-combiner.md:
  - Shallow, regularized LightGBM regressor (interpretable, not a black box).
  - Walk-forward folds via ic_math.py's build_walk_forward_folds (verbatim, no reimplementation).
  - Per-symbol OOS IC measured via ic_math.py's circular_block_bootstrap_ic_serial (verbatim,
    same per-tf APR block size the production ic_engine uses) -- never a fresh statistic
    invented for this test.
  - Directly compared against the single strongest standalone feature (ctf_momentum, same one
    T3 tests) measured the identical way, on the identical held-out population -- an uplift
    test, not an absolute-performance claim.

Usage: .venv/bin/python scripts/analysis/t5_nonlinear_combiner_lightgbm_check.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncpg  # noqa: E402

from src.config.settings import Settings  # noqa: E402
from src.intelligence.statistics.ic_math import (  # noqa: E402
    build_walk_forward_folds,
    circular_block_bootstrap_ic_serial,
)

_CROSS_SECTIONAL_BLOCK_BARS = 2  # block spans this many consecutive bar_ts's full cross-section

_TF = "1h"
_BASELINE_FEATURE = "ctf_momentum"
_N_FOLDS = 5
_EMBARGO_BARS = 24  # 1 day of 1h bars, avoids train/test leakage across the fold boundary
_MIN_RELIABLE_N = 50
_BOOTSTRAP_BLOCK_SIZE = 10  # matches live alpha.ic.bootstrap_block_size.1h
_N_BOOT = 500  # reduced from production's 2000 -- exploratory pass, not a promotion gate
_BOOTSTRAP_SEED = 42
_MIN_SYMBOL_ROWS = 300  # per-symbol floor for a meaningful per-symbol IC estimate

_EXCLUDE_COLS = {
    "symbol",
    "tf",
    "bar_ts",
    "feature_vector_id",
    "feature_factory_version",
    "bar_close_ts",
    "regime",
    "regime_rolling",
    "canary_acausal_placebo",
    "canary_constant",
    "canary_near_constant",
    "canary_noise_gaussian",
    "canary_noise_uniform",
}

_FV_SQL = """
    SELECT fv.*, fr.return_fast
    FROM feature_vectors fv
    JOIN forward_returns fr
      ON fr.symbol = fv.symbol AND fr.tf = fv.tf AND fr.bar_ts = fv.bar_ts
    JOIN instruments i ON i.symbol = fv.symbol
    WHERE fv.tf = $1
      AND fr.return_type = 'executable_open_to_open'
      AND fr.complete_fast = true
      AND i.is_active = true
      AND i.contract_details->>'asset_class' = 'equity'
    ORDER BY fv.bar_ts ASC, fv.symbol ASC
"""


def _bootstrap_ic_stats(
    score: np.ndarray, actual: np.ndarray, block_size: int, n_boot: int, seed: int
) -> dict[str, float | bool]:
    """Point Spearman IC + circular-block-bootstrap CI for one (score, actual) series,
    reusing ic_math.py's circular_block_bootstrap_ic_serial verbatim. Shared by the
    per-symbol loop below and the pooled within-bar_ts rigor pass at the bottom of
    main() -- same statistic, different granularity, one implementation."""
    rng = np.random.default_rng(seed)
    ci_lower, ci_upper = circular_block_bootstrap_ic_serial(
        score.reshape(-1, 1), actual, block_size=block_size, n_boot=n_boot, rng=rng
    )
    point_ic = float(pd.Series(score).rank().corr(pd.Series(actual).rank()))
    return {
        "point_ic": point_ic,
        "ci_lower": float(ci_lower[0]),
        "ci_upper": float(ci_upper[0]),
        "passes": bool(ci_lower[0] > 0),
    }


def _per_symbol_ic_ci(
    df: pd.DataFrame, score_col: str, return_col: str, block_size: int, n_boot: int, seed: int
) -> pd.DataFrame:
    """Per-symbol circular-block-bootstrap IC CI. One row per symbol with sufficient
    held-out rows; symbols below _MIN_SYMBOL_ROWS are skipped, not zero-filled."""
    records = []
    for symbol, group in df.groupby("symbol"):
        group = group.dropna(subset=[score_col, return_col])
        if len(group) < _MIN_SYMBOL_ROWS:
            continue
        stats = _bootstrap_ic_stats(
            group[score_col].to_numpy(dtype=float),
            group[return_col].to_numpy(dtype=float),
            block_size,
            n_boot,
            seed,
        )
        records.append({"symbol": symbol, "n": len(group), **stats})
    return pd.DataFrame.from_records(records)


def _train_and_predict_oos(
    df: pd.DataFrame, feature_cols: list[str], target_col: str, return_models: bool = False
) -> pd.DataFrame | tuple[pd.DataFrame, list[lgb.LGBMRegressor]]:
    """Walk-forward: train a shallow, regularized LightGBM regressor on each expanding-window
    fold's training slice, predict on that fold's held-out test slice. Returns the full OOS
    (out-of-fold) prediction set -- every row appears in exactly one test fold, never a train
    fold, so this is a legitimate held-out population for the IC measurement above.

    `return_models=True` (used by todo 184's canary-leakage check, not the production path)
    additionally returns the list of per-fold fitted models for feature-importance inspection."""
    n_valid = len(df)
    folds = build_walk_forward_folds(
        n_valid=n_valid,
        n_folds=_N_FOLDS,
        embargo_bars=_EMBARGO_BARS,
        min_reliable_n=_MIN_RELIABLE_N,
    )
    print(f"Walk-forward folds (expanding window, embargo={_EMBARGO_BARS} bars): {folds}")

    X = df[feature_cols].to_numpy(dtype=float)
    y = df[target_col].to_numpy(dtype=float)

    oos_frames = []
    fitted_models = []
    for k, (test_start, test_end) in enumerate(folds):
        train_end = test_start - _EMBARGO_BARS
        if train_end < _MIN_RELIABLE_N:
            continue
        train_mask = np.zeros(n_valid, dtype=bool)
        train_mask[:train_end] = True
        train_mask &= ~np.isnan(y)

        model = lgb.LGBMRegressor(
            n_estimators=200,
            max_depth=4,
            num_leaves=15,
            min_child_samples=200,
            learning_rate=0.05,
            reg_alpha=1.0,
            reg_lambda=1.0,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=_BOOTSTRAP_SEED,
            verbosity=-1,
        )
        model.fit(X[train_mask], y[train_mask])
        fitted_models.append(model)

        test_idx = np.arange(test_start, test_end)
        preds = model.predict(X[test_idx])
        fold_df = df.iloc[test_idx][["symbol", "bar_ts", target_col]].copy()
        fold_df["tree_score"] = preds
        fold_df["fold"] = k
        oos_frames.append(fold_df)
        print(f"  fold {k}: train_n={train_mask.sum()}  test_n={len(test_idx)}")

    oos_df = pd.concat(oos_frames, ignore_index=True)
    if return_models:
        return oos_df, fitted_models
    return oos_df


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
    print(f"Distinct symbols: {df['symbol'].nunique()}  Distinct bar_ts: {df['bar_ts'].nunique()}")

    # CRITICAL FIX (found live, 2026-07-26): the naive pooled-training result showed
    # mean_ic=0.30, 80/80 symbols passing -- ~3x anything else measured in this corpus.
    # Diagnosed as a static per-symbol drift leak: per-symbol MEAN return_fast in the
    # train half correlates 0.27 with the test half (some ETFs, e.g. ARKK/BTAL/VNQ,
    # simply have a persistently higher long-run average return than others, e.g.
    # GDX/KWEB/XOP, across the whole 20-year sample). A 147-feature tree can
    # implicitly recognize "this row's signature looks like ARKK" and predict ARKK's
    # known-good long-run drift -- correlating with actual returns for a reason that
    # has nothing to do with bar-level signal. This is exactly the "Attribution
    # honesty" failure trade-construction-layer.md's validation gate #2 pre-registered
    # ("a fixed membership explains most of it... a factor exposure in disguise").
    # Fix: subtract each symbol's own CAUSAL (shift(1), expanding, never look-ahead)
    # mean return_fast before training/measuring -- the model can now only earn credit
    # for predicting genuine deviations from a symbol's own baseline drift, not the
    # baseline itself. Applied identically to the tree target and the baseline-feature
    # comparison so both are measured on the same demeaned quantity.
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
        if c not in _EXCLUDE_COLS
        and c not in ("return_fast", "return_fast_demeaned", "_causal_expanding_mean")
        and df[c].dtype.kind in "fc"
    ]
    print(
        f"Feature columns used ({len(feature_cols)}): {feature_cols[:10]}... (+{len(feature_cols) - 10} more)"
    )

    oos = _train_and_predict_oos(df, feature_cols, "return_fast_demeaned")
    print(f"\nTotal OOS (out-of-fold) rows: {len(oos)}")

    # Re-attach the baseline feature to the OOS frame for an apples-to-apples comparison.
    oos = oos.merge(
        df[["symbol", "bar_ts", _BASELINE_FEATURE]], on=["symbol", "bar_ts"], how="left"
    )

    print(
        f"\n=== Per-symbol OOS IC: tree_score vs {_BASELINE_FEATURE} (both on identical held-out rows, target=return_fast_demeaned) ==="
    )
    tree_ic = _per_symbol_ic_ci(
        oos, "tree_score", "return_fast_demeaned", _BOOTSTRAP_BLOCK_SIZE, _N_BOOT, _BOOTSTRAP_SEED
    )
    baseline_ic = _per_symbol_ic_ci(
        oos,
        _BASELINE_FEATURE,
        "return_fast_demeaned",
        _BOOTSTRAP_BLOCK_SIZE,
        _N_BOOT,
        _BOOTSTRAP_SEED,
    )

    print(f"\ntree_score: {len(tree_ic)} symbols with sufficient rows")
    print(
        f"  mean point_ic={tree_ic['point_ic'].mean():.4f}  "
        f"n_pass(ci_lower>0)={tree_ic['passes'].sum()}/{len(tree_ic)}"
    )
    print(f"\n{_BASELINE_FEATURE}: {len(baseline_ic)} symbols with sufficient rows")
    print(
        f"  mean point_ic={baseline_ic['point_ic'].mean():.4f}  "
        f"n_pass(ci_lower>0)={baseline_ic['passes'].sum()}/{len(baseline_ic)}"
    )

    merged = tree_ic.merge(baseline_ic, on="symbol", suffixes=("_tree", "_baseline"))
    uplift = merged["point_ic_tree"] - merged["point_ic_baseline"]
    print(
        f"\nPer-symbol IC uplift (tree - {_BASELINE_FEATURE}): "
        f"mean={uplift.mean():.4f}  median={uplift.median():.4f}  "
        f"n_symbols_tree_better={int((uplift > 0).sum())}/{len(merged)}"
    )

    print("\nVERDICT:", end=" ")
    tree_pass_rate = tree_ic["passes"].mean() if len(tree_ic) else 0.0
    baseline_pass_rate = baseline_ic["passes"].mean() if len(baseline_ic) else 0.0
    if tree_pass_rate > baseline_pass_rate * 1.5 and uplift.mean() > 0:
        print(
            "Tree combiner shows a real uplift over the single best standalone feature -- "
            "genuine T5 candidate, worth a closer look with proper OOS/shadow validation "
            "before any production consideration."
        )
    elif uplift.mean() <= 0:
        print(
            "Tree combiner does NOT beat the single best standalone feature's own IC on "
            "identical held-out data -- no evidence the linear-vs-nonlinear distinction is "
            "the bottleneck for this feature set. T5 fails at this scale/tf."
        )
    else:
        print(
            "Mixed result -- some uplift but not decisive; read the per-symbol table before "
            "drawing a conclusion either way."
        )

    # --- Rigor pass (2026-07-26): decompose common-market-factor vs genuine within-symbol
    # (cross-sectional, dollar-neutral-relevant) signal, then bootstrap CI the latter properly.
    # The naive per-symbol IC above pools across 80 correlated ETFs -- averaging effects can
    # inflate apparent correlation even under a constant true idiosyncratic IC (the same
    # IR ~ IC*sqrt(breadth) arithmetic docs/research/data-edge-source-thesis.md names as this
    # universe's binding constraint). The within-bar_ts component, after subtracting each
    # bar_ts's cross-sectional mean from both prediction and actual, isolates the part that's
    # actually relevant to a T3-style dollar-neutral construction.
    print("\n\n=== Rigor pass: within-bar_ts (cross-sectional-neutral) component, bootstrap CI ===")
    oos_sorted = oos.sort_values(["bar_ts", "symbol"]).reset_index(drop=True)
    for score_col in ("tree_score", _BASELINE_FEATURE):
        work = oos_sorted.dropna(subset=[score_col, "return_fast_demeaned"]).copy()
        bar_mean_score = work.groupby("bar_ts")[score_col].transform("mean")
        bar_mean_actual = work.groupby("bar_ts")["return_fast_demeaned"].transform("mean")
        within_score = (work[score_col] - bar_mean_score).to_numpy(dtype=float)
        within_actual = (work["return_fast_demeaned"] - bar_mean_actual).to_numpy(dtype=float)

        n_symbols_per_bar = work.groupby("bar_ts").size().median()
        block_size = max(10, int(n_symbols_per_bar * _CROSS_SECTIONAL_BLOCK_BARS))
        stats = _bootstrap_ic_stats(
            within_score, within_actual, block_size, _N_BOOT, _BOOTSTRAP_SEED
        )
        print(
            f"\n{score_col}: n={len(work)}  block_size={block_size} (~{_CROSS_SECTIONAL_BLOCK_BARS} "
            f"bar_ts x {n_symbols_per_bar:.0f} symbols)  point_ic={stats['point_ic']:.4f}  "
            f"ci_lower={stats['ci_lower']:.4f}  ci_upper={stats['ci_upper']:.4f}  passes={stats['passes']}"
        )

    print(
        "\nNote: block_size here approximates cross-sectional block structure (time-blocks "
        "spanning the full symbol universe) rather than todo 133's per-tf calibrated per-symbol "
        "value -- a reasonable first pass, not a final production calibration."
    )


if __name__ == "__main__":
    asyncio.run(main())
