# Phase 39: Data Quality + DB Health - Context

**Gathered:** 2026-03-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Foundation work for the ML training dataset: repair CIS nulls in `signal_ledger`, rebuild `market_data_ohlcv` with correct chunk interval, add composite index to `signal_ledger`, create a self-healing gap-fill service for missing 1m RTH bars, re-run alpha validation for bootstrap-promoted plugins once N >= 30, and replace all raw signal status string literals with a typed `SignalStatus` enum. No new features — purely data quality, database health, and type safety.

</domain>

<decisions>
## Implementation Decisions

### Philosophy
- Every fix must be **institutional grade** — not just "works," but hardened, observable, self-healing, and exhaustively verified.
- Renaissance north star: instrument everything, let the system run, earn the right through proof.
- All changes must be idempotent (safe to run twice), observable (Prometheus metrics + structured logs), and self-validating (exit non-zero if goals not met).

### market_data_ohlcv Rebuild (DATA-03)
- **Strategy**: Create `market_data_ohlcv_v2` with correct chunk interval, backfill from old table, then atomic `ALTER TABLE RENAME` swap. Production continues reading the old table during rebuild — zero data loss window.
- **Chunk interval**: 7-day chunks. Calculated from data density: 23 symbols × 5 TFs over 7 years. TimescaleDB sweet spot for this data profile — balances aggregate query performance with insert locality.
- **Verification gate before swap**: automated check confirms `chunk_count < 200` AND a benchmark aggregate query completes `< 500ms`. Gate must pass before rename executes — script exits 1 if it fails.
- **Script is restartable**: if rebuild is interrupted mid-copy, restarting resumes from where it left off (delete-and-restart or use INSERT ... ON CONFLICT DO NOTHING).
- **Services stay live**: feature-writer and all read consumers continue operating on old table throughout. Only ~1 minute downtime for the rename.

### signal_ledger Composite Index (DATA-04)
- Add composite index on `(symbol, timeframe, status, computed_at DESC)` to cover lifecycle UPDATE pattern.
- Verify with `EXPLAIN ANALYZE` on a representative lifecycle UPDATE — confirm index scan, latency < 5ms.
- Create `CONCURRENTLY` to avoid locking the table during creation.

### CIS Null Repair (DATA-01)
- `repair_cis_nulls.py` already exists. Execution strategy to overcome shared memory issue:
  - **Chunked batches of 500 rows** — avoids large JOIN materialisation that hit PostgreSQL shared memory limit on 1.8M row table.
  - **Services stay live** — script is idempotent (`WHERE cis_score IS NULL` guard on UPDATE).
  - **Progress tracking**: print before-count, per-chunk progress, after-count.
  - **Completeness gate**: after repair, script runs a verification query — if `recoverable_null_count > 0`, exit 1. Non-zero exit surfaces in any CI/monitoring. Zero recoverable nulls = success.

### Gap-Fill Service (DATA-05)
- **New systemd service** `indicagent-gap-fill` — not a cron script. Self-healing infrastructure runs automatically.
- **Schedule**: Runs daily at 09:20 ET (10 minutes before RTH opens). Detects and fills gaps before the trading day starts.
- **Gap detection**: queries `market_data_ohlcv` for expected vs actual 1m bar timestamps per symbol per RTH window (09:30–16:00 ET). Expected = every 1m interval. Actual = what's stored. Diff = missing windows to fetch.
- **Fetch**: calls IBKR for only the missing windows. Uses `ON CONFLICT DO NOTHING` — running twice is safe.
- **Prometheus metrics**:
  - `gap_fill_gaps_detected_total{symbol}` — how many missing windows found
  - `gap_fill_bars_fetched_total{symbol}` — how many bars successfully fetched
  - `gap_fill_fetch_failed_total{symbol}` — how many fetch attempts failed
- **Alert threshold**: if `gaps_detected > 30` for any symbol, log at `CRITICAL` level — signals systemic data collection failure that automated gap-fill cannot resolve.
- **Metrics port**: `:9119` (next available after cross-asset :9118)
- **Logging**: via `setup_service_logging()` → `logs/gap-fill.log`

### SignalStatus Enum (DATA-06)
- **Location**: `src/intelligence/trading/signal_ledger.py` — co-located with `LedgerEntry`. Signal status is trading-domain, not infrastructure-core.
- **String-compatible values** — no DB migration needed:
  ```python
  class SignalStatus(str, Enum):
      PENDING = "pending"
      ACTIVE = "active"
      REGIME_SUPPRESSED = "regime_suppressed"
      # Terminal outcomes (from lifecycle)
      TARGET_HIT = "target_hit"
      STOP_HIT = "stop_hit"
      EXPIRED = "expired"
      CONDITION_EXPIRED = "condition_expired"
  ```
- **Exhaustiveness gate**: all `if/elif` chains on `SignalStatus` in lifecycle/generator code must use `typing.assert_never()` in the else branch. Python type checker (pyright/mypy) catches unhandled new statuses at dev time.
- **Migration scope**: 6 files — `signal_ledger.py`, `lifecycle_tracker.py`, `signal_generator_service.py`, `signal_lifecycle_service.py`, `src/api/routes/signals.py` (×2 occurrences). All string comparisons replaced with `SignalStatus.PENDING` etc.
- **DB values unchanged** — the enum's `.value` property returns the same string already stored. No migration script needed.

