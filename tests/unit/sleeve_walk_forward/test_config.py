import dataclasses

import pytest

from scripts.analysis.sleeve_walk_forward.config import DEFAULT_CONFIG


def test_config_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        DEFAULT_CONFIG.min_shift = 1  # type: ignore[misc]


def test_pinned_values_match_prereg():
    c = DEFAULT_CONFIG
    assert c.sleeve == (
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
    assert c.refit_years == range(2011, 2026)
    assert c.training_start == "2007-01-01"
    assert c.embargo_sessions == 5
    assert c.min_shift == 63
    assert c.warmup_sessions == 504
    assert c.calibration_refit_sessions == 252
    assert c.coverage_fraction == 0.95
    assert c.trading_start == "2013-01-01"
    assert c.sub_periods == (
        ("2013-01-01", "2016-12-31"),
        ("2017-01-01", "2020-12-31"),
        ("2021-01-01", "2025-12-23"),
    )
    assert c.alpha == 0.05 and c.n_tested == 18
    assert c.min_positive_sub_periods == 2
    assert c.bootstrap_mean_block == 21


def test_shift_memory_covers_the_longest_bounded_feature_reach():
    """Todo 424: 504 (price_vol_corr_slow) + 252 (z-score window) + 2 (forward span)."""
    from scripts.analysis.sleeve_walk_forward.config import DEFAULT_CONFIG
    from scripts.analysis.sleeve_walk_forward.score import FWD_SPAN_SESSIONS

    assert DEFAULT_CONFIG.shift_memory == 504 + 252 + FWD_SPAN_SESSIONS
