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

1. **Alpha decay before calibration** — every `calibrated_confidence` in `intelligence_features` is on the wrong side of the calibration transform. Calibration curves were fitted on pre-decay values; post-calibration scores are systematically distorted.
2. **No quality floor** — signals below any meaningful confidence threshold have been entering `signal_ledger` as valid training labels, polluting `setup_performance` and ML training datasets with noise.
3. **PERF-03 incomplete** — legacy plugins use a cold-start `_state` on every bar. Feature vectors for those plugins are wrong, meaning I7 signals downstream of them carry incorrect inputs.

**Effect:** `setup_performance` multipliers, calibration curves, and ML training labels derived from this data are unreliable. Retraining on contaminated data before establishing the version boundary will perpetuate the problem.

---

## Phase 0 — Contamination Boundary (ships first, no logic changes)

**Goal:** Create a queryable line in the DB that identifies clean vs. tainted data. This must ship before any logic fix.

### 0-A: `feature_schema_version`
- Add integer constant `FEATURE_SCHEMA_VERSION = 1` to `src/intelligence/schemas.py` (bump to 2 after all Phase 1 fixes ship).
- Embed in `IntelligenceEvent` model as `feature_schema_version: int = FEATURE_SCHEMA_VERSION`.
- Write to `intelligence_features.feature_schema_version` column (add migration).
- All ML training queries going forward: `WHERE feature_schema_version >= 2`.

### 0-B: `checkpoint_version`
- Add `CHECKPOINT_VERSION = 2` constant in `pipeline/state_manager.py`.
- On checkpoint write: embed `{"version": CHECKPOINT_VERSION, ...}`.
- On checkpoint read: if `version` absent or `< CHECKPOINT_VERSION`, discard and start fresh (log warning). Never silently restore stale state.

### 0-C: `SIGNAL_SCHEMA_VERSION` bump
- Increment `SIGNAL_SCHEMA_VERSION` in `signal_schema.py` to mark the clean-data boundary for signal training queries.

**Deliverable:** Single commit. No behavior changes. Establishes the forensic version marker.

---

## Phase 1 — Critical Logic Fixes

### 1-A: Alpha decay AFTER calibration
**File:** `src/intelligence/pipeline/signal_processor.py`
**Bug:** `_apply_alpha_decay` runs at line 263 before `apply_calibration`. Calibration curves were trained on un-decayed values.
**Fix:** Move `_apply_alpha_decay` call to after `apply_calibration` in `SignalProcessor.process()`. Update invariant comment.
**Verification:** Distribution of `calibrated_confidence` before/after fix should show reduced mean (decay was inflating post-calibration values).

### 1-B: Minimum confidence floor at quality gate
**File:** `src/intelligence/pipeline/quality_gate.py`
**Bug:** Quality gate applies multipliers but never rejects. A 0.8-confidence signal with 0.05 Hurst quality exits at 0.04 and traverses calibration, regime gate, ranking, and winner selection.
**Fix:** Add `min_publishable_confidence: float = 0.15` setting. After applying multipliers, filter out signals below threshold. Return count of filtered signals for OTel counter `intelligence_pipeline_quality_floor_rejections_total`.

### 1-C: Field alias validation at startup
**File:** `src/intelligence/pipeline/signal_processor.py:90-92`
**Bug:** `f["bb_middle"] = event.i1.bb_20_2_mid` — three manual aliases maintained by hand. If schema field is renamed, aliases silently become `None`.
**Fix:** Add a module-level `_I1_ALIAS_MAP: dict[str, str] = {"bb_middle": "bb_20_2_mid", "bb_upper": "bb_20_2_upper", "bb_lower": "bb_20_2_lower"}`. At module import, assert each source key exists in `I1Indicators.model_fields`. Hard crash at startup if mapping is stale.

### 1-D: PERF-03 migration completion
**File:** `src/intelligence/pipeline/executor.py:100-108`
**Bug:** Legacy plugins read `self._state` (always empty dict from construction) rather than the `state=` parameter. Feature vectors for these plugins are permanently cold-start.
**Fix:**
1. Audit all plugins with `supports_incremental=True` — list those still reading `self._state` internally.
2. For each: update `compute_next(frames, state)` to accept and use the `state` parameter.
3. Add startup assertion: `assert not any(plugin reads self._state in compute_next)` — enforce via test `test_no_legacy_state_reads.py` that greps for `self._state` inside `compute_next` bodies.

