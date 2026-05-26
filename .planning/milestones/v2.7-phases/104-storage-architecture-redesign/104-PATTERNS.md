# Phase 104: Storage Architecture Redesign - Pattern Map

**Mapped:** 2026-05-22
**Files analyzed:** 16 new/modified files
**Analogs found:** 14 / 16

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `db/migrations/104_rename_feature_columns.sql` | migration | batch | existing retention policy SQL patterns (RESEARCH.md) | no-analog |
| `db/migrations/104_slim_signal_ledger.sql` | migration | batch | existing retention policy SQL patterns (RESEARCH.md) | no-analog |
| `db/migrations/104_retention_policies.sql` | migration | batch | live DB job patterns (RESEARCH.md) | no-analog |
| `db/migrations/104_create_ml_signal_training.sql` | migration | batch | `ml_signal_training` schema in RESEARCH.md | no-analog |
| `src/persistence/repository/signal_ledger_repository.py` | model | CRUD | itself (major surgery) | self |
| `services/signal_writer_agent.py` | service | request-response | itself + `services/feature_snapshot_writer_agent.py` | self+role-match |
| `services/feature_snapshot_writer_agent.py` | service | — (deleted) | n/a — to be removed | n/a |
| `services/parity_auditor_agent.py` | service | — (deleted) | n/a — to be removed | n/a |
| `services/service_auditor_agent.py` | service | event-driven | itself (minor edit) | self |
| `services/signal_tracker_compute_agent.py` | service | event-driven | itself (read path update) | self |
| `services/lifecycle_writer_agent.py` | service | request-response | itself (read path update) | self |
| `services/signal_auditor_agent.py` | service | CRUD | itself (query column update) | self |
| `services/signal_metrics_compute_agent.py` | service | batch | itself (query column update) | self |
| `services/graduation_compute_agent.py` | service | event-driven | itself (query column update) | self |
| `services/ml_training_agent.py` / new `services/ml_signal_training_agent.py` | service | batch | `services/ml_training_agent.py` | exact |
| `src/api/routes/signals.py` | controller | request-response | itself (JOIN update for dropped columns) | self |
| `production/systemd/indicagent-ml-signal-training-materialize.{service,timer}` | config | batch | `production/systemd/indicagent-ml-training.{service,timer}` | exact |
| `services/feature_writer_agent.py` | service | request-response | itself (column name update only) | self |
| `src/intelligence/ml/feature_builder.py` | utility | batch | itself (column name update) | self |

---

## Pattern Assignments

### Migration files (4 SQL files, no Python analog)

These are pure DDL. No existing migration script analog exists in the repo — the project applies
migrations via direct psql execution, not a migration framework. Write as plain `.sql` files
in `db/migrations/` (or a new `production/migrations/` if that directory does not exist yet).
RESEARCH.md contains the exact verified SQL for all four migrations.

**Pattern to follow — DDL header comment style** (copy from RESEARCH.md SQL blocks verbatim):

```sql
-- Safe: works on compressed hypertables in TimescaleDB 2.25.1
-- Run with: PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f <file>
```

**Execution guard pattern** — use `if_not_exists => true` / `ON CONFLICT DO NOTHING` on every
idempotent statement so re-runs are safe.

---

### `src/persistence/repository/signal_ledger_repository.py` (model, CRUD)

**Analog:** itself — this file IS the `LedgerEntry` dataclass and all SQL. The task is surgical removal of the 47 fire-time duplicate columns.

**Current `LedgerEntry` dataclass** (`signal_ledger_repository.py` lines 55-232):
The dataclass has 67 INSERT fields. The slim schema keeps ~38. Every field from `entry_price`
through `features_snapshot` that duplicates `intelligence_features.trading_signals` JSONB must
be removed from the dataclass AND from `_to_row()`.

