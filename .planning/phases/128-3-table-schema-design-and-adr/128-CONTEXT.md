# Phase 128: 3-Table Schema Design and ADR — Context

**Gathered:** 2026-06-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Define the full 3-table schema (signal_events / trade_frames / trade_executions) with all column types, FK constraints, and index strategy. Write the ADR. Produce runnable CREATE TABLE SQL DDL so Phase 129 migration has zero open design questions.

Also in scope: `capture_signal_features()` deletion (deferred from Phase 126 D-10), G0 audit (signal_id hash consistency across entry_types), and `signal_ledger_v2` view SQL.

**Not in scope:** Executing the migration (Phase 129), rewriting writers/trackers/APIs to use the new schema (Phase 130), CounterfactualTracker daemon (Phase 130), clean replay (Phase 127 — runs after 128+129+130).

</domain>

<decisions>
## Implementation Decisions

### D-01: Architecture — 3-table is non-negotiable
3-table (signal_events / trade_frames / trade_executions) is the only correct design. Decided in the v2.10 refactor doc. No open question here — downstream agents must not revisit it.

Cardinality: 1 signal_event → N trade_frames (one per entry_type); 1 trade_frame → 0-1 trade_executions. `counterfactual_pnl_r` is a required first-class column on trade_frames — always populated by CounterfactualTracker regardless of execution.

### D-02: signal_events full schema

**First-class columns (all indexed where noted):**

| Column | Type | Index | Notes |
|--------|------|-------|-------|
| `signal_id` | `uuid` | PK (with ts) | Canonical identifier |
| `ts` | `timestamptz` | PK (with signal_id); hypertable dim | Bar timestamp at fire time |
| `symbol` | `text` | btree (symbol, ts) | |
| `timeframe` | `text` | | |
| `setup_plugin` | `text` | btree (setup_plugin, ts) | |
| `direction` | `text` | | `long` / `short` — text, not integer |
| `raw_confidence` | `float8` | | Intrinsic composite; immutable after emit |
| `calibrated_confidence` | `float8` | | Nullable; async-populated by calibration pipeline |
| `cis_score` | `float8` | | Composite intelligence score at fire time |
| `weights_version` | `int4` | | CIS weight version; ML trains on homogeneous segments |
| `factor_scores` | `jsonb` | | Per-plugin factor breakdown; ML weight optimization |
| `context_features` | `jsonb` | | Full flat_features snapshot; SignalRanker feature matrix |
| `ctf_score` | `float8` | btree (ctf_confirmed, ts) | Nullable; I6 alignment at emit |
| `ctf_confirmed` | `bool` | btree (ctf_confirmed, ts) | Nullable |
| `zone_friction_score` | `float8` | | Nullable; zone friction at emit |
| `hmm_regime_at_fire` | `int4` | btree (hmm_regime_at_fire, ts) | Regime segmentation — ML first-class dimension |
| `plugin_regime_type` | `text` | | Plugin's declared regime type |
| `garch_sigma_at_fire` | `float8` | | Volatility context at fire; ML feature |
| `is_shadow` | `bool` | btree (is_shadow) | Governance filter; every ML query uses it |
| `is_backfill` | `bool` | btree (is_backfill) | Training corpus provenance |
| `status` | `text` | btree (status, ts) | `pending` / `active` / `regime_suppressed` / `expired` |
| `signal_schema_version` | `int4` | | Schema version at write time (int4, not text) |
| `ttl_bars` | `int4` | | Lifecycle; max bars signal remains active |
| `expires_at` | `timestamptz` | btree (expires_at) WHERE NOT NULL | Lifecycle expiry |
| `signal_computed_at` | `timestamptz` | | Pipeline write wall-clock; latency = signal_computed_at - ts |
| `created_at` | `timestamptz` | | Synonym for signal_computed_at; DB insertion time |

**Into context_features JSONB (not first-class columns):** `bucket_scores`, fine-grained CIS sub-scores, other flat_features values already captured at emit time.

**Dropped from signal_ledger (not migrated):**
- `signal_type` — redundant with `setup_plugin` in new schema
- `feature_ts`, `feature_tf` — duplicates of `ts`, `timeframe`
- `feature_schema_version` — superseded by `signal_schema_version int4`
- `pipeline_lag_ms` — computable as `signal_computed_at - ts`

