#!/usr/bin/env python3
"""ConfigService HTTP API — OPS config management on port 9001.

Three-layer invariant:
  INFRA config (DATABASE_URL, KAFKA_BROKERS, secrets) — stored in .env files.
    Never accessible via this API. Requires restart to change.
  STRUCT config (plugin tiers, DAG order, signal schema) — lives in code.
    Never accessible via this API. Requires deployment to change.
  OPS config (regime thresholds, swarm weights, alert settings) — managed here.
    Hot-reloadable: agents subscribe to topic_config_updates and apply changes live.

This API handles OPS config ONLY. INFRA/STRUCT keys are rejected with HTTP 422.

Port convention:
  9001 = Config HTTP API (uvicorn)
  9005 = Config Service OTel metrics scrape endpoint (configured via METRICS_PORT env var
         in the systemd unit; separate uvicorn process is NOT needed — OTel exporter
         exposes metrics on this port independently)

Auth:
  When CONFIG_API_TOKEN is set, all endpoints require:
    Authorization: Bearer <CONFIG_API_TOKEN>
  Without CONFIG_API_TOKEN (dev mode), all endpoints are open.
  Token rotation: update env + restart service (live rotation deferred to Phase 110).

Phase 109 Plan 02.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

import _path_bootstrap  # noqa: F401 — project root on sys.path
import structlog
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from src.config.config_schema import ConfigValidationError, ConfigVersionConflict
from src.config.config_service import ConfigService
from src.config.settings import get_settings
from src.observability.metrics import CONFIG_AUTH_FAILED_TOTAL, CONFIG_SET_TOTAL

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Application state
# ---------------------------------------------------------------------------

config_service: ConfigService | None = None

# Auth token from environment — when set, all endpoints require Bearer auth.
CONFIG_API_TOKEN: str | None = os.getenv("CONFIG_API_TOKEN")


# ---------------------------------------------------------------------------
# FastAPI app lifecycle
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize ConfigService on startup; close pool on shutdown."""
    global config_service
    settings = get_settings()
    config_service = ConfigService(database_url=settings.database_url)
    await config_service.initialize()
    logger.info(
        "config_service_agent.startup",
        port=9001,
        auth_enabled=CONFIG_API_TOKEN is not None,
    )
    yield
    if config_service is not None:
        await config_service.close()
    logger.info("config_service_agent.shutdown")


app = FastAPI(
    title="IndicAgent Config Service",
    version="1.0.0",
    description=(
        "OPS config management API. "
        "INFRA and STRUCT keys are rejected. "
        "See three-layer invariant in module docstring."
    ),
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


async def verify_auth(request: Request) -> None:
    """Enforce Bearer token auth when CONFIG_API_TOKEN is set.

    In dev mode (CONFIG_API_TOKEN not set), passes through unconditionally.
    On missing header: emits config_auth_failed_total{reason=missing_header} + raises 401.
    On invalid token: emits config_auth_failed_total{reason=invalid_token} + raises 401.
    """
    if CONFIG_API_TOKEN is None:
        # Dev mode: no auth required
        return

    auth_header = request.headers.get("Authorization")
    if not auth_header:
        CONFIG_AUTH_FAILED_TOTAL.add(1, {"reason": "missing_header"})
        raise HTTPException(status_code=401, detail="Authorization header required")

    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        CONFIG_AUTH_FAILED_TOTAL.add(1, {"reason": "invalid_format"})
        raise HTTPException(status_code=401, detail="Authorization header must be Bearer <token>")

    token = parts[1]
    if token != CONFIG_API_TOKEN:
        CONFIG_AUTH_FAILED_TOTAL.add(1, {"reason": "invalid_token"})
        raise HTTPException(status_code=401, detail="Invalid Bearer token")


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


@app.exception_handler(ConfigValidationError)
async def validation_error_handler(request: Request, exc: ConfigValidationError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(ConfigVersionConflict)
async def version_conflict_handler(request: Request, exc: ConfigVersionConflict):
    return JSONResponse(
        status_code=409,
        content={
            "detail": "Version conflict",
            "expected_version": exc.expected_version,
            "actual_version": exc.actual_version,
        },
    )


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class ConfigSetRequest(BaseModel):
    key: str
    value: Any
    changed_by: str
    expected_version: int | None = None
    reason: str | None = None


class ConfigRevertRequest(BaseModel):
    key: str
    version: int
    changed_by: str
    reason: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/api/config/set", dependencies=[Depends(verify_auth)])
async def config_set(body: ConfigSetRequest):
    """Set an OPS config value. Returns the resulting ConfigChange.

    Raises:
      422 if key is not an OPS key (INFRA/STRUCT keys rejected).
      422 if value fails schema validation (type, range, allowed_values).
      409 if expected_version is set and does not match current version.
      401 if CONFIG_API_TOKEN is set and Bearer token is missing/invalid.
    """
    assert config_service is not None, "ConfigService not initialized"
    change = await config_service.set(
        key=body.key,
        value=body.value,
        changed_by=body.changed_by,
        expected_version=body.expected_version,
        reason=body.reason,
    )
    # Metric already emitted by ConfigService.set() — emit here too for API-layer labeling
    CONFIG_SET_TOTAL.add(
        1, {"key": body.key, "changed_by": body.changed_by, "outcome": "api_success"}
    )
    return change.model_dump()


@app.get("/api/config/get/{key}", dependencies=[Depends(verify_auth)])
async def config_get(key: str, default: str | None = None):
    """Get the current parsed value for a config key."""
    assert config_service is not None, "ConfigService not initialized"
    value = await config_service.get(key, default=default)
    return {"key": key, "value": value}


@app.get("/api/config/list", dependencies=[Depends(verify_auth)])
async def config_list():
    """Return all current OPS config values as a parsed dict."""
    assert config_service is not None, "ConfigService not initialized"
    values = await config_service.list()
    return values


@app.post("/api/config/revert", dependencies=[Depends(verify_auth)])
async def config_revert(body: ConfigRevertRequest):
    """Revert a config key to a specific historical version."""
    assert config_service is not None, "ConfigService not initialized"
    change = await config_service.revert_key(
        key=body.key,
        version=body.version,
        changed_by=body.changed_by,
        reason=body.reason,
    )
    return change.model_dump()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Port 9001 = Config HTTP API. OTel metrics exposed on port 9005 via env METRICS_PORT
    # (configured in systemd unit; OTel exporter binds to that port independently).
    uvicorn.run(app, host="0.0.0.0", port=9001)
