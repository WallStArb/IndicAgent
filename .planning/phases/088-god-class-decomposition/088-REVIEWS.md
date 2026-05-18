---
phase: 88
reviewers: [codex]
reviewed_at: 2026-05-18T00:00:00Z
plans_reviewed:
  - 088-01-PLAN.md
  - 088-02-PLAN.md
  - 088-03-PLAN.md
  - 088-04-PLAN.md
  - 088-05-PLAN.md
---

# Cross-AI Plan Review — Phase 088: God Class Decomposition

## Gemini Review

*Gemini CLI misinterpreted the review prompt as an implementation request and terminated without producing a plan review. Output not usable.*

---

## Codex Review

## Summary

The plans are unusually detailed and show strong awareness of the existing failure modes, especially around async queues, checkpoint ownership, cache refresh semantics, and CIS scorer mediation. However, I would rate the overall implementation risk as **HIGH** as written. The biggest issues are not documentation gaps; they are contract mismatches that could cause behavior changes: plugin state keying is inconsistent with the proposed DAG, initial cache loads may be lost, `SignalProcessor` still couples directly to `CacheManager`, and several current output paths appear omitted from the final orchestrator.

## Strengths

- Clear sequential decomposition: `OutputQueue` → `PluginStateManager` → `CacheManager` → `PluginExecutor` → `SignalProcessor` is a sensible extraction order.
- Good preservation of several known project rules:
  - Kafka publish uses `msg=`.
  - `datetime.now(UTC)` is called out.
  - jsonb handling is not worsened.
  - structlog `event=` collision is avoided in the plan language.
- Dedicated unit tests per extracted class are a strong move.
- The plan explicitly recognizes tricky cross-owned checkpoint fields instead of hiding them.
- `CacheManager` correctly avoids calling `cis_scorer.update_weights`; scorer mutation belongs outside cache loading.
- The public `seed_*` API for cache restoration/tests is a good stabilizing contract.
- The tuple-return design for signal/DLQ preparation is directionally correct: `SignalProcessor` should not enqueue directly.
- `_pattern_reliability` instance deletion is probably safe if static search confirms it is only written and never read.

## Concerns

- **HIGH: Plugin state keying does not line up with the proposed DAG.**
  Current state is keyed by `(plugin_name, symbol, tf)`. The proposed DAG uses:
  ```python
  key = (symbol, tf)
  state = self._state_mgr.get_state(key)
  lock = self._state_mgr.get_lock(key)
  ```
  But executor tasks still need per-plugin state keys. Passing a `(symbol, tf)` state dict will not preserve current behavior unless `PluginStateManager` changes to a nested namespace model. As written, this risks every plugin seeing empty or wrong state.

- **HIGH: "No lateral coupling" is not actually achieved.**
  `SignalProcessor(cis_scorer, cache: CacheManager, settings)` directly holds `CacheManager`. That is lateral coupling between extracted classes. If D-07 is strict, `SignalProcessor.process(...)` should receive cache snapshots/properties as arguments, or a narrow immutable cache view/interface should be passed by the orchestrator.

- **HIGH: Initial cache loading may be accidentally removed.**
  Current `_setup()` eagerly calls all 6 loaders (_load_perf_weights, _refresh_drift_penalties, etc.). The plan emphasizes `start_refresh_loops()`, whose loops sleep before loading. If eager loads are not preserved, the service starts with empty caches until the first interval — up to 4 hours for some caches.

- **HIGH: Final SignalProcessor/orchestrator plan appears to omit existing publishes.**
  Current behavior publishes: canonical `IntelligenceEvent`, I7 signal payload to `topic_intelligence_i7_signals`, winner to `topic_signals_aggregated`, DLQ payload when CIS assertion fails, bar intelligence journal via `_enqueue_intel_journal`. The final DAG only routes signals/DLQ. If winner aggregation and journal publishing are not explicitly retained, this is not a pure refactor.

- **HIGH: Checkpoint plugin_states is duplicated/inconsistent.**
  `PluginStateManager.write_checkpoint(extra_state)` already writes `plugin_states` from its own state. But `_assemble_checkpoint_extra()` is planned to include `"plugin_states": self._state_mgr.get_all_states()`. That weakens "single writer" and can create double-tagging or overwrite ambiguity. `extra_state` should exclude `plugin_states`.

- **MEDIUM: Background task ownership needs cancellation/error semantics.**
  `start_checkpoint_loop()` re-raising exceptions inside an un-awaited background task can produce unhandled task exceptions and silently kill checkpointing unless the orchestrator observes task results.

- **MEDIUM: OutputQueue drain loop should track whether an item was actually dequeued.**
  The current logic calls `task_done()` inside the broad exception handler. If an exception is raised after `get()`, that is correct; if future code raises before `get()` assigns an item, it can corrupt queue accounting.

