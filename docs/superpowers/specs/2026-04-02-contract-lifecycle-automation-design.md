# Contract Lifecycle Automation — Design Spec

**Date:** 2026-04-02  
**Status:** Approved for implementation  
**Phase:** v2.2 — Contract Lifecycle Automation  

---

## Problem Statement

Three symptoms, one root cause: the contract lifecycle has no automation layer. Every futures roll requires a human to update `settings.py` and `contract_metadata`. The bar auditor uses a hardcoded 95% completeness threshold that is structurally wrong for overnight sessions. The roll detection algorithm (`RollComputeAgent`) is validated and running but its output goes nowhere.

A system Jim Simons would accept has zero manual tasks in steady-state operation. This design closes that gap.

---

## Renaissance Principles Applied

- **Instrument everything** — completeness metrics derived from actual session geometry, not arbitrary thresholds
- **Let the system run** — zero operator intervention after a roll; detection → promotion → audit all automatic
- **Segment relentlessly** — each session type has its own structurally correct expected bar count and achievable ceiling
- **Degrade gracefully** — DB unavailable at startup = hard fail; roll event for unknown symbol = DLQ, not crash
- **No manual tasks** — `settings.py` front-month defaults are permanently retired after first boot

---

## Architecture

The contract lifecycle has four stages. Each maps to exactly one agent or subsystem with a single responsibility:

```
Stage 1: SEED (startup, idempotent)
  settings.py (static config: point_value, tick_size, session_id, exchange)
      → ContractMetadataWriterAgent._seed_missing_contracts()
      → contract_metadata (INSERT only — never overwrites existing rows)

Stage 2: DETECT (continuous, event-driven)
  market.bars
      → RollComputeAgent (z-score + calendar gate, DB-ignorant)
      → market.events.roll

Stage 3: PROMOTE (event-driven, automated)
  market.events.roll
      → ContractMetadataWriterAgent._handle_roll_event()
      → contract_metadata (atomic: demote old, promote new)
      → market.events.contract_update (broadcast to live services)

Stage 4: AUDIT (periodic, session-aligned)
  contract_metadata (via get_active_contracts(), 60s TTL cache)
      → BarAuditorAgent (session-aligned windows, derived ceiling)
      → market.events.gap_requests
      → IBKRProviderAgent (gap fill)
      → market_data_ohlcv
```

### DAG Summary

| Agent | Role | Consumes | Produces |
|---|---|---|---|
| `RollComputeAgent` | ComputeAgent | `market.bars` | `market.events.roll` |
| `ContractMetadataWriterAgent` | WriterAgent | `market.events.roll` | `contract_metadata` + `market.events.contract_update` |
| `BarAuditorAgent` | AuditorAgent | `market.events.contract_update` (cache flush) | `market.events.gap_requests` |

### What Changes vs. Today

| Today | After |
|---|---|
| `settings.py` defaults contain front-months | `settings.py` has static fields only — no front-months |
| Roll detection is shadow | Roll detection is live; `contract_metadata` auto-updates |
| BarAuditorAgent uses midnight-to-midnight UTC windows | BarAuditorAgent uses session-aligned windows |
| Completeness ceiling is hardcoded 95% constant | Ceiling derived from `TradingSession.max_achievable_pct()` |
| `contract_metadata` requires manual UPDATE to roll | `ContractMetadataWriterAgent` promotes on detected roll |
| No broadcast when contracts change | `market.events.contract_update` notifies live services |

### What Does NOT Change

- `get_active_contracts()` API — all callers unchanged
- `RollComputeAgent` internals — z-score algorithm untouched
- `contract_metadata` schema — all needed columns already exist
- `market.events.roll` topic — already exists, already published to
- Systemd process management model

---

## Component 1: ContractMetadataWriterAgent (New)

**File:** `services/contract_metadata_writer_agent.py`  
**Class:** `ContractMetadataWriterAgent`  
**Role:** WriterAgent — DB-aware, no compute logic, no signal intelligence  
**Systemd unit:** `indicagent-contract-metadata-writer.service`  
**Metrics port:** `:9124`  
**Consumes:** `market.events.roll`  
**Produces:** `contract_metadata` (DB), `market.events.contract_update` (Kafka)  

### Startup: `_seed_missing_contracts()`

