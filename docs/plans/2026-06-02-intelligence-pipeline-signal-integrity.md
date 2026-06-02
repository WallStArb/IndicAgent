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

1. **Alpha decay before calibration** — `_apply_alpha_decay` runs before `apply_calibration` in `signal_processor.py:263`. Calibration is isotonic regression fit on `(confidence, win_label)` pairs. The input `confidence` field at training time is the plugin raw confidence. Decay reduces that value before the calibrator sees it — the calibrator is receiving a different distribution at inference than it was trained on, producing systematically distorted outputs.
2. **No quality floor** — signals below any meaningful confidence threshold have been entering `signal_ledger` as valid training labels, polluting `setup_performance` and ML training datasets with noise.
3. **PERF-03 incomplete** — legacy plugins use a cold-start `_state` on every bar. Feature vectors for those plugins are wrong, meaning I7 signals downstream of them carry incorrect inputs.

**Critical pre-condition (see DEFECT-1 resolution below):** Before implementing the alpha decay fix, confirm what value the calibration curves were actually trained on. `confidence_calibrator.py:75` trains on `cis_score AS confidence`. If this is the bar-level CIS aggregate rather than per-signal plugin confidence, then `apply_calibration` in the pipeline is being fed the wrong input entirely — and the fix is to route calibration to CIS scores, not to reorder alpha decay.

---

## Calibration Design Intent (must resolve before Phase 1-A)

Two possible correct designs:

**Design A (current intent assumed in spec):** Calibration is per-signal, trained on plugin `confidence` values. The bug is alpha decay running before calibration. Fix: move alpha decay after calibration. Requires retraining calibration curves on raw `confidence` (not `cis_score`) if training was done incorrectly.

**Design B (what the training query actually does):** Calibration is trained on `cis_score`. The correct architecture is: per-signal confidence flows through quality gate → regime gate → ranking only. CIS score is calibrated separately. `apply_calibration` per-signal with cis_score-trained curves is applying the wrong transform to the wrong input. Fix: remove `apply_calibration` from the per-signal pipeline; apply calibration only to the CIS score in `CISScorer`.

Before implementing 1-A, query: `SELECT COUNT(*) FROM signal_ledger WHERE calibrated_confidence IS NOT NULL` and cross-reference with `confidence_calibrator.py:75` to determine which design the system was built for. This decision gates everything in section 1-A.

---

## Canonical Pipeline Stage Order (post all Phase 1+2 changes)

The complete ordered stage list after all changes. This is the authoritative reference — any implementation that deviates from this order is wrong:

```
raw_signals (from I7 plugins)
  ↓ 1. alpha_decay          — penalizes repeated fires (uses setup_last_fire)
  ↓ 2. quality_gate         — applies Hurst×entropy multiplier; drops below min_confidence
  ↓ 3. regime_gate_soft     — multiplies confidence by hmm_prob_in_favorable_regime (≥0.0)
  ↓ 4. calibration          — isotonic transform per (plugin, tf, symbol) [see DEFECT-1 resolution]
  ↓ 5. tod_adjustment       — time-of-day prior multiplier
  ↓ 6. ranking              — adjusted_rank = perf_multiplier (data-driven, no SETUP_PRIORITY)
  ↓ 7. winner_selection     — CIS override or priority/majority fallback
```

**Note on ordering:** Alpha decay (step 1) now runs BEFORE calibration (step 4). This means calibration receives the decayed value. If Design A is confirmed, this is correct — we want calibration to map `(decayed_confidence → calibrated_confidence)`. Quality floor check in step 2 uses the decayed, quality-multiplied value. Regime soft multiplier (step 3) runs after the quality floor — a signal that passes the floor may still be reduced by the regime multiplier but is NOT re-checked against the floor afterward. This is intentional: the floor gates on signal quality, the regime multiplier gates on market context.

---

## Phase 0 — Forensic Boundary Prep

**What this phase is:** A deliberate state flush and version marker commit. It is NOT "no behavior changes" — it has three intentional side effects documented below. Must ship as a single atomic commit before any logic fix.

### 0-A: `feature_schema_version`
- `FEATURE_SCHEMA_VERSION = 2` (starts at 2; all pre-fix rows have NULL = tainted by convention — no backfill).
- Add to `IntelligenceEvent` as `feature_schema_version: int = FEATURE_SCHEMA_VERSION`.
- Migration: add `feature_schema_version INTEGER` to `intelligence_features` (nullable, no default — old rows stay NULL).
- Also add to `signal_ledger` as `feature_schema_version INTEGER` (signals reference the features that generated them).
- **Training filter going forward:** `WHERE feature_schema_version = 2` (not `>= 2` — exact version match prevents accidentally including future-version rows in a backward-incompatible training query).
- **Migration must update `signal_ledger_full` VIEW** to include the new column.

