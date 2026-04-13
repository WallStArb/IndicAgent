# Phase 68: Pipeline Hardening & Institutional Foundation - Context

**Gathered:** 2026-04-12
**Status:** Ready for planning
**Source:** PRD Express Path (docs/plans/2026-04-11-pipeline-hardening-design.md)

<domain>
## Phase Boundary

Phase 68 delivers three parallel workstreams:

1. **Signal Pipeline Correctness** — Fix 5 critical bugs in `intelligence_pipeline_agent.py` plus 4 attribution/instrumentation improvements
2. **BaseWriterAgent + Write-path Reliability** — Create `src/core/agent/base_writer.py`, migrate all 5 writer agents, add offset-commit/DLQ/bounded-buffer guarantees
3. **Trace ID + Clean Slate** — Add `bar_id` UUID trace from provider to lifecycle exit, DB migration 063 with schema additions + TRUNCATE signal_ledger

**Not in scope:** New I7 plugins, I1–I6 tier logic changes, calibration curve retraining, historical signal_ledger backfill.

</domain>

<decisions>
## Implementation Decisions

### Fix 1: Regime Type Filtering (PIPE-REGIME-FILTER) — LOCKED
- In `_run_i7`, after collecting plugin output and BEFORE `apply_regime_gate`, inject plugin's class-level `regime_type` into signal dict:
  ```python
  plugin_inst = self._plugin_cache.get(task.plugin_name)
  sig["regime_type"] = getattr(plugin_inst, "regime_type", "any")
  sig["setup_plugin"] = task.plugin_name
  ```
- This injection MUST happen BEFORE `apply_quality_gate`
- The annotation loop that overwrites `sig["regime_type"]` with HMM numeric value MUST be removed (see Fix 3)
- Root cause: plugins declare `regime_type` as class attribute but never include it in return dict → defaults to "any" → zero filtering

### Fix 2: Settings Wiring for Regime Thresholds (PIPE-SETTINGS-WIRE) — LOCKED
- `_regime_dur_min` type is `float` (wrong) → change to `int` in Settings
- Both `regime_prob_min` and `regime_dur_min` currently use function defaults (Settings ignored)
- Fix: Load from Settings in `_setup()`:
  ```python
  self._regime_prob_min: float = self._settings.regime_prob_min
  self._regime_dur_min: int = self._settings.regime_dur_min
  ```
- Pass to call site:
  ```python
  regime_gated = apply_regime_gate(quality_gated, features, prob_min=self._regime_prob_min, dur_min=self._regime_dur_min)
  ```
- Verify `Settings.regime_dur_min` field type is `int`

### Fix 3: HMM Regime Label vs Numeric (PIPE-LABEL-FIX) — LOCKED
- In `_build_features_from_event`, separate concepts:
  ```python
  _HMM_TO_LABEL: dict[int, str] = {0: "ranging", 1: "trend", 2: "trend"}
  f["hmm_regime"] = hmm_val          # numeric: 0, 1, 2
  hmm_int = int(hmm_val) if hmm_val is not None else None
  f["hmm_regime_label"] = _HMM_TO_LABEL.get(hmm_int, "unknown")
  ```
- In annotation loop, stamp `hmm_regime_label` not `regime_type`:
  ```python
  sig["hmm_regime_label"] = features.get("hmm_regime_label")
  sig["hmm_regime_at_fire"] = features.get("hmm_regime")  # numeric
  # Do NOT overwrite sig["regime_type"] — set from plugin class attr in Fix 1
  ```
- Add `hmm_regime_label` column to `signal_ledger` in migration 063

### Fix 4: Long Bias Parameterization (PIPE-LONG-BIAS) — LOCKED
- Add to `Settings`:
  ```python
  winner_long_bias: bool = Field(default=True, validation_alias="WINNER_LONG_BIAS")
  ```
