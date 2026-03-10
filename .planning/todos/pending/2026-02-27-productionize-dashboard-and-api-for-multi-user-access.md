---
created: 2026-02-27T15:38:24.811Z
title: Productionize dashboard and API for multi-user access
area: ui
files:
  - dashboard/
  - src/api/main.py
---

## Problem

Current setup cannot handle multiple concurrent users:
- Dashboard runs `npm run dev` (single-threaded, hot-reload overhead — not for production)
- API runs single uvicorn process (no workers)
- SSE fan-out: each connected client independently polls Redis streams — doesn't scale
- No auth or rate limiting — API wide open on :8000
- No reverse proxy

Estimated capacity: 2-3 concurrent users before degradation.

## Solution

1. **Dashboard**: `next build && next start`, or nginx serving static export
2. **API**: `uvicorn --workers N` or gunicorn with uvicorn workers
3. **SSE fan-out**: one Redis reader → broadcast to N clients via Redis pub/sub layer (rather than each client polling independently)
4. **Auth**: at minimum a shared token or basic auth on the dashboard/API
5. **Reverse proxy**: nginx in front of both services (port 80/443 → :3000 + :8000)

This is milestone-scale work — likely its own phase.