**`_INSERT_SQL` pattern** (`signal_ledger_repository.py` lines 240-296):
```sql
INSERT INTO signal_ledger (
    signal_id, timestamp, symbol, timeframe, setup_plugin, signal_type,
    direction, entry_price, stop_loss, targets,
    ...
) VALUES (
    $1::uuid, $2, $3, $4, $5, $6,
    $7, $8, $9, $10::jsonb,
    ...
)
ON CONFLICT ON CONSTRAINT signal_ledger_pkey DO NOTHING
```
After slim migration: remove all JSONB casts for dropped fields; renumber `$N` placeholders
sequentially. `ON CONFLICT ... DO NOTHING` pattern is preserved unchanged.

**Columns to KEEP in slim `LedgerEntry`** (from RESEARCH.md lines 55-69 — authoritative):
```
signal_id, timestamp, symbol, timeframe, is_shadow, was_selected, status, is_backfill,
signal_schema_version, setup_plugin, signal_type, direction,
feature_ts, feature_tf,
activated_at, activation_price, zone_entry_pct, bars_to_activation,
exit_at, exit_price, exit_reason,
pnl_ticks, pnl_r, pnl_dollars, signal_quality,
mae, mfe, bars_in_trade, outcome,
market_entry_at, market_entry_exit_at, market_entry_outcome,
market_entry_pnl_r, market_entry_mae, market_entry_mfe, market_entry_bars_in_trade,
market_entry_gap_bars, market_entry_price, market_entry_exit_price,
trailing_stop_price, staleness_score, staleness_trigger_reason,
shadow_tracking_start_ts, shadow_outcome, shadow_mae, shadow_mfe,
ttl_bars, signal_computed_at
```

**Columns to DROP from `LedgerEntry`** (RESEARCH.md lines 72-84):
```
entry_price, stop_loss, targets, confidence, confluence_score, regime_context,
supporting_factors, num_signals_bar, num_agreeing, num_conflicting,
resolution_method, composite_rank, market_context, cis_score, bucket_scores,
weights_version, determined_at, ask_at_signal, bid_at_signal, market_price_at_signal,
entry_zone_low, entry_zone_high, zone_valid_at_signal, cis_attribution,
stop_basis, stop_structure_type, stop_structure_age_bars, structural_stop_distance_atr,
hmm_regime_at_fire, garch_sigma_at_fire, chandelier_vol_source,
trailing_stop_tightening_rate, raw_cis_score, filtered_cis_score,
calibrated_confidence, regime_type_at_fire, pre_quality_confidence,
pre_calibration_confidence, entry_type, co_fire_count, co_fire_partners,
features_snapshot, adjusted_confidence, swarm_multiplier, swarm_agent_count
```

**CAUTION — `signal_auditor_agent.py` reads `pipeline_lag_ms`** (line 278-284): this column is
a DB-only computed/defaulted column not in the current 67-column INSERT. It is NOT in the slim
schema target either. The `signal_auditor_agent` SQL must move to reading `signal_computed_at`
or be updated to use `intelligence_features.pipeline_latency_ms` instead. Flag this in the plan.

---

### `services/signal_writer_agent.py` (service, request-response)

**Analog:** itself — `_payload_to_ledger_entries()` (lines 156-280+) constructs `LedgerEntry`.

**Current construction pattern** (`signal_writer_agent.py` lines 175-230):
```python
entries.append(
    LedgerEntry(
        signal_id=str(sig.get("signal_id") or uuid4()),
        timestamp=bar_ts,
        symbol=symbol,
        timeframe=tf,
        setup_plugin=str(sig.get("setup_plugin", "unknown")),
        signal_type=str(sig.get("signal_type", "unknown")),
        direction=int(sig.get("direction", 0)),
        entry_price=float(sig.get("entry_price", 0.0)),    # DROP THIS
        stop_loss=float(sig.get("stop_loss", 0.0)),        # DROP THIS
        targets=[float(t) for t in (sig.get("targets") or [])],  # DROP THIS
        confidence=float(sig.get("confidence", 0.0)),      # DROP THIS
        ...
    )
)
```
After migration: remove all keyword arguments corresponding to dropped `LedgerEntry` fields.
`_parse_payload()` and `_flush_batch()` patterns remain identical — only
`_payload_to_ledger_entries()` changes.

