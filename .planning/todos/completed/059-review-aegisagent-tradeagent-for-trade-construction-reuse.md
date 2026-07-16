---
**Created:** 2026-07-05
**Area:** intelligence
**Type:** improvement
**Priority:** P2
**Effort:** ~2-4 hours
**Benefit:** Avoid re-deriving position-sizing/risk-overlay design from scratch when v4.0 Execution Layer planning starts
**Risk:** low
**Gate:** None — cheapest right before v4.0 (Trade Construction Layer) planning begins, but not blocked on anything
**Closed:** 2026-07-16
---

# 059 — Review AegisAgent + TradeAgent for Trade Construction Layer reuse

**Status:** completed

**Cross-reference (2026-07-12, housekeeping audit):** `.planning/todos/pending/060-review-cluster2-legacy-intelligence-backlog.md`
is the same shape of task (re-read old vision/backlog docs, salvage vs. archive), same effort
class, same low urgency, different content domain. Not a merge candidate — different domains —
but consider running both as one "legacy docs review" session rather than two separate sittings.

## Problem

`docs/research/vision-01-aegisagent.md` (independent risk management: position sizing, portfolio-level
constraints) and `docs/research/vision-05-tradeagent.md` (autonomous trading app, broker execution)
were written and filed as long-horizon commercial-product vision — multi-tenant, separate app,
out of scope for IndicAgent. `PROJECT.md`'s Core Value was clarified 2026-07-05: the actual
endgame is personal live trading capital, not a commercial product. Under that lens these two docs
may already contain reusable design for v4.0's Trade Construction Layer (minimum risk management,
position sizing, trade framing) — but nobody has re-read them with that framing since the endgame
was stated explicitly. Right now the docs sit filed as "different endgame, parked" in
`docs/research/roadmap-scope-map.md` area 6, with only a flag, not a real assessment.

## Solution / Fix / What / Why

Re-read both docs specifically asking "what design here is reusable for a single-user, personal-capital
version, stripped of multi-tenant/commercial concerns" — not "should we build the full vision." Output:
a short note (or an update to `docs/research/trade-construction-layer.md`) listing which pieces of
AegisAgent's risk-overlay design and TradeAgent's execution-vehicle design transfer directly,
which need descoping, and which are commercial-only and irrelevant. Feed the result into v4.0
planning when that milestone starts (currently gated on v3.1/v3.15/v3.2 completing per `ROADMAP.md`).

## Resolution (2026-07-16)

Re-read both docs (now at `docs/research/archive/vision-01-aegisagent.md` and
`docs/research/archive/vision-05-tradeagent.md`) specifically for single-user reuse, cross-checked
against the existing `docs/research/trade-construction-layer.md` and the v4.0 Execution Layer's
current design (`ROADMAP.md` Phases 156-159: Portfolio State, Position Sizing & Risk, Live
Execution, Cost Calibration — all four phases already exist with real design detail, not just
placeholder names).

**Found:** substantial convergent design already exists independently of these two vision docs.
Phase 157 (Position Sizing & Risk) already specs Portfolio Kelly, a VaR ceiling, per-symbol
drawdown limits, regime-conditioned caps, and a kill switch — AegisAgent's hard-limit table and
fail-safe/independent-authority framing map onto this almost line-for-line and should be used as
the starting checklist when Phase 157 is actually planned, not re-derived. Phase 156's
`portfolio_state` (correlation-cluster exposure) is AegisAgent's correlation/concentration
analysis. TradeAgent's trade lifecycle management (stop cascade, BE/trail), confidence→allocation
curve, and reconciliation-agent concept are all directly reusable and currently absent from
Phase 158/159's design — worth folding in when those phases are planned. TradeAgent's trade
linkage/groups design maps directly onto this doc's own cross-sectional spread-portfolio
construction (a ranked long/short bucket is exactly a "group").

Multi-tenant machinery in both docs (broker routing rules, per-tenant credentials, Lead-agent
HITL approval modes, agent-ops dashboards, customer reporting) needs descoping to a single
account/single broker/deterministic decision path, or is outright commercial-only and irrelevant
(tenant isolation, prompt-injection hardening for an LLM order-decision path this project doesn't
plan to build, institutional compliance framing, options-Greeks-specific stress scenarios — no
options are traded here).

Full breakdown (transfers directly / needs descoping / commercial-only) written into
`docs/research/trade-construction-layer.md`'s new "AegisAgent / TradeAgent Reuse Assessment"
section, citing concrete mechanisms from both source docs rather than restating them generically.
