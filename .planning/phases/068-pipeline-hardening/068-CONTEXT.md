# Phase 68: Pipeline Hardening & Institutional Foundation — Context

**Gathered:** 2026-04-11
**Status:** Ready for planning
**Source:** PRD Express Path (docs/plans/2026-04-11-pipeline-hardening-design.md)

<domain>
## Phase Boundary

Fix critical correctness bugs in the signal pipeline, consolidate writer agent
infrastructure into a shared base class, add end-to-end trace ID, and truncate
the contaminated signal_ledger for a clean data foundation.

**In scope:**
- 5 signal pipeline correctness fixes + 4 attribution/instrumentation improvements (Plan 1)
- BaseWriterAgent base class + migration of all 5 writer agents + 3 reliability fixes (Plan 2)
- bar_id trace from ibkr_provider_agent, migration 063, TRUNCATE signal_ledger (Plan 3)

**Not in scope:** New I7 plugins, I1–I6 changes, calibration retraining, historical backfill.

**Zero new systemd units. Zero new Kafka topics beyond what's in migration 063.**

</domain>

<decisions>
## Implementation Decisions

### Plan 1: Signal Pipeline Correctness

**Fix 1 — Regime type injection (Critical Bug)**
- `apply_regime_gate` reads `sig.get("regime_type", "any")` — plugins don't include it in return dict
- Fix: inject `getattr(plugin_inst, "regime_type", "any")` into signal dict BEFORE `apply_quality_gate`
- Must happen before the pipeline stages run, not in the post-annotation loop

**Fix 2 — Settings thresholds wired to apply_regime_gate**
- `self._regime_dur_min: float = 0.30` is wrong type (should be `int`) and never passed to call site
- Fix: load `self._regime_prob_min = self._settings.regime_prob_min` and `self._regime_dur_min: int = self._settings.regime_dur_min` in `_setup()`
- Pass as `apply_regime_gate(quality_gated, features, prob_min=self._regime_prob_min, dur_min=self._regime_dur_min)`

**Fix 3 — HMM numeric label bug**
- `f["regime_type"] = f.get("hmm_regime", "ranging")` stores numeric 0/1/2 as `regime_type`
- Fix: add `_HMM_TO_LABEL = {0: "ranging", 1: "trend", 2: "trend"}` in `_build_features_from_event`
- Store `f["hmm_regime_label"] = _HMM_TO_LABEL.get(int(hmm_val), "unknown")`
- In annotation loop: stamp `sig["hmm_regime_label"]`, do NOT overwrite `sig["regime_type"]`

**Fix 4 — Long bias parameterized**
- `majority_group = by_direction[1] if longs >= shorts else by_direction[-1]` — hardcoded, no empirical backing
- Add `Settings.winner_long_bias: bool = Field(default=True, validation_alias="WINNER_LONG_BIAS")`
- Pass into `select_winner` or `_aggregate_fallback`; default=True preserves current behavior

**Fix 5 — Confidence boost removed, agreement count stored**
- `_CONFIDENCE_BOOST_PER_AGREE = 0.05` applied before calibration defeats isotonic curves
- Remove boost from `_aggregate_via_cis` and `_aggregate_fallback`
- Store `n_agreeing_signals` and `n_opposing_signals` in signal dict for persistence

**Fix A — resolution_method stamped**
- `winner, _, resolution_method = select_winner(...)` — `_` discards the value
- Fix: stamp into ALL ranked signals: `sig["resolution_method"] = resolution_method`

**Fix B — setup_last_fire checkpointed**
- `_setup_last_fire` absent from `_checkpoint_state` — alpha decay resets on every restart
- Add `"_setup_last_fire": self._setup_last_fire` to state dict in `_checkpoint_state`

**Fix C — Full 5-point confidence attribution vector**
- Capture `pre_regime_confidence` (after quality, before regime) and `pre_tod_confidence` (after regime, before TOD)
- Attribution invariant: `pre_quality >= pre_regime >= pre_tod >= pre_calibration >= calibrated_confidence`

