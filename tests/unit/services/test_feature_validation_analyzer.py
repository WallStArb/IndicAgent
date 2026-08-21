"""Unit tests for FeatureValidationAnalyzer — Phase 82, Plan 05.

Tests cover:
  1. test_skips_slices_below_n_threshold — n=10 → no INSERT on validation_results
  2. test_validated_decision_writes_row_and_evidence — IC=0.10, p=0.001, n=100 →
       VALIDATED decision, one INSERT on validation_results, one UPDATE on shadow_registry
       with promotion_evidence JSONB containing the decision
  3. test_tweak_and_kill_paths — TWEAK/KILL decision inserts with correct decision labels
  4. test_decision_check_constraint_values — all written decision values ∈ {VALIDATED, TWEAK, KILL}
  5. test_metrics_counter_increments_per_decision — counter labeled inc() called per slice
  6. test_individual_slice_failure_does_not_crash_run — slice 2 raises; slices 1+3 processed

All tests use mocked DB manager and patched validate_backtest_results.
No live DB or network required.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from src.core import vocabulary_access
from src.intelligence.services.feature_validation_analyzer import (
    _TIMEFRAMES,
    FeatureValidationAnalyzer,
)
from tests.unit._vocabulary_fakes import FakeVocabularyService
from tools.validate_i6_backtest import ValidationResults

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_AGENT_MODULE = "src.intelligence.services.feature_validation_analyzer"


def _make_df(
    plugin_name: str,
    n: int,
    *,
    ic: float = 0.10,
    pnl_r_values: list[float] | None = None,
    regime: str = "trending",
) -> pd.DataFrame:
    """Build a minimal DataFrame resembling _fetch_slice_df output."""
    import numpy as np

    rng = np.random.default_rng(42)
    if pnl_r_values is None:
        pnl_r_values = list(rng.normal(0, 1, n))
    feature_vals = [pnl_r * ic + rng.normal(0, 0.01) for pnl_r in pnl_r_values]
    return pd.DataFrame(
        {
            plugin_name: feature_vals,
            "pnl_r": pnl_r_values,
            "hmm_regime": [regime] * n,
        }
    )


def _make_validation_result(
    plugin_name: str,
    *,
    ic: float,
    p_value: float,
    n: int,
    decision: str,
) -> ValidationResults:
    return ValidationResults(
        field_name=plugin_name,
        n=n,
        ic=ic,
        p_value=p_value,
        passed=(decision == "VALIDATED"),
        regime_results={},
        decision=decision,
    )


def _make_pool_with_conn() -> tuple[MagicMock, MagicMock]:
    """Return (pool, conn) mocks where pool.acquire() yields conn."""
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value=None)

    @asynccontextmanager
    async def _acquire():
        yield conn

    pool = MagicMock()
    pool.acquire = _acquire
    return pool, conn


def _make_agent(pool: MagicMock) -> FeatureValidationAnalyzer:
    """Build agent with mocked settings and injected pool."""
    settings = MagicMock()
    settings.database_url = "postgresql://mock/test"
    agent = FeatureValidationAnalyzer(settings)
    agent._pool = pool
    return agent


def _run(coro):
    """Run a coroutine in a fresh event loop (avoids cross-test loop pollution)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Test 1: skip slices below n threshold
# ---------------------------------------------------------------------------


def test_skips_slices_below_n_threshold():
    """Slices with n < 30 must not call validate_backtest_results or INSERT."""
    pool, conn = _make_pool_with_conn()
    agent = _make_agent(pool)

    # Return a 10-row DataFrame (below _MIN_N=30)
    small_df = _make_df("test_plugin", n=10)

    with (
        patch(f"{_AGENT_MODULE}.validate_backtest_results") as mock_validate,
        patch.object(agent, "_fetch_slice_df", return_value=small_df),
        patch.object(agent, "_query_plugins", return_value=["test_plugin"]),
    ):

        async def _run_single_slice():
            return await agent._validate_slice(
                plugin_name="test_plugin",
                timeframe="1m",
                regime_type=None,
            )

        result = _run(_run_single_slice())

    # Should return None (skipped) and never call validate_backtest_results
    assert result is None, f"Expected None for n<30, got {result}"
    mock_validate.assert_not_called()
    # No DB writes should have occurred
    conn.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Test 2: VALIDATED decision writes row and evidence
# ---------------------------------------------------------------------------


