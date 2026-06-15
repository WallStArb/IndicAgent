# Phase 128: 3-Table Schema Design and ADR - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-15
**Phase:** 128-3-table-schema-design-and-adr
**Areas discussed:** signal_events column completeness, trade_frames stop architecture, Hypertable strategy, Phase 128 scope boundary

---

## signal_events column completeness

| Option | Description | Selected |
|--------|-------------|----------|
| First-class columns (full set) | hmm_regime_at_fire, is_shadow, is_backfill, calibrated_confidence, cis_score, weights_version, ttl_bars, expires_at, signal_computed_at as indexed first-class columns | ✓ |
| Fold into context_features JSONB | Leaner schema; regime/ML fields queryable via JSONB operators with GIN index | |
| Hybrid | is_shadow/is_backfill first-class; calibrated_confidence in JSONB | |

**User's guidance:** "Design like Renaissance would. What would Jim Simons demand?"

**Notes:** Applied Renaissance first-principles: regime state and ML governance flags are first-class segmentation dimensions. JSONB penalty at 10M+ rows for common WHERE predicates is unacceptable. Every training query filters on is_shadow, is_backfill, hmm_regime_at_fire — these need btree indexes, not JSONB path scans. bucket_scores (variable-structure, not queried field-by-field) goes into context_features. Dropped signal_type, feature_ts, feature_tf, pipeline_lag_ms as redundant with existing columns.

---

## trade_frames stop architecture

| Option | Description | Selected |
|--------|-------------|----------|
| First-class columns | All ~10 stop architecture fields as indexed columns on trade_frames | |
| frame_details JSONB | Stop architecture provenance in JSONB; only hypothesis scalars (entry/stop/target) first-class | ✓ |
| Separate stop_architecture table | 1:1 join table for stop detail | |

**User's guidance:** Delegated to Renaissance council judgment.

**Notes:** Stop architecture fields (stop_basis, stop_type_col, structural_stop_distance_atr, etc.) are causal inputs that produced the frame geometry — diagnostic/audit fields, not ML query dimensions. Renaissance would not pollute the primary key space with fields that are never query predicates. frame_details JSONB contains all stop provenance for audit; first-class schema stays tight. Shadow tracking (shadow_mae/mfe/outcome) dropped — CounterfactualTracker supersedes; historical values archived into frame_details during migration.

---

## Hypertable strategy

| Option | Description | Selected |
|--------|-------------|----------|
| signal_events as hypertable | Time-partitioned, chunk interval 7 days, compression; PK (signal_id, ts); trade_frames FK needs (signal_id, signal_ts) | ✓ |
| signal_events as regular table | Simpler schema, standard PK (signal_id), no time-chunk management | |

**User's guidance:** Delegated to Renaissance council judgment.

**Notes:** signal_ledger is already a hypertable with 104 chunks and compression enabled. signal_events will accumulate the same or greater volume. Time-range queries are dominant. Denormalizing signal_ts onto trade_frames resolves the FK-to-hypertable constraint cleanly without losing referential integrity. trade_frames and trade_executions as regular tables — they join to signal_events for time filtering.

---

## Phase 128 scope boundary

| Option | Description | Selected |
|--------|-------------|----------|
| ADR only | Document schema design; Phase 129 writes DDL | |
| ADR + SQL DDL + capture_signal_features() deletion + G0 audit | Full scope per Phase 126 D-10 deferred items | ✓ |
| ADR + SQL DDL only | Write the migration SQL but defer code cleanup | |

**User's guidance:** Delegated to Renaissance council judgment.

**Notes:** Phase 126 D-10 explicitly deferred capture_signal_features() deletion to Phase 128 with note "delete in Phase 128 after confirming no external callers." Phase 128 is the correct time — before Phase 129 migration and Phase 130 writer rewrite. G0 audit (signal_id consistency across entry_types) is a pre-migration gate that must complete before Phase 129 can safely execute.

---

## Claude's Discretion

- Migration number (NNN after 136) — next available in sequence
- GIN index decision for context_features/factor_scores — defer until ML query patterns are known
- Exact hypertable compression settings — match existing signal_ledger compression config
- direction column confirmed as text (long/short), not integer — consistent with existing v2.10 schema design

## Deferred Ideas

- GIN indexes on JSONB columns — premature; add after seeing actual ML query patterns
- is_shadow governance_flags JSONB consolidation — rejected (independent indexes needed)
- I6 DB bootstrap at daemon startup — v2.11
- APR ML optimization on factor_scores — v2.11 (requires 30-90 days of counterfactual_pnl_r)
