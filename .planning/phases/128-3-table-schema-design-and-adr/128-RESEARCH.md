# Phase 128: 3-Table Schema Design and ADR - Research

**Researched:** 2026-06-15
**Domain:** TimescaleDB schema design, ADR authoring, PostgreSQL DDL patterns
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01:** 3-table architecture is non-negotiable — signal_events (hypertable) / trade_frames (regular) / trade_executions (regular). Cardinality: 1 signal_event → N trade_frames (one per entry_type); 1 trade_frame → 0-1 trade_executions. `counterfactual_pnl_r` is first-class on trade_frames, always populated.

**D-02:** signal_events full schema — see CONTEXT.md table (26 columns). Hypertable partitioned on `ts`, chunk interval 7 days, compression enabled with 7-day lag. Composite PK `(signal_id, ts)`.

**D-03:** trade_frames full schema — see CONTEXT.md table (20 columns). Regular table. Indexes: `(signal_id, signal_ts)`, `(entry_type, counterfactual_pnl_r)`, `(was_selected, counterfactual_pnl_r)`. FK: `FOREIGN KEY (signal_id, signal_ts) REFERENCES signal_events (signal_id, ts)`.

**D-04:** trade_executions full schema — see CONTEXT.md table (13 columns). Regular table. Indexes: `(frame_id)`, `(executed_at)`.

**D-05:** signal_ledger_v2 view SQL — fully written in CONTEXT.md. LEFT JOINs signal_events → trade_frames → trade_executions.

**D-06:** float8 throughout for all prices, confidence values, P&L. No float4, no numeric.

**D-07:** direction column type is `text` (`long` / `short`), not integer. Converts from signal_ledger's `direction integer`.

**D-08:** Phase 128 deliverables: (1) ADR at `docs/architecture/signal-trade-separation-ADR.md`, (2) DDL file at `db/migrations/NNN_3table_schema.sql`, (3) capture_signal_features() deletion, (4) G0 audit documented in ADR.

**D-09:** G0 writer grouping strategy documented in ADR — Phase 130 implementation detail; group by signal_id, insert ONE signal_events row per group, N trade_frames rows.

### Claude's Discretion

- Migration numbering (NNN) — use next available after 136
- Whether to add GIN index on `context_features` or `factor_scores` — check query patterns
- Exact hypertable chunk interval — 7 days recommended
- TimescaleDB compression policy settings — match existing signal_ledger compression config

### Deferred Ideas (OUT OF SCOPE)

- GIN indexes on context_features/factor_scores — defer to Phase 129 after seeing actual ML query patterns
- `is_shadow` → `governance_flags jsonb` consolidation — rejected
- `calibrated_confidence` async update pattern — Phase 130 implementation detail
- I6 DB bootstrap at daemon startup — v2.11
- APR ML optimization on factor_scores — v2.11

</user_constraints>

---

## Summary

Phase 128 is a design-and-documentation phase: no runtime code changes, no migration execution. The full schema is already locked in CONTEXT.md. What remains is authoring the ADR, producing the runnable DDL file, deleting a deprecated function, and running a signal_id consistency audit.

The live signal_ledger has 47 columns as a TimescaleDB hypertable with 53 chunks, partitioned on `timestamp` (note: new schema uses `ts` not `timestamp`), 7-day chunks, compression enabled at 7-day lag, segmented by `(symbol, timeframe)` for compression ordering. Next migration number is 137.

The `capture_signal_features()` function in `confidence_utils.py` has zero live callers. It is only referenced in comments and docstrings in `signal_processor.py`, `feature_builder.py`, and `ml_scorer_agent.py`. Safe to delete.

**Primary recommendation:** Produce all four deliverables in a single task sequence: G0 audit first (gates the ADR findings), then DDL file, then ADR, then capture_signal_features() deletion.

---

## Live Schema State (signal_ledger migration mapping reference)

### Current signal_ledger columns (47 total, from `\d signal_ledger`)

