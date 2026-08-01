# ADR: 3-Table Signal Architecture (signal_events / trade_frames / trade_executions)

**Status:** Accepted
**Date:** 2026-06-15
**Deciders:** Brandon Goyette (system owner), Renaissance engineering council review
**Implements:** v2.10 Workstream B (Phases 128-130)
**Migration:** `production/migrations/137_3table_schema.sql` (Phase 129 executes)

---

> **Staleness note (2026-08-01):** The 3-table `signal_events`/`trade_frames`/`trade_executions`
> architecture this ADR decided on was itself archived along with the rest of the v2.x Signal
> Ledger Architecture (no live consumer as of 2026-07-02 per CLAUDE.md). The decision record
> remains valid history; it does not describe the live system. See CLAUDE.md's Architecture
> section.

## Context

The `signal_ledger` table was a correct v1 design for a single-tier signal persistence layer. As the system matured through Phases 120-127, it accumulated 47 columns mixing three distinct semantic concerns:

**Detection state** — what the plugin observed and computed: `raw_confidence`, `cis_score`, `factor_scores`, `ctf_score`, `ctf_confirmed`, `zone_friction_score`, `hmm_regime_at_fire`, `garch_sigma_at_fire`, `is_shadow`, `status`.

**Hypothesis state** — what entry to take if the signal fires: `entry_price`, `stop_loss`, `targets`, `entry_zone_low`, `entry_zone_high`, `stop_basis`, `stop_type_col`, `trailing_stop_price`, `ttl_bars`.

**Execution state** — what actually happened in the market: `market_entry_price`, and shadow tracking fields (`shadow_mae`, `shadow_mfe`, `shadow_outcome`).

This mixing creates three compounding problems:

**Problem 1: ML training bias (survivorship, null patterns).** The column `counterfactual_pnl_r` did not exist in v1. Adding it to `signal_ledger` produces rows where suppressed signals have `null` counterfactual P&L — the ML model trains on a filtered subset without knowing the filter exists. The model never sees what suppressed signals would have returned, so it cannot learn that suppression causes it to miss trades. This is Bias Layer 2 in the ECL bias taxonomy (Bias Layer 1 was emission suppression, fixed in Phase 123).

**Problem 2: Cardinality mismatch.** A signal can have multiple entry types (`at_close`, `at_pullback`, `at_limit`, `at_reclaim`, `zone_proximal`) — each representing a distinct trade hypothesis from the same detection event. The monolith forces one row per detection, which cannot express multiple simultaneous hypotheses. Any future multi-entry-type expansion requires duplicating the detection row and denormalizing all detection fields.

**Problem 3: Shadow tracking contamination.** The `shadow_mae`, `shadow_mfe`, `shadow_outcome` columns track paper-trading performance. These are in the same row as live execution state (`market_entry_price`). This conflates governance (is this signal still in shadow mode?) with hypothesis testing (what did the counterfactual return?). CounterfactualTracker (Phase 130) supersedes shadow tracking entirely, but cannot be bolted onto the monolith cleanly.

The monolith has 47 columns today. Attempting to add `counterfactual_pnl_r`, `actual_pnl_r`, and `frame_details` to it would produce a 60+ column table with at least three competing NULL patterns — columns that are null for different structural reasons (not-yet-measured, not-executed, not-applicable). Queries that need to train ML models must defensively filter all three null patterns, and any regression will produce a silent wrong answer rather than a loud crash.

---

## Decision

Adopt a 3-table separation with distinct responsibilities and explicit cardinality:

```
signal_events        -- detection layer: one row per I7 plugin fire event
    1
    |
    N (one per entry_type)
trade_frames         -- hypothesis layer: one row per entry_type per signal
    1
    |
    0-1
trade_executions     -- execution layer: one row per live trade execution
```

**Invariant:** `counterfactual_pnl_r` is a required, always-populated column on `trade_frames`. The CounterfactualTracker daemon (Phase 130) fills it for every frame regardless of whether the trade was executed. ML trains on `trade_frames` directly — no null `counterfactual_pnl_r` is permitted in the steady state.

**Hypertable boundary:** Only `signal_events` is a TimescaleDB hypertable (partitioned on `ts`). `trade_frames` and `trade_executions` are regular tables. Time-range queries on frames go via JOIN to `signal_events`, or directly via the denormalized `signal_ts` column.

