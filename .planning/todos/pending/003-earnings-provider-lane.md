---
created: 2026-05-03T19:00:00.000Z
title: "Earnings Provider Lane — v3.0 context_features"
area: qualitative
priority: medium
v3_phase: Phase B+ — gated on context_features table (see 2026-06-22-tf-agnostic-feature-architecture)
note: v2.x agent/topic design superseded; reframes as event-driven rows in context_features (feature_date = earnings_date, symbol-scoped)
files:
  - docs/ideas/qualitative-intelligence-layer.md
  - services/earnings_provider_agent.py
  - services/earnings_compute_agent.py
---

# Earnings Provider Lane (P-CTX-03a)

**Filed:** 2026-05-03
**Priority:** Medium
**Prerequisite:** P-CTX-01 (todo 012)

## Problem

No earnings data flows into IndicAgent. Earnings surprises, consensus EPS, and report timing are known alpha signals (post-earnings announcement drift) that the quant pipeline is blind to.

## Solution

First deterministic context lane — earnings via IBKR Fundamental Data (already available):

1. **EarningsProviderAgent** — fetches earnings data via `src/providers/ibkr.py` extension
   - Reports: quarterly EPS, consensus, surprise %, report timing
   - Publishes raw events to `topic_ctx_earnings_raw()`
2. **EarningsComputeAgent** — normalizes raw earnings into ctx snapshot
   - Computes: days_to_next, last_surprise_pct, surprise_zscore, last_direction
   - Publishes to `topic_ctx_snapshot()` with event_type='earnings'
3. **CtxWriterAgent** (from P-CTX-01) persists to ctx_events + ctx_snapshots
4. **Feature writer bridge** resolves active earnings snapshot at bar insert time

### Agent naming (per CLAUDE.md conventions)

| Agent | File | Systemd unit |
|---|---|---|
| EarningsProviderAgent | services/earnings_provider_agent.py | indicagent-earnings-provider |
| EarningsComputeAgent | services/earnings_compute_agent.py | indicagent-earnings-compute |

### Data source

IBKR Fundamental Data — already available via existing TWS connection, no new API subscription needed.

## Context

Architecture: `docs/ideas/qualitative-intelligence-layer.md` (Provider Agent Design section)
Implementation plan: `docs/plans/2026-05-02-unified-intelligence-design.md` (Phase 3: P-QUAL-01)
