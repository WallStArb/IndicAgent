# Phase 130: Script Rewriting - Research

**Researched:** 2026-06-16
**Domain:** 3-Table Signal Schema Migration — Writers, Trackers, API Endpoints, Scripts
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01:** CounterfactualTracker is v2.11 - not Phase 130. Phase 130 writes `counterfactual_pnl_r = NULL`. Do not plan or implement CounterfactualTracker here.

**D-02:** G0 writer grouping: signals with same signal_id map to ONE signal_events row and N trade_frames rows. signal_writer._parse_payload() must group by signal_id, insert one signal_events row from detection fields, then N trade_frames rows per group — all in a single asyncpg transaction.

**D-03:** signal_outcomes is also dropped in Phase 130. Rewrite all signal_outcomes writes to signal_events/trade_executions. DROP order: signal_outcomes first, then signal_ledger CASCADE.

**D-04:** Drop sequence after 48h clean production: `DROP TABLE signal_outcomes; DROP TABLE signal_ledger CASCADE; ALTER VIEW signal_ledger_full RENAME TO signal_ledger;`

**D-05:** Rewrite SignalLedgerRepository in place - rename class to SignalEventsRepository, file to signal_events_repository.py, update all importers.

**D-06:** swarm_ledger_writer FK check: update `SELECT 1 FROM signal_ledger` to `SELECT 1 FROM signal_events`.

**D-07:** Read-only services work automatically after I8 view rename. Verify no hidden write paths.

**D-08:** New columns to populate going forward: `signal_events.concurrent_signal_count`, `signal_events.concurrent_plugins` (from signal_tracker active_signals state), `trade_frames.regime_at_activation` (from lifecycle events).

**D-09:** Explicit write-path file list (files requiring rewrite):
- `src/persistence/repository/signal_ledger_repository.py` → renamed to `signal_events_repository.py`
- `services/signal_writer.py`
- `services/lifecycle_writer.py`
- `services/signal_tracker.py`
- `services/signal_auditor.py`
- `services/swarm_ledger_writer.py`
- `src/api/routes/signals.py`
- `src/api/routes/narrative.py`
- `production/scripts/run_historical_pipeline.py`
- `production/scripts/lifecycle_replay.py`

**D-10:** API query strategy: use `signal_ledger_full` view (renamed to `signal_ledger` after I8). For ML-specific endpoints needing trade_frames columns not in view, write explicit 3-table JOINs.

**D-11:** Transaction atomicity: signal_events INSERT + trade_frames INSERT(s) in one asyncpg transaction. Lifecycle UPDATE (signal_events.status) is standalone (idempotent). trade_executions INSERT is standalone.

**D-12:** APR migrate-as-you-go mandatory. Full list of new keys, seed values, and locations in CONTEXT.md §D-12.

**D-13:** Add `"ui."` and `"weights."` to OPS_PREFIXES in `src/config/config_service.py` before seeding ui.signals.* keys.

**D-14:** File/class rename mandatory. Docstring corrections mandatory in all modified files.

**D-15:** Doc updates required AFTER DROP migration (I8): architecture-overview.md, architecture-dag-topology.md, temporal-data-architecture.md, adaptive-intelligence.md, event-driven-fabric.md, CLAUDE.md §TimescaleDB Tables.

### Claude's Discretion

- Exact migration numbering for DROP + APR-seed migration (next after 141 = 142).
- GIN index on context_features/factor_scores: add only if ML queries filter JSONB inline; check query patterns.
- Order of service rewrites in plans: signal_writer first (live write path), then lifecycle/tracker, then API, then scripts.
- Confidence that read-only services work via view: grep sweep to verify no hidden write paths.
- Separate APR seeding migration from DROP migration (prefer separate for clean rollback boundaries).

### Deferred Ideas (OUT OF SCOPE)

- CounterfactualTracker daemon — v2.11
- I6 DB bootstrap at startup — v2.11
- GIN index on context_features/factor_scores — defer unless ML query patterns warrant it
- APR ML optimization on factor_scores — v2.11
- SignalRanker (LightGBM) — v2.11
</user_constraints>

---

## Summary

Phase 130 is a large-scale schema migration at the write-path layer. The 3-table schema (signal_events / trade_frames / trade_executions) was designed in Phase 128 and migrated in Phase 129. Phase 130 rewrites all services that previously wrote to signal_ledger and signal_outcomes to instead write to the new tables. Signal_ledger is dropped after a 48-hour verification window.

The central rewrite target is `SignalLedgerRepository` (15+ methods, all SQL pointing at old tables). A single rewrite of this class propagates to all callers — signal_writer, lifecycle_writer, signal_tracker — without service-by-service SQL patching. The signal_writer gains the most structural complexity: the G0 grouping logic (group by signal_id, insert one signal_events row plus N trade_frames rows per group, all in one transaction).

