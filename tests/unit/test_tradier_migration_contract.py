"""Migration 438 contract: D1 drops its append-only guards, Tradier daily source tables and APR keys."""

from pathlib import Path

_SQL = (
    Path(__file__).resolve().parents[2] / "production/migrations/438_tradier_daily_source.sql"
).read_text()
_CODE = "\n".join(line for line in _SQL.splitlines() if not line.lstrip().startswith("--"))


def test_all_four_guards_and_the_function_are_dropped():
    for table in ("ohlcv_request", "ohlcv_observation"):
        assert f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}" in _CODE
        assert f"DROP TRIGGER IF EXISTS trg_{table}_no_truncate ON {table}" in _CODE
    assert "DROP FUNCTION IF EXISTS ohlcv_d1_append_only()" in _CODE


def test_writer_role_gains_update_delete_derivation_role_untouched():
    assert (
        "GRANT UPDATE, DELETE ON ohlcv_request, ohlcv_observation TO ohlcv_observation_writer"
        in _CODE
    )
    assert "bar_derivation_writer" not in _CODE


def test_request_source_check_admits_tradier():
    assert "CHECK (source IN ('ibkr', 'tradier'))" in _CODE


def test_every_apr_key_has_schema_and_state_rows():
    keys = {
        "history_start",
        "request_timeout_s",
        "concurrency",
        "min_session_ratio",
        "first_date_tolerance_days",
        "max_changed_bar_ratio",
    }
    for key in keys:
        assert _CODE.count(f"'infra.tradier.{key}'") >= 1
        assert f"('infra.tradier.{key}'," in _CODE