- In `_aggregate_fallback`, neutral tiebreak when disabled:
  ```python
  if longs == shorts:
      if settings.winner_long_bias:
          majority_group = by_direction[1]
      else:
          majority_group = sorted(active, key=lambda s: s.get("adjusted_rank", 999))[:1]
  else:
      majority_group = by_direction[1] if longs > shorts else by_direction[-1]
  ```
- Default `True` preserves current behavior. `WINNER_LONG_BIAS=false` enables neutral.
- Change lives in `src/intelligence/pipeline/winner_selector.py`

### Fix 5: Remove Confidence Boost (PIPE-CONFIDENCE-BOOST) — LOCKED
- Remove `_CONFIDENCE_BOOST_PER_AGREE` entirely from `_aggregate_via_cis` and `_aggregate_fallback`
- Replace with data capture:
  ```python
  sig["n_agreeing_signals"] = len([s for s in active if s.get("direction") == winner_direction])
  sig["n_opposing_signals"] = len([s for s in active if s.get("direction") != winner_direction])
  ```
- Add `n_agreeing_signals INT`, `n_opposing_signals INT` columns to `signal_ledger` (migration 063)
- Future: if p < 0.05 correlation with outcomes after 30+ days, add boost back with calibrated coefficient

### Fix A: Resolution Method Stamping (PIPE-RESOLUTION-METHOD) — LOCKED
- `winner, _, resolution_method = select_winner(ranked, cis_result)` currently discards `resolution_method`
- Fix: stamp into all ranked signals:
  ```python
  winner, _, resolution_method = select_winner(ranked, cis_result)
  for sig in ranked:
      sig["resolution_method"] = resolution_method
  ```
- `signal_ledger.resolution_method` column exists but is currently always NULL

### Fix B: Checkpoint `setup_last_fire` (PIPE-CHECKPOINT) — LOCKED
- Add `_setup_last_fire` to `_checkpoint_state`:
  ```python
  state = {
      "_plugin_states": self._plugin_states,
      "_kalman_state": self._kalman_state,
      "_tod_priors": self._tod_priors,
      "_bar_history": self._bar_history._data,
      "_last_bar_offset": self._last_bar_offset,
      "_setup_last_fire": self._setup_last_fire,  # ADD
  }
  ```

### Fix C: 5-Point Confidence Attribution Vector (PIPE-ATTRIBUTION-VECTOR) — LOCKED
- Capture at all 4 intermediate checkpoints in order:
  1. `pre_quality_confidence` before `apply_quality_gate` (existing)
  2. `pre_regime_confidence` before `apply_regime_gate` (NEW)
  3. `pre_tod_confidence` before `apply_tod_adjustment` (NEW)
  4. `pre_calibration_confidence` before `apply_calibration` (existing)
- Attribution invariant: `pre_quality >= pre_regime >= pre_tod >= pre_calibration >= calibrated_confidence`
- Add `pre_regime_confidence FLOAT`, `pre_tod_confidence FLOAT` to `signal_ledger` (migration 063)

### Fix F: Regime Suppression Metric (PIPE-REGIME-METRIC) — LOCKED
- Add to `src/observability/metrics.py`:
  ```python
  REGIME_GATE_SUPPRESSIONS_TOTAL = counter(
      "regime_gate_suppressions_total",
      "Signals suppressed by regime gate",
      labelnames=["reason", "plugin", "tf"],
  )
  ```
- In `_run_i7`, after `apply_regime_gate`, for each suppressed signal:
  ```python
  for sig in regime_gated:
      if not sig.get("regime_eligible", True):
          REGIME_GATE_SUPPRESSIONS_TOTAL.labels(
              reason=sig.get("suppression_reason", "unknown"),
              plugin=sig.get("setup_plugin", "unknown"),
              tf=tf,
          ).inc()
  ```

