"""Edge Source Thesis nonlinear_interaction_combiner -- independent replication at 15m, the directly actionable tf.

Todo 188: nonlinear_interaction_combiner_replication_1d.py already replicated the tree-combiner finding
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

Orchestration lives in `_nonlinear_interaction_combiner_shared.py`'s `run_nonlinear_interaction_combiner_check()`, shared verbatim
with the 1h/1d scripts -- only the tf-calibrated constants below differ.

Usage: .venv/bin/python scripts/analysis/nonlinear_interaction_combiner_replication_15m.py
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
