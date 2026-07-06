# Commercialization — Retail SaaS + Tiered API

**Status:** draft
**Priority:** low
**Milestone:** future (post-v2.8)
**Last Updated:** 2026-06-03
**Tags:** commercialization, saas, retail, api, monetization, platform, tiers, auth, multi-tenant

---

## Vision

Monetize IndicAgent as a retail SaaS platform with tiered subscriptions. The shared-brain model — compute intelligence once for 23 contracts, serve to N subscribers — gives excellent unit economics as the user base grows.

The key architectural insight: the intelligence pipeline (I1–I7, signal ledger, feature store) is shared infrastructure. It runs once regardless of subscriber count. Users buy filtered and configured views of its output. The hot path — Redpanda topics, the pipeline DAG, TimescaleDB writes — requires zero per-user changes. The multi-tenant layer is additive: access control, delivery, and per-user configuration sit entirely above the signal layer.

---

## Product Tiers

| Tier | Price | Access |
|------|-------|--------|
| **Free** | $0 | Dashboard, 15-min delayed data, 5 symbols. Acquisition funnel. |
| **Pro** | ~$49–99/mo | Real-time dashboard, all 23 contracts, full I1–I7 intelligence panel. |
| **API** | ~$149–299/mo | SSE stream or webhooks delivering signals + intelligence JSON. For algo traders. |
| **Premium CIS** | ~$299–499/mo | API access gated to CIS > 0.70 signals only — regime-eligible, GARCH/Kalman quality-gated. |

Note: Free-tier delayed data is not a query filter on the SSE stream. 15-minute delay requires either a buffered write path or a separate polling endpoint (`GET /signals?delayed=true`) against `signal_ledger WHERE timestamp < now() - interval '15 minutes'`. The polling approach adds zero infrastructure; SSE becomes a Pro-and-above feature. That is the cleaner design.

---

## The Moat: CIS as Premium Gate

Most retail platforms compete on indicator quantity. This platform competes on **signal quality**:

- **Self-improving:** WeightUpdater trains on real outcome data from `signal_ledger`
- **Verifiable:** win rate by CIS bucket is trackable — a marketing asset competitors cannot claim
- **Triple-filtered:** GARCH/Kalman quality gates + HMM regime eligibility + CIS threshold
- **Hard to replicate:** the compounding signal ledger is a durable moat; a competitor can copy the architecture but cannot replicate years of live outcome data feeding a self-improving weight system

The premium tier delivers fewer signals, much higher quality — and the performance data proves it.

---

## What Is and Isn't Already Built

The pipeline compute layer is complete. The multi-user delivery layer is not. These are different scopes.

| Component | Status | Notes |
|-----------|--------|-------|
| Intelligence pipeline I1–I7 | ✅ complete | Shared, runs once for all contracts |
| CIS scoring + WeightUpdater | ✅ complete | Self-improving; `signal_ledger` is authoritative |
| Signal ledger + outcome tracking | ✅ complete | Foundation for performance transparency page |
| Intelligence feature store | ✅ complete | `intelligence_features` hypertable |
| Dashboard UI (Next.js) | ✅ complete | Single-user dev server; not production-hardened |
| REST API (FastAPI) | ✅ complete | No auth; single-user only |
| SSE stream | ✅ complete — with correctness bugs | See SSE Audit section |
| Auth + identity | ❌ not built | |
| Subscription gating | ❌ not built | |
| Multi-user SSE fan-out | ❌ not built | Current fan-out has O(N) pathology and no predicate push-down |
| Webhook delivery | ❌ not built | |
| Org / team accounts | ❌ not built | |
| API key path | ❌ not built | |
| Stripe billing | ❌ not built | |
| Data licensing (redistribution) | ❌ hard blocker | See Critical Path |

---

## Critical Path (Ordered by Architectural Dependency)

Each step is a prerequisite for the one that follows.

### Step 1 — Data licensing (hard blocker)

