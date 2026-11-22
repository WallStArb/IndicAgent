"""Migrations that pin one live build (conftest._LIVE_BUILD_ONLY) are not replayed into
indicagent_test; this applies each to the empty test database and asserts its guard refuses and
leaves nothing behind, so the exclusion hides no coverage."""

from __future__ import annotations

import re

import pytest

from tests.integration.conftest import (
    _LIVE_BUILD_ONLY,
    _MIGRATIONS_DIR,
    _migration_number,
    _run_psql_file,
    connect,
)

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]


@pytest.mark.parametrize("number", sorted(_LIVE_BUILD_ONLY))
def test_the_guard_refuses_on_the_empty_test_database_and_changes_nothing(number):
    (path,) = [p for p in _MIGRATIONS_DIR.glob("*.sql") if _migration_number(p) == number]
    with connect() as conn:
        before = conn.execute(
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"
        ).fetchone()[0]
    with pytest.raises(RuntimeError, match=_LIVE_BUILD_ONLY[number][0]):
        _run_psql_file(path)
    with connect() as conn:
        after = conn.execute(
            "SELECT count(*) FROM pg_tables WHERE schemaname = 'public'"
        ).fetchone()[0]
    assert after == before


def test_every_listed_migration_exists():
    numbers = {_migration_number(p) for p in _MIGRATIONS_DIR.glob("*.sql")}
    assert set(_LIVE_BUILD_ONLY) <= numbers


@pytest.mark.parametrize("number", sorted(_LIVE_BUILD_ONLY))
def test_the_stub_creates_what_the_migration_creates(number):
    """The stub names exactly the tables and triggers the migration creates."""
    (path,) = [p for p in _MIGRATIONS_DIR.glob("*.sql") if _migration_number(p) == number]
    text = path.read_text()
    stub = _LIVE_BUILD_ONLY[number][1]
    made = re.findall(r"CREATE (?:TABLE|TRIGGER) (\w+)", stub)
    assert made and all(f"CREATE TABLE {n} " in text or f"CREATE TRIGGER {n}" in text for n in made)
    assert len(re.findall(r"CREATE (?:TABLE|TRIGGER) \w+", text)) == len(made)
    with connect() as conn:
        for name in made:
            found = conn.execute(
                "SELECT (SELECT count(*) FROM pg_class WHERE relname = %s) "
                "+ (SELECT count(*) FROM pg_trigger WHERE tgname = %s)",
                (name, name),
            ).fetchone()[0]
            assert found == 1, name