| Column | Type | Disposition in 3-table |
|--------|------|------------------------|
| signal_id | uuid | → signal_events.signal_id |
| timestamp | timestamptz | → signal_events.ts (renamed) |
| symbol | text | → signal_events.symbol |
| timeframe | text | → signal_events.timeframe |
| setup_plugin | text | → signal_events.setup_plugin |
| signal_type | text | **DROPPED** — redundant with setup_plugin |
| direction | integer | → signal_events.direction text (1/-1 → long/short) |
| was_selected | boolean | → trade_frames.was_selected |
| is_shadow | boolean | → signal_events.is_shadow |
| is_backfill | boolean | → signal_events.is_backfill |
| signal_schema_version | text | → signal_events.signal_schema_version int4 (type change) |
| signal_computed_at | timestamptz | → signal_events.signal_computed_at |
| feature_ts | timestamptz | **DROPPED** — duplicate of ts |
| feature_tf | text | **DROPPED** — duplicate of timeframe |
| hmm_regime_at_fire | integer | → signal_events.hmm_regime_at_fire int4 |
| garch_sigma_at_fire | double precision | → signal_events.garch_sigma_at_fire float8 |
| ttl_bars | integer | → signal_events.ttl_bars int4 |
| entry_price | numeric | → trade_frames.entry_price float8 (type change) |
| stop_loss | numeric | → trade_frames.stop_price float8 (renamed + type change) |
| targets | jsonb | → trade_frames.target_price float8 (primary target extracted) |
| entry_zone_low | numeric | → trade_frames.frame_details JSONB |
| entry_zone_high | numeric | → trade_frames.frame_details JSONB |
| market_entry_price | double precision | → trade_executions.market_entry_price float8 |
| cis_score | double precision | → signal_events.cis_score float8 |
| bucket_scores | jsonb | → signal_events.context_features JSONB (subsumed) |
| weights_version | integer | → signal_events.weights_version int4 |
| pipeline_lag_ms | double precision | **DROPPED** — computable as signal_computed_at - ts |
| expires_at | timestamptz | → signal_events.expires_at |
| feature_schema_version | integer | **DROPPED** — superseded by signal_schema_version int4 |
| stop_basis | text | → trade_frames.frame_details JSONB |
| stop_type_col | text | → trade_frames.frame_details JSONB |
| structural_stop_distance_atr | double precision | → trade_frames.frame_details JSONB |
| adaptive_buffer_mult | double precision | → trade_frames.frame_details JSONB |
| plugin_regime_type | text | → signal_events.plugin_regime_type |
| stop_structure_type | text | → trade_frames.frame_details JSONB |
| stop_structure_age_bars | integer | → trade_frames.frame_details JSONB |
| chandelier_vol_source | text | → trade_frames.frame_details JSONB |
| trailing_stop_price | jsonb | → trade_frames.frame_details JSONB |
| trailing_stop_tightening_rate | double precision | → trade_frames.frame_details JSONB |
| staleness_score | double precision | **No new home** — not in CONTEXT.md schema; treat as drop |
| staleness_trigger_reason | text | **No new home** — not in CONTEXT.md schema; treat as drop |
| shadow_tracking_start_ts | timestamptz | → trade_frames.frame_details JSONB (archival) |
| shadow_mae | double precision | → trade_frames.frame_details JSONB (archival) |
| shadow_mfe | double precision | → trade_frames.frame_details JSONB (archival) |
| shadow_outcome | text | → trade_frames.frame_details JSONB (archival) |
| raw_confidence | double precision | → signal_events.raw_confidence float8 |
| calibrated_confidence | double precision | → signal_events.calibrated_confidence float8 |

**Not in signal_ledger but new in 3-table schema (added in CONTEXT.md D-02):**
- signal_events: `factor_scores` (jsonb), `context_features` (jsonb), `ctf_score`, `ctf_confirmed`, `zone_friction_score`, `is_backfill`, `status`, `ttl_bars`, `signal_computed_at`, `created_at`, `cis_score`, `weights_version`, `plugin_regime_type`, `garch_sigma_at_fire`, `hmm_regime_at_fire`
- trade_frames: all counterfactual_* columns, `signal_ts`, `r_per_unit`, `ttl_bars`, `expires_at`, `frame_details`
- trade_executions: entirely new table