**`_flush_batch` pattern** (`signal_writer_agent.py` lines 125-136) — copy unchanged:
```python
async def _flush_batch(self, batch: list) -> None:
    invalid = self._invalid_signals[:]
    self._invalid_signals.clear()
    for sig in invalid:
        await self._send_to_dlq(sig, ValueError("validate_signal failed"))

    t0 = time.perf_counter()
    assert self._repo is not None
    await self._repo.insert_signals(batch)
    self._signals_written.add(len(batch))
    PERSISTENCE_BATCH_LATENCY.record(time.perf_counter() - t0, self._batch_latency_attrs)
    self.logger.info("signal_writer.flushed", count=len(batch))
```

---

### `services/feature_snapshot_writer_agent.py` — TO BE DELETED

**Action:** `systemctl stop indicagent-feature-snapshot-writer && systemctl disable indicagent-feature-snapshot-writer`

Remove from:
1. `services/service_auditor_agent.py` `_DAG_ORDER` (line 82), `_LAG_THRESHOLDS` (line 120), `_AGENT_ID_TO_UNIT` (line 141)
2. `services/dlq_drain_agent.py` topic list
3. Delete `production/systemd/indicagent-feature-snapshot-writer.service`
4. Delete the Python file itself

**No data backup needed** — `feature_snapshots_shadow` is byte-for-byte identical to `intelligence_features`.

---

### `services/parity_auditor_agent.py` — TO BE DELETED

**Action:** Same stop/disable/remove pattern as `feature_snapshot_writer_agent`.

Remove from `service_auditor_agent.py` `_DAG_ORDER` (line 87), `_AGENT_ID_TO_UNIT` (line 151).

Remove these 4 metrics from `src/observability/metrics.py`:
- `PARITY_CYCLES_TOTAL`
- `PARITY_MATCH_RATE`
- `PARITY_VIOLATIONS_TOTAL`
- `SHADOW_AHEAD_ROWS_TOTAL`

Remove Grafana alert rules targeting these metrics before deleting the service (Pitfall 8 in RESEARCH.md).

Delete `production/systemd/indicagent-parity-auditor.service`.

**Replacement health check** — wire into `service_auditor_agent.py` existing audit loop:
```sql
-- From RESEARCH.md (architecture patterns section, line 418-432)
CREATE OR REPLACE FUNCTION check_feature_pipeline_freshness()
RETURNS TABLE(symbol text, tf text, last_ts timestamptz, gap_minutes float)
LANGUAGE sql AS $$
    SELECT symbol, tf, MAX(ts) as last_ts,
           EXTRACT(EPOCH FROM (NOW() - MAX(ts))) / 60.0 as gap_minutes
    FROM intelligence_features
    WHERE ts > NOW() - INTERVAL '30 minutes'
    GROUP BY symbol, tf
    HAVING MAX(ts) < NOW() - INTERVAL '10 minutes'
    ORDER BY gap_minutes DESC;
$$;
```
Call from the existing `_run_audit()` async loop in `service_auditor_agent.py`. Publish to
`topic_alert_requests` if the function returns rows (same pattern as `_check_pipeline_lag`
in `signal_auditor_agent.py` lines 266-288).

---

### `services/service_auditor_agent.py` (service, event-driven)

**Analog:** itself — minor edit to `_DAG_ORDER` dict (lines 50-92).

**Pattern to copy — `_DAG_ORDER` entry format** (`service_auditor_agent.py` lines 50-92):
```python
_DAG_ORDER: dict[str, int] = {
    ...
    "indicagent-feature-snapshot-writer": 8,   # REMOVE this line
    "indicagent-parity-auditor": 9,             # REMOVE this line
    ...
}
```
Remove the two entries. Update `_LAG_THRESHOLDS` and `_AGENT_ID_TO_UNIT` dicts at the same
lines. Add the freshness check DB call to the existing audit cycle (see parity replacement above).

---

### `services/signal_tracker_compute_agent.py` (service, event-driven)

**Analog:** itself — bootstrap SQL read path may reference dropped columns.