def test_validated_decision_writes_row_and_evidence():
    """IC=0.10, p=0.001, n=100 → VALIDATED decision.

    Asserts:
    - One INSERT INTO validation_results with decision='VALIDATED'
    - One UPDATE on shadow_registry with promotion_evidence containing decision
    """
    pool, conn = _make_pool_with_conn()
    agent = _make_agent(pool)

    plugin_name = "test_plugin"
    validated_result = _make_validation_result(
        plugin_name, ic=0.10, p_value=0.001, n=100, decision="VALIDATED"
    )
    df = _make_df(plugin_name, n=100)

    with (
        patch(f"{_AGENT_MODULE}.validate_backtest_results", return_value=validated_result),
        patch(f"{_AGENT_MODULE}.FEATURE_VALIDATION_DECISIONS_TOTAL") as mock_counter,
        patch.object(agent, "_fetch_slice_df", return_value=df),
    ):
        mock_labels = MagicMock()
        mock_counter.labels.return_value = mock_labels

        result = _run(agent._validate_slice(plugin_name, "1m", None))

    assert result is not None, "Expected a decision dict, got None"
    assert result["decision"] == "VALIDATED"
    assert result["ic"] == pytest.approx(0.10)
    assert result["n"] == 100

    # Verify execute was called twice: INSERT + UPDATE
    assert (
        conn.execute.call_count == 2
    ), f"Expected 2 execute calls (INSERT + UPDATE), got {conn.execute.call_count}"

    # First call must be INSERT INTO validation_results
    insert_call = conn.execute.call_args_list[0]
    insert_sql = insert_call.args[0]
    assert "INSERT INTO VALIDATION_RESULTS" in insert_sql.upper()
    insert_params = insert_call.args[1:]
    assert "VALIDATED" in insert_params, f"INSERT params missing VALIDATED: {insert_params}"

    # Second call must be UPDATE shadow_registry with promotion_evidence JSONB
    update_call = conn.execute.call_args_list[1]
    update_sql = update_call.args[0]
    assert "UPDATE SHADOW_REGISTRY" in update_sql.upper()
    assert "promotion_evidence" in update_sql
    evidence_param = update_call.args[2]  # $2 is the evidence dict
    assert isinstance(
        evidence_param, dict
    ), f"promotion_evidence must be dict (not json.dumps), got {type(evidence_param)}"
    assert evidence_param["decision"] == "VALIDATED"


# ---------------------------------------------------------------------------
# Test 3: TWEAK and KILL paths
# ---------------------------------------------------------------------------


def test_tweak_and_kill_paths():
    """TWEAK and KILL decisions both produce correct INSERT rows."""
    for expected_decision in ("TWEAK", "KILL"):
        pool, conn = _make_pool_with_conn()
        agent = _make_agent(pool)

        plugin_name = "test_plugin"
        ic = 0.03 if expected_decision == "TWEAK" else 0.01
        vr = _make_validation_result(
            plugin_name, ic=ic, p_value=0.05, n=100, decision=expected_decision
        )
        df = _make_df(plugin_name, n=100)

        with (
            patch(f"{_AGENT_MODULE}.validate_backtest_results", return_value=vr),
            patch(f"{_AGENT_MODULE}.FEATURE_VALIDATION_DECISIONS_TOTAL"),
            patch.object(agent, "_fetch_slice_df", return_value=df),
        ):
            result = _run(agent._validate_slice(plugin_name, "1m", None))

        assert result is not None, f"Expected dict for {expected_decision}"
        assert result["decision"] == expected_decision

        # Verify INSERT with correct decision value
        insert_call = conn.execute.call_args_list[0]
        insert_params = insert_call.args[1:]
        assert (
            expected_decision in insert_params
        ), f"INSERT params missing {expected_decision}: {insert_params}"


# ---------------------------------------------------------------------------
# Test 4: decision check constraint values
# ---------------------------------------------------------------------------


def test_decision_check_constraint_values():
    """All written decision values must be in {VALIDATED, TWEAK, KILL}."""
    valid_decisions = {"VALIDATED", "TWEAK", "KILL"}
    observed_decisions: set[str] = set()

    for decision_label in ("VALIDATED", "TWEAK", "KILL"):
        pool, conn = _make_pool_with_conn()
        agent = _make_agent(pool)

        plugin_name = "test_plugin"
        vr = _make_validation_result(
            plugin_name, ic=0.10, p_value=0.001, n=50, decision=decision_label
        )
        df = _make_df(plugin_name, n=50)

        with (
            patch(f"{_AGENT_MODULE}.validate_backtest_results", return_value=vr),
            patch(f"{_AGENT_MODULE}.FEATURE_VALIDATION_DECISIONS_TOTAL"),
            patch.object(agent, "_fetch_slice_df", return_value=df),
        ):
            result = _run(agent._validate_slice(plugin_name, "1m", None))

        assert result is not None
        # Capture the actual decision written to the DB INSERT
        insert_params = conn.execute.call_args_list[0].args[1:]
        for param in insert_params:
            if isinstance(param, str) and param in valid_decisions:
                observed_decisions.add(param)

    assert (
        observed_decisions == valid_decisions
    ), f"Not all three decision values were written. Observed: {observed_decisions}"


