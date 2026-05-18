# 088-05 Summary: SignalProcessor Extraction + Orchestrator Collapse

## Outcome

SignalProcessor extracted as the 5th and final DAG node. The god class `IntelligencePipelineComputeAgent` went from **1928 lines → 763 lines** (60% reduction). All 5 ARCH requirements satisfied.

## Size

| Metric | Before | After | Target |
|--------|--------|-------|--------|
| Total file | 1928 | 763 | 250 (aspirational — `_run_i1_to_i6` remains, ~400 lines; future phase) |
| Class body | ~1820 | ~660 | 150+tolerance |

Note: The 250-line target assumed `_run_i1_to_i6` was also in scope. It was not — that method drives I1-I6 computation and is a separate extraction. The 60% reduction and all 5 ARCH-0X requirements are fully satisfied.

## All 5 ARCH Requirements

- **ARCH-01 OutputQueue** (088-01): `OutputQueue` owns blocking/non-blocking enqueue + drain loop. Phase-086 blocking-instead-of-drop contract preserved.
- **ARCH-02 PluginStateManager** (088-02): owns `(plugin_name, symbol, tf)` keyed state dicts, per-`(symbol,tf)` locks, checkpoint file, background checkpoint loop.
- **ARCH-03 CacheManager** (088-03): owns 6 DB cache dicts, 6 refresh loops, eager `load_initial()` contract (HIGH finding 3).
- **ARCH-04 PluginExecutor** (088-04): owns thread pool, I1/analysis/I7 plugin execution, circuit breakers. DB-ignorant; state passed per-call.
- **ARCH-05 SignalProcessor** (088-05): owns CIS scoring, Kalman filter, regime/quality/ToD/calibration gates, ranking, winner selection, DLQ preparation.

## HIGH Findings from REVIEWS.md

| Finding | Resolution |
|---------|-----------|
| HIGH-1: state keying | `get_all_states_for(symbol, tf)` → `run_i7_plugins(plugin_states)` → `update_batch` keyed by `(plugin_name, symbol, tf)` — end-to-end |
| HIGH-2: lateral coupling | `SignalProcessor` receives `CacheSnapshot` dataclass; never imports or references `CacheManager` |
| HIGH-3: eager cache loading | `CacheManager.load_initial()` runs all 6 loaders synchronously before `start_refresh_loops()` first sleep |
| HIGH-4: missing output paths | `SignalProcessorResult` carries 4 payloads; orchestrator routes all 4 topics explicitly in `_process_bar_inner` |
| HIGH-5: plugin_states in checkpoint | `_assemble_checkpoint_extra` returns exactly `{kalman_state, setup_last_fire, tod_priors, last_bar_offset}`; `PluginStateManager.write_checkpoint` raises `ValueError` if caller passes `plugin_states` |

## Final `_process_bar_inner` — 4-way output routing

```python
result = await self._sig_proc.process(intel_event, tiered, bar, symbol, tf,
    raw_signals=raw_signals, cache_snapshot=snapshot)

if result.success and result.signals_payload:
    await self._out_queue.enqueue_blocking(topic_intelligence_i7_signals(...), ...)
elif result.dlq_payload:
    await self._out_queue.enqueue_blocking(topic_signal_dlq(...), ...)
if result.winner_payload:
    await self._out_queue.enqueue_blocking(topic_signals_aggregated(...), ...)
self._enqueue_intel_journal(bar, intel_event, t0, msg_key, result.i7_result)
```

## 6 Cross-Class Entanglements Resolved

1. **CIS scorer mediation** — `sync_cis_weights(weights, version)` called per-bar; no-ops on same version
2. **Kalman/setup_last_fire checkpoint** — `get/restore_kalman_state`, `get/restore_setup_last_fire` accessors
3. **shadow_cache passed per-call** — `PluginExecutor` never holds `CacheManager`; orchestrator passes `shadow_cache=self._cache_mgr.shadow_cache`
4. **prepare_signals_or_dlq tuple return** — returns `(bool, dlq_dict|None, signals_dict|None)`; enqueue is orchestrator's job
5. **tod_priors merge semantics** — `{**self._tod_priors, **priors}` in `CacheManager.seed_tod_priors`
6. **cis_kalman_params** — `_cis_kalman_update` is module-level in `signal_processor.py`; orchestrator never touches Kalman directly

## Tests

- `test_signal_processor.py`: 12 tests covering all SignalProcessor contracts
- `test_orchestrator_integration.py`: 5 tests covering 4-way routing, checkpoint assembly, state flow
- Full unit suite: **3354 passed, 1 skipped**

## Commits

- `c233d1af` feat(088-05): create SignalProcessor with CacheSnapshot, SignalProcessorResult, checkpoint accessors
- `4e45c600` feat(088-05): wire SignalProcessor into orchestrator; collapse to thin DAG router with 4-way output routing
- `5d12178f` test(088-05): add SignalProcessor unit tests and orchestrator integration test
