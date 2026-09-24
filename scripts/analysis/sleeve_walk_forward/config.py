"""Pre-registered constants for the Phase 179 walk-forward
(docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md). APR-exempt: these are test
parameters fixed before any out-of-sample number exists; changing one is a methodology change."""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class HarnessConfig:
    sleeve: tuple[str, ...] = (
        "GLD",
        "DBA",
        "DBB",
        "DBC",
        "URA",
        "TLT",
        "UUP",
        "VIXY",
        "EMLC",
        "HYG",
        "XOM",
        "DHI",
        "PGR",
    )
    refit_years: range = range(2011, 2026)
    training_start: str = "2007-01-01"
    embargo_sessions: int = 5
    min_shift: int = 63
    warmup_sessions: int = 504
    calibration_refit_sessions: int = 252
    coverage_fraction: float = 0.95
    trading_start: str = "2013-01-01"
    sub_periods: tuple[tuple[str, str], ...] = (
        ("2013-01-01", "2016-12-31"),
        ("2017-01-01", "2020-12-31"),
        ("2021-01-01", "2025-12-23"),
    )
    alpha: float = 0.05
    n_tested: int = 15
    min_positive_sub_periods: int = 2
    bootstrap_mean_block: int = 21
    bootstrap_reps: int = 2000
    ic_shrinkage_k_key: str = "alpha.ic.shrinkage_k"
    mv_condition_max_key: str = "alpha.ensemble.mv_condition_max"
    ridge_epsilon_fraction: float = 0.10
    seed: int = 179
    # Matches infra.blas_threads_per_worker (1); passed to make_worker_pool (todo 216).
    blas_threads_per_worker: int = 1


DEFAULT_CONFIG = HarnessConfig()