### 0-B: `checkpoint_version`
- `CHECKPOINT_VERSION = 2` in `pipeline/state_manager.py`.
- On checkpoint read: if `version` absent or `!= CHECKPOINT_VERSION`, discard and start fresh. Log at WARNING level: `"checkpoint_discarded: version mismatch — deliberate state flush"`.
- **Intentional side effect:** On first restart after Phase 0 deploy, Kalman state, tod_priors, and setup_last_fire evaporate. This is correct — they were computed on the contaminated pipeline. Fresh state is preferable to poisoned state.

### 0-C: `SIGNAL_SCHEMA_VERSION` bump — DEFERRED to end of Phase 1
**Moved from Phase 0.** Bumping this version immediately affects `signal_replay_auditor.py`'s query gate (`signal_schema_version = $1`) — existing unresolved pending/active signals with the old version stop being replayed. This is a breaking behavior change. Bump `SIGNAL_SCHEMA_VERSION` atomically with the last Phase 1 logic fix, not in Phase 0.

**Phase 0 deliverable:** Single commit. Three intentional effects: version marker in DB, checkpoint flush on next restart, signal schema version bump deferred.

---

## Phase 1 — Critical Logic Fixes

### 1-A: Alpha decay position (Design A confirmed) OR calibration routing (Design B confirmed)

**If Design A:** Move `_apply_alpha_decay` call in `SignalProcessor.process()` to after `apply_calibration`. Per the canonical stage order above, alpha decay now feeds into calibration (step 1 → step 4). Update `TransformRecorder` dag_order values for all stages to match canonical order. Retrain calibration curves on raw plugin `confidence` if historical training used pre-decay values.

**If Design B:** Remove `apply_calibration` from the per-signal pipeline in `SignalProcessor.process()`. Apply calibration to CIS score inside `CISScorer.score()`. Update `TransformRecorder` to record the CIS calibration step. Per-signal `calibrated_confidence` field is populated from the CIS-calibrated direction confidence, not from isotonic per-signal curves.

**Verification:** After fix, query `SELECT AVG(calibrated_confidence), STDDEV(calibrated_confidence) FROM intelligence_features WHERE feature_schema_version = 2 LIMIT 10000` and compare to the pre-fix distribution. Expected: tighter distribution (lower variance), better separation between winning and losing setups in confidence deciles.

### 1-B: Minimum confidence floor — empirically derived, not hardcoded

**Bug:** Quality gate applies multipliers but never rejects. Signals with near-zero post-multiplier confidence consume downstream compute and pollute training labels.

**Fix protocol (do not hardcode 0.15):**
1. Query: `SELECT FLOOR(confidence*10)/10 AS bucket, COUNT(*), AVG(CASE WHEN outcome IN ('target_1_hit','target_1_2_hit','target_full_hit') THEN 1.0 ELSE 0.0 END) AS win_rate FROM signal_ledger WHERE signal_schema_version = $current GROUP BY 1 ORDER BY 1`. Find the confidence bucket where `win_rate` drops below 0.45 (near-random).
2. Set `SIGNAL_MIN_PUBLISHABLE_CONFIDENCE` setting to that value (expected ~0.10–0.20).
3. In `apply_quality_gate`: after all multipliers, drop signals below this threshold. Return dropped count to OTel counter `intelligence_pipeline_quality_floor_rejections_total`.
4. If insufficient historical data (< 500 outcomes), default to 0.12 with a log warning that the floor is using the pre-analysis default.

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
3. `PluginExecutor.__init__`: `assert all(getattr(p, "_state_migration_complete", False) for p in [self._plugin_cache[n] for n in TIER_I1 + ... if getattr(self._plugin_cache.get(n), "supports_incremental", False)])`. Hard crash at startup for any incremental plugin that has not confirmed migration.
4. Audit and migrate all remaining non-compliant plugins before Phase 1 ships.

### 1-E: Dead code removal and circuit breaker enablement

