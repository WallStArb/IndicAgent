# Intelligence Pipeline + Signal Lifecycle Integrity

**Date:** 2026-06-02
**Lens:** Renaissance Technologies — data integrity above all, no hidden biases, measurable improvements only
**Scope:** 22 findings across IntelligencePipeline (I1-I7) and SignalTracker/LifecycleWriter

---

## North Star

> "The model doesn't know what it doesn't know. Your job is to make sure the data it learns from tells the truth."

The pipeline has been generating tainted training data simultaneously from multiple bugs. Every bar processed adds more corrupted rows to `intelligence_features`, `signal_ledger`, and `signal_outcomes`. The fix order is not driven by code convenience — it is driven by the need to establish a forensic contamination boundary before modifying any logic.

---

## Contamination Assessment

Three bugs have been co-active for an unknown duration:

1. **Calibration applied to wrong input** — `apply_calibration` in `signal_processor.py` runs on per-signal plugin `confidence`. But `confidence_calibrator.py:74-80` trains on `cis_score AS confidence` from `signal_ledger_full`. This is not an ordering bug — it is a category error. The isotonic curves were trained on CIS scores (bar-level aggregates); the pipeline feeds them per-signal plugin outputs. The transform maps a distribution it was never trained on, producing systematically wrong `calibrated_confidence` values. Fix: remove `apply_calibration` from the per-signal pipeline entirely; apply it to the CIS score inside `CISScorer.score()`.
2. **No quality floor** — signals below any meaningful confidence threshold have been entering `signal_ledger` as valid training labels, polluting `setup_performance` and ML training datasets with noise.
3. **PERF-03 incomplete** — legacy plugins use a cold-start `_state` on every bar. Feature vectors for those plugins are wrong, meaning I7 signals downstream of them carry incorrect inputs.

**`setup_performance` is also contaminated.** Unlike `intelligence_features` and `signal_ledger`, `setup_performance` contains resolved outcomes (sample_size may be ≥ 30) that were generated under all three bugs simultaneously. Version filters alone cannot clean it — pre-fix outcomes are already counted. Phase 0 must reset `perf_multiplier` to neutral; see 0-D.

---

## Canonical Pipeline Stage Order (post all Phase 1+2 changes)

The complete ordered stage list after all changes. This is the authoritative reference — any implementation that deviates is wrong:

```
raw_signals (from I7 plugins)
  ↓ 1. alpha_decay       — penalizes repeated fires (uses setup_last_fire)
  ↓ 2. quality_gate      — Hurst×entropy multiplier; rejects below min_confidence floor
  ↓ 3. regime_gate_soft  — three-band attenuation: suppress / soft-attenuate / pass (hmm_regime_prob + entropy)
  ↓ 4. tod_adjustment    — time-of-day prior multiplier
  ↓ 5. ranking           — adjusted_rank = perf_multiplier (data-driven, no SETUP_PRIORITY)
  ↓ 6. winner_selection  — CIS override or rank/majority fallback

CIS score path (parallel, not sequential):
  raw_cis → Kalman filter → apply_calibration (isotonic, trained on cis_score outcomes) → filtered_cis
  calibrated_cis is stamped onto winner signal as calibrated_confidence
```

**Notes:** Alpha decay (step 1) is independent of calibration — it applies a temporal penalty to raw plugin confidence before any gate. The quality floor in step 2 uses the decayed, quality-multiplied value; the regime soft gate (step 3) can further reduce confidence below the floor but signals are not re-checked against the floor after step 3 — floor gates signal quality, regime gate gates market context. Calibration operates only on the CIS aggregate, not per-signal.

---

## Phase 0 — Forensic Boundary Prep

**What this phase is:** A deliberate state flush and version marker commit. It is NOT "no behavior changes" — it has four intentional side effects documented below. Must ship as a single atomic commit before any logic fix.

