---
**Created:** 2026-07-05
**Area:** intelligence
**Type:** improvement
**Priority:** P2
**Effort:** ~2-4 hours
**Benefit:** Avoid re-deriving position-sizing/risk-overlay design from scratch when v4.0 Execution Layer planning starts
**Risk:** low
**Gate:** None — cheapest right before v4.0 (Trade Construction Layer) planning begins, but not blocked on anything
---

# 059 — Review AegisAgent + TradeAgent for Trade Construction Layer reuse

## Problem

`docs/ideas/vision-01-aegisagent.md` (independent risk management: position sizing, portfolio-level
constraints) and `docs/ideas/vision-05-tradeagent.md` (autonomous trading app, broker execution)
were written and filed as long-horizon commercial-product vision — multi-tenant, separate app,
out of scope for IndicAgent. `PROJECT.md`'s Core Value was clarified 2026-07-05: the actual
endgame is personal live trading capital, not a commercial product. Under that lens these two docs
may already contain reusable design for v4.0's Trade Construction Layer (minimum risk management,
position sizing, trade framing) — but nobody has re-read them with that framing since the endgame
was stated explicitly. Right now the docs sit filed as "different endgame, parked" in
`docs/ideas/roadmap-scope-map.md` area 6, with only a flag, not a real assessment.

## Solution / Fix / What / Why

Re-read both docs specifically asking "what design here is reusable for a single-user, personal-capital
version, stripped of multi-tenant/commercial concerns" — not "should we build the full vision." Output:
a short note (or an update to `docs/ideas/trade-construction-layer.md`) listing which pieces of
AegisAgent's risk-overlay design and TradeAgent's execution-vehicle design transfer directly,
which need descoping, and which are commercial-only and irrelevant. Feed the result into v4.0
planning when that milestone starts (currently gated on v3.1/v3.15/v3.2 completing per `ROADMAP.md`).
