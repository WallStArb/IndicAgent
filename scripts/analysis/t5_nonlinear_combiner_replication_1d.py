"""Edge Source Thesis T5 -- independent replication at a different timeframe.

t5_nonlinear_combiner_lightgbm_check.py (equity/1h) found a tree combiner OOS point_ic=0.2992
vs. ctf_momentum's 0.09 -- a ~3.4x uplift, ~3x anything else measured in this corpus. Todo 184's
canary-leakage check ruled out look-ahead leakage as the explanation. Per this project's
resist-overfitting discipline and the research doc's own next-step ("independent replication --
a different tf, a different OOS window -- not further leakage investigation on this same
result"), this script reruns the identical pipeline at equity/1d.

Why 1d, not 15m: 15m has ~8.1M equity rows (vs. 1d's ~330K); with the concurrent todo 183
ic_engine recompute holding ~9GB RSS and only ~12GB available on this machine at the time this
was written, loading 15m's full corpus into one in-memory DataFrame risked OOM/heavy swapping.
1d is also the scientifically stronger "different regime" test on its own merits, independent
of the memory constraint: it is a much bigger frequency jump from the original 1h test than 15m
would be (different microstructure, different noise characteristics, less risk that a
replication at a nearby frequency "succeeds" for boring reasons like shared regime artifacts).

Reuses t5_nonlinear_combiner_lightgbm_check.py's _FV_SQL, _train_and_predict_oos,
_per_symbol_ic_ci, _bootstrap_ic_stats, and the causal per-symbol demeaning fix VERBATIM --
only _TF, _EMBARGO_BARS, _BOOTSTRAP_BLOCK_SIZE, and _MIN_SYMBOL_ROWS are recalibrated for 1d's
different bar cadence and lower row count.

Genuine methodological addition over the original script (not present in
t5_nonlinear_combiner_lightgbm_check.py or its canary-leakage follow-up): BH-FDR correction
across the ~80 per-symbol tests, via ic_math.py's apply_bh_fdr (reused verbatim, same function
services/ic_engine.py's own multiple-comparisons correction uses -- never a fresh statistic
invented for this test). The research doc's own T5 falsification bar states the test must use
"the same walk-forward OOS discipline, day-clustered bootstrap CI, and BH-FDR correction as
everything else in this doc" -- the original script and its leak-check follow-up compared raw
per-symbol ci_lower>0 counts without ever applying that correction. This script closes that gap
for both the tree and the baseline feature, on identical terms.

Usage: .venv/bin/python scripts/analysis/t5_nonlinear_combiner_replication_1d.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import asyncpg  # noqa: E402

import scripts.analysis.t5_nonlinear_combiner_lightgbm_check as _t5_orig  # noqa: E402
from scripts.analysis.t5_nonlinear_combiner_lightgbm_check import (  # noqa: E402
    _BASELINE_FEATURE,
    _EXCLUDE_COLS,
    _FV_SQL,
    _bootstrap_ic_stats,
    _per_symbol_ic_ci,
    _train_and_predict_oos,
)
from src.config.settings import Settings  # noqa: E402
from src.intelligence.statistics.ic_math import _p_values_from_ic, apply_bh_fdr  # noqa: E402

_CROSS_SECTIONAL_BLOCK_BARS = 2

_TF = "1d"
_N_FOLDS = 5
# 1h's original embargo was 24 bars = 1 calendar day, a wide buffer around a 1-bar-ahead
# target (return_fast) intended to keep rolling-window features from leaking training-period
# information into the earliest test rows. Scaling that same "buffer beyond the target
# horizon" intent to 1d bars: 5 bars = 1 trading week around a 1-bar-ahead target. A judgment
# call, same as the original's 24, not a derived constant.
_EMBARGO_BARS = 5
_MIN_RELIABLE_N = 50
_BOOTSTRAP_BLOCK_SIZE = 10  # matches live alpha.ic.bootstrap_block_size.1d (verified in DB)
_N_BOOT = 500
_BOOTSTRAP_SEED = 42
# Lower than 1h's 300: 1d's ~330K total rows / 80 symbols over ~19 years leaves meaningfully
# fewer OOS rows per symbol than 1h's much denser corpus even after walk-forward fold sizing.
_MIN_SYMBOL_ROWS = 100
_FDR_ALPHA = 0.05


async def main() -> None:
    # _train_and_predict_oos and _per_symbol_ic_ci are IMPORTED from
    # t5_nonlinear_combiner_lightgbm_check.py, so their references to
    # _N_FOLDS/_EMBARGO_BARS/_MIN_RELIABLE_N/_BOOTSTRAP_SEED/_MIN_SYMBOL_ROWS resolve in THAT
    # module's globals, not this script's -- redefining those names locally would silently do
    # nothing (e.g. the original module's _EMBARGO_BARS=24 would run instead of this script's
    # intended 5, and its _MIN_SYMBOL_ROWS=300 instead of 100). Override explicitly and
    # visibly, once, before any reused function that depends on them is called.
    _t5_orig._N_FOLDS = _N_FOLDS
    _t5_orig._EMBARGO_BARS = _EMBARGO_BARS
    _t5_orig._MIN_RELIABLE_N = _MIN_RELIABLE_N
    _t5_orig._BOOTSTRAP_SEED = _BOOTSTRAP_SEED
    _t5_orig._MIN_SYMBOL_ROWS = _MIN_SYMBOL_ROWS

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

    # Same causal per-symbol demeaning fix the original script applied after finding the
    # static-drift leak (2026-07-26) -- required here too, not tf-specific.
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
    print(f"Feature columns used: {len(feature_cols)}")

    oos = _train_and_predict_oos(df, feature_cols, "return_fast_demeaned")
    print(f"\nTotal OOS (out-of-fold) rows: {len(oos)}")

    oos = oos.merge(
        df[["symbol", "bar_ts", _BASELINE_FEATURE]], on=["symbol", "bar_ts"], how="left"
    )

    print(
        f"\n=== Per-symbol OOS IC: tree_score vs {_BASELINE_FEATURE} "
        f"(tf={_TF}, target=return_fast_demeaned) ==="
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

    # BH-FDR pass -- the methodological addition over the original script. Per-symbol
    # p-values via ic_math.py's _p_values_from_ic (same t-approximation ic_engine.py uses),
    # then apply_bh_fdr across the family of ~80 symbol tests, for each of tree/baseline
    # independently. _p_values_from_ic takes one shared n per call (matches its production
    # usage in ic_engine.py, where a single call covers one symbol's several features at
    # that symbol's own n) -- since each SYMBOL here has its own distinct OOS row count,
    # call it once per symbol with that symbol's own n, not once for the whole vector with
    # an approximated shared n.
    for label, ic_df in (("tree_score", tree_ic), (_BASELINE_FEATURE, baseline_ic)):
        if len(ic_df) == 0:
            continue
        p_values = np.array(
            [
                float(_p_values_from_ic(np.array([ic]), n=int(n))[0])
                for ic, n in zip(ic_df["point_ic"], ic_df["n"], strict=True)
            ]
        )
        reject, p_corrected = apply_bh_fdr(list(p_values), alpha=_FDR_ALPHA)
        ic_df["p_value"] = p_values
        ic_df["p_value_fdr"] = p_corrected
        # _p_values_from_ic is TWO-TAILED (significantly different from zero in EITHER
        # direction) -- `reject` alone answers "is this symbol's IC significant," not "is it
        # significantly POSITIVE." Gate on sign too, matching the one-sided ci_lower>0
        # semantics `passes` already uses, or a symbol with a strong significant NEGATIVE IC
        # would silently count as a "pass" here.
        ic_df["passes_fdr_significant"] = reject
        ic_df["passes_fdr"] = reject & (ic_df["point_ic"] > 0)
        print(
            f"\n{label}: {len(ic_df)} symbols with sufficient rows -- "
            f"mean point_ic={ic_df['point_ic'].mean():.4f}  "
            f"n_pass(ci_lower>0)={ic_df['passes'].sum()}/{len(ic_df)}  "
            f"n_pass_fdr_significant_either_sign(BH q<{_FDR_ALPHA})="
            f"{int(ic_df['passes_fdr_significant'].sum())}/{len(ic_df)}  "
            f"n_pass_fdr_positive(BH q<{_FDR_ALPHA} AND IC>0)="
            f"{int(ic_df['passes_fdr'].sum())}/{len(ic_df)}"
        )

    merged = tree_ic.merge(baseline_ic, on="symbol", suffixes=("_tree", "_baseline"))
    uplift = merged["point_ic_tree"] - merged["point_ic_baseline"]
    print(
        f"\nPer-symbol IC uplift (tree - {_BASELINE_FEATURE}): "
        f"mean={uplift.mean():.4f}  median={uplift.median():.4f}  "
        f"n_symbols_tree_better={int((uplift > 0).sum())}/{len(merged)}"
    )

    out_dir = Path("docs/analysis")
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"t5-replication-{_TF}-per-symbol.csv"
    merged.to_csv(csv_path, index=False)
    print(f"\nFull per-symbol table written to {csv_path}")

    print("\nVERDICT:", end=" ")
    tree_pass_rate = tree_ic["passes"].mean() if len(tree_ic) else 0.0
    baseline_pass_rate = baseline_ic["passes"].mean() if len(baseline_ic) else 0.0
    tree_fdr_rate = tree_ic["passes_fdr"].mean() if len(tree_ic) else 0.0
    if tree_pass_rate > baseline_pass_rate * 1.5 and uplift.mean() > 0 and tree_fdr_rate > 0.5:
        print(
            "Tree combiner shows a real uplift over the single best standalone feature, "
            "surviving BH-FDR correction at 1d -- replicates the 1h finding. Strong evidence "
            "toward T5 being real, worth production-track investment."
        )
    elif uplift.mean() <= 0:
        print(
            "Tree combiner does NOT beat the single best standalone feature's own IC on "
            "identical held-out data at 1d -- does NOT replicate the 1h finding."
        )
    else:
        print(
            "Mixed/weak result at 1d -- some uplift but not decisive after BH-FDR correction; "
            "read the per-symbol table before drawing a conclusion either way."
        )

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
            f"\n{score_col}: n={len(work)}  block_size={block_size}  "
            f"point_ic={stats['point_ic']:.4f}  ci_lower={stats['ci_lower']:.4f}  "
            f"ci_upper={stats['ci_upper']:.4f}  passes={stats['passes']}"
        )


if __name__ == "__main__":
    asyncio.run(main())