**Bootstrap read pattern** (`signal_tracker_compute_agent.py` lines 81-137 — class definition):
The agent seeds `_active_index` from DB at startup. After `signal_ledger` slim migration, any
bootstrap SQL that SELECT-s dropped columns (e.g. `entry_price`, `stop_loss`, `confidence`,
`targets`) must JOIN to `intelligence_features.trading_signals` instead, or be removed if the
lifecycle computation does not need those values.

**Key invariant** — the in-memory `_signal_states` dict tracks `SignalState` fields
(`mae`, `mfe`, `market_mae`, `market_mfe`, `chandelier_state`, `staleness_consecutive`,
`activated_at`, `active_bars_elapsed`, `bars_since_activation`) — none of these are dropped
columns. Only the bootstrap SELECT needs updating.

**Pattern — db read with asyncpg pool** (from `signal_auditor_agent.py` lines 122-131):
```python
async def _setup(self) -> None:
    self._db_pool = await create_db_pool(self.settings.database_url, min_size=1, max_size=3)
    ...
```

---

### `services/lifecycle_writer_agent.py` (service, request-response)

**Analog:** itself — `_TIMESTAMP_FIELDS` frozenset and `SignalLedgerRepository` import.

**`_TIMESTAMP_FIELDS` pattern** (`lifecycle_writer_agent.py` lines 44-52) — preserve as-is:
```python
_TIMESTAMP_FIELDS = frozenset(
    {
        "activated_at",
        "exit_at",
        "shadow_tracking_start_ts",
        "market_entry_at",
        "market_entry_exit_at",
    }
)
```
All these fields are in the slim schema. No changes to `_TIMESTAMP_FIELDS` needed.

The `SignalLedgerRepository` UPDATE methods are separate from the slim INSERT — they only update
lifecycle columns by `signal_id` PK. These UPDATE statements are not affected by the column
drops. Verify that no UPDATE path writes to a dropped column (e.g. `calibrated_confidence`,
`swarm_multiplier`).

---

### `services/signal_auditor_agent.py` (service, CRUD reader)

**Analog:** itself — 3 SQL queries reference `signal_ledger` columns.

**Query 1 — coverage check** (lines ~225): `SELECT ... FROM signal_ledger WHERE symbol=$1 AND timeframe=$2 AND ...`
Only uses `symbol`, `timeframe`, `timestamp` — all in slim schema. No change.

**Query 2 — pipeline lag** (lines 276-288): queries `pipeline_lag_ms`. This column is a
DB-computed column NOT in the slim INSERT schema. Post-migration options:
- Read `pipeline_latency_ms` from `intelligence_features` instead (it tracks per-bar pipeline latency)
- Or keep `pipeline_lag_ms` if it is a DB-side computed column that remains after the slim migration

Flag for investigation before plan step executes.

**Query 3 — CIS distribution** (lines 324-326): queries `cis_score`. This field IS in the
DROP list. After slim migration, this query must JOIN to `intelligence_features.trading_signals`
and extract `cis_score` from the JSONB element by `signal_id`, or be removed.

**Pattern — asyncpg fetchrow** (lines 275-288):
```python
async with self._db_pool.acquire() as conn:
    row = await conn.fetchrow(
        """
        SELECT
          percentile_cont(0.50) WITHIN GROUP (ORDER BY pipeline_lag_ms) AS p50,
          percentile_cont(0.95) WITHIN GROUP (ORDER BY pipeline_lag_ms) AS p95
        FROM signal_ledger
        WHERE symbol = $1
          AND timeframe = $2
          AND feature_ts >= NOW() - INTERVAL '1 hour'
          AND pipeline_lag_ms IS NOT NULL
        """,
        instrument.symbol,
        tf,
    )
```

---

### `services/signal_metrics_compute_agent.py` (service, batch reader)

**Analog:** itself — timer-triggered, reads `signal_ledger` for resolved signals.

**Pattern — 15-minute timer loop** (`signal_metrics_compute_agent.py` lines 1-60):
Queries signal_ledger for resolved signals. The `compute_signal_metrics()` and
`compute_ic_metrics()` functions in `src/intelligence/metrics/compute.py` build the SELECT
query. After slim migration, any references to dropped columns in those compute functions must
either be removed or changed to JOIN `intelligence_features.trading_signals`.

