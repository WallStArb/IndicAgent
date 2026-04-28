---
phase: 64-i6-confluence-expansion-cross-tf-plugins-macro-context-service
reviewed: 2026-04-28T00:00:00Z
depth: standard
files_reviewed: 14
files_reviewed_list:
  - services/intelligence_pipeline_agent.py
  - services/macro_compute_agent.py
  - src/intelligence/confluence/cross_tf_momentum_divergence.py
  - src/intelligence/confluence/cross_tf_orderflow_alignment.py
  - src/intelligence/confluence/cross_tf_regime_agreement.py
  - src/intelligence/confluence/cross_tf_sr_confluence.py
  - src/intelligence/confluence/squeeze_expansion_divergence.py
  - src/intelligence/register_plugins.py
  - src/intelligence/schemas.py
  - src/intelligence/trading/confidence_utils.py
  - tests/unit/intelligence/test_cross_tf_momentum_divergence.py
  - tests/unit/service_tests/test_macro_compute_agent.py
  - tests/unit/test_intelligence_pipeline_agent.py
  - tools/backtest_macro_factors.py
findings:
  critical: 4
  warning: 3
  info: 2
  total: 9
status: issues_found
---

# Phase 64: Code Review Report

**Reviewed:** 2026-04-28T00:00:00Z
**Depth:** standard
**Files Reviewed:** 14
**Status:** issues_found

## Summary