**Fix F — Regime suppression metric**
- Add `REGIME_GATE_SUPPRESSIONS_TOTAL` counter with labels `{reason, plugin, tf}` to `src/observability/metrics.py`
- Increment after `apply_regime_gate` for each signal where `regime_eligible=False`

### Plan 2: BaseWriterAgent + Write-path Reliability

**BaseWriterAgent location:** `src/core/agent/base_writer.py`
- Inherits from `BaseAgent`
- Abstract methods: `_topic_name() → str`, `_consumer_group: str`, `_parse_payload(payload) → list | None`, `_flush_batch(batch) → None`, `_dlq_topic() → str | None`
- Class vars: `BATCH_SIZE = 100`, `FLUSH_INTERVAL_SECS = 5.0`, `MAX_BUFFER_SIZE = 10_000`, `BUFFER_ALERT_PCT = 0.80`
- Base owns: consume loop, buffer overflow guard, flush scheduling, manual offset commit, DLQ routing, teardown flush, `_buffer_depth` gauge

**Manual offset commit contract:**
- `enable_auto_commit=False` on all consumers created by base
- Offset committed via `await self._consumer.commit()` only after `_flush_batch()` succeeds
- On `_flush_batch()` failure: retain buffer, log error, do NOT commit

**DLQ routing:**
- When `_parse_payload()` returns None: call `self._send_to_dlq(payload, exc)` (from BaseAgent)
- Continue consuming (do not crash)

**Writer migration targets:** signal_writer, lifecycle_writer, bar_writer, feature_writer, swarm_writer
- Each reduces to: `_parse_payload`, `_flush_batch`, `_topic_name`, `_consumer_group`, domain-specific `_setup()` additions

### Plan 3: Trace ID + Clean Slate

**bar_id originates at ibkr_provider_agent:**
- Add `bar_id: UUID = Field(default_factory=uuid4)` to `src/core/schemas/bar_message.py`
- `ibkr_provider_agent` stamps `bar_id=uuid4()` on each BarMessage before publishing to `market.bars`
- `intelligence_pipeline_agent` carries `bar.bar_id` through — no new UUID generated mid-pipeline
- Writers pass `bar_id` to DB via BaseWriterAgent

**Migration 063 (`063_pipeline_hardening.sql`):**
- `ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS bar_id UUID`
- `ALTER TABLE intelligence_features ADD COLUMN IF NOT EXISTS bar_id UUID`
- `ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS pre_regime_confidence FLOAT`
- `ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS pre_tod_confidence FLOAT`
- `ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS hmm_regime_label TEXT`
- `ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS n_agreeing_signals INT`
- `ALTER TABLE signal_ledger ADD COLUMN IF NOT EXISTS n_opposing_signals INT`
- `ALTER TABLE signal_ledger ADD CONSTRAINT uq_signal_ledger_identity UNIQUE (symbol, feature_ts, feature_tf, setup_plugin)`
- `TRUNCATE TABLE signal_ledger` — all historical signals have bypassed regime type filtering
- Indexes on `bar_id` for both tables

**intelligence_features kept intact** — feature vectors unaffected by signal bugs, valid ML training data.

### Wave / Execution Order

- **Plan 1 (foundation):** Signal pipeline correctness — all in `intelligence_pipeline_agent.py` + pipeline stages
- **Plan 2 (independent):** BaseWriterAgent + writer migration — disjoint files from Plan 1
- **Plan 3 (after Plan 1):** Trace ID + migration — bar_id needs corrected pipeline to flow through correctly

Plans 1 and 2 can execute in parallel. Plan 3 depends on Plan 1.

### Claude's Discretion

