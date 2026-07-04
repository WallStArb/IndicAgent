# Multi-Provider Data Architecture

**Date:** 2026-03-28
**Status:** Design / Brainstorm — not scheduled
**Area:** Data Layer — Provider Abstraction
**Related todo:** `.planning/todos/pending/012-broker-agnostic-instrument-provider-meta.md`

---

## Context

IndicAgent currently uses IBKR as its only data source. The platform is designed to be
provider-neutral — canonical instrument symbols, stream keys, and DB schema have no
broker-specific assumptions. The current coupling is shallow and intentional: IBKR is
the only provider, so IBKR quirks live in `src/providers/ibkr.py` and
`Instrument.provider_meta`. This design doc captures the target multi-provider
architecture so future work doesn't paint the system into a corner.

---

## Target Providers

| Provider | Asset Classes | Protocol |
|----------|--------------|----------|
| **IBKR** | Futures, equities, FX, crypto | ib_insync |
| **Alpaca** | Equities, crypto (no futures) | WebSocket + REST |
| **TastyTrade** | Futures, equities, options | Streamer API |
| **TradeStation** | Futures, equities | REST + streaming |
| **Schwab/ToS** | Equities, futures, options | REST API |

---

## Renaissance Framing

Medallion's edge wasn't the models — it was **data as infrastructure**. Every alpha
source normalized to the same schema, every feed instrumented identically, every
anomaly measurable. Jim Simons wouldn't tolerate five copies of reconnect logic any
more than he'd tolerate five copies of a risk model.

The question isn't "one agent or many" — it's **what changes per provider vs. what
is universal**.

### What changes per provider

- Authentication (API keys, OAuth, ib_insync handshake)
- Wire protocol (WebSocket, REST polling, FIX, ib_insync callbacks)
- Raw message format → `BarMessage` translation
- Symbol qualification (`provider_meta["ibkr"]`, `/VX` prefix, `@` prefix)
- Subscription API (subscribe by symbol list, contract object, stream ID)

### What is universal (must never be duplicated)

- `BaseAgent` lifecycle — SIGTERM drain, startup, shutdown
- Golden Signals metrics — traffic, latency, errors, saturation
- Reconnect with exponential backoff
- Heartbeat publishing
- `BarMessage` normalization (UTC timestamps, canonical symbol, field validation)
- Gap detection + DLQ on unprocessable payloads
- Consumer group management

That's ~80% of the code. Duplicating it across five agents is copy-paste architecture
— not modularity. Every bug in reconnect logic would need to be fixed in five places.
That's a data integrity risk, not just a maintenance cost.

**The adapter is commodity. The agent infrastructure is the moat.**

---

## Design Principles

- **Adapter pattern over agent proliferation.** One `DataProviderAgent` class, N
  deployed instances. All lifecycle, metrics, reconnect, and normalization live in
  the agent once. Only the wire protocol translation changes per provider.
- **`market.bars` is the single canonical feed.** Everything downstream
  (BarAggregatorComputeAgent, FeatureCompute, SignalGenerator) consumes `market.bars`
  and never changes regardless of how many providers are active.
- **Systemd units are the control plane.** Enable/disable providers by enabling/disabling
  units — no env switches, no code changes.
- **No code changes to add a new provider.** New adapter + new unit file. That's it.

---

## Architecture Decision

| Approach | Code reuse | Multi-provider | Maintenance | Renaissance? |
|----------|-----------|----------------|-------------|--------------|
| One agent per broker | Low (80% dup) | Yes (multiple units) | High (N places to fix bugs) | No |
| **Single agent + injected adapter** | **High** | **Yes (multiple units, one class)** | **Low (one place)** | **Yes** |
| Single agent, one provider | High | No | Low | No |

---

## Current State (Single Provider)

```
DataProviderAgent(IBKRAdapter) ──► market.bars ──► BarAggregatorComputeAgent ──► ...
```