Five significant discoveries emerged during research that are not fully addressed in CONTEXT.md:
1. `feature_replay.py` writes to signal_ledger and is not in D-09's explicit file list.
2. The signal_tracker bootstrap query uses columns (activated_at, mae, mfe, trailing_stop_price, targets, entry_zone_low/high, market_entry_price, chandelier_vol_source) that are NULL in the signal_ledger_full view — the bootstrap needs a direct query against signal_events + trade_frames, not the view.
3. Activation lifecycle fields (activated_at, activation_price, zone_entry_pct, bars_to_activation) have no column home in the new schema — they must go to trade_frames.frame_details JSONB via UPDATE.
4. concurrent_signal_count population requires signal_tracker's in-memory state, which is in a separate process — the simplest correct approach is to leave it NULL for Phase 130 and populate it in v2.11 (or enrich the signal payload in intelligence_pipeline).
5. Several API columns no longer exist in signal_ledger_full (signal_type, bucket_scores, staleness_score, staleness_trigger_reason, feature_tf, stop_basis) — API endpoints must either drop these from responses or query frame_details for stop_basis.

**Primary recommendation:** Start with SignalEventsRepository rewrite, then signal_writer (live write path critical), then lifecycle_writer, then signal_tracker bootstrap, then API, then scripts. Run the drop migration only after 48 hours of verified production operation.

---

## Standard Stack

### Core Libraries in Phase 130 Scope

| Library | Role | Verified |
|---------|------|---------|
| asyncpg | All DB operations in services (transactions, execute_batch, fetchrow) | HIGH - in production |
| psycopg2 | Used only in historical pipeline scripts (run_historical_pipeline.py, feature_replay.py) | HIGH - in production |
| uuid (stdlib) | uuid5 for deterministic frame_id generation: `uuid5(NAMESPACE_DNS, f"{signal_id}:{entry_type}")` | HIGH - used in migrate_signal_ledger.py |
| structlog | Logging in all service files | HIGH - in production |

### Established Patterns (use these, do not deviate)

| Pattern | Location | Notes |
|---------|----------|-------|
| asyncpg transaction | `signal_ledger_repository.py:insert_signals_with_features()` | `async with pool.acquire() as conn: async with conn.transaction():` |
| ON CONFLICT for signal_events | `ON CONFLICT (signal_id, ts) DO NOTHING` | PK is (signal_id, ts) |
| ON CONFLICT for trade_frames | `ON CONFLICT (frame_id) DO NOTHING` | PK is frame_id; deterministic uuid5 |
| execute_batch | `database_manager.execute_batch(sql, params_list)` | For batch inserts |
| JSONB as dict | asyncpg returns/accepts dicts directly — no json.loads/json.dumps | CLAUDE.md rule |
| Direction encoding | int 1/-1 in Kafka payload → "long"/"short" text in signal_events | Signal_events.direction is TEXT |
| format_iso_ts | `service_utils.format_iso_ts(dt)` — never inline .isoformat() | CLAUDE.md rule |

**Installation:** No new packages required. All dependencies already in project.

---

## Architecture Patterns

### Recommended Rewrite Order

```
Signal path (highest risk if broken):
  1. signal_events_repository.py — central hub, all SQL here
  2. signal_writer.py — live write path (signal_events + trade_frames)
  3. lifecycle_writer.py — lifecycle transitions (status UPDATE, trade_executions INSERT)
  4. signal_tracker.py — bootstrap query (reads from new tables)
  5. swarm_ledger_writer.py — FK check update (one line)
  6. signal_auditor.py — reads only (low risk)

Read path (API):
  7. src/api/routes/signals.py — biggest file, most endpoints
  8. src/api/routes/narrative.py — uses feature_tf (dropped)

Scripts:
  9. production/scripts/run_historical_pipeline.py — psycopg2 inserts
  10. production/scripts/lifecycle_replay.py — psycopg2 updates
  11. production/scripts/feature_replay.py — MISSING FROM D-09, also writes to signal_ledger

DROP sequence:
  12. Migration: APR seeds (new migration 142)
  13. 48-hour verification window
  14. Migration: DROP signal_outcomes; DROP signal_ledger CASCADE; ALTER VIEW
  15. Doc updates (D-15)
```

### Pattern 1: G0 Writer Grouping (signal_writer._parse_payload)

**What:** Group signals by signal_id; insert one signal_events row (detection fields) + one or more trade_frames rows per group.
**When to use:** Every time signal_writer receives an i7.signals Kafka message.

