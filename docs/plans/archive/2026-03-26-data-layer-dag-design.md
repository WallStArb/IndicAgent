# Data Layer DAG — Phase 53 Design

**Status:** Design approved
**Date:** 2026-03-26
**Milestone:** v2.1 (Phase 53)
**Supersedes:** `gap_fill_service` (retired), `BarAccumulator` in `feature_compute_agent` (extracted)

---

## Problem

The current data layer has three SOC violations that create fragility, untestability, and a blocked refactor:

1. **`feature_compute_agent` writes to DB in the hot compute path** — `_ohlcv_buffer` batch-flushes 1m bars to `market_data_ohlcv` mid-intelligence-pipeline. The ongoing DB-ignorant refactor (Phase 52) removes this, creating a gap: nothing writes raw bars to the DB.

2. **`BarAccumulator` (1m→HTF aggregation) lives inside the intelligence layer** — bar aggregation is a data concern, not an intelligence concern. `feature_compute_agent` should consume bars, not produce them.

3. **`RollMonitor` (volume z-score detection) lives inside `DataProviderAgent`** — analytical logic embedded in infrastructure. Untestable without a live IBKR connection. Roll events are not first-class typed events, so the ML layer cannot segment around roll periods.

---

## Renaissance Design Principles Applied

- **Single job per node** — every agent has one invariant responsibility
- **DB-ignorant compute** — Layers 0–1 never touch the database
- **Canonical data as source guarantee** — the provider guarantees completeness, not the consumer
- **Typed events only** — no dicts on the wire between agents
- **Self-healing** — the system detects and fills gaps automatically, zero manual steps
- **Instrument everything** — Golden Signals on every agent at birth, not retrofitted
- **Never drop data** — raw bars are ground truth; persisted independently of derived features

---

## Canonical Bar Guarantee

The pipeline guarantees a complete, gapless bar series for every active symbol across all timeframes. This is enforced at the **source**, not patched downstream:

**`DataProviderAgent` owns the canonical 1440 1m bar grid:**
- If no 5s tick data arrives for a minute → emits flat bar (`prev_close`, `volume=0`) to `market.bars`
- Every active symbol always has exactly 1440 1m bars/day for 24/7 markets (crypto, FX)
- RTH-gated markets (equity futures, commodities) emit flat bars during off-hours preserving the grid

**`BarAggregatorComputeAgent` produces canonical HTF from guaranteed 1m:**
- Because flat 1m bars flow continuously, every 5m/15m/1h/4h/1d period closes with an entry
- No HTF gaps possible in real-time — completeness is inherited from the 1m guarantee
- `is_flat_bar=True` flag propagates through so downstream agents can gate on it

**`BarAuditorAgent` audits historical gaps only:**
- Real-time canonical completeness is already guaranteed upstream
- Audits `market_data_ohlcv` on startup and periodically for historical gaps (new symbol onboarding, post-restart catch-up, pre-BarWriterAgent era data)
- Self-healing: publishes gap requests → DataProviderAgent fetches historical → BarWriterAgent persists

---

## DAG Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 0 — Data Provider                                     │
│                                                             │
│  DataProviderAgent (tws_daemon renamed)          :9100      │
│    in:  IBKR TWS (5s RTBs + official 1m bars)              │
│    in:  market.events.gap_requests  (gap fill demand)       │
│    out: market.bars  (1m, canonical 1440/day, flat bars)    │
│    out: market.ticks                                        │
└─────────────────────────────────────────────────────────────┘
                          │ market.bars
          ┌───────────────┴───────────────┐
          ▼                               ▼
┌─────────────────────┐   ┌──────────────────────────────────┐
│ Layer 1 — Processing │   │ Layer 1 — Processing             │
│ (DB-ignorant)        │   │ (DB-ignorant)                    │
│                      │   │                                  │
│ BarAggregatorComputeAgent   │   │ RollComputeAgent               │
│   :9120              │   │   :9122                          │
│ in:  market.bars     │   │ in:  market.bars                 │
│ out: market.bars.htf │   │ out: market.events.roll          │
│                      │   │                                  │
│ - BarAccumulator     │   │ - Volume z-score                 │
│ - Session-aware      │   │ - Calendar confirmation          │
│ - Canonical HTF      │   │ - Typed RollEvent schema         │
│ - is_flat_bar flag   │   │                                  │
└─────────────────────┘   └──────────────────────────────────┘
          │ market.bars.htf                │ market.events.roll
          ▼                               │ (consumed by Layer 3+:
┌─────────────────────────────────────────┼───────────────────┐
│ Layer 2 — Persistence                   │ signal_generator, │
│                                         │ future ML layer)  │
│                                                             │
│  BarWriterAgent                                  :9121      │
│    in:  market.bars (1m) + market.bars.htf (5m–1d)         │
│    out: market_data_ohlcv  (canonical bar store)            │
│    strategy: ON CONFLICT (ts, symbol, tf) DO NOTHING        │
│    source: "live_1m" | "live_htf"                           │
│                                                             │
│  BarAuditorAgent                            :9123      │
│    reads:   market_data_ohlcv (actual counts vs expected)   │
│    out:     market.events.gap_requests                      │
│    schedule: startup + every 5min market hours              │
│    retires:  gap_fill_service                               │
└─────────────────────────────────────────────────────────────┘
          │ market.bars.htf
          ▼