Most metrics (pnl_r, mae, mfe, outcome) are in the slim schema. The risk is metrics that
use `confidence`, `cis_score`, `bucket_scores`, `entry_price`, `stop_loss`. Audit
`src/intelligence/metrics/compute.py` for these references before executing the plan step.

---

### `services/graduation_compute_agent.py` (service, event-driven)

**Analog:** itself — `_EVAL_QUERY` (lines 43-50) JOINs `signal_ledger` on `signal_id`.

**Current query pattern** (`graduation_compute_agent.py` lines 43-50):
```python
_EVAL_QUERY = """
SELECT stl.multiplier, sl.pnl_r, stl.ts
FROM signal_transform_log stl
JOIN signal_ledger sl ON stl.signal_id = sl.signal_id
WHERE stl.transform_id = $1
  AND stl.transform_version = $2
  AND stl.segment_key = $3
  AND stl.ts >= NOW() - ($4::int || ' days')::interval
```
This query selects only `sl.pnl_r` from `signal_ledger`. `pnl_r` IS in the slim schema.
No changes needed for `graduation_compute_agent.py`.

---

### `services/ml_training_agent.py` and new `services/ml_signal_training_agent.py` (service, batch)

**Analog:** `services/ml_training_agent.py` (exact match — oneshot systemd entrypoint pattern).

**Pattern — oneshot entrypoint** (`services/ml_training_agent.py` lines 1-31):
```python
"""ML Training Agent — systemd oneshot entrypoint (Phase 070).

Invoked nightly by indicagent-ml-training.timer (03:00 UTC).
Type=oneshot: runs once, exits.
"""

import asyncio
import _path_bootstrap  # noqa: F401 — project root on sys.path

from src.config.settings import Settings
from src.intelligence.services.ml_training_compute_agent import MLTrainingComputeAgent


def main() -> None:
    """Create agent, run, exit.

    MLTrainingComputeAgent._run() swallows all exceptions and logs them,
    so asyncio.run() always completes cleanly (systemd oneshot exit code 0).
    """
    settings = Settings()
    agent = MLTrainingComputeAgent(settings)
    asyncio.run(agent.start())


if __name__ == "__main__":
    main()
```

New `services/ml_signal_training_agent.py` copies this pattern verbatim, substituting:
- `MLTrainingComputeAgent` → `MLSignalTrainingMaterializeAgent`
- Module path: `src/intelligence/services/ml_signal_training_materialize_agent.py`
- Docstring: references nightly 02:00 UTC timer

**`MLSignalTrainingMaterializeAgent._run()` INSERT pattern** (from `feature_builder.py` lines 84-113):
```python
_TRAINING_SQL = """
SELECT
    sl.signal_id,
    sl.timestamp,
    ...
    (f.i4->>'hmm_regime')::int AS hmm_regime,    -- UPDATE: i4 -> regime_features
    (f.i4->>'trend_regime')::float AS trend_regime,
    f.session_type,
    (f.i1->>'atr_pct')::float AS atr_pct,          -- UPDATE: i1 -> technical_indicators
    (f.i1->>'volume_z_score')::float AS volume_z_score,
    COALESCE((f.i7->0->>'tod_multiplier')::float, 1.0) AS tod_multiplier  -- UPDATE: i7 -> trading_signals
FROM signal_ledger sl
JOIN intelligence_features f
  ON f.symbol = sl.symbol
 AND f.ts = sl.feature_ts
 AND f.tf = sl.feature_tf
 AND f.ts < sl.activated_at
WHERE sl.outcome IS NOT NULL
  AND sl.is_shadow = FALSE
  AND sl.signal_schema_version = $1
  AND sl.features_snapshot IS NOT NULL  -- UPDATE: unnest from trading_signals after slim migration
ORDER BY sl.timestamp
"""
```
After column rename: `f.i4` becomes `f.regime_features`, `f.i1` becomes `f.technical_indicators`,
`f.i7` becomes `f.trading_signals`. The materialize agent inserts the flattened result into
`ml_signal_training` typed columns (no JSONB at destination).