---

## Migration Number

Next migration after 136 is **137**. File: `db/migrations/137_3table_schema.sql`.

Note: CONTEXT.md D-08 references path `db/migrations/NNN_3table_schema.sql` not `production/migrations/NNN_...`. Confirm which directory is canonical before writing the file. The existing migrations live at `production/migrations/`. The planner should use `production/migrations/137_3table_schema.sql`.

---

## Hypertable Configuration to Replicate

From live signal_ledger (confirmed via TimescaleDB system catalog):

```sql
-- Chunk interval: 7 days
SELECT create_hypertable('signal_events', 'ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE);

-- Compression: enabled, segmented by (symbol, timeframe), ordered by ts DESC
ALTER TABLE signal_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol,timeframe',
    timescaledb.compress_orderby = 'ts DESC'
);

-- Compression policy: compress chunks older than 7 days, run every 12 hours
SELECT add_compression_policy('signal_events', INTERVAL '7 days');
```

**Confidence:** HIGH — sourced directly from `timescaledb_information.compression_settings` and `timescaledb_information.jobs` on the live DB.

The compression job schedule (12h interval) is system-managed by TimescaleDB after `add_compression_policy()` is called — do not specify schedule manually.

---

## capture_signal_features() Deletion Audit

**Result: SAFE TO DELETE. Zero live callers.**

All grep hits in `src/` are:
1. `src/intelligence/CLAUDE.md:26` — documentation reference (update after deletion)
2. `src/intelligence/trading/confidence_utils.py:10,174` — the definition itself
3. `src/intelligence/pipeline/signal_processor.py:85` — comment in docstring: "No plugin may call capture_signal_features()"
4. `src/intelligence/ml/feature_builder.py:34` — comment: "25 keys verbatim from confidence_utils.py capture_signal_features()"
5. `src/intelligence/trading/signal_schema.py:18` — comment noting the transition

**No file calls `capture_signal_features(` as a function.** The comment in `signal_processor.py` line 85 is a prohibition ("No plugin may call..."), not a call. The references in `feature_builder.py` and `signal_schema.py` are documentation of historical key origins, not calls.

**Side-effect caution:** `feature_builder.py` has `SHADOW_FEATURE_KEYS` constant (25 keys from the old capture_signal_features output). These keys are used for querying historical signal_ledger rows. After capture_signal_features() is deleted, `SHADOW_FEATURE_KEYS` must remain — it references the key names, not the function. No change needed to feature_builder.py.

**After deletion**, update `src/intelligence/CLAUDE.md` line 26 to remove the `capture_signal_features()` entry from the confidence_utils.py row description.

---

## G0 Audit: signal_id Consistency Across entry_types

**Finding: signal_id is entry_type-agnostic. The hash is safe for 3-table FK.**

`make_signal_id()` in `signal_schema.py` lines 73-103 hashes: `(symbol, feature_ts_ns, feature_tf, open, high, low, close, volume, setup_plugin, direction)`. **entry_type is NOT in the hash.**

Plugins found calling `make_signal_from_frame()` multiple times per detection (potential multi-entry_type filers):

- **gap_analysis_setup.py** — sets `entry_type` conditionally (`at_limit` or `at_pullback` depending on gap type) then calls `make_signal_from_frame()` once. One fire = one entry_type. No collision risk.
- **divergence_stack.py** — calls `make_signal_from_frame()` once per detection (inside the loop body at line 289, not looping over entry_types). One fire = one entry_type.
- All other plugins (cross_asset_divergence, cvd_divergence, choch_reversal, orb30, orb15, anchored_vwap_reversion, squeeze_expansion, fvg_fill, dual_divergence, microstructure_utils, hvn_rejection, liquidity_hunt, lvn_breakout, mtf_alignment, momentum_breakout, mean_reversion, failed_breakout, ofi_divergence, poc_rejection, pattern_completion) — each calls `make_signal_from_frame()` once per fire.