```python
# Source: CONTEXT.md §specifics, G0 pseudocode
from collections import defaultdict
import uuid

_FRAME_ID_NS = uuid.NAMESPACE_DNS

def _make_frame_id(signal_id: str, entry_type: str) -> str:
    """Deterministic frame_id — same signal_id + entry_type always produces same UUID."""
    return str(uuid.uuid5(_FRAME_ID_NS, f"{signal_id}:{entry_type}"))

def _direction_text(direction_int: int) -> str:
    return "long" if direction_int == 1 else "short"

def _parse_payload_new(payload: dict) -> tuple[list, list]:
    groups = defaultdict(list)
    for signal in payload.get("signals", []):
        groups[signal["signal_id"]].append(signal)

    signal_events_rows = []
    trade_frames_rows = []
    for signal_id, signals in groups.items():
        detection = signals[0]  # All share same detection fields
        signal_events_rows.append(_build_signal_events_row(detection, payload))
        for s in signals:
            trade_frames_rows.append(_build_trade_frames_row(s))
    return signal_events_rows, trade_frames_rows
```

### Pattern 2: signal_events INSERT

```python
# Source: migration 137_3table_schema.sql + CONTEXT.md D-02
_INSERT_SIGNAL_EVENTS_SQL = """
INSERT INTO signal_events (
    signal_id, ts, symbol, tf, setup_plugin, direction,
    raw_confidence, calibrated_confidence, cis_score, weights_version,
    factor_scores, context_features,
    ctf_score, ctf_confirmed, zone_friction_score,
    hmm_regime_at_fire, plugin_regime_type, garch_sigma_at_fire,
    is_shadow, is_backfill, status, signal_schema_version,
    ttl_bars, expires_at, signal_computed_at, feature_ts
) VALUES (
    $1::uuid, $2, $3, $4, $5, $6,
    $7, $8, $9, $10,
    $11::jsonb, $12::jsonb,
    $13, $14, $15,
    $16, $17, $18,
    $19, $20, $21, $22,
    $23, $24, $25, $26
)
ON CONFLICT (signal_id, ts) DO NOTHING
"""
# NOTE: direction must be "long"/"short" text, NOT integer
# NOTE: status starts as 'pending' (or 'regime_suppressed' if flagged)
# NOTE: concurrent_signal_count and concurrent_plugins left NULL in Phase 130
```

### Pattern 3: trade_frames INSERT

```python
# Source: migration 137_3table_schema.sql, migrate_signal_ledger.py
_INSERT_TRADE_FRAMES_SQL = """
INSERT INTO trade_frames (
    frame_id, signal_id, signal_ts, entry_type, direction,
    entry_price, stop_price, target_price, r_multiple,
    ttl_bars, expires_at, counterfactual_pnl_r, was_selected,
    frame_details
) VALUES (
    $1::uuid, $2::uuid, $3, $4, $5,
    $6, $7, $8, $9,
    $10, $11, NULL, $12,
    $13::jsonb
)
ON CONFLICT (frame_id) DO NOTHING
"""
# frame_id = uuid5(NAMESPACE_DNS, f"{signal_id}:{entry_type}")
# signal_ts = same as signal_events.ts (FK anchor for hypertable composite PK)
# counterfactual_pnl_r = NULL (populated by CounterfactualTracker in v2.11)
# frame_details JSONB: stop_basis, stop_type_col, structural_stop_distance_atr,
#   adaptive_buffer_mult, plugin_regime_type, stop_structure_age_bars,
#   entry_zone_low, entry_zone_high
```

### Pattern 4: Transaction Wrapping (signal_writer)

```python
# Both inserts in one asyncpg transaction — if trade_frames fails, signal_events rolls back
async with pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute(_INSERT_SIGNAL_EVENTS_SQL, *signal_events_params)
        await conn.executemany(_INSERT_TRADE_FRAMES_SQL, trade_frames_params_list)
```

### Pattern 5: Lifecycle Status Update (lifecycle_writer → signal_events)

```python
# Source: CONTEXT.md D-11 — standalone UPDATE (not in transaction)
_UPDATE_STATUS_SQL = """
UPDATE signal_events
SET status = $2
WHERE signal_id = $1::uuid
"""
# Activation lifecycle fields (activated_at, activation_price, zone_entry_pct,
# bars_to_activation) go to trade_frames.frame_details JSONB via UPDATE:
_UPDATE_FRAME_DETAILS_SQL = """
UPDATE trade_frames
SET frame_details = frame_details || $2::jsonb
WHERE signal_id = $1::uuid
"""
```

