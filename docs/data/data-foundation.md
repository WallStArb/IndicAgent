# Data Foundation — Reference Data, Contracts & Roll Architecture

**Version:** 1.0.0
**Last Updated:** 2026-05-29
**Status:** current

---

## Purpose

The WHY and WHAT of IndicAgent's reference data layer: the two-table contract model, how instruments are defined and discovered at runtime, the futures roll lifecycle, and how the data layer stays consistent when contracts expire.

Start here before working on anything that touches `instruments`, `contract_metadata`, provider subscriptions, or `roll_batch.py`.

---

## Two-Table Reference Model

Reference data is split across two tables with different lifetimes and owners.

### `instruments` — Static Templates

Stores the config-time definition of every symbol the system knows about. Think of this as the schema layer: it defines what a symbol *is* (asset class, exchange, tick size, point value, session rules) but not which contract is live.

```
instruments
  symbol           — "ES", "NGM6", "EURUSD", "SPY"
  base             — "ES", "NG", "EURUSD", "SPY"
  contract_details — JSONB: asset_class, exchange, tick_size, point_value,
                            sector, name, session_id, provider_meta
  is_active        — true = eligible for data collection
  expiry           — date (futures only; empty for non-futures)
```

**Who writes it:** Seeded at startup from config (`src/config/settings.py`) and from `roll_batch.py`'s `seed_missing_contracts()`. Updated by the NOTIFY trigger `trg_instruments_notify` when contract details change.

**Key constraint:** Futures base symbols (`NG`, `ES`) live here as templates. The actual front-month contract (`NGN6`, `ESM6`) is resolved at runtime from `contract_metadata`.

### `contract_metadata` — Live State

Tracks which contract is the current front-month and the history of roll promotions. Think of this as the runtime layer: it tells the system which symbol is *active right now*.

```
contract_metadata
  symbol           — "NGN6", "SIM6", "ESM6"
  base_symbol      — "NG", "SI", "ES"
  asset_class      — 'futures'
  exchange         — "NYMEX", "COMEX", "CME"
  is_front_month   — true = this is the live contract (one per base_symbol)
  roll_from        — previous front-month symbol
  roll_to          — next front-month symbol (precomputed by roll_batch)
  roll_date        — when promotion was recorded
  expiry_date      — exchange expiry (populated on promotion)
  first_notice_date
  roll_gap         — price gap at roll (informational)
  roll_direction   — 'up' / 'down' / 'flat' / 'unknown'
  roll_detected_at
  confirmation_count
```

**Who writes it:** `roll_batch.py` exclusively. No service writes directly.

**Key invariant:** Exactly one row per `base_symbol` has `is_front_month = true`. The promotion transaction sets the old contract to `false` and the new to `true` atomically.

### Why Two Tables

`instruments` is append-mostly and config-driven. `contract_metadata` is runtime state that changes on every roll. Mixing them would couple config changes to operational roll promotions. The split also lets non-futures instruments (`EURUSD`, `SPY`) live in `instruments` without needing rows in `contract_metadata` at all.

---

## Contract Lifecycle

How a symbol travels from config to live bar subscription:

```
1. Config definition
   src/config/settings.py → Instrument(symbol="NG", base="NG", exchange="NYMEX", ...)
   (base symbol template, expiry="")

2. DB seed (at startup or roll_batch seed phase)
   roll_batch.seed_missing_contracts() →
     INSERT INTO instruments(symbol="NG", base="NG", ...) ON CONFLICT DO NOTHING
     INSERT INTO contract_metadata(symbol="NGN6", base_symbol="NG", is_front_month=true)
       ON CONFLICT DO NOTHING

3. Runtime resolution
   get_active_contracts(settings) →
     SELECT symbol, base_symbol FROM contract_metadata WHERE is_front_month=true
     JOIN instruments ON base_symbol=base → inherit tick_size, point_value, exchange
     → Instrument(symbol="NGN6", base="NG", tick_size=0.001, point_value=10000, ...)

4. Provider subscription
   IBKRProvider reads get_active_contracts() at startup →
   subscribes to real-time bars for each Instrument →
   publishes to market.bars.raw.ibkr keyed by symbol
```