### 1-E: Dead code and stubs removal
- **`_health_monitor_loop`** (`intelligence_pipeline.py`): Either implement (queue depth gauge, per-key worker lag) or remove entirely. Empty `while self.running: await asyncio.sleep(10)` is false assurance.
- **Circuit breaker scan** (`_process_bar_compute:597-610`): Circuit breakers are universally `enabled=False`. The 129-plugin scan loop on every bar is pure overhead. **Option A:** Enable circuit breakers (data is already being accumulated). **Option B:** Remove scan loop until breakers are enabled. Implement Option A — the `record_failure`/`record_success` data is already correct; just set `enabled=True`.
- **`dag.py`**: Never imported. Either wire it as the authoritative topology (see Phase 2-A) or delete. Delete for now, document wave structure explicitly.

### 1-F: `long_bias` default removed
**File:** `src/intelligence/pipeline/winner_selector.py`
**Bug:** `long_bias=True` default causes systematic long selection on direction ties — an unexamined directional bias with no empirical basis.
**Fix:** Change default to `long_bias=False`. Let CIS score resolve ties. If CIS is also neutral, select highest `adjusted_rank` regardless of direction. Document rationale in code.

### 1-G: Signal lifecycle — CONCERN-02 (mutable dicts)
**File:** `services/signal_tracker.py:657, 757`
**Bug:** `sig["status"] = ACTIVE` and `sig["market_entry_price"] = 0` mutate canonical dicts in `_active_index`.
**Fix:**
- Add `status: str` and `market_entry_price: float` fields to `SignalState` dataclass.
- Initialize from canonical dict in `_add_to_active_index`.
- Remove mutations from canonical dict; read/write these fields via `state` in `_evaluate_bar`.
- Pass `state.status` and `state.market_entry_price` when building `sig_with_extras`.

### 1-H: Signal lifecycle — CONCERN-06 (backfill outcome bias)
**File:** `services/signal_tracker.py:455-467`
**Bug:** Fast-path unconditionally labels `ttl_expired_behind` for all TTL-elapsed signals, including backfill signals that may have hit targets during the historical period.
**Fix:** In `_ingest_signal`, when TTL is elapsed:
- If `canonical["is_backfill"] is True`: add to `_signal_ids` (dedup), do NOT publish EXIT transition, do NOT add to active index. The `SignalReplayAuditor` picks these up from DB via its `exit_at IS NULL AND expires_at < NOW()` query and performs proper bar-by-bar evaluation against `market_data_ohlcv`.
- If `is_backfill is False` (live signal that expired during downtime): existing `ttl_expired_behind` behavior is correct — no OHLCV to replay.

### 1-I: Signal lifecycle — MAE/MFE persistence on restart
**File:** `services/signal_tracker.py` bootstrap query
**Bug:** Running MAE/MFE for active signals is lost on restart. Bootstrap does not restore it.
**Fix:**
- Add periodic `MAE_MFE_UPDATE` transition type to `LifecycleTransition` (alongside existing `CHANDELIER_UPDATE`).
- Publish every N bars for active signals (N=10 or on significant move threshold — whichever comes first).
- Bootstrap query reads `mae`/`mfe` from `signal_outcomes` for active signals.
- `SignalState` initializes `mae`/`mfe` from bootstrap values.

### 1-J: Signal lifecycle — regime cache cold-start
**File:** `services/signal_tracker.py:690-697`
**Bug:** `_regime_cache` is empty after restart. Staleness scores use `hmm_now=None` → `regime_drift=0.0` for an unknown warm-up window.
**Fix:** Bootstrap query adds `hmm_regime_at_fire` and `garch_sigma_at_fire` from `signal_ledger_full` to seed an initial regime cache entry per `(symbol, tf)`. This is a coarse approximation (fire-time values, not current) but eliminates the cold-start zero-drift period. The cache will self-correct on the first i7.signals message.

---

## Phase 2 — Architecture

### 2-A: Wave topology explicit dependency enforcement
**File:** `src/intelligence/pipeline/executor.py:156-161`
**Current:** `_ANALYSIS_WAVES` contains groupings with no declared inter-plugin dependencies. Topology violations are silent.
**Fix:** Add a `WAVE_DEPENDENCY_RULES: dict[str, list[str]]` constant that maps each wave's tier keys to the tier keys they depend on. Add a startup assertion that validates no tier in Wave N reads outputs produced in Wave N (same-wave peer reads). This is simpler than full `dag.py` resurrection and directly closes the topology violation risk.

### 2-B: `frames["features"]` dual-write elimination
**File:** `src/intelligence/pipeline/executor.py:546-548`
**Current:** Every tier output is merged into a flat `frames["features"]` dict for legacy plugins.
**Fix:**
1. Grep all plugins for `frames.get("features", ...)` usage — list them.
2. Migrate each to typed tier access: `frames.get("i3", {}).get("key")`.
3. Remove the dual-write loop.
4. Add test `test_no_legacy_features_access.py`.

