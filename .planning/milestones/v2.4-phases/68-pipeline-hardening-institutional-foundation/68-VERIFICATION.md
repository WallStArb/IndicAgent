---
phase: 68-pipeline-hardening-institutional-foundation
verified: 2026-04-23T18:00:00Z
status: gaps_found
score: 13/15 must-haves verified
overrides_applied: 0
gaps:
  - truth: "_setup_last_fire is included in checkpoint state"
    status: failed
    reason: "_checkpoint_state() writes 5 keys to state dict (_plugin_states, _kalman_state, _tod_priors, _bar_history, _last_bar_offset) but NOT _setup_last_fire. The restore path at line 763 reads _setup_last_fire from state if present, but it is never written, so the data is lost on every restart."
    artifacts:
      - path: "services/intelligence_pipeline_agent.py"
        issue: "_checkpoint_state() state dict (lines 1559-1565) missing '_setup_last_fire' key"
    missing:
      - "Add \"'_setup_last_fire': self._setup_last_fire\" to the state dict in _checkpoint_state()"
  - truth: "Long bias in tiebreaks is configurable via WINNER_LONG_BIAS env var"
    status: partial
    reason: "select_winner() accepts long_bias kwarg (default True) and Settings.winner_long_bias field was added, but the call site at line 1504 of intelligence_pipeline_agent.py does not pass long_bias=self._settings.winner_long_bias — it uses the hardcoded default True. The setting exists but is not wired to the call site."
    artifacts:
      - path: "services/intelligence_pipeline_agent.py"
        issue: "select_winner(ranked, cis_result) at line 1504 does not pass long_bias — WINNER_LONG_BIAS env var has no effect"
    missing:
      - "Change line 1504 to: select_winner(ranked, cis_result, long_bias=self._settings.winner_long_bias)"
---

# Phase 68: Pipeline Hardening & Institutional Foundation Verification Report

**Phase Goal:** Fix 5 critical signal pipeline bugs (regime type bypass, dead Settings thresholds, numeric label, long bias, confidence boost pre-calibration), add BaseWriterAgent consolidating shared buffer/flush/offset-commit/DLQ machinery across all 5 writer agents, add end-to-end bar_id trace from provider to lifecycle exit, full 5-point confidence attribution vector, and TRUNCATE signal_ledger for a clean slate after regime filtering was bypassed for all historical signals.

**Verified:** 2026-04-23T18:00:00Z
**Status:** gaps_found — 2 gaps in 68-01 (checkpoint and long_bias wiring)
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Plugins with regime_type='mean_reversion' are suppressed when HMM regime is trending | VERIFIED | `getattr(plugin_inst, "regime_type", "any")` at line 1398; `apply_regime_gate` wired with `prob_min=self._regime_prob_min, dur_min=self._regime_dur_min` at line 1452 |
| 2 | Settings.regime_prob_min and regime_dur_min values are passed to apply_regime_gate | VERIFIED | Line 1452: `prob_min=self._regime_prob_min, dur_min=self._regime_dur_min` confirmed |
| 3 | sig['regime_type'] comes from plugin class attribute, not from HMM numeric value | VERIFIED | Line 1398 injects from `getattr(plugin_inst, "regime_type", "any")`; `_HMM_REGIME_LABEL` dict at line 193 handles hmm_regime_label separately; old `f["regime_type"] = f.get("hmm_regime")` is gone |
| 4 | Long bias in tiebreaks is configurable via WINNER_LONG_BIAS env var | PARTIAL FAIL | `select_winner()` accepts `long_bias: bool = True` and Settings has `winner_long_bias` field, but call site at line 1504 does not pass `long_bias=self._settings.winner_long_bias` — WINNER_LONG_BIAS env var is silently ignored |
| 5 | Confidence boost per agreeing signal is removed; n_agreeing_signals captured instead | VERIFIED | No `_CONFIDENCE_BOOST_PER_AGREE` in winner_selector.py; `n_agreeing_signals` and `n_opposing_signals` set in both `_aggregate_via_cis` and `_aggregate_fallback` |
| 6 | resolution_method is stamped on every ranked signal, not discarded | VERIFIED | Lines 1506-1508: `for sig in ranked: sig["resolution_method"] = resolution_method` |
| 7 | _setup_last_fire is included in checkpoint state | FAIL | `_checkpoint_state()` (lines 1557-1572) state dict contains 5 keys but NOT `_setup_last_fire`. Restore logic at line 763 checks for it — it is read but never written |
| 8 | 5-point attribution vector: pre_quality, pre_regime, pre_tod, pre_calibration, calibrated | VERIFIED | Lines 1448 (`pre_regime_confidence`), 1464 (`pre_tod_confidence`), 1476 (`pre_calibration_confidence`); pre_quality captured in quality_gate; calibrated_confidence set by calibrator |
| 9 | regime_gate_suppressions_total Prometheus counter increments for suppressed signals | VERIFIED | `REGIME_GATE_SUPPRESSIONS_TOTAL` Counter defined at metrics.py:441, imported at line 118, incremented at line 1458 with labels (reason, plugin, tf) |
| 10 | All 5 writer agents inherit from BaseWriterAgent | VERIFIED | All 5: SignalWriterAgent, FeatureWriterAgent, BarWriterAgent, LifecycleWriterAgent, SwarmWriterAgent confirmed via grep |
| 11 | Offset is committed only after successful _flush_batch() | VERIFIED | `_do_flush()` in base_writer.py: `await self._consumer.commit()` executes only after `await self._flush_batch(batch)` succeeds |
| 12 | Every BarMessage published by ibkr_provider has a unique bar_id UUID | VERIFIED | `bar_id: UUID = Field(default_factory=uuid4)` at bar_message.py:91; auto-generated on construction |
| 13 | bar_id flows from BarMessage through IntelligenceEvent to BarIntelligenceRecord | VERIFIED | `IntelligenceEvent.bar_id: UUID | None = None` at schemas.py:795; pipeline carries `bar.bar_id` at line 1061; signal dicts get `sig["bar_id"] = str(bar.bar_id)` at line 1501 |
| 14 | signal_ledger is truncated (0 rows) after migration | VERIFIED | `TRUNCATE TABLE signal_ledger` in 063_pipeline_hardening.sql confirmed |
| 15 | Malformed bars in bar_aggregator_agent route to a DLQ topic, not silent drop | VERIFIED | `_dlq_producer` created in `_setup()`, routed to `topic_bar_aggregator_dlq()`, closed in `_teardown()`; DLQ routing on parse failure confirmed at line 283 |

