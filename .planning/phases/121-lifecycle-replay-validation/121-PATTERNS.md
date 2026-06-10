# Phase 121: Lifecycle Replay & Validation - Pattern Map

**Mapped:** 2026-06-10
**Files analyzed:** 4 new/modified files
**Analogs found:** 4 / 4

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `production/scripts/lifecycle_replay.py` (modify) | batch-script | CRUD + batch | self (v1.2) | exact |
| `production/scripts/historical_backfill.py` (modify) | batch-script | batch + transform | self (v1.4) | exact |
| `production/scripts/phase_121_before_snapshot.py` (create) | utility | CRUD + file-I/O | `production/scripts/compute_ic.py` | role-match |
| `production/scripts/phase_121_report.py` (create) | utility | CRUD + file-I/O | `production/scripts/compute_ic.py` | role-match |

---

## Pattern Assignments

### `production/scripts/lifecycle_replay.py` (modify, batch, CRUD)

**Analog:** self — targeted edits to existing v1.2 file. All patterns below are extracted from the current file.

**Imports pattern** (lines 44-66):
```python
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from src.config.settings import Settings, get_active_contracts
from src.core.database_manager import DatabaseManager
from src.core.service_utils import TF_SECONDS, TF_TTL_BARS
from src.intelligence.trading.lifecycle_tracker import (
    _classify_stop_outcome,
    evaluate_market_entry,
    evaluate_signal,
)
from src.observability.metrics import flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers
```

**Advisory lock pattern** (lines 77-80, 275-338, 1173-1206):
```python
_REPLAY_LOCK_ID = 20260602  # MUST NOT change — changing allows concurrent replays with old ID

async def _acquire_replay_lock(conn) -> bool:
    row = await conn.fetchrow("SELECT pg_try_advisory_lock($1) as acquired", _REPLAY_LOCK_ID)
    return row["acquired"]

# Release in finally block — session-scoped lock, must release before connection returns to pool
finally:
    await preflight_conn.execute("SELECT pg_advisory_unlock($1)", _REPLAY_LOCK_ID)
```

**`_seed_orphan_outcomes` — current (hardcoded, D-02 target)** (lines 105-131):
```python
# CURRENT — hardcoded dates to REMOVE per D-02:
async def _seed_orphan_outcomes(
    conn, symbols: list[str], timeframes: list[str], cutoff: datetime
) -> int:
    result = await conn.execute(
        """INSERT INTO signal_outcomes (signal_id, status)
           SELECT sl.signal_id, 'pending'
           FROM signal_ledger sl
           LEFT JOIN signal_outcomes so ON sl.signal_id = so.signal_id
           WHERE so.signal_id IS NULL
             AND sl.timestamp >= '2026-05-21'   -- REMOVE: hardcoded lower bound
             AND sl.timestamp < $1              -- REMOVE: hardcoded upper cutoff
             AND sl.symbol = ANY($2)
             AND sl.timeframe = ANY($3)
           ON CONFLICT (signal_id) DO NOTHING""",
        cutoff, symbols, timeframes,
    )
    return int(result.split()[-1])

# REPLACEMENT (from RESEARCH.md verified pattern):
async def _seed_orphan_outcomes(conn, symbols: list[str], timeframes: list[str]) -> int:
    """Seed ALL missing signal_outcomes rows — no date window."""
    result = await conn.execute(
        """INSERT INTO signal_outcomes (signal_id, status)
           SELECT sl.signal_id, 'pending'
           FROM signal_ledger sl
           LEFT JOIN signal_outcomes so ON sl.signal_id = so.signal_id
           WHERE so.signal_id IS NULL
             AND sl.symbol = ANY($1)
             AND sl.timeframe = ANY($2)
           ON CONFLICT (signal_id) DO NOTHING""",
        symbols, timeframes,
    )
    return int(result.split()[-1])
```

**SELECT query — columns to add (lines 396-420 context):**
```python
# Current SELECT is missing these columns. Add to the existing SELECT in _process_symbol_tf:

# Add from signal_ledger (migration 119):
#   sl.stop_basis, sl.stop_type_col, sl.structural_stop_distance_atr,
#   sl.adaptive_buffer_mult, sl.plugin_regime_type

# Add from signal_outcomes (migrations 112/119):
#   so.trailing_stop_price,       -- jsonb; asyncpg returns as dict, NO json.loads()
#   so.staleness_score,
#   so.staleness_trigger_reason,
#   so.chandelier_vol_source,
#   so.shadow_tracking_start_ts,
#   so.shadow_mae,
#   so.shadow_mfe,
#   so.shadow_outcome,
#   so.effective_ts
```