---

## Full Schema Tables

### signal_events (detection layer, hypertable)

Partitioned on `ts`, chunk interval 7 days. Composite PK `(signal_id, ts)` — required by TimescaleDB (unique constraints on hypertables must include the partitioning column).

| Column | Type | Index | Notes |
|--------|------|-------|-------|
| `signal_id` | `uuid` | PK (with ts) | Canonical identifier; hash of (symbol, feature_ts_ns, feature_tf, OHLCV, setup_plugin, direction) |
| `ts` | `timestamptz` NOT NULL | PK (with signal_id); hypertable dim | Bar timestamp at fire time |
| `symbol` | `text` NOT NULL | btree (symbol, ts) | Base symbol |
| `tf` | `text` NOT NULL | | `1m`, `5m`, `15m`, `1h` |
| `setup_plugin` | `text` NOT NULL | btree (setup_plugin, ts) | Fully qualified plugin class name |
| `direction` | `text` NOT NULL | | `long` or `short` (text, not integer) |
| `raw_confidence` | `float8` NOT NULL | | Intrinsic composite confidence (ICC output); immutable after emit |
| `calibrated_confidence` | `float8` | | Nullable; async-populated by calibration pipeline |
| `cis_score` | `float8` | | Composite intelligence score at fire time |
| `weights_version` | `int4` | | CIS weight version; ML trains on homogeneous segments |
| `factor_scores` | `jsonb` | | Per-factor ICC breakdown; ML weight optimization input |
| `context_features` | `jsonb` | | Full flat_features snapshot at fire; SignalRanker feature matrix |
| `ctf_score` | `float8` | btree (ctf_confirmed, ts) | Nullable; I6 CTF alignment score at emit time |
| `ctf_confirmed` | `bool` | btree (ctf_confirmed, ts) | Nullable; true if CTF threshold passed at emit |
| `zone_friction_score` | `float8` | | Nullable; zone friction annotation at emit (ECL vector, not a gate) |
| `hmm_regime_at_fire` | `int4` | btree (hmm_regime_at_fire, ts) | HMM regime state at emit; primary ML segmentation dimension |
| `plugin_regime_type` | `text` | | Plugin's declared regime type (e.g. `trending`, `ranging`) |
| `garch_sigma_at_fire` | `float8` | | GARCH volatility estimate at fire; ML feature |
| `is_shadow` | `bool` NOT NULL | btree (is_shadow) | Governance filter; every ML query conditions on this |
| `is_backfill` | `bool` NOT NULL | btree (is_backfill) | Training corpus provenance flag |
| `status` | `text` NOT NULL | btree (status, ts) | `pending` / `active` / `regime_suppressed` / `expired` |
| `signal_schema_version` | `int4` NOT NULL | | Schema version at write time (int4, not text) |
| `ttl_bars` | `int4` | | Maximum bars the signal remains active |
| `expires_at` | `timestamptz` | btree (expires_at) WHERE NOT NULL | Wall-clock expiry derived from ttl_bars |
| `signal_computed_at` | `timestamptz` | | Pipeline write wall-clock; latency = signal_computed_at - ts |
| `created_at` | `timestamptz` | | DB insertion timestamp; DEFAULT now() |
| `feature_ts` | `timestamptz` | NULL | Anchor to intelligence_features row; JOIN on (symbol, tf, ts = feature_ts). No FK — TimescaleDB hypertable constraint. |
| `concurrent_signal_count` | `int4` | NULL | Count of other active signals at fire time. Crowding indicator for ML. |
| `concurrent_plugins` | `text[]` | NULL | setup_plugin values of concurrent active signals at fire time. ML-queryable with `&&` array operator. |

**Total: 29 columns.**

**Compression config:**
```sql
ALTER TABLE signal_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol,tf',
    timescaledb.compress_orderby = 'ts DESC'
);
SELECT add_compression_policy('signal_events', INTERVAL '7 days');
```
Compression runs on a TimescaleDB-managed 12-hour job schedule. Chunks compress after 7 days, matching the existing signal_ledger policy.

---

### trade_frames (hypothesis layer, regular table)