**G0 verdict:** No plugin currently generates multiple signals with different entry_types from the same plugin fire event. Each plugin fire produces one signal dict with one entry_type. Post-migration, signal_events will have one row per fire, trade_frames will have one row per fire (not N). The N-frame cardinality is a future capability (Phase 130 writer can produce multiple frames per fire) but no existing plugin exercises it today.

**ADR implication:** Document that the current 1:1 signal-to-frame mapping is a Phase 130+ expansion target, not the current state. Phase 130 writer must handle the grouping contract but today there are no duplicate signal_ids in any Kafka payload.

---

## Architecture Patterns

### Hypertable DDL Pattern (from migration 095, confirmed canonical)

```sql
-- From production/migrations/095_signal_ledger_split.sql
CREATE TABLE signal_events (...);
SELECT create_hypertable('signal_events', 'ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE);
```

### Composite PK on Hypertable

```sql
-- Hypertable PK must include the time dimension column
ALTER TABLE signal_events ADD PRIMARY KEY (signal_id, ts);
```

This is required because TimescaleDB partitions by `ts` — unique constraints on hypertables must include all partitioning columns.

### FK from Regular Table to Hypertable

```sql
-- trade_frames must carry signal_ts (denormalized) to satisfy FK
FOREIGN KEY (signal_id, signal_ts) REFERENCES signal_events (signal_id, ts)
```

A single-column FK on `signal_id` alone will fail: PostgreSQL requires FK targets to match a unique constraint exactly, and the hypertable PK is `(signal_id, ts)`.

### Migration File Style (from migration 136)

- Header comment block: migration number, purpose, what it wires, ML/provenance notes
- Logical sections separated by `-- ---` dividers with section names
- `ON CONFLICT ... DO NOTHING` for idempotent seeds
- No transaction wrappers in individual migration files (applied by runner)

### GIN Indexes — Not Used

Neither `signal_ledger` nor `intelligence_features` has GIN indexes on any JSONB column. The existing pattern is btree-only. Per CONTEXT.md deferred section, GIN on `context_features` or `factor_scores` is deferred until ML training query patterns are known. **Do not add GIN indexes in Phase 128 DDL.**

---

## ADR Structure

No existing ADR file at `docs/architecture/signal-trade-separation-ADR.md`. The four existing architecture docs are:
- `architecture-dag-topology.md`
- `architecture-evolution.md`
- `architecture-overview.md`
- `setup-confidence-patterns.md`

The v2.10 refactor doc (Workstream B, G1 task) specifies these ADR sections: Context (monolith problems), Decision (3-table), Consequences (migration scope, FK design, CounterfactualTracker dependency), Alternatives Considered (2-table rejected).

CONTEXT.md D-08 expands this to also include: Full Schema Tables, and the G0 writer grouping strategy from D-09.

---

## Common Pitfalls

### Pitfall 1: Single-column FK to hypertable
**What goes wrong:** `FOREIGN KEY (signal_id) REFERENCES signal_events(signal_id)` fails at DDL time — PostgreSQL cannot satisfy FK against a non-unique column when the PK is composite.
**Prevention:** Always `FOREIGN KEY (signal_id, signal_ts) REFERENCES signal_events (signal_id, ts)`. This is why `signal_ts timestamptz` is a first-class column on trade_frames.

### Pitfall 2: Compression segmentby columns must not be nullable
**What goes wrong:** TimescaleDB rejects compression settings if segmentby columns contain nulls.
**Prevention:** `symbol` and `timeframe` are both `NOT NULL` on signal_events (matches signal_ledger pattern).

### Pitfall 3: direction column type in existing code
**What goes wrong:** Phase 129 migration converts `direction integer` (1/-1) to `direction text` (long/short). Writers, validators, and queries that compare `direction = 1` will break silently.
**Prevention:** ADR must note the type change. Phase 130 is the cutover point for writer code changes. The DDL in Phase 128 defines the new schema; Phase 129 executes the data migration.