**Score: 13/15 truths verified**

### Deferred Items

None.

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `services/intelligence_pipeline_agent.py` | Fixed _run_i7 with regime type injection, attribution vector, checkpoint, metric | PARTIAL | All fixes present EXCEPT _setup_last_fire not written to checkpoint state |
| `src/intelligence/pipeline/winner_selector.py` | Removed confidence boost, added n_agreeing capture, long bias param | VERIFIED | long_bias param exists in select_winner(); no _CONFIDENCE_BOOST_PER_AGREE; n_agreeing/n_opposing set in both aggregate paths |
| `src/config/settings.py` | winner_long_bias field | VERIFIED | Line 147: `winner_long_bias: bool = Field(default=True, validation_alias="WINNER_LONG_BIAS")` |
| `src/observability/metrics.py` | REGIME_GATE_SUPPRESSIONS_TOTAL counter with labels | VERIFIED | Counter at line 441 with labelnames=[reason, plugin, tf] |
| `src/core/agent/base_writer.py` | BaseWriterAgent ABC with consume-parse-buffer-flush-commit loop | VERIFIED | 8531 bytes; BaseWriterAgent(BaseAgent, abc.ABC); all abstract methods, _do_flush, _teardown confirmed |
| `services/signal_writer_agent.py` | SignalWriterAgent inheriting BaseWriterAgent | VERIFIED | class SignalWriterAgent(BaseWriterAgent); enable_auto_commit=False |
| `services/feature_writer_agent.py` | FeatureWriterAgent inheriting BaseWriterAgent | VERIFIED | class FeatureWriterAgent(BaseWriterAgent); enable_auto_commit=False |
| `services/bar_writer_agent.py` | BarWriterAgent inheriting BaseWriterAgent | VERIFIED | class BarWriterAgent(BaseWriterAgent); enable_auto_commit=False |
| `services/lifecycle_writer_agent.py` | LifecycleWriterAgent inheriting BaseWriterAgent | VERIFIED | class LifecycleWriterAgent(BaseWriterAgent); enable_auto_commit=False |
| `services/swarm_writer_agent.py` | SwarmWriterAgent inheriting BaseWriterAgent | VERIFIED | class SwarmWriterAgent(BaseWriterAgent); enable_auto_commit=False |
| `src/core/schemas/bar_message.py` | BarMessage with bar_id: UUID field | VERIFIED | `bar_id: UUID = Field(default_factory=uuid4)` at line 91 |
| `src/intelligence/schemas.py` | IntelligenceEvent with bar_id field | VERIFIED | `bar_id: UUID | None = None` at line 795 |
| `production/migrations/063_pipeline_hardening.sql` | Schema changes + TRUNCATE signal_ledger | VERIFIED | 8 column adds, TRUNCATE, unique constraint, 2 indexes, BEGIN/COMMIT |
| `production/migrations/064_symbol_keyed_aggregates.sql` | 6 tables with symbol column and updated PKs | VERIFIED | 6 ADD COLUMN IF NOT EXISTS symbol + 6 ADD PRIMARY KEY statements |
| `src/intelligence/pipeline/tod_adjuster.py` | apply_tod_adjustment with symbol param and 2-level fallback | VERIFIED | `symbol: str = "*"` param; specific_key then global_key lookup pattern |
| `src/intelligence/pipeline/calibrator.py` | apply_calibration with symbol param and (plugin, tf, symbol) key | VERIFIED | `symbol: str = "*"` param; 3-tuple (plugin_name, tf, symbol) keys |
| `src/intelligence/pipeline/ranker.py` | rank_signals with symbol param and 2-level perf_weights fallback | VERIFIED | `symbol: str = "*"` param; (plugin, tf, symbol) then (plugin, tf, '*') fallback |
| `src/intelligence/metrics/compute.py` | SignalMetricsResult with symbol field; grouping by (plugin, tf, regime, symbol) | VERIFIED | `symbol: str` at line 48; compute_signal_metrics groups by (plugin, tf, regime_label, symbol) |
| `src/core/stream_keys.py` | topic_bar_aggregator_dlq() function | VERIFIED | `topic_bar_aggregator_dlq(env_name)` at line 372 returns `{env}.bar.aggregator.dlq` |
| `src/core/bar_accumulator.py` | Forward-only timestamp validation in update() | VERIFIED | `bar_accumulator_out_of_order` warning at line 159; `__debug__` guard removed (no matches) |
| `services/bar_aggregator_agent.py` | DLQ routing, emit-once guard, bounded processing | VERIFIED | `_dlq_producer`, `_last_emitted` dict, `asyncio.Semaphore(200)`, all confirmed |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| intelligence_pipeline_agent.py | regime_gate.py | apply_regime_gate(prob_min=self._regime_prob_min, dur_min=self._regime_dur_min) | WIRED | Line 1452 confirmed |
| intelligence_pipeline_agent.py | metrics.py | REGIME_GATE_SUPPRESSIONS_TOTAL.labels(...).inc() | WIRED | Import at line 118, call at line 1458 |
| services/signal_writer_agent.py | src/core/agent/base_writer.py | class SignalWriterAgent(BaseWriterAgent) | WIRED | Confirmed |
| src/core/agent/base_writer.py | src/core/agent/base.py | class BaseWriterAgent(BaseAgent, abc.ABC) | WIRED | Confirmed at line 54 |
| src/providers/base_provider_agent.py | src/core/schemas/bar_message.py | bar_id auto-generated via default_factory=uuid4 | WIRED | Pydantic auto-generates on BarMessage construction; no explicit stamping needed |
| intelligence_pipeline_agent.py | src/intelligence/schemas.py | bar.bar_id carried through to IntelligenceEvent | WIRED | Line 1061 passes bar_id=bar.bar_id |
| services/bar_aggregator_agent.py | src/core/stream_keys.py | topic_bar_aggregator_dlq() | WIRED | Imported at line 43, used at line 222 |

