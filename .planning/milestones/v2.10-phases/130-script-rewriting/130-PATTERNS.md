# Phase 130: Script Rewriting - Pattern Map

**Mapped:** 2026-06-16
**Files analyzed:** 11 (core write-path) + 3 (supporting: config_service, signal_probe_auditor, narrative)
**Analogs found:** 11 / 11

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/persistence/repository/signal_events_repository.py` (rename from `signal_ledger_repository.py`) | repository | CRUD | `src/persistence/repository/signal_ledger_repository.py` | self (rewrite in place) |
| `services/signal_writer.py` | writer service | batch/CRUD | `services/signal_writer.py` | self (rewrite in place) |
| `services/lifecycle_writer.py` | writer service | batch/CRUD | `services/lifecycle_writer.py` | self (rewrite in place) |
| `services/signal_tracker.py` | tracker service | event-driven + DB bootstrap | `services/signal_tracker.py` | self (bootstrap query rewrite) |
| `services/swarm_ledger_writer.py` | writer service | event-driven | `services/swarm_ledger_writer.py` | self (one-line FK update) |
| `services/signal_auditor.py` | auditor service | request-response | `services/signal_auditor.py` | self (comment + docstring updates) |
| `src/api/routes/signals.py` | API route | request-response | `src/api/routes/signals.py` | self (SQL + column rewrite) |
| `src/api/routes/narrative.py` | API route | request-response | `src/api/routes/narrative.py` | self (feature_tf → tf) |
| `production/scripts/run_historical_pipeline.py` | batch script | batch/CRUD | `production/scripts/run_historical_pipeline.py` | self (SQL rewrite; psycopg2) |
| `production/scripts/lifecycle_replay.py` | batch script | batch/CRUD | `production/scripts/lifecycle_replay.py` | self (SQL rewrite; psycopg2) |
| `production/scripts/feature_replay.py` | batch script | batch/CRUD | `production/scripts/feature_replay.py` | self (SQL rewrite; asyncpg) |
| `src/config/config_service.py` | config | utility | `src/config/config_service.py` | self (OPS_PREFIXES one-liner) |
| `services/signal_probe_auditor.py` | auditor service | request-response | `services/signal_probe_auditor.py` | self (remove signal_outcomes JOIN) |

---

## Pattern Assignments

### `src/persistence/repository/signal_events_repository.py` (repository, CRUD)

**Analog:** `src/persistence/repository/signal_ledger_repository.py` — full rewrite in place; file and class renamed.

**File rename:** `signal_ledger_repository.py` → `signal_events_repository.py`
**Class rename:** `SignalLedgerRepository` → `SignalEventsRepository`
**All importers** that do `from src.persistence.repository.signal_ledger_repository import SignalLedgerRepository` (or `LedgerEntry`, `SignalStatus`, etc.) must be updated.

**Imports pattern** (lines 1-45 of current file — keep structlog, dataclass, Enum; drop LedgerEntry dataclass and replace with two new dataclasses):
```python
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_FRAME_ID_NS = uuid.NAMESPACE_DNS


def _make_frame_id(signal_id: str, entry_type: str) -> str:
    """Deterministic frame_id — same signal_id + entry_type always produces the same UUID."""
    return str(uuid.uuid5(_FRAME_ID_NS, f"{signal_id}:{entry_type}"))
```

**Preserved from current file — keep as-is:**
```python
class SignalStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    REGIME_SUPPRESSED = "regime_suppressed"
    EXPIRED = "expired"

# SignalOutcome, STOP_OUTCOMES, TTL_OUTCOMES, WIN_OUTCOMES imports from signal_outcome.py
```

**SQL INSERT for signal_events** (replace `_INSERT_SQL` and `_INSERT_OUTCOMES_SQL`, lines 145-186):
```python
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
# KEY constraints:
# - direction is TEXT "long"/"short", NOT integer 1/-1
# - status starts as 'pending' or 'regime_suppressed'
# - concurrent_signal_count and concurrent_plugins left NULL (Phase 130; v2.11 populates)
# - signal_schema_version is int4 (from SIGNAL_SCHEMA_VERSION constant) — do NOT str() it

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
# frame_id = _make_frame_id(signal_id, entry_type)
# signal_ts = same datetime as signal_events.ts (FK anchor)
# counterfactual_pnl_r = NULL always (CounterfactualTracker is v2.11)
# frame_details JSONB: stop_basis, stop_type_col, structural_stop_distance_atr,
#   adaptive_buffer_mult, stop_structure_age_bars, entry_zone_low, entry_zone_high
```

**Transaction pattern for atomic insert** (replaces `insert_signals_with_features`, extend to new shape):
```python
async def insert_signal_with_frames(
    self,
    signal_event: dict,       # detection fields for signal_events
    trade_frames: list[dict], # one per entry_type
) -> None:
    """Atomic INSERT: signal_events + trade_frames in one asyncpg transaction.

    If trade_frames INSERT fails, signal_events rolls back (D-11).
    """
    if self._db_manager.pool is None:
        return
    async with self._db_manager.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                _INSERT_SIGNAL_EVENTS_SQL,
                *_to_signal_events_params(signal_event),
            )
            for frame in trade_frames:
                await conn.execute(
                    _INSERT_TRADE_FRAMES_SQL,
                    *_to_trade_frames_params(frame),
                )
    logger.info(
        "Wrote signal_events + trade_frames atomically",
        signal_id=signal_event["signal_id"],
        frame_count=len(trade_frames),
    )
