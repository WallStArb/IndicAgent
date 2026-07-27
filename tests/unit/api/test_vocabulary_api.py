"""
Unit tests for the Controlled Vocabulary API route.

Tests cover:
- GET /api/vocabulary/{namespace} — happy path returns codes/labels/groups for a
  known seeded namespace, including per-group label/description and empty-but-known
  groups (LEFT JOIN)
- GET /api/vocabulary/{namespace} — unknown namespace (zero code rows) returns 404;
  a genuine backend failure on the codes query returns 503 instead, never a raw
  SQL error / 500
- A group-query failure degrades to groups_available=false rather than silently
  looking identical to "this namespace has no groups"
- The namespace path parameter is passed to the DB fetch as a bound parameter,
  never string-interpolated into SQL (T-161-01)

Uses the shared `client`/`mock_db` fixtures (tests/unit/api/conftest.py, todo 143).
No real DB required — the vocabulary router uses Depends(get_db_manager), overridden
here with an AsyncMock.
"""

from unittest.mock import AsyncMock


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
    {"group_name": "trending", "label": "Trending", "description": None, "code": "trending_up"},
    {"group_name": "trending", "label": "Trending", "description": None, "code": "trending_down"},
    {
        "group_name": "bullish_bias",
        "label": "Bullish Bias",
        "description": "Upward-biased regimes",
        "code": "trending_up",
    },
    {
        "group_name": "bullish_bias",
        "label": "Bullish Bias",
        "description": "Upward-biased regimes",
        "code": "transition_up",
    },
]


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
        assert data["groups_available"] is True
        assert data["groups"]["trending"] == {
            "label": "Trending",
            "description": None,
            "codes": ["trending_up", "trending_down"],
        }
        assert data["groups"]["bullish_bias"] == {
            "label": "Bullish Bias",
            "description": "Upward-biased regimes",
            "codes": ["trending_up", "transition_up"],
        }

    def test_group_with_no_members_still_appears_with_empty_codes(self, client, mock_db):
        """A vocabulary_group row with zero members (LEFT JOIN -> NULL code) is a
        real-but-empty group, distinguishable from an unknown one -- not silently
        dropped from the response."""
        empty_group_rows = [
            {"group_name": "trending", "label": "Trending", "description": None, "code": None}
        ]
        mock_db.fetch = AsyncMock(side_effect=[REGIME_HMM_ROWS, empty_group_rows])

        response = client.get("/api/vocabulary/regime_hmm")

        assert response.status_code == 200
        data = response.json()
        assert data["groups"]["trending"] == {"label": "Trending", "description": None, "codes": []}

    def test_group_query_failure_sets_groups_available_false(self, client, mock_db):
        """A group-query failure must not look identical to 'this namespace has no
        groups' -- groups_available signals the partial failure to callers."""
        mock_db.fetch = AsyncMock(side_effect=[REGIME_HMM_ROWS, RuntimeError("connection refused")])

        response = client.get("/api/vocabulary/regime_hmm")

        assert response.status_code == 200
        data = response.json()
        assert data["groups"] == {}
        assert data["groups_available"] is False
        assert "connection refused" not in response.text


class TestGetVocabularyUnknownNamespace:
    """GET /api/vocabulary/{namespace} for a namespace with zero rows."""

    def test_unknown_namespace_returns_404(self, client, mock_db):
        mock_db.fetch = AsyncMock(return_value=[])

        response = client.get("/api/vocabulary/does_not_exist")

        assert response.status_code == 404
        assert response.status_code != 500

    def test_codes_query_db_error_returns_503_not_404(self, client, mock_db):
        """A backend failure on the primary codes query is a 503 (retry-worthy),
        distinct from a genuinely unknown namespace (404, don't retry) -- and never
        a raw SQL error / 500."""
        mock_db.fetch = AsyncMock(side_effect=RuntimeError("connection refused"))

        response = client.get("/api/vocabulary/regime_hmm")

        assert response.status_code == 503
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