### BaseWriterAgent (WRITER-BASE-CLASS) — LOCKED
- Location: `src/core/agent/base_writer.py`
- Extends `BaseAgent`, is `ABC`
- Class vars: `BATCH_SIZE=100`, `FLUSH_INTERVAL_SECS=5.0`, `MAX_BUFFER_SIZE=10_000`, `BUFFER_ALERT_PCT=0.80`
- Abstract methods: `_topic_name() -> str`, `_consumer_group` (class var), `_parse_payload(payload: dict) -> list | None`, `_flush_batch(batch: list) -> None`
- Optional override: `_dlq_topic() -> str | None` (default None = log-only)
- Run loop: consume → `_parse_payload()` → None? → DLQ → continue; rows → buffer → flush trigger → `_flush_batch()` → success → commit offset
- Writers to migrate: `signal_writer_agent.py`, `lifecycle_writer_agent.py`, `bar_writer_agent.py`, `feature_writer_agent.py`, `swarm_writer_agent.py`

### Write-path Reliability (WRITER-OFFSET-COMMIT, WRITER-DLQ, WRITER-BUFFER-BOUND) — LOCKED
- `enable_auto_commit=False` on all consumers
- Offset committed only AFTER `_flush_batch()` succeeds
- Buffer capped at `MAX_BUFFER_SIZE`; overflow metric published
- `_buffer_depth` gauge published every consume cycle
- Alert log when depth > `BUFFER_ALERT_PCT * MAX_BUFFER_SIZE`
- Teardown: final flush before consumer stop
- DLQ route when `_parse_payload()` returns None (topic via `_dlq_topic()`)

### Trace ID (TRACE-BAR-ID) — LOCKED
- `bar_id: UUID = Field(default_factory=uuid4)` added to `src/core/schemas/bar_message.py`
- `ibkr_provider_agent`: stamp `bar_id=uuid4()` on each `BarMessage` before publish
- `intelligence_pipeline_agent`: carry `bar.bar_id` through to `IntelligenceEvent` and `BarIntelligenceRecord` — no new UUID at this layer
- Writer agents (via BaseWriterAgent): pass `bar_id` through to DB insert
- `bar_auditor_agent` cross-reference is future scope — not this phase

### Migration 063 (TRACE-CLEAN-SLATE) — LOCKED
- Single file: `production/migrations/063_pipeline_hardening.sql`
- Schema changes:
  ```sql
  ALTER TABLE signal_ledger         ADD COLUMN IF NOT EXISTS bar_id UUID;
  ALTER TABLE intelligence_features ADD COLUMN IF NOT EXISTS bar_id UUID;
  ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS pre_regime_confidence FLOAT;
  ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS pre_tod_confidence FLOAT;
  ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS hmm_regime_label TEXT;
  ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS n_agreeing_signals INT;
  ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS n_opposing_signals INT;
  ALTER TABLE signal_ledger
      ADD CONSTRAINT IF NOT EXISTS uq_signal_ledger_identity
      UNIQUE (symbol, feature_ts, feature_tf, setup_plugin);
  TRUNCATE TABLE signal_ledger;
  CREATE INDEX IF NOT EXISTS idx_signal_ledger_bar_id ON signal_ledger (bar_id);
  CREATE INDEX IF NOT EXISTS idx_intel_features_bar_id ON intelligence_features (bar_id);
  ```
- TRUNCATE is correct because all existing signals have bypassed regime type filtering

### Wave Ordering — LOCKED
- Wave A (parallel): Plan 68-01 (signal pipeline correctness) AND Plan 68-02 (BaseWriterAgent)
- Wave B (after 68-01): Plan 68-03 (trace ID + migration + clean slate)
- Wave C (after 68-03): Plan 68-04 (symbol-keyed aggregate tables)
- 68-01 and 68-02 touch disjoint files — safe to parallelize
- 68-03 depends on 68-01 because bar_id must flow through corrected pipeline
- 68-04 depends on 68-03 because both touch intelligence_pipeline_agent.py