```

**Lifecycle UPDATE patterns** (replace all `signal_outcomes` UPDATE SQLs):
```python
_UPDATE_STATUS_SQL = """
UPDATE signal_events
SET status = $2
WHERE signal_id = $1::uuid
"""

_UPDATE_FRAME_DETAILS_SQL = """
UPDATE trade_frames
SET frame_details = frame_details || $2::jsonb
WHERE signal_id = $1::uuid
"""

_INSERT_TRADE_EXECUTION_SQL = """
INSERT INTO trade_executions (
    execution_id, frame_id,
    actual_fill_price, actual_exit_price, actual_pnl_r,
    actual_mfe, actual_mae, actual_bars,
    market_entry_price, market_entry_gap_bars,
    exit_reason, executed_at, exited_at, regime_at_exit
) VALUES (
    $1::uuid, $2::uuid,
    $3, $4, $5,
    $6, $7, $8,
    $9, $10,
    $11, $12, $13, $14
)
ON CONFLICT (execution_id) DO NOTHING
"""
```

**Bootstrap query** (replace `_SELECT_ACTIVE_SQL` and `_SELECT_ACTIVE_BY_SYMBOL_SQL` that query `signal_ledger_full`):
```python
_BOOTSTRAP_QUERY = """
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
    tf.frame_details->>'trailing_stop_price' AS trailing_stop_price,
    tf.frame_details->>'chandelier_vol_source' AS chandelier_vol_source,
    (tf.frame_details->>'activated_at')::timestamptz AS activated_at
FROM signal_events se
LEFT JOIN trade_frames tf ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts
WHERE se.status IN ('pending', 'active', 'regime_suppressed')
  AND (
    (se.status = 'pending' AND se.ts > NOW() - ($1 * INTERVAL '1 day'))
    OR (se.status IN ('active', 'regime_suppressed') AND se.ts > NOW() - ($2 * INTERVAL '1 day'))
  )
"""
# $1 = bootstrap_pending_window_days (APR: feature.signal_tracker.bootstrap_pending_window_days, default 7)
# $2 = bootstrap_active_window_days  (APR: feature.signal_tracker.bootstrap_active_window_days,  default 30)
# NOTE: targets becomes [target_price] wrapped in list — adapt _load_signal() accordingly
```

**batch_execute method** — keep the same signature and dispatch pattern but update SQL constants:
- `"activation"` transition type: UPDATE `signal_events.status = 'active'` + UPDATE `trade_frames.frame_details` with activation metadata
- `"exit"` transition type: INSERT `trade_executions` row (replaces UPDATE `signal_outcomes`)
- `"chandelier_update"` transition type: UPDATE `trade_frames.frame_details || jsonb_patch`
- `"mae_mfe_update"` transition type: UPDATE `trade_frames.frame_details || jsonb_patch` (v2.11 populates properly via CounterfactualTracker; Phase 130 writes to frame_details for continuity)
- `"shadow_outcome"` transition type: UPDATE `trade_frames.frame_details || jsonb_patch`
- `"market_resolution"` transition type: UPDATE `trade_executions` or INSERT new execution row

**Error handling pattern** (lines 850-862 of current file — keep unchanged):
```python
else:
    raise ValueError(
        f"Unknown transition_type '{transition_type}'. "
        "Must be one of: activation, exit, chandelier_update, "
        "mae_mfe_update, shadow_outcome, market_resolution"
    )
await self._db_manager.execute_batch(sql, params)
logger.info("batch_execute completed", transition_type=transition_type, count=len(items))
```

**Docstring correction** (line 1):
```python
"""Signal Events Repository — data access layer for signal_events, trade_frames, trade_executions.

Provides write operations for 3-table signal architecture (Phase 130):
  - insert_signal_with_frames(): atomic signal_events + trade_frames INSERT
  - update_signal_status(): standalone signal_events.status UPDATE (idempotent)
  - update_frame_details(): merge JSONB patch into trade_frames.frame_details
  - batch_execute(): batched lifecycle transitions grouped by type
"""
```

---

### `services/signal_writer.py` (writer service, batch/CRUD)

**Analog:** `services/signal_writer.py` — rewrite in place.

**Docstring correction** (line 2):
```
Signal Writer Agent — persists I7 signals to signal_events/trade_frames (3-table schema).
```

**Imports change** (lines 34-38 — update repository import):
```python
from src.persistence.repository.signal_events_repository import (
    SignalEventsRepository,
    SignalStatus,
    _make_frame_id,
)
from src.intelligence.trading.signal_schema import SIGNAL_SCHEMA_VERSION, validate_signal
```

**APR constants** — replace class-level constants with APR loads in `_setup()`:
```python
# REMOVE these class-level constants (lines 50-52):
#   BATCH_SIZE = 100
#   FLUSH_INTERVAL_SECS = 5.0
#   MAX_BUFFER_SIZE = 10_000

# ADD in _setup() after ConfigService init:
async def _setup(self) -> None:
    self._db = DatabaseManager(self.settings.database_url)
    await self._db.initialize()
    self._config_service = ConfigService(self.settings.database_url, pool=self._db.pool)
    await self._config_service.initialize()
    self._batch_size = await self._config_service.get(
        "feature.signal_writer.batch_size", default=100
    )
    self._flush_interval = await self._config_service.get(
        "feature.signal_writer.flush_interval_secs", default=5.0
    )
    self._max_buffer_size = await self._config_service.get(
        "feature.signal_writer.max_buffer_size", default=10_000
    )
    self._repo = SignalEventsRepository(self._db)
    # ... rest of setup unchanged