**Hypertable:** YES. `signal_events` is a TimescaleDB hypertable partitioned on `ts`, chunk interval 7 days (matching signal_ledger), compression enabled with 7-day compress lag. PK must be composite: `(signal_id, ts)`.

### D-03: trade_frames full schema

**First-class columns:**

| Column | Type | Notes |
|--------|------|-------|
| `frame_id` | `uuid` | PK |
| `signal_id` | `uuid` | FK → signal_events(signal_id, ts) — must match hypertable PK |
| `signal_ts` | `timestamptz` | Denormalized from signal_events; required for FK to hypertable PK |
| `entry_type` | `text` | `at_close` / `at_pullback` / `at_limit` / `at_reclaim` / `zone_proximal` |
| `direction` | `text` | `long` / `short` |
| `entry_price` | `float8` | Hypothetical entry |
| `stop_price` | `float8` | |
| `target_price` | `float8` | |
| `r_per_unit` | `float8` | (target - entry) / (entry - stop) |
| `ttl_bars` | `int4` | Counterfactual measurement window |
| `expires_at` | `timestamptz` | When counterfactual measurement closes |
| `counterfactual_pnl_r` | `float8` | Always populated by CounterfactualTracker; ML target variable |
| `counterfactual_mfe` | `float8` | Max favorable excursion |
| `counterfactual_mae` | `float8` | Max adverse excursion |
| `counterfactual_bars` | `int4` | Bars to exit |
| `counterfactual_exit_reason` | `text` | `target_hit` / `stop_hit` / `ttl_expired` |
| `counterfactual_measured_at` | `timestamptz` | When CounterfactualTracker closed measurement |
| `was_selected` | `bool` | Selected by aggregator for potential execution |
| `frame_details` | `jsonb` | Stop architecture provenance (see below) |
| `created_at` | `timestamptz` | |

**`frame_details` JSONB contains stop architecture diagnostic fields:** `stop_basis`, `stop_type_col`, `structural_stop_distance_atr`, `adaptive_buffer_mult`, `stop_structure_type`, `stop_structure_age_bars`, `chandelier_vol_source`, `trailing_stop_price`, `trailing_stop_tightening_rate`, `entry_zone_low`, `entry_zone_high`. These are causal inputs that produced the frame geometry — diagnostic/audit fields, not ML query dimensions.

**Indexes:** `(signal_id, signal_ts)`, `(entry_type, counterfactual_pnl_r)`, `(was_selected, counterfactual_pnl_r)`.

**Shadow tracking (shadow_mae, shadow_mfe, shadow_outcome, shadow_tracking_start_ts):** DROPPED from new schema. CounterfactualTracker supersedes shadow P&L tracking. During Phase 129 migration, copy historical shadow values into `frame_details` JSONB for archival — never discard training history.

**Hypertable:** NO. trade_frames is a regular table. Time-range queries go via JOIN to signal_events. `signal_ts` denormalization enables time filtering on trade_frames directly when needed.

### D-04: trade_executions full schema

| Column | Type | Notes |
|--------|------|-------|
| `execution_id` | `uuid` | PK |
| `frame_id` | `uuid` | FK → trade_frames(frame_id) |
| `actual_fill_price` | `float8` | Live fill |
| `actual_exit_price` | `float8` | |
| `actual_pnl_r` | `float8` | Live outcome |
| `actual_mfe` | `float8` | |
| `actual_mae` | `float8` | |
| `actual_bars` | `int4` | |
| `market_entry_price` | `float8` | Actual market entry (vs hypothetical entry_price) |
| `market_entry_gap_bars` | `int4` | Bars between signal fire and actual fill |
| `exit_reason` | `text` | |
| `executed_at` | `timestamptz` | |
| `exited_at` | `timestamptz` | |

**Indexes:** `(frame_id)`, `(executed_at)`.

**Hypertable:** NO.

### D-05: signal_ledger_v2 backward-compat view

