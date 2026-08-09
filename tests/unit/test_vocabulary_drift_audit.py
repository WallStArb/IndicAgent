"""Unit tests: vocabulary drift audit pure comparison logic (Phase 161 Plan 03).

Pure-Python, no-DB style (mirrors tests/unit/test_concept_registry_service.py /
test_vocabulary_service.py): exercises the observed-vs-registered comparison core,
the regime '' extractor, the regime_group guard, and the idle/deprecation
classification -- all against literal fixtures, no DB connection or pool required.

Extended Phase 172 plan 02, Task 3: regime_volatility namespace registration
(_WINDOWED_NAMESPACE_QUERIES entry, assert_namespace_coverage recognition) and the
extract_regime_hmm_codes -> extract_regime_codes rename (column-agnostic, same
logic, both regime_hmm and regime_volatility use it).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from src.config.vocabulary_drift import (
    _WINDOWED_NAMESPACE_QUERIES,
    NamespaceDriftResult,
    assert_namespace_coverage,
    classify_namespace_drift,
    extract_regime_codes,
    unregistered_codes,
    unregistered_groups,
)

# ---------------------------------------------------------------------------
# Behavior 1: observed-vs-registered comparison core (data-superset).
# ---------------------------------------------------------------------------


def test_unregistered_codes_returns_data_superset():
    observed = ["trending_up", "ranging", "mystery_code"]
    registered = ["trending_up", "transition_down", "ranging", "transition_up", "trending_down"]

    result = unregistered_codes(observed, registered)

    assert result == {"mystery_code"}


def test_unregistered_codes_returns_empty_set_when_all_registered():
    observed = ["1m", "5m", "1h"]
    registered = ["1m", "5m", "15m", "1h", "1d"]

    assert unregistered_codes(observed, registered) == set()


# ---------------------------------------------------------------------------
# Behavior 2: regime_hmm observed-code extractor drops '' (Finding 3).
# ---------------------------------------------------------------------------


def test_extract_regime_codes_drops_empty_string():
    raw = ["trending_up", "", "ranging", "transition_down"]

    result = extract_regime_codes(raw)

    assert result == ["trending_up", "ranging", "transition_down"]
    assert "" not in result


def test_extract_regime_codes_no_empty_string_is_noop():
    raw = ["trending_up", "ranging"]

    assert extract_regime_codes(raw) == raw


def test_extract_regime_codes_is_column_agnostic_for_volatility_vocab():
    """Same function, same logic, applied to regime_volatility's calm/elevated/
    turbulent vocabulary -- confirms it is not implicitly regime_hmm-specific."""
    raw = ["calm", "", "turbulent"]

    result = extract_regime_codes(raw)

    assert result == ["calm", "turbulent"]
    assert "" not in result


# ---------------------------------------------------------------------------
# Behavior 3: regime_group guard (V2) -- unregistered qualifiers.
# ---------------------------------------------------------------------------


def test_unregistered_groups_flags_unknown_qualifier():
    observed_groups = ["equity", "rates", "commodity"]
    registered_groups = {"equity", "rates"}

    result = unregistered_groups(observed_groups, registered_groups)

    assert result == {"commodity"}


def test_unregistered_groups_empty_when_all_known():
    observed_groups = ["equity", "rates"]
    registered_groups = {"equity", "rates"}

    assert unregistered_groups(observed_groups, registered_groups) == set()


# ---------------------------------------------------------------------------
# Behavior 4: empty observed set is source-idle (skip), never mass deprecation (V5).
# ---------------------------------------------------------------------------


def test_classify_namespace_drift_empty_observed_is_idle_not_deprecation():
    result = classify_namespace_drift(observed=[], registered=["1m", "5m", "1h"])

    assert result == NamespaceDriftResult(idle=True, unregistered=frozenset())


def test_classify_namespace_drift_non_idle_flags_unregistered():
    result = classify_namespace_drift(observed=["1m", "unknown_tf"], registered=["1m", "5m", "1h"])

    assert result.idle is False
    assert result.unregistered == frozenset({"unknown_tf"})


def test_classify_namespace_drift_non_idle_clean_when_all_registered():
    result = classify_namespace_drift(observed=["1m", "5m"], registered=["1m", "5m", "1h"])

    assert result.idle is False
    assert result.unregistered == frozenset()


def test_classify_namespace_drift_uses_regime_group_diff_fn():
    result = classify_namespace_drift(
        observed=["equity", "commodity"],
        registered={"equity", "rates"},
        diff_fn=unregistered_groups,
    )

    assert result.idle is False
    assert result.unregistered == frozenset({"commodity"})


# ---------------------------------------------------------------------------
# Behavior 5: assert_namespace_coverage (todo 132) -- this module's hardcoded
# namespace-query dicts must stay a subset of what VocabularyService actually knows.
# ---------------------------------------------------------------------------


def test_assert_namespace_coverage_passes_when_all_queried_namespaces_known():
    assert_namespace_coverage(
        queried_namespaces=["timeframe", "asset_class"],
        known_namespaces={"timeframe", "asset_class", "regime_hmm"},
    )


def test_assert_namespace_coverage_raises_on_unknown_namespace():
    with pytest.raises(RuntimeError, match="stale_namespace"):
        assert_namespace_coverage(
            queried_namespaces=["timeframe", "stale_namespace"],
            known_namespaces={"timeframe"},
        )


# ---------------------------------------------------------------------------
# Behavior 6 (Phase 172 plan 02, Task 3): regime_volatility namespace
# registration in _WINDOWED_NAMESPACE_QUERIES + assert_namespace_coverage.
# ---------------------------------------------------------------------------


def test_windowed_namespace_queries_has_regime_volatility_entry():
    """_WINDOWED_NAMESPACE_QUERIES must carry a regime_volatility key whose SQL
    selects DISTINCT regime_volatility from feature_vectors, bound by the same
    $1-parametrized recent-window predicate and '' placeholder filter as the
    existing regime_hmm entry -- and regime_hmm must still be present, untouched."""
    assert "regime_volatility" in _WINDOWED_NAMESPACE_QUERIES
    sql = _WINDOWED_NAMESPACE_QUERIES["regime_volatility"]
    assert "regime_volatility" in sql
    assert "$1" in sql
    assert "<> ''" in sql
    assert "regime_hmm" in _WINDOWED_NAMESPACE_QUERIES


def test_regime_volatility_query_binds_window_never_a_hardcoded_interval_literal():
    """T-161-02: every windowed query binds the APR-sourced recent-window as $1,
    never a hardcoded interval literal (e.g. '30 days'::interval). A hardcoded
    literal here would silently stop tracking infra.vocabulary_drift.window_days
    changes for this one namespace while every sibling namespace kept respecting
    it."""
    sql = _WINDOWED_NAMESPACE_QUERIES["regime_volatility"]
    assert "($1 || ' days')::interval" in sql
    # No digit immediately precedes "days'::interval" -- catches a hardcoded
    # literal like "30 days'::interval" slipping in instead of the $1 bind.
    assert not re.search(r"\d+\s*days'::interval", sql)


def test_assert_namespace_coverage_passes_when_regime_volatility_known():
    assert_namespace_coverage(
        queried_namespaces=["regime_hmm", "regime_volatility"],
        known_namespaces={"regime_hmm", "regime_volatility", "timeframe"},
    )


def test_assert_namespace_coverage_raises_when_regime_volatility_missing():
    with pytest.raises(RuntimeError, match="regime_volatility"):
        assert_namespace_coverage(
            queried_namespaces=["regime_hmm", "regime_volatility"],
            known_namespaces={"regime_hmm"},
        )
