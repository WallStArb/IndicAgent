# Phase 38: Automated Futures Roll Detection - Context

**Gathered:** 2026-03-17
**Status:** Ready for planning
**Source:** PRD Express Path (docs/plans/2026-03-17-automated-roll-detection-design.md)

<domain>
## Phase Boundary

Automated detection of futures contract rolls via volume-based statistical analysis. When volume shifts from the current front-month contract to the next contract in the roll chain, the system detects this without manual intervention and propagates the roll event through the pipeline — updating subscriptions, migrating plugin state, and recording boundary markers — all without a service restart.

Applies only to `AssetClass.FUTURES`. ETFs, FX, and Crypto use `Settings().contracts` directly and are excluded.

</domain>

<decisions>
## Implementation Decisions

### DB Foundation (ROLL-02)
- Migration 037 adds to `contract_metadata`: `is_front_month BOOLEAN DEFAULT false`, `roll_gap DOUBLE PRECISION`, `roll_direction VARCHAR(10) DEFAULT 'unknown'`, `roll_detected_at TIMESTAMPTZ DEFAULT NOW()`, `confirmation_count INTEGER DEFAULT 0`
- New `system_events` table: `id BIGSERIAL PRIMARY KEY`, `event_type VARCHAR(50)`, `base_symbol VARCHAR(10)`, `old_symbol VARCHAR(10)`, `new_symbol VARCHAR(10)`, `roll_gap DOUBLE PRECISION`, `roll_direction VARCHAR(10)`, `detected_at TIMESTAMPTZ DEFAULT NOW()`, `event_data JSONB DEFAULT '{}'`
- Index: `idx_contract_meta_front_month ON contract_metadata (base_symbol, is_front_month)`
- Index: `idx_system_events_base_detected ON system_events (base_symbol, detected_at DESC)`
- File: `production/migrations/037_roll_monitor_integration.sql`

### Roll Chain Derivation (ROLL-01)
- New file: `src/config/contracts.py`
- Function: `derive_roll_chain(base_symbol: str) -> list[ContractMetadata]`
- Month codes: H=03, M=06, U=09, Z=12 (quarterly), F=01, G=04, J=05, K=05, N=07, Q=08, V=10, X=11
- Returns 3-contract chain sorted chronologically with `roll_from`/`roll_to` linkage
- Uses IBKR expiry code format: `ES` + month_code + 2-digit year (e.g. `ESM6`)

### Stream Key (ROLL-02)
- Add `topic_system_events()` to `src/core/stream_keys.py`
- Pattern follows existing `topic_indicators()`, `topic_signals_aggregated()` etc.
- Topic name: `{env_prefix}.system.events` (dots not colons per naming standard)

### DB-Backed Active Contracts (ROLL-03)
- Modify `Settings.get_active_contracts()` in `src/config/settings.py`
- Queries `contract_metadata WHERE is_front_month=true`
- 60-second in-memory cache (`_active_contracts_cache`, `_active_contracts_last_refresh`)
- Fallback to config-file contracts on DB error (graceful degradation)
- Returns `list[Instrument]` for TWS subscription compatibility

### Roll Detection Engine (ROLL-04)
- `services/tws_daemon.py` extended with `RollMonitor` or inline class
- 100-bar rolling window per base symbol (configurable via `ROLL_MONITOR_WINDOW_SIZE=100`)
- Volume ratio = `volume(next_contract) / volume(current_contract)`
- Z-score = `(volume_next - rolling_mean) / rolling_std` (guard: rolling_std > 0)
- **Segmented thresholds** (Renaissance: Segment Relentlessly):
  - ES, NQ, RTY, YM: `1.2` (high liquidity, sharp transitions)
  - CL, GC, SI, HG: `1.5` (energy/metals, gradual shifts)
  - ZN, ZF, ZB, ZT: `1.4` (rates products, moderate liquidity)
  - Default: `1.2` (configurable via `ROLL_MONITOR_THRESHOLD_DEFAULT=1.2`)
  - Per-symbol override: `ROLL_THRESHOLDS_ES=1.3` etc.
