---
created: 2026-04-13T00:12:23.969Z
title: Deactivate BTCUSD/ETHUSD — remove crypto from active contracts
area: intelligence
priority: high
files:
  - src/config/settings.py:423-445
  - src/providers/ibkr_adapter.py:145-208
  - src/core/timeframe_builder.py:388-390
---

## Problem

IBKR spot crypto (BTCUSD/ETHUSD via PAXOS exchange) data quality is poor — thin volume, unreliable feed, and a `volume=0` workaround already in production. Every bar these instruments produce is a potential training sample in `signal_ledger` and `intelligence_features`. Poisoned samples (low-volume, unreliable close prices) degrade ML model quality downstream in Phase 55 and beyond. Two clean futures instruments beat four instruments where two have questionable data.

Known issues:
- IBKR error 321 (keepUpToDate+AGGTRADES unsupported) forces a bespoke RTB workaround in `ibkr_adapter.py`
- `volume=0` paper-trading workaround in `timeframe_builder.py:388`
- Crypto cluster never reaches weight_updater promotion threshold (needs 100+ signals)
- `_days_to_expiry` returns 0 permanently for crypto (minor but incorrect)

## Solution

1. Comment out (do NOT delete) `BTCUSD` and `ETHUSD` entries in `get_active_contracts()` in `src/config/settings.py` — keeps the `Instrument` definitions intact for future use with a better feed
2. Keep `crypto_24_7` session, `_crypto_rtb_stream()`, and all crypto-related code dormant — no deletion, just deactivation
3. Restart `indicagent-ibkr-provider` — crypto subscriptions will stop
4. Verify pipeline adapts: no orphaned topics, dashboards show only active symbols, systemd units healthy
5. Optionally: add a `market_data_gaps` cleanup for any open crypto gap rows
