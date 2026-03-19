# Auth + External Access Research

**Project:** IndicAgent — Phase 45 Auth + External Access
**Researched:** 2026-03-19
**Overall confidence:** HIGH (JWT library, SSE fan-out), MEDIUM (Cloudflare SSE buffering workarounds)

---

## Recommended Stack

| Component | Choice | Version | Rationale |
|-----------|--------|---------|-----------|
| JWT library | PyJWT | 2.x | FastAPI officially switched to PyJWT in docs (2025); python-jose is nearly unmaintained; PyJWT is lightweight and async-compatible |
| Auth model | API key + short-lived JWT | — | API key for LAN/programmatic access; JWT (30-min expiry) for dashboard browser sessions |
| SSE fan-out | In-process asyncio (already implemented) | — | `KafkaSSEBroadcaster` is the correct architecture — one Kafka consumer, N asyncio.Queue per client |
| CF Tunnel mode | Public hostname | cloudflared | Zero-trust adds WARP client requirement; public hostname with JWT auth is correct for a personal dashboard |
| Next.js deploy | `output: 'standalone'` + systemd | — | Minimal node process, no Docker required, fits existing systemd pattern |
| SSE auth | HttpOnly cookie (primary) + query-param short-lived token (fallback) | — | Browser EventSource cannot set custom headers; cookies are the correct solution |

---

## JWT Auth Design

### Library: PyJWT