- **Confirmation window**: 3 consecutive detections before commit (`ROLL_CONFIRMATION_BARS=3`)
- **Cooldown**: 30 minutes minimum between rolls per base symbol (`ROLL_MONITOR_COOLDOWN_MIN=30`)
- **Time-of-day gating** (`ROLL_TIME_OF_DAY_GATED=true`):
  - Pre-open (9–11 ET): `threshold *= 1.3`
  - Close (15 ET): `threshold *= 0.9`
  - Post-close (16–18 ET): skip detection
  - RTH (standard hours): base threshold
- **Feature flag**: `ROLL_MONITOR_ENABLED=false` default (shadow mode — system unchanged until explicitly enabled)
- On confirmed roll: atomic `contract_metadata` UPDATE (toggle `is_front_month`), INSERT into `system_events`, publish to `development.system.events` Kafka topic
- Post-roll monitoring: continue polling old contract for `ROLL_MONITOR_POSTROLL_BARS=10` bars
- Deactivate after post-roll period: unsubscribe IBKR, remove from polling loop

### Pipeline Integration (ROLL-05)
- All downstream services consume `development.system.events` Kafka topic:
  - `indicator_service.py`: plugin state migration on roll
  - `market_analysis_service.py`: update active symbol list
  - `signal_generator_service.py`: update active symbol list, track post-roll performance
  - `feature_writer_service.py`: write roll boundary marker to `intelligence_features`
- **Plugin state migration** (`indicator_service.py`):
  - Price-sensitive plugins (bollinger_bands, keltner_channel, donchian_channel): adjust price levels by `roll_gap`
  - Volume-neutral plugins: copy verbatim
  - Snapshot captured from old symbol before migration
  - New symbol state applied before first new bar processed
- **Roll boundary marker** (`feature_writer_service.py`):
  - `INSERT INTO intelligence_features (ts, symbol, tf, i7) VALUES (NOW(), base_symbol, '1m', '{"roll_boundary":"ESM6->ESU6"}'::jsonb) ON CONFLICT DO UPDATE SET i7 = i7 || ...`

### Backfill Seeding (ROLL-06)
- `production/scripts/historical_backfill.py` extended with `--seed-roll-chain` flag
- Populates `contract_metadata` with 3-contract roll chain per active futures base symbol
- Sets `is_front_month=true` for current front-month contract

### Paper Account Handling
- Detect paper account: `ib_host in ("192.168.1.157", "127.0.0.1")`
- Skip roll monitoring for unavailable contracts: BZJ6, NGJ6, SR1H6, ZWH6
- Log warning when paper account detected and contract skipped

### Roll Event Delivery: Kafka (not DB polling)
- Roll events go to Kafka `system_events` topic for low-latency propagation
- DB update is source of truth; Kafka is notification mechanism
- All services maintain their own local symbol set, updated on receipt of roll event

### Plugin State Sync Timing
- Snapshot captured at roll event receipt (before any new bars for new symbol)
- State applied immediately; warmup flag emitted in next intelligence event

### Roll Back Triggering: Automatic
- 3-bar confirmation window is the primary protection
- After commit, verify over next 10 bars; if volume shifts back AND gap sign is wrong, revert `is_front_month` and re-publish corrective event

### Shadow Mode Semantics
- `ROLL_MONITOR_ENABLED=false`: detection disabled entirely — no volume tracking, no events, no DB writes
- All existing behavior preserved; manual contract updates via Settings still work

### Claude's Discretion
- Exact method names and class structure within tws_daemon (RollMonitor class vs inline methods)
- Error handling for IBKR subscription failures during roll transition
- Prometheus metrics names for roll events (follow existing pattern in `src/observability/metrics.py`)
- Whether to persist roll chain in DB or always derive on startup

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Core Architecture
- `src/core/stream_keys.py` — All stream key construction patterns; `topic_system_events()` must follow this
- `src/core/models.py` — `ContractMetadata` model to be added; existing model patterns
- `src/config/settings.py` — `Settings` class, `get_active_contracts()`, `Instrument` definition
- `CLAUDE.md` — Stream key naming standard (dots not colons), UTC timestamp rules, service patterns

