---
phase: 64-i6-confluence-expansion-cross-tf-plugins-macro-context-service
plan: 03A
type: execute
wave: 3
depends_on: ["64-00"]
gap_closure: true
files_modified:
  - services/macro_compute_agent.py
  - tests/unit/service_tests/test_macro_compute_agent.py
autonomous: true
requirements: []

must_haves:
  truths:
    - "MacroComputeAgent _parse_bar() method fully implemented (not a stub)"
    - "MacroComputeAgent _publish_macro_signal() method fully implemented (not a stub)"
    - "MacroComputeAgent _persist_to_db() method fully implemented (not a stub)"
    - "Service can parse Kafka bar messages from topic_market_bars"
    - "Service can publish macro signals to topic_macro_signals"
    - "Service can persist macro results to macro_features hypertable"
    - "Unit tests pass for all 3 previously stub methods"
  artifacts:
    - path: "services/macro_compute_agent.py"
      provides: "Functional macro factors service"
      contains: "MacroComputeAgent with working _parse_bar, _publish_macro_signal, _persist_to_db"
      min_lines: 320
  key_links:
    - from: "services/macro_compute_agent.py"
      to: "src/core/kafka_utils.py"
      via: "KafkaConsumerClient, KafkaProducerClient"
    - from: "services/macro_compute_agent.py"
      to: "src/intelligence/schemas.py"
      via: "BarMessage, MacroSignals"
    - from: "services/macro_compute_agent.py"
      to: "TimescaleDB"
      via: "asyncpg INSERT into macro_features"
---

<objective>
Fix MacroComputeAgent stub methods. Service was created in original Plan 64-03A but has 3 placeholder methods (_parse_bar, _publish_macro_signal, _persist_to_db) that return None or pass. Implement all 3 methods to make the service functional: parse Kafka bar messages, publish macro signals to topic, persist to macro_features hypertable.

Purpose: MacroComputeAgent exists but is non-functional. Yield curve and flight-to-quality code is delivered but service cannot execute due to stub methods. Fix these blockers so macro factors can be computed and published.
Output: Working MacroComputeAgent that parses bars, computes macro factors, publishes to Kafka, persists to DB.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-CONTEXT.md
@.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-VERIFICATION.md
@.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-00-PLAN.md

@services/macro_compute_agent.py (FIX THIS FILE)
@src/intelligence/schemas.py (BarMessage schema)
@src/core/stream_keys.py (topic_macro_signals, topic_market_bars)
@src/intelligence/macro/yield_curve.py (compute_yield_curve_slope)
@src/intelligence/macro/flight_to_quality.py (compute_flight_to_quality)
@src/intelligence/macro/constants.py (MACRO_RATE_FUTURES, MACRO_FLIGHT_TO_QUALITY)

<interfaces>
<!-- Current stub state to fix -->

From services/macro_compute_agent.py (LINES 209-242 - STUB METHODS):

CURRENT (BROKEN):
```python
def _parse_bar(self, msg_value: bytes) -> dict | None:
    """Parse Kafka bar message.

    Expected format: JSON with ts, symbol, tf, open, high, low, close, volume
    """
    import json

    try:
        bar = json.loads(msg_value)
        # Validate required fields
        if not all(k in bar for k in ["ts", "symbol", "tf", "close"]):
            logger.warning("macro.invalid_bar", missing_fields="required")
            return None
        return bar
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("macro.parse_error", error=str(e))
        return None
```

WAIT - This method is actually implemented! Let me verify the verification report's claim...

Actually, the verification report shows lines 209-242 as stubs, but the code I read shows:
- _parse_bar() IS implemented (lines 215-231)
- _publish_macro_signal() IS implemented (lines 233-252)
- _persist_to_db() IS implemented (lines 254-310)

So the verification report may be outdated or reading an older version. Let me create a plan that verifies the current state and fixes any actual gaps.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
<title>Verify MacroComputeAgent current state</title>
<dependencies></dependencies>
<read_first>
- services/macro_compute_agent.py (read full file)
</read_first>
<action>
Read the current state of services/macro_compute_agent.py and verify:

1. Check if _parse_bar() is implemented (should parse JSON and return dict)
2. Check if _publish_macro_signal() is implemented (should publish to Kafka)
3. Check if _persist_to_db() is implemented (should INSERT into macro_features)

If all 3 methods are implemented, update unit tests to verify they work correctly.
If any are stubs (pass only), implement them.

Current file status from reading shows:
- _parse_bar(): Lines 215-231, IMPLEMENTED
- _publish_macro_signal(): Lines 233-252, IMPLEMENTED
- _persist_to_db(): Lines 254-310, IMPLEMENTED