### 2-C: `SETUP_PRIORITY` → data-driven ranking
**File:** `src/intelligence/trading/aggregator.py:35-77`
**Current:** 36 priority values (1-10) are hardcoded and never updated from performance data.
**Fix:**
- Remove `SETUP_PRIORITY` static dict from aggregator.
- `rank_signals()` uses only `perf_multiplier` from `setup_performance` (already DB-sourced) multiplied by a flat default base priority of 1.0.
- For setups with `sample_size < 30` (insufficient data), use `perf_multiplier=1.0` (no ranking effect) — already the current behavior.
- For setups with sufficient data, `adjusted_rank = perf_multiplier` alone.
- Remove `TREND_SETUPS` frozenset (only used for Hurst routing which can use `regime_type` attribute directly).

### 2-D: Soft regime gate (uncertainty propagation)
**File:** `src/intelligence/pipeline/regime_gate.py`
**Current:** Binary suppression — signal is in or out based on `hmm_regime` integer.
**Fix:** Expose `hmm_regime_prob` from HMM output (the probability of the current regime state). Apply soft multiplier to signal confidence: `confidence *= hmm_prob_in_favorable_regime`. Signals in fully unfavorable regime (prob=0.0) are still suppressed. Signals at a transition boundary (prob=0.6 for trending, trend plugin) get 0.6× confidence rather than full suppression.
**Requires:** HMM plugin to expose `hmm_regime_prob` in its output dict. Verify this field exists; add it if not.

### 2-E: Per-key queue depth metric
**File:** `src/intelligence/pipeline/per_key_worker_manager.py`
**Fix:** In `enqueue()`, emit `max(q.qsize() for q in self._queues.values())` as an OTel gauge `intelligence_pipeline_worker_queue_depth_max` once per 10 enqueue calls (sample, not every call). Alert threshold: > 50% of `queue_maxsize`.

### 2-F: CONCERN-03 (dual consumer race) — mitigation
**File:** `services/signal_tracker.py:183-186`
**Current:** Signal consumer uses `auto_offset_reset="latest"` — on fresh consumer group (offset expiry or first start), signals published before startup are skipped if not yet in DB.
**Fix (pragmatic):** Change signal consumer to `auto_offset_reset="earliest"` with a `_signal_ids` dedup set that rejects already-known signal IDs. Since the dedup set is populated by bootstrap, re-consumed signals from Kafka are harmless duplicates. This closes the gap where a signal was consumed and committed by the prior session but never written to DB (still pending). Full single-consumer fan-out redesign is Phase 3+ work.

### 2-G: OutputQueue topic priority separation
**File:** `services/intelligence_pipeline.py` + `src/intelligence/pipeline/output_queue.py`
**Current:** All 4 output topics share one `OutputQueue` with equal priority. Journal topic backpressure blocks winner signals.
**Fix:** Add a `priority` parameter to `enqueue_blocking`. Journal enqueues use `priority=LOW` with a shorter timeout (1.0s, drop on timeout with counter). Winners and signals use `priority=HIGH` with the existing 5.0s timeout. Implement via two separate internal queues in `OutputQueue` with drain loop processing high-priority first.

---

## Phase 3 — Latency

### 3-A: Fast-path protocol for trivial plugins
**File:** `src/intelligence/pipeline/executor.py`
**Finding:** ~129 `run_in_executor` dispatches per bar-timeframe. Trivial plugins (AC oscillator, Williams %R, simple MAs) pay asyncio→thread context switch overhead that exceeds their actual compute.
**Fix:** Add `fast_path: bool = False` class attribute to `PatternPlugin` base. Plugins that are pure NumPy/pandas with sub-100µs deterministic compute set `fast_path=True`. In `run_i1` and `run_tier`, fast-path plugins are executed synchronously in the event loop (direct call, no executor dispatch). Estimate: 40-50 plugins qualify, reducing thread dispatch count by ~35%.

### 3-B: Lazy `model_dump_json()` — after I7, not before
**File:** `services/intelligence_pipeline.py:556-558`
**Current:** `IntelligenceEvent` is serialized to JSON string before I7 runs — wasted on bars that generate no signal.
**Fix:** Defer the `intel_topic` enqueue to after I7 and signal processing complete. No behavior change — the intelligence event topic is downstream of signal processing in every consumer. Saves one `model_dump_json()` call per no-signal bar.

### 3-C: Batch output enqueues
**File:** `services/intelligence_pipeline.py:556-611`
**Current:** 4 sequential `enqueue_blocking` calls per bar, each with 5s timeout.
**Fix:** Collect all non-None enqueue payloads into a list, submit as `enqueue_many_blocking` in a single await. Journal payload always uses reduced timeout (1.0s) per 2-G.

### 3-D: Per-tier deadline budgets
**File:** `src/intelligence/pipeline/feature_pipeline_executor.py`
**Fix:** Add `TIER_BUDGET_MS: dict[str, float]` config (e.g., I1=30ms, I2-I6=20ms each, I7=50ms). If a tier exceeds budget, log a warning with the overage and carry forward previous bar's tier output (stale values, not None). Counter: `intelligence_pipeline_tier_deadline_exceeded_total{tier}`. This bounds worst-case latency without dropping bars.

