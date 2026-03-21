---
created: 2026-03-21T00:00:00.000Z
title: Add market_entry_at and market_exit_at to signal_ledger
area: database
priority: 14
---

## Problem

`signal_ledger` tracks zone lifecycle (`activated_at`, `exit_at`) but has no equivalent timestamps for actual market entry and exit. Without these, there's no way to audit price/time alignment between signal activation and `market_data_ohlcv`.

## Solution

Add `market_entry_at` and `market_exit_at` columns to `signal_ledger` — mirrors the existing `activated_at`/`exit_at` zone track pair.

- DB migration: add two nullable `timestamptz` columns
- `signal_lifecycle_service.py`: populate `market_entry_at` when order fill is detected (or zone activation if not distinguishable)
- `market_exit_at`: set at signal terminal event alongside `exit_at`
- Enables JOIN to `market_data_ohlcv` on `(symbol, market_entry_at)` for price audit

## Notes

- Touches: migration + lifecycle service + replay script
- Low priority until live trade execution is wired (currently signals are advisory only)