### Pattern 6: signal_tracker Bootstrap Query (NEW — queries signal_events directly)

The current bootstrap queries `signal_ledger_full`, which returns NULL for all lifecycle fields (activated_at, mae, mfe, trailing_stop_price, etc.). Post-Phase 130, new signals go to signal_events and trade_frames. The bootstrap must query signal_events directly for lifecycle state.

```sql
-- Replace the signal_ledger_full bootstrap with direct signal_events + trade_frames JOIN
SELECT
    se.signal_id, se.symbol, se.tf AS timeframe, se.ts AS timestamp,
    se.status, se.direction,
    se.ttl_bars, se.is_backfill, se.is_shadow,
    se.garch_sigma_at_fire, se.hmm_regime_at_fire,
    se.expires_at,
    tf.entry_price,
    tf.stop_price AS stop_loss,
    tf.target_price,
    (tf.frame_details->>'entry_zone_low')::float8 AS entry_zone_low,
    (tf.frame_details->>'entry_zone_high')::float8 AS entry_zone_high,
    (tf.frame_details->>'trailing_stop_price')::jsonb AS trailing_stop_price,
    (tf.frame_details->>'chandelier_vol_source')::text AS chandelier_vol_source,
    (tf.frame_details->>'activated_at')::timestamptz AS activated_at
FROM signal_events se
LEFT JOIN trade_frames tf ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts
WHERE se.status IN ('pending', 'active', 'regime_suppressed')
  AND (
    (se.status = 'pending' AND se.ts > NOW() - INTERVAL '7 days')
    OR (se.status IN ('active', 'regime_suppressed') AND se.ts > NOW() - INTERVAL '30 days')
  )
```

Note: `targets` (was JSONB array in signal_ledger) is now `trade_frames.target_price` (first target only). Bootstrap needs to adapt signal canonical dicts accordingly.

### Pattern 7: APR Loading in Services

```python
# Load at _setup() time, not at class level (CLAUDE.md APR mandate)
self._batch_size = await self._config.get("feature.signal_writer.batch_size", default=100)
self._flush_interval = await self._config.get("feature.signal_writer.flush_interval_secs", default=5.0)
# For SQL INTERVAL use parameterized approach:
# WHERE ts > NOW() - ($1 * INTERVAL '1 day')  with param=int_days_from_apr
```

### Pattern 8: OPS_PREFIXES Update (one-liner before APR seeding)

```python
# src/config/config_service.py line ~39 — ADD "ui." and "weights." to tuple
OPS_PREFIXES: ClassVar[tuple[str, ...]] = (
    "regime.", "swarm.", "alert.", "ai.", "feature.", "threshold.",
    "roll.", "cross_asset.", "macro.",
    "ui.",       # ADD — for Dashboard preference keys
    "weights.",  # ADD — weights.* already in config_state but not settable via ConfigService
)
```

### Anti-Patterns to Avoid

- **Querying signal_ledger_full for lifecycle state in bootstrap:** The view returns NULL for activated_at, mae, mfe, etc. Use direct signal_events + trade_frames JOIN.
- **Random UUID for frame_id:** Must be deterministic (uuid5) for idempotency across replays.
- **Separate asyncpg transactions for signal_events and trade_frames:** Must be atomic (one transaction).
- **Integer direction (1/-1) in signal_events INSERT:** signal_events.direction is TEXT "long"/"short" — convert before INSERT.
- **Class-level BATCH_SIZE, FLUSH_INTERVAL_SECS, MAX_BUFFER_SIZE constants:** APR violation; load from ConfigService in _setup().
- **Code still querying signal_ledger after I8 via view-based code referencing signal_ledger_full:** After I8, signal_ledger_full no longer exists by that name; all references must be updated to signal_ledger BEFORE running I8.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Deterministic frame_id | Custom hash | `uuid.uuid5(uuid.NAMESPACE_DNS, f"{signal_id}:{entry_type}")` | Already established in migrate_signal_ledger.py; idempotent across replays |
| Batch DB writes | Manual loops | `database_manager.execute_batch(sql, params_list)` | Connection pooling and error handling built in |
| asyncpg transaction | Try/except with manual rollback | `async with conn.transaction():` | Context manager handles rollback automatically |
| JSONB serialization | json.dumps() before passing | Pass dict directly to asyncpg | asyncpg handles JSONB ↔ dict natively (CLAUDE.md rule) |

---

## Common Pitfalls

### Pitfall 1: signal_tracker Bootstrap NULL Columns