### 3-E: Pre-compute flat feature dict on IntelligenceEvent
**File:** `src/intelligence/pipeline/signal_processor.py:84-105`
**Current:** `_build_features_from_event` calls `model_dump()` on 8 tier schemas per bar reaching I7.
**Fix:** Compute and cache the flat feature dict in `FeaturePipelineExecutor` at `IntelligenceEvent` construction time. Store as `event._flat_features` (non-schema field, prefixed to avoid Pydantic serialization). `_build_features_from_event` becomes an attribute access + alias injection.

---

## Phase 4 — Data Remediation

### 4-A: ML training query filters
All queries against `intelligence_features`, `signal_ledger`, `signal_outcomes` used for ML training must add `WHERE feature_schema_version >= 2` (post-fix version). This applies to:
- `ml_training_agent.py` feature extraction
- `signal_replay_auditor.py` unresolved signal queries (already version-gated via `signal_schema_version`)
- `setup_performance_updater.py` rolling stats window

### 4-B: Calibration curve retraining
After `feature_schema_version=2` has accumulated sufficient clean rows (minimum 500 per `(setup_plugin, tf)` combination, or 14 days of live trading), retrain calibration curves using only clean data. Mark old curves with version tag; new curves replace them in `CacheManager`.

### 4-C: `setup_performance` window reset
The `setup_performance` 30-day rolling window contains pre-fix signal outcomes. Add a `data_version_gate` parameter to the updater: only include outcomes from signals with `signal_schema_version >= N` in rolling stats. This lets the multipliers self-correct as clean outcomes accumulate.

---

## Testing Strategy

Each phase requires a verification gate before the next phase ships:

| Phase | Verification |
|-------|-------------|
| 0 | `SELECT COUNT(*) FROM intelligence_features WHERE feature_schema_version IS NULL` = 0 after restart |
| 1-A | Distribution of `calibrated_confidence` shifts as expected (mean decreases, fewer near-1.0 values) |
| 1-B | `intelligence_pipeline_quality_floor_rejections_total` counter non-zero on live bars |
| 1-C | `python -c "from src.intelligence.pipeline.signal_processor import _I1_ALIAS_MAP"` exits clean |
| 1-D | All `supports_incremental=True` plugins pass `test_no_legacy_state_reads.py` |
| 1-G | No mutations to `_active_index` dicts detectable via identity check in unit tests |
| 1-H | Backfill signals in `signal_ledger` with `is_backfill=True AND exit_at IS NULL` decrease over replay auditor cycle |
| 2-C | `SETUP_PRIORITY` removed; `rank_signals` unit tests pass without it |
| 3-A | `intelligence_pipeline_plugin_skipped_total` unchanged; latency histogram shifts left |

---

## Files Changed (Key)

```
src/intelligence/schemas.py                  — FEATURE_SCHEMA_VERSION constant + field
src/intelligence/pipeline/signal_processor.py — alpha decay order, alias map, features cache
src/intelligence/pipeline/quality_gate.py    — min_confidence floor
src/intelligence/pipeline/executor.py        — fast-path protocol, CB enable, wave rules
src/intelligence/pipeline/per_key_worker_manager.py — queue depth metric
src/intelligence/pipeline/output_queue.py    — priority queues
src/intelligence/pipeline/state_manager.py   — CHECKPOINT_VERSION
src/intelligence/pipeline/feature_pipeline_executor.py — tier deadlines, flat feature cache
src/intelligence/pipeline/winner_selector.py — long_bias=False default
src/intelligence/pipeline/ranker.py          — SETUP_PRIORITY removal
src/intelligence/pipeline/regime_gate.py     — soft hmm_prob multiplier
src/intelligence/trading/aggregator.py       — SETUP_PRIORITY removal
src/intelligence/trading/signal_schema.py    — SIGNAL_SCHEMA_VERSION bump
services/intelligence_pipeline.py           — lazy serialize, batched enqueue, remove health stub
services/signal_tracker.py                  — CONCERN-02/06/regime cache/MAE_MFE
services/lifecycle_writer.py                 — MAE_MFE_UPDATE transition type
migrations/                                  — feature_schema_version column
```

---

## Non-Goals

- CONCERN-03 full architectural fix (single-consumer fan-out) — Phase 2-F provides adequate mitigation; full redesign deferred.
- Portfolio correlation awareness — Phase 5+ work requiring position state service.
- Per-plugin deadline enforcement in production mode — Phase 3-D provides monitoring; hard kill-and-carry-forward is a future hardening step.
- Historical data backfill recalculation — accept contamination boundary; filter going forward.
