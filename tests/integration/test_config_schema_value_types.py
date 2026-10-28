"""Integration test: every config_schema.value_type is one ConfigService accepts (todo 556).

A row with an unknown type ('integer', 'text') makes ConfigService.set raise, so the key can
only change by direct SQL, which skips validation and the config_history outbox.

Runs against indicagent_test (migrations replayed by tests/integration/conftest.py).
Run: pytest tests/integration/test_config_schema_value_types.py -m integration
"""

from __future__ import annotations

import pytest

from tests.integration.conftest import connect

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

_KNOWN_TYPES = ("int", "float", "bool", "str", "string", "json")


def test_every_config_schema_value_type_is_known() -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT config_key, value_type FROM config_schema "
            "WHERE lower(value_type) <> ALL(%s) ORDER BY config_key",
            (list(_KNOWN_TYPES),),
        )
        bad = cur.fetchall()
    assert bad == [], f"config_schema rows with a value_type ConfigService rejects: {bad}"