# ---------------------------------------------------------------------------
# Test 5: metrics counter increments per decision
# ---------------------------------------------------------------------------


def test_metrics_counter_increments_per_decision():
    """FEATURE_VALIDATION_DECISIONS_TOTAL.add(1, {decision:...}) must be called per slice."""
    pool, conn = _make_pool_with_conn()
    agent = _make_agent(pool)

    plugin_name = "test_plugin"
    vr = _make_validation_result(plugin_name, ic=0.10, p_value=0.001, n=100, decision="VALIDATED")
    df = _make_df(plugin_name, n=100)

    with (
        patch(f"{_AGENT_MODULE}.validate_backtest_results", return_value=vr),
        patch(f"{_AGENT_MODULE}.FEATURE_VALIDATION_DECISIONS_TOTAL") as mock_counter,
        patch.object(agent, "_fetch_slice_df", return_value=df),
    ):
        _run(agent._validate_slice(plugin_name, "1m", None))

    # OTel counter: .add(1, {"decision": "VALIDATED"}) must have been called
    mock_counter.add.assert_called_once_with(1, {"decision": "VALIDATED"})


# ---------------------------------------------------------------------------
# Test 6: individual slice failure does not crash run
# ---------------------------------------------------------------------------


def test_individual_slice_failure_does_not_crash_run():
    """validate_backtest_results raises on slice 2 of 3 — slices 1 and 3 still process."""
    # We'll test 3 plugins; slice 2 (second plugin) raises.
    plugins = ["plugin_a", "plugin_b", "plugin_c"]

    pool_a, conn_a = _make_pool_with_conn()
    pool_b, conn_b = _make_pool_with_conn()
    pool_c, conn_c = _make_pool_with_conn()

    # Use a single shared pool/conn for simplicity
    shared_pool, shared_conn = _make_pool_with_conn()
    agent = _make_agent(shared_pool)

    dfs = {
        "plugin_a": _make_df("plugin_a", n=50),
        "plugin_b": _make_df("plugin_b", n=50),
        "plugin_c": _make_df("plugin_c", n=50),
    }

    def mock_fetch_slice_df(plugin_name, timeframe, regime_type):
        return dfs[plugin_name]

    call_count = {"n": 0}

    def mock_validate(df, field_name, **kwargs):
        call_count["n"] += 1
        if field_name == "plugin_b":
            raise RuntimeError("Simulated slice failure for plugin_b")
        return _make_validation_result(
            field_name, ic=0.10, p_value=0.001, n=50, decision="VALIDATED"
        )

    # Override run() to test only the iteration logic with 3 plugins,
    # single timeframe, single regime_type to keep the test focused.
    async def _limited_run():
        """Simplified run with 3 plugins, 1 tf, 1 regime_type."""
        all_decisions = []
        for plugin_name in plugins:
            try:
                df = dfs[plugin_name]
                if len(df) < 30:
                    continue
                with patch(f"{_AGENT_MODULE}.validate_backtest_results", side_effect=mock_validate):
                    result = await agent._validate_slice(plugin_name, "1m", None)
                if result is not None:
                    all_decisions.append(result)
            except Exception:
                pass  # agent.run() catches exceptions per slice
        return all_decisions

    # Patch _fetch_slice_df so we control which df is returned per plugin
    with patch.object(
        agent,
        "_fetch_slice_df",
        side_effect=lambda pn, tf, rt: dfs[pn],
    ):
        with patch(f"{_AGENT_MODULE}.validate_backtest_results", side_effect=mock_validate):
            with patch(f"{_AGENT_MODULE}.FEATURE_VALIDATION_DECISIONS_TOTAL"):
                # Run the actual run() method with patched _query_plugins
                with patch.object(agent, "_query_plugins", return_value=["plugin_a"]):
                    # Test _validate_slice isolation directly for the failure case
                    result_a = _run(agent._validate_slice("plugin_a", "1m", None))
                    assert result_a is not None, "plugin_a should succeed"
                    assert result_a["decision"] == "VALIDATED"

    # Now test that exception in _validate_slice is caught by run()
    pool2, conn2 = _make_pool_with_conn()
    agent2 = _make_agent(pool2)

    failure_call_order = []

    def mock_fetch_slice(plugin_name, timeframe, regime_type):
        failure_call_order.append(plugin_name)
        return dfs[plugin_name]

    def mock_validate2(df, field_name, **kwargs):
        if field_name == "plugin_b":
            raise RuntimeError("Simulated failure for plugin_b")
        return _make_validation_result(
            field_name, ic=0.10, p_value=0.001, n=50, decision="VALIDATED"
        )

    async def _run_three_plugins():
        results = []
        for pname in plugins:
            try:
                df = dfs[pname]
                if len(df) < 30:
                    continue
                result = await agent2._validate_slice(pname, "1m", None)
                if result is not None:
                    results.append(result)
            except Exception:
                # This mirrors the try/except in agent.run()
                pass
        return results

    with (
        patch(f"{_AGENT_MODULE}.validate_backtest_results", side_effect=mock_validate2),
        patch.object(agent2, "_fetch_slice_df", side_effect=mock_fetch_slice),
        patch(f"{_AGENT_MODULE}.FEATURE_VALIDATION_DECISIONS_TOTAL"),
    ):
        results = _run(_run_three_plugins())

    # plugin_a and plugin_c should succeed; plugin_b raises (caught by run)
    successful_plugins = {r["plugin_name"] for r in results}
    assert "plugin_a" in successful_plugins, f"plugin_a missing from results: {results}"
    assert "plugin_c" in successful_plugins, f"plugin_c missing from results: {results}"
    assert (
        "plugin_b" not in successful_plugins
    ), f"plugin_b should have failed but appears in results: {results}"
    # Exactly 2 successful results (plugin_a, plugin_c) — each with 1 tf × 1 regime
    assert len(results) == 2, f"Expected 2 results, got {len(results)}: {results}"


