"""SelfHealingAgent -- receives Alertmanager webhooks, executes remediation strategies.

Port convention:
  9002 = HTTP API (uvicorn) for /webhook/alertmanager
  9007 = OTel metrics scrape endpoint (set via METRICS_PORT in systemd unit)

Authentication is defense-in-depth: both this HTTP layer AND the engine layer
(src/self_healing/engine.py) verify CONFIG_WEBHOOK_SHARED_SECRET. Engine-layer
auth exists because the engine may be invoked from non-HTTP paths in future.

Pool management: ManagedPool (Plan 04) owns pool creation internally. Pass
settings.database_url directly to ManagedPool(...) -- do NOT pre-create a raw
asyncpg.Pool. ManagedPool.__init__ signature is
`ManagedPool(database_url: str, pool_name: str = ..., drain_timeout_seconds: float = ..., **pool_kwargs)`.
"""

from __future__ import annotations

import os

import _path_bootstrap  # noqa: F401 -- project root on sys.path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="IndicAgent Self-Healing Engine", version="1.0.0")
_self_healing_engine = None
_WEBHOOK_SECRET = os.getenv("CONFIG_WEBHOOK_SHARED_SECRET")


@app.on_event("startup")
async def startup() -> None:
    from src.config.settings import get_settings
    from src.self_healing.engine import SelfHealingEngine
    from src.self_healing.pool_manager import ManagedPool

    settings = get_settings()
    # ManagedPool owns pool creation (Plan 04 contract). Do NOT pre-create a raw pool.
    managed_pool = ManagedPool(settings.database_url, pool_name="self_healing")
    await managed_pool.initialize()
    global _self_healing_engine
    _self_healing_engine = SelfHealingEngine(managed_pool)
    await _self_healing_engine.initialize()


@app.on_event("shutdown")
async def shutdown() -> None:
    if _self_healing_engine:
        await _self_healing_engine.close()


@app.post("/webhook/alertmanager")
async def webhook_alertmanager(request: Request) -> JSONResponse:
    from src.observability.metrics import (
        WEBHOOK_AUTH_FAILED_TOTAL,
        WEBHOOK_VALIDATION_FAILED_TOTAL,
    )

    if not _self_healing_engine:
        raise HTTPException(status_code=503, detail="Engine not initialized")

    payload = await request.json()

    # HTTP-layer auth (engine ALSO verifies; defense-in-depth)
    if _WEBHOOK_SECRET:
        secret = (
            payload.get("webhook_secret")
            or payload.get("shared_secret")
            or request.headers.get("X-Webhook-Secret")
        )
        if secret != _WEBHOOK_SECRET:
            WEBHOOK_AUTH_FAILED_TOTAL.add(1, {"layer": "http", "reason": "invalid_secret"})
            raise HTTPException(status_code=401, detail="Invalid webhook shared secret")

    try:
        result = await _self_healing_engine.handle_webhook(payload)
        return JSONResponse(
            content={
                "remediation_id": result.remediation_id,
                "status": result.status,
                "error": result.error,
            },
            status_code=200,
        )
    except HTTPException:
        raise
    except Exception as exc:
        WEBHOOK_VALIDATION_FAILED_TOTAL.add(1, {"reason": type(exc).__name__})
        raise HTTPException(status_code=400, detail=str(exc)) from exc


if __name__ == "__main__":
    import uvicorn

    # Port 9002 = HTTP API. OTel metrics on 9007 via METRICS_PORT env (systemd unit).
    uvicorn.run(app, host="0.0.0.0", port=9002)
