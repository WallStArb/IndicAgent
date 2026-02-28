# Commercialization — Retail SaaS + Tiered API

**Version:** 1.0.0
**Last Updated:** 2026-02-28
**Status:** Idea — strategic direction, not yet scoped into roadmap

---

## Vision

Monetize IndicAgent as a retail SaaS platform with tiered subscriptions. The shared-brain model — compute intelligence once for 23 contracts, serve to N subscribers — gives excellent unit economics as the user base grows.

---

## Product Tiers

| Tier | Price | Access |
|------|-------|--------|
| **Free** | $0 | Dashboard, 15-min delayed data, 5 symbols. Acquisition funnel. |
| **Pro** | ~$49–99/mo | Real-time dashboard, all 23 contracts, full I1–I7 intelligence panel. |
| **API** | ~$149–299/mo | SSE stream or webhooks delivering signals + intelligence JSON. For algo traders building on top of our layer. |
| **Premium CIS** | ~$299–499/mo | API access gated to CIS > 0.70 signals only — regime-eligible, GARCH/Kalman quality-gated. |

---

## The Moat: CIS as Premium Gate

Most retail platforms compete on indicator quantity. This platform competes on **signal quality** — which is defensible:

- **Self-improving:** WeightUpdater (Phase 7) trains on real signal outcome data from `signal_ledger`
- **Verifiable:** win rate by CIS bucket is trackable from `signal_ledger` outcomes — a marketing asset competitors can't claim
- **Triple-filtered:** GARCH/Kalman quality gates + HMM regime eligibility + CIS threshold
- **Hard to replicate:** 9 phases of pipeline, hundreds of hours of domain-specific work

The premium tier delivers fewer signals, much higher quality — and the performance data proves it.

---

## What's Already Built

Surprisingly little needs to be added:

| Component | Status |
|-----------|--------|
| Dashboard UI (Next.js) | ✅ done |
| SSE stream | ✅ done |
| REST API (FastAPI) | ✅ done |
| CIS scoring + WeightUpdater | ✅ done |
| Signal ledger + outcome tracking | ✅ done |
| Intelligence feature store | ✅ done |

Missing: auth, Stripe, tier middleware, webhook delivery, data vendor swap.

---

## Critical Path

### 1. Data Licensing (hard blocker — do first)
IBKR market data license prohibits redistribution to third parties. Must switch to a commercial vendor before any public launch.

**Best fit for futures:** [Databento](https://databento.com) — futures-native, excellent CME/CBOT coverage, clean WebSocket API, pay-per-symbol-month. [Rithmic](https://rithmic.com) is another option (prop-shop standard).

The TWS daemon (`production/daemons/high_frequency_tws_daemon.py`) would be replaced with a Databento feed adapter. The rest of the pipeline (indicator service onward) is already data-source agnostic — it just consumes from Redis streams.

### 2. Auth + Subscription Gating
- **Auth:** [Clerk](https://clerk.com) integrates natively with Next.js (dashboard) and can issue JWTs consumed by FastAPI
- **Billing:** Stripe subscriptions + webhooks to update user tier in DB
- **Gating:** FastAPI middleware reads subscription tier from JWT claim, gates endpoints and SSE stream accordingly

### 3. Webhook Delivery (API tier)
API subscribers don't want to maintain a persistent SSE connection. On each CIS-filtered signal fire, POST to their registered webhook endpoint. Simple async worker with retry logic.

### 4. LLM Scaling
`qwen3:8b` at ~90s/narrative on CPU doesn't scale beyond a handful of users. Options:
- **GPU server** (RTX 4090 → ~5s per inference) — best quality/cost for moderate scale
- **Cloud LLM API** (Claude/OpenAI) — pay-per-token, scales infinitely
- **Pre-generate on schedule** — narratives generated per bar regardless of active users, cached in Redis, served on demand

### 5. Performance Transparency Page
Public stats page pulling from `signal_ledger`: win rate by CIS bucket, by setup type, by regime, rolling 90-day window. This page sells the premium tier better than any marketing copy — it's the proof of work.

---

## Infrastructure Gaps

The existing `docs/todos/pending/2026-02-27-productionize-dashboard-and-api-for-multi-user-access.md` covers the technical side:
- `next build && next start` (replace dev server)
- `uvicorn --workers N` or gunicorn
- SSE fan-out via Redis pub/sub (one reader → broadcast to N clients)
- nginx reverse proxy (port 80/443 → :3000 + :8000)
- Rate limiting per tier

---

## Unit Economics

Shared-brain model: data costs are fixed per symbol, not per user. At 1,000 Pro subscribers × $79/mo = $79k MRR — data costs for 23 futures symbols are a small fraction of that. Margin improves linearly with subscriber growth.

---

## Open Questions

- Target user profile: discretionary trader (dashboard-first) vs. systematic trader (API-first)?
- How much of the intelligence methodology to expose vs. keep as black box?
- Solo venture or bring in partners/team early?
- Jurisdiction for regulatory considerations (market data redistribution, financial advice disclaimers)