**`_verify_replay` — current (excludes shadow, D-06 target)** (lines 1046-1109):
```python
# CURRENT — is_shadow = false filter on line 1074 MUST be updated for D-06:
WHERE sl.symbol = ANY($1)
  AND sl.timeframe = ANY($2)
  AND sl.is_shadow = false    -- REMOVE/modify: excludes shadow signals from all checks

# D-06 EXTENSIONS to add (raise RuntimeError on violation):
# shadow_stopped_at_entry check:
COUNT(CASE WHEN so.outcome = 'stopped_at_entry'
           AND sl.is_shadow = true
           AND sl.setup_plugin = ANY($3)   -- 22 shadow setups from _SHADOW_VALIDATION_SETUPS
      THEN 1 END) as shadow_stopped_at_entry,

# orphan_ledger_rows check (Phase 104 invariant):
COUNT(CASE WHEN sl.signal_id IS NOT NULL
           AND so.signal_id IS NULL
      THEN 1 END) as orphan_ledger_rows

# Hard-fail triggers (extend existing issues list):
if row["shadow_stopped_at_entry"] > 0:
    issues.append(f"{row['shadow_stopped_at_entry']} shadow signals have stopped_at_entry outcome")
if row["orphan_ledger_rows"] > 0:
    issues.append(f"{row['orphan_ledger_rows']} signal_ledger rows without signal_outcomes row")
```

**Hardcoded date constraints to remove** (lines 1141-1151, 1199):
```python
# REMOVE these hardcoded defaults — replace with None:
parser.add_argument(
    "--reset-before",
    type=str,
    default="2026-06-02T00:00:00Z",   # → default=None
    ...
)
parser.add_argument(
    "--reset-after",
    type=str,
    default="2026-05-21T00:00:00Z",   # → default=None
    ...
)

# REMOVE this hardcoded cutoff at line 1199:
cutoff = datetime(2026, 6, 2, 0, 0, 0, tzinfo=UTC)   # → remove
orphans = await _seed_orphan_outcomes(preflight_conn, symbols, timeframes, cutoff)
# → becomes:
orphans = await _seed_orphan_outcomes(preflight_conn, symbols, timeframes)
```

**TimescaleDB DML session setting** (line 485):
```python
# Must be set per connection before any DML on compressed chunks:
await conn.execute("SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0")
```

**Oneshot exit pattern** (lines 1279-1289):
```python
def main():
    asyncio.run(main_async())
    flush_and_shutdown_metrics()

if __name__ == "__main__":
    try:
        init_otel_providers("lifecycle-replay")
    except OTelInitError as error:
        print(f"[warn] OTel init failed — metrics disabled: {error}")
```

**`_flush_writes` chunk sizes** (lines 947-949) — DO NOT change:
```python
ZONE_CHUNK = 1500       # 14 params/row — preserves PostgreSQL 32767 param limit
MARKET_CHUNK = 2000     # 11 params/row
ACTIVATION_CHUNK = 4000 # 6 params/row
```

---

### `production/scripts/historical_backfill.py` (modify, batch, transform)

**Analog:** self — targeted edit to the `--clean` path. All patterns below are from the current file.

**Current `--clean` delete path (lines 2066-2116) — the section to modify:**
```python
# CURRENT: deletes by symbol only — wipes ALL 30 setups including GOOD control group
if args.clean:
    symbol_values = [c.symbol for c in contracts]
    cur.execute(
        "DELETE FROM intelligence_features WHERE symbol = ANY(%s)",
        (symbol_values,),
    )
    cur.execute(
        """DELETE FROM signal_outcomes
           WHERE signal_id IN (
               SELECT signal_id FROM signal_ledger WHERE symbol = ANY(%s)
           );""",
        (symbol_values,),
    )
    cur.execute(
        "DELETE FROM signal_ledger WHERE symbol = ANY(%s);",
        (symbol_values,),
    )
```