**Why not python-jose:** Last meaningful development stalled; FastAPI maintainer confirmed the docs migration to PyJWT (GitHub Discussion #11345, 2025). python-jose 3.5.0 shipped May 2025 but community consensus is to migrate away.

**Why not authlib:** Authlib is excellent but is a full OAuth2/OIDC server suite — overkill for a personal dashboard. Adds significant surface area. Use authlib only if you need to federate with a third-party IdP.

**PyJWT installation:**
```bash
pip install "PyJWT[crypto]"  # crypto extra for RS256/ES256 support
```

For this use case, HS256 (symmetric) is sufficient — single server, no key distribution problem.

### Auth Model: API Key + JWT (Both)

For a personal/small-team dashboard, implement both:

**API key** (static, long-lived):
- For LAN access, programmatic queries, and health-check endpoints
- Stored as `INDICAGENT_API_KEY` env var (SHA-256 hashed copy in settings for comparison)
- Sent as `Authorization: Bearer <api-key>` header
- Does not expire — revoke by rotating env var + restarting API

**JWT** (short-lived, for browser sessions):
- 30-minute access token; 7-day refresh token stored in HttpOnly cookie
- `POST /api/auth/token` — accepts password (single shared password for personal use), returns access token in JSON body + sets refresh token as HttpOnly cookie
- `POST /api/auth/refresh` — reads HttpOnly refresh cookie, issues new access token
- `POST /api/auth/logout` — clears refresh cookie

**Why both:** API key is simpler for LAN, cURL, and scripts. JWT is required for the browser dashboard because cookies give you the SSE auth solution for free (see SSE Auth section below).

### FastAPI Dependency Pattern

```python
# src/api/auth.py
import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer(auto_error=False)

def require_auth(
    creds: HTTPAuthorizationCredentials | None = Security(_bearer),
    request: Request = None,
) -> dict:
    """Validates Bearer token (API key or JWT) or session cookie."""
    token = None

    # 1. Bearer header (API key or JWT)
    if creds:
        token = creds.credentials

    # 2. Fallback: cookie (for SSE EventSource which cannot set headers)
    if not token and request:
        token = request.cookies.get("indicagent_session")

    # 3. Fallback: query param (short-lived SSE token only — see SSE Auth section)
    if not token and request:
        token = request.query_params.get("token")

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # API key check first (fast path)
    if token == settings.api_key:
        return {"type": "api_key"}

    # JWT check
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
```

Apply to routes:
```python
@router.get("/events")
async def sse_events(
    ...,
    _auth: dict = Depends(require_auth),
):
```

**Critical:** Do NOT apply `require_auth` globally via middleware — the `/health` and `/metrics` endpoints must remain unauthenticated for systemd/Prometheus. Apply the dependency per-router or per-route group.

### Settings additions needed

```python
# src/config/settings.py additions
jwt_secret: str = Field(default="CHANGE-ME-IN-PROD", env="INDICAGENT_JWT_SECRET")
jwt_access_ttl_minutes: int = Field(default=30)
jwt_refresh_ttl_days: int = Field(default=7)
api_key: str = Field(default="", env="INDICAGENT_API_KEY")
```

---

## SSE Fan-Out Architecture

### Current State: Already Correct

The `KafkaSSEBroadcaster` in `src/api/routes/sse.py` implements the right architecture:

- ONE `KafkaConsumerClient` with `group_id="sse_broadcaster"` consuming all topics
- `run()` loop fans out to per-client `asyncio.Queue(maxsize=500)`
- `subscribe()` returns `(_latest snapshot, live_queue)` — new clients get full state instantly
- Slow clients: `put_nowait` + drop on `QueueFull` — correct, non-blocking

**No changes needed to the fan-out architecture.** This correctly solves the "N dashboard clients from ONE Redpanda consumer" requirement. The Redpanda consumer group never scales with client count.

### What changes with auth

The only SSE fan-out change for auth is:
1. Add `_auth: dict = Depends(require_auth)` to the `sse_events` endpoint
2. The broadcaster itself is unaffected — auth is enforced at HTTP connection time before the generator runs

### Scaling note (not needed now)

If the API ever runs multiple uvicorn workers (multiple processes), each worker would have its own `KafkaSSEBroadcaster` and its own Kafka consumer. That is fine for this use case — each API worker is a single-process uvicorn. If multi-worker is ever needed, the fan-out would need to move to an inter-process channel (Redis pub/sub). Not relevant today.

---

## Cloudflare Tunnel Setup

### Mode: Public Hostname (not Zero Trust)

Zero Trust Access (WARP client + device policy) is appropriate for enterprise environments. For a personal dashboard accessible from any browser without installing a client, use **public hostname mode** with application-layer JWT auth.

### Installation and Setup

```bash
# On the server (192.168.1.158)
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb -o /tmp/cloudflared.deb
sudo dpkg -i /tmp/cloudflared.deb

# Authenticate (opens browser, selects domain)
cloudflared tunnel login

# Create the tunnel (generates UUID)
cloudflared tunnel create indicagent

# Create config
mkdir -p ~/.cloudflared
cat > ~/.cloudflared/config.yml << 'EOF'
tunnel: <UUID-from-above>
credentials-file: /root/.cloudflared/<UUID>.json

ingress:
  - hostname: api.indicagent.com
    service: http://localhost:8000
    originRequest:
      noTLSVerify: false
      disableChunkedEncoding: true   # helps SSE streaming (see below)
  - hostname: dash.indicagent.com
    service: http://localhost:3000
  - service: http_status:404
EOF

# Route DNS
cloudflared tunnel route dns indicagent api.indicagent.com
cloudflared tunnel route dns indicagent dash.indicagent.com

# Install as systemd service
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

### SSE Buffering — The Real Problem

**This is a known, partially-unresolved issue with cloudflared.** Research findings:

- cloudflared has a hardcoded `flushableContentTypes` list; `text/event-stream` is in the list, so the Content-Type header should trigger flush mode
- In practice, buffering still occurs in some configurations (100KB threshold, or GET-specific behavior in Quick Tunnels)
- The `X-Accel-Buffering: no` header is already set in the SSE `StreamingResponse` — this is the right signal to cloudflared/nginx

**Mitigation steps (in order of confidence):**

1. `Content-Type: text/event-stream` on the response — already set by FastAPI `StreamingResponse(media_type="text/event-stream")`. Confirmed.
2. `X-Accel-Buffering: no` — already set in `sse.py`. Confirmed.
3. `disableChunkedEncoding: true` in cloudflare config.yml ingress rule for the API hostname — found in community workarounds; reduces intermediate buffering.
4. If buffering persists: consider tunneling SSE through WebSocket (not recommended — complexity cost) OR serve the SSE endpoint over HTTP/2 where framing is different.

**Pragmatic recommendation:** Set `disableChunkedEncoding: true` and test. The existing headers are already correct. If SSE works on LAN but breaks through the tunnel, the 5-second heartbeat (`b": heartbeat\n\n"`) already in the generator will keep the connection alive even if some batching occurs.

**Dashboard SSE reconnect:** The dashboard should already handle reconnects gracefully. The `_latest` snapshot on broadcaster means clients reconnecting get full state within one snapshot drain cycle, even after a brief disconnection caused by tunnel buffering forcing a flush.

### Cloudflare Dashboard Configuration

In Cloudflare Zero Trust Dashboard (dash.teams.cloudflare.com):
- Networks > Tunnels > indicagent > Public Hostnames
- For `api.indicagent.com`: Additional Application Settings > HTTP Settings > Disable Chunked Encoding: ON

---

## Next.js Production Deploy

### Pattern: `output: 'standalone'` + systemd (no Docker)

Fits the existing systemd-managed service pattern. No new infrastructure.

**Step 1 — Build config:**
```typescript
// dashboard/next.config.ts
const nextConfig: NextConfig = {
  output: "standalone",
  allowedDevOrigins: ["dash.indicagent.com", "www.indicagent.com", "192.168.1.158"],
};
```

**Step 2 — Build:**
```bash
cd /home/bg/dev/indicagent/dashboard
npm run build
# Produces: dashboard/.next/standalone/
# Copy static assets (standalone does NOT include them automatically):
cp -r .next/static .next/standalone/.next/static
cp -r public .next/standalone/public
```

**Step 3 — Systemd unit:**
```ini
# /etc/systemd/system/indicagent-dashboard.service
[Unit]
Description=IndicAgent Dashboard
After=network.target

[Service]
Type=simple
User=bg
WorkingDirectory=/home/bg/dev/indicagent/dashboard/.next/standalone
ExecStart=/usr/bin/node server.js
Restart=always
RestartSec=5
Environment=NODE_ENV=production
Environment=PORT=3000
Environment=HOSTNAME=0.0.0.0
Environment=NEXT_PUBLIC_API_BASE_URL=
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now indicagent-dashboard
```

**Why not PM2:** PM2 adds another process manager on top of systemd — redundant. systemd `Restart=always` handles restarts equivalently. The project already uses systemd for 12 services; consistency is correct.

**Why not nginx in front:** The Cloudflare Tunnel proxies directly to `localhost:3000`. nginx would add a layer with no benefit on this single-server setup. Skip it.

**Deploy script pattern:**
```bash
#!/usr/bin/env bash
# production/scripts/deploy_dashboard.sh
set -euo pipefail
cd /home/bg/dev/indicagent/dashboard
npm ci --production=false
npm run build
cp -r .next/static .next/standalone/.next/static
cp -r public .next/standalone/public
sudo systemctl restart indicagent-dashboard
echo "Dashboard deployed."
```

---

## Auth on SSE Endpoints

### The Problem

The browser's native `EventSource` API is defined by the W3C/WHATWG spec to make a GET request with no ability to set custom request headers. `Authorization: Bearer <token>` is not possible with EventSource. This is a fundamental browser API limitation, not a FastAPI limitation.

### Solution: HttpOnly Session Cookie

This is the cleanest, most secure approach for a browser-native dashboard:

1. User authenticates via `POST /api/auth/token` with password
2. Server sets `Set-Cookie: indicagent_session=<jwt>; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=1800`
3. Browser `EventSource` opens the SSE connection — browser automatically includes the cookie
4. FastAPI `require_auth` dependency checks `request.cookies.get("indicagent_session")` before the Bearer header check

**Why HttpOnly:** XSS cannot steal an HttpOnly cookie. JWT in `localStorage` is vulnerable to XSS theft. HttpOnly cookie is unreadable by JavaScript but sent automatically by the browser on every same-origin (and credentialed cross-origin) request.

**HTTPS required:** Cloudflare Tunnel provides HTTPS termination, so the `Secure` cookie flag is satisfied for external access. For LAN access, the cookie will need `Secure=false` on HTTP (or use the `api_key` query param on LAN where XSS risk is lower).

**EventSource with credentials (cross-origin):**
```typescript
// dashboard/src/hooks/use-market-stream.ts
const eventSource = new EventSource(url, { withCredentials: true });
```
`withCredentials: true` is required for cross-origin SSE to include cookies. This requires the CORS config to have `allow_credentials=True` with explicit origins (not `"*"`).

### Fallback: Short-Lived Query Parameter Token

For environments where cookie setup is complex (e.g., LAN HTTP access during development):

1. `POST /api/auth/sse-token` → returns a 60-second single-use token
2. `EventSource("/api/sse/events?token=<short-lived-token>&symbols=...")`
3. FastAPI extracts from `request.query_params.get("token")` after cookie and Bearer header checks fail

The short TTL (60s) limits exposure even if the URL appears in server logs. This is a pragmatic tradeoff for internal LAN access where HTTPS is not in use.

**Do not use a long-lived JWT as a query parameter.** Long-lived tokens in URLs are logged by every proxy, web server, and browser history.

### Dashboard TypeScript changes needed

```typescript
// In the SSE connection hook, add withCredentials:
const es = new EventSource(
  `${getApiBase()}/api/sse/events?symbols=${symbols}&timeframe=${tf}`,
  { withCredentials: true }
);
```

---

## CORS Configuration

Current state: `allow_origins=["*"]` with `allow_credentials=True` — this combination is **rejected by browsers** as insecure (spec violation). Must be fixed when auth ships.

### Production CORS config

```python
# src/api/main.py
ALLOWED_ORIGINS = [
    "https://dash.indicagent.com",
    "https://www.indicagent.com",
    "http://192.168.1.158:3000",   # LAN dashboard dev
    "http://localhost:3000",        # local dev
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,         # required for cookie-based SSE auth
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["X-Request-ID"],
)
```

Load origins from `Settings` so they can be configured per environment without code changes:

```python
# settings.py
cors_origins: list[str] = Field(
    default=["http://localhost:3000"],
    env="INDICAGENT_CORS_ORIGINS",
)
```

Environment variable (comma-separated or JSON list works with Pydantic):
```bash
INDICAGENT_CORS_ORIGINS='["https://dash.indicagent.com","http://192.168.1.158:3000"]'
```

### Why `allow_credentials=True` is required

The HttpOnly session cookie solution requires `allow_credentials=True`. This forces explicit origins (no wildcard). The Cloudflare Tunnel hostnames must be in the list.

### Preflight caching

Add `max_age=3600` to `CORSMiddleware` to cache OPTIONS preflight for 1 hour, reducing preflight round-trips to Cloudflare:

```python
app.add_middleware(CORSMiddleware, ..., max_age=3600)
```

---

## Implementation Order

Phase 45 should execute in this sequence:

### Wave 1 — Foundation (no UI changes, internal only)

1. Add `PyJWT[crypto]` to `requirements.txt` / `pyproject.toml`
2. Add `jwt_secret`, `jwt_access_ttl_minutes`, `jwt_refresh_ttl_days`, `api_key`, `cors_origins` to `Settings`
3. Create `src/api/auth.py`: `require_auth` dependency (cookie → Bearer → query param order)
4. Create `POST /api/auth/token`, `POST /api/auth/refresh`, `POST /api/auth/logout` routes
5. Fix CORS: replace `allow_origins=["*"]` with env-configurable list + `allow_credentials=True`
6. Apply `require_auth` to all `/api/*` routes except `/health` and `/metrics`
7. Unit tests: valid JWT, expired JWT, invalid JWT, API key, missing auth → 401

### Wave 2 — Cloudflare Tunnel

8. Install and configure `cloudflared` with `disableChunkedEncoding: true`
9. Route `api.indicagent.com` → `:8000` and `dash.indicagent.com` → `:3000`
10. Verify SSE streaming works end-to-end through the tunnel (5-second heartbeat proves connectivity)

### Wave 3 — Next.js Production Build

11. Add `output: 'standalone'` to `next.config.ts`
12. Build, copy static assets, create `indicagent-dashboard.service` systemd unit
13. Add `withCredentials: true` to `EventSource` constructor in the SSE hook
14. Update `getApiBase()` if needed for production hostname detection
15. Smoke test: auth login → cookie → SSE through tunnel

### Wave 4 — Hardening

16. Add refresh token rotation (issue new refresh token on each refresh, invalidate old)
17. Add rate limiting on auth endpoints (`slowapi` or simple in-process counter)
18. Log auth events (login, logout, token expiry) via structlog with `service="api"` field

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| PyJWT recommendation | HIGH | FastAPI official docs updated; multiple verified sources |
| API key + JWT dual model | HIGH | Well-established pattern for personal/small-team tools |
| SSE fan-out (asyncio.Queue) | HIGH | Already implemented correctly in KafkaSSEBroadcaster; no changes needed |
| HttpOnly cookie for SSE auth | HIGH | W3C spec limitation on EventSource confirmed; cookie is the canonical solution |
| CORS config | HIGH | FastAPI docs + browser spec; wildcard + credentials rejection confirmed |
| Next.js standalone + systemd | HIGH | Official Next.js docs; consistent with existing project pattern |
| Cloudflare SSE buffering fix | MEDIUM | `disableChunkedEncoding` + existing headers should work; community reports mixed; needs empirical validation |
| Cloudflare Tunnel setup steps | MEDIUM | Based on official docs + community guides; exact config.yml syntax should be verified against cloudflared version installed |

## Open Questions

- Does the `indicagent_session` cookie need `SameSite=None` (required for cross-site cookies) when the dashboard at `dash.indicagent.com` connects to the API at `api.indicagent.com`? These are different subdomains — technically cross-origin. Answer: YES, `SameSite=None; Secure` is required for cross-subdomain cookie sending. The LAN fallback (same host) can use `SameSite=Strict`.
- If SSE buffering through Cloudflare proves persistent despite all headers, the fallback is to implement a polling endpoint (`GET /api/sse/poll?after=<cursor>`) as a degraded alternative. Not recommended unless buffering is confirmed unresolvable.
- Refresh token storage: for a single-user system, storing refresh tokens in-memory (a `set` in `auth.py`) is sufficient for immediate revocation. Adding a `refresh_tokens` DB table is the right move if multi-device sessions are needed later.

## Sources

- FastAPI Discussion #11345: python-jose abandonment, PyJWT migration (2025)
- FastAPI official JWT docs: https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/
- cloudflared SSE buffering issue #199: https://github.com/cloudflare/cloudflared/issues/199
- cloudflared SSE GET buffering issue #1449: https://github.com/cloudflare/cloudflared/issues/1449
- MDN EventSource withCredentials: https://developer.mozilla.org/en-US/docs/Web/API/EventSource/withCredentials
- Next.js standalone output docs: https://nextjs.org/docs/pages/api-reference/config/next-config-js/output
- Cloudflare Tunnel setup: https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/
- FastAPI CORS docs: https://fastapi.tiangolo.com/tutorial/cors/
