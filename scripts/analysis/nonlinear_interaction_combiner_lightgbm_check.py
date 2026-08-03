"""Edge Source Thesis nonlinear_interaction_combiner falsification test (non-linear interaction combiner) -- equity/1h,
the original finding.

docs/research/data-edge-source-thesis.md nonlinear_interaction_combiner: ensemble_trainer.py's linear, shrunk-IC-weighted
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
  - BH-FDR corrected across the ~80 per-symbol tests -- added 2026-08-02 (todo 232 cleanup):
    this script's own replications (1d, 15m) already applied this correction; the research
    doc's own nonlinear_interaction_combiner bar requires it everywhere, and the flagship number shouldn't be held to a
    lower methodological bar than its confirmatory replications.
  - Directly compared against the single strongest standalone feature (ctf_momentum, same one
    cross_sectional_relative_value tests) measured the identical way, on the identical held-out population -- an uplift
    test, not an absolute-performance claim.

Orchestration lives in `_nonlinear_interaction_combiner_shared.py`'s `run_nonlinear_interaction_combiner_check()`, shared verbatim
with the 1d/15m replication scripts -- only the tf-calibrated constants below differ.

Usage: .venv/bin/python scripts/analysis/nonlinear_interaction_combiner_lightgbm_check.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.analysis._nonlinear_interaction_combiner_shared import (
    run_nonlinear_interaction_combiner_check,  # noqa: E402
)
from src.config.settings import Settings  # noqa: E402

_TF = "1h"
_N_FOLDS = 5
_EMBARGO_BARS = 24  # 1 day of 1h bars, avoids train/test leakage across the fold boundary
_MIN_RELIABLE_N = 50
_BOOTSTRAP_BLOCK_SIZE = 10  # matches live alpha.ic.bootstrap_block_size.1h
_N_BOOT = 500  # reduced from production's 2000 -- exploratory pass, not a promotion gate
_BOOTSTRAP_SEED = 42
_MIN_SYMBOL_ROWS = 300  # per-symbol floor for a meaningful per-symbol IC estimate
_FDR_ALPHA = 0.05


async def main() -> None:
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    await run_nonlinear_interaction_combiner_check(
        _TF,
        db_dsn,
        csv_filename=f"t5-{_TF}-per-symbol.csv",
        embargo_bars=_EMBARGO_BARS,
        bootstrap_block_size=_BOOTSTRAP_BLOCK_SIZE,
        min_symbol_rows=_MIN_SYMBOL_ROWS,
        n_folds=_N_FOLDS,
        min_reliable_n=_MIN_RELIABLE_N,
        n_boot=_N_BOOT,
        bootstrap_seed=_BOOTSTRAP_SEED,
        fdr_alpha=_FDR_ALPHA,
    )


if __name__ == "__main__":
    asyncio.run(main())