### 0-A: `feature_schema_version`
- `FEATURE_SCHEMA_VERSION = 2` (starts at 2; all pre-fix rows have NULL = tainted by convention — no backfill).
- Add to `IntelligenceEvent` as `feature_schema_version: int = FEATURE_SCHEMA_VERSION`.
- Migration: add `feature_schema_version INTEGER` to `intelligence_features` (nullable, no default — old rows stay NULL).
- Also add to `signal_ledger` as `feature_schema_version INTEGER` (signals reference the features that generated them).
- **Training filter going forward:** `WHERE feature_schema_version >= 2`. Use `>= 2`, not `= 2` — future backward-compatible schema additions should not be excluded from training queries. Combine with `signal_schema_version` filter for signal-side isolation.
- **Migration must update `signal_ledger_full` VIEW** to include the new column.

### 0-B: `checkpoint_version`
- `CHECKPOINT_VERSION = 2` in `pipeline/state_manager.py`.
- On checkpoint read: if `version` absent or `!= CHECKPOINT_VERSION`, discard and start fresh. Log at WARNING level: `"checkpoint_discarded: version mismatch — deliberate state flush"`.
- **Intentional side effect:** On first restart after Phase 0 deploy, Kalman state, tod_priors, and setup_last_fire evaporate. This is correct — they were computed on the contaminated pipeline. Fresh state is preferable to poisoned state.

### 0-C: `SIGNAL_SCHEMA_VERSION` bump — DEFERRED to end of Phase 1
**Moved from Phase 0.** Bumping this version immediately affects `signal_replay_auditor.py`'s query gate (`signal_schema_version = $1`) — existing unresolved pending/active signals with the old version stop being replayed. This is a breaking behavior change. Bump `SIGNAL_SCHEMA_VERSION` atomically with the last Phase 1 logic fix, not in Phase 0.

**Transition window gap:** Between Phase 0 deploy and the eventual schema version bump, new signals are generated with the old `signal_schema_version`. When the bump fires, these in-flight signals become invisible to the replay auditor. At bump time, log `SELECT COUNT(*) FROM signal_ledger WHERE signal_schema_version = $old AND exit_at IS NULL` and route any such active signals to replay auditor explicitly rather than letting them expire silently via version gate.

### 0-D: `setup_performance` reset
Execute at Phase 0 deploy (same atomic commit as 0-A):
```sql
UPDATE setup_performance SET perf_multiplier = 1.0, sample_size = 0
WHERE signal_schema_version < $new_version OR signal_schema_version IS NULL;
```
Rationale: `setup_performance` contains outcomes from all three contamination bugs. Version filters (4-C) only prevent new contaminated outcomes from mixing — they don't retroactively clean existing rows that already have `sample_size >= 30`. Resetting to `perf_multiplier = 1.0` (neutral) ensures the warm-up penalty in 2-C applies to all setups uniformly at boot, and ranking is clean from the first clean outcomes. Accept 2-C warm-up penalties on all setups during the 30-day clean accumulation window.

**Phase 0 deliverable:** Single commit. Four intentional effects: version marker in DB, checkpoint flush on next restart, `setup_performance` reset to neutral, signal schema version bump deferred.

---

## Phase 1 — Critical Logic Fixes

### 1-A: Calibration routing — Design B (confirmed)

The calibrator trains on `cis_score AS confidence` (`confidence_calibrator.py:74`). Design B is the correct architecture. Per-signal `apply_calibration` is applying a CIS-trained isotonic curve to per-plugin confidence values — a category error, not an ordering bug.

**Fix:**
- Remove the `apply_calibration(tod_adjusted, ...)` call from `SignalProcessor.process()`.
- In `CISScorer.score()`: after Kalman filtering, apply `apply_calibration` to `filtered_cis`. Expose `calibrated_cis` on the CIS result object.
- Stamp `calibrated_confidence` on the winner signal from `cis_result.calibrated_cis`, not from per-signal isotonic transform.
- Update `TransformRecorder` dag_order values to reflect the new stage order (no calibration step in per-signal chain).
- Update `Files Changed` entry: `calibrator.py` is no longer modified for per-signal logic; `cis_scorer.py` is added.