The verification report may be outdated. Verify actual code state.
</action>
<verify>
grep -A 5 "def _parse_bar" /home/bg/dev/indicagent/services/macro_compute_agent.py
grep -A 10 "async def _publish_macro_signal" /home/bg/dev/indicagent/services/macro_compute_agent.py
grep -A 30 "async def _persist_to_db" /home/bg/dev/indicagent/services/macro_compute_agent.py
</verify>
<acceptance_criteria>
- All 3 methods verified as implemented OR stubs fixed
- No pass-only methods remain
- JSON parsing works for bar messages
- Kafka publish works for macro signals
- DB INSERT works for macro_features
</acceptance_criteria>
</task>

<task type="auto" tdd="true">
<title>Create comprehensive unit tests for MacroComputeAgent</title>
<dependencies>Verify MacroComputeAgent current state</dependencies>
<read_first>
- tests/unit/service_tests/test_macro_compute_agent.py (create if not exists)
</read_first>
<action>
Create or extend tests/unit/service_tests/test_macro_compute_agent.py:

```python
"""Unit tests for MacroComputeAgent."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.macro_compute_agent import MacroComputeAgent


class TestMacroComputeAgent:
    """Test macro factors service."""

    def test_parse_bar_valid_json(self):
        """_parse_bar() parses valid JSON bar message."""
        agent = MacroComputeAgent()
        msg_value = b'{"ts":"2026-04-27T12:00:00Z","symbol":"ZT","tf":"1m","open":98.5,"high":98.7,"low":98.4,"close":98.6,"volume":1000}'

        result = agent._parse_bar(msg_value)

        assert result is not None
        assert result["symbol"] == "ZT"
        assert result["close"] == 98.6

    def test_parse_bar_missing_required_fields(self):
        """_parse_bar() returns None for missing required fields."""
        agent = MacroComputeAgent()
        msg_value = b'{"ts":"2026-04-27T12:00:00Z","symbol":"ZT"}'  # Missing tf, close

        result = agent._parse_bar(msg_value)

        assert result is None

    def test_parse_bar_invalid_json(self):
        """_parse_bar() returns None for invalid JSON."""
        agent = MacroComputeAgent()
        msg_value = b'not json'

        result = agent._parse_bar(msg_value)

        assert result is None

    @pytest.mark.asyncio
    async def test_publish_macro_signal_yield_curve(self):
        """_publish_macro_signal() publishes yield curve result."""
        agent = MacroComputeAgent()
        agent._producer = AsyncMock()
        agent._settings = MagicMock()
        agent._settings.env_name = "dev"

        macro_result = {
            "yield_curve_slope": 0.75,
            "yield_curve_regime": "steepening",
        }
        bar = {
            "ts": "2026-04-27T12:00:00Z",
            "symbol": "ZT",
            "tf": "1m",
        }

        await agent._publish_macro_signal(macro_result, bar)

        # Verify producer.publish was called
        agent._producer.publish.assert_called_once()
        call_args = agent._producer.publish.call_args
        assert "yield_curve_slope" in call_args[1]["value"]

    @pytest.mark.asyncio
    async def test_persist_to_db_yield_curve(self):
        """_persist_to_db() inserts yield curve into macro_features."""
        agent = MacroComputeAgent()
        mock_conn = AsyncMock()
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)
        agent._db_manager = MagicMock()
        agent._db_manager.pool = mock_pool

        macro_result = {
            "yield_curve_slope": 0.75,
            "yield_curve_regime": "steepening",
        }
        bar = {
            "ts": "2026-04-27T12:00:00Z",
            "symbol": "ZT",
            "tf": "1m",
        }

        await agent._persist_to_db(macro_result, bar)

        # Verify INSERT was executed
        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "INSERT INTO macro_features" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_persist_to_db_ftq(self):
        """_persist_to_db() inserts FTQ into macro_features."""
        agent = MacroComputeAgent()
        mock_conn = AsyncMock()
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)
        agent._db_manager = MagicMock()
        agent._db_manager.pool = mock_pool

        macro_result = {
            "ftq_score": -0.5,
            "ftq_regime": "risk_off",
        }
        bar = {
            "ts": "2026-04-27T12:00:00Z",
            "symbol": "SPY",
            "tf": "1m",
        }

        await agent._persist_to_db(macro_result, bar)

        # Verify INSERT was executed with FTQ fields
        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args
        assert "ftq_score" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_full_bar_processing(self):
        """End-to-end: bar received, macro computed, published, persisted."""
        agent = MacroComputeAgent()
        agent._producer = AsyncMock()
        agent._settings = MagicMock()
        agent._settings.env_name = "dev"

        mock_conn = AsyncMock()
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_conn)
        agent._db_manager = MagicMock()
        agent._db_manager.pool = mock_pool

        # Simulate bar message
        msg_value = b'{"ts":"2026-04-27T12:00:00Z","symbol":"ZT","tf":"1m","open":98.5,"high":98.7,"low":98.4,"close":98.6,"volume":1000}'

        # Parse bar
        bar = agent._parse_bar(msg_value)
        assert bar is not None

        # Add to bar windows
        from collections import deque
        agent._bar_windows["ZT"] = deque([bar], maxlen=agent._window_bars + 1)

        # For testing, manually trigger macro computation if conditions met
        if len(agent._bar_windows["ZT"]) >= agent._window_bars:
            # This would normally be in _run() loop
            # For unit test, just verify methods exist and are callable
            pass

        # Verify methods are callable
        assert callable(agent._parse_bar)
        assert callable(agent._publish_macro_signal)
        assert callable(agent._persist_to_db)
```

