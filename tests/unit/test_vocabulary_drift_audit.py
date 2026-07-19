"""Unit tests: vocabulary drift audit pure comparison logic (Phase 161 Plan 03).

Pure-Python, no-DB style (mirrors tests/unit/test_concept_registry_service.py /
test_vocabulary_service.py): exercises the observed-vs-registered comparison core,
the regime_hmm '' extractor, the regime_group guard, and the idle/deprecation
classification -- all against literal fixtures, no DB connection or pool required.
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import pytest

from src.config.vocabulary_drift import (
    NamespaceDriftResult,
    assert_namespace_coverage,
    classify_namespace_drift,
    extract_regime_hmm_codes,
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


def test_extract_regime_hmm_codes_drops_empty_string():
    raw = ["trending_up", "", "ranging", "transition_down"]

    result = extract_regime_hmm_codes(raw)

    assert result == ["trending_up", "ranging", "transition_down"]
    assert "" not in result


def test_extract_regime_hmm_codes_no_empty_string_is_noop():
    raw = ["trending_up", "ranging"]

    assert extract_regime_hmm_codes(raw) == raw


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