**Plugin-scoped delete pattern (RESEARCH.md verified):**
```python
# REPLACEMENT when --setups flag is present (psycopg2, not asyncpg):
setup_values = list(shadow_22_setups)  # from _SHADOW_VALIDATION_SETUPS

# Delete outcomes first (no FK cascade), then ledger — scoped to setup_plugin
cur.execute(
    """DELETE FROM signal_outcomes
       WHERE signal_id IN (
           SELECT signal_id FROM signal_ledger
           WHERE symbol = ANY(%s) AND setup_plugin = ANY(%s)
       )""",
    (symbol_values, setup_values),
)
cur.execute(
    """DELETE FROM signal_ledger
       WHERE symbol = ANY(%s) AND setup_plugin = ANY(%s)""",
    (symbol_values, setup_values),
)
# CRITICAL: Do NOT delete intelligence_features when --setups is provided.
# intelligence_features has no setup_plugin column; per-bar feature vectors
# are shared across all setups. Bars must remain for replay to re-evaluate.
```

**Argparse addition pattern** (psycopg2 script uses standard argparse, see lines 1757+):
```python
parser.add_argument(
    "--setups",
    type=str,
    default=None,
    help=(
        "Comma-separated setup_plugin names to scope --clean deletion. "
        "When provided, only deletes signal_ledger rows for these setups "
        "(intelligence_features is NOT deleted). "
        "Default: None (full-symbol clean)."
    ),
)
```

---

### `production/scripts/phase_121_before_snapshot.py` (create, utility, CRUD + file-I/O)

**Analog:** `production/scripts/compute_ic.py` (asyncpg oneshot reporting script with DB query, stdout + file output)

**Imports pattern** (from compute_ic.py lines 24-43, adapted):
```python
#!/usr/bin/env python3
"""phase_121_before_snapshot — capture per-setup signal metrics before any deletes.

Writes docs/plans/phase-121-before-snapshot.json as the authoritative "before"
baseline for Wave 2 comparison report. Run ONCE before executing the D-01 clean+replay.
Idempotent if run before any deletes — will not overwrite an existing snapshot file.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

import asyncpg

from src.config.settings import Settings
from src.core.database_manager import DatabaseManager
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers
```

**DB connection pattern** (from compute_ic.py lines 261-282):
```python
async def _amain() -> int:
    settings = Settings()
    db = DatabaseManager(settings.database_url)
    await db.initialize()
    try:
        async with db.get_connection() as conn:
            rows = await _fetch_snapshot(conn)
        # ... process and write
    finally:
        await db.close()
    return 0
```

**Before-snapshot query** (from CONTEXT.md D-04 — exact SQL):
```python
async def _fetch_snapshot(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        """SELECT
               sl.setup_plugin,
               sl.is_shadow,
               COUNT(*) as total_signals,
               COUNT(CASE WHEN sl.was_selected THEN 1 END) as selected,
               COUNT(CASE WHEN sl.was_selected THEN 1 END)::float
                   / NULLIF(COUNT(*), 0) as selection_rate,
               AVG(CASE WHEN so.pnl_r IS NOT NULL THEN so.pnl_r END) as avg_pnl_r,
               CORR(sl.cis_score, (so.pnl_r > 0)::int)
                   FILTER (WHERE so.pnl_r IS NOT NULL) as calibration_corr
           FROM signal_ledger sl
           LEFT JOIN signal_outcomes so ON sl.signal_id = so.signal_id
           GROUP BY sl.setup_plugin, sl.is_shadow
           ORDER BY total_signals DESC"""
    )
```

**JSON file output pattern** (adapt from compute_ic.py, add file write):
```python
_SNAPSHOT_PATH = _PROJECT_ROOT / "docs" / "plans" / "phase-121-before-snapshot.json"

def _write_snapshot(rows: list[asyncpg.Record]) -> None:
    if _SNAPSHOT_PATH.exists():
        print(f"ABORT: snapshot already exists at {_SNAPSHOT_PATH}. Delete it first.")
        raise SystemExit(1)
    snapshot = {
        "captured_at": datetime.now(UTC).isoformat(),
        "setups": [
            {
                "setup_plugin": row["setup_plugin"],
                "is_shadow": row["is_shadow"],
                "total_signals": row["total_signals"],
                "selected": row["selected"],
                "selection_rate": row["selection_rate"],
                "avg_pnl_r": row["avg_pnl_r"],
                "calibration_corr": row["calibration_corr"],
            }
            for row in rows
        ],
    }
    _SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2, default=str))
    print(f"Snapshot written to {_SNAPSHOT_PATH} ({len(rows)} setups)")
```