```

**G0 grouping — `_parse_payload` rewrite** (replace lines 94-128):
```python
from collections import defaultdict

def _parse_payload(self, payload: dict) -> tuple[list, list]:
    """Parse i7.signals payload: group by signal_id, validate, return (rows, dlq)."""
    signals: list[dict] = payload.get("signals", [])
    if not signals:
        return [], []

    valid_sigs, invalid_sigs = [], []
    for sig in signals:
        if validate_signal(sig):
            valid_sigs.append(sig)
        else:
            invalid_sigs.append(sig)

    if invalid_sigs:
        self._invalid_signals.extend(invalid_sigs)
        self.logger.warning(
            "signal_writer.invalid_signals_partitioned",
            count=len(invalid_sigs),
            symbol=payload.get("symbol"),
            tf=payload.get("tf"),
        )

    if not valid_sigs:
        return [], [payload]

    # G0 grouping: one signal_events row + N trade_frames rows per signal_id
    event_rows, frame_rows = _parse_payload_to_3table(
        {**payload, "signals": valid_sigs}
    )
    if not event_rows:
        return [], [payload]
    # Return flat list of (event_dict, [frame_dicts]) tuples for _flush_batch
    return list(zip(event_rows, frame_rows)), []
```

**G0 module-level helper** (replace `_payload_to_ledger_entries`, lines 168-260):
```python
def _parse_payload_to_3table(
    payload: dict,
) -> tuple[list[dict], list[list[dict]]]:
    """Convert i7.signals payload to signal_events + trade_frames row lists.

    Returns:
        (signal_events_rows, trade_frames_groups)
        Outer list is per-signal_id group; inner list is per-entry_type frame.
    """
    symbol = payload.get("symbol", "")
    tf = payload.get("tf", "")
    computed_at = parse_iso_ts(payload.get("computed_at"))
    bar_ts = parse_iso_ts(payload.get("bar_ts")) or computed_at

    groups: dict[str, list[dict]] = defaultdict(list)
    for sig in payload.get("signals", []):
        groups[sig["signal_id"]].append(sig)

    event_rows, frame_groups = [], []
    for signal_id, sigs in groups.items():
        detection = sigs[0]  # All share same detection fields
        status = (
            SignalStatus.REGIME_SUPPRESSED.value
            if detection.get("status") == "regime_suppressed"
            else SignalStatus.PENDING.value
        )
        ttl = detection.get("ttl_bars")
        expires_at = _compute_expires_at(bar_ts, ttl, tf)
        direction_text = "long" if int(detection.get("direction", 0)) == 1 else "short"

        event_rows.append({
            "signal_id": str(signal_id),
            "ts": bar_ts,
            "symbol": symbol,
            "tf": tf,
            "setup_plugin": str(detection.get("setup_plugin", "unknown")),
            "direction": direction_text,
            "raw_confidence": detection.get("pre_quality_confidence") or detection.get("confidence"),
            "calibrated_confidence": detection.get("calibrated_confidence"),
            "cis_score": detection.get("filtered_cis_score"),
            "weights_version": detection.get("weights_version"),
            "factor_scores": detection.get("factor_scores"),
            "context_features": detection.get("context_features"),
            "ctf_score": detection.get("ctf_score"),
            "ctf_confirmed": detection.get("ctf_confirmed"),
            "zone_friction_score": detection.get("zone_friction_score"),
            "hmm_regime_at_fire": detection.get("hmm_regime_at_fire"),
            "plugin_regime_type": detection.get("plugin_regime_type"),
            "garch_sigma_at_fire": detection.get("garch_sigma_at_fire"),
            "is_shadow": bool(detection.get("is_shadow", False)),
            "is_backfill": bool(detection.get("is_backfill", False)),
            "status": status,
            "signal_schema_version": SIGNAL_SCHEMA_VERSION,  # int4 — do NOT str()
            "ttl_bars": ttl,
            "expires_at": expires_at,
            "signal_computed_at": computed_at,
            "feature_ts": bar_ts,
        })

        frames = []
        for sig in sigs:
            entry_type = str(sig.get("entry_type", "at_close"))
            frames.append({
                "frame_id": _make_frame_id(str(signal_id), entry_type),
                "signal_id": str(signal_id),
                "signal_ts": bar_ts,
                "entry_type": entry_type,
                "direction": direction_text,
                "entry_price": sig.get("entry_price"),
                "stop_price": sig.get("stop_loss"),
                "target_price": sig.get("targets", [None])[0] if sig.get("targets") else None,
                "r_multiple": None,
                "ttl_bars": ttl,
                "expires_at": expires_at,
                "was_selected": bool(sig.get("was_selected", False)),
                "frame_details": {
                    "stop_basis": sig.get("stop_basis"),
                    "stop_type_col": sig.get("stop_type"),
                    "structural_stop_distance_atr": sig.get("structural_stop_distance_atr"),
                    "adaptive_buffer_mult": sig.get("adaptive_buffer_mult"),
                    "stop_structure_age_bars": sig.get("stop_structure_age_bars"),
                    "entry_zone_low": sig.get("zone_low"),
                    "entry_zone_high": sig.get("zone_high"),
                },
            })
        frame_groups.append(frames)

    return event_rows, frame_groups
