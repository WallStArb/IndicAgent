---
created: 2026-03-04T00:00:00.000Z
title: Add trade journal auto-documentation (LLM daily summary)
area: intelligence
priority: 14
tier: deferred
phase: post-49
files:
  - services/
  - src/config/settings.py
---

## Problem

Signal outcomes accumulate in `signal_ledger` but there is no automated mechanism to synthesize patterns, surface learning opportunities, or generate a daily performance narrative. Manual review of raw SQL is the only option.

## Solution

Batch script or scheduled service (end-of-day) that:
1. Queries `signal_ledger` for the day's resolved signals (entry, exit, pnl_r, setup_plugin, symbol, timeframe, outcome class)
2. Computes summary stats by dimension (win rate by setup, by regime, by timeframe, by symbol)
3. Calls Ollama (phi4-mini:3.8b — fast, sufficient for structured summarization) to generate:
   - Daily narrative: what worked, what didn't, notable patterns
   - Learning notes: recurring loss patterns by setup or regime
4. Writes output to a daily journal file or `narratives:journal:YYYY-MM-DD` Redis key

No new market data required — purely operates on `signal_ledger` outcomes already in DB.