- **`_health_monitor_loop`:** Replace the empty stub with real monitoring: emit `intelligence_pipeline_worker_queue_depth_max` (max across all per-key queues) and `intelligence_pipeline_per_key_worker_count` gauges every 10 seconds.
- **Circuit breakers:** Enable with conservative parameters: `failure_threshold=10, timeout_sec=60`. Rationale: threshold=3 (current shadow default) would trip on transient bad bars; 10 requires a genuinely broken plugin. timeout=60s means a broken plugin retries after 1 minute, not 5. Monitor for 48h after enabling before tightening thresholds.
- **`dag.py`:** Delete. Replace with explicit inline dependency comments on `_ANALYSIS_WAVES` (see 2-A).

### 1-F: `long_bias` default — remove unexamined directional asymmetry

**Bug:** `long_bias=True` in `select_winner` default causes systematic long selection on direction ties. No empirical basis for this bias in a futures system that trades both directions.

**Fix:** Change default to `long_bias=False`. On tie: select highest `adjusted_rank` regardless of direction. Document: "tie-breaking is direction-neutral by default; CIS score is the correct tie-breaker when signals are otherwise equal."

### 1-G: Signal lifecycle — CONCERN-02 (mutable dicts)

**Bug:** `sig["status"] = ACTIVE` (line 757) and `sig["market_entry_price"] = 0` (line 657) mutate canonical dicts in `_active_index`. These mutations are load-bearing — `evaluate_signal` reads `signal.get("status")` from `sig_with_extras`.

**Fix:**
- Add `status: str` and `market_entry_price: float` to `SignalState`. Initialize from canonical dict in `_add_to_active_index`.
- In `_evaluate_bar`: read `state.status` and `state.market_entry_price` instead of `sig["status"]` and `sig["market_entry_price"]`.
- Inject into `sig_with_extras`: `sig_with_extras = {**sig, "status": state.status, "market_entry_price": state.market_entry_price, "point_value": ..., "bars_elapsed": ...}`.
- Remove the two direct dict mutations. Canonical dicts in `_active_index` are read-only after ingestion.
- **Contract note:** `evaluate_signal` in `lifecycle_tracker.py` must continue to read `status` from the signal dict passed to it — this is satisfied by injecting via `sig_with_extras`.

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
- Remove `SETUP_PRIORITY` static dict entirely from `aggregator.py`.
- Ranking formula: `adjusted_rank = perf_multiplier` where `perf_multiplier` comes from `setup_performance` DB table.
- **Warm-up penalty (new):** For setups with `sample_size < 30`, use `perf_multiplier = 0.5` (below neutral, not 1.0). Unvalidated setups must earn their ranking through outcomes. The gate is `sample_size >= 30` AND `bootstrap_ci_lower(pnl_r) > 0.0` for above-neutral ranking.
- Remove `TREND_SETUPS` frozenset — Hurst quality routing uses `plugin.regime_type` attribute directly.
- `SETUP_PRIORITY` constant removed from `aggregator.py` and `ranker.py`. `CONCERN-04` assertion (`set(SETUP_PRIORITY.keys()) == set(TIER_I7_names)`) replaces with `set(TIER_I7).issubset(set(p.name for p in all_plugins))`.

### 2-D: Soft regime gate — uncertainty propagation via `hmm_regime_prob`

**Bug:** Binary suppression at regime transition boundaries. HMM uncertainty not propagated.

**Fix:** `hmm_regime_prob`, `hmm_prob_ranging`, `hmm_prob_trending_up`, `hmm_prob_trending_down` are confirmed present in `hmm_regime.py:406-409`. In `apply_regime_gate`:
- For trend plugins: `favorable_prob = hmm_prob_trending_up + hmm_prob_trending_down`
- For mean_reversion plugins: `favorable_prob = hmm_prob_ranging`
- For `any` plugins: `favorable_prob = 1.0` (no suppression)
- Apply: `signal["confidence"] = round(signal["confidence"] * favorable_prob, 4)`
- Keep hard suppression only when `favorable_prob == 0.0` (regime is certain and unfavorable).
- Update `regime_eligible` flag: set to `True` for all signals (remove binary flag); downstream `select_winner` already reads active vs. suppressed — update logic to use `favorable_prob < 0.05` as the suppression threshold.

### 2-E: Per-key queue depth metric

In `PerKeyWorkerManager.enqueue()`: every 10th call, emit `max(q.qsize() for q in self._queues.values())` as OTel gauge `intelligence_pipeline_worker_queue_depth_max`. Also emit `len(self._queues)` as `intelligence_pipeline_per_key_worker_count`. SLO alert: queue depth > 50% of `queue_maxsize`.

### 2-F: CONCERN-03 — dual consumer race mitigation