**Oneshot exit pattern** (from roll_batch.py lines 460-465, 472-481):
```python
JOB_COMPLETED_TOTAL.add(1, {"job": "phase-121-before-snapshot", "status": "success"})

def main() -> None:
    try:
        init_otel_providers("phase-121-before-snapshot")
    except OTelInitError as error:
        print(f"[warn] OTel init failed: {error}")
    try:
        asyncio.run(_amain())
    finally:
        flush_and_shutdown_metrics()

if __name__ == "__main__":
    main()
```

---

### `production/scripts/phase_121_report.py` (create, utility, CRUD + file-I/O)

**Analog:** `production/scripts/compute_ic.py` (asyncpg oneshot analysis script with multi-step query, table output, and file write)

**Imports pattern** (from compute_ic.py, adapted):
```python
#!/usr/bin/env python3
"""phase_121_report — before/after comparison report for Phase 121 replay.

Reads docs/plans/phase-121-before-snapshot.json as "before" baseline.
Runs identical metrics post-replay. Writes docs/plans/phase-121-validation-report.md.

Prerequisites:
  - phase_121_before_snapshot.py must have run (before-snapshot JSON must exist)
  - lifecycle_replay.py must have completed (no pending signals older than 2 days)
  - _verify_replay() must have passed (hard gate — this script checks it internally)
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

import asyncpg

from src.config.settings import Settings
from src.core.database_manager import DatabaseManager
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers
```

**DB pattern** (same as before_snapshot — asyncpg via DatabaseManager):
```python
async def _amain() -> int:
    settings = Settings()
    db = DatabaseManager(settings.database_url)
    await db.initialize()
    try:
        async with db.get_connection() as conn:
            after_rows = await _fetch_post_replay_metrics(conn)
            stopped_at_entry_rows = await _fetch_stopped_at_entry(conn)
    finally:
        await db.close()
    return 0
```

**Post-replay metrics query** (same shape as before-snapshot query, adds stopped_at_entry):
```python
async def _fetch_post_replay_metrics(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        """SELECT
               sl.setup_plugin,
               sl.is_shadow,
               COUNT(*) as total_signals,
               COUNT(CASE WHEN sl.was_selected THEN 1 END) as selected,
               COUNT(CASE WHEN sl.was_selected THEN 1 END)::float
                   / NULLIF(COUNT(*), 0) as selection_rate,
               AVG(CASE WHEN so.pnl_r IS NOT NULL THEN so.pnl_r END) as avg_pnl_r,
               CORR(sl.cis_score, (so.pnl_r > 0)::int)
                   FILTER (WHERE so.pnl_r IS NOT NULL) as calibration_corr
           FROM signal_ledger sl
           LEFT JOIN signal_outcomes so ON sl.signal_id = so.signal_id
           GROUP BY sl.setup_plugin, sl.is_shadow
           ORDER BY total_signals DESC"""
    )

async def _fetch_stopped_at_entry(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    """Per D-05: stopped_at_entry must be 0 for all regenerated shadow signals."""
    return await conn.fetch(
        """SELECT sl.setup_plugin, COUNT(*) as count
           FROM signal_ledger sl
           JOIN signal_outcomes so ON sl.signal_id = so.signal_id
           WHERE so.outcome = 'stopped_at_entry'
             AND sl.is_shadow = true
           GROUP BY sl.setup_plugin"""
    )
```

**Report table rendering pattern** (from compute_ic.py lines 212-243 — build header + rows):
```python
# Per D-05: per-setup table with verdict column
REPORT_COLUMNS = (
    "setup_plugin | cluster | signals_before | signals_after | delta_pct | "
    "snr_before | snr_after | calibration_corr | stopped_at_entry | verdict"
)

def _render_markdown_table(report_rows: list[dict]) -> str:
    lines = [
        "| setup_plugin | cluster | signals_before | signals_after | delta_pct |"
        " snr_before | snr_after | calibration_corr | stopped_at_entry | verdict |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in report_rows:
        lines.append(
            f"| {row['setup_plugin']} | {row['cluster']} "
            f"| {row['signals_before']:,} | {row['signals_after']:,} "
            f"| {row['delta_pct']:.1f}% | {row['snr_before']:.2%} "
            f"| {row['snr_after']:.2%} | {row['calibration_corr'] or 'n/a'} "
            f"| {row['stopped_at_entry']} | {row['verdict']} |"
        )
    return "\n".join(lines)
```

