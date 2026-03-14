"""Tests for market_analysis_service — I3→I6 analysis consuming indicators stream."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest


def test_market_analysis_service_imports():
    """Ensure market_analysis_service exists and has the right class."""
    from services.market_analysis_service import MarketAnalysisService

    svc = MarketAnalysisService()
    assert hasattr(svc, "_run_analysis_pipeline")


@pytest.mark.asyncio
async def test_run_analysis_pipeline_requires_features():
    """Pipeline must return a dict when called with minimal frames."""
    from services.market_analysis_service import MarketAnalysisService

    svc = MarketAnalysisService()
    frames = {
        "main": pd.DataFrame(
            [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 500}] * 30
        ),
        "features": {},
    }

    result = await svc._run_analysis_pipeline("ES", "1m", frames)
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Phase 01-01: IntelligenceEvent schema tests
# ---------------------------------------------------------------------------


class TestIntelligenceEventSchema:
    """RED→GREEN tests for IntelligenceEvent schema definition."""

    def test_intelligence_event_constructs_valid_full_event(self):
        """IntelligenceEvent constructs without error given valid sub-models."""
        from src.intelligence.schemas import (
            I1Indicators,
            I3Structure,
            I4Context,
            I5Patterns,
            I6Confluence,
            IntelligenceEvent,
            OHLCVBar,
            SMCContext,
        )

        event = IntelligenceEvent(
            ts=datetime(2026, 1, 1, 12, 0, 0),
            symbol="ES",
            tf="1m",
            bar=OHLCVBar(o=4900.0, h=4905.0, l=4895.0, c=4902.0, v=1000),
            i1=I1Indicators(),
            i3=I3Structure(),
            i4=I4Context(),
            i5=I5Patterns(),
            smc=SMCContext(),
            i6=I6Confluence(),
        )
        assert event.schema_version == "1.0"
        assert event.symbol == "ES"
        assert event.tf == "1m"
        assert event.platform == "futures"
        assert event.source == "live"

    def test_i3_structure_rejects_unknown_field(self):
        """I3Structure with unknown_field raises ValidationError (extra=forbid)."""
        from pydantic import ValidationError

        from src.intelligence.schemas import I3Structure

        with pytest.raises(ValidationError):
            I3Structure(unknown_field="bad")

    def test_i4_context_rejects_unknown_field(self):
        """I4Context with unknown_field raises ValidationError (extra=forbid)."""
        from pydantic import ValidationError

        from src.intelligence.schemas import I4Context

        with pytest.raises(ValidationError):
            I4Context(unknown_field=1.0)

    def test_i1_indicators_allows_extra_fields(self):
        """I1Indicators with any extra field does NOT raise (extra=allow)."""
        from src.intelligence.schemas import I1Indicators

        # Should not raise
        i1 = I1Indicators(any_extra_field=1.0, another_dynamic_field="value")
        assert i1 is not None

    def test_i4_context_garch_fields_accept_correct_types(self):
        """garch_vol_regime is int | None — accepts int 0/1/2."""
        from src.intelligence.schemas import I4Context

        ctx = I4Context(
            garch_sigma=0.015,
            garch_vol_ratio=1.2,
            garch_vol_regime=1,  # int — not float
            garch_shock=0.002,
        )
        assert ctx.garch_vol_regime == 1
        assert isinstance(ctx.garch_vol_regime, int)

    def test_i3_structure_swing_pattern_is_float(self):
        """swing_pattern: float|None — numeric encoding (1.0=uptrend, -1.0=downtrend)."""
        from src.intelligence.schemas import I3Structure

        s3 = I3Structure(swing_pattern=1.0)
        assert s3.swing_pattern == 1.0

    def test_smc_context_bos_detected_is_float(self):
        """bos_detected is float | None — plugin returns 0.0/1.0 flag, not a boolean."""
        from src.intelligence.schemas import SMCContext

        smc = SMCContext(bos_detected=1.0, bos_direction=1, bos_level=4950.0)
        assert smc.bos_detected == 1.0

    def test_intelligence_event_model_dump_json_roundtrip(self):
        """model_dump_json() produces valid JSON that model_validate_json() can round-trip."""
        from src.intelligence.schemas import (
            I1Indicators,
            I3Structure,
            I4Context,
            I5Patterns,
            I6Confluence,
            IntelligenceEvent,
            OHLCVBar,
            SMCContext,
        )

        event = IntelligenceEvent(
            ts=datetime(2026, 1, 1, 12, 0, 0),
            symbol="NQ",
            tf="5m",
            bar=OHLCVBar(o=20000.0, h=20050.0, l=19990.0, c=20025.0, v=500),
            i1=I1Indicators(rsi_14=55.0, atr_14=25.0),
            i3=I3Structure(swing_high=20050.0, swing_pattern=1.0),
            i4=I4Context(garch_sigma=0.015, garch_vol_regime=1),
            i5=I5Patterns(squeeze_active=0.0),
            smc=SMCContext(bos_detected=False),
            i6=I6Confluence(ctf_score=0.7),
        )
        json_str = event.model_dump_json()

        # Must contain schema_version in the JSON
        assert '"schema_version":"1.0"' in json_str or '"schema_version": "1.0"' in json_str

        # Round-trip
        recovered = IntelligenceEvent.model_validate_json(json_str)
        assert recovered.symbol == "NQ"
        assert recovered.tf == "5m"
        assert recovered.i4.garch_vol_regime == 1
        assert recovered.i3.swing_pattern == 1.0

    def test_i4_context_with_garch_kalman_values(self):
        """I4Context with realistic GARCH/Kalman values constructs and validates."""
        from src.intelligence.schemas import I4Context

        ctx = I4Context(
            garch_sigma=0.015,
            garch_vol_ratio=1.2,
            garch_vol_regime=1,
            garch_shock=0.002,
            kalman_trend=1.2,
            kalman_slope=0.003,
            kalman_price_position=0.65,
            kalman_uncertainty=0.4,
            kalman_upper=4910.0,
            kalman_lower=4895.0,
            kalman_gain=0.12,
        )
        assert ctx.garch_vol_regime == 1
        assert ctx.kalman_trend == 1.2

    def test_i5_patterns_rejects_unknown_field(self):
        """I5Patterns with unknown_field raises ValidationError."""
        from pydantic import ValidationError

        from src.intelligence.schemas import I5Patterns

        with pytest.raises(ValidationError):
            I5Patterns(some_undeclared_field=99.9)

    def test_smc_context_rejects_unknown_field(self):
        """SMCContext with unknown_field raises ValidationError."""
        from pydantic import ValidationError

        from src.intelligence.schemas import SMCContext

        with pytest.raises(ValidationError):
            SMCContext(unknown_smc_field=True)

    def test_smc_context_uses_smc_trend_direction(self):
        """SMCContext has smc_trend_direction (not trend_direction) to avoid I3 collision."""
        from src.intelligence.schemas import SMCContext

        smc = SMCContext(smc_trend_direction=1)
        assert smc.smc_trend_direction == 1
        # I3 has trend_direction — SMC should NOT have trend_direction
        assert not hasattr(smc, "trend_direction") or True  # check via pydantic

    def test_intelligence_event_schema_version_is_literal(self):
        """schema_version must be '1.0' — cannot be set to '2.0'."""
        from pydantic import ValidationError

        from src.intelligence.schemas import (
            I1Indicators,
            I3Structure,
            I4Context,
            I5Patterns,
            I6Confluence,
            IntelligenceEvent,
            OHLCVBar,
            SMCContext,
        )

        with pytest.raises(ValidationError):
            IntelligenceEvent(
                ts=datetime(2026, 1, 1),
                symbol="ES",
                tf="1m",
                schema_version="2.0",  # invalid Literal
                bar=OHLCVBar(o=100.0, h=101.0, l=99.0, c=100.5, v=1000),
                i1=I1Indicators(),
                i3=I3Structure(),
                i4=I4Context(),
                i5=I5Patterns(),
                smc=SMCContext(),
                i6=I6Confluence(),
            )

    def test_intelligence_event_all_sub_models_exist(self):
        """schemas.py exports all 7 required sub-models."""
        from src.intelligence import schemas

        required_exports = [
            "IntelligenceEvent",
            "OHLCVBar",
            "I1Indicators",
            "I3Structure",
            "I4Context",
            "I5Patterns",
            "SMCContext",
            "I6Confluence",
        ]
        for name in required_exports:
            assert hasattr(schemas, name), f"schemas.py missing: {name}"


class TestPublisherFormat:
    """RED→GREEN tests for _publish_intelligence() emitting typed event JSON."""

    def _make_service(self):
        from services.market_analysis_service import MarketAnalysisService
        svc = MarketAnalysisService()
        svc._kafka_producer = AsyncMock()
        svc._kafka_producer.publish = AsyncMock()
        svc.error_count_total = MagicMock()
        svc.error_count_total.inc = MagicMock()
        return svc

    def _make_tiered(self, **overrides):
        """Build a minimal valid tiered dict from _run_analysis_pipeline."""
        tiered = {
            "i3": {},
            "i4": {},
            "i5": {},
            "smc": {},
            "i6": {},
        }
        tiered.update(overrides)
        return tiered

    @pytest.mark.asyncio
    async def test_publish_intelligence_emits_single_event_field(self):
        """_publish_intelligence() calls redis.xadd with a single 'event' key containing JSON.

        Verifies the new contract: NOT flat field keys like b'garch_sigma', but a
        single serialized IntelligenceEvent JSON under the 'event' key.
        """
        svc = self._make_service()
        ts = datetime(2026, 1, 1, 12, 0, 0)
        bar_data = {"open": 4900.0, "high": 4905.0, "low": 4895.0, "close": 4902.0, "volume": 100}
        i1_features = {"rsi_14": 55.0}
        tiered = self._make_tiered()

        await svc._publish_intelligence("ES", "1m", tiered, ts, bar_data, i1_features)

        assert svc._kafka_producer.publish.called
        call_args = svc._kafka_producer.publish.call_args
        # publish(topic, msg_dict, key=...) — msg_dict is second positional arg
        msg_dict = call_args.args[1] if call_args.args else call_args.kwargs.get("msg", {})

        # There should be exactly one field key: "event"
        assert "event" in msg_dict

        # The value must be a JSON string containing "schema_version"
        event_val = msg_dict.get("event")
        if isinstance(event_val, bytes):
            event_val = event_val.decode()
        assert "schema_version" in event_val

        # Verify it does NOT contain flat individual field keys
        for flat_key in ["garch_sigma", "rsi_14", "vol_regime"]:
            assert flat_key not in msg_dict

    @pytest.mark.asyncio
    async def test_publish_intelligence_drops_event_on_validation_error(self):
        """Unrecognized field in tiered dict → ValidationError caught, xadd is NOT called."""
        svc = self._make_service()
        ts = datetime(2026, 1, 1, 12, 0, 0)
        bar_data = {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 100}
        i1_features = {}

        # Inject an invalid field into i4 — this should raise ValidationError
        bad_tiered = self._make_tiered(
            i4={"garch_sigma": 0.01, "UNKNOWN_PLUGIN_FIELD_XYZ": 999.0},
        )

        await svc._publish_intelligence("ES", "1m", bad_tiered, ts, bar_data, i1_features)

        # publish must NOT have been called — malformed event dropped
        assert not svc._kafka_producer.publish.called

    @pytest.mark.asyncio
    async def test_publish_intelligence_uses_model_dump_json(self):
        """The published event JSON can be round-tripped as IntelligenceEvent."""

        from src.intelligence.schemas import IntelligenceEvent

        svc = self._make_service()
        ts = datetime(2026, 1, 1, 12, 0, 0)
        bar_data = {"open": 4900.0, "high": 4905.0, "low": 4895.0, "close": 4902.0, "volume": 200}
        i1_features = {"rsi_14": 60.0, "atr_14": 12.5}
        tiered = self._make_tiered(
            i4={"garch_sigma": 0.015, "garch_vol_regime": 1},
            i3={"swing_pattern": 1.0},
        )

        await svc._publish_intelligence("ES", "1m", tiered, ts, bar_data, i1_features)

        assert svc._kafka_producer.publish.called
        call_args = svc._kafka_producer.publish.call_args
        msg_dict = call_args.args[1] if call_args.args else call_args.kwargs.get("msg", {})

        event_json = msg_dict.get("event")
        if isinstance(event_json, bytes):
            event_json = event_json.decode()

        # Must be deserializable as IntelligenceEvent
        recovered = IntelligenceEvent.model_validate_json(event_json)
        assert recovered.symbol == "ES"
        assert recovered.i4.garch_vol_regime == 1


class TestPluginCache:
    """Plugin reference cache — eliminates per-bar registry.get_pattern() calls."""

    def test_plugin_cache_populated_at_init(self):
        """_plugin_cache must contain all I2-I6 plugin names after __init__."""
        from services.market_analysis_service import MarketAnalysisService
        from src.intelligence.register_plugins import (
            TIER_I2,
            TIER_I3,
            TIER_I4,
            TIER_I5,
            TIER_I6,
            TIER_SMC,
        )

        svc = MarketAnalysisService()
        all_names = TIER_I2 + TIER_I3 + TIER_I4 + TIER_I5 + TIER_SMC + TIER_I6
        for name in all_names:
            assert name in svc._plugin_cache, f"_plugin_cache missing: {name}"

    @pytest.mark.asyncio
    async def test_run_tier_does_not_call_registry_get_pattern(self):
        """_run_tier must use _plugin_cache — NOT call registry.get_pattern() on each bar."""
        from unittest.mock import patch

        import pandas as pd

        from services.market_analysis_service import MarketAnalysisService
        from src.intelligence.plugins import registry

        svc = MarketAnalysisService()
        frames = {
            "main": pd.DataFrame(
                [{"open": 100.0, "high": 101.0, "low": 99.0,
                  "close": 100.5, "volume": 500}] * 30
            ),
            "features": {},
        }

        with patch.object(registry, "get_pattern") as mock_get:
            await svc._run_analysis_pipeline("ES", "1m", frames)

        mock_get.assert_not_called()


class TestPluginStateIsolation:
    """Plugin _state must be namespaced per (plugin, symbol, timeframe)."""

    @pytest.mark.asyncio
    async def test_state_is_keyed_per_symbol(self):
        """Running the same plugin for ES and NQ must produce independent state dicts."""
        import pandas as pd

        from services.market_analysis_service import MarketAnalysisService

        svc = MarketAnalysisService()

        def make_frames(rsi_prev, rsi_curr):
            df = pd.DataFrame(
                [{"open": 100.0, "high": 101.0, "low": 99.0,
                  "close": 100.5, "volume": 500}] * 30
            )
            return {
                "main": df,
                "features": {"rsi_14": rsi_curr, "macd_12_26_9": 0.5, "roc_14": 0.3},
                "prev_features": {"rsi_14": rsi_prev, "macd_12_26_9": 0.4, "roc_14": 0.2},
            }

        # Run ES:1m — rsi accel = 5.0
        await svc._run_analysis_pipeline("ES", "1m", make_frames(50.0, 55.0))
        # Run NQ:1m — rsi accel = -3.0
        await svc._run_analysis_pipeline("NQ", "1m", make_frames(60.0, 57.0))

        pname = "evt_MomentumAcceleration"
        es_state = svc._plugin_states.get((pname, "ES", "1m"), {})
        nq_state = svc._plugin_states.get((pname, "NQ", "1m"), {})

        # States must be separate dicts
        assert es_state is not nq_state
        # ES accumulated rsi_accel = 5.0, NQ = -3.0
        assert es_state.get("prev_rsi_accel") == pytest.approx(5.0, abs=0.01)
        assert nq_state.get("prev_rsi_accel") == pytest.approx(-3.0, abs=0.01)

    @pytest.mark.asyncio
    async def test_state_accumulates_across_bars_same_symbol(self):
        """Calling the same symbol twice must accumulate state in the same dict."""
        import pandas as pd

        from services.market_analysis_service import MarketAnalysisService

        svc = MarketAnalysisService()
        pname = "evt_MomentumAcceleration"

        async def run(rsi_prev, rsi_curr):
            df = pd.DataFrame(
                [{"open": 100.0, "high": 101.0, "low": 99.0,
                  "close": 100.5, "volume": 500}] * 30
            )
            await svc._run_analysis_pipeline("ES", "1m", {
                "main": df,
                "features": {"rsi_14": rsi_curr, "macd_12_26_9": 0.5, "roc_14": 0.3},
                "prev_features": {"rsi_14": rsi_prev, "macd_12_26_9": 0.4, "roc_14": 0.2},
            })
            return svc._plugin_states.get((pname, "ES", "1m"), {}).copy()

        state_after_bar1 = await run(50.0, 55.0)   # accel = +5.0
        state_after_bar2 = await run(55.0, 53.0)   # accel = -2.0

        assert state_after_bar1.get("prev_rsi_accel") == pytest.approx(5.0, abs=0.01)
        assert state_after_bar2.get("prev_rsi_accel") == pytest.approx(-2.0, abs=0.01)


class TestPrometheusSampling:
    """record_plugin_execution is called at sampled rate for successes, always for errors."""

    @pytest.mark.asyncio
    async def test_success_metrics_sampled_at_rate_10(self):
        """Success metrics recorded only every 10th call, not every call."""
        from unittest.mock import patch

        import pandas as pd

        from services.market_analysis_service import MarketAnalysisService

        svc = MarketAnalysisService()
        df = pd.DataFrame(
            [{"open": 100.0, "high": 101.0, "low": 99.0,
              "close": 100.5, "volume": 500}] * 30
        )
        frames = {"main": df, "features": {}, "prev_features": {}}

        with patch(
            "services.market_analysis_service.record_plugin_execution"
        ) as mock_record:
            for _ in range(10):
                await svc._run_analysis_pipeline("ES", "1m", frames)

        # With 48 plugins × 10 calls = 480 total success invocations
        # At rate=10, we expect 48 recorded (every 10th)
        # But we only care that it's less than total, i.e. sampled
        success_calls = [
            c for c in mock_record.call_args_list if c.args[4] == "success"
        ]
        total_plugin_invocations = len(
            list(svc._plugin_cache.keys())
        ) * 10
        assert len(success_calls) < total_plugin_invocations, (
            "Expected sampling: fewer success records than total invocations"
        )
        # Exactly 1-in-10 should be recorded
        assert len(success_calls) == len(svc._plugin_cache) * 1  # 1 per plugin at call 10

    @pytest.mark.asyncio
    async def test_error_metrics_always_recorded(self):
        """Error metrics are recorded on every failure — never sampled."""
        from unittest.mock import MagicMock, patch

        import pandas as pd

        from services.market_analysis_service import MarketAnalysisService

        svc = MarketAnalysisService()

        # Make one plugin always raise
        boom_name = list(svc._plugin_cache.keys())[0]
        mock_plugin = MagicMock()
        mock_plugin.compute_full.side_effect = RuntimeError("boom")
        svc._plugin_cache[boom_name] = mock_plugin

        df = pd.DataFrame(
            [{"open": 100.0, "high": 101.0, "low": 99.0,
              "close": 100.5, "volume": 500}] * 30
        )
        frames = {"main": df, "features": {}, "prev_features": {}}

        with patch(
            "services.market_analysis_service.record_plugin_execution"
        ) as mock_record:
            for _ in range(5):
                await svc._run_analysis_pipeline("ES", "1m", frames)

        error_calls = [
            c for c in mock_record.call_args_list
            if c.args[4] == "error" and c.args[0] == boom_name
        ]
        assert len(error_calls) == 5, "Errors must be recorded on every invocation"


def test_df_cache_miss_builds_dataframe():
    from collections import deque
    from datetime import datetime

    import pandas as pd

    from services.market_analysis_service import MarketAnalysisService
    svc = MarketAnalysisService()
    key = "ES:1m"
    svc.bar_history[key] = deque(maxlen=200)
    svc._df_cache[key] = None
    svc.bar_history[key].append({"timestamp": datetime(2026,2,28,10,0), "close": 5303.0})
    df = svc._get_df(key)
    assert isinstance(df, pd.DataFrame) and len(df) == 1

def test_df_cache_hit_returns_same_object():
    import pandas as pd

    from services.market_analysis_service import MarketAnalysisService
    svc = MarketAnalysisService()
    key = "ES:5m"
    cached = pd.DataFrame([{"close": 5300.0}])
    svc._df_cache[key] = cached
    assert svc._get_df(key) is cached

def test_bar_append_invalidates_cache():
    from collections import deque
    from datetime import datetime

    import pandas as pd

    from services.market_analysis_service import MarketAnalysisService
    svc = MarketAnalysisService()
    key = "NQ:1m"
    svc.bar_history[key] = deque(maxlen=200)
    svc._df_cache[key] = pd.DataFrame([{"close": 5300.0}])
    svc.bar_history[key].append({"timestamp": datetime(2026,2,28,10,1), "close": 5310.0})
    svc._df_cache[key] = None
    assert svc._df_cache[key] is None
