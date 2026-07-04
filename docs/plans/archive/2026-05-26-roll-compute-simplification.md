# Roll Compute Simplification Plan

**Version:** 1.0
**Last Updated:** 2026-05-26
**Date:** 2026-05-26
**Status:** Plan
**Goal:** Replace 24/7 real-time RollComputeAgent + ContractMetadataWriterAgent with a calendar-driven nightly batch that updates `is_front_month` in `contract_metadata`.

## Design Principles

This refactor follows the same principles that govern the rest of the system:

1. **Simplicity over cleverness** — The current system uses numpy z-scores on streaming bar data to detect periodic roll events. The exchange publishes the roll calendar. Use the calendar.
2. **Separation of concerns** — Detection, execution, and broadcast are pure functions. No I/O mixed with logic.
3. **Shadow mode first** — Run the new batch alongside the old agents for one full roll cycle. Compare outputs. Then cut over.
4. **Instrument everything** — Even batch jobs emit structured logs and metrics. Silent failures are unacceptable.
5. **Idempotent by default** — The script can run twice, fail mid-way, or miss a week. Next run picks up where it left off.
6. **Fail-safe** — If the batch fails, current state persists. No partial writes. The system degrades gracefully to "last known good state."

## Why Calendar-Only, No Volume Detection

The current system has two detection paths: volume z-score (primary) and calendar (fallback). A Renaissance quant would ask: "Why do we need the primary at all?"

- **We don't execute trades.** Our system collects data and generates signals. There is no position risk from rolling a day early or late.
- **Volume detection adds complexity without adding value.** It requires numpy, rolling windows, streaming state, and 24/7 bar consumption — all to detect something the calendar already tells us.
- **The calendar IS the answer.** `get_roll_window()` from `contracts.py` already computes exact roll windows per symbol. `derive_roll_chain()` already knows which contract is next. These are pure functions, tested, and deterministic.
- **The cost of being wrong is near-zero.** A late roll means bars temporarily map to the old contract for a few hours. Annoying, not fatal.

## Architecture (Current)

```
market_bars (1m) → RollComputeAgent (24/7, z-score + calendar) → topic_roll_events
                                                                   ↓
                                           ContractMetadataWriterAgent → DB + roll_events
                                                                   ↓
                                           ServiceAuditor → restarts ibkr-provider + roll-compute
```

Three active services, ~1,300 lines, two Kafka topics, restart cascades.

## Architecture (Proposed)

```
systemd timer (6pm ET nightly) → roll_batch.py
                                    ↓
                                 1. seed_missing_contracts(conn, settings)   — pure DB write
                                 2. detect_rolls(today)                      — pure function, calendar-only
                                 3. execute_promotion(conn, base, old, new)  — atomic DB transaction
                                 4. broadcast_update(producer, base, old, new) — Kafka publish
```

One script, no running service, no restarts. Four pure functions, each testable in isolation.

## Phase 1: Nightly Batch Script

Create `production/scripts/roll_batch.py` with four functions:

### `seed_missing_contracts(conn, settings) -> int`
- Read `get_active_contracts(settings)`, filter futures
- Multi-row INSERT with ON CONFLICT DO NOTHING
- Returns count of new rows seeded
- Replaces `ContractMetadataWriterAgent._seed_missing_contracts()`

### `detect_rolls(today: date) -> list[RollDecision]`
- Pure function, no I/O
- For each base symbol in `FUTURES_ROLL_CYCLES`:
  - `get_roll_window(base_symbol, today)` — if `None`, skip
  - If today >= roll_end: `derive_roll_chain(base_symbol)` to get old + new contract
  - Return `RollDecision(base_symbol, old_contract, new_contract, roll_end_date)`
- Returns empty list most nights — non-empty only during active roll windows (quarterly for equity/rates, monthly for energy/metals/grains)
- Fully testable with known dates, no mocking needed

```python
@dataclass
class RollDecision:
    base_symbol: str
    old_contract: str
    new_contract: str
    roll_end: date
```

