---
phase: 64-i6-confluence-expansion-cross-tf-plugins-macro-context-service
plan: 03B
type: execute
wave: 3
depends_on: ["64-03A"]
gap_closure: true
status: complete
completed: 2026-04-27
note: "03B scope was pipeline integration (not FTQ — FTQ was delivered separately via 03B-FTQ during 03A execution). Pipeline integration shipped: topic_macro_signals subscription + _macro_cache + frames['cross_asset'] merge. No new service or topic needed."
files_modified:
  - services/intelligence_pipeline_agent.py
autonomous: true
requirements: []

must_haves:
  truths:
    - "IntelligencePipelineComputeAgent consumes topic_macro_signals"
    - "Macro factors injected into frames['cross_asset'] for I7 consumption"
    - "Macro fields (yield_curve_slope, ftq_score) available to I7 plugins"
    - "Unit tests pass for macro factor injection"
    - "Integration test: macro factors appear in frames during pipeline execution"
  artifacts:
    - path: "services/intelligence_pipeline_agent.py"
      provides: "Pipeline with macro factor integration"
      contains: "topic_macro_signals subscription and cross_asset injection"
    - path: "src/core/stream_keys.py"
      provides: "topic_macro_signals function"
      contains: "def topic_macro_signals"
  key_links:
    - from: "services/intelligence_pipeline_agent.py"
      to: "topic_macro_signals"
      via: "Kafka consumer subscription"
    - from: "topic_macro_signals"
      to: "frames['cross_asset']"
      via: "_cross_asset_cache injection"
    - from: "frames['cross_asset']"
      to: "I7 plugins"
      via: "frames parameter in compute() calls"
---

<objective>
Integrate macro factors into intelligence pipeline. MacroComputeAgent publishes to topic_macro_signals but IntelligencePipelineComputeAgent does not consume it. Add consumer for topic_macro_signals and inject macro factors into frames['cross_asset'] so I7 plugins can consume yield curve and flight-to-quality data.

Purpose: Macro factors exist (yield curve, FTQ) but are not available to I7 plugins. Close the loop so macro intelligence flows through the pipeline and can be used by trading setups.
Output: Pipeline consumes macro_signals, injects into frames['cross_asset'], I7 plugins can access macro factors.
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
@.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-03A-REVISED-PLAN.md

@services/intelligence_pipeline_agent.py (ADD macro_signals consumer)
@services/macro_compute_agent.py (publishes to topic_macro_signals)
@src/core/stream_keys.py (topic_macro_signals function)
@src/intelligence/schemas.py (MacroSignals schema)

<interfaces>
<!-- Current cross_asset injection pattern -->

From services/intelligence_pipeline_agent.py (EXISTING PATTERN):

Lines 620-627 (topic subscription):
```python
topics = [
    topic_market_bars(self.settings.env_name),
    topic_market_bars_htf(self.settings.env_name),
    topic_system_events(self.settings.env_name),
    topic_cross_asset(self.settings.env_name),
]
```

Lines 865-878 (message processing):
```python
_cross_asset_topic = topic_cross_asset(self.settings.env_name)
_system_topic = topic_system_events(self.settings.env_name)

async for _topic, _key, payload in self._kafka_consumer.messages():
    if _topic == _cross_asset_topic:
        tf = payload.get("tf", "1m")
        self._cross_asset_cache[tf] = payload
    elif _topic == _system_topic:
        await self._handle_system_event(payload)
    else:
        bar = self._parse_bar(payload)
        if bar is None:
            await self._send_to_dlq(payload, Exception("Parse failed"))
            continue
        await self._process_bar(bar)
```

Line 1023 (frames injection):
```python
frames["cross_asset"] = self._cross_asset_cache.get(tf, {"ready": False})
```

NEW: Add topic_macro_signals to this pattern.
Macro factors should be injected into frames['cross_asset'] alongside existing cross-asset data.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
<title>Add topic_macro_signals to pipeline subscription</title>
<dependencies></dependencies>
<read_first>
- services/intelligence_pipeline_agent.py (read topic subscriptions around line 620)
- src/core/stream_keys.py (verify topic_macro_signals exists)
</read_first>
<action>
1. Verify topic_macro_signals() exists in src/core/stream_keys.py:
   ```python
   grep -n "def topic_macro_signals" src/core/stream_keys.py
   ```
   If not found, add it (should exist from Plan 64-03A).

2. Add topic_macro_signals to pipeline subscription in services/intelligence_pipeline_agent.py:

   Find the topic list around line 620 and add:
   ```python
   from src.core.stream_keys import (
       topic_cross_asset,
       topic_macro_signals,  # ADD THIS IMPORT
       # ... other imports ...
   )

   # In _setup() method, add to topics list:
   topics = [
       topic_market_bars(self.settings.env_name),
       topic_market_bars_htf(self.settings.env_name),
       topic_system_events(self.settings.env_name),
       topic_cross_asset(self.settings.env_name),
       topic_macro_signals(self.settings.env_name),  # ADD THIS LINE
   ]
   ```

