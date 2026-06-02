# Phase 112: Intelligence Pipeline Signal Integrity — Context

**Gathered:** 2026-06-02
**Status:** Ready for planning
**Source:** PRD Express Path (docs/plans/2026-06-02-intelligence-pipeline-signal-integrity.md)

<domain>
## Phase Boundary

Fix 22 data integrity defects across the intelligence pipeline (I1-I7) and signal lifecycle. Three co-active bugs have been contaminating training data: (1) calibration applied to wrong input distribution, (2) no quality floor rejecting noise signals, (3) PERF-03 incomplete — legacy plugins cold-starting on every bar. The fix must establish a forensic contamination boundary (`feature_schema_version = 2`) before any logic changes, then fix the logic, then fix architecture/latency, then update ML data queries.

**What this phase delivers:**
- A clean-data guarantee: every row after Phase 0 deploy has `feature_schema_version = 2`
- Correct calibration architecture (CIS-level, not per-signal)
- Empirical quality floor via win-rate analysis
- Complete PERF-03 migration with startup enforcement
- Signal lifecycle integrity (immutable canonical dicts, MAE/MFE persistence, regime bootstrap)
- Architecture cleanup (wave isolation, features dual-write elimination, output queue fair drain)
- Latency improvements (fast-path, serialization fix, tier deadlines, flat features precompute)
- ML training query gates on `feature_schema_version >= 2`

**What this phase does NOT deliver:**
- Full single-consumer fan-out redesign (2-F provides adequate mitigation only)
- Portfolio correlation awareness (Phase 5+)
- Historical data recalculation (accept contamination boundary; filter going forward)
- Carry-forward for stateful plugins on deadline miss (hard outer timeout handles it)

</domain>

<decisions>
## Implementation Decisions

### D-01: Contamination boundary strategy
Use `feature_schema_version = 2` as the clean-data marker. Old rows stay NULL — no backfill. Training queries add `WHERE feature_schema_version >= 2`. Version starts at 2 (not 1) so pre-fix rows have NULL = tainted by convention.

### D-02: Phase 0 ships as single atomic commit
Phase 0 has four intentional side effects that must co-deploy: version marker in DB, checkpoint flush on next restart, `setup_performance` reset to neutral, `SIGNAL_SCHEMA_VERSION` bump DEFERRED to end of Phase 1.

### D-03: SIGNAL_SCHEMA_VERSION bump timing
Bump `SIGNAL_SCHEMA_VERSION` at end of Wave 2 (atomically with 1-F + 2-C), NOT in Phase 0. Bumping in Phase 0 breaks `signal_replay_auditor.py` query gate mid-flight.

### D-04: Calibration architecture — Design B (confirmed)
Remove `apply_calibration` from `SignalProcessor.process()`. Apply calibration to filtered CIS inside `CISScorer.score()`. Stamp `calibrated_confidence` from `cis_result.calibrated_cis`. The isotonic curves were trained on CIS scores; applying them to per-signal plugin outputs is a category error.

### D-05: Quality floor — empirically derived, not hardcoded
Run win-rate query: find lowest confidence bucket where `win_rate >= 0.50`. Set `SIGNAL_MIN_PUBLISHABLE_CONFIDENCE` to that value. Default to 0.12 if < 500 outcomes. Never guess the value.

### D-06: 1-F and 2-C ship atomically
`long_bias=False` (1-F) and `SETUP_PRIORITY` removal (2-C) must co-deploy. The tiebreak logic (confidence secondary sort) only makes sense when adjusted_rank has no priority component.

### D-07: PERF-03 — class attribute enforcement, not grep assertions
Add `_state_migration_complete: ClassVar[bool] = False` to `PatternPlugin`. Compliant plugins set `= True`. `PluginExecutor.__init__` raises named `RuntimeError` (not assert) for any incremental plugin that hasn't confirmed migration.

### D-08: Lifecycle — no canonical dict mutations
`status` and `market_entry_price` move to `SignalState`. `sig_with_extras` injection is the single point where state fields enter the evaluation dict. Canonical dicts in `_active_index` are read-only after ingestion.

### D-09: Backfill signal routing
`is_backfill=True` + TTL elapsed → add to `_signal_ids` dedup only; do NOT publish EXIT, do NOT add to active index. `SignalReplayAuditor` evaluates bar-by-bar. `is_backfill=False` + TTL elapsed → existing `ttl_expired_behind` behavior preserved.

### D-10: Consumer offset reset
Change signal consumer `auto_offset_reset` from `"latest"` to `"earliest"`. `_signal_ids` dedup makes re-consumed known signals harmless.

