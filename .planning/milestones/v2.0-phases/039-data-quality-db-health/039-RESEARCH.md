# Phase 39: Data Quality + DB Health - Research

**Researched:** 2026-03-19
**Domain:** TimescaleDB hypertable management, Python service scaffolding, enum migration, DB index tuning
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Philosophy**
- Every fix must be institutional grade — not just "works," but hardened, observable, self-healing, and exhaustively verified.
- Renaissance north star: instrument everything, let the system run, earn the right through proof.
- All changes must be idempotent (safe to run twice), observable (Prometheus metrics + structured logs), and self-validating (exit non-zero if goals not met).

**market_data_ohlcv Rebuild (DATA-03)**
- Strategy: Create `market_data_ohlcv_v2` with correct chunk interval, backfill from old table, then atomic `ALTER TABLE RENAME` swap. Production continues reading the old table during rebuild.
- Chunk interval: 7-day chunks.
- Verification gate before swap: automated check confirms `chunk_count < 200` AND benchmark aggregate query completes `< 500ms`. Gate must pass before rename executes — script exits 1 if it fails.
- Script is restartable: if interrupted, restarting resumes via `INSERT ... ON CONFLICT DO NOTHING`.
- Services stay live: only ~1 minute downtime for the rename.

**signal_ledger Composite Index (DATA-04)**
- Composite index on `(symbol, timeframe, status, computed_at DESC)`.
- Create `CONCURRENTLY` to avoid locking during creation.
- Verify with `EXPLAIN ANALYZE` on representative lifecycle UPDATE — confirm index scan, latency < 5ms.

**CIS Null Repair (DATA-01)**
- `repair_cis_nulls.py` already exists. Strategy: chunked batches of 500 rows.
- Services stay live — script is idempotent.
- Progress tracking: print before-count, per-chunk progress, after-count.
- Completeness gate: after repair, verify `recoverable_null_count == 0`, exit 1 otherwise.

**Gap-Fill Service (DATA-05)**
- New systemd service `indicagent-gap-fill` — not a cron script.
- Schedule: runs daily at 09:20 ET (10 minutes before RTH opens).
- Gap detection: queries `market_data_ohlcv` for expected vs actual 1m bar timestamps per symbol per RTH window (09:30–16:00 ET).
- Fetch: calls IBKR for only missing windows. `ON CONFLICT DO NOTHING`.
- Prometheus metrics: `gap_fill_gaps_detected_total{symbol}`, `gap_fill_bars_fetched_total{symbol}`, `gap_fill_fetch_failed_total{symbol}`.
- Alert threshold: `gaps_detected > 30` for any symbol → log at `CRITICAL`.
- Metrics port: `:9119`.
- Logging: via `setup_service_logging()` → `logs/gap-fill.log`.

**SignalStatus Enum (DATA-06)**
- Location: `src/intelligence/trading/signal_ledger.py`, co-located with `LedgerEntry`.
- Values (string-compatible, no DB migration):
  ```python
  class SignalStatus(str, Enum):
      PENDING = "pending"
      ACTIVE = "active"
      REGIME_SUPPRESSED = "regime_suppressed"
      TARGET_HIT = "target_hit"
      STOP_HIT = "stop_hit"
      EXPIRED = "expired"
      CONDITION_EXPIRED = "condition_expired"
  ```
- Exhaustiveness gate: `typing.assert_never()` in else branches of all if/elif chains.
- Migration scope: 6 files — `signal_ledger.py`, `lifecycle_tracker.py`, `signal_generator_service.py`, `signal_lifecycle_service.py`, `src/api/routes/signals.py` (×2 occurrences).
- DB values unchanged — no migration script needed.

**Alpha Validation Re-run (DATA-02)**
- `validate_alpha.py --promote` for `cmp_DerivativeOscillator` and `ind_ACOscillator`.
- Gate: N >= 30 resolved signals required before promotion.
- Script already exists — this is an operational task, not new code.
- Add a check at start of plan execution: if N < 30, document exact query to recheck and defer until data accumulates.

**Renaissance-Grade Hardening Additions (all approved)**
1. Health-check gate on ohlcv rebuild (chunk count + query latency verified before swap).
2. CIS repair completeness gate (exit 1 on non-zero recoverable nulls).
3. Gap-fill Prometheus metrics + CRITICAL alert on systemic failures.
4. SignalStatus exhaustiveness checking via `assert_never()` in all status dispatch chains.

### Claude's Discretion
- Exact batch insert strategy for ohlcv rebuild (COPY vs INSERT ... SELECT batches).
- Implementation of RTH window generation for gap detection (timezone handling for ET).
- Whether gap-fill service also covers non-1m timeframes (requirement only specifies 1m).
- Ordering of execution steps within each plan.