IBKR market data license prohibits redistribution to third parties. The entire SaaS model is legally blocked until resolved. No subscriber-facing feature can be integration-tested with real data until the feed is switched.

**Best fit for futures:** [Databento](https://databento.com) — futures-native, excellent CME/CBOT coverage, clean WebSocket API, pay-per-symbol-month. [Rithmic](https://rithmic.com) is the prop-shop standard alternative.

`services/ibkr_provider.py` would be replaced with a Databento feed adapter. `IntelligencePipeline` onward is already data-source agnostic — it consumes from Kafka, not from IBKR directly.

### Step 2 — SSE correctness bugs (fix before adding any auth layer)

Adding auth to a broken delivery layer compounds the bugs. See SSE Audit section.

### Step 3 — Auth + authorization

**Identity provider: Clerk**

Clerk is the right choice for this stage:
- Native Next.js middleware handles session cookies, route protection, and redirect logic with minimal config — this is not trivially replicated with Auth.js without significant custom code
- Native Organizations support maps cleanly to the org model (member invites, roles, org-scoped JWTs)
- Python SDK for FastAPI JWT validation is straightforward
- The third-party availability risk is bounded: Clerk being down affects new logins only; existing sessions carry JWTs validated locally against the cached Clerk JWKS public key — no Clerk network call on the request hot path

**The one scenario where Clerk becomes wrong:** enterprise/fund clients who require SAML SSO (Okta, Azure AD). Clerk supports SAML but only on its Enterprise plan. The mitigation: the `orgs` table carries `clerk_org_id` as a nullable FK. When a SAML-requiring client is onboarded, WorkOS or Auth0 can be added for that org only — the authorization layer is indifferent to which identity provider issued the JWT.

**Authorization state: in-process cache backed by Postgres**

The infrastructure is TimescaleDB + Redpanda. There is no Redis in the stack and none should be added for this.

Subscription tier must NOT be in the JWT. JWTs are signed at issuance; subscription state changes asynchronously via Stripe webhook. A user who cancels retains access until JWT expiry — a contractual failure mode on a paid financial product.

The correct model:
```
In-process per-worker cache: dict[str, tuple[AuthzState, float]]
  key:   user_id or org_id
  value: (AuthzState, expiry_timestamp)
  TTL:   60s

On cache miss: query subscriptions table (one DB read, result cached for TTL)

Invalidation: Stripe webhook fires → updates subscriptions table →
  publishes invalidation event to topic_config_updates (existing compacted topic,
  designed for exactly this pattern) → FastAPI background consumer drops
  the cache entry for the affected org_id immediately
```

FastAPI middleware chain:
```
Request
  → validate JWT signature (cached Clerk JWKS public key, no network call)
  → extract user_id / org_id
  → check in-process authz cache
  → on miss: query subscriptions table, populate cache
  → inject AuthContext(user_id, org_id, tier) into request state
  → route handler
```

With `uvicorn --workers N`, each worker has an independent cache. Without the Kafka invalidation consumer, a tier downgrade takes up to 60s per worker. With it, propagation is near-immediate. The Kafka consumer fits naturally as a FastAPI lifespan background task — same pattern as the existing `kafka_broadcaster`.

### Step 4 — Org model and DB schema

Every user belongs to an org. Solo users get a personal org created at signup. Corporate accounts get an org with multiple members. All queries are `WHERE org_id = ?`. There is no `WHERE user_id = X OR org_id = Y` pattern anywhere.

```sql
users (
    user_id     UUID PRIMARY KEY,
    clerk_id    TEXT UNIQUE NOT NULL,
    email       TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)

orgs (
    org_id       UUID PRIMARY KEY,
    clerk_org_id TEXT UNIQUE,        -- NULL for personal orgs
    name         TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
)

org_members (
    org_id    UUID NOT NULL REFERENCES orgs,
    user_id   UUID NOT NULL REFERENCES users,
    role      TEXT NOT NULL CHECK (role IN ('owner','admin','member')),
    joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (org_id, user_id)
)

subscriptions (
    org_id        UUID PRIMARY KEY REFERENCES orgs,
    tier          TEXT NOT NULL CHECK (tier IN ('free','pro','api','premium')),
    stripe_sub_id TEXT UNIQUE,
    valid_from    TIMESTAMPTZ NOT NULL,
    valid_to      TIMESTAMPTZ,
    seats         INT
)

api_keys (
    key_id       UUID PRIMARY KEY,
    org_id       UUID NOT NULL REFERENCES orgs,
    key_hash     TEXT UNIQUE NOT NULL,   -- HMAC-SHA256; plaintext never stored
    key_prefix   TEXT NOT NULL,          -- first 12 chars for lookup before hashing
    scopes       JSONB NOT NULL,         -- ["signals:read", "intelligence:read", ...]
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at   TIMESTAMPTZ,
    last_used_at TIMESTAMPTZ
)

signal_filters (
    filter_id UUID PRIMARY KEY,
    org_id    UUID NOT NULL REFERENCES orgs,
    user_id   UUID REFERENCES users,    -- NULL = org-wide default
    min_cis   FLOAT,
    symbols   JSONB,                    -- NULL = all
    setups    JSONB,                    -- NULL = all
    active    BOOL NOT NULL DEFAULT TRUE
)

webhook_endpoints (
    endpoint_id UUID PRIMARY KEY,
    org_id      UUID NOT NULL REFERENCES orgs,
    url         TEXT NOT NULL,
    secret_hash TEXT NOT NULL,
    event_types JSONB NOT NULL,
    active      BOOL NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
```

### Step 5 — Webhook delivery (outbox pattern)

"Simple async worker with retry logic" is not correct for a paid financial product. If the worker crashes between a signal firing and a successful POST, the event is lost.

Write to `webhook_outbox` in the **same transaction** as the signal write to `signal_ledger`. The outbox is the delivery guarantee.

```sql
webhook_outbox (
    event_id         UUID PRIMARY KEY,
    endpoint_id      UUID NOT NULL REFERENCES webhook_endpoints,
    org_id           UUID NOT NULL,
    payload          JSONB NOT NULL,
    idempotency_key  TEXT NOT NULL UNIQUE,  -- signal_id + ':' + endpoint_id
    scheduled_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    attempted_at     TIMESTAMPTZ,
    delivered_at     TIMESTAMPTZ,
    attempts         INT NOT NULL DEFAULT 0,
    failed           BOOL NOT NULL DEFAULT FALSE
)
```

A separate `webhook_dispatcher` service reads pending rows and POSTs with exponential backoff (1s, 2s, 4s, 8s, max 3 attempts). On exhaustion: mark `failed=TRUE`, emit `job_completed_total{status="failure"}`.

Every outgoing payload carries `X-Indicagent-Signature: HMAC-SHA256(endpoint_secret, payload_json)` so recipients can verify authenticity. `idempotency_key` prevents duplicate delivery on retry.

### Step 6 — API key path

- **Format:** `inda_live_{random_32_bytes_hex}` — prefix enables prefix-based DB lookup before hashing
- **Storage:** `HMAC-SHA256(key, server_secret)` only; plaintext never written
- **Scopes:** per-key; a `signals:read` key cannot access webhook config endpoints
- **FastAPI path:** `X-Indicagent-Key` header → hash → in-process cache lookup (TTL 60s, backed by `api_keys` table) → inject `AuthContext`
- **Rate limiting:** nginx `limit_req_zone` per tier at the edge handles tier-level limits without any per-process state; per-API-key limits use an in-process token bucket at moderate scale

### Step 7 — Production hardening

- `next build && next start` — replace dev server
- `uvicorn --workers N` behind gunicorn
- nginx reverse proxy (80/443 → :3000 + :8000) with `limit_req_zone` for tier-level rate limiting

---

## SSE Audit: Correctness Bugs in Current Implementation

`src/api/routes/sse.py` has four correctness problems that exist independently of multi-tenancy.

**Bug 1 — Symbol filtering is a fiction.**
`_build_topic_list()` ignores `symbols` and `timeframe` query parameters and returns the same global topic set for every caller. Every connected client receives data for all 23 contracts. The `topic_set` filter inside `event_generator` discards nothing because it already contains all topics.

**Bug 2 — Fan-out is O(N) on every message.**
`_queues` is a `list[asyncio.Queue]`. Every incoming Kafka message iterates the entire client list. `_queues.remove(q)` on disconnect is a linear scan. Correct structure: `dict[topic, set[Subscription]]` — fan-out cost proportional to matching clients, subscription/unsubscription O(1).

**Bug 3 — Silent drops have no telemetry.**
`q.put_nowait` raises `QueueFull` and the handler is `pass`. Slow clients lose data with zero observability. Fix: `sse_messages_dropped_total{user_id}` OTel counter on every drop.

**Bug 4 — Reconnect is broken by design.**
The SSE spec requires each outgoing `data:` frame to carry an `id:` field. The broadcaster never sets one. `Last-Event-ID` from a reconnecting client is always empty — full snapshot retransmit on every reconnect. Fix: stamp each message with a monotonic sequence number; use `last_event_id` to replay only events after the client's last received sequence.

**Latent tech debt:**
- `_latest` dict has no size bound — grows indefinitely as contracts change
- `_build_stream_list` and `_event_name_for_stream` are dead legacy Redis code kept for test compat — delete and fix the tests
- `_extract_signal_scorecard_payload` exists because the publisher double-serializes; fix at the publisher, remove the transform

**Multi-tenant additions required after bug fixes:**
- Connection time: validate JWT or API key, verify `tier >= pro`, reject 401 otherwise
- Tier heartbeat (every 30s): re-read in-process authz cache; if tier changed, send `event: tier_changed\ndata: {"action":"reconnect"}` and close the stream — bounds the downgrade window to 30s

---

## LLM Scaling

Active inference model is `nemotron-3-nano:4b` (set via `OLLAMA_MODEL` in `.env`, running in `ollama` Docker container). At CPU inference speeds, narrative generation does not scale to concurrent paid subscribers.

Options:
- **GPU server** (RTX 4090 → ~5s per inference) — best quality/cost at moderate scale
- **Cloud LLM API** (Claude/OpenAI) — pay-per-token; cost per narrative must be modeled against subscription revenue at each tier
- **Pre-generate on schedule** — generate narratives per bar regardless of active users; store in `intelligence_features`; serve cached on demand. No inference on the request path.

Pre-generation is the recommended first approach: it removes inference latency from the delivery path and makes narrative freshness a function of bar frequency, not subscriber count.

---

## Infrastructure Gaps (Corrected)

| Gap | Correct Approach | What Not To Do |
|-----|-----------------|----------------|
| SSE fan-out | Fix O(N) list → `dict[topic, set[Subscription]]`, add predicate push-down | Do not add Redis pub/sub — adds a second streaming system when Redpanda already exists |
| Auth | Clerk (identity) + in-process authz cache backed by `subscriptions` table | Do not put subscription tier in JWT — stale on tier change |
| Authz cache invalidation | `topic_config_updates` Kafka topic (already exists) | Do not add Redis for this |
| API keys | `inda_live_{hex32}` format, HMAC-SHA256 stored, in-process cached, scoped | |
| Webhooks | Outbox table in same transaction as signal write; separate dispatcher with backoff | Do not use fire-and-forget async worker |
| Rate limiting | nginx `limit_req_zone` at the edge for tier limits | Do not require Redis token buckets — no Redis in stack |
| Org model | All FKs to `org_id`; Clerk Orgs for member management UI | No `user_id OR org_id` query patterns |
| Prod server | `next start` + `uvicorn --workers N` + nginx | Replace all dev servers |

---

## Performance Transparency Page

Public stats page pulling from `signal_ledger`: win rate by CIS bucket, by setup type, by regime, rolling 90-day window. This can be built on existing `signal_ledger` + `setup_performance` tables with no new infrastructure. It is the highest-leverage item in the entire commercialization roadmap — it sells the premium tier better than any copy, and it should be built before any subscriber infrastructure exists.

---

## Unit Economics

Shared-brain model: intelligence compute costs are fixed per symbol, not per user. At 1,000 Pro subscribers × $79/mo = $79k MRR — data costs for 23 futures symbols are a small fraction.

Delivery costs do scale with subscribers (SSE connections, webhook POSTs per signal, `webhook_outbox` row growth). These are small at moderate scale but should be modeled before pricing is finalized. The SSE O(N) fan-out fix is a prerequisite for the shared-brain unit economics to hold at scale.

---

## Competitive Landscape

### Option Alpha (optionalpha.com/bots)

No-code automated trading for options and stocks. Users build bots using if-then rules applied to standard technical indicators. Connects to TradeStation and Tradier. Recently moved to a free model with broker connection.

**The critical limitation:** Option Alpha executes the user's rule reliably. It does not generate signals through a multi-tier analytical pipeline, understand macro regime, model derivatives structure, adapt based on outcomes, or reason over context.

**What their free pricing signals:** basic trading automation is being commoditized. The differentiation edge must be in intelligence depth, not automation infrastructure.

| Capability | Option Alpha | This stack |
|-----------|-------------|-----------|
| Signal generation | User-defined if-then rules | I1–I8 multi-tier pipeline |
| Regime awareness | None | I4 + QualAgent macro regime |
| Qualitative context | None | QualAgent: COT, prediction markets, macro, sentiment |
| Derivatives structure | Standard indicators only | DerivAgent: GEX, VRP, vol surface, VANNA/CHARM |
| Self-improvement | None | Signal ledger → feedback loop → adaptive weights |
| Target instrument | Options + equities | Futures (then expanding) |

---

## Open Questions

- **Data licensing jurisdiction:** which legal entity holds the Databento agreement; what redistribution terms cover CME futures data specifically?
- **Financial advice disclaimers:** signals that include directional guidance are categorically different from indicator readouts — legal review required before public launch
- **Target user profile:** discretionary trader (dashboard-first) vs. systematic trader (API-first)? Different onboarding UX, support needs, and tier uptake patterns
- **Intelligence methodology exposure:** performance transparency page reveals outcomes; mechanism can remain proprietary
- **SAML readiness:** at what point does an enterprise/fund client require SAML SSO? That is the trigger to evaluate WorkOS alongside Clerk

---

## Product Family & Suite Naming

*Captured 2026-03-04. Relevant when the platform expands to the full four-product suite.*

`.ai` TLD is recommended for an AI-native platform. Priority: `[product].ai` → `[product].io` → `[product].com`.

**Suite name candidates:**

| Name | Verdict |
|------|---------|
| **AlphaAgent** | ✅ Strong — universal hedge fund language; short, memorable |
| **SpectraAgent** | ✅ Distinctive — spectrum metaphor, ownable brand |
| **ApexAgent** | ⚠️ Risks sounding generic |
| **AegisAgent** | ⚠️ Institutional feel; less obvious signal connection |
| **QuantAgent** | ❌ Implies quant-only; contradicts QualAgent's purpose |
| **NexusAgent** | ❌ Generic tech-startup name |

**Recommended:** AlphaAgent as suite master brand; individual products retain own domains. Products serve different buyer profiles and launch sequentially — each should stand alone commercially.

| Phase | Product | Price range | Primary buyer |
|-------|---------|------------|--------------|
| 1 | IndicAgent SaaS | $49–299/mo | Discretionary futures trader |
| 2 | QualAgent context add-on | $199–399/mo | Systematic trader, small fund |
| 3 | DerivAgent overlay | $299–599/mo | Options-aware trader, prop shop |
| 4 | TradeAgent execution | Subscription + performance fee | Affluent trader, family office |

The moat is not any single product — it is the compounding intelligence when all four are connected. A competitor can copy one product; they cannot replicate years of live `signal_ledger` outcomes feeding a self-improving system.
