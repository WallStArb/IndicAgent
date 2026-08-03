"""Edge Source Thesis nonlinear_interaction_combiner -- independent replication at a different timeframe.

nonlinear_interaction_combiner_lightgbm_check.py (equity/1h) found a tree combiner OOS point_ic=0.2992
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

Genuine methodological addition over the original 1h script at write time (not present in
nonlinear_interaction_combiner_lightgbm_check.py or its canary-leakage follow-up): BH-FDR correction
across the ~80 per-symbol tests, via ic_math.py's apply_bh_fdr (reused verbatim, same function
services/ic_engine.py's own multiple-comparisons correction uses -- never a fresh statistic
invented for this test). The research doc's own nonlinear_interaction_combiner falsification bar states the test must use
"the same walk-forward OOS discipline, day-clustered bootstrap CI, and BH-FDR correction as
everything else in this doc" -- the 1h script has since adopted the same correction (2026-08-02
cleanup), closing that gap for all three tfs on identical terms.

Orchestration lives in `_nonlinear_interaction_combiner_shared.py`'s `run_nonlinear_interaction_combiner_check()`, shared verbatim
with the 1h/15m scripts -- only the tf-calibrated constants below differ.

Usage: .venv/bin/python scripts/analysis/nonlinear_interaction_combiner_replication_1d.py
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
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    await run_nonlinear_interaction_combiner_check(
        _TF,
        db_dsn,
        csv_filename=f"t5-replication-{_TF}-per-symbol.csv",
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