**Verification:** After fix, `SELECT AVG(calibrated_confidence), STDDEV(calibrated_confidence) FROM intelligence_features WHERE feature_schema_version >= 2 LIMIT 10000`. Expected: tighter distribution, better separation between winning and losing setups in CIS deciles. Compare ECE (expected calibration error) pre- vs. post-fix using `confidence_calibrator.py`'s `_compute_ece()`.

### 1-B: Minimum confidence floor — empirically derived, not hardcoded

**Bug:** Quality gate applies multipliers but never rejects. Signals with near-zero post-multiplier confidence consume downstream compute and pollute training labels.

**Fix protocol:**
1. Query: `SELECT FLOOR(confidence*10)/10 AS bucket, COUNT(*), AVG(CASE WHEN outcome IN ('target_1_hit','target_1_2_hit','target_full_hit') THEN 1.0 ELSE 0.0 END) AS win_rate FROM signal_ledger WHERE signal_schema_version = $current GROUP BY 1 ORDER BY 1`. Find the lowest confidence bucket where `win_rate >= 0.50` — the floor is set just below the first bucket with positive expected value. The cutoff is 0.50 (below random, not 0.45 — in a futures system where signal edge is 2–5%, 0.45 retains signals with measurably negative expected value).
2. Set `SIGNAL_MIN_PUBLISHABLE_CONFIDENCE` setting to that value (expected ~0.10–0.20).
3. In `apply_quality_gate`: after all multipliers, drop signals below this threshold. Return dropped count to OTel counter `intelligence_pipeline_quality_floor_rejections_total`.
4. If insufficient historical data (< 500 outcomes), default to 0.12 with a log warning that the floor is using the pre-analysis default. Do not set this value by intuition — the query result governs.

### 1-C: Field alias validation at startup

**Bug:** `_build_features_from_event` manually aliases `bb_middle`, `bb_upper`, `bb_lower` to `bb_20_2_mid`, `bb_20_2_upper`, `bb_20_2_lower`. Schema rename silently produces `None` in I7 feature dicts.

**Fix:** Replace inline assignments with a module-level map:
```python
_I1_ALIAS_MAP: dict[str, str] = {
    "bb_middle": "bb_20_2_mid",
    "bb_upper": "bb_20_2_upper",
    "bb_lower": "bb_20_2_lower",
}
```
At module import, assert every source key exists in `I1Indicators.model_fields`. Crash at startup if stale. Apply aliases via loop, not three separate lines.

### 1-D: PERF-03 migration completion — opt-in class attribute

**Bug:** Legacy plugins read `self._state` (empty dict from construction) instead of the `state=` parameter passed by the executor. Feature vectors for these plugins are permanently cold-start.

**Fix mechanism (replaces the unimplementable grep-assertion):**
1. Add `_state_migration_complete: ClassVar[bool] = False` to `PatternPlugin` base class.
2. PERF-03-compliant plugins (those that use the `state=` parameter correctly) set `_state_migration_complete = True`.
3. `PluginExecutor.__init__`: hard crash at startup for any incremental plugin that has not confirmed migration. Use a named error — not `assert all(...)` (opaque crash):
   ```python
   incomplete = [
       n for n in incremental_names
       if not getattr(self._plugin_cache.get(n), "_state_migration_complete", False)
   ]
   if incomplete:
       raise RuntimeError(f"PERF-03 migration incomplete for plugins: {incomplete}")
   ```
4. Audit and migrate all remaining non-compliant plugins before Phase 1 ships.

### 1-E: Dead code removal and circuit breaker enablement

