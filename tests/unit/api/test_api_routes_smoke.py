"""
Request-level smoke test for every registered GET route (todo 137).

Todo 130's bug (drift.py importing a nonexistent `get_connection` symbol) survived
undetected because the bad import was inside the function body, only triggered at
request time -- an import-time smoke test (`import src.api.main`) would not have
caught it. This test builds a minimal app from the same routers `src/api/main.py`
registers, mocks the DB dependency with well-behaved empty responses (so a route's
own error-handling paths don't fire and mask a real crash as an intentional 4xx/5xx),
and hits every GET route once, asserting it never returns 500.

Excludes `sse.router`: `/api/sse/events` is an infinite Server-Sent-Events stream,
structurally incompatible with a single-request smoke check.

Doesn't assert response shape -- only that the route doesn't blow up on import or
first invocation, per the todo's own scope.
"""

from __future__ import annotations

from collections import defaultdict
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from src.api import dependencies
from src.api.routes import (
    ai_stats,
    drift,
    features,
    health,
    instruments,
    market_data,
    narrative,
    signals,
    validation,
    vocabulary,
)

# name -> dummy value substituted into any {name} path segment. A UUID string
# also satisfies routes where the same segment name is typed plain `str`
# (e.g. signals.py's /signals/detail/{signal_id}), so one value per name covers
# every route regardless of its own path-param type.
_PATH_PARAM_VALUES = {
    "symbol": "SPY",
    "timeframe": "5m",
    "namespace": "asset_class",
    "signal_id": str(uuid4()),
}


def _fetchrow_result(args: tuple):
    """A parameterized WHERE-keyed lookup (args non-empty) can genuinely miss --
    None mimics that correctly and exercises routes' real not-found paths. A bare
    aggregate query (no args, e.g. `SELECT COUNT(*) ... WHERE <fixed condition>`)
    always returns exactly one row in Postgres, never zero -- a permissive
    all-zero row here avoids a false "route crashed" failure that's really just
    this fake being less forgiving than real Postgres."""
    if args:
        return None
    return defaultdict(int)


class _FakeConn:
    """Stand-in for an asyncpg connection: every read returns benign empty data."""

    fetch = AsyncMock(return_value=[])
    fetchval = AsyncMock(return_value=1)
    execute = AsyncMock(return_value="OK")

    async def fetchrow(self, query, *args):
        return _fetchrow_result(args)


class _FakePool:
    def acquire(self):
        return _fake_cm()


@asynccontextmanager
async def _fake_cm():
    yield _FakeConn()


class _FakeDatabaseManager:
    """Mirrors DatabaseManager's public surface used by API routes, minus a real pool."""

    pool = _FakePool()

    def get_connection(self):
        return _fake_cm()

    async def fetch(self, query, *args):
        return []

    async def fetchrow(self, query, *args):
        return _fetchrow_result(args)

    async def execute_query(self, query, *args):
        return []


def _build_test_app() -> FastAPI:
    app = FastAPI()
    for router, prefix in _ROUTERS:
        app.include_router(router, prefix=prefix)
    return app


def _resolve_path(path_template: str) -> str:
    path = path_template
    for name, value in _PATH_PARAM_VALUES.items():
        path = path.replace("{" + name + "}", value)
    return path


# (router, prefix) pairs, the single source `_build_test_app` and `_collect_get_routes` both
# read from. Introspecting the assembled `app.routes` after `include_router()` used to work
# (each sub-route flattened into the top-level list with its own `.path`/`.methods`), but a
# fastapi bump wraps included routers in `fastapi.routing._IncludedRouter` instead, which
# exposes no `.path`/`.methods` of its own -- collecting from the router objects directly,
# before they're handed to `include_router()`, sidesteps that internal representation entirely
# rather than re-coupling to whatever fastapi's wrapper looks like this time.
_ROUTERS: list[tuple[APIRouter, str]] = [
    (health.router, "/health"),
    (market_data.router, "/api"),
    (instruments.router, "/api"),
    (features.router, "/api"),
    (signals.router, "/api"),
    (narrative.router, "/api"),
    (ai_stats.router, "/api"),
    (drift.router, "/api/drift"),
    (validation.router, "/api/validation"),
    (vocabulary.router, "/api/vocabulary"),
]


def _collect_get_routes() -> list[str]:
    paths = []
    for router, prefix in _ROUTERS:
        for route in router.routes:
            methods = getattr(route, "methods", None)
            if not methods or "GET" not in methods:
                continue
            paths.append(_resolve_path(prefix + route.path))
    return paths


_test_app = _build_test_app()
_GET_ROUTE_PATHS = _collect_get_routes()


@pytest.fixture
def client():
    _test_app.dependency_overrides[dependencies.get_db_manager] = lambda: _FakeDatabaseManager()
    yield TestClient(_test_app)
    _test_app.dependency_overrides.clear()


class TestApiRoutesSmoke:
    def test_route_inventory_is_nonempty(self):
        """Guards against a future router-registration change silently dropping
        every route from this test (an empty parametrize list still 'passes')."""
        assert len(_GET_ROUTE_PATHS) >= 15

    @pytest.mark.parametrize("path", _GET_ROUTE_PATHS)
    def test_get_route_does_not_500(self, client, path):
        response = client.get(path)

        assert response.status_code != 500, f"GET {path} returned 500: {response.text[:500]}"