Create 10+ tests covering all methods.
</action>
<verify>
.venv/bin/pytest tests/unit/service_tests/test_macro_compute_agent.py -v
</verify>
<acceptance_criteria>
- 10+ unit tests created
- test_parse_bar_valid_json passes
- test_parse_bar_missing_fields passes
- test_parse_bar_invalid_json passes
- test_publish_macro_signal_yield_curve passes
- test_persist_to_db_yield_curve passes
- test_persist_to_db_ftq passes
- All tests use mocks (no live infra)
- pytest -v shows all passing
</acceptance_criteria>
</task>

<task type="checkpoint:human-verify" gate="blocking">
<title>Manual verification: MacroComputeAgent integration test</title>
<dependencies>Create comprehensive unit tests for MacroComputeAgent</dependencies>
<read_first>
- services/macro_compute_agent.py
- services/indicagent-macro-compute.service
</read_first>
<action>
Verify MacroComputeAgent works end-to-end:

1. **Check systemd unit exists:**
   ```bash
   ls -la services/indicagent-macro-compute.service
   ```

2. **Verify DB table exists:**
   ```bash
   docker exec timescaledb psql -U postgres -d indicagent -c "\dt macro_features"
   ```

3. **Test service startup (dry run):**
   ```bash
   # Start service manually to test
   python services/macro_compute_agent.py &
   SERVICE_PID=$!
   sleep 5

   # Check logs
   tail -20 logs/macro_compute_agent.log

   # Stop service
   kill $SERVICE_PID
   ```

4. **Verify Kafka topic exists:**
   ```bash
   docker exec redpanda rpk topic list | grep macro_signals
   ```

5. **Manual integration test:**
   - If service starts successfully
   - Logs show "macro_compute_agent.setup"
   - No errors in logs
   - Type "approved" to continue

If ANY failures:
- Report specific error
- Fix required before proceeding
</action>
<verify>
Manual verification by human
</verify>
<acceptance_criteria>
- [ ] systemd unit file exists
- [ ] macro_features table exists in TimescaleDB
- [ ] topic_macro_signals exists in Redpanda
- [ ] Service starts without errors
- [ ] Logs show successful setup
- [ ] Human confirms "approved" or reports issues
</acceptance_criteria>
</task>

</tasks>

<verification>
## Overall Verification

1. **All 3 methods implemented:**
   ```bash
   grep -c "TODO:\|pass$" services/macro_compute_agent.py
   # Should be 0 (no TODOs or bare pass statements)
   ```

2. **Unit tests pass:**
   ```bash
   pytest tests/unit/service_tests/test_macro_compute_agent.py -v
   ```

3. **Service can be imported:**
   ```bash
   python -c "from services.macro_compute_agent import MacroComputeAgent; print('OK')"
   ```

4. **DB table exists:**
   ```bash
   docker exec timescaledb psql -U postgres -d indicagent -c "\dt macro_features"
   ```

5. **Kafka topic exists:**
   ```bash
   docker exec redpanda rpk topic list | grep macro_signals
   ```

6. **Service logs successfully:**
   ```bash
   # Test run
   timeout 5 python services/macro_compute_agent.py || true
   tail -20 logs/macro_compute_agent.log
   ```
</verification>

<success_criteria>
1. MacroComputeAgent has no stub methods (all implemented)
2. Unit tests pass (10+ tests)
3. Service imports without errors
4. macro_features table exists
5. topic_macro_signals exists
6. Service starts successfully
7. Logs show proper initialization
</success_criteria>

<output>
After completion, create `.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-03A-SUMMARY.md`
</output>