**What goes wrong:** Bootstrap query uses `signal_ledger_full` view. In the new schema, the view returns NULL for `activated_at`, `mae`, `mfe`, `targets`, `entry_zone_low`, `entry_zone_high`, `market_entry_price`, `trailing_stop_price`, `chandelier_vol_source`. Bootstrap succeeds (no error) but loads signals with no lifecycle state.
**Why it happens:** The view definition hard-codes NULL for lifecycle fields that were in signal_outcomes (which is being dropped).
**How to avoid:** Rewrite the bootstrap query to JOIN signal_events + trade_frames directly. Pull lifecycle metadata from trade_frames.frame_details JSONB.
**Warning signs:** Bootstrap logs "bootstrap_complete" with 0 active signals when there should be some; signal_tracker treats all loaded signals as having no tracking history.

### Pitfall 2: Activation Fields Lost

**What goes wrong:** lifecycle_writer "activation" transition (activated_at, activation_price, zone_entry_pct, bars_to_activation) goes nowhere — signal_outcomes is dropped and there is no column home for these in signal_events.
**Why it happens:** The 3-table schema ADR does not include activation lifecycle columns.
**How to avoid:** UPDATE trade_frames.frame_details JSONB with activation metadata: `SET frame_details = frame_details || '{"activated_at":...}'::jsonb WHERE signal_id = $1`.
**Warning signs:** Dashboard shows 0 activation_price / activated_at for active signals.

### Pitfall 3: feature_replay.py Not Rewritten