---

### `src/api/routes/signals.py` (controller, request-response)

**Analog:** itself — `_build_signal_row()` (lines 67-130) and `get_active_signals()` (lines 141-240).

**`get_active_signals()` query** (lines 152-188): currently selects `entry_price`, `stop_loss`,
`confidence`, `cis_score`, `targets`, `regime_context`, `stop_basis`, `market_price_at_signal`,
`ask_at_signal`, `bid_at_signal`, `entry_zone_low`, `entry_zone_high`, `zone_valid_at_signal`
from `signal_ledger` directly. After slim migration, these must come from a JOIN to
`intelligence_features.trading_signals` JSONB.

**Pattern — JOIN to i7/trading_signals for fire-time data:**
```sql
SELECT
    sl.signal_id, sl.symbol, sl.timeframe, sl.status, sl.was_selected,
    sl.feature_ts, sl.timestamp, sl.signal_computed_at,
    -- Fire-time data now lives in intelligence_features.trading_signals JSONB
    tf_sig.value->>'entry_price' AS entry_price,
    tf_sig.value->>'stop_loss' AS stop_loss,
    tf_sig.value->>'confidence' AS confidence,
    tf_sig.value->>'cis_score' AS cis_score,
    tf_sig.value->'targets' AS targets,
    tf_sig.value->>'regime_context' AS regime_context
FROM signal_ledger sl
LEFT JOIN intelligence_features f
  ON f.ts = sl.feature_ts AND f.symbol = sl.symbol AND f.tf = sl.feature_tf
LEFT JOIN LATERAL jsonb_array_elements(f.trading_signals) AS tf_sig(value)
  ON tf_sig.value->>'signal_id' = sl.signal_id::text
WHERE sl.status IN ('pending', 'active')
  AND sl.timestamp >= NOW() - INTERVAL '7 days'
ORDER BY sl.symbol, sl.timeframe, sl.signal_computed_at DESC
LIMIT 500
```
After column rename: `f.i7` becomes `f.trading_signals` in the LATERAL JOIN.

**`_build_signal_row()` with `include_features=True`** (lines 120-130):
```python
signal["features"] = {
    "bar": _parse_jsonb(row["bar"], default=None),
    "i1": _parse_jsonb(row["i1"], default=None),   # UPDATE: rename key to technical_indicators
    "i3": _parse_jsonb(row["i3"], default=None),   # UPDATE: pattern_detections
    "i4": _parse_jsonb(row["i4"], default=None),   # UPDATE: regime_features
    "i5": _parse_jsonb(row["i5"], default=None),   # UPDATE: confluence_scores
    "smc": _parse_jsonb(row["smc"], default=None), # unchanged
    "i6": _parse_jsonb(row["i6"], default=None),   # UPDATE: cross_timeframe_context
}
```
The response JSON key names facing the dashboard (`"i1"`, `"i3"`, etc.) may need to stay
as-is for backward compat with the Next.js dashboard, or be updated atomically with the
dashboard. Coordinate with the dashboard update.

---

### `production/systemd/indicagent-ml-signal-training-materialize.{service,timer}` (config, batch)

**Analog:** `production/systemd/indicagent-ml-training.{service,timer}` (exact match).

**Service unit pattern** (`production/systemd/indicagent-ml-training.service`):
```ini
[Unit]
Description=IndicAgent ML Training Compute Agent -- nightly LightGBM training
After=network.target

[Service]
Type=oneshot
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
Environment=PYTHONUNBUFFERED=1
Environment=INDICAGENT_ENV=development
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/ml_training_agent.py
TimeoutStartSec=7200

[Install]
WantedBy=multi-user.target
```
Copy verbatim, change `Description`, `ExecStart` to `services/ml_signal_training_agent.py`,
and add `StandardOutput`/`StandardError` append lines (from RESEARCH.md pattern).

