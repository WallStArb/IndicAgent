# Requirements: v2.10 Data Architecture Evolution

## Overview

**Milestone:** v2.10 — Data Architecture Evolution
**Goal:** Decide on signal/trade separation architecture, execute database migration if approved, rewrite affected scripts, then run clean replay and produce the deferred Phase 121 Wave 2 validation report.
**Architecture constraint:** Signal generation + trade framing remain embedded at compute layer (Principle 12 — Signal Generation Invariant). This milestone addresses data layer separation only.

---

## v1 Requirements

### Architecture Decision (Phase 123)

- [ ] **ARCH-01**: Operator can read an ADR that documents the chosen data model (2-table vs 3-table), with rationale and rejection reasoning for the alternative
- [ ] **ARCH-02**: ADR defines cardinality rules — whether one signal can produce multiple trades, and whether one trade can have multiple executions (partial fills, scale-outs)
- [ ] **ARCH-03**: ADR defines numeric type standardization for prices and P&L (NUMERIC vs FLOAT) and records the chosen approach with migration implications

### Database Migration (Phase 124 — conditional on ARCH decision)

- [ ] **MIGRATE-01**: Old schema (signal_ledger, signal_outcomes) is cleanly dropped and replaced with new tables per ADR decision; migration script is idempotent and includes rollback DDL
- [ ] **MIGRATE-02**: New schema has performance indexes on all high-frequency query patterns: (timestamp DESC), (symbol, timestamp DESC), (signal_id), (exit_at), (outcome, exit_at)
- [ ] **MIGRATE-03**: A `signal_ledger_full` compatibility view exists so existing consumers can query through it without immediate code changes; backward-compatible until Phase 125 rewrites complete

### Script Rewriting (Phase 125 — conditional on MIGRATE completion)

- [ ] **REWRITE-01**: SignalWriter writes signal fire events to the new tables (signal_events and trade_framing/trade_execution per ADR); no direct signal_ledger writes remain in any service
- [ ] **REWRITE-02**: lifecycle_writer reads from signal_events, writes outcome columns to trade_execution; all query callsites updated to new table names or signal_ledger_full view
- [ ] **REWRITE-03**: Dashboard `/api/signals/active` continues to return all fire-time fields with LATERAL JOIN latency under 500ms p95; all services restart cleanly after migration

### Clean Replay + Signal Quality Validation (Phase 126 — conditional on REWRITE completion)

- [ ] **REPLAY-02**: Full clean replay executes on empty new-schema tables — historical backfill → feature_replay.py → lifecycle_replay.py — producing a complete, noise-free signal history under the v2.9 pipeline; before/after comparison report generated with per-setup PASS/FAIL/PARTIAL verdicts, bootstrap 95% CI on calibration_corr (setups with pnl_r_n >= 30), and Welch's t-test p-value for pnl_r shift
- [ ] **REPLAY-03**: RCA Part VI updated with MEASURED values and `MEASURED [date]` annotations for all v2.9 roadmap targets; v2.9 milestone formally closed

---

## Future Requirements (deferred)

| Requirement | Reason for deferral |
|-------------|---------------------|
| Partial fill / scale-out execution modeling | Cardinality decision in ARCH-02 may unlock this; deferred to a future execution-focused milestone |
| ML training dataset rebuild on new schema | After REPLAY-02 completes, ml_signal_training hypertable may need schema migration — deferred to v2.8 Part 2 prep |

---

## Out of Scope

| Feature | Reason |
|---------|--------|
| Moving signal generation or trade framing out of IntelligencePipeline | Principle 12 (Signal Generation Invariant) — settled in `docs/plans/archive/2026-06-07-trade-framing-architecture-analysis.md` |
| Execution engine / order routing | Intelligence platform only — no execution engine |
| v2.8 Part 2 AI platform phases (096-099, 101-103) | Separate milestone; unblocked after v2.10 completes |

---

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| ARCH-01 | 123 | — |
| ARCH-02 | 123 | — |
| ARCH-03 | 123 | — |
| MIGRATE-01 | 124 | — |
| MIGRATE-02 | 124 | — |
| MIGRATE-03 | 124 | — |
| REWRITE-01 | 125 | — |
| REWRITE-02 | 125 | — |
| REWRITE-03 | 125 | — |
| REPLAY-02 | 126 | — |
| REPLAY-03 | 126 | — |