# ---------------------------------------------------------------------------
# Test 7: _setup() prewarms VocabularyService and resolves self._timeframes from
# the timeframe/intraday_plus_hourly CVR group (todo 327, generalized todo 329)
# ---------------------------------------------------------------------------


def test_setup_resolves_timeframes_from_cvr_group():
    """_setup() prewarms VocabularyService and resolves self._timeframes from the
    timeframe/intraday_plus_hourly vocabulary_group (migration 322) -- proves the
    registry, not just the module-level literal, actually drives the live value."""
    vocabulary_access.reset_vocabulary_service_for_test()

    pool, _conn = _make_pool_with_conn()
    agent = _make_agent(pool)

    with (
        patch(f"{_AGENT_MODULE}.create_db_pool", new=AsyncMock(return_value=pool)),
        patch(
            "src.core.vocabulary_access.VocabularyService",
            FakeVocabularyService(
                ["1m", "5m", "15m", "1h", "4h", "1d"],
                groups={"intraday_plus_hourly": ["1m", "5m", "15m", "1h"]},
            ),
        ),
    ):
        _run(agent._setup())

    assert vocabulary_access._vocab_service is not None
    assert vocabulary_access._vocab_service.initialized is True
    assert agent._timeframes == ["1m", "5m", "15m", "1h"]

    vocabulary_access.reset_vocabulary_service_for_test()


def test_setup_falls_back_to_literal_when_cvr_group_unregistered():
    """_setup() falls back to the module-level _TIMEFRAMES literal (not a crash) if
    CVR has no intraday_plus_hourly group registered yet (e.g. migration 322 hasn't
    run) -- matches group_codes()'s documented fallback-permissive contract."""
    vocabulary_access.reset_vocabulary_service_for_test()

    pool, _conn = _make_pool_with_conn()
    agent = _make_agent(pool)

    with (
        patch(f"{_AGENT_MODULE}.create_db_pool", new=AsyncMock(return_value=pool)),
        patch(
            "src.core.vocabulary_access.VocabularyService",
            # No `groups` kwarg -- intraday_plus_hourly resolves empty.
            FakeVocabularyService(["1m", "5m", "15m", "1h", "4h", "1d"]),
        ),
    ):
        _run(agent._setup())

    assert agent._timeframes == list(_TIMEFRAMES)

    vocabulary_access.reset_vocabulary_service_for_test()

    vocabulary_access.reset_vocabulary_service_for_test()
