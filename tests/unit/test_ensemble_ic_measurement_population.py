"""Unit test: EIC-01 measures IC against the full scored population, not the
emission-gated subset.

Renaissance-rigor finding (2026-07-08): EnsembleICEngine's own docstring states its
purpose is to "prove the ensemble OUTPUT has IC before any execution rules are
tested" -- i.e. no frame assumptions. But the original implementation read from
alpha_events, which is ensemble_alpha AFTER a threshold + directional-CI + cost-hurdle
filter -- an execution-policy gate, not a signal-validation population. That is a
textbook post-selection-bias error: conditioning a correlation measurement on the
very confidence threshold you're trying to validate destroys statistical power (the
observed real-world effect: alpha_events was 0.17% of ensemble_alpha's row count,
collapsing per-cell N to 100-150 against a 3000-observation floor) and can bias the
measured IC in either direction. Standard factor-IC methodology measures the
continuous score against forward returns across the FULL population.

Empirically confirmed switching populations resolves the sample-size crisis: 96% of
5m cells and 90% of 15m cells clear N>=3000 when measured against ensemble_alpha,
vs 0% against alpha_events (query run 2026-07-08 against the live corpus).

alpha_events / the emission threshold remains the correct population for Phase 142B
(frame simulation -- testing whether an execution rule is profitable, a genuinely
different question), just not for EIC-01/EIC-04 signal validation.

No DB, no Kafka. Pure string assertions against the source file (mirrors
test_ensemble_ic_executable_returns.py's grep-as-test pattern).
"""

from __future__ import annotations

from tests.unit._source_grep_helpers import read_source


def _read_source() -> str:
    return read_source("services", "ensemble_ic_engine.py")


def test_worker_fetch_sources_from_ensemble_alpha():
    source = _read_source()
    assert "FROM ensemble_alpha" in source, (
        "_WORKER_FETCH_SQL must read from ensemble_alpha (the full scored population), "
        "not alpha_events (the emission-gated execution subset)"
    )


def test_pooled_worker_fetch_sources_from_ensemble_alpha():
    source = _read_source()
    # Both the per-symbol and pooled fetch SQL must source from ensemble_alpha.
    assert source.count("FROM ensemble_alpha") >= 2, (
        "Both _WORKER_FETCH_SQL and _POOLED_WORKER_FETCH_SQL must read from " "ensemble_alpha"
    )


def test_no_alpha_events_sql_usage_remains():
    """No SQL statement may read FROM/JOIN alpha_events -- this engine has zero data
    dependency on the emission-gated table after the fix (it never wrote to
    alpha_events either). Explanatory prose naming alpha_events by name (to document
    WHY it's deliberately not used) is fine and expected; only SQL usage patterns are
    checked here, mirroring how test_ensemble_weight_epoch.py's RETURNING check avoids
    false-positiving on its own docstring."""
    source = _read_source()
    for forbidden in ("FROM alpha_events", "JOIN alpha_events", "UPDATE alpha_events"):
        assert forbidden not in source, (
            f"Found {forbidden!r} in services/ensemble_ic_engine.py -- EIC-01 must "
            "measure signal IC against the full ensemble_alpha population, never "
            "the emission-gated alpha_events subset. See module docstring for the "
            "post-selection-bias rationale."
        )


def test_startup_gate_counts_ensemble_alpha():
    source = _read_source()
    assert "SELECT count(*) FROM ensemble_alpha WHERE weight_version" in source


def test_tf_enumeration_sources_from_ensemble_alpha():
    source = _read_source()
    assert "SELECT DISTINCT tf FROM ensemble_alpha WHERE weight_version" in source


def test_symbol_tf_enumeration_sources_from_ensemble_alpha():
    source = _read_source()
    assert "SELECT DISTINCT symbol, tf FROM ensemble_alpha" in source