**Markdown file write pattern:**
```python
_REPORT_PATH = _PROJECT_ROOT / "docs" / "plans" / "phase-121-validation-report.md"

def _write_report(content: str) -> None:
    _REPORT_PATH.write_text(content)
    print(f"Report written to {_REPORT_PATH}")
```

**Oneshot exit pattern** (same as before_snapshot, different job label):
```python
JOB_COMPLETED_TOTAL.add(1, {"job": "phase-121-report", "status": "success"})
# job label MUST match systemd unit %n suffix exactly (kebab-case) per CLAUDE.md D-06
```

---

## Shared Patterns

### AsyncPG connection — DatabaseManager
**Source:** `production/scripts/lifecycle_replay.py` lines 1162-1164, 1173, 1275-1276
**Apply to:** All 4 files (lifecycle_replay.py already uses it; new scripts adopt same pattern)
```python
settings = Settings()
db = DatabaseManager(settings.database_url)
await db.initialize()
try:
    async with db.pool.acquire() as conn:
        ...
finally:
    await db.close()
```

### Oneshot OTel + metrics exit
**Source:** `production/scripts/lifecycle_replay.py` lines 1279-1289; `roll_batch.py` lines 460-481
**Apply to:** `phase_121_before_snapshot.py`, `phase_121_report.py`
```python
from src.observability.metrics import JOB_COMPLETED_TOTAL, flush_and_shutdown_metrics
from src.observability.otel import OTelInitError, init_otel_providers

# Success path:
JOB_COMPLETED_TOTAL.add(1, {"job": "<kebab-job-name>", "status": "success"})
# Failure path:
JOB_COMPLETED_TOTAL.add(1, {"job": "<kebab-job-name>", "status": "failure"})

def main() -> None:
    try:
        init_otel_providers("<kebab-job-name>")
    except OTelInitError as error:
        print(f"[warn] OTel init failed: {error}")
    try:
        asyncio.run(_amain())
    finally:
        flush_and_shutdown_metrics()
```

### TimescaleDB DML session setting
**Source:** `production/scripts/lifecycle_replay.py` line 485
**Apply to:** Any connection that issues UPDATE/DELETE on signal_ledger or signal_outcomes
```python
await conn.execute("SET timescaledb.max_tuples_decompressed_per_dml_transaction = 0")
```

### asyncpg JSONB handling
**Source:** CLAUDE.md core rule
**Apply to:** `lifecycle_replay.py` SELECT for `trailing_stop_price` (jsonb column)
```python
# asyncpg returns JSONB as dict automatically — no json.loads() or json.dumps()
# trailing_stop_price: asyncpg returns dict | None directly from asyncpg Record
trailing_stop_price = signal_row["trailing_stop_price"]  # already dict or None
```

### sys.path bootstrap pattern
**Source:** `production/scripts/lifecycle_replay.py` line 53; `compute_ic.py` lines 31-32
**Apply to:** `phase_121_before_snapshot.py`, `phase_121_report.py`
```python
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))
```

### psycopg2 (historical_backfill.py only — do NOT mix drivers)
**Source:** CLAUDE.md, RESEARCH.md
**Apply to:** `historical_backfill.py` `--clean` path only
```python
# historical_backfill.py uses psycopg2, lifecycle_replay.py uses asyncpg.
# The --setups filter in the clean path must use cur.execute() with %s placeholders (psycopg2),
# NOT $1 placeholders (asyncpg).
cur.execute("DELETE FROM signal_ledger WHERE symbol = ANY(%s) AND setup_plugin = ANY(%s)",
            (symbol_values, setup_values))
```

---

## No Analog Found

All 4 files have close analogs in the codebase. No files lack a pattern reference.

---

## Metadata

**Analog search scope:** `production/scripts/`
**Files scanned:** lifecycle_replay.py (1289 lines), historical_backfill.py (--clean path ~2066-2116), compute_ic.py (300 lines), roll_batch.py (486 lines)
**Pattern extraction date:** 2026-06-10
