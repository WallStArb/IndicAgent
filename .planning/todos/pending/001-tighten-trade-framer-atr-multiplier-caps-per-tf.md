---
created: 2026-03-20T09:51:12.383Z
title: Tighten trade_framer ATR multiplier caps per-TF
area: general
priority: 1
tier: immediate
phase: unblocked
files:
  - src/intelligence/trading/trade_framer.py:64-83
---

## Problem

`ATR_TARGET_MAX_MULTIPLIER = 8.0` in `trade_framer.py` allows stops and targets to be placed many % away from current price on volatile instruments (PL, CL, GC). For instruments with 1-2% ATR, 8× ATR = 8-16% away — clearly not actionable. The fallback RR targets (1.5×, 3.0×, 5.0× risk) compound the issue when stop distance is already wide.

Surfaced during Phase 41 discuss-phase as a production quality issue visible in signal_ledger rows.

## Solution

Add per-TF max ATR caps:
- 1m: max 3 ATR for targets
- 5m: max 5 ATR
- 15m: max 7 ATR
- 1h+: keep current 8.0

Also review fallback RR target multipliers (1.5×, 3.0×, 5.0× risk) — may need per-TF caps too since a 5R target on a wide 1m stop produces unreachable targets.

`frame_trade()` already receives `timeframe` — just needs to select the right cap.