---

## Data-Flow Trace (Level 4)

Not applicable — phase 68 fixes pipeline logic rather than adding new rendering components. Data flows confirmed via wiring checks above.

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| winner_selector has no confidence boost | grep -c '_CONFIDENCE_BOOST_PER_AGREE' src/intelligence/pipeline/winner_selector.py | 0 | PASS |
| regime_gate receives Settings params | grep -n 'prob_min=self._regime_prob_min' services/intelligence_pipeline_agent.py | line 1452 | PASS |
| bar_id in BarMessage | grep 'bar_id.*UUID.*Field.*default_factory' src/core/schemas/bar_message.py | line 91 | PASS |
| TRUNCATE in migration 063 | grep -c 'TRUNCATE TABLE signal_ledger' production/migrations/063_pipeline_hardening.sql | 1 | PASS |
| All 5 writers inherit BaseWriterAgent | grep -c 'class.*BaseWriterAgent' services/*.py | 5 | PASS |
| _checkpoint_state writes _setup_last_fire | grep '"_setup_last_fire"' _checkpoint_state state dict | 0 matches | FAIL |
| select_winner receives long_bias from Settings | grep 'long_bias=self._settings.winner_long_bias' services/intelligence_pipeline_agent.py | 0 matches | FAIL |
| 44 pipeline+winner selector tests pass | pytest test_intelligence_pipeline_agent.py test_winner_selector.py -q | 44 passed | PASS |
| 43 bar accumulator/aggregator tests pass | pytest -k "bar_accumulator or bar_aggregator" -q | 43 passed | PASS |

---

## Requirements Coverage

All Phase 68 requirement IDs (PIPE-*, WRITER-*, TRACE-*, AGG-*) are plan-internal identifiers not tracked in REQUIREMENTS.md. No entries for these IDs exist in `.planning/REQUIREMENTS.md`. Coverage is assessed directly against plan must_haves above.

| Requirement | Plan | Status | Evidence |
|-------------|------|--------|----------|
| PIPE-REGIME-FILTER | 68-01 | VERIFIED | regime_type from plugin class attr; apply_regime_gate called with Settings params |
| PIPE-SETTINGS-WIRE | 68-01 | VERIFIED | self._regime_prob_min/dur_min wired from Settings |
| PIPE-LABEL-FIX | 68-01 | VERIFIED | _HMM_REGIME_LABEL dict separates hmm_regime_label from hmm_regime |
| PIPE-LONG-BIAS | 68-01 | PARTIAL | winner_long_bias in Settings, long_bias param in select_winner, but call site does not pass it |
| PIPE-CONFIDENCE-BOOST | 68-01 | VERIFIED | _CONFIDENCE_BOOST_PER_AGREE removed from winner_selector.py |
| PIPE-RESOLUTION-METHOD | 68-01 | VERIFIED | resolution_method stamped on all ranked signals |
| PIPE-CHECKPOINT | 68-01 | FAILED | _setup_last_fire not written to checkpoint state dict |
| PIPE-ATTRIBUTION-VECTOR | 68-01 | VERIFIED | 5-point vector: pre_quality, pre_regime, pre_tod, pre_calibration, calibrated confirmed |
| PIPE-REGIME-METRIC | 68-01 | VERIFIED | REGIME_GATE_SUPPRESSIONS_TOTAL Counter with labels defined and wired |
| WRITER-BASE-CLASS | 68-02 | VERIFIED | BaseWriterAgent ABC with all abstract methods |
| WRITER-OFFSET-COMMIT | 68-02 | VERIFIED | commit only after _flush_batch() succeeds in _do_flush() |
| WRITER-DLQ | 68-02 | VERIFIED | _dlq_topic() hook; all writers parse payloads to None for DLQ routing |
| WRITER-BUFFER-BOUND | 68-02 | VERIFIED | MAX_BUFFER_SIZE=10_000; overflow drops oldest, increments counter |
| TRACE-BAR-ID | 68-03 | VERIFIED | bar_id UUID flows from BarMessage → IntelligenceEvent → signal dicts |
| TRACE-CLEAN-SLATE | 68-03 | VERIFIED | TRUNCATE TABLE signal_ledger in 063_pipeline_hardening.sql |

---

## Anti-Patterns Found

No blocking anti-patterns found in modified files. Stubs, hardcoded empties, and TODO markers searched across all key files — none found.

---

## Gaps Summary

Phase 68 is substantially complete. Two gaps in plan 68-01 prevent full certification:

**Gap 1 — Checkpoint missing _setup_last_fire (PIPE-CHECKPOINT):** `_checkpoint_state()` writes plugin states, kalman state, tod priors, bar history, and last bar offset to the compacted state topic — but omits `_setup_last_fire`. The restore path at line 763 correctly reads it back if present, but since it is never written, the restore is always a no-op. After any service restart, `_setup_last_fire` resets to an empty dict, causing alpha decay to treat every signal as if it was never recently fired. Fix is a one-line addition to the state dict.

**Gap 2 — WINNER_LONG_BIAS setting not wired to call site (PIPE-LONG-BIAS):** `Settings.winner_long_bias` field was added and `select_winner()` was updated to accept `long_bias: bool = True`, but the call site in `_run_i7` (line 1504) passes no `long_bias` kwarg. The default `True` hardcodes the long bias regardless of the `WINNER_LONG_BIAS` environment variable. Fix is adding `long_bias=self._settings.winner_long_bias` to the `select_winner()` call.

Both gaps are confined to `services/intelligence_pipeline_agent.py` and are small, targeted fixes. All other plans (68-02 through 68-05) verified fully.

---

_Verified: 2026-04-23T18:00:00Z_
_Verifier: Claude (gsd-verifier)_