### `execute_promotion(conn, decision: RollDecision) -> None`
- Atomic transaction:
  1. Lock old contract row (`SELECT ... FOR UPDATE`)
  2. Set `is_front_month = false` on old
  3. Upsert new contract (`ON CONFLICT DO UPDATE`), copy `exchange` from old row
  4. **Volume validation**: query last 3 days of volume for both old and new from `market_data_ohlcv`, log the ratio alongside the promotion. Not used for detection — builds a historical record proving the calendar is correct (or surfacing edge cases where it isn't)
  5. Insert into `roll_events` table (`detection_method="calendar"`, `volume_zscore=NULL`, `is_authoritative=true`, `confirmation_count=NULL`)
- Mirrors current `ContractMetadataWriterAgent._handle_roll_event()` promotion logic
- Idempotent: `is_front_month` is already `false` on old if previously promoted, already `true` on new

### `broadcast_update(producer, decision: RollDecision) -> None`
- Publish `ContractUpdateEvent` to `topic_contract_updates`
- Short-lived Kafka producer: connect, publish, disconnect
- Required because `bar_writer_agent` and `bar_auditor_agent` subscribe to this topic to invalidate in-memory contract caches
- Without this broadcast, those services would map stale contract codes until restart

### Main function

```python
async def main():
    settings = Settings()
    pool = await create_pool(settings.database_url, min_size=1, max_size=2)
    today = datetime.now(UTC).date()

    async with pool.acquire() as conn:
        seeded = await seed_missing_contracts(conn, settings)
        decisions = detect_rolls(today)

        for decision in decisions:
            await execute_promotion(conn, decision)
            producer = KafkaProducerClient(bootstrap_servers=settings.kafka_bootstrap_servers)
            await producer.start()
            await broadcast_update(producer, decision)
            await producer.stop()

    logger.info("roll_batch.complete", decisions=len(decisions), seeded=seeded)
```

### Observability

OTel metrics (same pattern as every other service):
- `roll_batch_runs_total` (counter) — incremented every run
- `roll_batch_promotions_total` (counter) — incremented per promotion
- `roll_batch_seeds_total` (counter) — new contracts seeded
- `roll_batch_errors_total` (counter) — any failure

Structured logs (`structlog`) for detail:
- `roll_batch.run` — start, with today's date
- `roll_batch.roll_detected` — per-symbol, with old→new contract + volume validation ratio
- `roll_batch.promotion_complete` — per-symbol
- `roll_batch.complete` — summary with total decisions, seeded count, and run duration

## Phase 2: Validate + Deploy

1. **Historical backtest**: Run `detect_rolls()` against dates from the last 12 months. Compare output with `roll_events` table entries (detection_method="volume" or "calendar"). Confirm the batch would have promoted the same contracts.
2. **Dry run**: Run the batch script with a `--dry-run` flag that logs promotions but skips DB writes and Kafka publishes. Verify decisions look correct.
3. **Deploy**: Install systemd timer, run once manually to verify `contract_metadata` updates and `ContractUpdateEvent` broadcast received by bar_writer/bar_auditor.
4. **Stop old services**: `sudo systemctl stop && disable indicagent-roll-compute indicagent-contract-metadata-writer`
5. **Monitor**: Check for a few days that bars flow correctly under the new front-month contracts.

## Phase 3: Remove Old References

## Phase 4: Remove Old References

**Systemd:**
- Remove unit files from `/etc/systemd/system/`
- Remove reference unit files from `production/systemd/`
- `sudo systemctl daemon-reload`

**Service Auditor (`services/service_auditor_agent.py`):**
- Remove `"roll_compute_agent"` and `"contract_metadata_writer_agent"` from `_DAG_ORDER`
- Remove their entries from `_LAG_THRESHOLDS`
- Remove their entries from `_AGENT_ID_TO_UNIT`
- Remove `_roll_consumer_loop()`, `_handle_roll_event()`, `_restart_roll_service()`
- Remove `_roll_consumer` initialization in `_setup()`
- Remove `topic_roll_events` from audit subscription list

**Bar Auditor (`services/bar_auditor_agent.py`):**
- Remove `topic_roll_events` from `topics_consumed`
- Remove `_drain_roll_events()` method and all calls
- Remove `RollEvent` import

**Feature Writer (`services/feature_writer_agent.py`):**
- Remove `topic_roll_events` from `topics_consumed`
- Remove roll handler routing logic
- Remove `topic_roll_events` import

**Bar Writer (`services/bar_writer_agent.py`):**
- No changes — keeps `ContractUpdateEvent` subscription for cache invalidation

**Stream keys (`src/core/stream_keys.py`):**
- Remove `topic_roll_events()` and `topic_roll_dlq()`
- Keep `topic_contract_updates()`

**Schemas (`src/core/schemas/market_events.py`):**
- Remove `RollEvent` class
- Keep `ContractUpdateEvent`

**Service utils (`src/core/service_utils.py`):**
- Remove `parse_roll_event()` function and `RollEvent` import

## Phase 4: Archive and Delete Old Code

- Delete `services/roll_compute_agent.py`
- Delete `services/contract_metadata_writer_agent.py`
- Archive `docs/ideas/futures-roll-simplification.md` to `docs/ideas/archive/`
- Remove `roll_compute_` OTel metric definitions
- Remove `contract_writer_` OTel metric definitions
- Update `CLAUDE.md`:
  - Remove roll-compute and contract-metadata-writer from Service DAG (L6)
  - Replace "Roll flow" section with: "Roll batch: nightly systemd timer, `production/scripts/roll_batch.py`. Calendar-driven promotion, no real-time agent."
  - Add to ML batch services section
  - Remove `topic_roll_events` references
- Update `docs/operations/` runbooks if any reference roll-compute restart procedures

## Migration Checklist

- [ ] Implement `roll_batch.py` with four pure functions
- [ ] Add unit tests for `detect_rolls()` with known dates (pure function, trivial to test)
- [ ] Historical backtest: compare `detect_rolls()` output against `roll_events` table for last 12 months
- [ ] Dry run with `--dry-run` flag
- [ ] Install systemd timer + service units
- [ ] Run batch manually, verify `contract_metadata` state and `ContractUpdateEvent` broadcast
- [ ] Stop + disable old services
- [ ] Monitor for a few days
- [ ] Remove old references (Phase 3)
- [ ] Delete old code (Phase 4)

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Calendar date wrong for a symbol | Low | Medium | `get_roll_window()` is already tested and in production use; shadow mode validates |
| Batch fails silently for days | Low | Low | systemd `Persistent=true` retries on next boot; idempotent design means no state corruption |
| Services don't pick up new front-month | Low | Medium | `get_active_contracts()` reads DB at startup; ibkr-provider nightly restart covers it |
| Need to roll back | Low | Low | Old agents disabled, not deleted until Phase 5; re-enable and restart |

## What Gets Removed

| Component | Lines | What Happens |
|-----------|-------|-------------|
| `services/roll_compute_agent.py` | ~594 | Deleted |
| `services/contract_metadata_writer_agent.py` | ~427 | Deleted |
| Roll consumer in service_auditor | ~80 | Removed |
| Roll drain in bar_auditor | ~30 | Removed |
| Roll handler in feature_writer | ~15 | Removed |
| `topic_roll_events` + `topic_roll_dlq` | stream_keys.py | Removed |
| `RollEvent` class | market_events.py | Removed |
| `parse_roll_event()` | service_utils.py | Removed |
| OTel metrics (8 total) | roll_compute + contract_writer | Removed |
| Systemd units (2 daemons) | production/systemd/ | Replaced by 1 timer + 1 oneshot |
| **Total removed** | **~1,300 lines + 2 daemon services** | Replaced by ~100-line script + 2 systemd units |