One row per entry_type per signal fire. FK anchors to signal_events via composite `(signal_id, signal_ts)` — see FK Design section for why signal_ts is required.

| Column | Type | Notes |
|--------|------|-------|
| `frame_id` | `uuid` NOT NULL | PK |
| `signal_id` | `uuid` NOT NULL | FK component; references signal_events.signal_id |
| `signal_ts` | `timestamptz` NOT NULL | FK component; denormalized from signal_events.ts; required for FK to hypertable composite PK |
| `entry_type` | `text` NOT NULL | `at_close` / `at_pullback` / `at_limit` / `at_reclaim` / `zone_proximal` |
| `direction` | `text` NOT NULL | `long` or `short` (denormalized for query convenience) |
| `entry_price` | `float8` | Hypothetical entry price for this frame |
| `stop_price` | `float8` | Stop-loss price (renamed from signal_ledger.stop_loss) |
| `target_price` | `float8` | Primary profit target (primary extracted from signal_ledger.targets JSONB) |
| `r_multiple` | `float8` | (target_price - entry_price) / (entry_price - stop_price); reward-to-risk ratio |
| `ttl_bars` | `int4` | Counterfactual measurement window in bars |
| `expires_at` | `timestamptz` | When counterfactual measurement closes |
| `counterfactual_pnl_r` | `float8` | Primary ML target variable; always populated by CounterfactualTracker |
| `counterfactual_mfe` | `float8` | Max favorable excursion during measurement window |
| `counterfactual_mae` | `float8` | Max adverse excursion during measurement window |
| `counterfactual_bars` | `int4` | Number of bars from entry to counterfactual exit |
| `counterfactual_exit_reason` | `text` | `target_hit` / `stop_hit` / `ttl_expired` |
| `counterfactual_measured_at` | `timestamptz` | Wall-clock when CounterfactualTracker closed measurement |
| `was_selected` | `bool` | Selected by aggregator for potential live execution |
| `frame_details` | `jsonb` | Stop architecture provenance fields (see below) |
| `created_at` | `timestamptz` | DEFAULT now() |
| `regime_at_activation` | `int4` | NULL | HMM regime at entry condition trigger. NULL for at_close (fires immediately at bar close — no distinct activation). |

**Total: 21 columns.**

**frame_details JSONB** contains stop architecture diagnostic fields that are causal inputs to the frame geometry but are not ML query dimensions:
`stop_basis`, `stop_type_col`, `structural_stop_distance_atr`, `adaptive_buffer_mult`, `stop_structure_type`, `stop_structure_age_bars`, `chandelier_vol_source`, `trailing_stop_price`, `trailing_stop_tightening_rate`, `entry_zone_low`, `entry_zone_high`.

**Historical shadow fields** (`shadow_mae`, `shadow_mfe`, `shadow_outcome`, `shadow_tracking_start_ts`) from the signal_ledger monolith are archived into `frame_details` JSONB during Phase 129 migration. They are not dropped -- historical shadow P&L is training data and must be preserved per the Renaissance data retention principle.

**Indexes:**
```sql
CREATE INDEX idx_trade_frames_signal ON trade_frames (signal_id, signal_ts);
CREATE INDEX idx_trade_frames_entry_type_pnl ON trade_frames (entry_type, counterfactual_pnl_r);
CREATE INDEX idx_trade_frames_selected_pnl ON trade_frames (was_selected, counterfactual_pnl_r);
```

**FK constraint:**
```sql
FOREIGN KEY (signal_id, signal_ts) REFERENCES signal_events (signal_id, ts)
```

---

### trade_executions (execution layer, regular table)

One row per live trade execution. Most frames have zero rows here. Cardinality: 1 trade_frame to 0-1 trade_executions.

