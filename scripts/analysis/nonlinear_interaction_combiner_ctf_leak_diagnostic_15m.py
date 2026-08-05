"""Todo 245's diagnostic at 15m -- the tf Phase 167's live construction actually trades.

Same question as nonlinear_interaction_combiner_ctf_leak_diagnostic_1h.py (1h result, confirmed
2026-08-03: tree's cross-sectional-neutral point_ic collapsed 90.6% (0.1811 -> 0.0171) once
`ctf_momentum`/`ctf_vwap_align`/`ctf_regime_align` were excluded from the training matrix;
n_pass_fdr_positive fell 80/80 -> 21/80; a small, real, statistically significant edge survives,
tree-linear diff=0.0106, ci_lower=0.0064). 1h does NOT automatically generalize -- this is the
15m rerun.

Runs `run_nonlinear_interaction_combiner_check()` TWICE at 15m, under the identical corrected
methodology (todos 239/240 -- bar-unit embargo, linear-ensemble PRIMARY arm), with only ONE
variable changed between the two runs:

  1. "with_ctf"    -- the real 15m re-run, CTF columns included (baseline_feature=ctf_momentum,
                       matching every prior published number's convention).
  2. "without_ctf" -- CTF columns excluded via `extra_exclude_cols` (NOT a hand-edit of the
                       shared EXCLUDE_COLS constant -- see `_select_feature_columns`'s docstring
                       for why that would be a real hazard in this concurrently-edited repo).
                       `baseline_feature` switched to `momentum_z_fast` for this run only, since
                       `ctf_momentum` is no longer a trained column and the baseline lookup reads
                       its value out of the fetched matrix by name (would raise ValueError
                       otherwise -- fail loud, not silently compare against nothing).

tf-calibrated constants (embargo_bars=96, bootstrap_block_size=26, min_symbol_rows=300) match
nonlinear_interaction_combiner_replication_15m.py exactly -- apples-to-apples with the already-
published 15m number, only the CTF-inclusion variable changes.

Usage: .venv/bin/python scripts/analysis/nonlinear_interaction_combiner_ctf_leak_diagnostic_15m.py
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
_EMBARGO_BARS = 96  # 96 bars = 1 calendar day at 15m (24 * 4), same intent as the 1h script's 24
_MIN_RELIABLE_N = 50
_BOOTSTRAP_BLOCK_SIZE = 26  # live alpha.ic.bootstrap_block_size.15m
_N_BOOT = 500
_BOOTSTRAP_SEED = 42
_MIN_SYMBOL_ROWS = 300
_FDR_ALPHA = 0.05

_CTF_COLS = frozenset({"ctf_momentum", "ctf_vwap_align", "ctf_regime_align"})


async def main() -> None:
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")

    print("=" * 100)
    print("RUN 1/2: with_ctf -- CTF columns included (the real 15m re-run under todos 239/240)")
    print("=" * 100)
    await run_nonlinear_interaction_combiner_check(
        _TF,
        db_dsn,
        csv_filename="t5-ctf-leak-diagnostic-15m-with-ctf-per-symbol.csv",
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
        csv_filename="t5-ctf-leak-diagnostic-15m-without-ctf-per-symbol.csv",
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
    print("doing real work in the published '15m' finding.")
    print("=" * 100)


if __name__ == "__main__":
    asyncio.run(main())