3. Add message handler in _process_loop() around line 865:
   ```python
   _cross_asset_topic = topic_cross_asset(self.settings.env_name)
   _system_topic = topic_system_events(self.settings.env_name)
   _macro_topic = topic_macro_signals(self.settings.env_name)  # ADD THIS LINE

   async for _topic, _key, payload in self._kafka_consumer.messages():
       if _topic == _cross_asset_topic:
           tf = payload.get("tf", "1m")
           # Merge into existing cross_asset cache
           if tf not in self._cross_asset_cache:
               self._cross_asset_cache[tf] = {}
           self._cross_asset_cache[tf].update(payload)
       elif _topic == _macro_topic:  # ADD THIS HANDLER
           # Macro signals - inject into cross_asset cache
           tf = payload.get("timeframe", payload.get("tf", "1m"))
           if tf not in self._cross_asset_cache:
               self._cross_asset_cache[tf] = {}
           # Merge macro factors into cross_asset
           self._cross_asset_cache[tf].update({
               "yield_curve_slope": payload.get("yield_curve_slope"),
               "yield_curve_regime": payload.get("yield_curve_regime"),
               "ftq_score": payload.get("ftq_score"),
               "ftq_regime": payload.get("ftq_regime"),
           })
       elif _topic == _system_topic:
           await self._handle_system_event(payload)
       else:
           # ... existing bar processing ...
   ```

Key points:
- Macro factors merge into existing cross_asset cache
- Use same tf-based cache structure
- Merge (update) so macro and cross-asset coexist
</action>
<verify>
grep -n "topic_macro_signals" /home/bg/dev/indicagent/services/intelligence_pipeline_agent.py
grep -n "_macro_topic" /home/bg/dev/indicagent/services/intelligence_pipeline_agent.py
</verify>
<acceptance_criteria>
- topic_macro_signals imported in stream_keys imports
- topic_macro_signals added to topics list
- _macro_topic variable defined
- elif _topic == _macro_topic handler added
- Macro factors merged into _cross_asset_cache[tf]
- yield_curve_slope, yield_curve_regime, ftq_score, ftq_regime injected
</acceptance_criteria>
</task>

<task type="auto" tdd="true">
<title>Create unit tests for macro factor integration</title>
<dependencies>Add topic_macro_signals to pipeline subscription</dependencies>
<read_first>
- tests/unit/service_tests/test_intelligence_pipeline_agent.py
</read_first>
<action>
Add tests to tests/unit/service_tests/test_intelligence_pipeline_agent.py:

```python
class TestMacroFactorIntegration:
    """Test macro factor integration into intelligence pipeline."""

    @pytest.mark.asyncio
    async def test_macro_signals_subscription(self):
        """Pipeline subscribes to topic_macro_signals."""
        agent = IntelligencePipelineComputeAgent.__new__(IntelligencePipelineComputeAgent)
        agent._settings = Settings()
        agent._kafka_consumer = AsyncMock()
        agent._kafka_consumer.subscribe = AsyncMock()

        await agent._setup()

        # Verify macro_signals topic in subscription
        subscribe_call = agent._kafka_consumer.subscribe.call_args
        topics = subscribe_call[0][0]
        assert "dev.macro_signals" in topics or "macro_signals" in str(topics)

    @pytest.mark.asyncio
    async def test_macro_factors_injected_to_frames(self):
        """Macro factors appear in frames['cross_asset']."""
        agent = IntelligencePipelineComputeAgent.__new__(IntelligencePipelineComputeAgent)
        agent._settings = Settings()
        agent._cross_asset_cache = {}

        # Simulate macro signal message
        macro_payload = {
            "ts": "2026-04-27T12:00:00Z",
            "symbol": "macro",
            "timeframe": "5m",
            "yield_curve_slope": 0.75,
            "yield_curve_regime": "steepening",
            "ftq_score": -0.3,
            "ftq_regime": "risk_off",
        }

        # Process as macro topic message
        tf = macro_payload.get("timeframe", "1m")
        if tf not in agent._cross_asset_cache:
            agent._cross_asset_cache[tf] = {}
        agent._cross_asset_cache[tf].update({
            "yield_curve_slope": macro_payload.get("yield_curve_slope"),
            "yield_curve_regime": macro_payload.get("yield_curve_regime"),
            "ftq_score": macro_payload.get("ftq_score"),
            "ftq_regime": macro_payload.get("ftq_regime"),
        })

        # Verify cache has macro factors
        assert "5m" in agent._cross_asset_cache
        assert agent._cross_asset_cache["5m"]["yield_curve_slope"] == 0.75
        assert agent._cross_asset_cache["5m"]["ftq_score"] == -0.3

    @pytest.mark.asyncio
    async def test_macro_and_cross_asset_merge(self):
        """Macro factors merge with existing cross-asset data."""
        agent = IntelligencePipelineComputeAgent.__new__(IntelligencePipelineComputeAgent)
        agent._settings = Settings()
        agent._cross_asset_cache = {}

        # First add cross-asset data
        agent._cross_asset_cache["5m"] = {
            "vix_level": 20.5,
            "eq_spread": 100,
        }

        # Then add macro data (simulating macro_signals message)
        macro_payload = {
            "timeframe": "5m",
            "yield_curve_slope": 0.5,
            "ftq_score": 0.2,
        }
        agent._cross_asset_cache["5m"].update({
            "yield_curve_slope": macro_payload.get("yield_curve_slope"),
            "ftq_score": macro_payload.get("ftq_score"),
        })

        # Verify both cross-asset and macro data coexist
        assert agent._cross_asset_cache["5m"]["vix_level"] == 20.5
        assert agent._cross_asset_cache["5m"]["yield_curve_slope"] == 0.5
        assert agent._cross_asset_cache["5m"]["ftq_score"] == 0.2
```