| Column | Type | Notes |
|--------|------|-------|
| `execution_id` | `uuid` NOT NULL | PK |
| `frame_id` | `uuid` NOT NULL | FK → trade_frames(frame_id) |
| `actual_fill_price` | `float8` | Confirmed fill price (vs entry_price hypothesis) |
| `actual_exit_price` | `float8` | Actual exit price |
| `actual_pnl_r` | `float8` | Live realized outcome in R units |
| `actual_mfe` | `float8` | Max favorable excursion during live trade |
| `actual_mae` | `float8` | Max adverse excursion during live trade |
| `actual_bars` | `int4` | Bars held from entry to exit |
| `market_entry_price` | `float8` | Actual market entry (vs hypothetical entry_price; gap = slippage) |
| `market_entry_gap_bars` | `int4` | Bars between signal fire and actual fill |
| `exit_reason` | `text` | Live exit reason (matches counterfactual_exit_reason vocabulary) |
| `executed_at` | `timestamptz` | When the live trade was entered |
| `exited_at` | `timestamptz` | When the live trade was closed |
| `regime_at_exit` | `int4` | NULL | HMM regime at position exit. Enables regime-transition analysis: did regime flip before exit? |

**Total: 14 columns.**

**Indexes:**
```sql
CREATE INDEX idx_trade_executions_frame ON trade_executions (frame_id);
CREATE INDEX idx_trade_executions_executed_at ON trade_executions (executed_at);
```

**FK constraint:**
```sql
FOREIGN KEY (frame_id) REFERENCES trade_frames (frame_id)
```

---

### signal_ledger_v2 (backward-compatibility view)

Replaces the `signal_ledger_full` view from migration 095. Provides a flat join across all three tables for query callers that were written against the monolith.