### Deferred Ideas (OUT OF SCOPE)
- Gap-fill for non-1m timeframes (5m, 15m, 1h).
- Automated CIS repair on startup.
- ohlcv retention policy (compression + tiered storage for data > 1 year).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| DATA-01 | CIS null fields repaired in `signal_ledger` for all historical rows recoverable from `intelligence_features` | `repair_cis_nulls.py` is complete; needs 500-row batch execution and exit-1 completeness gate added |
| DATA-02 | `validate_alpha.py --promote` re-run for DerivOsc and AC Osc once N >= 30 accumulated | Script is fully operational; task is gated on data accumulation; pre-check query identified |
| DATA-03 | `market_data_ohlcv` rebuilt — chunk count < 200, aggregate queries < 500ms | Create-backfill-verify-rename pattern is well-understood in TimescaleDB; `docker cp` migration path established |
| DATA-04 | Composite index on `signal_ledger` for lifecycle UPDATEs — latency < 5ms | `CREATE INDEX CONCURRENTLY` on hypertable parent works; existing `039_performance_and_schema_fixes.sql` pattern shows exact syntax |
| DATA-05 | Gap-fill service detects and fetches missing 1m RTH bars from IBKR | New systemd service follows `cross_asset_service.py` scaffold; `zoneinfo` for ET timezone; IBKR fetch via `historical_backfill.py` patterns |
| DATA-06 | `SignalStatus` enum replaces raw string literals across 5 files | All 6 usage sites identified; `str` enum subclass approach is drop-in; `assert_never()` requires Python 3.11+ or `typing_extensions` |
</phase_requirements>

---

## Summary

Phase 39 is pure infrastructure surgery — no new features. All six requirements are well-bounded with existing scaffolding, scripts, and patterns that are already proven in this codebase. The highest-risk item is the `market_data_ohlcv` rebuild because it involves downtime (even if minimal) and a large data copy; the atomic rename pattern de-risks this completely.

