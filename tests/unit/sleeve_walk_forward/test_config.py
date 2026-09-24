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
    assert c.alpha == 0.05 and c.n_tested == 17
    assert c.min_positive_sub_periods == 2
    assert c.bootstrap_mean_block == 21