`get_active_contracts()` is cached for 60 seconds and reads from DB on cache miss. Services read it at startup; the 60-second TTL means contract changes propagate within one minute without restarts.

---

## Roll Architecture

Futures contracts expire on a fixed calendar. When a front-month contract expires, the system must promote the next contract so bars keep flowing under the new symbol.

### Calendar-Driven Detection (`detect_rolls`)

`production/scripts/roll_batch.py` runs nightly at 8pm via systemd timer. The primary detection path is pure calendar arithmetic — no volume heuristics, no streaming state.

```python
detect_rolls(today: date) -> list[RollDecision]
```

For each base symbol in `FUTURES_ROLL_CYCLES`:
1. `get_roll_window(base_symbol, today)` — compute `(roll_start, roll_end)` from expiry date
2. Skip if `today < roll_end` (window hasn't closed yet)
3. `derive_roll_chain(base_symbol)` — get `[current, next, next+1]` contracts
4. Emit `RollDecision(base_symbol, old=chain[0], new=chain[1], roll_end=roll_end)`

The roll window spans `expiry - 14 days` to `expiry - 3 days` (~10 to 2 trading days before expiry). A roll is due when the batch runs inside or after this window.

### Rescue Path (`detect_expired_front_months`)

`detect_rolls` returns `None` when called outside any roll window — before or after. If the system was down during a roll window, or if a contract expired without the nightly batch catching it, the calendar path produces zero decisions indefinitely.

The rescue path handles this:

```python
detect_expired_front_months(conn, today) -> list[RollDecision]
```

1. Query `contract_metadata WHERE is_front_month=true AND asset_class='futures'`
2. Parse expiry date from each symbol suffix (`NGN6` → N=July, 6=2026 → `get_expiry_date("NG", 7, 2026)`)
3. Skip if `today <= computed_expiry`
4. **Liveness guard:** skip if `market_data_ohlcv` has a bar within 28 hours — the contract is still trading regardless of what the formula says (see expiry formula caveat below)
5. Resolve next contract via `roll_to` column, then chain derivation fallback
6. Emit `RollDecision` with a `rescue_expired_front_month` warning log

The 28-hour window (not 24) covers the CME weekend gap: futures close Friday ~20:00 UTC, reopen Sunday ~21:00 UTC. A Saturday-night batch run would otherwise flag live contracts whose last bar was Friday evening.

`run()` merges rescue decisions (higher priority) and calendar decisions, deduplicates by `base_symbol`, then promotes and broadcasts each.

### Expiry Formula Caveat

`get_expiry_date()` in `src/config/contracts.py` computes approximate expiry dates by contract family:

| Family | Rule | Symbols |
|--------|------|---------|
| Quarterly equity/rates | Third Friday of expiry month | ES, NQ, RTY, YM, ZN, ZF, ZB, ZT, VX |
| Monthly energy | 3 biz days before 25th of prior month | CL, NG |
| Monthly metals | 3 biz days before 25th of prior month | GC, SI, HG |
| Grain cycle | Friday closest to 15th of expiry month | ZC, ZS, ZW |

**Known inaccuracy:** The energy/metals formula uses the NG (natural gas) CME rule for all `_ENERGY_METALS_SYMBOLS`. In practice, GC (Gold), SI (Silver), and HG (Copper) expire at a different point (last 3 business days of the delivery month) — the formula computes a date ~5-9 days earlier than actual. This is why the liveness guard exists: the rescue path will compute `today > formula_expiry` for GC/SI/HG while they're still trading, but the 28-hour bar check correctly suppresses the false promotion.

**Consequence:** Do not rely on `get_expiry_date()` alone to decide if a contract is expired. Always combine it with the liveness guard.

### Atomic Promotion (`execute_promotion`)

Each roll is committed in a single transaction:

```sql
BEGIN;
  SELECT ... FROM contract_metadata WHERE symbol=$old FOR UPDATE;  -- row lock
  UPDATE contract_metadata SET is_front_month=false WHERE symbol=$old;
  INSERT INTO contract_metadata (..., is_front_month=true, roll_from=$old)
    ON CONFLICT (symbol) DO UPDATE SET is_front_month=true, roll_from=..., ...;
  INSERT INTO roll_events (detected_at, base_symbol, old_contract, new_contract,
                           detection_method, is_authoritative)
    VALUES (..., 'calendar', true);
COMMIT;
```

Idempotent: if `new_contract` is already `is_front_month=true`, the function returns early without writing.

### Kafka Broadcast (`broadcast_update`)

After DB promotion, `roll_batch.py` publishes a `ContractUpdateEvent` to `topic_contract_updates`. `bar-writer` and `bar-auditor` subscribe to this topic to invalidate in-memory contract caches. Without this, those services would map bars to the stale front-month symbol until restart.

The `get_active_contracts()` 60-second cache also expires naturally, so all other services pick up the new front-month within one minute.

### Roll Cycle Reference

| Asset Class | Cycle | Symbols |
|-------------|-------|---------|
| Equity index | Quarterly: H M U Z | ES NQ RTY YM |
| Interest rates | Quarterly: H M U Z | ZN ZF ZB ZT |
| Volatility | Quarterly: H M U Z | VX |
| Energy | Monthly: all 12 | CL NG |
| Metals | Monthly: all 12 | GC SI HG |
| Grains | 5-month: H K N U Z | ZC ZS ZW |

CME month codes: F=Jan G=Feb H=Mar J=Apr K=May M=Jun N=Jul Q=Aug U=Sep V=Oct X=Nov Z=Dec

---

## `get_active_contracts()` — The Runtime Contract List

This is the single function that bridges reference data to all runtime consumers.

```python
# src/config/settings.py
get_active_contracts(settings: Settings | None = None) -> list[Instrument]
```

**What it does:**
1. Returns cached result if < 60 seconds old (thread-safe under `_settings_lock`)
2. Queries `contract_metadata WHERE is_front_month=true AND asset_class='futures'` — live futures contracts
3. Queries `instruments WHERE is_active=true AND asset_class != 'futures'` — equities, FX
4. Builds `Instrument` objects for each, inheriting `tick_size`, `point_value`, `session_id`, `exchange` from the matching base template in `instruments`
5. Caches result, returns merged list

**Consumers:** `IBKRProvider` (at startup), `roll_batch.py` (seed phase), `IntelligencePipeline` (contract selection), historical backfill scripts.

**Fallback:** On DB error, returns last valid cache. Cold start with no cache returns empty list — services will retry on the next 60-second cycle.

**Important:** `get_active_contracts()` is a module-level function, not a method on `Settings`. Call as `get_active_contracts(settings)`, never `settings.get_active_contracts()`.

---

## Gap-Fill Loop

When bars are missing (provider outage, contract expiry, weekend recovery), the bar auditor detects and requests backfill automatically:

```
BarAuditor
  → detects gap in market_data_ohlcv (symbol, timeframe, time range)
  → publishes BarGapRequest to market.events.gap_requests

IBKRProvider
  → subscribes to market.events.gap_requests
  → calls reqHistoricalData for (symbol, start_ts, end_ts)
  → publishes bars to market.bars.raw.ibkr
  → BarWriter persists to market_data_ohlcv
```

Gaps are detected on both 1m and HTF timeframes. HTF gaps are inferred from missing 1m source bars. The loop is self-terminating: once the gap is filled, the auditor stops emitting requests for that range.

**After a contract roll:** the new front-month has no bar history in `market_data_ohlcv`. The bar auditor will detect the gap on the first bar arrival and trigger backfill for the prior trading session automatically.

---

## Adding a New Data Source

IndicAgent's provider layer is source-neutral. To wire in a new data source:

1. **Implement `BaseProvider`** (`src/providers/base_provider_agent.py`) — the abstract contract for all providers
2. **Normalize via `bar_normalizer.py`** — convert native format to canonical `BarMessage` schema; define a new `SOURCE_*` constant
3. **Publish to `market.bars.raw.<name>`** — build the topic key via `stream_keys.py`
4. **Register in `settings.provider_raw_topics`** — `ProviderMerger` subscribes to all configured raw topics
5. **Configure routing** — `settings.provider_routing_config` maps `asset_class → authoritative_provider`; the new source can be authoritative for a subset of asset classes while IBKR remains authoritative for others

`ProviderMerger` handles failover automatically per-symbol: if the authoritative provider goes silent, a secondary is promoted. When the primary resumes, the promotion is cleared.

---

## Observability

### Roll Batch Metrics (OTel)

| Metric | Type | Meaning |
|--------|------|---------|
| `roll_batch_runs_total` | counter | Incremented every nightly run |
| `roll_batch_promotions_total` | counter | Contracts promoted |
| `roll_batch_seeds_total` | counter | New contracts seeded into contract_metadata |
| `roll_batch_errors_total` | counter | Failures |
| `job_completed_total{job="roll-batch", status}` | counter | Oneshot exit status; `status=failure` → alert |

### Diagnosing a Missed Roll

```bash
# 1. Check which contracts are marked front-month
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT symbol, base_symbol, is_front_month, roll_to FROM contract_metadata \
   WHERE is_front_month=true ORDER BY base_symbol;"

# 2. Check bar recency for a suspect symbol (e.g. NGM6)
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT symbol, MAX(timestamp) as latest FROM market_data_ohlcv \
   WHERE symbol='NGM6' GROUP BY symbol;"

# 3. Run rescue dry-run to see what roll_batch would do
.venv/bin/python production/scripts/roll_batch.py --dry-run

# 4. Manual promotion (if roll_batch can't run)
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "
  BEGIN;
  UPDATE contract_metadata SET is_front_month=false WHERE symbol='NGM6';
  UPDATE contract_metadata SET is_front_month=true  WHERE symbol='NGN6';
  COMMIT;"

# 5. Restart provider to pick up new front-month
sudo systemctl restart indicagent-ibkr-provider.service
```

### Roll Batch Timer

```bash
# Verify timer is active
systemctl list-timers --all | grep roll-batch

# Check last run
journalctl -u indicagent-roll-batch.service -n 30 --no-pager
```

---

## Key Files

| File | Role |
|------|------|
| `src/config/settings.py` | `get_active_contracts()` — runtime contract resolution with 60s cache |
| `src/config/contracts.py` | `FUTURES_ROLL_CYCLES`, `derive_roll_chain()`, `get_expiry_date()`, `get_roll_window()` |
| `production/scripts/roll_batch.py` | Nightly roll promotion: `detect_rolls()`, `detect_expired_front_months()`, `execute_promotion()`, `broadcast_update()` |
| `src/core/schemas/market_events.py` | `ContractUpdateEvent` — Kafka payload for roll broadcasts |
| `src/core/stream_keys.py` | `topic_contract_updates()` — roll broadcast topic |
| `services/bar_auditor.py` | Gap detection + BarGapRequest emission |
| `services/ibkr_provider.py` | Gap-fill subscriber; re-subscribes on roll via `get_active_contracts()` |

---

## See Also

- **Bar flow:** `data-provider.md` — provider isolation, failover, IBKR dual streams, bar normalization
- **Hot/warm/cold tiers:** `data-pipeline.md` — Redpanda topics, processing services, TimescaleDB writers
- **Intelligence layer:** `docs/intelligence/intelligence-foundation.md` — how bar data feeds I1-I8
- **DAG topology:** `docs/architecture/dag-topology.md` — full service graph including roll-batch timer