### D-11: Output queue — weighted-fair drain (5:1 configurable)
Two queues: `_high_queue` (intelligence, signals, winners) and `_low_queue` (journal). Drain ratio `OUTPUT_QUEUE_DRAIN_RATIO` setting, default 5. Prevents journal starvation under sustained load.

### D-12: Tier deadline budgets — stateful plugins never carry forward
Non-stateful plugins on deadline miss: carry forward previous bar output. Stateful plugins (GARCH, Kalman, HMM): run anyway, log warning, accept latency. Hard outer 500ms budget at `_process_bar` level — DLQ on timeout.

### D-13: Fast-path eligibility requires metric verification
`fast_path=True` requires `supports_incremental=False` AND P99 latency < 100µs verified from histogram over 24h live data. Mark candidates tentatively; verify metric; then set attribute.

### D-14: Serialization fix — model_dump not model_dump_json
Change `{"event": fp_result.event.model_dump_json()}` to `fp_result.event.model_dump(mode="json")` — eliminates double-deserialize at every consumer.

### D-15: `frames["features"]` dual-write must be eliminated completely
Migrate all I2-I7 plugins to typed tier access. Remove the `frames.setdefault("features", {})` + `features.update(tier_output)` pattern from `run_tiers`. Add regression test asserting no plugin uses `frames.get("features"`.

### D-16: Warm-up penalty for unvalidated setups
For setups with `sample_size < 30`, use `perf_multiplier = 0.5` (below neutral). Gate for above-neutral ranking: `sample_size >= 30` AND `bootstrap_ci_lower(pnl_r) > 0.0`.

### D-17: 2-D soft regime gate — DO NOT IMPLEMENT
`regime_gate.py` already implements three-band soft gate with Shannon entropy attenuation. The described bug does not exist. Skip entirely.

### D-18: MAE/MFE persistence
Add `MAE_MFE_UPDATE` to `TransitionType`. Publish when `abs(state.mae) > 0.05 or abs(state.mfe) > 0.05` AND every 10 active bars. Bootstrap seeds `state.mae` and `state.mfe` from `signal_outcomes` JOIN.

### D-19: Regime cache bootstrap
Seed `_regime_cache[(symbol, tf)]` from `hmm_regime_at_fire` and `garch_sigma_at_fire` in bootstrapped signal set. Fire-time regime is coarse but better than zero.

### Claude's Discretion
- Exact SQL in the quality floor win-rate query can be adapted from the spec as written
- Unit test structure and file names follow project conventions (tests/unit/intelligence/)
- OTel counter/gauge wiring follows existing patterns in `src/observability/metrics.py`
- Migration file naming follows existing convention in `migrations/` directory

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Primary spec
- `docs/plans/2026-06-02-intelligence-pipeline-signal-integrity.md` — Full 22-finding spec with exact file changes, migration checklist, and canonical testing gates. READ THIS FIRST.

### Core files being modified
- `src/intelligence/pipeline/signal_processor.py` — remove apply_calibration, add alias map, stage order
- `src/intelligence/trading/cis_scorer.py` — add apply_calibration to CIS score path
- `src/intelligence/pipeline/quality_gate.py` — empirical confidence floor
- `src/intelligence/pipeline/executor.py` — fast-path, CB enable, _state_migration_complete check
- `src/intelligence/pipeline/feature_pipeline_executor.py` — tier deadlines, flat_features on result
- `src/intelligence/pipeline/state_manager.py` — CHECKPOINT_VERSION=2
- `src/intelligence/pipeline/per_key_worker_manager.py` — queue depth metrics
- `src/intelligence/pipeline/output_queue.py` — weighted-fair-queue
- `src/intelligence/pipeline/winner_selector.py` — long_bias=False
- `src/intelligence/pipeline/ranker.py` — SETUP_PRIORITY removed, warm-up penalty
- `src/intelligence/trading/aggregator.py` — SETUP_PRIORITY removed
- `src/intelligence/trading/signal_schema.py` — SIGNAL_SCHEMA_VERSION bump (end Wave 2)
- `src/intelligence/trading/lifecycle_transitions.py` — MAE_MFE_UPDATE transition type
- `src/intelligence/plugins/base.py` — fast_path, _state_migration_complete attrs
- `src/intelligence/schemas.py` — FEATURE_SCHEMA_VERSION=2
- `services/intelligence_pipeline.py` — serialization fix, batched enqueue, health loop
- `services/signal_tracker.py` — CONCERN-02/06/MAE_MFE/regime_cache/CONCERN-03
- `services/lifecycle_writer.py` — MAE_MFE_UPDATE flush handler