```sql
CREATE VIEW signal_ledger_v2 AS
SELECT
    se.signal_id,
    se.ts,
    se.symbol,
    se.timeframe,
    se.setup_plugin,
    se.direction,
    se.raw_confidence,
    se.calibrated_confidence,
    se.cis_score,
    se.factor_scores,
    se.context_features,
    se.ctf_score,
    se.ctf_confirmed,
    se.zone_friction_score,
    se.hmm_regime_at_fire,
    se.plugin_regime_type,
    se.is_shadow,
    se.is_backfill,
    se.status,
    se.signal_schema_version,
    se.ttl_bars,
    se.expires_at,
    tf.frame_id,
    tf.entry_type,
    tf.entry_price,
    tf.stop_price,
    tf.target_price,
    tf.r_per_unit,
    tf.counterfactual_pnl_r,
    tf.counterfactual_mfe,
    tf.counterfactual_mae,
    tf.counterfactual_exit_reason,
    tf.was_selected,
    te.execution_id,
    te.actual_pnl_r,
    te.actual_fill_price,
    te.actual_exit_price,
    te.exit_reason,
    te.executed_at,
    te.exited_at
FROM signal_events se
LEFT JOIN trade_frames tf ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts
LEFT JOIN trade_executions te ON te.frame_id = tf.frame_id;
```

`signal_ledger_full` (from migration 095) is superseded by `signal_ledger_v2` after Phase 129.

### D-06: Numeric types
`float8` throughout for all prices, confidence values, P&L. No `float4` — precision matters for pnl_r and confidence deltas. `numeric` from the old signal_ledger (entry_price, stop_loss) converts to `float8` in the new schema.

### D-07: direction column type
`text` (`long` / `short`) — not `integer`. The current signal_ledger uses `direction integer` (1/-1). Phase 129 migration converts to text.

### D-08: Phase 128 output deliverables
1. ADR at `docs/architecture/signal-trade-separation-ADR.md` — sections: Context (monolith problems), Decision (3-table + rationale), Consequences (migration scope, FK design, CounterfactualTracker dependency), Alternatives Considered (2-table rejected), Full Schema Tables
2. `db/migrations/NNN_3table_schema.sql` — runnable CREATE TABLE DDL + CREATE VIEW signal_ledger_v2 (Phase 129 executes this, not Phase 128)
3. `capture_signal_features()` deletion — grep for external callers first; delete from `src/intelligence/trading/confidence_utils.py` and any call sites (Phase 126 D-10 explicitly deferred to Phase 128)
4. G0 audit — run `grep -n "entry_type" src/intelligence/trading/*.py | grep "make_signal_from_frame"` and confirm signal_id is identical across all entry_type variants per plugin fire; document findings in ADR

