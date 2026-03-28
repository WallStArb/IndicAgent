---
id: "026"
title: "External access + auth (post-DAG)"
priority: low
created: 2026-03-28
tags: [auth, infrastructure, dashboard, api]
---

# External Access + Auth

## Context

Removed from v2.2 roadmap (was Phase 54) — not needed for personal/LAN use. The pipeline DAG
is now fully decomposed (Phases 53.1–53.3): DataProviderAgent → BarAggregatorComputeAgent →
BarWriterAgent/BarAuditorAgent → FeatureComputeAgent → SignalGeneratorAgent, all as discrete
BaseAgent instances with Golden Signal metrics and OTel trace propagation (Phase 52.6–52.8).

If external access ever becomes necessary, the architecture is clean enough to add auth without
surgery — every external boundary goes through the FastAPI layer (`src/api/`), SSE is already
fan-out via `KafkaSSEBroadcaster` (one consumer, N asyncio queues), and systemd + Prometheus
are the process model (no Kubernetes, no HPA).

## What was planned

- **Cloudflare Tunnel** — public hostname mode (`cloudflared`), no WARP client requirement
- **SSE auth problem** — Browser `EventSource` cannot set custom headers; solution is HttpOnly
  cookie (primary) + short-lived query-param token (fallback for SSE)
- **Auth model** — API key (LAN/programmatic) + short-lived JWT (browser session, 30-min
  access token + 7-day HttpOnly refresh cookie); library: PyJWT 2.x (not python-jose — stale)
- **CORS hardening** — tighten `allow_origins` to tunnel domain only
- **Rate limiting** — `slowapi` or Cloudflare WAF rules
- **Next.js deploy** — `output: 'standalone'` + systemd unit (no Docker)

## Research already done

`.planning/research/AUTH-ACCESS.md` — JWT library comparison, SSE fan-out architecture,
Cloudflare tunnel mode rationale, FastAPI dependency pattern (`require_auth`), full
implementation outline. Still valid; no dependencies on v2.1 internals.

## When to pick up

- You actually need access from outside the LAN, OR
- A second user/device needs their own session

## Effort estimate

~3 plans: (1) Cloudflare tunnel + PyJWT infra, (2) SSE auth cookie flow + Next.js token
refresh, (3) CORS + rate limiting. Research is complete — go straight to `/gsd:plan-phase`.
