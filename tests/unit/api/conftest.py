"""Shared fixtures for tests/unit/api/ (todo 143).

`client`/`mock_db` were independently hand-rolled in `test_market_data_route.py`,
`test_features_route.py`, `test_drift_route.py`, and `test_vocabulary_api.py` -- each built
its own single-router `FastAPI()` instance out of a stated worry about "touching main.py
lifespan complexity". That worry doesn't apply in practice: Starlette's `TestClient` only
runs `lifespan()` startup/shutdown when used as a context manager (`with TestClient(app) as
c:`) -- a bare `TestClient(app).get(...)` (the form every one of these files already used)
never triggers it, confirmed by `test_signals_api_detail.py`'s pre-existing use of the real
`src.api.main.app` this same way. Sharing the real app instead of 4 independent minimal
reconstructions is strictly better fidelity (same router registration/prefixes as
production) for less code.
"""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.api import dependencies
from src.api.main import app


@pytest.fixture
def mock_db():
    """Plain AsyncMock database manager -- configure return values per test."""
    return AsyncMock()


@pytest.fixture
def client(mock_db):
    """TestClient against the real app, with get_db_manager overridden to mock_db."""
    app.dependency_overrides[dependencies.get_db_manager] = lambda: mock_db
    yield TestClient(app)
    app.dependency_overrides.clear()