**Timer unit pattern** (`production/systemd/indicagent-ml-training.timer`):
```ini
[Unit]
Description=ML Training Timer -- nightly 03:00 UTC

[Timer]
OnCalendar=*-*-* 03:00:00 UTC
Persistent=true
Unit=indicagent-ml-training.service

[Install]
WantedBy=timers.target
```
Copy verbatim, change `Description` to `ML Signal Training Materialization Timer -- nightly 02:00 UTC`,
`OnCalendar` to `02:00:00 UTC` (runs before ML training at 03:00), and `Unit` to
`indicagent-ml-signal-training-materialize.service`.

---

### `services/feature_writer_agent.py` (service, request-response)

**Analog:** itself — `_INSERT_FEATURE_SQL` (lines 63-93).

**Column name update** — after `ALTER TABLE intelligence_features RENAME COLUMN i1 TO technical_indicators`, the INSERT must change from:
```sql
bar, i1, i2, i3, i4, i5, smc, i6, i7,
...
$8::jsonb, $9::jsonb, $10::jsonb, $11::jsonb, $12::jsonb,
$13::jsonb, $14::jsonb, $15::jsonb,
```
to:
```sql
bar, technical_indicators, market_context, pattern_detections, regime_features,
confluence_scores, smc_features, cross_timeframe_context, trading_signals,
...
$8::jsonb, $9::jsonb, $10::jsonb, $11::jsonb, $12::jsonb,
$13::jsonb, $14::jsonb, $15::jsonb,
```
`smc` per CONTEXT.md decision stays as-is (acceptable). Python parameter positions `$8`-`$15`
do not change — only the SQL column names change.

Also update the `i7` UPSERT SQL at line 101:
```sql
SET i7 = COALESCE(i7, '{}'::jsonb) || $4::jsonb
```
becomes:
```sql
SET trading_signals = COALESCE(trading_signals, '{}'::jsonb) || $4::jsonb
```

---

### `src/intelligence/ml/feature_builder.py` (utility, batch)

**Analog:** itself — `_TRAINING_SQL` (lines 84-113).

**Column name update** (`feature_builder.py` lines 96-101):
```python
# BEFORE (current):
(f.i4->>'hmm_regime')::int AS hmm_regime,
(f.i4->>'trend_regime')::float AS trend_regime,
...
(f.i1->>'atr_pct')::float AS atr_pct,
(f.i1->>'volume_z_score')::float AS volume_z_score,
COALESCE((f.i7->0->>'tod_multiplier')::float, 1.0) AS tod_multiplier

# AFTER (post-rename):
(f.regime_features->>'hmm_regime')::int AS hmm_regime,
(f.regime_features->>'trend_regime')::float AS trend_regime,
...
(f.technical_indicators->>'atr_pct')::float AS atr_pct,
(f.technical_indicators->>'volume_z_score')::float AS volume_z_score,
COALESCE((f.trading_signals->0->>'tod_multiplier')::float, 1.0) AS tod_multiplier
```
Only these 3 column references change. The Python DataFrame logic (`build_training_matrix`)
is unchanged.

---

## Shared Patterns

### asyncpg JSONB access (apply to all new SQL involving trading_signals JSONB)

**Source:** `services/feature_writer_agent.py`, `src/intelligence/ml/feature_builder.py`

asyncpg returns JSONB columns as Python `dict` — never call `json.loads()`. Pass `dict`/`list`
for JSONB INSERT params — never `json.dumps()`. LATERAL unnesting returns one row per array
element; `->>'key'` extracts text, `->key` returns JSONB sub-object.

```python
# asyncpg JSONB read (no json.loads needed):
row = await conn.fetchrow("SELECT trading_signals FROM intelligence_features WHERE ...")
signals: list[dict] = row["trading_signals"]  # already a Python list

# asyncpg JSONB write (no json.dumps needed):
await conn.execute("INSERT ... VALUES ($1::jsonb)", {"key": "value"})
```

### structlog event logging (apply to all new Python files)

**Source:** `services/signal_writer_agent.py`, `services/feature_snapshot_writer_agent.py`