- **`_health_monitor_loop`:** Replace the empty stub with real monitoring: emit `intelligence_pipeline_worker_queue_depth_max` (max across all per-key queues) and `intelligence_pipeline_per_key_worker_count` gauges every 10 seconds.
- **Circuit breakers:** Enable with conservative parameters: `failure_threshold=10, timeout_sec=60`. Rationale: threshold=3 (current shadow default) would trip on transient bad bars; 10 requires a genuinely broken plugin. timeout=60s means a broken plugin retries after 1 minute, not 5. Monitor for 48h after enabling before tightening thresholds.
- **`dag.py`:** No action — file does not exist in `src/intelligence/pipeline/`. Replace with inline dependency comments on `_ANALYSIS_WAVES` (see 2-A).

### 1-F: `long_bias` default — remove unexamined directional asymmetry

**Bug:** `long_bias=True` in `select_winner` default (`signal_processor.py:435` via `settings.winner_long_bias` which does not exist on `Settings`, falling through to `True`) causes systematic long selection on direction ties. No empirical basis for this bias in a futures system that trades both directions.

**Fix:** Change default to `long_bias=False`. On tie, `_aggregate_fallback` selects the signal with the highest `adjusted_rank` from all active signals regardless of direction. As tiebreaker within equal `adjusted_rank` (all setups at warm-up penalty 0.5), use `confidence` as secondary sort: `sorted(active, key=lambda s: (-s.get("adjusted_rank", 0), -s.get("confidence", 0)))`. This prevents undefined ordering via dict hash.

**Coordination requirement:** 1-F and 2-C (SETUP_PRIORITY removal) must ship atomically. After 2-C, `adjusted_rank = perf_multiplier` with no priority component. The tiebreak behavior above only makes sense when both changes are live.

### 1-G: Signal lifecycle — CONCERN-02 (mutable dicts)

**Bug:** `sig["status"] = ACTIVE` (`signal_tracker.py:758`) and `sig["market_entry_price"] = 0` (`signal_tracker.py:657`) mutate canonical dicts in `_active_index`. These mutations are load-bearing — `evaluate_signal` reads `signal.get("status")` from `sig_with_extras`.

**Fix:**
- Add `status: str`, `market_entry_price: float` to `SignalState`. Initialize from canonical dict in `_add_to_active_index`.
- In `_evaluate_bar`: read `state.status` and `state.market_entry_price` instead of mutating `sig`.
- Inject all state that `evaluate_signal` reads into `sig_with_extras` — keep the injection point the single source of truth:
  ```python
  sig_with_extras = {
      **sig,
      "status": state.status,
      "market_entry_price": state.market_entry_price,
      "staleness_consecutive": state.staleness_consecutive,
      "active_bars_elapsed": state.active_bars_elapsed,
      "point_value": ...,
      "bars_elapsed": ...,
  }
  ```
- Remove the two direct dict mutations. Canonical dicts in `_active_index` are read-only after ingestion.
- **Contract note:** `evaluate_signal` in `lifecycle_tracker.py` must continue to read these fields from the signal dict passed to it — satisfied by injecting via `sig_with_extras`. Do not split reads between `sig` and `state` directly in `_evaluate_bar`.

### 1-H: Signal lifecycle — CONCERN-06 (backfill outcome bias)

**Bug:** Fast-path unconditionally labels `ttl_expired_behind` for all TTL-elapsed signals. Backfill signals may have hit targets or stops during the historical period.

**Fix:** In `_ingest_signal`, when TTL is elapsed:
- `canonical["is_backfill"] is True` → add to `_signal_ids` (dedup only), do NOT publish EXIT, do NOT add to active index. `SignalReplayAuditor` picks these up via `exit_at IS NULL AND expires_at < NOW() AND is_backfill = TRUE` and evaluates bar-by-bar against `market_data_ohlcv`.
- `is_backfill is False` → existing `ttl_expired_behind` behavior is correct. Live signals that expired during downtime have no historical OHLCV window for replay.
- Add `SIGNAL_TRACKER_BACKFILL_ROUTED_TO_REPLAY_TOTAL` counter for observability.

### 1-I: Signal lifecycle — MAE/MFE persistence on restart

