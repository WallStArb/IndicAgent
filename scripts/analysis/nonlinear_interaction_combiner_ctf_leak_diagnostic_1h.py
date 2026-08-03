"""Todo 245's diagnostic: does nonlinear_interaction_combiner's tree-vs-linear uplift at 1h
survive removing the three lookahead-contaminated CTF columns (todo 243: `ctf_momentum`,
`ctf_vwap_align`, `ctf_regime_align` all share the identical batch join that selects the
still-forming HTF bar, not the last completed one)?

Runs `run_nonlinear_interaction_combiner_check()` TWICE at 1h, under the identical corrected
methodology (todos 239/240 -- bar-unit embargo, linear-ensemble PRIMARY arm), with only ONE
variable changed between the two runs:

  1. "with_ctf"    -- the real 1h re-run, CTF columns included (baseline_feature=ctf_momentum,
                       matching every prior published number's convention).
  2. "without_ctf" -- CTF columns excluded via `extra_exclude_cols` (NOT a hand-edit of the
                       shared EXCLUDE_COLS constant -- see `_select_feature_columns`'s docstring
                       for why that would be a real hazard in this concurrently-edited repo).
                       `baseline_feature` switched to `momentum_z_fast` for this run only, since
                       `ctf_momentum` is no longer a trained column and the baseline lookup reads
                       its value out of the fetched matrix by name (would raise ValueError
                       otherwise -- fail loud, not silently compare against nothing).

If the tree's uplift over the linear ensemble collapses in run 2 relative to run 1, the
lookahead leak was doing real work in the published "substantial at 1h" finding. If it survives,
that's evidence of genuine non-linear structure independent of the leak. 1h chosen as the
cheapest affected timeframe (5m/15m are much larger; 1d is unaffected and doesn't need this).

Usage: .venv/bin/python scripts/analysis/nonlinear_interaction_combiner_ctf_leak_diagnostic_1h.py
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

# Identical to nonlinear_interaction_combiner_lightgbm_check.py's calibrated 1h constants --
# apples-to-apples with the already-published number, only the CTF-inclusion variable changes.
_TF = "1h"
_N_FOLDS = 5
_EMBARGO_BARS = 24
_MIN_RELIABLE_N = 50
_BOOTSTRAP_BLOCK_SIZE = 10
_N_BOOT = 500
_BOOTSTRAP_SEED = 42
_MIN_SYMBOL_ROWS = 300
_FDR_ALPHA = 0.05

_CTF_COLS = frozenset({"ctf_momentum", "ctf_vwap_align", "ctf_regime_align"})


async def main() -> None:
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")

    print("=" * 100)
    print("RUN 1/2: with_ctf -- CTF columns included (the real 1h re-run under todos 239/240)")
    print("=" * 100)
    await run_nonlinear_interaction_combiner_check(
        _TF,
        db_dsn,
        csv_filename="t5-ctf-leak-diagnostic-1h-with-ctf-per-symbol.csv",
        embargo_bars=_EMBARGO_BARS,
        bootstrap_block_size=_BOOTSTRAP_BLOCK_SIZE,
        min_symbol_rows=_MIN_SYMBOL_ROWS,
        baseline_feature="ctf_momentum",
        n_folds=_N_FOLDS,
        min_reliable_n=_MIN_RELIABLE_N,
        n_boot=_N_BOOT,
        bootstrap_seed=_BOOTSTRAP_SEED,
        fdr_alpha=_FDR_ALPHA,
    )

    print("\n" + "=" * 100)
    print("RUN 2/2: without_ctf -- ctf_momentum/ctf_vwap_align/ctf_regime_align excluded")
    print("=" * 100)
    await run_nonlinear_interaction_combiner_check(
        _TF,
        db_dsn,
        csv_filename="t5-ctf-leak-diagnostic-1h-without-ctf-per-symbol.csv",
        embargo_bars=_EMBARGO_BARS,
        bootstrap_block_size=_BOOTSTRAP_BLOCK_SIZE,
        min_symbol_rows=_MIN_SYMBOL_ROWS,
        baseline_feature="momentum_z_fast",
        n_folds=_N_FOLDS,
        min_reliable_n=_MIN_RELIABLE_N,
        n_boot=_N_BOOT,
        bootstrap_seed=_BOOTSTRAP_SEED,
        fdr_alpha=_FDR_ALPHA,
        extra_exclude_cols=_CTF_COLS,
    )

    print("\n" + "=" * 100)
    print("Compare the two PRIMARY VERDICT lines above (tree vs linear ensemble) directly.")
    print("If run 2's tree uplift collapsed relative to run 1's, the CTF lookahead leak was")
    print("doing real work in the published 'substantial at 1h' finding.")
    print("=" * 100)


if __name__ == "__main__":
    asyncio.run(main())