Runs once in `_setup()` before consuming events. Idempotent INSERT: for each futures instrument in `settings.py` that has no row in `contract_metadata`, insert a row seeded from config. If a row exists (any row for that base symbol), skip — DB is already authoritative.

This is the last time `settings.py` front-month data is used. After first boot, the DB owns all front-month state permanently.

```sql
INSERT INTO contract_metadata (symbol, base_symbol, asset_class, exchange, is_front_month)
VALUES ($1, $2, 'futures', $3, true)
ON CONFLICT (symbol) DO NOTHING
```

### Live Operation: `_handle_roll_event()`

On each `RollEvent` from `market.events.roll`:

1. Validate `old_contract` and `new_contract` are both non-empty; send to DLQ if malformed
2. Execute atomically in a single transaction:
   - `UPDATE contract_metadata SET is_front_month = false WHERE symbol = old_contract`
   - `INSERT INTO contract_metadata (..., is_front_month = true, roll_from = old_contract, roll_detected_at = detection_ts, confirmation_count = ...) ON CONFLICT (symbol) DO UPDATE SET is_front_month = true, ...`
3. Publish `ContractUpdateEvent` to `market.events.contract_update`
4. Invalidate `get_active_contracts()` cache by zeroing `_active_contracts_last_refresh`

Steps 2a and 2b are in one transaction — no window where a base symbol has zero or two front-months.

### `market.events.contract_update` Topic

New topic. Payload: `{ base_symbol, old_contract, new_contract, promoted_at }`.

Purpose: live services flush their contract cache immediately rather than waiting up to 60s for TTL expiry. **Not required for correctness** — it is a latency optimization. Services that do not subscribe converge within one TTL cycle.

### Graceful Degradation

- DB unavailable at startup → agent refuses to start (hard fail, log error). Correct behavior: rolls require DB. Silent degradation would corrupt the SoT.
- Roll event for unknown symbol → log warning, publish to `market.events.roll.dlq`, continue. Do not crash.
- Duplicate roll event (same old→new already promoted) → idempotent UPSERT handles it, publish no-op `ContractUpdateEvent`.

### Metrics (Golden Signals)