**Bug:** Running MAE/MFE for active signals is lost on every restart. Exit outcome accuracy degrades for signals that survive a restart.

**Fix:**
- Add `MAE_MFE_UPDATE` to `TransitionType` enum in `lifecycle_transitions.py`.
- In `_evaluate_bar`: publish `MAE_MFE_UPDATE` when `abs(state.mae) > 0.05 or abs(state.mfe) > 0.05` AND every 10 active bars (whichever triggers first). Data payload: `{signal_id, mae, mfe}`.
- `LifecycleWriter._flush_batch`: handle `mae_mfe_update` group — `UPDATE signal_outcomes SET mae=$2, mfe=$3 WHERE signal_id=$1::uuid AND exit_at IS NULL`.
- Bootstrap query: add `so.mae, so.mfe` from `signal_outcomes` JOIN. `_add_to_active_index` initializes `state.mae` and `state.mfe` from bootstrapped values.
- **`_TIMESTAMP_FIELDS` in lifecycle_writer.py**: MAE_MFE_UPDATE payload has no timestamp fields — no update needed.

### 1-J: Signal lifecycle — regime cache cold-start

**Bug:** `_regime_cache` empty after restart → `regime_drift=0.0` for unknown warm-up window → staleness exits suppressed.

**Fix:** Bootstrap query seeds `_regime_cache[(symbol, tf)]` using `hmm_regime_at_fire` and `garch_sigma_at_fire` from `signal_ledger_full` for each distinct `(symbol, timeframe)` in the bootstrapped signal set. This is fire-time regime (coarse approximation), not current regime — the cache self-corrects on first `i7.signals` message. Better than zero.

---

## Phase 2 — Architecture

### 2-A: Wave topology — documentation + regression test (not runtime enforcement)

**Bug:** `_ANALYSIS_WAVES` has no dependency declarations. Same-wave peer reads are undetectable at startup.

**Pragmatic fix (replaces the unimplementable `WAVE_DEPENDENCY_RULES` constant):**
1. Add inline dependency comments to each wave entry in `_ANALYSIS_WAVES`:
   ```python
   # Wave 1: reads only I1 output — I2-A, I3, SMC-A are fully independent
   # Wave 2: reads I1+I3+SMC-A — I4-A needs I3 structure data
   # Wave 3: reads I1+I2+I3+I4-A+SMC — kalman(I4-B) after garch(I4-A); I5 reads all
   # Wave 4: reads all prior tiers — I6 cross-timeframe confluence
   ```
2. Add regression test `test_wave_isolation.py`: run each wave tier in isolation (only I1 in frames) and assert outputs are identical to running with full prior-wave context. Any wave that produces different outputs in isolation has an undeclared same-wave peer dependency.

### 2-B: `frames["features"]` dual-write elimination

**Fix:**
1. Grep all I2-I7 plugins for `frames.get("features"` or `features.get(` with a flat key.
2. Migrate each to typed tier access: `frames.get("i3", {}).get("swing_high")` etc.
3. Remove the `frames.setdefault("features", {}); features.update(tier_output)` lines in `run_tiers`.
4. Add `test_no_legacy_features_access.py` that asserts no plugin source file contains the string `frames.get("features"`.

### 2-C: `SETUP_PRIORITY` → data-driven ranking with warm-up penalty

**Fix:**
- Remove `SETUP_PRIORITY` static dict entirely from `aggregator.py` and `ranker.py`.
- Ranking formula: `adjusted_rank = perf_multiplier` where `perf_multiplier` comes from `setup_performance` DB table.
- **Warm-up penalty (new):** For setups with `sample_size < 30`, use `perf_multiplier = 0.5` (below neutral, not 1.0). Unvalidated setups must earn their ranking through outcomes. The gate is `sample_size >= 30` AND `bootstrap_ci_lower(pnl_r) > 0.0` for above-neutral ranking.
- Remove `TREND_SETUPS` frozenset — Hurst quality routing uses `plugin.regime_type` attribute directly.
- `CONCERN-04` assertion (`set(SETUP_PRIORITY.keys()) == set(TIER_I7_names)`) replaces with `set(TIER_I7).issubset(set(p.name for p in all_plugins))`.
- **Ships atomically with 1-F** — the `long_bias=False` tiebreak (1-F) relies on `adjusted_rank` without a priority component, which only holds after this change is live.