┌─────────────────────────────────────────────────────────────┐
│ Layer 3 — Intelligence (unchanged consumers)                │
│                                                             │
│  feature_compute_agent  pure I1-I6, no DB writes, no        │
│                         BarAccumulator (extracted to L1)    │
│  signal_generator       unchanged                           │
│  ...                                                        │
└─────────────────────────────────────────────────────────────┘
```

---

## Agent Specifications

### DataProviderAgent (rename of tws_daemon)

**File:** `services/data_provider_agent.py`
**Class:** `DataProviderAgent`
**Systemd:** `indicagent-data-provider.service`
**Metrics:** `:9100` (existing port, unchanged)
**Phase:** 53.3

**Responsibilities:**
- IBKR TWS connection (5s RTBs + official 1m reconciliation)
- Canonical 1440 1m bar grid enforcement (flat bars for empty minutes)
- Publishes `market.bars` + `market.ticks`
- Subscribes to `market.events.gap_requests` → fetches historical bars → re-publishes to `market.bars`

**Extracted in this phase:** `RollMonitor` class removed entirely (→ `RollComputeAgent`)

**Key invariant:** Always emits exactly one 1m bar per minute per active symbol. Never skips a minute.

---

### BarAggregatorComputeAgent

**File:** `services/bar_aggregator_agent.py`
**Class:** `BarAggregatorComputeAgent(BaseAgent)`
**Systemd:** `indicagent-bar-aggregator-compute.service`
**Metrics:** `:9120`
**Phase:** 53.2

**Responsibilities:**
- Consume `market.bars` (1m)
- Aggregate 1m → HTF via `BarAccumulator` (extracted from `feature_compute_agent`)
- Publish `market.bars.htf` (5m, 15m, 1h, 4h, 1d)
- Session-aware period emission (RTH boundaries, no cross-session contamination)
- `is_flat_bar` flag propagated from 1m bars through HTF output

**Cold start:** `auto.offset.reset=latest`. If restart mid-period, partial bar is acceptable — period closes cleanly on next boundary. No DB access needed.

**Extracted from:** `feature_compute_agent._bar_accumulator` + `_publish_htf_bar()`

**Golden Signals:**
- Traffic: `events_consumed_total`, `htf_bars_produced_total{tf}`
- Latency: `bar_aggregation_latency_seconds`
- Errors: `aggregation_errors_total`
- Saturation: `consumer_lag`

---

### BarWriterAgent

**File:** `services/bar_writer_agent.py`
**Class:** `BarWriterAgent(BaseAgent)`
**Systemd:** `indicagent-bar-writer.service`
**Metrics:** `:9121`
**Phase:** 53.1 ← **first, unblocks Phase 52 DB-ignorant refactor**

**Responsibilities:**
- Consume `market.bars` (1m) + `market.bars.htf` (5m–1d)
- Batch-write to `market_data_ohlcv`
- UPSERT strategy: `ON CONFLICT (timestamp, symbol, timeframe) DO NOTHING` — first write wins
- Set `source` column: `"live_1m"` for 1m bars, `"live_htf"` for aggregated
- Idempotent on restart — Kafka offset replay re-processes with no duplicates

**This agent is the missing piece** that unblocks removing `_ohlcv_buffer` from `feature_compute_agent`.

**Golden Signals:**
- Traffic: `events_consumed_total`, `bars_written_total{tf}`
- Latency: `persistence_batch_latency_seconds`
- Errors: `write_errors_total`, `conflict_skips_total`
- Saturation: `persistence_consumer_lag`

---

### RollComputeAgent

**File:** `services/roll_compute_agent.py`
**Class:** `RollComputeAgent(BaseAgent)`
**Systemd:** `indicagent-roll-compute.service`
**Metrics:** `:9122`
**Phase:** 53.3 (same phase as DataProviderAgent cleanup)

**Responsibilities:**
- Consume `market.bars`
- Volume z-score + calendar confirmation (extracted `RollMonitor` logic)
- Publish typed `RollEvent` to `market.events.roll`

**RollEvent schema** (`src/core/schemas/market_events.py`):
```python
class RollEvent(BaseModel):
    symbol: str            # base symbol (ES, CL)
    old_contract: str      # ESH6
    new_contract: str      # ESM6
    roll_gap_price: float
    roll_gap_pct: float    # signed: positive=contango, negative=backwardation
    detection_ts: datetime
    volume_zscore: float   # confirmation strength — ML feature
    confirmation_count: int