### Pitfall 4: signal_schema_version type change
**What goes wrong:** signal_ledger has `signal_schema_version text`; new schema uses `signal_schema_version int4`. The SIGNAL_SCHEMA_VERSION constant in `signal_schema.py` is already an integer — this is a correction, not a new constraint.
**Prevention:** Phase 129 migration must cast: `CAST(signal_schema_version AS int4)` during data copy.

### Pitfall 5: staleness_score / staleness_trigger_reason not mapped
**What goes wrong:** These two columns exist in signal_ledger but are absent from CONTEXT.md D-02 schema and appear nowhere in the v2.10 doc.
**Prevention:** Treat as dropped. The ADR should explicitly list them as "not migrated — no new home in 3-table design." Do not add them to signal_events without a CONTEXT.md decision.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead |
|---------|-------------|-------------|
| Hypertable partitioning | Custom sharding | `SELECT create_hypertable(...)` |
| Compression policy scheduling | cron + pg_cron | `SELECT add_compression_policy(...)` |
| TimescaleDB chunk management | Manual partition DDL | TimescaleDB auto-management |

---

## Open Questions

1. **DDL file location: `db/migrations/` vs `production/migrations/`**
   - What we know: CONTEXT.md D-08 says `db/migrations/NNN_3table_schema.sql`. All 136 existing migrations are in `production/migrations/`.
   - What's unclear: Is `db/migrations/` a new parallel path, or a typo?
   - Recommendation: Use `production/migrations/137_3table_schema.sql` to match established convention. The planner should note this discrepancy and resolve with the existing path.

2. **staleness_score / staleness_trigger_reason disposition**
   - What we know: Present in signal_ledger; absent from CONTEXT.md schema.
   - What's unclear: Were they intentionally dropped or accidentally omitted?
   - Recommendation: ADR explicitly lists them as dropped. If they were staleness/quality signals useful to ML, they would have appeared in the CONTEXT.md schema design. Drop is correct.

3. **`created_at` vs `signal_computed_at` — both on signal_events**
   - What we know: CONTEXT.md D-02 lists both columns with the note "Synonym for signal_computed_at; DB insertion time".
   - What's unclear: Whether Phase 129 populates both identically or one is derived from the other.
   - Recommendation: DDL defines both; Phase 130 writer populates `signal_computed_at` from payload and `created_at` as `DEFAULT now()`. ADR should note the distinction.

---

## Sources

### Primary (HIGH confidence)
- Live DB inspection via psql — signal_ledger schema, hypertable config, compression settings, job schedule
- `production/migrations/095_signal_ledger_split.sql` — hypertable creation pattern
- `production/migrations/136_phase126_i7_apr_params.sql` — migration file style
- `src/intelligence/trading/signal_schema.py` lines 73-103 — make_signal_id() hash inputs (G0 audit)
- `src/intelligence/trading/confidence_utils.py` — capture_signal_features() definition + deprecation notice
- `grep -rn "capture_signal_features(" src/` — zero live callers confirmed
- `docs/plans/2026-06-14-v2.10-signal-architecture-refactor.md` lines 1045-1244 — Workstream B, ADR structure
- `timescaledb_information.compression_settings` + `timescaledb_information.jobs` — live compression config

### Secondary (MEDIUM confidence)
- `src/intelligence/ml/feature_builder.py` — SHADOW_FEATURE_KEYS (25 keys from old capture_signal_features) confirmed as comment-only reference, not a call

---

## Metadata

**Confidence breakdown:**
- Live schema state: HIGH — directly queried from DB
- Next migration number: HIGH — ls production/migrations/ confirmed 136 is last
- capture_signal_features() callers: HIGH — grep confirmed zero live calls
- Hypertable config: HIGH — confirmed from timescaledb system catalogs
- G0 audit: HIGH — read make_signal_id() source + checked all make_signal_from_frame() call sites
- GIN index decision: HIGH — confirmed no GIN indexes exist in codebase; deferred per CONTEXT.md
- ADR structure: HIGH — Workstream B specifies sections exactly

**Research date:** 2026-06-15
**Valid until:** 2026-07-15 (stable domain; schema and migration patterns don't change)