`DataProviderAgent` holds a `DataProviderAdapter` instance loaded at startup via
`INDICAGENT_PROVIDER=ibkr|alpaca|tastytrade`. One agent class, N deployable instances.
All lifecycle, metrics, reconnect, and normalization live in the agent once.
The adapter is pure protocol translation.

```
DataProviderAgent(IBKRAdapter)   → indicagent-ibkr-provider.service   → market.bars
DataProviderAgent(AlpacaAdapter) → indicagent-alpaca-provider.service → market.bars
DataProviderAgent(TTAdapter)     → indicagent-tt-provider.service     → market.bars
```

### DataProviderAdapter Protocol

```python
# src/providers/base.py
class DataProviderAdapter(Protocol):
    async def connect(self) -> None: ...
    async def subscribe(self, instruments: list[Instrument]) -> None: ...
    async def stream(self) -> AsyncIterator[RawBar]: ...
    async def qualify(self, instrument: Instrument) -> Instrument: ...
    async def disconnect(self) -> None: ...
```

### Instrument schema

Provider-specific symbol quirks nested under broker key — canonical layer stays clean:

```python
Instrument(
    symbol="VXJ6",   # canonical — stream keys, DB, dashboard
    base="VX",       # exchange convention
    provider_meta={
        "ibkr":        {"symbol": "VIX", "trading_class": "VX"},
        "tastytrade":  {"symbol": "/VX"},
        "tradestation":{"symbol": "@VX"},
    }
)
```

Each adapter reads only its own key, falling back to `instrument.base`.

---

## Case 1: Complementary Coverage (Near-Term)

IBKR for futures, Alpaca for equities/crypto — **no instrument overlap**.

```
DataProviderAgent(IBKRAdapter)   ──► market.bars   (ES, NQ, VX, GC, ...)
DataProviderAgent(AlpacaAdapter) ──► market.bars   (SPY, QQQ, BTC, ...)
```

Both agents publish to the same `market.bars` topic. No deduplication needed —
different instruments, no conflict. This works with the current architecture
as-is once the adapter pattern is in place.

**Naming (per CLAUDE.md conventions):**

| Layer | IBKR | Alpaca |
|-------|------|--------|
| Adapter | `src/providers/ibkr.py` | `src/providers/alpaca.py` |
| Agent file | `services/ibkr_provider_agent.py` | `services/alpaca_provider_agent.py` |
| Agent class | `IBKRProviderAgent` | `AlpacaProviderAgent` |
| Systemd unit | `indicagent-ibkr-provider.service` | `indicagent-alpaca-provider.service` |

Current `data_provider_agent.py` → `ibkr_provider_agent.py` as part of this migration.

---

## Case 2 & 3: Redundancy / Cross-Validation (Future State)

When two providers cover the **same instruments** simultaneously — either for failover
(IBKR down → Alpaca promotes) or cross-validation (price divergence as a quality signal)
— a merge/arbitration layer is required between raw provider output and the canonical
`market.bars` topic.

### The ProviderMergerAgent

Applying the same **Convergence Gate** pattern already used in the persistence DAG
(StreamMerger joining tiered intelligence streams before DB write):

```
IBKRProviderAgent      ──► market.bars.raw.ibkr       ──┐
AlpacaProviderAgent    ──► market.bars.raw.alpaca     ──┼──► ProviderMergerAgent ──► market.bars
TastyTradeProviderAgent──► market.bars.raw.tastytrade ──┘              │
                                                                        ▼
                                                           market.data.quality
                                                      (divergence, gap rate, latency)
```

**Responsibilities:**

| Concern | Behaviour |
|---------|-----------|
| **Routing** | Config-driven rules: which provider is authoritative per instrument or asset class |
| **Deduplication** | Single canonical `BarMessage` out, regardless of how many sources in |
| **Failover** | If primary silent >30s on instrument, promote secondary automatically — no manual intervention |
| **Divergence detection** | If two providers disagree on close price >threshold, publish to `market.data.quality` |
| **Single provider passthrough** | When only one provider active, zero arbitration logic — direct passthrough |