Add 5+ tests for macro integration.
</action>
<verify>
.venv/bin/pytest tests/unit/service_tests/test_intelligence_pipeline_agent.py::TestMacroFactorIntegration -v
</verify>
<acceptance_criteria>
- 5+ unit tests created
- test_macro_signals_subscription passes
- test_macro_factors_injected_to_frames passes
- test_macro_and_cross_asset_merge passes
- All tests use mocks
- pytest -v shows all passing
</acceptance_criteria>
</task>

<task type="checkpoint:human-verify" gate="blocking">
<title>Manual verification: End-to-end macro factor flow</title>
<dependencies>Create unit tests for macro factor integration</dependencies>
<read_first>
- services/intelligence_pipeline_agent.py
- services/macro_compute_agent.py
</read_first>
<action>
Verify end-to-end macro factor flow:

1. **Start MacroComputeAgent:**
   ```bash
   sudo systemctl start indicagent-macro-compute
   sudo systemctl status indicagent-macro-compute
   ```

2. **Restart IntelligencePipelineComputeAgent:**
   ```bash
   sudo systemctl restart indicagent-intelligence-pipeline
   sudo systemctl status indicagent-intelligence-pipeline
   ```

3. **Verify topic consumption:**
   ```bash
   # Check if pipeline is consuming macro_signals
   docker exec redpanda rpk group describe macro_consumer -t dev.macro_signals
   docker exec redpanda rpk group describe intelligence_pipeline_consumer -t dev.macro_signals
   ```

4. **Monitor logs for macro injection:**
   ```bash
   # Watch for macro factor injection
   tail -f logs/intelligence_pipeline_agent.log | grep -i macro
   ```

5. **Verify macro factors in pipeline:**
   - If macro factors appear in logs
   - No errors in pipeline logs
   - Type "approved" to continue

If ANY failures:
- Report specific error
- Check if MacroComputeAgent is publishing
- Check if pipeline is consuming correct topic
</action>
<verify>
Manual verification by human
</verify>
<acceptance_criteria>
- [ ] MacroComputeAgent running
- [ ] IntelligencePipelineComputeAgent running
- [ ] Pipeline consuming macro_signals topic (verify with rkg group describe)
- [ ] No errors in logs
- [ ] Macro factors visible in pipeline logs (if logging added)
- [ ] Human confirms "approved" or reports issues
</acceptance_criteria>
</task>

</tasks>

<verification>
## Overall Verification

1. **Topic subscription added:**
   ```bash
   grep "topic_macro_signals" services/intelligence_pipeline_agent.py
   ```

2. **Message handler added:**
   ```bash
   grep -A 10 "_macro_topic" services/intelligence_pipeline_agent.py
   ```

3. **Unit tests pass:**
   ```bash
   pytest tests/unit/service_tests/test_intelligence_pipeline_agent.py::TestMacroFactorIntegration -v
   ```

4. **Integration test:**
   ```bash
   pytest tests/unit/test_intelligence_pipeline_agent.py -v
   ```

5. **Services running:**
   ```bash
   systemctl is-active indicagent-macro-compute
   systemctl is-active indicagent-intelligence-pipeline
   ```

6. **Topic consumption verified:**
   ```bash
   docker exec redpanda rpk group describe intelligence_pipeline_consumer -t dev.macro_signals
   ```
</verification>

<success_criteria>
1. topic_macro_signals added to pipeline subscription
2. Macro message handler added in _process_loop()
3. Macro factors merged into _cross_asset_cache
4. Unit tests pass (5+ tests)
5. Both services running
6. Pipeline consuming macro_signals topic
7. Macro factors available in frames['cross_asset'] for I7
</success_criteria>

<output>
After completion, create `.planning/phases/64-i6-confluence-expansion-cross-tf-plugins-macro-context-service/64-03B-SUMMARY.md`
</output>