- Exact `KafkaConsumerClient` API for manual offset commit (check `src/core/kafka_utils.py`)
- Whether `_flush_batch` raises or returns bool — base class uses raise-on-failure contract
- Test approach for BaseWriterAgent (unit tests with mock consumer + mock DB)
- Whether `winner_long_bias` setting is passed to `select_winner` via argument or read from Settings inside the function

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design Doc (source of truth)
- `docs/plans/2026-04-11-pipeline-hardening-design.md` — Full problem analysis, fix specifications, success criteria

### Core Pipeline Files
- `services/intelligence_pipeline_agent.py` — All Plan 1 fixes live here (1761 lines; read fully)
- `src/intelligence/pipeline/winner_selector.py` — Fix 4 (long bias), Fix 5 (boost removal)
- `src/intelligence/pipeline/regime_gate.py` — Verify apply_regime_gate signature for prob_min/dur_min
- `src/config/settings.py` — Add winner_long_bias field, fix regime_dur_min type
- `src/observability/metrics.py` — Add REGIME_GATE_SUPPRESSIONS_TOTAL counter

### Writer Infrastructure
- `src/core/agent/base.py` — Existing BaseAgent (BaseWriterAgent inherits from this)
- `src/core/kafka_utils.py` — KafkaConsumerClient API for manual offset commit
- `services/signal_writer_agent.py` — Migration target (234 lines)
- `services/lifecycle_writer_agent.py` — Migration target (200 lines)
- `services/bar_writer_agent.py` — Migration target (has contract cache — domain-specific _setup)
- `services/feature_writer_agent.py` — Migration target (798 lines — largest, most complex)
- `services/swarm_writer_agent.py` — Migration target

### Trace + Schema
- `src/core/schemas/bar_message.py` — Add bar_id field
- `services/ibkr_provider_agent.py` — Stamp bar_id at publish
- `production/migrations/` — Next migration: 063_pipeline_hardening.sql
- `src/persistence/repository/signal_ledger_repository.py` — LedgerEntry fields + insert SQL

### Naming Conventions
- `CLAUDE.md` — Cross-layer naming rules, service patterns, TDD requirements

</canonical_refs>

<specifics>
## Specific Requirements

### Success Criteria
1. MeanReversionPlugin signal suppressed (status=regime_suppressed) when hmm_regime=1 — verifiable via signal_ledger query
2. `regime_gate_suppressions_total{reason="regime_type"}` increments in first trading session
3. Settings.regime_prob_min and regime_dur_min changes take effect on restart
4. signal_ledger.resolution_method non-null for all rows after deploy
5. pre_regime_confidence and pre_tod_confidence non-null for all rows
6. After restart, alpha decay does not reset (first bar confidence = decayed value, not raw)
7. All 5 writers inherit BaseWriterAgent; offset committed only after successful DB flush
8. Malformed payloads route to DLQ, not silent drop
9. signal_ledger.bar_id matches intelligence_features.bar_id for same (symbol, feature_ts, feature_tf)
10. signal_ledger empty after TRUNCATE; new signals accumulate with clean regime filtering

### Attribution Invariant (test-enforced)
`pre_quality_confidence >= pre_regime_confidence >= pre_tod_confidence >= pre_calibration_confidence >= calibrated_confidence`

### Prometheus Metric Naming
- `regime_gate_suppressions_total` — labels: `{reason, plugin, tf}`
- `*_buffer_depth` — per-writer gauge from BaseWriterAgent (follows existing `signal_writer_buffer_depth` pattern)

</specifics>

<deferred>
## Deferred Items

- bar_auditor_agent cross-referencing bar_ids to detect pipeline drops (future phase)
- Empirical validation of n_agreeing_signals predicting outcomes (30+ days clean data needed first)
- SETUP_PRIORITY empirical derivation from setup_performance (future ML phase)
- Calibration curve staleness detection / TTL refresh
- TOD/calibration/perf_weights coverage metrics

</deferred>

---

*Phase: 068-pipeline-hardening*
*Context gathered: 2026-04-11 via PRD Express Path (docs/plans/2026-04-11-pipeline-hardening-design.md)*
