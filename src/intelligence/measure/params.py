"""Tunables for the measure package, passed in by the caller (the 186-14 writer).

No defaults: every value is read from APR by the writer and handed over, so no numeric literal
lives in this package (APR mandate). Field to APR key mapping is recorded in the 186-10 summary.
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class MeasureParams:
    min_stride: int  # alpha.ic.subsample_min_stride
    bootstrap_block_size: int  # alpha.ic.bootstrap_block_size.{tf}
    bootstrap_resamples: int  # alpha.ic.bootstrap_resamples
    rng_seed: int  # cell-level seed chosen by the writer
    fdr_alpha: float  # alpha.ic.fdr_alpha (BH-FDR level)
    min_obs: int  # alpha.ic.min_reliable_n (minimum finite pairs for a reliable cell)
    symbol_chunk_size: int  # infra.measure.symbol_chunk_size
    monitor_window_sessions: int  # alpha.ic.monitor_window_sessions
    hac_max_lag: int  # alpha.ic.hac_max_lag
    degenerate_std: float  # std floor below which a feature column is degenerate (ic_engine 1e-8)
    monitor_degenerate_std: float
    """Std floor below which the spread of a member's window ICs is degenerate, so its IC
    Sharpe is 0.0 rather than a ratio to a near-zero denominator (monitoring.py). A different
    quantity from `degenerate_std`, which floors a feature column's std. Callers pass 1e-10, the
    value the monitor used as a literal; 186-14 seeds it as an APR key (not seeded here)."""

    def __post_init__(self) -> None:
        for name in (
            "min_stride",
            "bootstrap_block_size",
            "bootstrap_resamples",
            "min_obs",
            "symbol_chunk_size",
            "monitor_window_sessions",
            "hac_max_lag",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive int, got {value!r}")
        if not isinstance(self.rng_seed, int) or isinstance(self.rng_seed, bool):
            raise ValueError(f"rng_seed must be an int, got {self.rng_seed!r}")
        if not 0.0 < self.fdr_alpha < 1.0:
            raise ValueError(f"fdr_alpha must be in (0, 1), got {self.fdr_alpha!r}")
        if not self.degenerate_std > 0.0:
            raise ValueError(f"degenerate_std must be positive, got {self.degenerate_std!r}")
        if not self.monitor_degenerate_std > 0.0:
            raise ValueError(
                f"monitor_degenerate_std must be positive, got {self.monitor_degenerate_std!r}"
            )