**DATA-01 (CIS null repair)** has a complete script (`repair_cis_nulls.py`) that needs only two additions: enforce the 500-row batch limit (already in the script's `repair_recoverable()` function via `batch_size` parameter — the script already supports this) and add an exit-1 completeness gate after the verification phase. The script currently prints a warning but does not exit non-zero on failure — that gap is the only code change.

**DATA-03 (ohlcv rebuild)** is the most operationally complex task but is conceptually straightforward: create a new hypertable, copy data in batches using `INSERT INTO v2 SELECT ... ON CONFLICT DO NOTHING`, run the verification gate (chunk count < 200 AND query benchmark < 500ms), then `ALTER TABLE RENAME`. The `docker cp` + `psql -f` migration delivery pattern is established. The copy can run while production reads the old table.

**DATA-05 (gap-fill service)** is the only net-new code module. The service pattern is fully established: `cross_asset_service.py` is the canonical template. The novel pieces are ET timezone RTH window generation (using `zoneinfo.ZoneInfo("America/New_York")`) and the IBKR fetch call (reusing `historical_backfill.py`'s fetch logic).

**DATA-06 (SignalStatus enum)** is a mechanical refactor: 6 files, 14 usage sites identified via grep. The `str` enum subclass means no consumer breaks — `.value` returns the same strings already in the DB.

**Primary recommendation:** Execute in dependency order — DATA-04 (index, fastest win, independent), DATA-06 (enum, zero-risk refactor), DATA-01 (CIS repair, idempotent, run while live), DATA-03 (ohlcv rebuild, scheduled downtime window), DATA-05 (new service), DATA-02 (operational gate, conditional on N >= 30).

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| psycopg2 | 2.9.x | Synchronous DB access in repair/rebuild scripts | Already used in `repair_cis_nulls.py`, `validate_alpha.py`, `historical_backfill.py` |
| asyncpg | 0.29.x | Async DB access in the gap-fill service | All services use this via `DatabaseManager` |
| prometheus_client | 0.20.x | Metrics for gap-fill service | All services use; module-level labeled `Counter` pattern |
| structlog | 23.x | Structured logging | `setup_service_logging()` wraps this for all services |
| zoneinfo | stdlib (3.9+) | ET timezone for RTH window generation | Already used in `CVDPlugin` (`zoneinfo.ZoneInfo("America/New_York")`) |
| aiokafka | 0.11.x | Kafka consumer in gap-fill service (if subscribing to events) | Already used across all services |
| typing | stdlib | `assert_never()` for exhaustiveness (Python 3.11+) | Or `typing_extensions` if < 3.11 |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| ib_insync (via providers/ibkr.py) | — | IBKR bar fetch for gap-fill | All IBKR access goes through `src/providers/ibkr.py` only — never import directly |
| psycopg2.extras | — | `execute_batch` for batch UPDATE in repair script | Already in repair_cis_nulls.py |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `INSERT ... ON CONFLICT DO NOTHING` for ohlcv backfill | COPY + dedup | ON CONFLICT is simpler and restartable; COPY is faster for cold tables but no conflict handling |
| Batched INSERT SELECT for ohlcv copy | pg_dump/restore | pg_dump does NOT work for TimescaleDB hypertables — explicitly prohibited by CLAUDE.md |
| `str` Enum for SignalStatus | plain Enum | `str` subclass is drop-in — no `.value` unwrapping needed at comparison sites |

**Installation:** No new packages required — all libraries already in the virtualenv.

---

## Architecture Patterns

### Recommended Project Structure for Phase 39

```
production/
├── scripts/
│   ├── repair_cis_nulls.py       # DATA-01: modify — add exit-1 gate
│   ├── rebuild_ohlcv.py          # DATA-03: new script
│   └── validate_alpha.py         # DATA-02: operational task (no code change)
├── migrations/
│   └── 040_signal_ledger_index.sql  # DATA-04: CONCURRENTLY index
services/
└── gap_fill_service.py           # DATA-05: new service
production/systemd/
└── indicagent-gap-fill.service   # DATA-05: systemd unit
src/intelligence/trading/
└── signal_ledger.py              # DATA-06: add SignalStatus enum
```

### Pattern 1: TimescaleDB Atomic Table Swap

**What:** Create v2 hypertable, backfill from v1, verify, then rename.
**When to use:** Rebuilding a hypertable with different chunk interval without service downtime.

```sql
-- Source: CLAUDE.md §TimescaleDB Gotchas + TimescaleDB docs
-- Step 1: Create v2 hypertable with correct chunk interval
CREATE TABLE market_data_ohlcv_v2 (LIKE market_data_ohlcv INCLUDING ALL);
-- Remove inherited primary key to allow SELECT_INTO_TARGET pattern
ALTER TABLE market_data_ohlcv_v2 DROP CONSTRAINT IF EXISTS market_data_ohlcv_v2_pkey;

SELECT create_hypertable(
    'market_data_ohlcv_v2',
    'timestamp',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists => TRUE
);

-- Step 2: Backfill in batches (Python loop, ON CONFLICT DO NOTHING for restartability)
-- INSERT INTO market_data_ohlcv_v2 SELECT ... ON CONFLICT DO NOTHING

-- Step 3: Verification gate (Python checks this before proceeding)
SELECT count(*) FROM timescaledb_information.chunks
WHERE hypertable_name = 'market_data_ohlcv_v2';
-- Must be < 200

-- Step 4: Atomic rename (requires ~1 minute service downtime)
ALTER TABLE market_data_ohlcv RENAME TO market_data_ohlcv_old;
ALTER TABLE market_data_ohlcv_v2 RENAME TO market_data_ohlcv;
```

**Key constraint:** `pg_dump` cannot be used for hypertables. Volume-level copy is the only safe backup method. The rename swap IS safe because it's in-place within the same schema — no data movement.

**Delivery pattern for SQL migrations:**
```bash
# Always via docker cp — heredoc to /dev/stdin does NOT work
docker cp rebuild.sql timescaledb:/tmp/rebuild.sql
docker exec timescaledb psql -U postgres -d indicagent -f /tmp/rebuild.sql
```

### Pattern 2: CONCURRENTLY Index on Hypertable

**What:** Add composite index without locking the table.
**When to use:** Adding indexes to live, high-write hypertables.

```sql
-- Source: CLAUDE.md §TimescaleDB Gotchas — "CREATE INDEX CONCURRENTLY"
-- signal_ledger is a hypertable; CONCURRENTLY prevents lock
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_signal_ledger_lifecycle
    ON signal_ledger (symbol, timeframe, status, computed_at DESC);
```

**Gotcha:** `CREATE INDEX` (without CONCURRENTLY) on hypertables is supported but locks the table. Use CONCURRENTLY for live tables. However, `CREATE INDEX ... CONCURRENTLY` cannot be run inside a transaction block — run as a standalone statement.

### Pattern 3: systemd Service (Gap-Fill)

**What:** New `indicagent-gap-fill.service` following the canonical cross-asset pattern.
**When to use:** New long-running services.

```ini
# Source: production/systemd/indicagent-cross-asset.service pattern
[Unit]
Description=IndicAgent Gap-Fill Service
After=network-online.target
StartLimitIntervalSec=300
StartLimitBurst=5

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent
Environment=PYTHONPATH=/home/bg/dev/indicagent
Environment=PYTHONUNBUFFERED=1          # MANDATORY — without this journald sees nothing
ExecStart=/home/bg/dev/indicagent/.venv/bin/python services/gap_fill_service.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=indicagent-gap-fill
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

### Pattern 4: Gap-Fill RTH Window Generation

**What:** Generate expected 1-minute bar timestamps for RTH (09:30–16:00 ET).
**When to use:** Detecting missing bars in market_data_ohlcv.

```python
# Source: CVDPlugin session reset pattern (src/intelligence/indicators/cvd.py)
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
RTH_OPEN_ET = (9, 30)   # hour, minute
RTH_CLOSE_ET = (16, 0)  # exclusive

def generate_rth_timestamps(date_et: date) -> list[datetime]:
    """Generate all expected 1m bar timestamps for one RTH session."""
    open_et = datetime(date_et.year, date_et.month, date_et.day,
                       *RTH_OPEN_ET, tzinfo=ET)
    close_et = datetime(date_et.year, date_et.month, date_et.day,
                        *RTH_CLOSE_ET, tzinfo=ET)
    ts = open_et
    result = []
    while ts < close_et:
        result.append(ts.astimezone(UTC))  # Store as UTC — all DB timestamps are UTC
        ts += timedelta(minutes=1)
    return result  # 390 bars per session
```

**Gotcha:** Always compare/store timestamps in UTC. The `ZoneInfo("America/New_York")` handles DST transitions correctly — `pytz` is not needed.

**Trading day detection:** Skip weekends and US market holidays. Use a simple weekday check for the MVP; a proper holiday calendar (e.g., `exchange_calendars` or a hardcoded list) is optional for now. The gap-fill runs at 09:20 ET daily so only weekdays have RTH data.

### Pattern 5: SignalStatus str Enum

**What:** Drop-in replacement for raw status string literals.
**When to use:** Typed status dispatch with exhaustiveness checking.

```python
# Source: CONTEXT.md §SignalStatus Enum decision
from __future__ import annotations
import typing
from enum import Enum


class SignalStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    REGIME_SUPPRESSED = "regime_suppressed"
    # Terminal outcomes (set by lifecycle service)
    TARGET_HIT = "target_hit"
    STOP_HIT = "stop_hit"
    EXPIRED = "expired"
    CONDITION_EXPIRED = "condition_expired"


# Usage at comparison sites — no .value needed because str subclass:
if status == SignalStatus.ACTIVE:         # works: "active" == "active"
    ...
elif status == SignalStatus.PENDING:
    ...
else:
    typing.assert_never(status)           # type checker catches unhandled variants
```

**Gotcha:** `typing.assert_never()` was added in Python 3.11. For 3.9/3.10 compatibility use `typing_extensions.assert_never`. Check the venv Python version before deciding.

**Migration approach:** All 6 files have raw string comparisons. The `str` subclass means:
- `status == "active"` still evaluates True when `status` is `SignalStatus.ACTIVE`
- DB reads/writes are unchanged — `asyncpg` returns plain `str` from the DB, which compares equal to `SignalStatus` members
- No schema migration needed

### Anti-Patterns to Avoid

- **`pg_dump`/restore for hypertables**: chunk restoration is unreliable. The rename-swap is the only supported rebuild pattern (CLAUDE.md).
- **`ALTER TABLE hypertable SET (autovacuum_...)` on parent only**: this only applies to new chunks. For existing chunks, iterate `timescaledb_information.chunks` (CLAUDE.md).
- **`idx_scan = 0` as indicator of unused index on hypertable parents**: chunk-level indexes are tracked separately from the parent. Never drop a hypertable index based on `pg_stat_user_indexes.idx_scan` (CLAUDE.md).
- **Hardcoding signal status as raw strings in new code**: after DATA-06 lands, all new status comparisons must use `SignalStatus.ACTIVE` etc.
- **Non-CONCURRENTLY index on live hypertable**: blocks all writes. Always use `CONCURRENTLY` in production.
- **Running VACUUM inside a transaction block**: `VACUUM cannot run inside a transaction block` — use standalone `psql -c "VACUUM ..."` (CLAUDE.md).

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Hypertable chunk size calculation | Custom chunking math | TimescaleDB `chunk_time_interval => INTERVAL '7 days'` | TimescaleDB handles internal chunk sizing and index inheritance automatically |
| ET timezone conversion | Manual UTC offset | `zoneinfo.ZoneInfo("America/New_York")` | Handles DST transitions correctly; already used in CVDPlugin |
| Prometheus labeled counters | Custom metrics store | `prometheus_client.Counter(name, doc, labelnames=["symbol"])` | Already used in `PLUGIN_EXECUTION_TOTAL`; `src/observability/metrics.py` pattern |
| Batch DB update | Custom chunking loop | `psycopg2.extras.execute_batch()` | Already used in `repair_cis_nulls.py`; handles parameterized batch UPDATE |
| Service logging setup | Custom logger config | `setup_service_logging()` from `src/core/service_utils.py` | All services use this; creates `logs/<name>.log` with 10MB rotation |
| IBKR bar fetch | Custom IBKR API calls | `src/providers/ibkr.py` only | All ib_insync logic lives there — no direct imports elsewhere (CLAUDE.md) |

**Key insight:** Every infrastructure pattern in Phase 39 already exists in this codebase. The only net-new code is `gap_fill_service.py`; even that follows the cross-asset service template almost verbatim.

---

## Common Pitfalls

### Pitfall 1: ohlcv rebuild not restartable
**What goes wrong:** If the copy is interrupted halfway (large table, network blip), the script starts over from scratch.
**Why it happens:** Naive `INSERT INTO v2 SELECT * FROM v1` has no restartability.
**How to avoid:** Use `INSERT INTO market_data_ohlcv_v2 SELECT ... ON CONFLICT DO NOTHING`. The PK on the v2 table (same as v1) causes duplicate rows to be silently skipped on restart. Always confirm the PK/unique constraint is in place on v2 before starting the copy.
**Warning signs:** Script re-runs take as long as the first run.

### Pitfall 2: index CONCURRENTLY blocking inside a transaction
**What goes wrong:** `CREATE INDEX CONCURRENTLY` fails with `ERROR: CREATE INDEX CONCURRENTLY cannot run inside a transaction block`.
**Why it happens:** psql by default wraps each statement in a transaction; some migration scripts do too.
**How to avoid:** Run the index creation as a standalone statement via `psql -c "CREATE INDEX CONCURRENTLY ..."` or ensure the migration SQL file uses no `BEGIN`/`COMMIT` wrapper around this statement. The `IF NOT EXISTS` variant also works fine.
**Warning signs:** Error message immediately on execution.

### Pitfall 3: Gap-fill duplicate rows from ON CONFLICT
**What goes wrong:** `ON CONFLICT DO NOTHING` on a table without a unique constraint silently inserts duplicates.
**Why it happens:** `ON CONFLICT` only works when there is an applicable unique constraint or primary key.
**How to avoid:** Confirm the PK on `market_data_ohlcv` covers `(symbol, timeframe, timestamp)` before using `ON CONFLICT DO NOTHING` in the gap-fill fetch. The existing table schema should have this — verify before assuming.
**Warning signs:** Duplicate rows in `market_data_ohlcv` after gap-fill runs twice.

### Pitfall 4: SignalStatus enum not recognized for DB-read strings
**What goes wrong:** `asyncpg` returns plain `str` from the DB. Code that does `if status == SignalStatus.ACTIVE` passes a plain string — this works for the `str` enum subclass, but code that does `isinstance(status, SignalStatus)` or `SignalStatus(status)` (constructor) may behave differently.
**Why it happens:** DB reads return raw Python `str`, not enum members.
**How to avoid:** Only use `==` comparisons and `str` subclass equality. Do NOT use `isinstance(status, SignalStatus)` to check DB-read values — that would fail. Do NOT wrap DB values in `SignalStatus(status)` in the lifecycle code hot path (overhead). The `str` subclass makes equality transparent.
**Warning signs:** Tests pass but production sees `SignalStatus(status)` raise `ValueError` on unexpected DB values.

### Pitfall 5: repair_cis_nulls.py exits 0 on failure
**What goes wrong:** Current script prints a warning when `total_null_after != len(orphaned_ids)` but returns normally — CI/monitoring never surfaces the failure.
**Why it happens:** The verification block uses `print()` not `sys.exit(1)`.
**How to avoid:** Add `sys.exit(1)` when `recoverable_null_count > 0` after repair. This is the only code change needed to the existing script for DATA-01.
**Warning signs:** Script says "Verification warning" in output but returns exit code 0 — misleads operators.

### Pitfall 6: market_data_ohlcv rename blocks live services
**What goes wrong:** `ALTER TABLE RENAME` briefly locks the table. Services reading the old table name get a short error burst.
**Why it happens:** DDL locks are brief but real.
**How to avoid:** Schedule the rename outside market hours (e.g., weekend). All services have `Restart=always` and will reconnect. The expected ~1 minute downtime is acceptable. Do NOT attempt a zero-downtime view-based approach — it adds unnecessary complexity for a 1-minute operation.
**Warning signs:** Service logs show brief `relation "market_data_ohlcv" does not exist` errors during rename.

### Pitfall 7: `assert_never()` Python version mismatch
**What goes wrong:** `from typing import assert_never` fails on Python < 3.11.
**Why it happens:** `assert_never` was added in Python 3.11 (PEP 673).
**How to avoid:** Check the venv Python version (`python --version`). If < 3.11, import from `typing_extensions` instead: `from typing_extensions import assert_never`. The project should confirm the Python version before committing to `from typing import assert_never`.
**Warning signs:** `ImportError: cannot import name 'assert_never' from 'typing'`.

---

## Code Examples

### CIS Repair Script — Add Exit-1 Gate

```python
# Source: repair_cis_nulls.py main() — current verification block (needs modification)
# After repair, run second audit and check for remaining recoverable nulls
total_null_after, recoverable_after, orphaned_after = audit_null_cis(conn, symbols)

recoverable_remaining = len(recoverable_after)
if recoverable_remaining > 0:
    print(
        f"\n[FAIL] Completeness gate: {recoverable_remaining} recoverable rows "
        f"still have NULL cis_score. Exit 1."
    )
    sys.exit(1)

print(
    f"\n[PASS] Completeness gate: 0 recoverable nulls remain. "
    f"Orphaned (unrecoverable): {len(orphaned_after)}"
)
```

### ohlcv Rebuild Script — Verification Gate

```python
# Source: CONTEXT.md §market_data_ohlcv Rebuild decisions
def verify_v2_ready(conn, benchmark_query: str) -> bool:
    """Return True only if chunk_count < 200 AND benchmark query < 500ms."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM timescaledb_information.chunks "
            "WHERE hypertable_name = 'market_data_ohlcv_v2'"
        )
        chunk_count = cur.fetchone()[0]

    if chunk_count >= 200:
        logger.error("chunk_count_gate_fail", chunk_count=chunk_count)
        return False

    start = time.monotonic()
    with conn.cursor() as cur:
        cur.execute(benchmark_query)
        cur.fetchall()
    elapsed_ms = (time.monotonic() - start) * 1000

    if elapsed_ms >= 500:
        logger.error("latency_gate_fail", elapsed_ms=elapsed_ms)
        return False

    logger.info("v2_verification_passed", chunk_count=chunk_count, elapsed_ms=elapsed_ms)
    return True
```

### Gap-Fill Service — Prometheus Metrics

```python
# Source: src/observability/metrics.py module-level Counter pattern
from prometheus_client import Counter

GAP_FILL_GAPS_DETECTED = Counter(
    "gap_fill_gaps_detected_total",
    "Missing 1m RTH bar windows detected per symbol",
    ["symbol"],
)
GAP_FILL_BARS_FETCHED = Counter(
    "gap_fill_bars_fetched_total",
    "1m RTH bars successfully fetched per symbol",
    ["symbol"],
)
GAP_FILL_FETCH_FAILED = Counter(
    "gap_fill_fetch_failed_total",
    "Fetch attempts that failed per symbol",
    ["symbol"],
)

# Usage:
GAP_FILL_GAPS_DETECTED.labels(symbol=symbol).inc(gap_count)
if gap_count > 30:
    logger.critical("systemic_gap_detected", symbol=symbol, gap_count=gap_count)
```

### SignalStatus Enum — All Sites

```python
# Source: Existing files (grep confirmed)
# signal_ledger.py (DATA-06 addition):
from __future__ import annotations
import typing
from enum import Enum

class SignalStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    REGIME_SUPPRESSED = "regime_suppressed"
    TARGET_HIT = "target_hit"
    STOP_HIT = "stop_hit"
    EXPIRED = "expired"
    CONDITION_EXPIRED = "condition_expired"

# LedgerEntry:
status: str = SignalStatus.PENDING  # still stored as "pending" in DB

# lifecycle_tracker.py (lines 193, 212, 215, 352, 465):
if status == SignalStatus.PENDING:        # was: if status == "pending":
    ...
elif status == SignalStatus.ACTIVE:       # was: if status == "active":
    ...
else:
    typing.assert_never(status)           # new: exhaustiveness gate

# signal_lifecycle_service.py (many sites):
if status == SignalStatus.REGIME_SUPPRESSED:   # was: if status == "regime_suppressed":
    ...

# src/api/routes/signals.py (line 29):
_TERMINAL_STATUSES: frozenset[SignalStatus] = frozenset({
    SignalStatus.PENDING,
    SignalStatus.ACTIVE,
})
# line 378:
if s["status"] == SignalStatus.REGIME_SUPPRESSED:  # was: == "regime_suppressed"
```

### Hypertable chunk count verification query

```sql
-- Source: CLAUDE.md §TimescaleDB Gotchas
-- Count chunks in rebuilt table (target: < 200)
SELECT count(*)
FROM timescaledb_information.chunks
WHERE hypertable_name = 'market_data_ohlcv_v2'
  AND hypertable_schema = 'public';

-- Benchmark aggregate query for verification gate
SELECT symbol, timeframe, date_trunc('day', timestamp) AS day,
       max(high), min(low), sum(volume)
FROM market_data_ohlcv_v2
WHERE timestamp >= NOW() - INTERVAL '30 days'
GROUP BY 1, 2, 3
LIMIT 1;
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Raw string literals `"pending"`, `"active"` | `SignalStatus` enum | Phase 39 (this phase) | Type-safe status dispatch, compile-time exhaustiveness checking |
| 15,740 chunks / default interval on `market_data_ohlcv` | 7-day chunks, < 200 total | Phase 39 (this phase) | 4-5s query timeouts → < 500ms aggregate queries |
| 34ms lifecycle UPDATE latency | < 5ms with composite index | Phase 39 (this phase) | Lifecycle pipeline headroom |
| DragonflyDB Redis streams | Redpanda Kafka topics | Phase 30 | All stream keys use dots not colons |
| Status string in 6 raw-literal files | Typed enum, one definition | Phase 39 (this phase) | Prevents future status drift |

**Deprecated/outdated:**
- `docker exec ... psql ... -f /dev/stdin <<'EOF'`: does NOT work for SQL migrations. Always `docker cp file.sql timescaledb:/tmp/` first (CLAUDE.md confirmed).
- `from pytz import timezone`: replaced by stdlib `zoneinfo` in Python 3.9+. CVDPlugin already uses `zoneinfo`.

---

## Open Questions

1. **Python version in .venv**
   - What we know: `assert_never` requires Python 3.11+; `zoneinfo` requires 3.9+.
   - What's unclear: The exact Python version in the production `.venv`.
   - Recommendation: Run `python --version` at start of DATA-06 plan execution. If < 3.11, import `assert_never` from `typing_extensions` (already in many Python projects; verify it's installed or add it).

2. **market_data_ohlcv primary key / unique constraint structure**
   - What we know: `ON CONFLICT DO NOTHING` requires a unique constraint on the target columns.
   - What's unclear: The exact PK definition on `market_data_ohlcv` (whether it covers `(symbol, timeframe, timestamp)` or just `timestamp`).
   - Recommendation: Start the DATA-03 plan with `\d market_data_ohlcv` to confirm PK scope before writing the rebuild script. The hypertable's PK must include the partitioning column (`timestamp`).

3. **DATA-02 N count for DerivOsc and AC Osc**
   - What we know: Gate requires N >= 30 resolved signals. Script exits non-zero if N < 30 (prints `Insufficient data`).
   - What's unclear: Whether N >= 30 has been reached since the bootstrap promotion.
   - Recommendation: Start DATA-02 plan with a pre-check query:
     ```sql
     SELECT plugin_name, COUNT(*) as n
     FROM signal_ledger
     WHERE setup_plugin IN ('cmp_DerivativeOscillator', 'ind_ACOscillator')
       AND outcome IS NOT NULL
     GROUP BY 1;
     ```
     If N < 30, document the result and defer this task — it's a data accumulation gate, not a code problem.

4. **Gap-fill service: weekday / holiday detection**
   - What we know: Service runs daily at 09:20 ET. RTH only applies to weekdays on US trading days.
   - What's unclear: Whether a holiday calendar library is available or desired.
   - Recommendation (Claude's Discretion): For the MVP, skip the holiday calendar. Use a simple weekday check (`datetime.weekday() < 5`). The gap-fill running on a holiday does minimal harm — it will find 0 expected bars for that day and do nothing. Add holiday-awareness only if explicitly requested.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (pyproject.toml `[tool:pytest]`) |
| Config file | `pyproject.toml` — `[tool:pytest]` section |
| Quick run command | `.venv/bin/pytest tests/unit/scripts/ -v -x` |
| Full suite command | `.venv/bin/pytest tests/unit/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DATA-01 | `repair_cis_nulls.py` exits 1 when recoverable nulls remain | unit | `.venv/bin/pytest tests/unit/scripts/test_repair_cis_nulls.py -v -x` | ✅ (existing, needs new test for exit-1 gate) |
| DATA-02 | `validate_alpha.py` exits 1 when N < 30 | unit | `.venv/bin/pytest tests/unit/scripts/test_validate_alpha.py -v -x` | ✅ (existing) |
| DATA-03 | `rebuild_ohlcv.py` verification gate: chunk_count >= 200 exits 1 | unit | `.venv/bin/pytest tests/unit/scripts/test_rebuild_ohlcv.py -v -x` | ❌ Wave 0 |
| DATA-03 | `rebuild_ohlcv.py` verification gate: latency >= 500ms exits 1 | unit | `.venv/bin/pytest tests/unit/scripts/test_rebuild_ohlcv.py::test_verify_v2_latency_gate_fails -v` | ❌ Wave 0 |
| DATA-04 | Index existence verified by EXPLAIN ANALYZE showing index scan | manual | `docker exec timescaledb psql ... -c "EXPLAIN ANALYZE ..."` | manual-only |
| DATA-05 | RTH window generation produces 390 bars on a standard weekday | unit | `.venv/bin/pytest tests/unit/service_tests/test_gap_fill_service.py -v -x` | ❌ Wave 0 |
| DATA-05 | Gap detection: missing timestamps identified correctly | unit | `.venv/bin/pytest tests/unit/service_tests/test_gap_fill_service.py::test_detect_gaps -v` | ❌ Wave 0 |
| DATA-05 | ON CONFLICT idempotency: running twice produces no duplicates | manual | `docker exec timescaledb psql ... -c "SELECT COUNT(*) ..."` after two runs | manual-only |
| DATA-06 | `grep -r '"pending"\|"active"\|"regime_suppressed"' services/` returns 0 | smoke | `.venv/bin/pytest tests/unit/intelligence/test_signal_status_enum.py -v -x` | ❌ Wave 0 |
| DATA-06 | `SignalStatus` enum equality with raw strings | unit | `.venv/bin/pytest tests/unit/intelligence/test_signal_status_enum.py -v -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `.venv/bin/pytest tests/unit/scripts/ tests/unit/service_tests/ -v -x -q`
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/unit/scripts/test_rebuild_ohlcv.py` — covers DATA-03 verification gate logic (pure function tests, no DB)
- [ ] `tests/unit/service_tests/test_gap_fill_service.py` — covers RTH window generation (DATA-05), gap detection logic
- [ ] `tests/unit/intelligence/test_signal_status_enum.py` — covers DATA-06 enum equality, str subclass behavior

*(Existing test infrastructure: pytest configured, `tests/unit/scripts/test_repair_cis_nulls.py` ✅, `tests/unit/scripts/test_validate_alpha.py` ✅)*

---

## Sources

### Primary (HIGH confidence)
- `production/scripts/repair_cis_nulls.py` — complete script reviewed; exact batch_size parameter exists; only exit-1 gate missing
- `production/scripts/validate_alpha.py` — complete script reviewed; N >= 30 gate exists; operational task only
- `src/intelligence/trading/signal_ledger.py` — `LedgerEntry.status: str = "pending"` confirmed; `SignalStatus` not yet defined
- `src/intelligence/trading/lifecycle_tracker.py` — raw string comparisons at lines 193, 212, 215, 352, 465 confirmed
- `services/signal_lifecycle_service.py` — raw string comparisons at 13 sites confirmed via grep
- `services/signal_generator_service.py` — `entry_status = "pending" if is_regime_eligible else "regime_suppressed"` confirmed
- `src/api/routes/signals.py` — `_TERMINAL_STATUSES` frozenset and `status == "regime_suppressed"` confirmed
- `src/observability/metrics.py` — labeled Counter pattern (module-level constants with `labelnames`) confirmed
- `src/core/service_utils.py` — `setup_service_logging()` signature confirmed; `TF_SECONDS`, `TF_TTL_BARS` available
- `production/systemd/indicagent-cross-asset.service` — canonical service unit template confirmed
- `production/migrations/039_performance_and_schema_fixes.sql` — existing migration confirms `CREATE INDEX IF NOT EXISTS ... ON signal_ledger` syntax
- `CLAUDE.md` §TimescaleDB Gotchas — all hypertable constraints confirmed (docker cp pattern, no pg_dump, chunk indexing behavior)

### Secondary (MEDIUM confidence)
- TimescaleDB `create_hypertable` + `chunk_time_interval` API — standard documented API; 7-day interval is within recommended range for this data density
- `typing.assert_never()` Python 3.11+ — confirmed from Python changelog; `typing_extensions` fallback well-known

### Tertiary (LOW confidence)
- None — all findings are grounded in actual codebase files.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries are already installed and used in the codebase
- Architecture: HIGH — all patterns sourced from existing project files
- Pitfalls: HIGH — sourced from CLAUDE.md documented gotchas and code review of existing scripts
- Test coverage: HIGH — existing test files confirmed; gaps identified

**Research date:** 2026-03-19
**Valid until:** 2026-04-18 (stable domain; 30-day window)
