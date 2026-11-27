"""The database carries its own UTC session timezone (migration 621, todo 614 row 11).

Every `::date` and `date_trunc` in the repo reads the session timezone and 129 call sites open their own connection,
so a server whose postgresql.conf differs (a rebuilt host, the todo 654 image, a standby) would shift dates without
this setting. Skips cleanly when no database is reachable (the live-DB convention, run in the CI DB job).
"""

from __future__ import annotations

import psycopg
import pytest

_LIVE_DB_DSN = "postgresql://postgres:postgres@localhost:5432/indicagent"


def _connect() -> psycopg.Connection:
    try:
        return psycopg.connect(_LIVE_DB_DSN, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("no live database")


def test_the_database_setting_pins_utc() -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT s.setconfig FROM pg_db_role_setting s JOIN pg_database d ON d.oid = s.setdatabase "
            "WHERE d.datname = current_database() AND s.setrole = 0"
        )
        settings = [item for (row,) in cur.fetchall() for item in row]
    assert "timezone=UTC" in settings