**What goes wrong:** feature_replay.py still writes to signal_ledger (now read-only, REVOKE'd). Writes silently fail for postgres superuser OR raise PermissionError for non-superuser.
**Why it happens:** feature_replay.py is not in D-09's explicit file list in CONTEXT.md, but it contains `INSERT INTO signal_ledger` and `INSERT INTO signal_outcomes`.
**How to avoid:** Add feature_replay.py to the Phase 130 rewrite scope.

### Pitfall 4: signal_ledger_full Reference After I8

**What goes wrong:** Code that queries `signal_ledger_full` breaks after I8 renames the view to `signal_ledger`.
**Why it happens:** API routes, services, and auditors that were updated to use `signal_ledger_full` during Phases 128-129 still reference the old view name.
**How to avoid:** Before running I8, update ALL `signal_ledger_full` references to `signal_ledger`. The CONTEXT.md notes this explicitly.

### Pitfall 5: concurrent_signal_count Population Mismatch

**What goes wrong:** CONTEXT.md D-08 says "Signal_writer computes this from signal_tracker's in-memory active_signals state." But signal_writer and signal_tracker are separate OS processes — they cannot share in-memory state.
**Why it happens:** D-08 assumption that they share state is architecturally incorrect.
**How to avoid:** Leave concurrent_signal_count and concurrent_plugins as NULL in Phase 130. Mark for v2.11. The column is nullable. Do NOT attempt to query signal_events for active counts (would violate "zero extra DB queries" constraint and create circular dependency).

### Pitfall 6: direction Encoding

**What goes wrong:** signal_events.direction is TEXT ("long"/"short"). Kafka signals carry direction as INT (1/-1). Signal_writer naively passes 1 to the INSERT, which fails the NOT NULL TEXT constraint.
**Why it happens:** Schema encoding changed in Phase 128 ADR from integer to text.
**How to avoid:** In signal_writer, convert before building signal_events row: `direction_text = "long" if sig["direction"] == 1 else "short"`.

### Pitfall 7: Missing SIGNAL_SCHEMA_VERSION in signal_events INSERT

**What goes wrong:** signal_events.signal_schema_version is populated from the constant but the constant is INT (5) while the old schema stored TEXT. Phase 129 already changed the DB column to int4.
**Why it happens:** Migration 129 changed the column type. Old code passed strings.
**How to avoid:** Always pass `SIGNAL_SCHEMA_VERSION` constant (int) directly to INSERT. Do not str() it.

### Pitfall 8: API Columns That No Longer Exist

**What goes wrong:** API queries referencing `sl.signal_type`, `sl.bucket_scores`, `sl.feature_tf`, `sl.stop_basis`, `so.staleness_score`, `so.staleness_trigger_reason` will fail with column-not-found errors after DROP.
**Why it happens:** These columns were dropped from the schema (confirmed by column inventory vs signal_ledger_full view).
**How to avoid:** For each dropped column, either:
- Remove from SELECT and API response (signal_type, feature_tf, bucket_scores, staleness_*)
- Extract from frame_details JSONB if still needed (stop_basis: `tf.frame_details->>'stop_basis'`)
The signal_ledger_full view has `stop_price AS stop_loss` from trade_frames, `was_selected` from trade_frames, `entry_price` from trade_frames, `targets` and lifecycle fields as NULL.

---

## Code Examples

### signal_events_repository.py Skeleton

```python
# Source: src/persistence/repository/signal_ledger_repository.py (rewrite target)
class SignalEventsRepository:
    """Repository for signal_events, trade_frames, trade_executions persistence."""

    def __init__(self, db_manager: Any):
        self._db_manager = db_manager

    async def insert_signal_with_frames(
        self,
        signal_event: dict,          # detection fields
        trade_frames: list[dict],    # one per entry_type
    ) -> None:
        """Atomic INSERT: signal_events + trade_frames in one transaction."""
        if self._db_manager.pool is None:
            return
        async with self._db_manager.pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(_INSERT_SIGNAL_EVENTS_SQL, *_to_signal_events_params(signal_event))
                for frame in trade_frames:
                    await conn.execute(_INSERT_TRADE_FRAMES_SQL, *_to_trade_frames_params(frame))

    async def update_signal_status(self, signal_id: str, status: str) -> None:
        """Standalone UPDATE — idempotent, retryable."""
        await self._db_manager.execute_command(_UPDATE_STATUS_SQL, signal_id, status)

    async def get_active_signals_for_bootstrap(self) -> list[dict]:
        """Bootstrap query — direct JOIN on signal_events + trade_frames."""
        return await self._db_manager.execute_query(_BOOTSTRAP_QUERY)
```

### lifecycle_writer Activation Transition Mapping

```python
# lifecycle_writer._flush_activation_items() — after Phase 130 rewrite
async def _flush_activation_items(self, items: list[dict]) -> None:
    for entry in items:
        # 1. Update signal_events.status to 'active'
        await self._repo.update_signal_status(entry["signal_id"], "active")
        # 2. Write activation metadata to trade_frames.frame_details JSONB
        activation_meta = {
            "activated_at": format_iso_ts(entry.get("activated_at")),
            "activation_price": entry.get("activation_price"),
            "zone_entry_pct": entry.get("zone_entry_pct"),
            "bars_to_activation": entry.get("bars_to_activation"),
        }
        await self._repo.update_frame_details(entry["signal_id"], activation_meta)
```

### run_historical_pipeline.py psycopg2 Pattern

```python
# Source: run_historical_pipeline.py:891 (_batch_insert_signals) — rewrite target
# psycopg2 uses %s (not $N), execute_values for batch inserts

_INSERT_SIGNAL_EVENTS_SYNC_SQL = """
INSERT INTO signal_events (
    signal_id, ts, symbol, tf, setup_plugin, direction,
    raw_confidence, cis_score, weights_version,
    factor_scores, context_features,
    ctf_score, ctf_confirmed, zone_friction_score,
    hmm_regime_at_fire, plugin_regime_type, garch_sigma_at_fire,
    is_shadow, is_backfill, status, signal_schema_version,
    ttl_bars, expires_at, signal_computed_at, feature_ts
) VALUES %s
ON CONFLICT (signal_id, ts) DO NOTHING
"""
# direction transform: 1 → 'long', -1 → 'short'
# factor_scores, context_features: from signal dict (ECL fields added Phase 123)
# status: 'pending' initially (will be updated by lifecycle_replay)

_INSERT_TRADE_FRAMES_SYNC_SQL = """
INSERT INTO trade_frames (
    frame_id, signal_id, signal_ts, entry_type, direction,
    entry_price, stop_price, target_price, r_multiple,
    ttl_bars, expires_at, counterfactual_pnl_r, was_selected, frame_details
) VALUES %s
ON CONFLICT (frame_id) DO NOTHING
"""
# frame_id: uuid5(NAMESPACE_DNS, f"{signal_id}:at_close") for historical backfill
```

### Migration 142: APR Seeds

```sql
-- Migration 142: Phase 130 APR parameter seeds
-- Separate from DROP migration for clean rollback boundaries

-- Update OPS_PREFIXES in application code (Python, not SQL)
-- Then seed new keys:

INSERT INTO config_schema (config_key, description, data_type, is_ml_target)
VALUES
    ('feature.signal_writer.batch_size', 'Signal writer batch size [initial_estimate] NOT ML target', 'integer', false),
    ('feature.signal_writer.flush_interval_secs', 'Signal writer flush interval seconds [initial_estimate]', 'float', false),
    -- ... (full list from CONTEXT.md D-12)
    ('ui.signals.recent_window_days', 'Recent signals window days for API [initial_estimate]', 'integer', false)
ON CONFLICT (config_key) DO NOTHING;

INSERT INTO config_state (config_key, config_value, version)
VALUES
    ('feature.signal_writer.batch_size', '100', 1),
    ('feature.signal_writer.flush_interval_secs', '5.0', 1),
    -- ... (full list from CONTEXT.md D-12)
    ('ui.signals.recent_window_days', '90', 1)
ON CONFLICT (config_key) DO NOTHING;
```

### Migration 143: DROP signal_ledger

```sql
-- Migration 143: Phase 130 Drop signal_ledger and signal_outcomes
-- Run ONLY after 48-hour verification window with all writers on new schema

-- Step 1: Drop signal_outcomes (no dependents)
DROP TABLE IF EXISTS signal_outcomes;

-- Step 2: Drop signal_ledger (CASCADE drops any remaining dependent objects)
DROP TABLE IF EXISTS signal_ledger CASCADE;

-- Step 3: Rename backward-compat view to canonical name
ALTER VIEW signal_ledger_full RENAME TO signal_ledger;

-- Verification: code querying 'signal_ledger' now hits the JOIN view
-- Verification: code querying 'signal_ledger_full' will break (expected)
```

---

## State of the Art

| Old Approach | Current Approach | Notes |
|--------------|------------------|-------|
| signal_ledger monolith (47 cols) | signal_events (detection) + trade_frames (hypothesis) + trade_executions (execution) | Phase 128-130 migration |
| signal_outcomes for lifecycle state | signal_events.status + trade_frames.frame_details JSONB | Phase 130 |
| LedgerEntry dataclass → signal_ledger INSERT | Two dataclasses: SignalEventRow + TradeFrameRow | Phase 130 |
| direction as integer 1/-1 | direction as text "long"/"short" | Changed in Phase 128 ADR |
| signal_type column | Dropped — not in new schema | No replacement |
| bucket_scores column | Dropped — not in new schema | No replacement |
| staleness_score / staleness_trigger_reason | Dropped — no home in new schema | MAE/mfe via counterfactual |
| feature_tf column | Dropped — not in new schema | Use tf from signal_events |
| pipeline_lag_ms column | Dropped — computed from intelligence_features | Not in new schema |

---

## Open Questions

1. **concurrent_signal_count population**
   - What we know: D-08 says signal_writer should compute this from signal_tracker's in-memory active_signals. Signal_writer and signal_tracker are separate OS processes.
   - What's unclear: How signal_writer gets access to signal_tracker's active index without a shared process or extra DB query.
   - Recommendation: Leave NULL for Phase 130. Add population logic as part of v2.11 (enrichment pass or intelligence_pipeline payload enrichment).

2. **signal_tracker bootstrap targets column**
   - What we know: bootstrap query uses `sl.targets` (JSONB array). In new schema, only `trade_frames.target_price` exists (first target only, float8).
   - What's unclear: Whether signal_tracker needs multiple targets post-Phase 130 (for TTL evaluation).
   - Recommendation: Pull `target_price` as first target from trade_frames. Adapt signal canonical dict to wrap it as `targets: [target_price]` for backward compatibility with evaluate_signal().

3. **feature_replay.py rewrite scope**
   - What we know: file writes to signal_ledger (line 82) and signal_outcomes (line 125); not in CONTEXT.md D-09 list.
   - What's unclear: Whether it's actively used in Phase 127 replay or deferred.
   - Recommendation: Include in Phase 130 rewrite. It's a straightforward adaptation of the same G0 pattern.

---

## Codebase Findings

### File Inventory — Write-Path Services

| File | Lines | Write Target | Change Required |
|------|-------|--------------|----------------|
| `src/persistence/repository/signal_ledger_repository.py` | 863 | signal_ledger, signal_outcomes | Full rewrite → signal_events_repository.py |
| `services/signal_writer.py` | 265 | via repository | G0 grouping logic; APR for class constants |
| `services/lifecycle_writer.py` | 234 | via repository + direct EXIT SQL | Update exit SQL; activation → frame_details |
| `services/signal_tracker.py` | 1302 | read-only (bootstrap DB read) | Bootstrap query rewrite; APR for constants |
| `services/swarm_ledger_writer.py` | 277 | signal_ai_enrichment (unchanged) | One-line FK check update |
| `services/signal_auditor.py` | ~350 | read-only | Docstring + comment updates; minor SQL update |
| `src/api/routes/signals.py` | 1041 | read-only | All queries; drop unavailable columns |
| `src/api/routes/narrative.py` | ~170 | read-only | feature_tf → tf |
| `production/scripts/run_historical_pipeline.py` | 2422+ | signal_ledger, signal_outcomes | G0 pattern, psycopg2 inserts |
| `production/scripts/lifecycle_replay.py` | 1309+ | signal_outcomes | UPDATE signal_events.status |
| `production/scripts/feature_replay.py` | ~130 | signal_ledger, signal_outcomes | G0 pattern (NOT IN D-09) |

### File Inventory — Read-Only Services (auto-fixed by view rename in I8)

Verified read-only (SELECT only, no INSERT/UPDATE/DELETE on signal_ledger or signal_outcomes):
- `services/confidence_calibration_monitor.py` — queries signal_ledger_full
- `services/signal_probe_auditor.py` — queries signal_ledger_full + signal_outcomes SELECT
- `services/data_quality_auditor.py` — queries signal_ledger_full
- `services/quality_floor_bootstrap.py` — queries signal_ledger_full
- `services/signal_metrics_analyzer.py` — queries signal_ledger_full
- `services/signal_replay_auditor.py` — queries signal_ledger_full
- `services/ml_discovery_analyzer.py` — queries signal_ledger_full
- `services/shadow_auditor.py` — queries signal_ledger_full
- `services/graduation_analyzer.py` — queries signal_ledger_full
- `services/shadow_validator.py` — queries signal_ledger (SELECT) + writes to shadow_registry (different table)
- `services/alpha_swarm.py` — queries signal_ledger_full (SELECT)

**Caveat:** `signal_probe_auditor.py` uses `LEFT JOIN signal_outcomes so USING (signal_id)` for a SELECT (line 217). After signal_outcomes is dropped, this join will fail. This service needs the signal_outcomes JOIN removed or replaced with signal_events columns.

### Column Gaps in signal_ledger_full View vs Legacy signal_ledger

Columns in `signal_ledger` (legacy) that are NOT available in `signal_ledger_full` view:

| Column | Was In | Now | Action Required |
|--------|--------|-----|----------------|
| signal_type | signal_ledger | Dropped | Remove from API responses |
| feature_tf | signal_ledger | Dropped | Use `tf` from signal_events |
| pipeline_lag_ms | signal_ledger | Dropped | Use intelligence_features for lag |
| feature_schema_version | signal_ledger | Dropped | Remove from queries |
| staleness_score | signal_outcomes | Dropped | Remove from API responses |
| staleness_trigger_reason | signal_outcomes | Dropped | Remove from API responses |
| stop_basis | signal_ledger | In trade_frames.frame_details | Extract: `tf.frame_details->>'stop_basis'` |
| bucket_scores | signal_ledger | Dropped | Remove from API responses |
| exit_at | signal_outcomes | In view as `te.exited_at AS exit_at` | Already in view via trade_executions |

Columns in `signal_ledger_full` view that are NULL (from dropped signal_outcomes):
`activated_at`, `activation_price`, `targets`, `entry_zone_low`, `entry_zone_high`, `market_entry_price`, `trailing_stop_price`, `chandelier_vol_source`, `mae`, `mfe`

These are NULL for historical rows (pre-Phase 130) and will populate for new rows only after lifecycle events flow through the new system.

### Migration Numbering

Last applied migration: `141_trade_frames_labeled_data_index.sql`
Next available: 142 (APR seeds), 143 (DROP signal_ledger)

---

## Sources

### Primary (HIGH confidence)
- `production/migrations/137_3table_schema.sql` — authoritative DDL for all three tables and signal_ledger_full view
- `production/scripts/migrate_signal_ledger.py` — established patterns: uuid5 frame_id generation, direction encoding, column mapping
- `docs/signals/signal-trade-separation-ADR.md` — full column specifications and design rationale
- Live DB inspection: `\d signal_events`, `\d trade_frames`, column inventory of signal_ledger_full view
- `.planning/phases/130-script-rewriting/130-CONTEXT.md` — locked decisions D-01 through D-15

### Secondary (MEDIUM confidence)
- `services/signal_writer.py`, `services/lifecycle_writer.py`, `services/signal_tracker.py` — current write-path code
- `src/persistence/repository/signal_ledger_repository.py` — current repository (rewrite target, 15+ methods)
- `src/api/routes/signals.py` — current API queries with column references

### Tertiary (research observation, verify during planning)
- `services/signal_probe_auditor.py` line 217 — LEFT JOIN signal_outcomes will break after DROP; needs verification that it's a SELECT-only join
- `feature_replay.py` lines 82, 125 — writes to signal_ledger/signal_outcomes; not in CONTEXT.md D-09 file list

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — asyncpg, psycopg2, uuid are all in production use
- Architecture: HIGH — migration DDL is authoritative; ADR is locked
- Pitfalls: HIGH for most; MEDIUM for signal_tracker bootstrap (requires plan-time query design)
- Column mapping: HIGH — verified against live DB schema

**Research date:** 2026-06-16
**Valid until:** 2026-07-16 (stable schema; no upstream changes expected before Phase 130 executes)