### Patterns and infrastructure
- `src/core/stream_keys.py` — all Kafka topic keys
- `src/observability/metrics.py` — OTel counter/gauge patterns (direct SDK, no prometheus_client)
- `src/observability/spans.py` — observed_span patterns
- `src/config/settings.py` — Settings class (add SIGNAL_MIN_PUBLISHABLE_CONFIDENCE, OUTPUT_QUEUE_DRAIN_RATIO)
- `migrations/` — existing migration files for naming convention

### Schema references
- `migrations/095_signal_ledger_full_view.sql` — current signal_ledger_full VIEW DDL (must be updated)
- `src/intelligence/trading/signal_schema.py` — SIGNAL_SCHEMA_VERSION constant (single source of truth)

</canonical_refs>

<specifics>
## Specific Implementation Details

### Canonical pipeline stage order (post all Wave 2+3 changes)
```
raw_signals (from I7 plugins)
  ↓ 1. alpha_decay       — penalizes repeated fires (uses setup_last_fire)
  ↓ 2. quality_gate      — Hurst×entropy multiplier; rejects below min_confidence floor
  ↓ 3. regime_gate_soft  — three-band attenuation: suppress / soft-attenuate / pass
  ↓ 4. tod_adjustment    — time-of-day prior multiplier
  ↓ 5. ranking           — adjusted_rank = perf_multiplier (no SETUP_PRIORITY)
  ↓ 6. winner_selection  — CIS override or rank/majority fallback

CIS score path (parallel):
  raw_cis → Kalman filter → apply_calibration (isotonic on cis_score outcomes) → filtered_cis
  calibrated_cis stamped onto winner as calibrated_confidence
```

### Migration checklist (Wave 1)
```
migrations/
  add_feature_schema_version_to_intelligence_features.sql  -- nullable INTEGER
  add_feature_schema_version_to_signal_ledger.sql          -- nullable INTEGER
  update_signal_ledger_full_view.sql                       -- include new columns
  reset_setup_performance_to_neutral.sql                   -- perf_multiplier=1.0, sample_size=0
```

### Testing gates from spec
- Phase 0: `SELECT COUNT(*) FROM intelligence_features WHERE feature_schema_version IS NULL` decreases after restart; `SELECT perf_multiplier FROM setup_performance LIMIT 1` = 1.0
- 1-A: `apply_calibration` not in `SignalProcessor.process()`; calibrated_confidence distribution narrows
- 1-B: `intelligence_pipeline_quality_floor_rejections_total` counter non-zero after 1h live
- 1-C: `python -c "from src.intelligence.pipeline.signal_processor import _I1_ALIAS_MAP"` exits 0
- 1-D: `pytest tests/unit/intelligence/test_perf03_migration.py` — all incremental plugins confirmed
- 1-G: unit test: `_active_index` dicts unchanged before/after `_evaluate_bar`
- 1-H: backfill count in signal_ledger decreases over replay auditor cycle
- 2-C: `grep -r "SETUP_PRIORITY" src/ services/` returns empty

### setup_performance reset SQL (Wave 1)
```sql
UPDATE setup_performance SET perf_multiplier = 1.0, sample_size = 0
WHERE signal_schema_version < $new_version OR signal_schema_version IS NULL;
```

### PERF-03 enforcement pattern (Wave 2)
```python
incomplete = [
    n for n in incremental_names
    if not getattr(self._plugin_cache.get(n), "_state_migration_complete", False)
]
if incomplete:
    raise RuntimeError(f"PERF-03 migration incomplete for plugins: {incomplete}")
```

### Transition window for SIGNAL_SCHEMA_VERSION bump (Wave 2 end)
At bump time: `SELECT COUNT(*) FROM signal_ledger WHERE signal_schema_version = $old AND exit_at IS NULL`. Log count; route any active in-flight signals to replay auditor explicitly before they expire silently.

</specifics>

<deferred>
## Deferred Ideas

- CONCERN-03 full architectural fix (single-consumer fan-out) — 2-F (earliest offset reset) provides adequate mitigation only
- Portfolio correlation awareness — Phase 5+ requiring position state service
- Historical data recalculation — accept contamination boundary; filter going forward
- Per-miss carry-forward for stateful plugins — hard outer 500ms timeout handles degenerate case
- Calibration curve retraining (4-B) — happens organically after >= 500 clean outcomes accumulate; no code gate needed in this phase beyond the query filter in 4-A

</deferred>

---

*Phase: 112-intelligence-pipeline-signal-integrity*
*Context gathered: 2026-06-02 via PRD Express Path (docs/plans/2026-06-02-intelligence-pipeline-signal-integrity.md)*