- **MEDIUM: `running_fn=lambda: self._running` may be wrong.**
  Current code uses `self.running`. If `BaseAgent` exposes `running` as the canonical property, use `lambda: self.running`.

- **MEDIUM: CacheManager extraction must preserve shadow registry enrollment.**
  Current setup calls `enroll_all_plugins(conn)` before `_load_shadow_cache()`. The plan mentions loading shadow cache but does not clearly keep enrollment.

- **MEDIUM: Tests lean heavily on mocks and source greps.**
  The plans need at least one end-to-end orchestration test with fake components verifying queue routing, checkpoint assembly, state update flow, and journal/winner outputs.

- **LOW: `_pattern_reliability` deletion needs two scopes called out.**
  There is an instance attribute `self._pattern_reliability`, but also module-level `_pattern_reliability_cache` and `_load_pattern_reliability_weights`. If the instance attribute is deleted, the loader/cache should be removed only after repo-wide search confirms no other imports.

## Suggestions

- Fix the state contract before implementation. Prefer one of:
  - `PluginStateManager.get_all_states_for(symbol, tf)` returns mapping keyed by plugin name; `update_batch()` writes back `(plugin_name, symbol, tf)`.
  - Or keep executor pure by passing the full state dict and making state keys explicit in the call.
- Remove `"plugin_states"` from `_assemble_checkpoint_extra()`. Let `PluginStateManager` be the only source.
- Add `CacheManager.load_initial()` or `start_refresh_loops(load_now=True)` to preserve eager loading before the first sleep interval.
- Resolve D-07 honestly: either accept that `SignalProcessor -> CacheManager` is allowed (and update D-07), or change `SignalProcessor.process()` to receive `cache_snapshot` dicts from the orchestrator.
- Add a final integration-style test: fake executor + fake signal processor → assert orchestrator routes canonical event, signals/DLQ, winner, journal correctly.
- Explicitly preserve `topic_signals_aggregated` and journal publishing in 088-05, or state where they moved.
- In `OutputQueue.drain_loop`, structure narrowly:
  ```python
  item = await queue.get()
  try:
      await producer.publish(...)
  finally:
      queue.task_done()
  ```
- Add cancellation tests for all background loops.
- Repo-wide verification before `_pattern_reliability` deletion: `rg "_pattern_reliability|load_pattern_reliability"`.

## Risk Assessment

**Overall risk: HIGH.**

The extraction direction is sound, but several plan contracts currently conflict with existing behavior. The most serious risks are the plugin state key mismatch, incomplete final output routing, loss of eager cache loading, and ambiguous "zero lateral coupling" because `SignalProcessor` directly owns a `CacheManager` reference.

---

## Ollama Review (qwen3.5:4b)

*Failed — empty response. Likely exceeded qwen3.5:4b context window (120KB prompt). Skipped.*

---

## Consensus Summary

*Based on Codex review (Gemini non-responsive, Ollama pending).*

### Agreed Strengths

- Sequential extraction order (OutputQueue → StateManager → CacheManager → Executor → SignalProcessor) is sound
- Explicit handling of cross-class entanglements (checkpoint, CIS scorer mediation, shadow_cache per-call) is thorough
- Public `seed_*` API for CacheManager testing is a strong stabilizing contract
- Tuple-return pattern for SignalProcessor (no direct enqueue) is correct

### Critical Concerns (from Codex — HIGH severity)

1. **Plugin state key mismatch** — `PluginStateManager.get_state(symbol, tf)` returns a dict, but `PluginExecutor` tasks need per-plugin keys `(plugin_name, symbol, tf)`. Current DAG description in D-08 may not preserve state routing without a nested namespace model.

2. **CacheManager→SignalProcessor is lateral coupling** — `SignalProcessor(cache: CacheManager)` violates D-07. Either accept it and update D-07, or have the orchestrator pass cache snapshots per-call.

3. **Eager cache loading may be lost** — `start_refresh_loops()` sleeps before first load. Current `_setup()` eagerly loads all 6 caches. Must preserve initial eager load or the service starts cold for up to 4 hours.

4. **Missing output paths in Plan 05** — `topic_signals_aggregated` (winner) and `_enqueue_intel_journal` must be explicitly accounted for in the final orchestrator — not just signals + DLQ.

5. **Checkpoint plugin_states double-write** — `extra_state` must NOT include `plugin_states` — that is already written by `PluginStateManager` internally. Otherwise "single writer" principle is violated.

### Divergent Views

- Codex rates overall risk HIGH; the plan checker passed after 3 revision rounds. The divergence likely reflects that the plan checker validated structure/contracts while Codex identified runtime behavior correctness risks that require checking against the live god class code.