```python
import structlog
logger = structlog.get_logger(__name__)

# Log with keyword args — NEVER use event= kwarg (collision with structlog internals)
logger.info("ml_signal_training.flushed", count=len(batch))
logger.warning("ml_signal_training.no_rows", schema_version=SIGNAL_SCHEMA_VERSION)
logger.error("ml_signal_training.insert_failed", error=str(exc))
```

### OTel metrics pattern (apply to new ml_signal_training_materialize service)

**Source:** `services/signal_metrics_compute_agent.py` lines 47-60

```python
from opentelemetry import metrics as _otel_metrics
_meter = _otel_metrics.get_meter("indicagent")

_CYCLES = _meter.create_counter("ml_signal_training_cycles_total", description="...")
_ERRORS = _meter.create_counter("ml_signal_training_errors_total", description="...")
_DURATION = _meter.create_histogram(
    "ml_signal_training_duration_seconds", description="...", unit="s"
)
_ROWS = _meter.create_up_down_counter("ml_signal_training_rows_materialized", description="...")
```
Never import `prometheus_client` (removed in Phase 83).

### BaseWriterAgent flush pattern (apply only if ml_signal_training_materialize is a writer)

**Source:** `services/signal_writer_agent.py` lines 125-136, `services/feature_snapshot_writer_agent.py` lines 90-94

```python
async def _flush_batch(self, batch: list) -> None:
    t0 = time.perf_counter()
    assert self._repo is not None
    await self._repo.insert_batch(batch)
    self._rows_written.add(len(batch))
    PERSISTENCE_BATCH_LATENCY.record(time.perf_counter() - t0, self._batch_latency_attrs)
```
The `ml_signal_training_materialize` agent is a **oneshot** (not a streaming writer), so it
will NOT use `BaseWriterAgent`. Use a plain `asyncio.run()` loop with a single bulk INSERT.
Pattern: `MLTrainingComputeAgent` in `src/intelligence/services/ml_training_compute_agent.py`.

### UTC timestamps (apply to all new Python code)

**Source:** CLAUDE.md core rules

```python
from datetime import UTC, datetime
now = datetime.now(UTC)          # CORRECT
# datetime.now() and datetime.utcnow() are FORBIDDEN
```

### _path_bootstrap in service entrypoints (apply to all `services/*.py` files)

**Source:** `services/ml_training_agent.py` line 11

```python
import _path_bootstrap  # noqa: F401 — project root on sys.path
```
Required in every `services/` entrypoint to put the project root on `sys.path`.

---

## No Analog Found

Files with no existing close match:

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `db/migrations/104_rename_feature_columns.sql` | migration | batch | No migration SQL files exist in repo — use psql direct execution pattern from RESEARCH.md |
| `db/migrations/104_slim_signal_ledger.sql` | migration | batch | Same — no migration framework |
| `db/migrations/104_retention_policies.sql` | migration | batch | Same |
| `db/migrations/104_create_ml_signal_training.sql` | migration | batch | Same |

---

## Critical Sequencing Notes for Planner

The RESEARCH.md execution order is binding — three constraints drive the sequence:

1. **Column rename and signal_ledger slim must be in the same maintenance window** (RESEARCH.md line 23). Services that INSERT to `intelligence_features` must be stopped before the DDL, restarted after code deploy. Stop order: `indicagent-feature-writer` → run DDL → deploy code → start `indicagent-feature-writer`.

2. **DROP COLUMN on signal_ledger triggers recompression** (RESEARCH.md Pitfall 3, lines 464-469). Plan a 10-30 minute maintenance window for 77 chunks / 12 GB. Alternative: stop writing the columns first, drop later.

3. **`ml_signal_training` table must be created AFTER the slim ledger is live** (the nightly materialize job reads from the slim schema).

---

## Metadata

**Analog search scope:** `/home/bg/dev/indicagent/services/`, `/home/bg/dev/indicagent/src/persistence/`, `/home/bg/dev/indicagent/src/api/routes/`, `/home/bg/dev/indicagent/src/intelligence/ml/`, `/home/bg/dev/indicagent/production/systemd/`
**Files scanned:** 18
**Pattern extraction date:** 2026-05-22