### Bar Selection Strategy

The merger receives bars from multiple providers for the same instrument and must
decide which single bar to publish. Three strategies — only one is right for live trading:

**Option A: Primary wins (recommended)**
The authoritative provider per instrument is configured (e.g. IBKR for futures, Alpaca
for equities). When IBKR bar arrives it is published immediately to `market.bars`. The
Alpaca bar for the same instrument/timestamp is not published — it is logged to
`market.data.quality` for divergence tracking only. Zero latency added on the hot path.

```
IBKR bar arrives   → published immediately to market.bars
                     Alpaca bar for same instrument → market.data.quality (divergence check only)

IBKR silent >30s   → ProviderMergerAgent promotes Alpaca, logs failover event to market.data.quality
                     Alpaca bars now published to market.bars

IBKR recovers      → grace period (e.g. 5 bars) before demoting Alpaca — prevents flapping
                     demotion event logged to market.data.quality
```

**Option B: First wins**
Whoever arrives first gets published. Simple but fragile — if Alpaca is consistently
200ms faster on bar close, it always wins regardless of quality. Not recommended.

**Option C: Consensus / averaging**
Wait for both bars, compare, publish averaged or best-quality version. Adds latency —
you are waiting for the slower provider before any bar goes downstream. Unacceptable
for a live trading pipeline. Suitable only for offline research/validation runs.

**Decision: Primary wins with auto-failover.** Deterministic, zero hot-path latency,
full redundancy, no manual intervention required.

### The Renaissance Bonus

Every divergence between IBKR and Alpaca on the same bar is a measurable data point.
Over weeks this builds a dataset about provider reliability per instrument, per session,
per volatility regime. That dataset eventually feeds back into:
- Provider selection logic (auto-demote a degraded feed before it causes missed signals)
- ML features: `provider_agreement_score` as a data quality gate on signal confidence
- Audit surface in Grafana: per-provider gap rate, latency p99, divergence frequency

The infrastructure itself generates data quality intelligence. That's the Renaissance
principle applied to the data layer — instrument everything, let the system self-correct.

**Why this preserves the DAG invariant:**

`market.bars` remains a single clean canonical feed. BarAggregatorComputeAgent,
FeatureCompute, SignalGenerator — everything downstream — never changes. The merger
is the only component that knows multiple providers exist.

### market.data.quality events

Provider quality data is a first-class signal, not a log line:

```python
class ProviderQualityEvent(BaseModel):
    ts: datetime
    instrument: str
    event_type: str          # "divergence" | "gap" | "failover" | "latency_spike"
    primary_provider: str
    secondary_provider: str | None
    primary_value: float | None
    secondary_value: float | None
    delta: float | None
    promoted_provider: str | None   # set on failover events
```

These events feed a `ProviderAuditorAgent` that maintains per-provider quality scores
(gap rate, latency p99, divergence frequency) — surfaced in Grafana and eventually
usable as ML features for data quality-aware signal gating.

---

## Sequencing

This work does **not** need to be done all at once. Natural phases:

1. **Now (deferred):** `provider_meta` nesting + `DataProviderAdapter` Protocol
   — non-breaking, zero operational impact, unblocks future work
2. **When adding second provider:** adapter implementation + agent rename + new systemd unit
   — complementary coverage (Case 1) works immediately
3. **When running overlapping providers:** `ProviderMergerAgent` + `market.bars.raw.*` topics
   — only needed if two providers cover the same instruments

**Do not build the merger speculatively.** The adapter pattern is the prerequisite.
The merger is the upgrade path if/when the use case demands it.

---

## Open Questions (resolve when scheduling)

- Which asset classes does each target provider actually support for the instruments we trade?
- TastyTrade and TradeStation API stability / rate limits for streaming bars?
- Does Alpaca support 1m bars with sufficient precision for futures proxies (SPY for ES)?
- Routing rule format — static config in `settings.py` or dynamic via DB table?
