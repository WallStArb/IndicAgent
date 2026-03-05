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

## Competitive Landscape

### Option Alpha (optionalpha.com/bots)

**What they are:** A no-code automated trading platform for options and stocks. Users build "bots" using natural language "recipes" — deterministic if-then rules applied to standard technical indicators and position data. Connects to TradeStation and Tradier. Recently moved to a **free** model with broker connection.

**What they do well:**
- Clean UX for non-coders; accessible to a wide retail audience
- Template library lets users adopt strategies without building from scratch
- Good execution infrastructure (SmartPricing, position limits, scheduling)
- Paper trading and bot logs — transparency and testing
- Community sharing of templates

**The critical limitation — they automate rules, they don't generate intelligence:**

Option Alpha's "intelligence" is the user's own rule — "if RSI < 30 AND price > VWAP, buy." The platform executes that rule reliably. It does not:
- Generate signals through a multi-tier analytical pipeline
- Know what macro regime the market is in
- Understand derivatives structure (no GEX, no vol surface, no VRP)
- Adapt based on outcomes (no feedback loop)
- Synthesize qualitative context (no news regime, no COT, no prediction markets)
- Reason over context — it applies rules, not judgment

**What their free pricing tells us:** Basic trading automation is being commoditized. The differentiation edge has to be in **intelligence depth**, not automation infrastructure. A rule engine is table stakes. The question is what the rule is based on — and that is precisely what IndicAgent, QualAgent, and DerivAgent provide.

**Competitive positioning of our stack vs Option Alpha:**

| Capability | Option Alpha | Our stack |
|-----------|-------------|-----------|
| Signal generation | User-defined if-then rules | IndicAgent I1–I8 multi-tier pipeline |
| Regime awareness | None | IndicAgent I4 + QualAgent macro regime |
| Qualitative context | None | QualAgent: COT, prediction markets, macro, sentiment |
| Derivatives structure | Standard indicators only | DerivAgent: GEX, VRP, vol surface, VANNA/CHARM |
| Decision layer | Deterministic rules | TradeAgent: LLM-assisted lead agent over full context |
| Self-improvement | None | Signal ledger → feedback loop → adaptive weights |
| Narrative / explanation | None | I8 AI narrative + QualAgent synthesis |
| Target instrument | Options + equities | Futures (then expanding) |
| Pricing model | Free (broker-connected) | Subscription tiers + performance layer |

**The key insight from Option Alpha:** The retail market wants automation but is getting rule-based automation. Our product delivers **intelligence-based** automation — the system understands context, not just conditions. That is a different product category even if it looks similar from the outside.

**Reference:** [Option Alpha Bots](https://optionalpha.com/bots)

---

## Open Questions

- Target user profile: discretionary trader (dashboard-first) vs. systematic trader (API-first)?
- How much of the intelligence methodology to expose vs. keep as black box?
- Solo venture or bring in partners/team early?
- Jurisdiction for regulatory considerations (market data redistribution, financial advice disclaimers)

---

## Product Family & Suite Naming

*Captured 2026-03-04. As the platform grows from IndicAgent to a four-product suite (IndicAgent + QualAgent + DerivAgent + TradeAgent), the suite needs its own brand identity.*

### The problem with individual product names as .com

- `tradeagent.com` — **not available**
- `qualagent.com` — **not available**
- `indicagent.com` / `indicagent.io` — check / TBC
- `derivagent.com` — likely available (new concept)

### TLD strategy

For an AI-native platform in 2026, **.ai is more credible than .com**. The namespace is less saturated and the TLD signals what the product is before any copy is read. `.io` is the backup — widely trusted in fintech infrastructure.

Priority: `[product].ai` → `[product].io` → `[product].com`

### Suite name candidates

The suite needs a name that encompasses quant + qual + deriv + trade without being confused with any individual component. Evaluated below:

| Name | Verdict | Reasoning |
|------|---------|-----------|
| **QuantAgent** | ❌ Avoid | Implies quant-only; contradicts QualAgent's entire purpose; confused with IndicAgent |
| **AlphaAgent** | ✅ Strong | Universal hedge fund language; the whole suite exists to generate alpha; short, memorable, immediately understood. Check `alphaagent.ai` |
| **SpectraAgent** | ✅ Distinctive | Spectrum metaphor — each product is a wavelength of market intelligence. Unique, ownable, visual. Check `spectra.ai` |
| **ApexAgent** | ⚠️ Decent | The apex of market intelligence. Simple. Risks sounding generic/fitness-brand. |
| **SynthAgent** | ⚠️ Interesting | The synthesis narrative is the core value prop. But sounds like a chemistry/audio product. |
| **NexusAgent** | ❌ Generic | Nexus = connection point; correct concept but forgettable tech-startup name. |
| **AegisAgent** | ⚠️ Strong imagery | Aegis = shield; protecting capital through intelligence. Institutional feel. Less obvious connection to signals. |

### Recommendation

**Primary: AlphaAgent** (`alphaagent.ai`) — clearest statement of the platform's purpose, instantly understood in every hedge fund / prop shop / trading context globally.

**Secondary: SpectraAgent** (`spectra.ai`) — if AlphaAgent.ai is taken or too generic; more ownable as a brand.

### Domain structure options

**Option A — Suite domain, subdomains per product:**
```
alphaagent.ai           → marketing site, suite overview
indic.alphaagent.ai     → IndicAgent dashboard
trade.alphaagent.ai     → TradeAgent app
qual.alphaagent.ai      → QualAgent intelligence
deriv.alphaagent.ai     → DerivAgent overlay
```
Best for single-brand marketing. Products feel like features of one platform.

**Option B — Each product gets its own domain:**
```
indicagent.ai           → core quant product (existing)
qualagent.ai            → qualitative add-on
derivagent.ai           → derivatives overlay
tradeagent.ai           → execution product
alphaagent.ai           → suite landing / marketing
```
Best for products sold to distinct audiences. IndicAgent SaaS customers ≠ TradeAgent autonomous trading customers.

**Recommended: Option B** — the products serve meaningfully different buyer profiles and will be launched sequentially. Each product should be able to stand alone commercially. The suite domain (`alphaagent.ai`) becomes the master brand and cross-links all four.

### Commercial tier evolution (with expanded product family)

| Phase | Product | Price range | Primary buyer |
|-------|---------|------------|--------------|
| **Phase 1** | IndicAgent SaaS | $49–299/mo | Discretionary futures trader |
| **Phase 2** | QualAgent context add-on | $199–399/mo | Systematic trader, small fund |
| **Phase 3** | DerivAgent overlay | $299–599/mo | Options-aware trader, prop shop |
| **Phase 4** | TradeAgent execution | Subscription + performance fee | Affluent trader, family office |

The moat is not any single product — it is the **compounding intelligence** when all four are connected. A competitor can copy one product; they cannot replicate four years of live `signal_ledger` outcomes feeding a self-improving QualScore.