### Alpha Validation Re-run (DATA-02)
- `validate_alpha.py --promote` for `cmp_DerivativeOscillator` and `ind_ACOscillator`.
- Gate: N >= 30 resolved signals required before promotion.
- Script already exists — this is an operational task, not new code.
- Add a check at start of plan execution: if N < 30, document exact query to recheck and defer step until data accumulates.

### Renaissance-Grade Hardening Additions
All 4 additions approved — included in plan scope:
1. **Health-check gate** on ohlcv rebuild (chunk count + query latency verified before swap)
2. **CIS repair completeness gate** (exit 1 on non-zero recoverable nulls)
3. **Gap-fill Prometheus metrics** + CRITICAL alert on systemic failures
4. **SignalStatus exhaustiveness checking** via `assert_never()` in all status dispatch chains

### Claude's Discretion
- Exact batch insert strategy for ohlcv rebuild (COPY vs INSERT ... SELECT batches)
- Implementation of RTH window generation for gap detection (timezone handling for ET)
- Whether gap-fill service also covers non-1m timeframes (requirement only specifies 1m)
- Ordering of execution steps within each plan

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Database & TimescaleDB
- `CLAUDE.md` §TimescaleDB Gotchas — chunk size gotchas, hypertable migration rules, pg_dump restrictions, psql migration via docker cp pattern, index gotchas on hypertables
- `CLAUDE.md` §Data Flow — hot/warm/cold tier roles, what market_data_ohlcv is for (backfill only, keep forever)

### Existing Scripts
- `production/scripts/repair_cis_nulls.py` — CIS null repair, current implementation, shared memory issue context
- `production/scripts/validate_alpha.py` — alpha validation gate, --promote flag, hard gates (N>=30, r>0, p<0.05)
- `production/scripts/historical_backfill.py` — existing gap-fill with --days N, fetch/replay stages

### Signal Status
- `src/intelligence/trading/signal_ledger.py` — LedgerEntry, current string usage (`status: str = "pending"`)
- `src/intelligence/trading/lifecycle_tracker.py` — status comparison patterns to migrate
- `services/signal_generator_service.py` — `entry_status` assignment to migrate
- `services/signal_lifecycle_service.py` — all status comparisons to migrate
- `src/api/routes/signals.py` — `_TERMINAL_STATUSES` frozenset to migrate

### Service Patterns
- `CLAUDE.md` §Core Runtime Files — `setup_service_logging()`, `src/core/service_utils.py`
- `CLAUDE.md` §Active Services table — metrics port convention (next: :9119 for gap-fill)
- `CLAUDE.md` §Key Rules — Timestamps UTC, Settings usage, stream keys via stream_keys.py
- `src/observability/metrics.py` — metrics registration pattern (prevent duplicate registration)

### Requirements
- `.planning/REQUIREMENTS.md` §DATA — DATA-01 through DATA-06 acceptance criteria

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `repair_cis_nulls.py`: Complete script — needs only batch-size parameter added (default 500)
- `validate_alpha.py`: Complete script — operational task, no code changes needed
- `historical_backfill.py`: Gap detection logic needs to be added; fetch logic already handles `--days N`
- `src/core/service_utils.py`: `setup_service_logging()` for gap-fill service logging
- `src/observability/metrics.py`: Pattern for registering Prometheus counters/gauges
- `src/config/settings.py`: `get_active_contracts()` for symbol list in gap-fill

### Established Patterns
- Service structure: graceful SIGINT/SIGTERM, drain queues, idempotent consumer groups
- Signal status: raw string literals in 6 files — no enum exists yet
- Systemd services: `indicagent-<name>.service`, `PYTHONUNBUFFERED=1` required
- DB migrations: `docker cp file.sql timescaledb:/tmp/file.sql` then `docker exec ... -f /tmp/file.sql`

### Integration Points
- Gap-fill service connects to `market_data_ohlcv` (TimescaleDB) and IBKR (via `src/providers/ibkr.py`)
- SignalStatus enum is a drop-in replacement — string values unchanged, so no downstream consumers break
- ohlcv rebuild runs purely in TimescaleDB — no service code changes needed

</code_context>

<specifics>
## Specific Ideas

- Gap-fill service: "self-healing infrastructure" — runs every trading day without manual intervention
- ohlcv rebuild: atomic swap pattern (create → backfill → verify → rename) — never touch production data until verified
- CIS repair: 500-row chunks resolve the shared memory issue; completeness gate (exit 1) makes it pipeline-safe
- SignalStatus: `str` enum subclass so `.value` comparison is transparent; `assert_never()` for exhaustiveness

</specifics>

<deferred>
## Deferred Ideas

- Gap-fill for non-1m timeframes (5m, 15m, 1h) — DATA-05 only specifies 1m; add to backlog if 1m gaps are resolved
- Automated CIS repair on startup (detect + repair nulls on signal_generator_service start) — interesting but scope creep; add to backlog
- ohlcv retention policy (compression + tiered storage for data > 1 year) — Phase 39 is about correctness, not compression

</deferred>

---

*Phase: 039-data-quality-db-health*
*Context gathered: 2026-03-19*