Change signal consumer `auto_offset_reset` from `"latest"` to `"earliest"`. The `_signal_ids` dedup set (populated from bootstrap) makes re-consumed known signals harmless. This closes the gap where a signal was consumed and committed by the prior session but not yet persisted to DB. Full single-consumer fan-out redesign remains a future architectural item.

### 2-G: OutputQueue — weighted-fair-queue to prevent journal starvation

**Bug:** "process high-priority first" with no rate guarantee starves journal under sustained load.

**Fix:** Implement weighted-fair-queue in `OutputQueue.drain_loop`:
- Maintain two queues: `_high_queue` (intelligence, signals, winners) and `_low_queue` (journal).
- Drain ratio: 10 high-priority items per 1 low-priority item. If `_high_queue` is empty, drain from `_low_queue` freely.
- Journal enqueue: `priority=LOW`, timeout=1.0s, drop on timeout with counter `intelligence_pipeline_journal_drop_total`.
- Winner/signal/intel enqueues: `priority=HIGH`, timeout=5.0s.

---

## Phase 3 — Latency

### 3-A: Fast-path protocol for trivial plugins

**Fix:** Add `fast_path: ClassVar[bool] = False` to `PatternPlugin` base. In `run_i1` and `run_tier`: fast-path plugins execute synchronously in the event loop (no `run_in_executor`). Candidate criteria: `fast_path=True` requires `supports_incremental=False` AND P99 latency < 100µs verified from `intelligence_pipeline_plugin_duration_ms` histogram over 24h. Mark candidates tentatively, verify metric, then set attribute. Do NOT mark fast-path without metric verification.

### 3-B: Lazy `model_dump_json()` — defer intel topic enqueue

Move the `intel_topic` enqueue from before I7 to after `_sig_proc.process()` completes in `_process_bar_compute`. The intelligence event topic has no consumers that depend on receiving the event before signals — all consumers are downstream of signal processing. This eliminates one `model_dump_json()` call per no-signal bar. Also fix the nested JSON anti-pattern: change `{"event": fp_result.event.model_dump_json()}` to `fp_result.event.model_dump(mode="json")` — consistent with journal serialization and eliminates double-deserialize at consumers.

### 3-C: Batch output enqueues

Replace 4 sequential `enqueue_blocking` calls with a single `enqueue_many` that submits all non-None payloads as a list. Journal always uses LOW priority (2-G). Collect payloads first, then one await.

### 3-D: Per-tier deadline budgets — non-stateful carry-forward only

**Fix:** Add `TIER_BUDGET_MS: dict[str, float]` config. On deadline miss:
- **Non-stateful plugins** (`supports_incremental=False`): carry forward previous bar's output, increment `intelligence_pipeline_tier_deadline_exceeded_total{tier}`.
- **Stateful plugins** (GARCH, Kalman, HMM — `supports_incremental=True`): do NOT carry forward stale output. Carrying forward stale output while state has advanced creates a state/output desynchronization — state is at bar N, output is at bar N-1, next bar receives wrong context. For stateful plugins on deadline miss: run anyway, log warning, accept the latency hit. The deadline budget for stateful-heavy tiers (I4) should be set conservatively to avoid repeated misses.

### 3-E: Pre-compute flat feature dict

**Fix:** In `FeaturePipelineExecutor.run()`, after `IntelligenceEvent` construction, compute the flat feature dict once and store it on the result object: `fp_result.flat_features: dict`. `_build_features_from_event` in `signal_processor.py` is replaced with `fp_result.flat_features` — no `model_dump()` calls at I7 time. The `_I1_ALIAS_MAP` (1-C) is applied during this pre-computation. Do NOT store on the Pydantic model itself — add as a field on `FeaturePipelineResult` dataclass.

---

## Phase 4 — Data Remediation

### 4-A: ML training query filters

All queries against `intelligence_features`, `signal_ledger`, `signal_outcomes` for ML training add `WHERE feature_schema_version = 2`. Applies to: `ml_training_agent.py`, `ml_signal_training_materializer.py`, `setup_performance_updater.py` (rolling stats window), `confidence_calibrator.py` (calibration curve training).

### 4-B: Calibration curve retraining

After `feature_schema_version=2` accumulates ≥500 outcomes per `(setup_plugin, tf)` or 14 days of live data, retrain calibration curves using only clean data. Old curves remain active until new ones pass ECE validation (ECE improvement ≥ 5% vs. passthrough). Mark curves with `data_version=2` in `calibration_curves` table.

### 4-C: `setup_performance` window gate