### D-09: G0 writer grouping strategy
Documented in ADR (not implemented in Phase 128 — that's Phase 130). The ADR must include the Phase 130 writer contract (from v2.10 doc section G0): group signals by signal_id, insert ONE signal_events row per group using detection fields from first signal, insert N trade_frames rows (one per entry_type).

### Claude's Discretion
- Migration numbering (NNN) — use next available after 136
- Whether to add GIN index on `context_features` or `factor_scores` — check query patterns in existing codebase; add only if ML training queries filter JSONB fields inline
- Exact hypertable chunk interval — 7 days recommended (matches signal_ledger pattern)
- TimescaleDB compression policy settings — match existing signal_ledger compression config

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Primary Design Document
- `docs/plans/2026-06-14-v2.10-signal-architecture-refactor.md` §"Workstream B: 3-Table Signal Architecture (Phases 128-130)" — Full Phase 128 schema tables, cardinality decisions, G0 writer grouping contract, ADR task list (G1-G3), Phase 128 success criteria. **MUST read before writing any DDL.**

### Live Schema (authoritative current state)
- Run `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "\d signal_ledger"` to see all 50+ current columns; Phase 129 migration maps each to the 3-table schema per decisions above.

### Architecture Foundation
- `docs/architecture/signal-trade-separation-ADR.md` — **output of this phase** (does not exist yet; planner must create it)
- `docs/architecture/setup-confidence-patterns.md` — ECL pattern spec; governs which fields are extrinsic vs intrinsic
- `docs/foundation/naming-system.md` — naming conventions for new tables/columns

### Code Files (for capture_signal_features() deletion audit)
- `src/intelligence/trading/confidence_utils.py` — `capture_signal_features()` definition (marked deprecated since Phase 126)
- `src/intelligence/signal_processor.py` — `_annotate_signal()` replacement (Phase 126 pipeline annotation)

### Migration Patterns
- `production/migrations/136_phase126_i7_apr_params.sql` — most recent migration; use as template for numbering and structure

### Requirements
- `REQUIREMENTS.md` §"ARCH-01" — primary requirement for this phase
- `CLAUDE.md` §"Data Flow / TimescaleDB Tables" — signal architecture section (signal_events, trade_frames, trade_executions descriptions)
- `CLAUDE.md` §"Signal Logic" — signal table column canonical list for Phase 128+

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `production/migrations/136_phase126_i7_apr_params.sql` — migration file structure and SQL style to follow for the new DDL
- `src/core/database_manager.py` — asyncpg connection pool; all new table interactions use this
- `src/intelligence/trading/confidence_utils.py` — `capture_signal_features()` function to delete (Phase 126 D-10)

### Established Patterns
- TimescaleDB hypertable: `CREATE TABLE ... ; SELECT create_hypertable(...);` pattern — check existing migrations (signal_ledger, intelligence_features) for exact syntax
- FK to hypertable requires all PK columns: `FOREIGN KEY (signal_id, signal_ts) REFERENCES signal_events(signal_id, ts)` — standard FK won't work against composite PK
- Compression policy: `SELECT add_compression_policy(...)` after `ALTER TABLE ... SET (timescaledb.compress, ...)` — check existing signal_ledger policy for settings

### Integration Points
- `src/intelligence/trading/signal_schema.py` — `SIGNAL_SCHEMA_VERSION` constant; ADR should note that Phase 129 migration bumps this
- `src/intelligence/pipeline/signal_processor.py` — `_annotate_signal()` now the sole `capture_signal_features()` caller after Phase 126; confirm this before deletion
- Dashboard queries using `signal_ledger_full` view — after Phase 129, redirect to `signal_ledger_v2`

</code_context>

<specifics>
## Specific Ideas

### Hypertable FK Pattern (critical for Phase 130 writer)
Because signal_events is a hypertable with composite PK `(signal_id, ts)`, trade_frames CANNOT have a standard single-column FK on `signal_id` alone. The FK must be:
```sql
FOREIGN KEY (signal_id, signal_ts) REFERENCES signal_events (signal_id, ts)
```
This is why `signal_ts timestamptz` is a first-class column on trade_frames — it's the FK anchor, not just a convenience denormalization.

### Column count reality check
The live signal_ledger has ~50 columns. Phase 128 schema design for signal_events adds ~10 columns beyond the v2.10 doc baseline. This is intentional and correct — the v2.10 doc was a starting-point schema, not the final schema. The additional columns are all first-class ML segmentation or lifecycle fields that would be slow or painful as JSONB.

### G0 Audit Gate
Before Phase 129 can run, confirm via grep:
```bash
grep -n "entry_type" src/intelligence/trading/*.py | grep "make_signal_from_frame"
```
Any plugin calling `make_signal_from_frame()` twice with different entry_types must produce identical `signal_id` values. `make_signal_id()` hashes `(symbol, bar_ts, tf, OHLCV, setup_plugin)` — entry_type is NOT in the hash. If any plugin uses different OHLCV inputs per entry_type, it would generate different signal_ids → orphaned trade_frames rows post-migration.

### capture_signal_features() deletion pre-flight
Before deleting:
```bash
grep -rn "capture_signal_features" src/
```
Expected: only `confidence_utils.py` (definition) and `signal_processor.py` (one call in `_annotate_signal()`, which Phase 126 was supposed to deprecate but keep). Verify the call in `signal_processor.py` now uses `_annotate_signal()` directly, then delete `capture_signal_features()` from `confidence_utils.py`.

</specifics>

<deferred>
## Deferred Ideas

- GIN indexes on `context_features` or `factor_scores` — defer to Phase 129 after seeing actual ML query patterns; don't add speculatively
- `is_shadow` → `governance_flags jsonb` consolidation (was_selected, is_shadow, is_backfill as JSONB) — rejected; these are separate boolean governance dimensions that need independent indexes
- `calibrated_confidence` async update pattern (via UPDATE instead of INSERT) — Phase 130 implementation detail; Phase 128 schema just ensures the column is nullable
- I6 DB bootstrap at daemon startup — v2.11 (requires intelligence_features accumulation), noted in REQUIREMENTS.md Future
- APR ML optimization on factor_scores — v2.11 (requires 30-90 days of counterfactual_pnl_r data)
- Reviewed Todos (not folded):
  - "Quant Pipeline Modularization (P-QUANT-01)" — architecture phase but different domain; defer
  - "SR Strength Calibration" — signal ledger related but requires replay data first; defer to v2.11

</deferred>

---

*Phase: 128-3-table-schema-design-and-adr*
*Context gathered: 2026-06-15*