### 2-D: ~~Soft regime gate~~ — NOT NEEDED

`regime_gate.py` already implements a three-band soft gate with Shannon entropy attenuation (`_entropy_multiplier()`). The bug described here does not exist in the current code. Do not implement.

### 2-E: Per-key queue depth metric

In `PerKeyWorkerManager.enqueue()`: every 10th call, emit `max(q.qsize() for q in self._queues.values())` as OTel gauge `intelligence_pipeline_worker_queue_depth_max`. Also emit `len(self._queues)` as `intelligence_pipeline_per_key_worker_count`. SLO alert: queue depth > 50% of `queue_maxsize`.

### 2-F: CONCERN-03 — dual consumer race mitigation

Change signal consumer `auto_offset_reset` from `"latest"` to `"earliest"`. The `_signal_ids` dedup set (populated from bootstrap) makes re-consumed known signals harmless. This closes the gap where a signal was consumed and committed by the prior session but not yet persisted to DB.

**Retention boundary:** `_signal_ids` dedup protects against re-consuming messages still in the Redpanda topic. Signals that were generated before Redpanda's retention window are not present in the topic at all, regardless of offset reset — they survive only via DB bootstrap. This change is correct and safe within the retention window; it does not extend protection beyond it.

Full single-consumer fan-out redesign remains a future architectural item.

### 2-G: OutputQueue — weighted-fair-queue to prevent journal starvation

**Bug:** "process high-priority first" with no rate guarantee starves journal under sustained load.

**Fix:** Implement weighted-fair-queue in `OutputQueue.drain_loop`:
- Maintain two queues: `_high_queue` (intelligence, signals, winners) and `_low_queue` (journal).
- Drain ratio: 5 high-priority items per 1 low-priority item (configurable via `OUTPUT_QUEUE_DRAIN_RATIO` setting, default 5). Start at 5:1; tune based on observed journal lag from `intelligence_pipeline_journal_drop_total` counter after 2-E metrics are live. Do not guess at the ratio — derive it from measured throughput.
- If `_high_queue` is empty, drain from `_low_queue` freely.
- Journal enqueue: `priority=LOW`, timeout=1.0s, drop on timeout with counter `intelligence_pipeline_journal_drop_total`.
- Winner/signal/intel enqueues: `priority=HIGH`, timeout=5.0s.

---

## Phase 3 — Latency

### 3-A: Fast-path protocol for trivial plugins

**Fix:** Add `fast_path: ClassVar[bool] = False` to `PatternPlugin` base. In `run_i1` and `run_tier`: fast-path plugins execute synchronously in the event loop (no `run_in_executor`). Candidate criteria: `fast_path=True` requires `supports_incremental=False` AND P99 latency < 100µs verified from `intelligence_pipeline_plugin_duration_ms` histogram over 24h. Mark candidates tentatively, verify metric, then set attribute. Do NOT mark fast-path without metric verification.

### 3-B: Serialization fix + lazy intel topic enqueue

Primary change: fix the nested JSON anti-pattern. Change `{"event": fp_result.event.model_dump_json()}` to `fp_result.event.model_dump(mode="json")` — eliminates double-deserialize at every consumer, consistent with journal serialization. This applies on every bar regardless of signal presence.

Secondary change: move the `intel_topic` enqueue from before I7 to after `_sig_proc.process()` completes in `_process_bar_compute`. Eliminates one `model_dump(mode="json")` call per no-signal bar. Precondition: verify no consumer reads the intel event to augment signal metadata before signals are published — if any such dependency exists, this move creates a race condition.