```sql
CREATE VIEW signal_ledger_v2 AS
SELECT
    se.signal_id,
    se.ts,
    se.symbol,
    se.tf,
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
    tf.r_multiple,
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

`signal_ledger_full` (migration 095) is superseded by `signal_ledger_v2` after Phase 129 migration completes. The legacy `signal_ledger` monolith table is retained read-only for 48 hours post-migration, then dropped in Phase 130 (the view name `signal_ledger` is reclaimed for a new alias if needed).

---

## G0 Audit -- signal_id Hash Consistency

**Finding: CLEARED. Phase 129 migration may proceed.**

`make_signal_id()` in `src/intelligence/trading/signal_schema.py` hashes:
```
(symbol, feature_ts_ns, feature_tf, open, high, low, close, volume, setup_plugin, direction)
```

**entry_type is NOT in the hash.** This is the correct design -- the signal identity is the detection event, not the trade hypothesis derived from it.

**Audit of all make_signal_from_frame() call sites:**

All 22 plugins that emit signals call `make_signal_from_frame()` exactly once per detection event. No plugin generates multiple signals with different entry_types from the same fire:

- `gap_analysis_setup.py` -- sets `entry_type` conditionally (`at_limit` or `at_pullback` depending on gap type), then calls `make_signal_from_frame()` once. One fire produces one entry_type. No collision risk.
- `divergence_stack.py` -- calls `make_signal_from_frame()` once per detection inside the loop body (not looping over entry_types). One fire = one entry_type.
- All other plugins (cross_asset_divergence, cvd_divergence, choch_reversal, orb30, orb15, anchored_vwap_reversion, squeeze_expansion, fvg_fill, dual_divergence, microstructure_utils, hvn_rejection, liquidity_hunt, lvn_breakout, mtf_alignment, momentum_breakout, mean_reversion, failed_breakout, ofi_divergence, poc_rejection, pattern_completion, and others) -- each calls `make_signal_from_frame()` once per fire event.

**Current cardinality:** 1 signal_id = 1 signal_events row = 1 trade_frames row. The N-frame cardinality (1 signal_events : N trade_frames, one per entry_type) is a Phase 130+ expansion target. No existing plugin exercises multi-entry_type emission today. The Phase 129 migration can proceed without needing to handle duplicate signal_ids in the source data.

---

## Phase 130 Writer Grouping Contract

This section documents the contract that Phase 130's `signal_writer` must implement when writing to the 3-table schema. It is documented here (not in Phase 130) because it governs the schema design choices above.

**Contract (D-09):**

When a batch of signal dicts arrives from Kafka:

1. **Group by signal_id.** All signal dicts with the same `signal_id` represent the same detection event with different entry_types.
2. **Insert ONE `signal_events` row per group.** Use detection fields from the first signal dict in the group (they are identical across all entry_types -- detection state does not vary by hypothesis).
3. **Insert N `trade_frames` rows per group** -- one per entry_type variant in the group.

**Today (Phase 129-130 initial state):** All plugins emit one entry_type per fire, so N=1. Every group has exactly one signal dict. The writer must nonetheless implement the grouping contract from day one -- not assume N=1 -- because future plugins will expand to multi-frame emission without a contract change.

**Why this matters for the schema:** The `signal_ts` denormalized column on `trade_frames` exists because the Phase 130 writer needs to write frame rows without a round-trip query to `signal_events` to obtain the hypertable PK value. The writer computes `signal_ts` from the signal dict (it is the bar timestamp, available in every payload) and writes it directly to `trade_frames.signal_ts` at insert time.

### New Column Obligations (Phase 128-04)

**SignalWriter / SignalAggregatorWriter** (populates `signal_events`):
- `feature_ts`: set to the `ts` of the `intelligence_features` bar that produced the signal's flat_features. Available from the bar's `IntelligenceEvent.ts` field. Do NOT query the DB — use the event timestamp directly.
- `concurrent_signal_count`: count of signals with `status == "active"` in SignalTracker state at fire time. In-process state only — no DB query.
- `concurrent_plugins`: list of `setup_plugin` values from all `SignalState` objects with `status == "active"` at fire time.

**TradeFrameWriter** (populates `trade_frames`):
- `regime_at_activation`: for `at_pullback`, `at_reclaim`, `at_limit`, `zone_proximal` entry types — record `hmm_regime` from the bar when the activation condition triggered. For `at_close` — leave NULL (activation is simultaneous with fire).

**TradeExecutionWriter** (populates `trade_executions`):
- `regime_at_exit`: record `hmm_regime` from the bar when the exit event occurred (stop hit, target hit, TTL expired, or manual close).

---

## Dropped Columns

The following signal_ledger columns are not carried forward into the 3-table schema. They are explicitly dropped at migration time (not archived).

| Column | Reason |
|--------|--------|
| `signal_type` | Redundant with `setup_plugin` -- plugin name fully identifies signal type |
| `feature_tf` | Duplicate of `signal_events.timeframe` |
| `feature_schema_version` | Superseded by `signal_schema_version int4`; the old text version is replaced |
| `pipeline_lag_ms` | Computable: `signal_computed_at - ts`; storing it violates SoC (derived values belong in queries, not columns) |
| `staleness_score` | No new home in 3-table design; absent from CONTEXT.md D-02; treat as dropped |
| `staleness_trigger_reason` | No new home in 3-table design; absent from CONTEXT.md D-02; treat as dropped |

**Note on feature_ts:** Re-introduced in Phase 128-04 as a JOIN anchor to `intelligence_features` (semantically distinct from the old `feature_ts` which was a duplicate of `ts`). The new `feature_ts` is a first-class column on `signal_events` and must NOT be dropped in Phase 129.

**Archived to frame_details JSONB (not dropped):**

The following columns contain historical training data and must not be discarded (Renaissance data retention principle: never drop data that could contain signal):

| Column | Destination |
|--------|-------------|
| `shadow_mae` | `trade_frames.frame_details['shadow_mae']` |
| `shadow_mfe` | `trade_frames.frame_details['shadow_mfe']` |
| `shadow_outcome` | `trade_frames.frame_details['shadow_outcome']` |
| `shadow_tracking_start_ts` | `trade_frames.frame_details['shadow_tracking_start_ts']` |
| `entry_zone_low` | `trade_frames.frame_details['entry_zone_low']` |
| `entry_zone_high` | `trade_frames.frame_details['entry_zone_high']` |
| `stop_basis` | `trade_frames.frame_details['stop_basis']` |
| `stop_type_col` | `trade_frames.frame_details['stop_type_col']` |
| `structural_stop_distance_atr` | `trade_frames.frame_details['structural_stop_distance_atr']` |
| `adaptive_buffer_mult` | `trade_frames.frame_details['adaptive_buffer_mult']` |
| `stop_structure_type` | `trade_frames.frame_details['stop_structure_type']` |
| `stop_structure_age_bars` | `trade_frames.frame_details['stop_structure_age_bars']` |
| `chandelier_vol_source` | `trade_frames.frame_details['chandelier_vol_source']` |
| `trailing_stop_price` | `trade_frames.frame_details['trailing_stop_price']` |
| `trailing_stop_tightening_rate` | `trade_frames.frame_details['trailing_stop_tightening_rate']` |

CounterfactualTracker (Phase 130) supersedes the shadow tracking columns as the primary P&L measurement mechanism. The historical shadow values are archived to JSONB precisely so they can still be used as training data alongside CounterfactualTracker output during the transition period.

---

## FK Design on Hypertable

**Why the FK requires two columns:**

TimescaleDB partitions hypertables by the time dimension column (`ts` on `signal_events`). All unique constraints on a TimescaleDB hypertable must include every partitioning column. This means the PK on `signal_events` must be composite: `(signal_id, ts)`.

PostgreSQL FK constraints must reference a unique constraint exactly -- a FK targeting only `signal_id` would fail because there is no unique constraint on `signal_id` alone (the only unique constraint includes `ts`).

Therefore, `trade_frames` must carry `signal_ts timestamptz` as a first-class column and declare:

```sql
FOREIGN KEY (signal_id, signal_ts) REFERENCES signal_events (signal_id, ts)
```

**This is not a convenience denormalization.** `signal_ts` on `trade_frames` is architecturally required by the hypertable FK constraint. It also enables time-range filtering on `trade_frames` directly without joining `signal_events`, which is a secondary performance benefit.

**Pitfall to avoid:** A single-column FK `FOREIGN KEY (signal_id) REFERENCES signal_events(signal_id)` will fail at DDL time -- PostgreSQL cannot satisfy an FK against a column that is not itself uniquely constrained.

---

## Hypertable Configuration

`signal_events` is the only hypertable in the 3-table schema. Configuration mirrors the existing `signal_ledger` hypertable (7-day chunks, compression after 7 days, segmented by symbol+timeframe):

```sql
-- Create hypertable
SELECT create_hypertable('signal_events', 'ts',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE);