### Claude's Discretion
- Test file structure and naming within `tests/unit/`
- Exact error message strings for DLQ log entries
- Whether BaseWriterAgent `_setup()` abstract or has default implementation
- Buffer depth Prometheus gauge metric name (not specified in PRD)
- Exact structlog fields for suppression log entries

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design Doc (primary spec)
- `docs/plans/2026-04-11-pipeline-hardening-design.md` — Full design with exact code snippets, root cause analysis, and success criteria for all 15 requirements

### Core Pipeline Files
- `services/intelligence_pipeline_agent.py` — Primary target for Plans 68-01 and 68-03; fixes 1-5, A, B, C, F
- `src/intelligence/pipeline/winner_selector.py` — Fix 4 (long bias), Fix 5 (remove boost)
- `src/intelligence/pipeline/regime_gate.py` — Read to understand interface (no changes)
- `src/config/settings.py` — `winner_long_bias`, `regime_dur_min` type fix

### Agent Infrastructure
- `src/core/agent/` — Existing BaseAgent and agent patterns to follow
- `services/signal_writer_agent.py` — First writer to migrate; canonical example
- `services/feature_writer_agent.py` — Current feature writer pattern
- `services/bar_writer_agent.py` — Current bar writer pattern
- `services/lifecycle_writer_agent.py` — Current lifecycle writer pattern
- `services/swarm_writer_agent.py` — Current swarm writer pattern

### Observability
- `src/observability/metrics.py` — Add `regime_gate_suppressions_total` here; check label API before adding

### Schema
- `src/core/schemas/bar_message.py` — Add `bar_id: UUID` field
- `services/ibkr_provider_agent.py` — Stamp bar_id on publish
- `production/migrations/` — Migration numbering reference (063 is next)

### Project Standards
- `CLAUDE.md` — Naming conventions, async DB patterns, asyncpg batch insert rules, structlog fields
- `.planning/ROADMAP.md` — Phase 68 requirements and plan structure
- `.planning/STATE.md` — Project state and decisions

</canonical_refs>

<specifics>
## Specific Ideas

### Success Criteria (from PRD)
1. `MeanReversionPlugin` signal suppressed when `hmm_regime=1` (trending-up) — query `signal_ledger`
2. `regime_gate_suppressions_total{reason="regime_type"}` counter increments in first trading session
3. `Settings.regime_prob_min` and `regime_dur_min` changes take effect on restart without code changes
4. `signal_ledger.resolution_method` non-null for all rows after deploy
5. `signal_ledger.pre_regime_confidence` and `pre_tod_confidence` non-null
6. After restart, alpha decay does not reset (first bar confidence matches expected decayed value)
7. All 5 writers inherit `BaseWriterAgent`; offset committed only after successful DB flush
8. Malformed Kafka payloads route to DLQ, not silent drop
9. `signal_ledger.bar_id` matches `intelligence_features.bar_id` for same `(symbol, feature_ts, feature_tf)`
10. `signal_ledger` empty after TRUNCATE; new signals accumulate with clean regime filtering

### Attribution Invariant Test
- Test must enforce: `pre_quality >= pre_regime >= pre_tod >= pre_calibration >= calibrated_confidence`

### Plugin Cache Reference
- `self._plugin_cache.get(task.plugin_name)` is the lookup pattern for Fix 1

</specifics>

<deferred>
## Deferred Ideas

- `bar_auditor_agent` cross-reference of `market.bars` vs `intelligence_features` bar_ids — explicitly out of scope for Phase 68 (future phase)
- New I7 plugins — out of scope
- I1–I6 tier logic changes — out of scope
- Calibration curve retraining — out of scope
- Historical signal_ledger backfill — out of scope
- Agreement count → confidence boost (requires 30+ days of clean data and p < 0.05 correlation)

</deferred>

---

*Phase: 68-pipeline-hardening-institutional-foundation*
*Context gathered: 2026-04-12 via PRD Express Path (docs/plans/2026-04-11-pipeline-hardening-design.md)*
