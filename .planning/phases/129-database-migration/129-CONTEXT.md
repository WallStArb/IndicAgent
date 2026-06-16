# Phase 129: Database Migration — Context

**Gathered:** 2026-06-16
**Status:** Ready for planning
**Source:** Phase 128 CONTEXT.md + live DB state + ADR + v2.10 spec

<domain>
## Phase Boundary

Execute the 3-table signal architecture migration:
1. Apply missing Plan 04 columns to live DB (ALTER TABLE — not yet applied after Phase 128-04 did not execute)
2. Write and run `production/scripts/migrate_signal_ledger.py` to copy 1.44M signal_ledger rows into signal_events + trade_frames
3. Verify row counts; set signal_ledger read-only; bump SIGNAL_SCHEMA_VERSION

**Not in scope:** Rewriting writers/trackers/API endpoints (Phase 130). CounterfactualTracker (Phase 130). Dropping signal_ledger (Phase 130). Clean replay (Phase 127 — runs after 130).

### Pre-flight state confirmed (2026-06-16)

- **Tables exist** (applied during Phase 128 UAT): signal_events (0 rows), trade_frames (0 rows), trade_executions (0 rows)
- **signal_ledger_full view** exists (Phase 128 migration 137 DROP + CREATE)
- **signal_ledger** has 1,442,909 rows — source data for migration
- **Missing columns** — NOT yet applied (Phase 128-04 did not execute):
  - signal_events: feature_ts, concurrent_signal_count, concurrent_plugins
  - trade_frames: regime_at_activation
  - trade_executions: regime_at_exit

</domain>

<decisions>
## Implementation Decisions

### D-01: Column mapping — signal_events from signal_ledger
| signal_ledger column | signal_events column | Transform |
|---------------------|---------------------|-----------|
| signal_id | signal_id | none |
| timestamp | ts | column rename |
| symbol | symbol | none |
| timeframe | tf | column rename |
| setup_plugin | setup_plugin | none |
| direction (int) | direction (text) | 1→'long', -1→'short' |
| raw_confidence | raw_confidence | none |
| calibrated_confidence | calibrated_confidence | none |
| cis_score | cis_score | none |
| weights_version | weights_version | none |
| hmm_regime_at_fire | hmm_regime_at_fire | none |
| plugin_regime_type | plugin_regime_type | none |
| garch_sigma_at_fire | garch_sigma_at_fire | none |
| is_shadow | is_shadow | none |
| is_backfill | is_backfill | none |
| signal_schema_version (text) | signal_schema_version (int4) | NULLIF(signal_schema_version,'')::int4 |
| ttl_bars | ttl_bars | none |
| expires_at | expires_at | none |
| signal_computed_at | signal_computed_at | none |
| feature_ts | feature_ts | none (after Plan 04 columns added) |
| (none) | status | hardcode 'expired' for all historical rows |
| (none) | factor_scores | NULL — not in signal_ledger |
| (none) | context_features | NULL — not in signal_ledger |
| (none) | ctf_score | NULL — not in signal_ledger |
| (none) | ctf_confirmed | NULL — not in signal_ledger |
| (none) | zone_friction_score | NULL — not in signal_ledger |
| (none) | concurrent_signal_count | NULL — Phase 130 writer populates going forward |
| (none) | concurrent_plugins | NULL — Phase 130 writer populates going forward |

**Dropped from signal_ledger (no new home):** signal_type, feature_tf, pipeline_lag_ms, feature_schema_version, staleness_score, staleness_trigger_reason

### D-02: Column mapping — trade_frames from signal_ledger
One trade_frame per signal_ledger row.

| signal_ledger column | trade_frames column | Transform |
|---------------------|---------------------|-----------|
| signal_id | signal_id | FK anchor |
| timestamp | signal_ts | FK anchor (required for composite FK to hypertable) |
| (derived) | direction | same as signal_events.direction (1→'long', -1→'short') |
| (hardcoded) | entry_type | 'at_close' — historical rows had one entry_type; at_close is canonical default |
| entry_price (numeric) | entry_price (float8) | ::float8 cast |
| stop_loss (numeric) | stop_price (float8) | ::float8 cast |
| targets[0] | target_price (float8) | (targets->>0)::float8 — first element of JSON array |
| (computed) | r_multiple | (target_price - entry_price) / NULLIF(entry_price - stop_price, 0) |
| was_selected | was_selected | none |
| ttl_bars | ttl_bars | none |
| expires_at | expires_at | none |
| (none) | counterfactual_pnl_r | NULL — CounterfactualTracker (Phase 130) |
| stop_basis, stop_type_col, etc. | frame_details (jsonb) | archive all stop architecture fields + shadow fields |
| (none) | regime_at_activation | NULL — Phase 130 TradeFrameWriter populates |

