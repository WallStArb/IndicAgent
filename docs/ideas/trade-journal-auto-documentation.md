# Trade Journal Auto-Documentation (Idea)

**Version:** 1.0.0  
**Last Updated:** 2026-02-27  
**Status:** Reference — product idea

**Source:** `.planning/IDEAS.md`

---

## Overview

Use an LLM to generate daily trade summaries and learning notes from existing `signal_ledger` data. No new market data required; builds on outcomes (entry, exit, P&L, setup type) already stored.

---

## Proposed Capabilities

- **Daily trade summaries** — LLM-generated narrative of the day’s signals and outcomes.
- **Learning-from-losses** — Identify patterns in losing trades (setup, regime, timeframe) and suggest focus areas.
- **Performance by dimension** — Track results by setup plugin, regime, timeframe, symbol (using existing `signal_ledger` and related tables).

---

## Data Source

Existing `signal_ledger` (and any linked tables): timestamps, symbols, setup plugin, entry/exit, P&L, regime, timeframe. Export or query as needed for the LLM context window.

---

## Notes

- Fits as a batch or scheduled job (e.g. end-of-day) rather than real-time.
- Could be a separate service or script that reads from the DB and calls Ollama/OpenRouter.
