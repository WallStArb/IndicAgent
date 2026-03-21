---
created: 2026-03-07T00:00:00.000Z
title: Broker-agnostic instrument provider_meta
area: general
priority: 16
tier: deferred
phase: when-second-provider
files:
  - src/config/settings.py
  - src/providers/ibkr.py
---

# Broker-Agnostic Instrument provider_meta

**Created:** 2026-03-07
**Trigger:** Discovered that IBKR requires `symbol="VIX"` and `trading_class="VX"` to qualify
VXJ6, but these are IBKR-specific quirks — not standard market conventions. Currently
these live directly in the canonical `Instrument` definition (`base="VIX"`, `provider_meta={"trading_class": "VX"}`),
which leaks broker-specific data into the shared instrument model.

## Problem

`Instrument.base` and `Instrument.provider_meta` are currently IBKR-specific:
- `base="VIX"` — IBKR's API symbol for VX futures (standard market convention is "VX")
- `provider_meta={"trading_class": "VX"}` — IBKR qualifier to select standard monthly
  contract over weeklies (VX13, VX14, VX16 series)

When a second broker (Tradovate, Alpaca, Schwab, etc.) is added, each will have its own
symbol conventions. The current flat structure forces IBKR quirks on all providers.

## Target Design

Nest provider overrides under broker keys in `provider_meta`:

```python
Instrument(
    symbol="VXJ6",       # canonical — used in stream keys, DB, dashboard
    base="VX",           # standard market base symbol (exchange convention)
    exchange="CFE",
    expiry="20260415",
    provider_meta={
        "ibkr": {
            "symbol": "VIX",        # IBKR API symbol (IBKR-specific quirk)
            "trading_class": "VX",  # selects monthly over weekly VX contracts
        },
        # future brokers add their own key here
        # "tradovate": {"symbol": "VX"},
    }
)
```

`ibkr.py` reads:
```python
ibkr_meta = instrument.provider_meta.get("ibkr", {})
api_symbol = ibkr_meta.get("symbol") or instrument.base
trading_class = ibkr_meta.get("trading_class", "")
```

Other providers do the same pattern for their own key — no cross-contamination.

## Scope

- `src/config/settings.py` — restructure all 24 instruments' `provider_meta`
- `src/providers/ibkr.py` — update `qualify_instrument()` to read `provider_meta["ibkr"]`
- `src/core/models.py` — `provider_meta` schema stays `dict[str, Any]`, no change needed
- Any future provider (tradovate.py, alpaca.py) reads its own key from day one

## When to Do

Defer until a second data provider is being integrated. Implementing now creates
churn across 24 instruments with no operational value — IBKR is the only provider.
Flag this at the start of the broker-abstraction work in TradeAgent/DerivAgent.