**frame_details JSONB:** Consolidates all stop architecture fields and historical shadow data:
```json
{
  "stop_basis": "...",
  "stop_type_col": "...",
  "structural_stop_distance_atr": 0.0,
  "adaptive_buffer_mult": 0.0,
  "stop_structure_type": "...",
  "stop_structure_age_bars": 0,
  "chandelier_vol_source": "...",
  "trailing_stop_price": {...},
  "trailing_stop_tightening_rate": 0.0,
  "entry_zone_low": 0.0,
  "entry_zone_high": 0.0,
  "shadow_tracking_start_ts": null,
  "shadow_mae": null,
  "shadow_mfe": null,
  "shadow_outcome": null,
  "targets_raw": [...]
}
```

### D-03: No trade_executions migration
signal_ledger has zero shadow outcomes (COUNT(shadow_outcome) = 0, confirmed). No live trades were tracked in the old schema. trade_executions starts empty — Phase 130 SignalTracker will populate on new live trades.

### D-04: status = 'expired' for all migrated rows
All 1.44M rows are historical (past TTL). Setting status='expired' is semantically correct. The migration uses hardcoded 'expired' — Phase 130 writers set the correct lifecycle status going forward.

### D-05: Migration batching — 10K rows per batch
1.44M rows requires batching to avoid: (1) OOM on asyncpg, (2) long-running transactions blocking TimescaleDB compression, (3) lock contention. 10K rows per batch with batch-level commit. Order by timestamp ASC to respect TimescaleDB chunk ordering.

### D-06: Idempotency via ON CONFLICT DO NOTHING
Both signal_events (PK: signal_id, ts) and trade_frames (UNIQUE: signal_id, entry_type) use ON CONFLICT DO NOTHING. The script can be restarted safely if interrupted — completed batches are skipped, incomplete batches retry.

### D-07: signal_ledger read-only via REVOKE
After migration completes and row counts verified, write migration 138_signal_ledger_readonly.sql:
```sql
REVOKE INSERT, UPDATE, DELETE ON signal_ledger FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE ON signal_ledger FROM postgres;
```
This is the "48-hour transition window" mechanism from ROADMAP.md. Phase 130 drops the table after verifying all writers use the new schema.

### D-08: SIGNAL_SCHEMA_VERSION bump
Bump the constant in `src/intelligence/trading/signal_schema.py` after migration completes. Signals written before the bump → old schema. Signals written after → new 3-table schema. ML training must segment on this boundary.

### Claude's Discretion
- Batch progress logging interval: every 50 batches (500K rows) for sanity output
- Dry-run mode: --dry-run flag that runs SELECT but no INSERT (for pre-validation)
- Error handling: log failed rows to a file, continue (don't abort entire migration for one bad row)
- frame_id generation: uuid.uuid4() in Python for each trade_frame row

</decisions>

<canonical_refs>
## Canonical References

### Schema Foundation (MUST read before implementing)
- `docs/signals/signal-trade-separation-ADR.md` — full column specs, FK design, Phase 130 writer contract
- `production/migrations/137_3table_schema.sql` — authoritative DDL (canonical schema for all 3 tables + view)
- `.planning/phases/128-3-table-schema-design-and-adr/128-CONTEXT.md` — D-02/D-03/D-04/D-05 locked decisions

### Live DB State (verify before altering)
- Run `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "\d signal_events"` — confirm which columns are missing
- Run `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "\d trade_frames"` — confirm regime_at_activation missing

### Code Reference
- `src/intelligence/trading/signal_schema.py` — SIGNAL_SCHEMA_VERSION constant to bump
- `production/migrations/136_phase126_i7_apr_params.sql` — migration file style template
- `src/core/database_manager.py` — asyncpg pool (migration script uses direct psycopg2 or asyncpg)

### Requirements
- `REQUIREMENTS.md` §MIGRATE-01 — primary requirement; verified row counts required

</canonical_refs>
