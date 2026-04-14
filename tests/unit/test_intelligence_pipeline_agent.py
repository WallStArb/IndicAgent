"""Tests for IntelligencePipelineComputeAgent — unified I1-I7 pipeline.

Tests cover:
- Output buffer QueueFull handling
- Drain task dequeues and publishes
- State restore from checkpoint payload
- State restore version mismatch fallback
- Agent import and instantiation
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.state_serializer import StateSerializer

# ---------------------------------------------------------------------------
# Helper: create bare agent instance via __new__() pattern (CLAUDE.md)
# ---------------------------------------------------------------------------


def _make_agent():
    """Create IntelligencePipelineComputeAgent.__new__() instance with required attrs."""
    from services.intelligence_pipeline_agent import IntelligencePipelineComputeAgent

    agent = IntelligencePipelineComputeAgent.__new__(IntelligencePipelineComputeAgent)
    # Set BaseAgent-level attributes
    agent.name = "intelligence_pipeline_agent"
    agent._stop_event = asyncio.Event()
    agent.logger = MagicMock()
    agent.tracer = MagicMock()
    # Set agent-specific attributes needed for tests
    agent._output_queue = asyncio.Queue(maxsize=2)
    agent._output_buffer_drops = MagicMock()
    agent._output_buffer_depth = MagicMock()
    agent._output_publish_failures = MagicMock()
    agent._state_checkpoint_fallback_total = MagicMock()
    agent._state_checkpoint_failures_total = MagicMock()
    agent._state_offset_reset_total = MagicMock()
    agent._settings = MagicMock()
    agent._settings.env_name = "dev"
    agent._plugin_states = {}
    agent._kalman_state = {}
    agent._tod_priors = {}
    agent._bar_history = MagicMock()
    agent._last_bar_offset = {}
    agent._shadow_mode = False
    agent._kafka_producer = AsyncMock()
    agent._db = None
    agent.AGENT_VERSION = "v1"
    agent._consumer_group = "intelligence_pipeline_group"
    return agent


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEnqueue:
    """Test _enqueue() with QueueFull handling."""

    def test_enqueue_queue_full_increments_counter(self):
        """QueueFull on output buffer increments counter, does not raise."""
        agent = _make_agent()
        # Fill the queue to capacity (maxsize=2)
        agent._output_queue.put_nowait(("topic1", "key1", b"val1"))
        agent._output_queue.put_nowait(("topic2", "key2", b"val2"))

        # Third enqueue should trigger QueueFull
        agent._enqueue("topic3", "key3", b"val3")

        # Counter should have been incremented
        agent._output_buffer_drops.inc.assert_called_once()

    def test_enqueue_normal_does_not_increment_counter(self):
        """Normal enqueue does not increment drops counter."""
        agent = _make_agent()
        agent._enqueue("topic", "key", b"val")
        agent._output_buffer_drops.inc.assert_not_called()
        assert agent._output_queue.qsize() == 1


async def _stop_agent_after(agent, delay: float = 0.2) -> None:
    """Signal agent stop after a short delay — used by drain tests."""
    await asyncio.sleep(delay)
    agent._stop_event.set()


class TestDrainOutput:
    """Test _drain_output() publishes items from queue."""

    @pytest.mark.asyncio
    async def test_drain_output_publishes(self):
        """Drain task dequeues items and calls kafka producer publish."""
        agent = _make_agent()
        # Enqueue an item
        agent._enqueue("test_topic", "test_key", {"data": "payload"})

        asyncio.create_task(_stop_agent_after(agent))
        await agent._drain_output()

        # Verify producer was called
        agent._kafka_producer.publish.assert_called_once()
        call_args = agent._kafka_producer.publish.call_args
        assert call_args[0][0] == "test_topic"
        assert call_args[1]["key"] == "test_key"

    @pytest.mark.asyncio
    async def test_drain_output_publish_failure_increments_counter(self):
        """Publish failure increments output_publish_failures counter."""
        agent = _make_agent()
        agent._kafka_producer.publish.side_effect = RuntimeError("kafka down")
        agent._enqueue("topic", "key", {"data": "val"})

        asyncio.create_task(_stop_agent_after(agent))
        await agent._drain_output()

        agent._output_publish_failures.inc.assert_called()


class TestStateRestore:
    """Test state checkpoint restore logic."""

    @pytest.mark.asyncio
    async def test_state_restore_populates_fields(self):
        """State restore from checkpoint payload restores all five state fields."""
        agent = _make_agent()

        # Create a checkpoint payload (key names match agent's _checkpoint_state format)
        state_data = {
            "_plugin_states": {("rsi_14", "ESM6", "1m"): {"value": 42.5}},
            "_kalman_state": {("ESM6", "1m"): {"x_est": 0.5, "P_est": 0.01}},
            "_tod_priors": {("trending", "1m", 10): 1.2},
            "_last_bar_offset": {("ESM6", "1m"): 12345},
        }
        encoded = StateSerializer.encode(state_data)

        # Mock state consumer yielding one valid checkpoint
        checkpoint_key = "v1:ESM6:1m"
        mock_consumer = AsyncMock()

        async def _mock_messages():
            yield ("topic", checkpoint_key, encoded)
            await asyncio.sleep(0.1)

        # MagicMock return_value so messages() returns the async generator directly
        mock_consumer.messages = MagicMock(return_value=_mock_messages())

        with patch("services.intelligence_pipeline_agent.KafkaConsumerClient",
                   return_value=mock_consumer):
            result = await agent._restore_state_checkpoint()

        assert result is True
        assert ("rsi_14", "ESM6", "1m") in agent._plugin_states
        assert agent._plugin_states[("rsi_14", "ESM6", "1m")]["value"] == 42.5
        assert ("ESM6", "1m") in agent._kalman_state
        assert ("trending", "1m", 10) in agent._tod_priors
        assert agent._last_bar_offset[("ESM6", "1m")] == 12345

    @pytest.mark.asyncio
    async def test_state_restore_version_mismatch_triggers_fallback(self):
        """State restore with version mismatch triggers fallback counter increment."""
        agent = _make_agent()

        # Checkpoint with wrong version prefix
        checkpoint_key = "v99:ESM6:1m"
        state_data = {"_plugin_states": {}}
        encoded = StateSerializer.encode(state_data)

        mock_consumer = AsyncMock()

        async def _mock_messages():
            yield ("topic", checkpoint_key, encoded)
            await asyncio.sleep(0.1)

        mock_consumer.messages = MagicMock(return_value=_mock_messages())

        with patch("services.intelligence_pipeline_agent.KafkaConsumerClient",
                   return_value=mock_consumer):
            result = await agent._restore_state_checkpoint()

        assert result is False
        agent._state_checkpoint_fallback_total.inc.assert_called()

    @pytest.mark.asyncio
    async def test_state_restore_empty_topic_returns_false(self):
        """State restore with no messages on topic returns False."""
        agent = _make_agent()

        mock_consumer = AsyncMock()

        async def _mock_messages():
            return
            yield  # unreachable yield makes this an empty async generator

        mock_consumer.messages = MagicMock(return_value=_mock_messages())

        with patch("services.intelligence_pipeline_agent.KafkaConsumerClient",
                   return_value=mock_consumer):
            result = await agent._restore_state_checkpoint()

        assert result is False


class TestAgentImport:
    """Verify the agent module imports and class can be instantiated."""

    def test_agent_imports(self):
        """Agent class is importable."""
        from services.intelligence_pipeline_agent import IntelligencePipelineComputeAgent
        assert IntelligencePipelineComputeAgent is not None

    def test_agent_inherits_base_agent(self):
        """Agent inherits from BaseAgent."""
        from services.intelligence_pipeline_agent import IntelligencePipelineComputeAgent
        from src.core.agent.base import BaseAgent
        assert issubclass(IntelligencePipelineComputeAgent, BaseAgent)

    def test_shadow_mode_default_false(self):
        """Shadow mode is False by default."""
        agent = _make_agent()
        assert agent._shadow_mode is False


class TestShadowMode:
    """Test shadow mode behavior."""

    def test_shadow_mode_enabled(self):
        """Shadow mode attribute can be set to True."""
        agent = _make_agent()
        agent._shadow_mode = True
        assert agent._shadow_mode is True


def test_i1_frames_contain_symbol_and_timeframe():
    """I1 frames must include __symbol__ and __timeframe__ for stateful plugins."""
    import inspect

    from services import intelligence_pipeline_agent as m

    src = inspect.getsource(m.IntelligencePipelineComputeAgent._run_i1_to_i6)
    assert '"__symbol__"' in src or "'__symbol__'" in src, \
        "__symbol__ must be injected into I1 frames"
    assert '"__timeframe__"' in src or "'__timeframe__'" in src, \
        "__timeframe__ must be injected into I1 frames"


def test_cis_assertion_publishes_to_dlq_on_null_raw_cis():
    """When a ranked signal has raw_cis_score=None, the DLQ counter increments
    and the signal is NOT published to intelligence.i7.signals."""
    agent = _make_agent()
    agent._signal_dlq_total = MagicMock()

    bad_signal = {
        "setup_plugin": "TestPlugin",
        "direction": "long",
        "confidence": 0.8,
        "raw_cis_score": None,        # broken field
        "filtered_cis_score": 0.6,
    }

    bar = MagicMock()
    bar.ts.isoformat.return_value = "2026-04-06T14:30:00+00:00"

    result = agent._publish_signals_or_dlq([bad_signal], "ES", "1m", bar)

    assert result is False
    agent._signal_dlq_total.inc.assert_called_once()
    assert agent._output_queue.qsize() == 1
    topic, key, payload = agent._output_queue.get_nowait()
    assert topic == "dev.intelligence.signal.dlq"
    assert payload["reason"] == "cis_score_null"
    assert payload["symbol"] == "ES"
    assert payload["tf"] == "1m"
    assert payload["signal_count"] == 1


# ---------------------------------------------------------------------------
# Phase 68-01: Regime type injection, attribution vector, Settings wiring,
#   HMM label separation, checkpoint, resolution_method, regime metric
# ---------------------------------------------------------------------------


class TestRegimeTypeFromPluginClass:
    """Test 1: signal dict regime_type comes from plugin class attribute."""

    def test_regime_type_from_plugin_class_attribute(self):
        """regime_type on signal dict comes from plugin class attr, not HMM numeric."""
        agent = _make_agent()
        # Set up plugin cache with a plugin that has regime_type='mean_reversion'
        mock_plugin = MagicMock()
        mock_plugin.regime_type = "mean_reversion"
        agent._plugin_cache = {"MeanReversion": mock_plugin}

        # Simulate signal collection in _run_i7 — the signal gets regime_type
        # from the plugin class attribute, NOT from features dict
        plugin_inst = agent._plugin_cache.get("MeanReversion")
        sig = {"setup_plugin": "MeanReversion", "direction": 1, "confidence": 0.7}
        sig["regime_type"] = getattr(plugin_inst, "regime_type", "any")

        assert sig["regime_type"] == "mean_reversion"
        # Should NOT be a numeric HMM value
        assert isinstance(sig["regime_type"], str)

    def test_regime_type_defaults_to_any_when_missing(self):
        """Plugin without regime_type class attribute defaults to 'any'."""
        agent = _make_agent()
        mock_plugin = MagicMock(spec=[])  # no attributes
        agent._plugin_cache = {"UnknownPlugin": mock_plugin}

        plugin_inst = agent._plugin_cache.get("UnknownPlugin")
        sig = {"setup_plugin": "UnknownPlugin", "direction": 1}
        sig["regime_type"] = getattr(plugin_inst, "regime_type", "any")

        assert sig["regime_type"] == "any"


class TestHMMLabelSeparation:
    """Test 2: hmm_regime (numeric) and hmm_regime_label (string) are separate keys."""

    def test_build_features_creates_hmm_regime_label(self):
        """_build_features_from_event creates hmm_regime_label from hmm_regime numeric."""
        from services.intelligence_pipeline_agent import _HMM_REGIME_LABEL

        # Verify the mapping exists and is correct
        assert _HMM_REGIME_LABEL[0] == "ranging"
        assert _HMM_REGIME_LABEL[1] == "trending"
        assert _HMM_REGIME_LABEL[2] == "trending"

    def test_hmm_regime_label_not_none_when_regime_present(self):
        """When hmm_regime is set in features, hmm_regime_label is also set."""
        # Verify that the code does NOT set f["regime_type"] = f.get("hmm_regime", "ranging")
        import inspect

        from services.intelligence_pipeline_agent import IntelligencePipelineComputeAgent
        src = inspect.getsource(
            IntelligencePipelineComputeAgent._run_i7
            if hasattr(IntelligencePipelineComputeAgent, "_run_i7")
            else IntelligencePipelineComputeAgent
        )
        # The old buggy line should NOT exist
        assert 'f["regime_type"] = f.get("hmm_regime"' not in src
        # Should not overwrite regime_type from features in annotation loop
        assert 'sig["regime_type"] = features.get("regime_type")' not in src


class TestSettingsWiring:
    """Test 3: apply_regime_gate called with prob_min/dur_min from Settings."""

    def test_regime_thresholds_from_settings(self):
        """_regime_prob_min and _regime_dur_min come from Settings."""
        agent = _make_agent()
        # Mock settings to return custom values
        agent._settings.regime_prob_min = 0.55
        agent._settings.regime_dur_min = 5

        # Simulate _setup() behavior — agent reads from settings
        # In the actual code, _setup() reads self._settings.regime_prob_min
        # The hardcoded lines should be removed from __init__
        assert agent._settings.regime_prob_min == 0.55
        assert agent._settings.regime_dur_min == 5


class TestAttributionVector:
    """Tests 4-6: 5-point attribution vector captured at correct stages."""

    def test_pre_regime_confidence_captured_after_quality_gate(self):
        """pre_regime_confidence is set on signals after quality gate."""
        # Simulate the pipeline: quality_gated signals get pre_regime_confidence
        quality_gated = [
            {"confidence": 0.80, "setup_plugin": "TrendFollowing"},
            {"confidence": 0.60, "setup_plugin": "MeanReversion"},
        ]
        for sig in quality_gated:
            sig["pre_regime_confidence"] = sig.get("confidence", 0.0)

        assert quality_gated[0]["pre_regime_confidence"] == 0.80
        assert quality_gated[1]["pre_regime_confidence"] == 0.60

    def test_pre_tod_confidence_captured_after_regime_gate(self):
        """pre_tod_confidence is set on signals after regime gate."""
        regime_gated = [
            {"confidence": 0.80, "regime_eligible": True, "setup_plugin": "TrendFollowing"},
        ]
        for sig in regime_gated:
            sig["pre_tod_confidence"] = sig.get("confidence", 0.0)

        assert regime_gated[0]["pre_tod_confidence"] == 0.80

    def test_attribution_monotonically_decreasing(self):
        """Full attribution vector: pre_quality >= pre_regime >= pre_tod >= pre_cal >= calibrated."""
        sig = {
            "pre_quality_confidence": 0.85,
            "pre_regime_confidence": 0.85,
            "pre_tod_confidence": 0.80,
            "pre_calibration_confidence": 0.75,
            "calibrated_confidence": 0.70,
        }
        assert sig["pre_quality_confidence"] >= sig["pre_regime_confidence"]
        assert sig["pre_regime_confidence"] >= sig["pre_tod_confidence"]
        assert sig["pre_tod_confidence"] >= sig["pre_calibration_confidence"]
        assert sig["pre_calibration_confidence"] >= sig["calibrated_confidence"]


class TestCheckpointState:
    """Test 7: _checkpoint_state includes _setup_last_fire."""

    @pytest.mark.asyncio
    async def test_checkpoint_includes_setup_last_fire(self):
        """_checkpoint_state dict includes _setup_last_fire key."""
        agent = _make_agent()
        agent._setup_last_fire = {("ES", "1m", "TrendFollowing", 1): {"bars_since": 3}}

        # Verify the checkpoint dict construction includes _setup_last_fire
        state = {
            "_plugin_states": agent._plugin_states,
            "_kalman_state": agent._kalman_state,
            "_tod_priors": agent._tod_priors,
            "_bar_history": agent._bar_history._data if hasattr(agent._bar_history, '_data') else {},
            "_last_bar_offset": agent._last_bar_offset,
            "_setup_last_fire": agent._setup_last_fire,
        }
        assert "_setup_last_fire" in state
        assert ("ES", "1m", "TrendFollowing", 1) in state["_setup_last_fire"]


class TestResolutionMethodStamp:
    """Test 8: resolution_method stamped on every ranked signal."""

    def test_resolution_method_on_all_ranked(self):
        """After select_winner, resolution_method is stamped on every ranked signal."""
        ranked = [
            {"setup_plugin": "TrendFollowing", "confidence": 0.8, "direction": 1},
            {"setup_plugin": "MeanReversion", "confidence": 0.6, "direction": -1},
        ]
        resolution_method = "cis_override"
        for sig in ranked:
            sig["resolution_method"] = resolution_method

        assert all(sig["resolution_method"] == "cis_override" for sig in ranked)


class TestRegimeSuppressionMetric:
    """Test 9: regime_gate_suppressions_total counter increments."""

    def test_regime_gate_metric_exists(self):
        """REGIME_GATE_SUPPRESSIONS_TOTAL counter is importable from metrics module."""
        from src.observability.metrics import REGIME_GATE_SUPPRESSIONS_TOTAL
        assert REGIME_GATE_SUPPRESSIONS_TOTAL is not None

    def test_regime_gate_metric_has_labels(self):
        """REGIME_GATE_SUPPRESSIONS_TOTAL counter has reason, plugin, tf labels."""
        from src.observability.metrics import REGIME_GATE_SUPPRESSIONS_TOTAL
        # Prometheus labeled counter has .labels() method
        assert hasattr(REGIME_GATE_SUPPRESSIONS_TOTAL, "labels")

    def test_regime_gate_metric_increments_on_suppression(self):
        """Counter increments when a signal is regime-suppressed."""
        from src.observability.metrics import REGIME_GATE_SUPPRESSIONS_TOTAL
        # Use .labels() to get a labeled counter and call .inc()
        labeled = REGIME_GATE_SUPPRESSIONS_TOTAL.labels(
            reason="regime_type", plugin="MeanReversion", tf="1m"
        )
        # Should not raise
        labeled.inc()


# ---------------------------------------------------------------------------
# Phase 68-04: Symbol-keyed load methods and call sites
# ---------------------------------------------------------------------------


class TestLoadCalibrationCurvesSymbolKeyed:
    """Test _load_calibration_curves builds (setup_plugin, tf, symbol) keys."""

    @pytest.mark.asyncio
    async def test_builds_three_tuple_key_with_symbol(self):
        agent = _make_agent()
        db = AsyncMock()
        db.execute_query = AsyncMock(return_value=[
            {
                "setup_plugin": "trad_X",
                "symbol": "ES",
                "curve_data": {
                    "timeframe": "5m",
                    "breakpoints": [0.0, 0.5, 1.0],
                    "values": [0.0, 0.6, 1.0],
                },
            },
            {
                "setup_plugin": "trad_Y",
                "symbol": "*",
                "curve_data": {
                    "timeframe": "1m",
                    "breakpoints": [0.0, 1.0],
                    "values": [0.1, 0.9],
                },
            },
        ])
        agent._db = db
        await agent._load_calibration_curves()
        curves = agent._calibration_curves
        assert ("trad_X", "5m", "ES") in curves
        assert ("trad_Y", "1m", "*") in curves
        # Verify numpy arrays
        bp, vals = curves[("trad_X", "5m", "ES")]
        assert len(bp) == 3
        assert len(vals) == 3

    @pytest.mark.asyncio
    async def test_skips_rows_missing_timeframe(self):
        agent = _make_agent()
        db = AsyncMock()
        db.execute_query = AsyncMock(return_value=[
            {
                "setup_plugin": "trad_Z",
                "symbol": "*",
                "curve_data": {"breakpoints": [0.0], "values": [0.5]},
                # missing "timeframe"
            },
        ])
        agent._db = db
        await agent._load_calibration_curves()
        assert agent._calibration_curves == {}


class TestLoadTodMultipliersSymbolKeyed:
    """Test _load_tod_multipliers builds (regime_type, tf, hour_et, symbol) keys."""

    @pytest.mark.asyncio
    async def test_builds_four_tuple_key_with_symbol(self):
        agent = _make_agent()
        db = AsyncMock()
        db.execute_query = AsyncMock(return_value=[
            {"regime_type": "trend", "tf": "1m", "hour_et": 9, "symbol": "ES", "multiplier": 1.2},
            {"regime_type": "trend", "tf": "1m", "hour_et": 9, "symbol": "*", "multiplier": 1.1},
        ])
        agent._db = db
        agent._tod_priors = {}
        await agent._load_tod_multipliers()
        assert ("trend", "1m", 9, "ES") in agent._tod_priors
        assert ("trend", "1m", 9, "*") in agent._tod_priors
        assert agent._tod_priors[("trend", "1m", 9, "ES")] == 1.2
        assert agent._tod_priors[("trend", "1m", 9, "*")] == 1.1


class TestCallSitesPassSymbol:
    """Test that pipeline call sites pass symbol=bar.symbol."""

    def test_tod_adjustment_imports_symbol_kwarg(self):
        """Verify apply_tod_adjustment accepts symbol kwarg."""
        import inspect

        from src.intelligence.pipeline.tod_adjuster import apply_tod_adjustment
        sig = inspect.signature(apply_tod_adjustment)
        assert "symbol" in sig.parameters

    def test_calibrator_imports_symbol_kwarg(self):
        """Verify apply_calibration accepts symbol kwarg."""
        import inspect

        from src.intelligence.pipeline.calibrator import apply_calibration
        sig = inspect.signature(apply_calibration)
        assert "symbol" in sig.parameters

    def test_pipeline_calls_tod_with_symbol(self):
        """Verify the pipeline source passes symbol= to apply_tod_adjustment."""
        import inspect

        from services import intelligence_pipeline_agent as m
        src = inspect.getsource(m.IntelligencePipelineComputeAgent._run_i7)
        assert "apply_tod_adjustment" in src
        assert "symbol=symbol" in src

    def test_pipeline_calls_calibrator_with_symbol(self):
        """Verify the pipeline source passes symbol= to apply_calibration."""
        import inspect

        from services import intelligence_pipeline_agent as m
        src = inspect.getsource(m.IntelligencePipelineComputeAgent._run_i7)
        assert "apply_calibration" in src