```

**`_flush_batch` rewrite** (replace lines 130-141):
```python
async def _flush_batch(self, batch: list) -> None:
    """batch items are (event_dict, [frame_dicts]) tuples from _parse_payload."""
    invalid = self._invalid_signals[:]
    self._invalid_signals.clear()
    for sig in invalid:
        await self._send_to_dlq(sig, ValueError("validate_signal failed"))

    t0 = time.perf_counter()
    assert self._repo is not None
    for event_dict, frames in batch:
        await self._repo.insert_signal_with_frames(event_dict, frames)
    self._signals_written.add(len(batch))
    PERSISTENCE_BATCH_LATENCY.record(time.perf_counter() - t0, self._batch_latency_attrs)
    self.logger.info("signal_writer.flushed", count=len(batch))
```

---

### `services/lifecycle_writer.py` (writer service, batch/CRUD)

**Analog:** `services/lifecycle_writer.py` — rewrite in place.

**Docstring correction** (line 2):
```
Lifecycle Writer Agent — persists signal lifecycle transitions to signal_events.
```

**Import change** (lines 33-35):
```python
from src.persistence.repository.signal_events_repository import (
    SignalEventsRepository,
)
```

**APR constants** (same pattern as signal_writer — remove class-level BATCH_SIZE/FLUSH_INTERVAL_SECS/MAX_BUFFER_SIZE; add to `_setup()`):
```python
# In _setup():
self._config_service = ConfigService(self.settings.database_url, pool=self._db.pool)
await self._config_service.initialize()
self._batch_size = await self._config_service.get(
    "feature.lifecycle_writer.batch_size", default=100
)
self._flush_interval = await self._config_service.get(
    "feature.lifecycle_writer.flush_interval_secs", default=5.0
)
self._max_buffer_size = await self._config_service.get(
    "feature.lifecycle_writer.max_buffer_size", default=10_000
)
self._repo = SignalEventsRepository(self._db)
```

**Activation transition** (replaces `_BATCH_ACTIVATION_SQL` on `signal_outcomes`):
```python
# In _flush_batch, when ttype == "activation":
# 1. UPDATE signal_events.status = 'active'
# 2. UPDATE trade_frames.frame_details with activation metadata
async def _flush_activation_items(self, items: list[dict]) -> None:
    for entry in items:
        await self._repo.update_signal_status(entry["signal_id"], "active")
        activation_meta = {
            k: v for k, v in {
                "activated_at": format_iso_ts(entry.get("activated_at")),
                "activation_price": entry.get("activation_price"),
                "zone_entry_pct": entry.get("zone_entry_pct"),
                "bars_to_activation": entry.get("bars_to_activation"),
            }.items() if v is not None
        }
        if activation_meta:
            await self._repo.update_frame_details(entry["signal_id"], activation_meta)
```

**Exit transition** (replace `_EXIT_IDEMPOTENT_SQL` which targets `signal_outcomes` — now inserts to `trade_executions`):
```python
# _EXIT_IDEMPOTENT_SQL: idempotent INSERT to trade_executions (not UPDATE signal_outcomes)
# "First writer wins" guard: ON CONFLICT (execution_id) DO NOTHING
# execution_id: deterministic uuid5(NAMESPACE_DNS, f"{signal_id}:exit:{exit_at}")

_EXIT_SQL = """
INSERT INTO trade_executions (
    execution_id, frame_id,
    actual_pnl_r, exit_reason, exited_at, actual_fill_price, actual_exit_price
) VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7)
ON CONFLICT (execution_id) DO NOTHING
"""
# Also UPDATE signal_events.status to terminal status (expired/stop_hit/target_hit)
```

**`_flush_batch` group loop** (lines 191-201 — keep same dispatch pattern, update method calls):
```python
for ttype, items in groups.items():
    if ttype == "exit":
        await self._flush_exit_items(items)  # now inserts trade_executions + updates status
    elif ttype == "activation":
        await self._flush_activation_items(items)  # status + frame_details
    else:
        await self._repo.batch_execute(ttype, items)  # chandelier_update, mae_mfe_update, etc.
