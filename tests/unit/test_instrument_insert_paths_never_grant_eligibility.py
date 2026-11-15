"""Every non-onboarding insert path writes eligibility flags false and resets them on re-activation.

Phase 174 code review WR-04: compute_eligible defaulted to true and POST /instruments /
DatabaseManager.upsert_instruments did not name it, so a row added or re-activated through
them skipped the compute-readiness predicate. The upsert semantics (new row false, active
row keeps flags, re-activated row resets) were verified against live Postgres in a rolled-
back transaction. The re-activation reset lives in migration 352's trigger + CHECK;
these tests pin the insert shape and the migration's enforcement.
"""

from __future__ import annotations

import asyncio
import re
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import dependencies
from src.api.routes.instruments import router as instruments_router
from src.core.database_manager import DatabaseManager
from src.core.models import AssetClass, Instrument

_FLAGS = ("compute_eligible", "compute_eligible_1d", "live_tradeable")


def _assert_never_grants(sql: str) -> None:
    columns = re.search(r"INSERT INTO instruments \((.*?)\)", sql, re.S).group(1)
    for flag in _FLAGS:
        assert flag in columns, f"insert does not name {flag}; it would take the column default"
    values = re.search(r"VALUES \((.*?)\)", sql, re.S).group(1)
    assert values.count("false") == 3
    on_conflict = sql.split("ON CONFLICT", 1)[1]
    for flag in _FLAGS:
        assert (
            f"{flag} =" not in on_conflict
        ), f"the upsert must not rewrite {flag}; re-activation is handled by the DB trigger"


def test_migration_352_enforces_no_eligibility_while_inactive():
    """The re-activation rule lives in the database for every writer (API PATCH, soft
    delete, upserts). Verified live in a rolled-back transaction: new row f/f/f, active
    re-post keeps flags, soft delete clears, re-activated starts false, direct violation
    rejected by the CHECK even with the trigger disabled."""
    from pathlib import Path

    migration = next(
        (Path(__file__).resolve().parents[2] / "production/migrations").glob("352_*.sql")
    ).read_text()
    assert "BEFORE INSERT OR UPDATE ON instruments" in migration
    assert "IF NEW.is_active IS NOT TRUE THEN" in migration
    assert (
        "CHECK (is_active IS TRUE OR NOT (compute_eligible OR compute_eligible_1d OR "
        "live_tradeable))" in migration
    )
    # The stale rows must be cleared before the CHECK is added, or the ALTER fails.
    assert migration.index("WHERE is_active = false") < migration.index("ADD CONSTRAINT")


@pytest.mark.unit
def test_api_post_instrument_never_grants_eligibility():
    mock_db = MagicMock()
    mock_db.execute_query = AsyncMock(return_value=[{"code": "equity"}])
    mock_db.execute_command = AsyncMock(return_value="INSERT 0 1")
    app = FastAPI()
    app.include_router(instruments_router, prefix="/api")
    app.dependency_overrides[dependencies.get_db_manager] = lambda: mock_db
    response = TestClient(app).post(
        "/api/instruments",
        json={"symbol": "ZZ", "base": "ZZ", "asset_class": "equity", "exchange": "SMART"},
    )
    assert response.status_code == 201, response.text
    _assert_never_grants(mock_db.execute_command.call_args.args[0])


@pytest.mark.unit
def test_upsert_instruments_never_grants_eligibility():
    db = DatabaseManager.__new__(DatabaseManager)
    db.execute_batch = AsyncMock()
    asyncio.run(db.upsert_instruments([Instrument(symbol="ZZ", asset_class=AssetClass.EQUITY)]))
    _assert_never_grants(db.execute_batch.call_args.args[0])


@pytest.mark.unit
def test_api_startup_never_seeds_instruments():
    """The API startup once seeded an empty instruments table from IBKR_CONTRACTS_JSON. Onboarding
    goes through the instrument onboarding SOP only, so the startup path holds no insert call."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "src/api/main.py").read_text()
    assert "upsert_instruments" not in source
    assert "IBKR_CONTRACTS_JSON" not in source
