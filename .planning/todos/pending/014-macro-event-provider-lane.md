---
created: 2026-05-03T19:00:00.000Z
title: "Macro Event Provider Lane (P-CTX-03b)"
area: qualitative
priority: 6
resolves_phase: 89
tier: feature
files:
  - docs/ideas/qualitative-intelligence-layer.md
  - services/macro_event_provider_agent.py
  - services/macro_event_compute_agent.py
---

# Macro Event Provider Lane (P-CTX-03b)

**Filed:** 2026-05-03
**Priority:** Medium
**Prerequisite:** P-CTX-01 (todo 012)

## Problem

Macro events (FOMC, CPI, NFP) are the largest single-day volatility catalysts. The pipeline has no awareness of upcoming economic releases, policy meetings, or their historical impact patterns.

## Solution

Second deterministic context lane — macro calendar:

1. **MacroEventProviderAgent** — ingests economic calendar data
   - Events: FOMC, CPI, NFP, PMI, GDP, unemployment
   - Publishes raw events to `topic_ctx_macro_raw()` with key="global"
   - Sources: FRED API (free), Trading Economics, or IBKR calendar
2. **MacroEventComputeAgent** — normalizes into macro ctx snapshot
   - Computes: fomc_days_away, cpi_days_away, current_regime (hiking/pausing/cutting), vix_term_structure_slope
   - Publishes to `topic_ctx_snapshot()` with event_type='macro'
3. **CtxWriterAgent** persists to ctx_events + ctx_snapshots (global events, symbol=NULL)

### Agent naming

| Agent | File | Systemd unit |
|---|---|---|
| MacroEventProviderAgent | services/macro_event_provider_agent.py | indicagent-macro-event-provider |
| MacroEventComputeAgent | services/macro_event_compute_agent.py | indicagent-macro-event-compute |

Note: MacroComputeAgent already exists for yield_curve + FTQ — this is a separate raw-ingest layer for economic calendar events.

### Data sources

- FRED API (free, well-structured, Fed Economic Data)
- IBKR economic calendar (if available via TWS)
- Trading Economics (paid, high quality)

## Context

Architecture: `docs/ideas/qualitative-intelligence-layer.md`
Implementation plan: `docs/plans/2026-05-02-unified-intelligence-design.md` (Phase 3: P-MACRO-01)

---
**Updated 2026-06-22** — v2.x qualitative lane concept is superseded, but the data (earnings dates, macro event calendar) is a concrete candidate for the TF-agnostic `context_features` table (cadence: event-driven/daily, no natural bar TF). Revisit when `context_features` is implemented: `.planning/todos/pending/2026-06-22-tf-agnostic-feature-architecture.md`.
