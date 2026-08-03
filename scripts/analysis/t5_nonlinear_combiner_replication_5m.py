"""Edge Source Thesis T5 -- independent replication at 5m, the highest-frequency tf measured.

1h/1d/15m all replicate (see `docs/research/data-edge-source-thesis.md`'s T5 section, v1.8):
substantial at 1h and 15m (cross-sectional-neutral point_ic 0.18-0.25), small specifically at
1d (0.0127, confounded by 1d's own known-degenerate `ctf_momentum` baseline, todo 189). 5m is
the one remaining untested tf and the highest-frequency data this corpus has -- Renaissance's
own historical edge came substantially from pushing frequency up, per this doc's own "Breadth
Is the Binding Constraint" section, so a 5m data point closes a real gap rather than adding a
redundant one.

5m is ~24.6M equity rows -- 2.9x 15m's ~8.5M and far past what fits as float32 on this 29GB
host (X alone would be ~23GB, before any training overhead). `feature_dtype=np.float16` (the
one override on this script relative to its 1h/1d/15m siblings) halves that to ~11.6GB, a
resource necessity, not a data-dropping shortcut -- every row is still used, consistent with
this project's "never drop data that could contain signal" principle. Row-subsampling was
considered and rejected on exactly that basis. LightGBM bins every feature into ~255 histogram
buckets internally regardless of input precision, so float32's extra mantissa bits were already
discarded by the algorithm itself; confirmed empirically before relying on it (see
`fetch_training_matrix`'s docstring in `_t5_nonlinear_combiner_shared.py`) rather than assumed.

Orchestration lives in `_t5_nonlinear_combiner_shared.py`'s `run_t5_check()`, shared with the
1h/1d/15m scripts -- only the tf-calibrated constants below (and `feature_dtype`) differ.

Usage: .venv/bin/python scripts/analysis/t5_nonlinear_combiner_replication_5m.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.analysis._t5_nonlinear_combiner_shared import run_t5_check  # noqa: E402
from src.config.settings import Settings  # noqa: E402

_TF = "5m"
_N_FOLDS = 5
# 1h's original embargo was 24 bars = 1 calendar day. 5m has 12x the bar density of 1h
# (60/5=12), so 24*12=288 bars = 1 calendar day at 5m, same "buffer beyond the target horizon"
# intent as every other tf's embargo, not a fresh derivation.
_EMBARGO_BARS = 288
_MIN_RELIABLE_N = 50
_BOOTSTRAP_BLOCK_SIZE = 78  # live alpha.ic.bootstrap_block_size.5m, verified in config_state
_N_BOOT = 500
_BOOTSTRAP_SEED = 42
# 5m has ~2.9x 15m's row count over the same symbol set -- keep 15m's floor (300), which is
# already far more conservative than 1d's (100) relative to each tf's own OOS row density.
_MIN_SYMBOL_ROWS = 300
_FDR_ALPHA = 0.05


async def main() -> None:
    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    await run_t5_check(
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
        feature_dtype=np.float16,
    )


if __name__ == "__main__":
    asyncio.run(main())
