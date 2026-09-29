"""feature_coverage: the one definition of per-(feature, tf) data quality (186-09, D-30)."""

from __future__ import annotations

import pytest

from src.intelligence.statistics.feature_coverage import (
    SymbolCounts,
    feature_quality_verdict,
    feature_tf_quality,
)


def _q(feature: str, tf: str, counts: list[SymbolCounts]):
    return feature_tf_quality(feature, tf, counts)


def test_quality_counts_populated_symbols():
    q = _q(
        "f",
        "1h",
        [
            SymbolCounts("A", 10, 10, 0),
            SymbolCounts("B", 10, 5, 0),
            SymbolCounts("C", 10, 0, 0),
            SymbolCounts("D", 10, 10, 1),
        ],
    )
    assert q.n_symbols_with_rows == 4
    assert q.n_symbols_populated == 3
    assert q.symbol_coverage == pytest.approx(0.75)
    assert q.non_null_share == pytest.approx(25 / 40)
    assert q.n_non_finite == 1
    assert q.n_rows == 40


def test_symbol_with_rows_but_no_values_is_in_denominator_only():
    q = _q("f", "1h", [SymbolCounts("A", 5, 0, 0), SymbolCounts("B", 5, 5, 0)])
    assert q.n_symbols_with_rows == 2
    assert q.n_symbols_populated == 1
    assert q.symbol_coverage == 0.5


def test_zero_symbols_gives_no_claim():
    q = _q("f", "1h", [])
    assert q.symbol_coverage is None
    assert q.non_null_share is None
    assert q.n_symbols_with_rows == 0


def test_symbol_with_zero_rows_is_not_counted():
    q = _q("f", "1h", [SymbolCounts("A", 0, 0, 0), SymbolCounts("B", 4, 4, 0)])
    assert q.n_symbols_with_rows == 1
    assert q.symbol_coverage == 1.0


def _full(tf: str, n_pop: int, n_all: int, non_finite: int = 0):
    counts = [SymbolCounts(f"S{i}", 10, 10 if i < n_pop else 0, 0) for i in range(n_all)]
    if non_finite:
        counts[0] = SymbolCounts("S0", 10, 10, non_finite)
    return _q("f", tf, counts)


def test_verdict_not_computed_when_no_tf_has_values():
    v = feature_quality_verdict([_full("5m", 0, 10), _full("1h", 0, 10)], 0.95)
    assert not v.passed
    assert v.failures == ("not_computed",)
    assert v.statistic is None


def test_verdict_not_computed_with_no_evidence_at_all():
    v = feature_quality_verdict([], 0.95)
    assert not v.passed
    assert v.failures == ("not_computed",)


def test_verdict_non_finite_fails():
    v = feature_quality_verdict([_full("1h", 10, 10, non_finite=2)], 0.95)
    assert not v.passed
    assert "non_finite" in v.failures
    assert v.per_tf["1h"] == "non_finite"


def test_verdict_coverage_fails_below_floor():
    v = feature_quality_verdict([_full("5m", 1, 10), _full("1h", 10, 10)], 0.95)
    assert not v.passed
    assert v.failures == ("coverage",)
    assert v.per_tf == {"5m": "coverage", "1h": "ok"}
    assert v.statistic == pytest.approx(0.1)


def test_verdict_tf_with_all_null_does_not_fail_when_another_tf_populated():
    v = feature_quality_verdict([_full("5m", 0, 10), _full("1h", 10, 10)], 0.95)
    assert v.passed
    assert v.failures == ()
    assert v.per_tf == {"5m": "not_emitted_at_tf", "1h": "ok"}
    assert v.statistic == 1.0


def test_verdict_passes_and_statistic_is_minimum_coverage():
    v = feature_quality_verdict([_full("5m", 96, 100), _full("1h", 100, 100)], 0.95)
    assert v.passed
    assert v.statistic == pytest.approx(0.96)


def test_verdict_coverage_at_floor_passes():
    v = feature_quality_verdict([_full("1h", 95, 100)], 0.95)
    assert v.passed