```

---

### `services/signal_tracker.py` (tracker service, event-driven + DB bootstrap)

**Analog:** `services/signal_tracker.py` — bootstrap query section rewrite + APR constants.

**Import change** — update repository import from `SignalLedgerRepository` to `SignalEventsRepository`.

**APR bootstrap constants** (replace hard-coded values at lines 127, 1170, 1171, 1229):
```python
# In _setup(), after ConfigService init:
self._bootstrap_max_attempts = await self._config_service.get(
    "feature.signal_tracker.bootstrap_max_attempts", default=3
)
self._bootstrap_pending_window_days = await self._config_service.get(
    "feature.signal_tracker.bootstrap_pending_window_days", default=7
)
self._bootstrap_active_window_days = await self._config_service.get(
    "feature.signal_tracker.bootstrap_active_window_days", default=30
)
self._bootstrap_dedup_window_days = await self._config_service.get(
    "feature.signal_tracker.bootstrap_dedup_window_days", default=3
)
```

**Bootstrap query rewrite** (replace `_BOOTSTRAP_QUERY` at lines 1149-1172):
```python
# OLD: queries signal_ledger_full — all lifecycle cols are NULL in the new view
# NEW: direct JOIN on signal_events + trade_frames
_BOOTSTRAP_QUERY = """
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
    tf.frame_details->>'trailing_stop_price' AS trailing_stop_price,
    tf.frame_details->>'chandelier_vol_source' AS chandelier_vol_source,
    (tf.frame_details->>'activated_at')::timestamptz AS activated_at
FROM signal_events se
LEFT JOIN trade_frames tf ON tf.signal_id = se.signal_id AND tf.signal_ts = se.ts
WHERE se.status IN ('pending', 'active', 'regime_suppressed')
  AND (
    (se.status = 'pending' AND se.ts > NOW() - ($1 * INTERVAL '1 day'))
    OR (se.status IN ('active', 'regime_suppressed') AND se.ts > NOW() - ($2 * INTERVAL '1 day'))
  )
"""
# Call: await conn.fetch(_BOOTSTRAP_QUERY, bootstrap_pending_window_days, bootstrap_active_window_days)
```

**Adapt `_load_signal`** — `targets` column no longer available as JSONB array; wrap `target_price` float:
```python
# In _load_signal(raw: dict) or at point of use:
# OLD: canonical["targets"] = raw["targets"]  (JSONB array)
# NEW: canonical["targets"] = [raw["target_price"]] if raw.get("target_price") else []
```

**Empty-ledger check** (lines 1225-1229 — update table reference):
```python
# OLD: FROM signal_ledger_full WHERE ... AND timestamp > NOW() - INTERVAL '3 days'
# NEW:
count_row = await db.execute_query(
    """SELECT COUNT(*) as count FROM signal_events
       WHERE status IN ('pending', 'active')
         AND ts > NOW() - ($1 * INTERVAL '1 day')""",
    self._bootstrap_dedup_window_days,
)
```

**Docstring updates** — update all docstrings referencing `signal_ledger_full bootstrap query` to reference `signal_events + trade_frames JOIN`.

---

### `services/swarm_ledger_writer.py` (writer service, event-driven)

**Analog:** `services/swarm_ledger_writer.py` — one-line FK check update.

**FK existence check** (line 214 — only change in this file):
```python
# OLD:
exists = await conn.fetchval(
    "SELECT 1 FROM signal_ledger WHERE signal_id = $1::uuid LIMIT 1",
    str(signal_id),
)
# NEW:
exists = await conn.fetchval(
    "SELECT 1 FROM signal_events WHERE signal_id = $1::uuid LIMIT 1",
    str(signal_id),
)
```

All other code in this file is unchanged. Docstring update only if it references `signal_ledger` in the class or method docstrings.

---

### `services/signal_auditor.py` (auditor service, request-response)

**Analog:** `services/signal_auditor.py` — docstring and SQL comment updates + APR constant.

**Import change:** `SignalLedgerRepository` → `SignalEventsRepository`

**APR constant** (line 273 SQL INTERVAL):
```python
# In _setup(), after ConfigService init:
self._audit_lookback_hours = await self._config_service.get(
    "feature.signal_auditor.audit_lookback_hours", default=1
)
# In SQL:
# OLD: AND ts > NOW() - INTERVAL '1 hours'
# NEW: AND se.ts > NOW() - ($N * INTERVAL '1 hour')  with param=audit_lookback_hours
```

**SQL updates:** Any SELECT queries that join `signal_outcomes` or `signal_ledger` must be updated:
- `FROM signal_ledger_full` → `FROM signal_ledger` (after I8 rename) or use direct 3-table JOIN
- `JOIN signal_outcomes` → replace with `signal_events.status` column references

---

### `src/api/routes/signals.py` (API route, request-response)

**Analog:** `src/api/routes/signals.py` — SQL rewrite throughout.

**Docstring correction** (line 4):
```python
"""
Signal History API Routes

Queries signal_events/trade_frames via signal_ledger (join view).
"""
```

**Import change** (lines 18-19):
```python
from ...persistence.repository.signal_events_repository import WIN_OUTCOMES as _WIN_OUTCOMES
from ...persistence.repository.signal_events_repository import SignalStatus
```

**APR constants** — remove all module-level constants; inject via ConfigService:
```python
# Remove line 33:
# _RECENT_SIGNAL_WINDOW_DAYS = 90

# Add after app startup or in a setup function:
# All values below loaded via ConfigService.get() at startup:
# ui.signals.recent_window_days       (default 90)
# ui.signals.min_confidence           (default 0.40)
# ui.signals.min_cis_score            (default 0.35)
# ui.signals.today_window_hours       (default 24)
# ui.signals.yesterday_window_hours   (default 48)
# ui.signals.short_window_days        (default 7)
# ui.signals.medium_window_days       (default 30)
# ui.signals.latency_threshold_minutes (default 5)
# ui.signals.max_results              (default 500)
# ui.signals.top_n_results            (default 10)
```

**Query strategy** (D-10): use `signal_ledger` view for all API endpoints — it provides the same column surface as the old monolith. The view is named `signal_ledger_full` until I8 runs; update ALL references to `signal_ledger_full` to `signal_ledger` BEFORE running I8.

**Pattern for dropping unavailable columns from response** (replace references to dropped columns):
```python
# REMOVE from _build_signal_row() and all SELECT lists:
#   row["signal_type"]            — dropped
#   row["feature_tf"]             — dropped; use row["tf"] or row["timeframe"] from signal_events
#   row["pipeline_lag_ms"]        — dropped
#   row["feature_schema_version"] — dropped
#   row["staleness_score"]        — dropped (from signal_outcomes)
#   row["staleness_trigger_reason"] — dropped (from signal_outcomes)
#   row["bucket_scores"]          — dropped