Add `WHERE so.signal_schema_version = $current_version` to `setup_performance_updater.py` rolling stats queries. This lets the warm-up penalty in 2-C (sample_size < 30) self-resolve as clean outcomes accumulate. Old contaminated outcomes fall out of the 30-day window naturally; the gate ensures new clean outcomes aren't mixed with pre-fix ones during the transition window.

---

## Canonical Testing Gates

Each phase must pass its gate before the next phase ships:

| Item | Gate |
|------|------|
| Phase 0 | `SELECT COUNT(*) FROM intelligence_features WHERE feature_schema_version IS NULL` decreases monotonically after restart; existing rows remain NULL |
| 1-A | Confirm Design A vs B. Post-fix: `AVG(calibrated_confidence)` distribution narrows; P(win \| conf>0.7) increases |
| 1-B | `intelligence_pipeline_quality_floor_rejections_total` counter non-zero after 1h live |
| 1-C | `python -c "from src.intelligence.pipeline.signal_processor import _I1_ALIAS_MAP"` exits 0 |
| 1-D | `pytest tests/unit/intelligence/test_perf03_migration.py` — all incremental plugins have `_state_migration_complete = True` |
| 1-G | Unit test: identity-check `_active_index` dicts before and after `_evaluate_bar` — no mutations |
| 1-H | `SELECT COUNT(*) FROM signal_ledger WHERE is_backfill=TRUE AND exit_at IS NULL AND expires_at < NOW()` decreases over replay auditor cycle |
| 2-C | `SETUP_PRIORITY` symbol not imported anywhere: `grep -r "SETUP_PRIORITY" src/ services/` returns empty |
| 2-D | Regime gate unit tests: trend signal at hmm_prob_ranging=0.6 gets `confidence *= 0.4` not full suppression |
| 3-A | `intelligence_pipeline_plugin_duration_ms` P99 for marked fast-path plugins < 100µs on live data for 24h |

---

## Migration Checklist

All migrations must update `signal_ledger_full` VIEW — this view is queried by bootstrap, replay auditor, and lifecycle writer:

```
migrations/
  add_feature_schema_version_to_intelligence_features.sql  -- nullable INTEGER
  add_feature_schema_version_to_signal_ledger.sql          -- nullable INTEGER
  update_signal_ledger_full_view.sql                       -- include new columns
```

---

## Files Changed (Key)

```
src/intelligence/schemas.py                       — FEATURE_SCHEMA_VERSION=2
src/intelligence/pipeline/signal_processor.py     — decay order, alias map, stage order
src/intelligence/pipeline/quality_gate.py         — empirical confidence floor
src/intelligence/pipeline/calibrator.py           — depends on Design A/B resolution
src/intelligence/pipeline/executor.py             — fast-path, CB enable (threshold=10), _state_migration_complete
src/intelligence/pipeline/per_key_worker_manager.py — queue depth metrics
src/intelligence/pipeline/output_queue.py         — weighted-fair-queue
src/intelligence/pipeline/state_manager.py        — CHECKPOINT_VERSION=2
src/intelligence/pipeline/feature_pipeline_executor.py — tier deadlines, flat_features on result
src/intelligence/pipeline/winner_selector.py      — long_bias=False
src/intelligence/pipeline/ranker.py               — SETUP_PRIORITY removed, warm-up penalty
src/intelligence/pipeline/regime_gate.py          — soft hmm_prob multiplier
src/intelligence/trading/aggregator.py            — SETUP_PRIORITY removed
src/intelligence/trading/signal_schema.py         — SIGNAL_SCHEMA_VERSION bump (end of Phase 1)
src/intelligence/trading/lifecycle_transitions.py — MAE_MFE_UPDATE transition type
src/intelligence/plugins/base.py                  — fast_path, _state_migration_complete attrs
services/intelligence_pipeline.py                — lazy serialize, batched enqueue, health loop
services/signal_tracker.py                       — CONCERN-02/06/MAE_MFE/regime_cache/CONCERN-03
services/lifecycle_writer.py                     — MAE_MFE_UPDATE flush handler
migrations/                                      — 3 files (see above)
```

---

## Non-Goals

- CONCERN-03 full architectural fix (single-consumer fan-out) — 2-F provides adequate mitigation.
- Portfolio correlation awareness — Phase 5+ requiring position state service.
- Historical data recalculation — accept contamination boundary; filter going forward.
- Hard kill-and-carry-forward for stateful plugins on deadline miss — 3-D provides monitoring only.