### Existing Services to Modify
- `services/tws_daemon.py` — Current bar polling infrastructure, IBKR subscription cap (80 total)
- `services/indicator_service.py` — Plugin state structure, `_i1_plugin_states`, `TIER_I1`
- `services/market_analysis_service.py` — Active symbol consumption pattern
- `services/signal_generator_service.py` — Active symbol consumption, post-roll tracking
- `services/feature_writer_service.py` — `intelligence_features` write pattern

### Database
- `production/migrations/036_per_contract_futures_storage.sql` — Existing `contract_metadata` schema (must read before writing 037)
- `src/core/database_manager.py` — Connection pool and transaction patterns

### Test Patterns
- `tests/unit/` — `ServiceClass.__new__(ServiceClass)` pattern for service tests
- `CLAUDE.md` section "Service test `__new__` pattern" — Manual attribute setup required

### Design Document
- `docs/plans/2026-03-17-automated-roll-detection-design.md` — Full architecture, roll algorithm, Renaissance enhancements

</canonical_refs>

<specifics>
## Specific Requirements

### Configuration Environment Variables (all in Settings)
| Variable | Default | Description |
|----------|---------|-------------|
| `ROLL_MONITOR_ENABLED` | `false` | Feature flag (shadow mode default) |
| `ROLL_MONITOR_WINDOW_SIZE` | `100` | Rolling window bars |
| `ROLL_MONITOR_THRESHOLD_DEFAULT` | `1.2` | Default volume ratio threshold |
| `ROLL_MONITOR_POSTROLL_BARS` | `10` | Post-roll monitoring bars |
| `ROLL_MONITOR_COOLDOWN_MIN` | `30` | Min minutes between rolls |
| `ROLL_CONFIRMATION_BARS` | `3` | Consecutive bars required before commit |
| `ROLL_TIME_OF_DAY_GATED` | `true` | RTH-only detection gating |

### Unit Tests Required (per design doc)
1. `test_roll_chain_derivation.py` — month code ordering, edge cases
2. `test_roll_detection_algorithm.py` — volume ratio, z-score, thresholds, segmented thresholds
3. `test_service_contract_resolution.py` — DB-backed contracts, cache behavior, fallback
4. `test_plugin_state_migration.py` — state transfer accuracy, roll gap adjustments
5. `test_time_of_day_gating.py` — session-aware detection
6. `test_roll_kafka_events.py` — roll event publishing and consumption

### Verification Steps (from design doc)
1. With `ROLL_MONITOR_ENABLED=false`: no `system_events` rows after normal run
2. With `ROLL_MONITOR_ENABLED=true` + simulated volume shift: "Roll detected" in logs, `is_front_month` toggles after 3 bars
3. Roll boundary marker in `intelligence_features.i7` at roll timestamp
4. Plugin state continuity: price-sensitive plugins adjusted by `roll_gap`, volume-neutral copied

</specifics>

<deferred>
## Deferred Ideas

Per the design doc "Renaissance Iteration" note: basic system with outcome tracking ships in v1.9; segmented thresholds are included. The following are explicitly deferred to v2.0:

- **Roll prediction / pre-warming** (materialized view `roll_prediction`, 5-day pre-warm) — needs historical roll data accumulation first
- **Roll outcome tracking JSONB** (`slippage_bps`, `timeliness`, `detection_latency_sec`) — designed but not in v1.9 scope
- **Roll premium/discount feature** (front/back month spread as contango/backwardation signal) — requires back-month IBKR subscription

</deferred>

---

*Phase: 038-automated-futures-roll-detection*
*Context gathered: 2026-03-17 via PRD Express Path*