# For stop_basis — still available via trade_frames.frame_details:
# In signal_ledger view: tf.frame_details->>'stop_basis' AS stop_basis (add to view if needed)
# Or: query separately per signal_id for detail endpoints
```

**Queries using `signal_ledger JOIN signal_outcomes`** (lines 196-197 — one endpoint still uses the old JOIN):
```python
# OLD (lines 196-197):
# FROM signal_ledger sl
# JOIN signal_outcomes so ON sl.signal_id = so.signal_id

# NEW: use signal_ledger view (which includes status from signal_events):
# FROM signal_ledger sl
# (no signal_outcomes JOIN needed — status, exit fields all in signal_ledger view)
```

**`_compute_signal_tier` thresholds** (lines 69-74 — APR migration):
```python
# OLD hard-coded thresholds:
# confidence >= 0.40 (line 72)
# abs(cis_score) > 0.35 (line 73)

# NEW: accept as parameters (loaded from APR by caller):
def _compute_signal_tier(
    was_selected: bool,
    confidence: float | None,
    cis_score: float | None,
    min_confidence: float = 0.40,   # ui.signals.min_confidence
    min_cis_score: float = 0.35,    # ui.signals.min_cis_score
) -> str:
    ...
```

---

### `src/api/routes/narrative.py` (API route, request-response)

**Analog:** `src/api/routes/narrative.py` — targeted SQL updates.

**Column fix** (lines 160-176 — `feature_tf` column dropped):
```python
# OLD:
# tf_sig.value->>'feature_tf' AS feature_tf,   (if present)

# The narrative query at line 170 uses signal_ledger_full — rename to signal_ledger BEFORE I8.
# feature_tf no longer in signal_ledger view — use se.tf instead:
# sl.tf AS feature_tf   (backward compat alias in the query)
```

**Query update** (line 170):
```python
# OLD: FROM signal_ledger_full sl
# NEW: FROM signal_ledger sl     (BEFORE running I8)
```

---

### `production/scripts/run_historical_pipeline.py` (batch script, batch/CRUD)

**Analog:** `production/scripts/run_historical_pipeline.py` — SQL rewrite; psycopg2 pattern preserved.

**Pattern: psycopg2 batch insert** (lines 725-770 — replace `_INSERT_SYNC_SQL` / `_INSERT_SYNC_TEMPLATE`):
```python
# psycopg2 uses %s placeholders (NOT $N), execute_values for multi-row INSERT
# Keep: with conn.cursor() as cur: psycopg2.extras.execute_values(...)
# Keep: conn.commit() after both inserts

_INSERT_SIGNAL_EVENTS_SYNC_SQL = """
INSERT INTO signal_events (
    signal_id, ts, symbol, tf, setup_plugin, direction,
    raw_confidence, calibrated_confidence, cis_score, weights_version,
    factor_scores, context_features,
    ctf_score, ctf_confirmed, zone_friction_score,
    hmm_regime_at_fire, plugin_regime_type, garch_sigma_at_fire,
    is_shadow, is_backfill, status, signal_schema_version,
    ttl_bars, expires_at, signal_computed_at, feature_ts
) VALUES %s
ON CONFLICT (signal_id, ts) DO NOTHING
"""

_INSERT_TRADE_FRAMES_SYNC_SQL = """
INSERT INTO trade_frames (
    frame_id, signal_id, signal_ts, entry_type, direction,
    entry_price, stop_price, target_price, r_multiple,
    ttl_bars, expires_at, counterfactual_pnl_r, was_selected, frame_details
) VALUES %s
ON CONFLICT (frame_id) DO NOTHING
"""
# frame_id: uuid.uuid5(uuid.NAMESPACE_DNS, f"{signal_id}:at_close") for backfill
# direction: "long"/"short" TEXT (convert from integer before building tuple)
# factor_scores, context_features: json.dumps() needed for psycopg2 (NOT asyncpg)
# counterfactual_pnl_r: NULL literal in template
```

**G0 grouping** — same `defaultdict(list)` pattern as signal_writer; wrap in `_build_signal_events_entries()` and `_build_trade_frames_entries()` replacing `_build_ledger_entries()` and `_insert_signals_sync()`.

**`_insert_signals_sync` replacement**:
```python
def _insert_signal_events_sync(conn: Any, event_rows: list[dict], frame_rows: list[dict]) -> None:
    """psycopg2 batch insert into signal_events + trade_frames (3-table schema)."""
    if not event_rows:
        return
    # Build tuples for execute_values
    signal_events_params = [_to_signal_events_tuple(e) for e in event_rows]
    trade_frames_params = [_to_trade_frames_tuple(f) for f in frame_rows]
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur, _INSERT_SIGNAL_EVENTS_SYNC_SQL, signal_events_params,
            template=_SIGNAL_EVENTS_SYNC_TEMPLATE
        )
        psycopg2.extras.execute_values(
            cur, _INSERT_TRADE_FRAMES_SYNC_SQL, trade_frames_params,
            template=_TRADE_FRAMES_SYNC_TEMPLATE
        )
    conn.commit()
