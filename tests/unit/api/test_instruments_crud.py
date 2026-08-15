"""
Unit tests for POST/PUT/DELETE endpoints in src/api/routes/instruments.py.

Uses a test-local FastAPI app (avoids main.py lifespan) with the db_manager
dependency overridden via FastAPI's dependency injection mechanism.

All DB calls are captured by the mock; no real database is required.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import dependencies
from src.api.routes.instruments import router as instruments_router

# ---------------------------------------------------------------------------
# Test app setup (avoids main.py lifespan)
# ---------------------------------------------------------------------------

test_app = FastAPI()
test_app.include_router(instruments_router, prefix="/api")


def _make_mock_db(
    query_rows: list | None = None,
    command_status: str = "UPDATE 1",
    asset_class_valid: bool = True,
):
    """Build a mock db_manager that captures SQL calls.

    Args:
        query_rows: Rows returned by execute_query for non-CVR lookups, e.g. the
            "does this symbol exist" check (default: [{"symbol": "AAPL"}]).
        command_status: Status string returned by execute_command (default: "UPDATE 1").
        asset_class_valid: Controls the response to the `controlled_vocabulary`
            asset_class lookup specifically (todo 326) -- True returns a matching
            row (code is registered), False returns no rows (code is not
            registered, triggers a 422). Distinguished from query_rows by
            inspecting the SQL text, since both lookups go through the same
            execute_query method.
    """
    if query_rows is None:
        query_rows = [{"symbol": "AAPL"}]

    async def _execute_query(sql, *args):
        if "controlled_vocabulary" in sql:
            return [{"code": args[-1]}] if asset_class_valid else []
        return query_rows

    mock_db = MagicMock()
    mock_db.execute_query = AsyncMock(side_effect=_execute_query)
    mock_db.execute_command = AsyncMock(return_value=command_status)
    return mock_db


def _make_client(mock_db) -> TestClient:
    """Build a TestClient with the db_manager dependency overridden."""
    test_app.dependency_overrides[dependencies.get_db_manager] = lambda: mock_db
    return TestClient(test_app)


# ---------------------------------------------------------------------------
# POST /api/instruments
# ---------------------------------------------------------------------------


class TestPostInstrument:
    """Tests for POST /api/instruments."""

    @pytest.mark.unit
    def test_post_instrument_creates_row(self):
        """POST with valid payload returns 201 and the mock DB received an INSERT."""
        mock_db = _make_mock_db(command_status="INSERT 0 1")
        client = _make_client(mock_db)

        response = client.post(
            "/api/instruments",
            json={
                "symbol": "AAPL",
                "base": "AAPL",
                "asset_class": "equity",
                "exchange": "NASDAQ",
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "created"
        assert body["symbol"] == "AAPL"

        # Verify the mock db received an execute_command call with INSERT
        mock_db.execute_command.assert_called_once()
        sql_called = mock_db.execute_command.call_args.args[0]
        assert "INSERT INTO instruments" in sql_called
        assert "ON CONFLICT" in sql_called

    @pytest.mark.unit
    def test_post_instrument_invalid_asset_class_rejected(self):
        """POST with an unregistered asset_class returns 422.

        Checked against the CVR `asset_class` namespace at request time (todo 326),
        not a static Pydantic Literal -- so the mock DB is the thing saying "no".
        """
        mock_db = _make_mock_db(asset_class_valid=False)
        client = _make_client(mock_db)

        response = client.post(
            "/api/instruments",
            json={
                "symbol": "AAPL",
                "base": "AAPL",
                "asset_class": "bogus",
                "exchange": "NASDAQ",
            },
        )

        assert response.status_code == 422
        # DB write should never have been called
        mock_db.execute_command.assert_not_called()

    @pytest.mark.unit
    def test_post_instrument_crypto_asset_class_rejected(self):
        """POST with asset_class="crypto" returns 422 -- todo 326 regression test.

        CVR's `asset_class` namespace has exactly 3 live codes (equity/futures/fx;
        migration 233). Before this fix, `InstrumentUpsert.asset_class` was a static
        Pydantic `Literal` that included "crypto" -- a value that exists nowhere in
        the registry or `get_active_contracts()` (verified 2026-08-15: zero
        instruments have asset_class='crypto'; crypto-exposed names like MARA/MSTR/
        IBIT/COIN are all correctly classified 'equity'). The endpoint should defer
        to the registry, not a hand-typed copy that already drifted from it.
        """
        mock_db = _make_mock_db(asset_class_valid=False)
        client = _make_client(mock_db)

        response = client.post(
            "/api/instruments",
            json={
                "symbol": "MSTR",
                "base": "MSTR",
                "asset_class": "crypto",
                "exchange": "NASDAQ",
            },
        )

        assert response.status_code == 422
        mock_db.execute_command.assert_not_called()

    @pytest.mark.unit
    def test_post_instrument_symbol_uppercased(self):
        """POST with lowercase symbol: response symbol is uppercased."""
        mock_db = _make_mock_db(command_status="INSERT 0 1")
        client = _make_client(mock_db)

        response = client.post(
            "/api/instruments",
            json={"symbol": "tsla", "base": "tsla", "asset_class": "equity"},
        )

        assert response.status_code == 201
        assert response.json()["symbol"] == "TSLA"


# ---------------------------------------------------------------------------
# PUT /api/instruments/{symbol}
# ---------------------------------------------------------------------------


class TestPutInstrument:
    """Tests for PUT /api/instruments/{symbol}."""

    @pytest.mark.unit
    def test_put_instrument_updates_existing(self):
        """PUT with is_active=false for existing symbol returns 200 and the mock saw UPDATE."""
        mock_db = _make_mock_db(
            query_rows=[{"symbol": "AAPL"}],
            command_status="UPDATE 1",
        )
        client = _make_client(mock_db)

        response = client.put(
            "/api/instruments/AAPL",
            json={"is_active": False},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "updated"
        assert body["symbol"] == "AAPL"

        # Verify at least one UPDATE was issued
        assert mock_db.execute_command.call_count >= 1
        sql_called = mock_db.execute_command.call_args_list[0].args[0]
        assert "UPDATE instruments" in sql_called

    @pytest.mark.unit
    def test_put_instrument_404_when_missing(self):
        """PUT for a non-existent symbol (query returns []) returns 404."""
        mock_db = _make_mock_db(query_rows=[])
        client = _make_client(mock_db)

        response = client.put(
            "/api/instruments/NONEXISTENT",
            json={"is_active": False},
        )

        assert response.status_code == 404
        # DB command should not have been called
        mock_db.execute_command.assert_not_called()

    @pytest.mark.unit
    def test_put_instrument_invalid_tick_size_type_rejected(self):
        """PUT with tick_size as string returns 422 (Pydantic rejects string for float field)."""
        mock_db = _make_mock_db()
        client = _make_client(mock_db)

        response = client.put(
            "/api/instruments/AAPL",
            json={"tick_size": "bad"},
        )

        assert response.status_code == 422
        mock_db.execute_command.assert_not_called()

    @pytest.mark.unit
    def test_put_instrument_crypto_asset_class_rejected(self):
        """PUT with asset_class="crypto" on an existing symbol returns 422.

        Todo 326 regression test -- same CVR-registry check as the POST path,
        exercised on the update path (asset_class is optional there, so the check
        must only fire when the field is actually present in the payload).
        """
        mock_db = _make_mock_db(
            query_rows=[{"symbol": "AAPL"}],
            asset_class_valid=False,
        )
        client = _make_client(mock_db)

        response = client.put(
            "/api/instruments/AAPL",
            json={"asset_class": "crypto"},
        )

        assert response.status_code == 422
        mock_db.execute_command.assert_not_called()


# ---------------------------------------------------------------------------
# DELETE /api/instruments/{symbol}
# ---------------------------------------------------------------------------


class TestDeleteInstrument:
    """Tests for DELETE /api/instruments/{symbol}."""

    @pytest.mark.unit
    def test_delete_instrument_soft_deletes(self):
        """DELETE returns 200 and the SQL is UPDATE (not hard DELETE)."""
        mock_db = _make_mock_db(command_status="UPDATE 1")
        client = _make_client(mock_db)

        response = client.delete("/api/instruments/AAPL")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "deactivated"
        assert body["symbol"] == "AAPL"

        # Critical: soft-delete uses UPDATE, not hard DELETE
        mock_db.execute_command.assert_called_once()
        sql_called = mock_db.execute_command.call_args.args[0]
        assert "UPDATE instruments" in sql_called
        assert "is_active = false" in sql_called
        assert sql_called.strip().upper().startswith("UPDATE")

    @pytest.mark.unit
    def test_delete_instrument_404_when_missing(self):
        """DELETE with 0 rows affected (UPDATE 0) returns 404."""
        mock_db = _make_mock_db(command_status="UPDATE 0")
        client = _make_client(mock_db)

        response = client.delete("/api/instruments/NONEXISTENT")

        assert response.status_code == 404
