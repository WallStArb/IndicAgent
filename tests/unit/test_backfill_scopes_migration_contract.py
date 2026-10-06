"""Migration 445 contract: vendor 15m and 1h leave every default fetch scope (data layer integrity spec, step 1)."""

import json
import re
from pathlib import Path

_SQL = (
    Path(__file__).resolve().parents[2]
    / "production/migrations/445_backfill_scopes_stop_vendor_htf.sql"
).read_text()
_CODE = "\n".join(line for line in _SQL.splitlines() if not line.lstrip().startswith("--"))
_HEADER = "\n".join(line for line in _SQL.splitlines() if line.lstrip().startswith("--"))


def _set_value(key: str) -> str:
    for statement in _CODE.split(";"):
        if f"WHERE config_key = '{key}'" in statement and "UPDATE config_state" in statement:
            match = re.search(r"SET config_value = '([^']*)'", statement)
            assert match, key
            return match.group(1)
    raise AssertionError(f"no UPDATE for {key}")


def test_default_scopes_pinned_to_compute_1d_daily_and_5m():
    value = json.loads(_set_value("infra.backfill.default_scopes"))
    assert value == {"compute_1d": ["1d", "5m"]}


def test_priority_tf_order_pinned_to_5m():
    assert json.loads(_set_value("infra.backfill.priority_tf_order")) == ["5m"]


def test_no_vendor_15m_or_1h_in_any_new_value():
    for key in ("infra.backfill.default_scopes", "infra.backfill.priority_tf_order"):
        value = _set_value(key)
        assert "15m" not in value and "1h" not in value


def test_version_bump_and_history_rows():
    assert _CODE.count("version = version + 1") == 2
    assert "INSERT INTO config_history" in _CODE
    assert "'migration 445'" in _CODE


def test_header_records_previous_values_and_rollback():
    assert (
        '{"compute": ["1d", "1h", "15m", "5m"], "compute_1d": ["1d"], "backfill": ["1h", "15m"]}'
        in _HEADER
    )
    assert '["15m", "1h"]' in _HEADER
    assert "Rollback" in _HEADER


def test_wrapped_in_transaction():
    assert _CODE.strip().startswith("BEGIN;")
    assert _CODE.strip().endswith("COMMIT;")