```

**JSONB handling** (psycopg2 requires explicit json.dumps — unlike asyncpg):
```python
# In _to_signal_events_tuple():
json.dumps(factor_scores) if factor_scores is not None else None,   # factor_scores
json.dumps(context_features) if context_features is not None else None,  # context_features
# NOT needed for asyncpg services — psycopg2 only
```

---

### `production/scripts/lifecycle_replay.py` (batch script, batch/CRUD)

**Analog:** `production/scripts/lifecycle_replay.py` — SQL UPDATE target changes.

**Status UPDATE** (lines 1028, 1050, 1072 — replace `signal_outcomes` UPDATEs):
```python
# OLD: UPDATE signal_outcomes AS sl SET status = ... WHERE signal_id = ...
# NEW: UPDATE signal_events SET status = $2 WHERE signal_id = $1::uuid

# For exit lifecycle (pnl_r, exit fields) — INSERT to trade_executions instead of UPDATE
```

**Orphan seed** (lines 130-133 — replace `signal_outcomes` seed with no-op check):
```python
# OLD: INSERT INTO signal_outcomes (signal_id, status) SELECT ... FROM signal_ledger
# NEW: signal_events already has status column; orphan concept does not apply.
# Replace with: check signal_events rows missing status='pending' (should not occur)
```

**SELECT JOIN** (lines 359-362, 461-462 — replace `JOIN signal_outcomes`):
```python
# OLD: JOIN signal_outcomes so ON sl.signal_id = so.signal_id
# NEW: Query signal_events directly (status is on signal_events, not a join)
# FROM signal_events sl WHERE sl.status = 'pending' ...
```

---

### `production/scripts/feature_replay.py` (batch script, batch/CRUD)

**Analog:** `production/scripts/feature_replay.py` — full SQL rewrite (NOT in CONTEXT.md D-09 but confirmed write path).

**Imports** (lines 60-62 — replace LedgerEntry import):
```python
# Remove:
# from src.persistence.repository.signal_ledger_repository import LedgerEntry, SignalStatus
# Add:
from src.persistence.repository.signal_events_repository import SignalEventsRepository, SignalStatus
import uuid

_FRAME_ID_NS = uuid.NAMESPACE_DNS
```

**SQL constants** (lines 82-127 — replace `_UPSERT_SIGNAL_SQL` / `_UPSERT_OUTCOMES_SQL`):
```python
# Replace with INSERT ... ON CONFLICT DO NOTHING for signal_events + trade_frames
# Same SQL shape as run_historical_pipeline.py (asyncpg version — uses $N parameters)
# feature_replay.py uses asyncpg (not psycopg2), so no json.dumps() for JSONB
_UPSERT_SIGNAL_EVENTS_SQL = """
INSERT INTO signal_events (...)
ON CONFLICT (signal_id, ts) DO UPDATE SET
    setup_plugin = EXCLUDED.setup_plugin,
    direction = EXCLUDED.direction,
    raw_confidence = EXCLUDED.raw_confidence,
    calibrated_confidence = EXCLUDED.calibrated_confidence
"""
```

---

### `src/config/config_service.py` (config, utility)

**Analog:** `src/config/config_service.py` — one-line addition before APR seeds are written.

**OPS_PREFIXES update** (line 39 — mandatory prerequisite for ui.* and weights.* seeding):
```python
# CURRENT (line 39):
OPS_PREFIXES: ClassVar[tuple[str, ...]] = (
    "regime.", "swarm.", "alert.", "ai.", "feature.",
    "threshold.", "roll.", "cross_asset.", "macro.",
)

# UPDATED:
OPS_PREFIXES: ClassVar[tuple[str, ...]] = (
    "regime.", "swarm.", "alert.", "ai.", "feature.",
    "threshold.", "roll.", "cross_asset.", "macro.",
    "ui.",       # Phase 130: Dashboard preference keys (ui.signals.*)
    "weights.",  # Phase 130: weights.* already in config_state but not settable via ConfigService
)
```

---

### `services/signal_probe_auditor.py` (auditor service, request-response)

**Analog:** `services/signal_probe_auditor.py` — targeted fix for the `LEFT JOIN signal_outcomes` SELECT.

**signal_outcomes JOIN removal** (line 217):
```python
# OLD (lines 216-217):
# FROM signal_ledger_full slf
# LEFT JOIN signal_outcomes so USING (signal_id)

# NEW: signal_outcomes is dropped; replace so.stop_loss with tf.stop_price:
# FROM signal_ledger sl
# (no JOIN needed — stop_loss available as sl.stop_loss via view alias)
# Also: activated_at is NULL in view (Phase 130 only writes to frame_details)
#   → adapt WHERE clause: AND sl.activated_at IS NULL → AND sl.status != 'active'
```

---

## Shared Patterns

### asyncpg Transaction (signal_events + trade_frames atomic write)
**Source:** `src/persistence/repository/signal_ledger_repository.py` lines 447-466 (`insert_signals_with_features`)
**Apply to:** `signal_events_repository.py` (`insert_signal_with_frames`)
```python
async with self._db_manager.pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute(_INSERT_SIGNAL_EVENTS_SQL, *signal_events_params)
        for frame in trade_frames:
            await conn.execute(_INSERT_TRADE_FRAMES_SQL, *_to_trade_frames_params(frame))