| Metric | Type | Description |
|---|---|---|
| `contract_writer_rolls_processed_total` | Counter | Roll events successfully processed |
| `contract_writer_roll_errors_total` | Counter | Failed roll processing (DLQ'd) |
| `contract_writer_seeds_inserted_total` | Counter | Rows seeded at startup |
| `contract_writer_processing_latency_seconds` | Histogram | DB write latency per roll event |

---

## Component 2: BarAuditorAgent — Session-Aligned Windows

### Root Cause

The auditor queries `WHERE timestamp >= midnight AND timestamp < next_midnight` (UTC calendar day) but `_expected_bars_for_date()` computes based on session open/close times. For CME ES (opens 23:00 UTC Sunday, closes 22:00 UTC Monday), a Monday audit queries the wrong bar window, producing structurally incorrect completeness readings.

### Fix 1: `TradingSession.session_window_for_date(target_date) → (start_utc, end_utc)`

New pure method on `TradingSession` in `src/core/models.py`. Returns the actual UTC window for a session on a given calendar date:

| Session Type | Window Logic |
|---|---|
| Same-day (NYSE: 09:30–16:00 ET) | `target_date 09:30 ET → target_date 16:00 ET`, converted to UTC |
| Overnight (CME: 18:00 CT prev → 17:00 CT) | `(target_date − 1d) 18:00 CT → target_date 17:00 CT`, converted to UTC |
| All-day (crypto, FX) | `target_date 00:00 UTC → (target_date + 1d) 00:00 UTC` |

This replaces the hardcoded `datetime(year, month, day, 0, 0, 0, tzinfo=UTC)` in `_detect_gaps()`.

`BarGapRequest.start_ts` / `end_ts` now carry session-aligned timestamps — the IBKR backfill fetches exactly the right window.

### Fix 2: `TradingSession.max_achievable_pct() → float`

Derived entirely from the session definition — no magic numbers, no per-instrument constants:

```
expected_bars     = _expected_bars_for_date(session, any_trading_day)
                    (already subtracts trading_breaks)
session_minutes   = minutes in session_window_for_date()
max_achievable    = expected_bars / session_minutes
```

For CME overnight with breaks fully encoded in `trading_breaks`: `max_achievable = 1.0`. For sessions where IBKR structurally under-delivers (known first/last bar edge), encode those breaks explicitly. The system derives the ceiling from data, not from a developer's intuition.

### Fix 3: Derived Threshold

Replace the single `_COMPLETENESS_THRESHOLD = 0.95` constant with:

```python
_COMPLETENESS_GATE = 0.97  # system-wide: "97% of structurally achievable bars"

threshold = session.max_achievable_pct() * _COMPLETENESS_GATE
```

One constant, self-adjusting per session type. No per-instrument overrides ever.

### Fix 4: Subscribe to `market.events.contract_update`

`BarAuditorAgent` subscribes to the new topic. On receipt: zero `_active_contracts_last_refresh` so the next audit cycle fetches fresh contracts. Within one audit cycle after a roll, the auditor is tracking the correct front-month symbol.

---

## Component 3: SoT Consolidation — `settings.py` Cleanup

### Principle

`settings.py` defines **what** an instrument is (point value, tick size, session type, exchange, sector). `contract_metadata` defines **which contract** is currently active. These are orthogonal concerns that have been conflated.

### Changes to `settings.py`

Remove front-month symbols from `build_contracts()` defaults. The defaults become base-symbol templates with static fields only:

```python
Instrument(
    symbol="ES",        # base symbol as placeholder — never used by get_active_contracts()
    base="ES",
    exchange="CME",
    # ... point_value, tick_size, session_id, sector — all static, never change on a roll
)
```

`get_active_contracts()` already queries DB-first and uses `_build_instrument_from_db_row()` to inherit these static fields via `config_by_base` lookup. The base-symbol template is the inheritance source. The DB provides the live symbol.

### No Migration Script Needed

`ContractMetadataWriterAgent._seed_missing_contracts()` handles bootstrap on first deployment. The seed uses the current `settings.py` front-month defaults (which still exist at deployment time, just not as runtime state). After the seed runs once, the defaults in `settings.py` are replaced with base-symbol templates and never touched again.

### `get_active_contracts()` Behavior Unchanged

- DB query first (futures: `WHERE is_front_month = true AND asset_class = 'futures'`)
- Config-file non-futures (FX, equity, crypto) appended — these never roll, so config remains authoritative for them
- 60s TTL cache — flushed early by `ContractUpdateEvent`
- Fallback to full config list on DB error — unchanged

---

## Component 4: RollComputeAgent Graduation

### Graduation Gate

The algorithm is already validated by construction: `contract_metadata` records H6→M6 transitions on 2026-03-16 for all quarterly contracts. A back-test script replays `market_data_ohlcv` bars from the two weeks prior to each known roll date through `RollMonitor.check_roll()` and verifies:

1. Roll fires within the known roll window (not before, not after)
2. No false positives in the 30 days preceding the roll window
3. Cooldown prevents double-fire

If back-test passes: graduate. If it fails: fix the algorithm, re-test, then graduate. Graduation is a commit + systemd enable, not a meeting.

### Graduation Steps

1. Run back-test script against known rolls
2. If passes: `sudo systemctl enable --now indicagent-roll-compute.service` (agent has no IS_SHADOW flag — it is simply disabled in systemd)
3. `sudo systemctl enable --now indicagent-contract-metadata-writer.service`
4. Steps 2 and 3 are deployed together — they are a unit (detector + writer)
5. Replace hardcoded front-month defaults in `settings.py` with base-symbol templates in the same commit

**Sequencing constraint:** Step 1 (`ContractMetadataWriterAgent` deployment) must run first so that `_seed_missing_contracts()` executes against the pre-cleanup `settings.py` (which still contains front-month symbols like `ESM6`). Only after the seed has successfully run should `settings.py` be updated to base-symbol templates. The seed is idempotent — subsequent runs with the updated `settings.py` insert nothing.

### Shadow→Live Transition Safety

During the first roll cycle post-graduation:
- `RollComputeAgent` detects the roll, publishes to `market.events.roll`
- `ContractMetadataWriterAgent` promotes new front-month
- `BarAuditorAgent` picks up new symbol within one audit cycle
- `IBKRProviderAgent` restarts (manual step — daemon reads contracts once at startup)

IBKRProviderAgent restart on roll is the one remaining manual step. This is acceptable: a futures roll is a scheduled, known event (quarterly for equity index, monthly for energy/metals). It can be handled by a systemd override or a cron that checks for `ContractUpdateEvent` and triggers a restart. That automation can be deferred — it is not part of this design.

---

## Error Handling & Degradation

| Failure Mode | Behavior |
|---|---|
| DB unavailable at `ContractMetadataWriterAgent` startup | Hard fail — refuse to start. Correct: soft start would corrupt SoT. |
| Malformed `RollEvent` payload | DLQ to `market.events.roll.dlq`, continue processing |
| Duplicate roll event | Idempotent UPSERT — no side effects |
| `session_window_for_date()` for unknown session type | Raise `ValueError` at startup validation — fail fast before any audit runs |
| Gap request for expired front-month (auditor behind on contract update) | IBKR returns no data — `BarGapRequest` silently unfulfilled. Auditor corrects itself on next cycle once cache refreshes. |
| `market.events.contract_update` topic missing | `BarAuditorAgent` continues on TTL cache only — degrades to 60s latency, not a failure |

---

## Testing Strategy

### Unit Tests

| Test | What it validates |
|---|---|
| `test_session_window_for_date_overnight` | CME ES Monday window = Sunday 23:00 UTC → Monday 22:00 UTC |
| `test_session_window_for_date_same_day` | NYSE Monday window = Monday 13:30 UTC → Monday 20:00 UTC |
| `test_max_achievable_pct_with_breaks` | Session with 60-min maintenance break → ceiling reflects break subtraction |
| `test_seed_missing_contracts_idempotent` | Second call inserts 0 rows |
| `test_handle_roll_event_atomic` | After roll: old `is_front_month=false`, new `is_front_month=true`, no window with two fronts |
| `test_handle_roll_event_malformed` | Missing old_contract → DLQ publish, no DB write |
| `test_detect_gaps_session_aligned` | Query window uses session timestamps, not midnight UTC |
| `test_completeness_threshold_derived` | Threshold = `max_achievable_pct * _COMPLETENESS_GATE` |

### Integration Test

Replay known H6→M6 roll through `RollMonitor.check_roll()` against actual `market_data_ohlcv` bars. Assert:
- Roll detected within roll window
- Zero false positives in 30-day pre-window
- `contract_metadata` reflects promotion correctly post-event

### Back-test Script

`production/scripts/roll_backtest.py` — standalone script, runs against live DB, prints per-symbol detection results vs. ground truth. Pass/fail gate for graduation.

---

## Deployment Order

1. Deploy `ContractMetadataWriterAgent` (seeding runs at first startup)
2. Verify `contract_metadata` rows seeded correctly
3. Run `roll_backtest.py` — verify graduation gate passes
4. Enable `RollComputeAgent` (remove shadow, systemd enable)
5. Modify `settings.py` — replace front-month defaults with base-symbol templates
6. Deploy `BarAuditorAgent` with session-aligned windows

Steps 4 and 5 are deployed together atomically. Steps 1–3 can be deployed independently.

---

## Files Modified / Created

| File | Change |
|---|---|
| `services/contract_metadata_writer_agent.py` | **New** — ContractMetadataWriterAgent |
| `services/indicagent-contract-metadata-writer.service` | **New** — systemd unit |
| `src/core/models.py` | Add `session_window_for_date()` + `max_achievable_pct()` to `TradingSession` |
| `src/core/schemas/market_events.py` | Add `ContractUpdateEvent` schema |
| `src/core/stream_keys.py` | Add `topic_contract_updates()` + `topic_roll_dlq()` |
| `services/bar_auditor_agent.py` | Session-aligned windows, derived threshold, subscribe to contract_update |
| `src/config/settings.py` | Replace front-month defaults with base-symbol templates |
| `services/indicagent-roll-compute.service` | No change — graduated via `systemctl enable`, not a code flag |
| `production/scripts/roll_backtest.py` | **New** — graduation back-test script |
| `tests/unit/test_contract_metadata_writer_agent.py` | **New** — unit tests |
| `tests/unit/test_bar_auditor_agent.py` | Extend with session-aligned window tests |
| `tests/unit/test_models.py` | Extend with `session_window_for_date` tests |