### 3-C: Batch output enqueues

Replace 4 sequential `enqueue_blocking` calls with a single `enqueue_many` that submits all non-None payloads as a list. Journal always uses LOW priority (2-G). Collect payloads first, then one await.

### 3-D: Per-tier deadline budgets — non-stateful carry-forward only

**Fix:** Add `TIER_BUDGET_MS: dict[str, float]` config. On deadline miss:
- **Non-stateful plugins** (`supports_incremental=False`): carry forward previous bar's output, increment `intelligence_pipeline_tier_deadline_exceeded_total{tier}`.
- **Stateful plugins** (GARCH, Kalman, HMM — `supports_incremental=True`): do NOT carry forward stale output. State is at bar N, stale output is bar N-1 — carrying it forward desynchronizes state from output. For stateful plugins on deadline miss: run anyway, log warning, accept latency. Set `TIER_BUDGET_MS` for stateful-heavy tiers (I4) conservatively to minimize repeated misses.
- **Hard outer timeout:** Add a 500ms total budget at the `_process_bar` level. If `run_tiers()` has not completed in 500ms, publish to DLQ with reason `bar_tier_timeout` and increment `intelligence_pipeline_bar_timeout_total`. Stateful plugin state remains valid (it simply did not emit output for that bar). This prevents a runaway GARCH or HMM computation from stalling the pipeline indefinitely. 500ms is a starting point — tune from `intelligence_pipeline_pipeline_latency_ms` histogram P99.

### 3-E: Pre-compute flat feature dict

**Fix:** In `FeaturePipelineExecutor.run()`, after `IntelligenceEvent` construction, compute the flat feature dict once and store it on the result object: `fp_result.flat_features: dict`. `_build_features_from_event` in `signal_processor.py` is replaced with `fp_result.flat_features` — no `model_dump()` calls at I7 time. The `_I1_ALIAS_MAP` (1-C) is applied during this pre-computation. Do NOT store on the Pydantic model itself — add as a field on `FeaturePipelineResult` dataclass.

**Serialization boundary note:** `FeaturePipelineResult.flat_features` is a plain `dict` and is not serializable as part of the dataclass if the result ever crosses a process boundary. If `FeaturePipelineResult` is ever pickled or JSON-serialized, exclude `flat_features` or make it `field(repr=False)` with a note that it is in-process only.

---

## Phase 4 — Data Remediation

### 4-A: ML training query filters

All queries against `intelligence_features`, `signal_ledger`, `signal_outcomes` for ML training add `WHERE feature_schema_version >= 2`. Applies to: `ml_training_agent.py`, `ml_signal_training_materializer.py`, `setup_performance_updater.py` (rolling stats window), `confidence_calibrator.py` (calibration curve training).

### 4-B: Calibration curve retraining

After `feature_schema_version >= 2` accumulates ≥ 500 outcomes per `(setup_plugin, tf)` or 14 days of live data, retrain calibration curves using only clean data. Old curves remain active until new ones pass ECE validation (ECE improvement ≥ 5% vs. passthrough). Mark curves with `data_version=2` in `calibration_curves` table.

### 4-C: `setup_performance` window gate

Add `WHERE so.signal_schema_version = $current_version` to `setup_performance_updater.py` rolling stats queries. This lets the warm-up penalty in 2-C (sample_size < 30) self-resolve as clean outcomes accumulate. Combined with the 0-D reset, contaminated pre-fix outcomes are excluded and do not mix with clean outcomes during the transition window.

---

## Canonical Testing Gates

Each phase must pass its gate before the next phase ships:

| Item | Gate |
|------|------|
| Phase 0 | `SELECT COUNT(*) FROM intelligence_features WHERE feature_schema_version IS NULL` decreases monotonically after restart; existing rows remain NULL. `SELECT perf_multiplier FROM setup_performance LIMIT 1` = 1.0 for all rows |
| 1-A | `apply_calibration` not called in `SignalProcessor.process()`. Post-fix: `AVG(calibrated_confidence)` distribution narrows vs. pre-fix; ECE decreases on `feature_schema_version >= 2` data |
| 1-B | `intelligence_pipeline_quality_floor_rejections_total` counter non-zero after 1h live |
| 1-C | `python -c "from src.intelligence.pipeline.signal_processor import _I1_ALIAS_MAP"` exits 0 |
| 1-D | `pytest tests/unit/intelligence/test_perf03_migration.py` — all incremental plugins have `_state_migration_complete = True` |
| 1-G | Unit test: identity-check `_active_index` dicts before and after `_evaluate_bar` — no mutations |
| 1-H | `SELECT COUNT(*) FROM signal_ledger WHERE is_backfill=TRUE AND exit_at IS NULL AND expires_at < NOW()` decreases over replay auditor cycle |
| 2-C | `grep -r "SETUP_PRIORITY" src/ services/` returns empty |
| 3-A | `intelligence_pipeline_plugin_duration_ms` P99 for marked fast-path plugins < 100µs on live data for 24h |

---

## Migration Checklist

All migrations must update `signal_ledger_full` VIEW — this view is queried by bootstrap, replay auditor, and lifecycle writer:

```
migrations/
  add_feature_schema_version_to_intelligence_features.sql  -- nullable INTEGER
  add_feature_schema_version_to_signal_ledger.sql          -- nullable INTEGER
  update_signal_ledger_full_view.sql                       -- include new columns
  reset_setup_performance_to_neutral.sql                   -- 0-D: perf_multiplier=1.0, sample_size=0
```

---

## Files Changed (Key)

```
src/intelligence/schemas.py                              — FEATURE_SCHEMA_VERSION=2
src/intelligence/pipeline/signal_processor.py            — remove apply_calibration, alias map, stage order
src/intelligence/pipeline/quality_gate.py                — empirical confidence floor (floor at win_rate < 0.50)
src/intelligence/trading/cis_scorer.py                   — apply_calibration on CIS score (Design B)
src/intelligence/pipeline/executor.py                    — fast-path, CB enable (threshold=10), _state_migration_complete
src/intelligence/pipeline/per_key_worker_manager.py      — queue depth metrics
src/intelligence/pipeline/output_queue.py                — weighted-fair-queue (ratio configurable, default 5:1)
src/intelligence/pipeline/state_manager.py               — CHECKPOINT_VERSION=2
src/intelligence/pipeline/feature_pipeline_executor.py   — tier deadlines (+ 500ms hard outer), flat_features on result
src/intelligence/pipeline/winner_selector.py             — long_bias=False, confidence as secondary tiebreaker
src/intelligence/pipeline/ranker.py                      — SETUP_PRIORITY removed, warm-up penalty
src/intelligence/trading/aggregator.py                   — SETUP_PRIORITY removed
src/intelligence/trading/signal_schema.py                — SIGNAL_SCHEMA_VERSION bump (end of Phase 1)
src/intelligence/trading/lifecycle_transitions.py        — MAE_MFE_UPDATE transition type
src/intelligence/plugins/base.py                         — fast_path, _state_migration_complete attrs
services/intelligence_pipeline.py                        — serialization fix, batched enqueue, health loop
services/signal_tracker.py                               — CONCERN-02/06/MAE_MFE/regime_cache/CONCERN-03
services/lifecycle_writer.py                             — MAE_MFE_UPDATE flush handler
migrations/                                              — 4 files (see above)
```

---

## Non-Goals

- CONCERN-03 full architectural fix (single-consumer fan-out) — 2-F provides adequate mitigation.
- Portfolio correlation awareness — Phase 5+ requiring position state service.
- Historical data recalculation — accept contamination boundary; filter going forward.
- Carry-forward for stateful plugins on deadline miss — 3-D hard outer timeout handles the degenerate case; per-miss carry-forward would desynchronize state.