```

### asyncpg JSONB — no json.dumps()
**Source:** CLAUDE.md rule; evidenced by `signal_ledger_repository.py` passing dicts directly
**Apply to:** All asyncpg callers (`signal_events_repository.py`, `signal_writer.py`, `feature_replay.py`)
```python
# asyncpg accepts/returns dicts for JSONB — no json.dumps() or json.loads()
factor_scores=sig.get("factor_scores"),   # dict or None — pass directly
```

### psycopg2 JSONB — explicit json.dumps()
**Source:** `production/scripts/run_historical_pipeline.py` lines 916-925
**Apply to:** `run_historical_pipeline.py`, `lifecycle_replay.py` (psycopg2 callers only)
```python
json.dumps(e.targets) if e.targets is not None else None,
json.dumps(e.bucket_scores) if e.bucket_scores is not None else None,
```

### ON CONFLICT idempotency
**Source:** `signal_ledger_repository.py` line 179; migration 137
**Apply to:** All INSERT SQL in Phase 130
```python
# signal_events PK is (signal_id, ts):
ON CONFLICT (signal_id, ts) DO NOTHING

# trade_frames PK is frame_id (uuid):
ON CONFLICT (frame_id) DO NOTHING

# trade_executions PK is execution_id:
ON CONFLICT (execution_id) DO NOTHING
```

### Direction encoding
**Source:** Research.md Pattern 6; migration 137 DDL comment
**Apply to:** `signal_writer.py`, `run_historical_pipeline.py`, `feature_replay.py`
```python
# signal_events.direction and trade_frames.direction are TEXT
direction_text = "long" if int(sig.get("direction", 0)) == 1 else "short"
```

### Deterministic frame_id (uuid5)
**Source:** `production/scripts/migrate_signal_ledger.py` (established in Phase 129)
**Apply to:** All files that insert into trade_frames
```python
import uuid
_FRAME_ID_NS = uuid.NAMESPACE_DNS

def _make_frame_id(signal_id: str, entry_type: str) -> str:
    return str(uuid.uuid5(_FRAME_ID_NS, f"{signal_id}:{entry_type}"))
```

### APR loading in _setup()
**Source:** `services/intelligence_pipeline.py` lines 253, 497-501
**Apply to:** `signal_writer.py`, `lifecycle_writer.py`, `signal_tracker.py`, `signal_auditor.py`
```python
# Pattern from intelligence_pipeline._setup() and _prewarm_threshold_config():
self._config_service = ConfigService(self.settings.database_url, pool=self._db.pool)
await self._config_service.initialize()
self._batch_size = await self._config_service.get(
    "feature.signal_writer.batch_size", default=100
)
# For SQL INTERVAL: parameterized with integer days from APR:
# WHERE ts > NOW() - ($1 * INTERVAL '1 day')   with $1 = int_days_from_apr
```

### structlog event kwarg — never use `event=`
**Source:** CLAUDE.md rule
**Apply to:** All new log calls in Phase 130
```python
# WRONG: logger.info("...", event=payload)
# RIGHT: logger.info("...", signal=payload)  or  data=, payload=, etc.
```

### Exception variable naming
**Source:** CLAUDE.md rule; `swarm_ledger_writer.py` line 114
**Apply to:** All try/except in Phase 130 code
```python
except Exception as error:  # NOT "exc"
    self.logger.warning("...", error=str(error))
```

### Timestamp serialization
**Source:** CLAUDE.md rule + `service_utils.py`
**Apply to:** All places that serialize datetime to string for Kafka or JSON
```python
from src.core.service_utils import format_iso_ts
# Not: dt.isoformat().replace("+00:00", "Z")
```

### Repository batch pattern (execute_batch)
**Source:** `signal_ledger_repository.py` lines 430-431, 857
**Apply to:** `signal_events_repository.py` batch_execute method
```python
await self._db_manager.execute_batch(sql, params)
```

---

## No Analog Found

No files in Phase 130 have zero analog — every file is a rewrite of an existing file. The patterns for the new 3-table SQL shapes come from `production/migrations/137_3table_schema.sql` (authoritative DDL) and `production/scripts/migrate_signal_ledger.py` (frame_id generation).

---

## Critical Sequencing Notes (for planner)

1. **OPS_PREFIXES one-liner** must land BEFORE APR migration 142 (seeds `ui.*` and `weights.*` keys).
2. **`signal_events_repository.py`** (class rename + SQL rewrite) must land before any service rewrite — all services import from it.
3. **All `signal_ledger_full` references updated to `signal_ledger`** before running migration 143 (I8 view rename). Code that still says `signal_ledger_full` will break post-I8.
4. **Migration 142** (APR seeds for `feature.*` and `ui.*` keys) runs before services are deployed with APR loads.
5. **Migration 143** (DROP signal_outcomes; DROP signal_ledger CASCADE; ALTER VIEW RENAME) runs after 48-hour verification only.
6. **Doc updates** (D-15) run after migration 143.
7. `signal_probe_auditor.py` is listed as "read-only auto-fixed by view rename" in RESEARCH.md but has a `LEFT JOIN signal_outcomes` SELECT that will break — must be in the explicit rewrite list.

---

## Metadata

**Analog search scope:** `services/`, `src/persistence/repository/`, `src/api/routes/`, `production/scripts/`, `production/migrations/`, `src/config/`
**Files scanned:** 13 source files + migration 137
**Pattern extraction date:** 2026-06-16
