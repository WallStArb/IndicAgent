"""
Unit tests for the Controlled Vocabulary API route.

Tests cover:
- GET /api/vocabulary/{namespace} — happy path returns codes/labels/groups for a
  known seeded namespace
- GET /api/vocabulary/{namespace} — unknown namespace returns 404, never a raw
  SQL error / 500
- The namespace path parameter is passed to the DB fetch as a bound parameter,
  never string-interpolated into SQL (T-161-01)

Uses a minimal test_app + TestClient, mirroring tests/unit/api/test_features_route.py.
No real DB required — the vocabulary router uses Depends(get_db_manager), overridden
here with an AsyncMock.
"""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import dependencies
from src.api.routes.vocabulary import router as vocabulary_router

# Minimal test app — avoids lifespan startup (no DB/Redis required)
test_app = FastAPI()
test_app.include_router(vocabulary_router, prefix="/api/vocabulary")


def make_mock_code_row(
    code: str,
    label: str,
    description: str | None = None,
    sort_order: int = 0,
    is_deprecated: bool = False,
) -> dict:
    """Return a dict that mimics an asyncpg Record (subscriptable by key)."""
    return {
        "code": code,
        "label": label,
        "description": description,
        "sort_order": sort_order,
        "is_deprecated": is_deprecated,
    }


REGIME_HMM_ROWS = [
    make_mock_code_row("trending_up", "Trending Up", sort_order=0),
    make_mock_code_row("transition_up", "Transition Up", sort_order=1),
    make_mock_code_row("ranging", "Ranging", sort_order=2),
    make_mock_code_row("transition_down", "Transition Down", sort_order=3),
    make_mock_code_row("trending_down", "Trending Down", sort_order=4),
]

REGIME_HMM_GROUP_ROWS = [
    {"group_name": "trending", "code": "trending_up"},
    {"group_name": "trending", "code": "trending_down"},
    {"group_name": "bullish_bias", "code": "trending_up"},
    {"group_name": "bullish_bias", "code": "transition_up"},
]


@pytest.fixture
def mock_db():
    """AsyncMock database manager."""
    db = AsyncMock()
    return db


@pytest.fixture
def client(mock_db):
    """TestClient with dependency override for get_db_manager."""
    test_app.dependency_overrides[dependencies.get_db_manager] = lambda: mock_db
    yield TestClient(test_app)
    test_app.dependency_overrides.clear()


class TestGetVocabularyHappyPath:
    """GET /api/vocabulary/{namespace} for a known, seeded namespace."""

    def test_known_namespace_returns_200_with_codes(self, client, mock_db):
        mock_db.fetch = AsyncMock(side_effect=[REGIME_HMM_ROWS, REGIME_HMM_GROUP_ROWS])

        response = client.get("/api/vocabulary/regime_hmm")

        assert response.status_code == 200
        data = response.json()
        assert data["namespace"] == "regime_hmm"
        assert "codes" in data
        assert len(data["codes"]) == 5
        codes = {entry["code"] for entry in data["codes"]}
        assert codes == {
            "trending_up",
            "transition_up",
            "ranging",
            "transition_down",
            "trending_down",
        }
        first = data["codes"][0]
        assert first["code"] == "trending_up"
        assert first["label"] == "Trending Up"

    def test_known_namespace_includes_groups(self, client, mock_db):
        mock_db.fetch = AsyncMock(side_effect=[REGIME_HMM_ROWS, REGIME_HMM_GROUP_ROWS])

        response = client.get("/api/vocabulary/regime_hmm")

        assert response.status_code == 200
        data = response.json()
        assert "groups" in data
        assert data["groups"]["trending"] == ["trending_up", "trending_down"]
        assert data["groups"]["bullish_bias"] == ["trending_up", "transition_up"]


class TestGetVocabularyUnknownNamespace:
    """GET /api/vocabulary/{namespace} for a namespace with zero rows."""

    def test_unknown_namespace_returns_404(self, client, mock_db):
        mock_db.fetch = AsyncMock(return_value=[])

        response = client.get("/api/vocabulary/does_not_exist")

        assert response.status_code == 404
        assert response.status_code != 500

    def test_db_error_returns_404_not_500(self, client, mock_db):
        """A DB query error is caught and surfaces as 404, never a raw SQL error/500."""
        mock_db.fetch = AsyncMock(side_effect=RuntimeError("connection refused"))

        response = client.get("/api/vocabulary/regime_hmm")

        assert response.status_code == 404
        assert response.status_code != 500
        assert "connection refused" not in response.text


class TestVocabularyParameterizedQuery:
    """The namespace path parameter must be bound, never string-interpolated."""

    def test_namespace_passed_as_bound_parameter(self, client, mock_db):
        mock_db.fetch = AsyncMock(side_effect=[REGIME_HMM_ROWS, REGIME_HMM_GROUP_ROWS])

        response = client.get("/api/vocabulary/regime_hmm")

        assert response.status_code == 200
        assert mock_db.fetch.await_count == 2

        first_call_args = mock_db.fetch.await_args_list[0][0]
        query_text = first_call_args[0]
        bound_args = first_call_args[1:]

        # namespace must appear as a bound positional argument, not inside the SQL text
        assert "regime_hmm" in bound_args
        assert "regime_hmm" not in query_text
        assert "$1" in query_text

    def test_unknown_namespace_still_uses_bound_parameter(self, client, mock_db):
        mock_db.fetch = AsyncMock(return_value=[])

        client.get("/api/vocabulary/does_not_exist")

        call_args = mock_db.fetch.await_args_list[0][0]
        query_text = call_args[0]
        bound_args = call_args[1:]

        assert "does_not_exist" in bound_args
        assert "does_not_exist" not in query_text
