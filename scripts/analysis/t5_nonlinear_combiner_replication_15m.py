"""Edge Source Thesis T5 -- independent replication at 15m, the directly actionable tf.

Todo 188: t5_nonlinear_combiner_replication_1d.py already replicated the tree-combiner finding
at 1d (confirmed SMALL, point_ic=0.0164 vs the original 1h's 0.2992 -- a ~16x magnitude
collapse). That result answers "is this real at all" (yes) but not "does it matter at the tf
Phase 167's live construction actually trades" -- `cross_sectional_spread_tracker.py` ranks
`ctf_momentum` at 15m, not 1h or 1d. This script closes that gap.

Deferred at 1d-script write time (2026-07-26) on memory contention: 15m is ~8.1M equity rows
vs 1d's ~330K, and the concurrent todo 183 `ic_engine` recompute was holding ~9GB RSS against
~12GB available. Todo 183 completed 2026-07-27T21:55 UTC; this script's own run was further
sequenced to avoid contending with todo 167's scoped `ic_engine` equity re-run (2026-07-27,
same day) -- launched only after that process exited, same single-writer-adjacent discipline,
applied to memory rather than DB writes this time.

Reuses t5_nonlinear_combiner_lightgbm_check.py's _FV_SQL, _train_and_predict_oos,
_per_symbol_ic_ci, _bootstrap_ic_stats, and ic_math.py's causal_entity_expanding_mean for the
same per-symbol demeaning fix -- only _TF, _EMBARGO_BARS, _BOOTSTRAP_BLOCK_SIZE, and
_MIN_SYMBOL_ROWS are recalibrated for 15m's cadence, same pattern the 1d script established.
BH-FDR correction included, same as the 1d script (methodological parity, not re-derived).

Usage: .venv/bin/python scripts/analysis/t5_nonlinear_combiner_replication_15m.py
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
from src.intelligence.statistics.ic_math import (  # noqa: E402
    _p_values_from_ic,
    apply_bh_fdr,
    causal_entity_expanding_mean,
)

_CROSS_SECTIONAL_BLOCK_BARS = 2

_TF = "15m"
_N_FOLDS = 5
# 1h's original embargo was 24 bars = 1 calendar day (a 1-bar-ahead target, return_fast).
# 15m has 4x the bar density of 1h, so 24*4=96 bars = 1 calendar day at 15m, same "buffer
# beyond the target horizon" intent as the original, not a fresh derivation.
_EMBARGO_BARS = 96
_MIN_RELIABLE_N = 50
_BOOTSTRAP_BLOCK_SIZE = 26  # live alpha.ic.bootstrap_block_size.15m, verified in config_state
_N_BOOT = 500
_BOOTSTRAP_SEED = 42
# 15m's ~8.1M total rows / ~49 equity symbols leaves far more OOS rows per symbol than 1d's
# 330K/80 -- keep the original 1h script's own floor (300) rather than 1d's lowered 100.
_MIN_SYMBOL_ROWS = 300
_FDR_ALPHA = 0.05


async def main() -> None:
    # See t5_nonlinear_combiner_replication_1d.py's identical comment: _train_and_predict_oos
    # and _per_symbol_ic_ci resolve _N_FOLDS/_EMBARGO_BARS/etc. in the ORIGINAL module's
    # globals, not this script's -- must override explicitly before calling either.
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

    df["_causal_expanding_mean"] = causal_entity_expanding_mean(
        df["symbol"].to_numpy(), df["return_fast"].to_numpy(), min_periods=50
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
    del df  # ~8.1M-row frame no longer needed; free it before the bootstrap-heavy tail below.

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

    tree_pass_rate = tree_ic["passes"].mean() if len(tree_ic) else 0.0
    baseline_pass_rate = baseline_ic["passes"].mean() if len(baseline_ic) else 0.0
    tree_fdr_rate = tree_ic["passes_fdr"].mean() if len(tree_ic) else 0.0
    if tree_pass_rate > baseline_pass_rate * 1.5 and uplift.mean() > 0 and tree_fdr_rate > 0.5:
        verdict = (
            "Tree combiner shows a real uplift over the single best standalone feature, "
            "surviving BH-FDR correction at 15m -- replicates the 1h finding at the tf that "
            "matters most (Phase 167's live construction trades ctf_momentum here). Strong "
            "evidence toward T5 being real and directly actionable."
        )
    elif uplift.mean() <= 0:
        verdict = (
            "Tree combiner does NOT beat the single best standalone feature's own IC on "
            "identical held-out data at 15m -- does NOT replicate the 1h finding at the "
            "actionable tf."
        )
    else:
        verdict = (
            "Mixed/weak result at 15m -- some uplift but not decisive after BH-FDR "
            "correction; read the per-symbol table before drawing a conclusion either way."
        )
    print(f"\nVERDICT: {verdict}")

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