-- Composite PK (after hypertable creation)
ALTER TABLE signal_events ADD PRIMARY KEY (signal_id, ts);

-- Compression: enabled, segmented by (symbol, timeframe), ordered by ts DESC
ALTER TABLE signal_events SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol,tf',
    timescaledb.compress_orderby = 'ts DESC'
);

-- Compression policy: compress chunks older than 7 days
-- TimescaleDB manages the 12-hour job schedule automatically
SELECT add_compression_policy('signal_events', INTERVAL '7 days');
```

**Compression column requirement:** `symbol` and `tf` are `NOT NULL` on `signal_events` -- this is required because TimescaleDB rejects compression settings where segmentby columns contain nulls.

`trade_frames` and `trade_executions` are regular PostgreSQL tables. Their time-range access pattern is either direct (via `signal_ts` on trade_frames) or through a JOIN to `signal_events`. No hypertable is needed or beneficial for these tables at current data volumes.

---

## Alternatives Considered

### Alternative 1: 2-Table Design (signal_events + trade_outcomes)

**Proposal:** Merge trade_frames and trade_executions into a single `trade_outcomes` table with nullable execution columns.

**Schema sketch:**
```
signal_events: detection fields
trade_outcomes: entry_type + counterfactual_pnl_r + actual_pnl_r (nullable)
```

**Why rejected:**

A single `trade_outcomes` row cannot cleanly separate counterfactual P&L (always available, measured by a daemon) from actual P&L (only for live trades, measured from broker fills). The result is a table with two competing null patterns:

- `counterfactual_pnl_r IS NULL` means CounterfactualTracker has not yet measured this frame (transient)
- `actual_pnl_r IS NULL` means this frame was never executed (permanent -- structural null, not a timing issue)

ML training requires a clean `counterfactual_pnl_r` that is always populated once the measurement window closes. In a 2-table design, ML queries must filter `WHERE actual_pnl_r IS NULL` to exclude executed rows (or include them -- a design choice that must be made explicitly and can be made wrong). This creates a hidden dependency between the null pattern and the ML query logic.

The 3-table design makes the cardinality explicit: every `trade_frames` row has `counterfactual_pnl_r` (not null at steady state), and `trade_executions` rows only exist for live trades. No null filtering needed -- the schema structure encodes the intent.

### Alternative 2: Flat Monolith (Enhanced signal_ledger)

**Proposal:** Add `counterfactual_pnl_r` and related columns to the existing `signal_ledger` table rather than migrating.

**Why rejected:**

This perpetuates the root cause. The monolith already has 47 columns. Adding `counterfactual_pnl_r`, `counterfactual_mfe`, `counterfactual_mae`, `counterfactual_exit_reason`, `actual_pnl_r`, `actual_fill_price`, `actual_exit_price`, `actual_mfe`, `actual_mae`, `actual_bars`, `executed_at`, `exited_at` would produce a 59+ column table.

More critically, it cannot express the 1:N cardinality of signal-to-hypothesis. If a single detection event fires with three entry_types (`at_close`, `at_pullback`, `at_limit`), the monolith must store three rows with identical detection fields -- and ML training must deduplicate on signal_id to avoid weighting the detection event three times.

The flat monolith also conflates two distinct NULL semantics for `counterfactual_pnl_r`:
- Null because CounterfactualTracker has not yet run (transient)
- Null because the signal was suppressed before reaching hypothesis state (structural)

These are fundamentally different and require different handling. The 3-table design makes them structurally impossible to confuse: a suppressed signal has a `signal_events` row with `status = 'regime_suppressed'` and zero `trade_frames` rows. A pending signal has a `trade_frames` row with `counterfactual_pnl_r IS NULL`. An ML query joins signal_events to trade_frames and gets only signals that have hypotheses, which are the only signals for which counterfactual measurement makes sense.

---

## Consequences

### Migration Scope

**Phase 129:** Executes DDL (`production/migrations/137_3table_schema.sql`), migrates all existing `signal_ledger` rows into the 3-table schema, archives shadow fields to JSONB, converts `direction integer` to `direction text` (`1` -> `'long'`, `-1` -> `'short'`), casts `signal_schema_version text` to `int4`. `signal_ledger` table retained read-only for 48 hours post-migration (zero writes, read path served by `signal_ledger_v2` view).

**Phase 130:** Rewrites signal_writer, SignalTracker, CounterfactualTracker, and API queries to use the 3-table schema directly. Drops the legacy `signal_ledger` monolith. CounterfactualTracker daemon is the critical dependency -- `counterfactual_pnl_r` will be null on all rows until Phase 130 ships.

### Type Changes

| Column | Old type | New type | Callers to update in Phase 130 |
|--------|----------|----------|-------------------------------|
| `direction` | `integer` (1/-1) | `text` (long/short) | signal_writer, SignalRanker, all queries comparing direction |
| `signal_schema_version` | `text` | `int4` | signal_writer, any callers reading version |
| `entry_price`, `stop_loss` | `numeric` | `float8` | signal_writer, counterfactual calculations |

### Backward Compatibility

`signal_ledger_v2` view is the backward-compatibility surface during Phase 130 transition. Dashboard queries, API handlers, and any external callers that read `signal_ledger_full` (migration 095 view) should be migrated to query `signal_ledger_v2` in Phase 130. The `signal_ledger_full` view (migration 095) is superseded but not immediately dropped -- it can coexist with `signal_ledger_v2` until all callers are migrated.

### CounterfactualTracker Dependency

`counterfactual_pnl_r` on `trade_frames` will be `NULL` on all rows between Phase 129 (migration) and Phase 130 (CounterfactualTracker daemon). ML training must not be run against the 3-table schema until CounterfactualTracker has been running long enough to populate a statistically meaningful sample (n >= 100 per plugin, per the shadow promotion gate). This is an intentional gap -- the schema is correct, the data pipeline is not yet complete.

### signal_schema_version Bump

Phase 129 migration should bump `SIGNAL_SCHEMA_VERSION` in `src/intelligence/trading/signal_schema.py` from the current integer value to the next integer. All producers and consumers import from this constant -- a version bump signals to the ML discovery pipeline that a schema boundary exists at this date.

### GIN Indexes (Deferred)

No GIN indexes are added on `context_features` or `factor_scores` in Phase 128 or 129. The existing codebase has no GIN indexes on any JSONB column in the production tables. GIN indexes will be added in a future phase after ML training query patterns are observed in production. Speculative GIN indexes on large JSONB columns impose write overhead without a confirmed query benefit.