Phase 64 adds five cross-TF confluence I6 plugins and a MacroComputeAgent service. The schema registration, pipeline wave ordering, macro cache merge semantics, and unit test coverage are sound. However, a fundamental frame-key mismatch means all five new I6 plugins silently produce their zero/default outputs on every production bar — none of the new confluence scores contribute anything. A secondary data-availability bug in `CrossTFMomentumDivergencePlugin` (wrong field names for RSI and MACD) and a missing field bug in `CrossTFSRConfluencePlugin` (pivot fields that don't exist in any plugin output) compound this. Together these are showstoppers that make Phase 64's core deliverable non-functional.

---

## Critical Issues

### CR-01: All Five New I6 Plugins Read Non-Existent Frame Keys — Silent Zero Output on Every Bar

**Files:**
- `src/intelligence/confluence/cross_tf_momentum_divergence.py:88-89`
- `src/intelligence/confluence/cross_tf_orderflow_alignment.py:85`
- `src/intelligence/confluence/cross_tf_regime_agreement.py:82`
- `src/intelligence/confluence/cross_tf_sr_confluence.py:87-88`
- `src/intelligence/confluence/squeeze_expansion_divergence.py:88`

**Issue:** Every new I6 plugin reads cross-TF data from frame keys that are never populated by the pipeline:

| Plugin | Key it reads | Key the pipeline injects |
|--------|-------------|--------------------------|
| CrossTFMomentumDivergence | `frames["intel_i2"]`, `frames["intel_i4"]` | `frames["intel_5m"]`, `frames["intel_1h"]`, etc. |
| CrossTFOrderFlowAlignment | `frames["intel_i1"]` | same pattern |
| CrossTFRegimeAgreement | `frames["intel_i4"]` | same pattern |
| SqueezeExpansionDivergence | `frames["intel_i4"]` | same pattern |
| CrossTFSRConfluence | `frames["intel_i4"]`, `frames["intel_ohlcv"]` | neither exists |

The pipeline (`intelligence_pipeline_agent.py` lines 1019–1030) stores per-TF flattened intelligence under `frames["intel_{tf}"]` (e.g., `frames["intel_5m"]`), where all tier fields (I1 through SMC) are flattened together. The tier-keyed variants (`intel_i1`, `intel_i2`, `intel_i4`, `intel_ohlcv`) are never created.

Because each plugin uses `.get(missing_key, {})`, they return their safe-fallback defaults (`0.0` divergence, `"mixed"` or `"missing_data"` regime) for every bar in production. The schema validation passes, the service starts, no errors are logged — but all new I6 scores carry zero information.

This is confirmed by examining the working `CrossTimeframeConfluencePlugin` (`cross_timeframe.py` lines 72–75), which correctly iterates `frames.items()` and identifies per-TF intel dicts by checking `key.startswith("intel_")`, then extracts the TF suffix from the key name.

**Fix:** Replace the tier-indexed access pattern with the same pattern used by the existing working plugin:

```python
# Build per-TF intel from the flattened frames["intel_{tf}"] dicts
intel_by_tf: dict[str, dict] = {}
for key, val in frames.items():
    if key.startswith("intel_") and isinstance(val, dict):
        tf = key[6:]   # "intel_5m" -> "5m"
        intel_by_tf[tf] = val  # flattened dict contains I1+I2+I3+I4+SMC fields

# Then access per-TF fields directly:
for tf in self._ALL_TFS:
    if tf not in intel_by_tf:
        continue
    tf_data = intel_by_tf[tf]
    hmm_regime = tf_data.get("hmm_regime")  # from SMC HMMRegime plugin
    atr = tf_data.get("atr_14")             # from I1 ATR plugin
    ...
```

---

### CR-02: CrossTFMomentumDivergencePlugin Uses Wrong Field Names for RSI and MACD

**File:** `src/intelligence/confluence/cross_tf_momentum_divergence.py:119,127`

**Issue:** Even after fixing CR-01, this plugin reads `i4_tf.get("rsi")` and `i4_tf.get("macd_histogram")` — neither of which exists in any plugin's output:

- `rsi` is an I1 field. Its schema name is `rsi_14` (`I1Indicators.rsi_14`). There is no plain `rsi` field.
- `macd_histogram` is also an I1 field. Its schema name is `macd_histogram_12_26_9`. There is no plain `macd_histogram` field.

The unit tests in `test_cross_tf_momentum_divergence.py` inject `{"rsi": ..., "macd_histogram": ...}` directly into the frames dict — synthetic names that happen to match what the plugin reads, but do not match production data. Tests pass; production returns 0.0 from RSI and MACD components.

**Fix:**
```python
# Line 121 — wrong:
rsi = i4_tf.get("rsi")
# Fix:
rsi = i4_tf.get("rsi_14")

# Line 127 — wrong:
macd_hist = i4_tf.get("macd_histogram")
# Fix:
macd_hist = i4_tf.get("macd_histogram_12_26_9")
```

---

### CR-03: CrossTFSRConfluencePlugin References Pivot Fields That Are Not Produced by Any Plugin

**File:** `src/intelligence/confluence/cross_tf_sr_confluence.py:109-114`

**Issue:** The plugin reads `pivot_r1`, `pivot_s1`, `pivot_r2`, `pivot_s2` from the per-TF context dict:

```python
resistance = i4_tf.get("pivot_r1") or i4_tf.get("pivot_r2", 0)
support = i4_tf.get("pivot_s1") or i4_tf.get("pivot_s2", 0)
```

A search across all plugin `outputs` frozensets, `I4Context`, `I3Structure`, and the full `schemas.py` confirms that no plugin in the I1–SMC tiers produces any of these fields. They do not exist in any tier schema. The guard `if ... == 0: continue` will fire for every bar, and the plugin will always return `{"ctf_sr_confluence": 0.0, "ctf_sr_regime": "no_confluence"}`.

The closest matching fields are `nearest_resistance` and `nearest_support` from `SupportResistancePlugin` (I3), available in the flattened intel dict.

**Fix:** After fixing CR-01, replace pivot lookups with the fields that actually exist:
```python
# Wrong — fields don't exist:
resistance = i4_tf.get("pivot_r1") or i4_tf.get("pivot_r2", 0)
support = i4_tf.get("pivot_s1") or i4_tf.get("pivot_s2", 0)

# Fix — use actual I3 S/R fields:
resistance = tf_data.get("nearest_resistance")
support = tf_data.get("nearest_support")
if not isinstance(resistance, (int, float)) or resistance == 0:
    continue
if not isinstance(support, (int, float)) or support == 0:
    continue
```

For `close`, the flattened intel dict does not contain OHLCV bar fields. Use `frames[f"tf_{tf}"].iloc[-1]["close"]` (the BarHistory DataFrame injected at line 1017 of `intelligence_pipeline_agent.py`) instead of the non-existent `frames["intel_ohlcv"]`.

---

### CR-04: MacroComputeAgent.__init__ Does Not Pass settings to super().__init__ — Two Settings Instances in Same Object

**File:** `services/macro_compute_agent.py:99-103`

**Issue:** `MacroComputeAgent.__init__` constructs `settings = Settings()` on line 71 and stores it as `self._settings`. It then calls `super().__init__()` without the `settings=` keyword argument. `BaseAgent.__init__` will call `get_settings()` independently and store a **second** settings object as `self.settings`. The agent ends up with two settings instances: `self._settings` (used by `_run()`, `_setup()`, `_publish_macro_signal()`, `_persist_to_db()`) and `self.settings` (used by BaseAgent internals including the `env_prefix` property and any health/alert publishing).

If env vars differ between the two calls (unlikely in practice, but possible during test setup or environment patching), or if either uses a cached singleton whose cache was cleared between calls, the two settings objects could diverge. This also means `self.settings.env_name` (used by BaseAgent) may not match `self._settings.env_name` (used by topic construction), causing the agent to report metrics and publish alerts under a different env prefix than it reads messages from.

**Fix:**
```python
super().__init__(
    name="MacroComputeAgent",
    metrics_port=settings.macro_metrics_port,
    max_idle_seconds=300,
    settings=settings,  # pass the already-constructed instance
)
```

---

## Warnings

### WR-01: CrossTFMomentumDivergencePlugin Unit Tests Use Synthetic Field Names — No Production Regression Protection

**File:** `tests/unit/intelligence/test_cross_tf_momentum_divergence.py:43-48`

**Issue:** The `_frames()` helper in the test uses `{"rsi": ltf_rsi, "macd_histogram": ltf_macd}` as the I4 context values. These field names are invented by the test and do not match the production schema fields `rsi_14` and `macd_histogram_12_26_9` (CR-02). Additionally, the test injects data under the fictional `"intel_i2"` and `"intel_i4"` keys rather than the production `"intel_5m"` / `"intel_1h"` pattern (CR-01). Tests therefore pass against a synthetic data structure that will never occur in production, providing no regression protection for the actual data path.

**Fix:** After fixing CR-01 and CR-02, update `_frames()` to match production frame layout:
```python
def _frames(self, ...) -> dict:
    return {
        # Use production intel_<tf> key pattern with real field names
        "intel_5m": {
            "rsi_14": ltf_rsi,
            "macd_histogram_12_26_9": ltf_macd,
            "macd_cross_bullish": ltf_direction,
            ...
        },
        "intel_1h": {
            "rsi_14": htf_rsi,
            "macd_histogram_12_26_9": htf_macd,
            "macd_cross_bullish": htf_direction,
            ...
        },
    }
```

---

### WR-02: backtest_macro_factors.py — asof Join Tolerance Too Tight for Multi-TF Signals

**File:** `tools/backtest_macro_factors.py:206-208`

**Issue:** `_merge_with_outcomes()` uses `tolerance=pd.Timedelta("1min")` in `pd.merge_asof`. The signal ledger contains signals across all timeframes (1m through 4h). For a 15m or 1h signal, `feature_ts` aligns to bar boundaries that may be 5, 15, or 60 minutes apart from the nearest macro factor observation. The 1-minute tolerance will cause these signals to produce NaN for `pnl_r`, be dropped by `dropna(subset=["pnl_r"])`, and the matched count will fall far below 30 — causing the validation to return `None` as if there is insufficient data, when the real issue is the tolerance.

This can silently prevent the D-25 gate from ever being evaluated even when sufficient data exists.

**Fix:** Set tolerance to match the dominant signal timeframe, or default to 15 minutes:
```python
tolerance=pd.Timedelta("15min"),   # accommodates 1m through 15m signal alignment
```

---

### WR-03: MacroComputeAgent._run() Does Not Check self.running — Prevents Orderly BaseAgent Shutdown

**File:** `services/macro_compute_agent.py:154`

**Issue:** The `_run()` implementation uses a bare `async for ... in self._consumer.messages()` without checking `self.running` (inherited from `BaseAgent`). `BaseAgent.stop()` sets `_stop_event` and expects the `_run()` coroutine to exit cleanly. The only way this loop exits is via `CancelledError`. A task-cancellation-based shutdown will work (line 200 re-raises), but any `BaseAgent` stop mechanism that relies on `self.running` transitioning to `False` (e.g., the stall monitor) cannot signal `_run()` to stop early.

The canonical pattern from `IntelligencePipelineComputeAgent` (line 873) wraps the consumer loop in `while self.running:`.

**Fix:**
```python
async def _run(self) -> None:
    logger.info("macro_compute_agent.started")
    if not self._consumer:
        raise RuntimeError("Consumer not initialized in _setup")
    try:
        while self.running:
            async for _topic, _key, bar in self._consumer.messages():
                if not self.running:
                    return
                # ... rest of processing ...
    except asyncio.CancelledError:
        logger.info("macro_compute_agent.shutdown")
        raise
```

---

## Info

### IN-01: intelligence_pipeline_agent.py — AGENT_VERSION Defined Twice at Module Scope

**File:** `services/intelligence_pipeline_agent.py:180,349`

**Issue:** `AGENT_VERSION = "v1"` is defined at line 180 (public, no underscore). `_AGENT_VERSION = "v1"` is defined at line 349 (private, underscore-prefixed). Checkpoint key construction at line 613 uses `_AGENT_VERSION`. The public `AGENT_VERSION` is dead code — never read by production paths. The test at `test_intelligence_pipeline_agent.py:52` sets `agent.AGENT_VERSION = "v1"` as an instance attribute, which also has no effect since production code reads the module-level constant.

**Fix:** Remove `AGENT_VERSION = "v1"` at line 180. The underscore-prefixed module constant is the authoritative version sentinel.

---

### IN-02: test_intelligence_pipeline_agent.py — Dead Instance Attribute Setup in _make_agent()

**File:** `tests/unit/test_intelligence_pipeline_agent.py:52`

**Issue:** `agent.AGENT_VERSION = "v1"` is set in `_make_agent()` but is never read by any production method. The checkpoint key in `_checkpoint_state()` uses the module-level `_AGENT_VERSION` constant, not `self.AGENT_VERSION`. This setup creates the impression that the checkpoint key is instance-configurable, which is false.

**Fix:** Remove `agent.AGENT_VERSION = "v1"` from `_make_agent()` in the test.

---

_Reviewed: 2026-04-28T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
