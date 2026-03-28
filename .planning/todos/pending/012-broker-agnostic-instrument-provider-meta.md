---
created: 2026-03-07T00:00:00.000Z
updated: 2026-03-28T00:00:00.000Z
title: Broker-agnostic instrument provider_meta — multi-provider DAG architecture
area: architecture
priority: 16
tier: deferred
phase: when-second-provider
files:
  - src/config/settings.py
  - src/providers/ibkr.py
  - services/data_provider_agent.py
---

# Broker-Agnostic Instrument provider_meta

**Created:** 2026-03-07
**Updated:** 2026-03-28 — restructured around DAG/Agent methodology
**Trigger:** IBKR-specific symbol quirks (`VIX`/`VX` trading_class) are leaking into the
canonical `Instrument` model. The platform is designed to work with any real-time data source
— IBKR is just the current implementation.

## Vision

IndicAgent should support any of the following data sources, alone or simultaneously:

| Provider | Asset Classes | Notes |
|----------|--------------|-------|
| **IBKR** | Futures, equities, FX, crypto | Current. via ib_insync. |
| **Alpaca** | Equities, crypto | REST + WebSocket. No futures. |
| **TastyTrade** | Futures, equities, options | Streamer API. Slash-prefix futures. |
| **TradeStation** | Futures, equities | REST + streaming. Strong historical data. |
| **Schwab/ToS** | Equities, futures, options | Post-TD Ameritrade acquisition. |

## DAG Architecture

Each provider is its own **`ProviderAgent`** — one job, one systemd unit, publishing
canonical `BarMessage` to the shared `market.bars` topic. Downstream agents are already
provider-blind.

```
IBKRProviderAgent      ──┐
AlpacaProviderAgent    ──┼──► market.bars ──► BarAggregatorComputeAgent ──► ...
TastyTradeProviderAgent ─┘
```

This means:
- **Run one or many simultaneously** via systemd — IBKR for futures, Alpaca for equities
- **No env switch needed** — enable/disable the relevant systemd unit
- **No injected protocol** — each agent is a standalone file/class following `ProviderAgent` taxonomy
- A `DataProvider` Protocol in `src/providers/base.py` serves as a structural contract
  (shared interface, not an injection mechanism)

### Naming (per CLAUDE.md conventions)

| Layer | IBKR | Alpaca | TastyTrade |
|-------|------|--------|------------|
| Python file | `src/providers/ibkr.py` | `src/providers/alpaca.py` | `src/providers/tastytrade.py` |
| Agent file | `services/ibkr_provider_agent.py` | `services/alpaca_provider_agent.py` | `services/tastytrade_provider_agent.py` |
| Agent class | `IBKRProviderAgent` | `AlpacaProviderAgent` | `TastyTradeProviderAgent` |
| Systemd unit | `indicagent-ibkr-provider.service` | `indicagent-alpaca-provider.service` | `indicagent-tastytrade-provider.service` |

Current `data_provider_agent.py` → rename to `ibkr_provider_agent.py` as part of this work.

## Instrument Schema

Nest provider overrides under broker keys in `provider_meta`:

```python
Instrument(
    symbol="VXJ6",       # canonical — stream keys, DB, dashboard, signal_ledger
    base="VX",           # exchange-convention base symbol (not broker-specific)
    exchange="CFE",
    expiry="20260415",
    provider_meta={
        "ibkr": {
            "symbol": "VIX",        # IBKR API symbol (IBKR-specific quirk)
            "trading_class": "VX",  # selects monthly over weekly VX contracts
        },
        "tastytrade": {
            "symbol": "/VX",        # TastyTrade slash-prefix for futures
        },
        "tradestation": {
            "symbol": "@VX",        # TradeStation @ prefix for continuous futures
        },
        # alpaca: no futures support; schwab: TBD
    }
)
```

Each agent reads only its own key, falling back to `instrument.base`:

```python
# In IBKRProviderAgent / ibkr.py
meta = instrument.provider_meta.get("ibkr", {})
api_symbol = meta.get("symbol") or instrument.base
```

## Scope When Triggered

1. `src/config/settings.py` — restructure all instruments' `provider_meta` to nested-by-broker format
2. `src/providers/ibkr.py` — update `qualify_instrument()` to read `provider_meta["ibkr"]`
3. `src/providers/base.py` (new) — `DataProvider` Protocol as structural contract
4. `services/data_provider_agent.py` → `services/ibkr_provider_agent.py` — rename + update class
5. `services/indicagent-data-provider.service` → `indicagent-ibkr-provider.service` — rename unit
6. New provider: `src/providers/<name>.py` + `services/<name>_provider_agent.py` + systemd unit

## When to Do

Defer until a second data provider is being integrated. The `provider_meta` nesting
is the only non-breaking prep step — do it first (small, isolated change) before
building a new ProviderAgent.

**Flag this todo at the start of any new provider integration.**