```

**Enables Phase 50** (ROLL_MONITOR_ENABLED graduation) — once this agent is running and validated, enable the flag.

**Golden Signals:**
- Traffic: `events_consumed_total`, `rolls_detected_total`
- Latency: `detection_latency_seconds`
- Errors: `detection_errors_total`
- Saturation: `consumer_lag`

---

### BarAuditorAgent

**File:** `services/bar_auditor_agent.py`
**Class:** `BarAuditorAgent(BaseAgent)`
**Systemd:** `indicagent-bar-auditor.service`
**Metrics:** `:9123`
**Phase:** 53.1 (alongside BarWriterAgent)

**Responsibilities:**
- On startup: audit `market_data_ohlcv` for historical gaps vs expected canonical counts
- Every 5 minutes during market hours: re-audit active symbols
- Expected counts by instrument type:
  - Crypto (BTC, ETH): 1440 1m/day, 7 days/week
  - FX (EUR, GBP, JPY, CHF): 1440 1m/day, Sun–Fri
  - Equity futures (ES, NQ, RTY, YM): ~390 1m/RTH session, Mon–Fri
  - Commodities (CL, GC, SI): session-dependent per instrument spec
- Publish `BarGapRequest` events to `market.events.gap_requests`
- `DataProviderAgent` consumes, fetches historical bars, re-publishes to `market.bars`
- `BarWriterAgent` persists → next audit cycle confirms filled

**Retires:** `gap_fill_service` (decommission in Phase 53.1)

**Instrument metadata source:** `get_active_contracts()` from `src/config/settings.py`

**Golden Signals:**
- Traffic: `audits_run_total`, `gap_requests_published_total`
- Latency: `audit_duration_seconds`
- Errors: `audit_errors_total`
- Saturation: `canonical_completeness_pct{symbol,tf}` ← key operational metric

---

## Self-Healing Loop

```
BarAuditorAgent detects gap in market_data_ohlcv
  → publishes BarGapRequest{symbol, tf, start_ts, end_ts}
  → DataProviderAgent fetches historical bars from IBKR
  → publishes to market.bars (same topic as live)
  → BarWriterAgent persists (ON CONFLICT DO NOTHING)
  → next BarAuditorAgent audit cycle confirms gap filled
```

Zero manual steps. No scripts. No human in the loop.

---

## Implementation Phases

| Phase | Agent | Dependency | Value |
|-------|-------|-----------|-------|
| **53.1** | `BarWriterAgent` + `BarAuditorAgent` | Phase 52 (DB-ignorant feature_compute) | Unblocks Phase 52 completion; retires gap_fill_service |
| **53.2** | `BarAggregatorComputeAgent` | 53.1 (BarWriterAgent running) | Extracts BarAccumulator from intelligence layer; feature_compute becomes pure |
| **53.3** | `RollComputeAgent` + `DataProviderAgent` rename | 53.2 (BarAggregatorComputeAgent running) | Extracts RollMonitor from provider; typed RollEvent schema; clean DataProviderAgent |
| **50** | Enable `ROLL_MONITOR_ENABLED` | 53.3 (RollComputeAgent validated) | Graduates roll monitor from shadow; enables roll_premium_pct population |

---

## What Gets Retired

| Current | Replaced by | Phase |
|---------|-------------|-------|
| `feature_compute_agent._ohlcv_buffer` + `_flush_ohlcv()` | `BarWriterAgent` | 53.1 |
| `feature_compute_agent._bar_accumulator` + `_publish_htf_bar()` | `BarAggregatorComputeAgent` | 53.2 |
| `gap_fill_service` | `BarAuditorAgent` | 53.1 |
| `tws_daemon.RollMonitor` class | `RollComputeAgent` | 53.3 |
| `tws_daemon.py` filename/class | `data_provider_agent.py` / `DataProviderAgent` | 53.3 |

---

## Metrics Port Registry (updated)

| Agent | Port |
|-------|------|
| DataProviderAgent (tws_daemon) | :9100 (existing) |
| FeatureComputeAgent | :9125 (existing) |
| BarAggregatorComputeAgent | :9120 |
| BarWriterAgent | :9121 |
| RollComputeAgent | :9122 |
| BarAuditorAgent | :9123 |
