"""Tests for database migrations (Phase 67)."""


def test_062_market_data_gaps_sql_parseable():
    """Verify migration 062 has required table name and constraint."""
    import pathlib

    # Resolve path relative to test file location (tests/unit -> project root is ../..)
    project_root = pathlib.Path(__file__).resolve().parent.parent.parent
    sql_path = project_root / "production" / "migrations" / "062_market_data_gaps.sql"
    assert sql_path.exists(), "Migration file 062_market_data_gaps.sql does not exist"

    sql = sql_path.read_text()

    # Check for required table (allow IF NOT EXISTS)
    assert "CREATE TABLE" in sql and "market_data_gaps" in sql, "Missing CREATE TABLE market_data_gaps"

    # Check for unique constraint
    assert "UNIQUE" in sql, "Missing UNIQUE constraint"

    # Check for required columns
    assert "gap_start_ts" in sql, "Missing gap_start_ts column"
    assert "resolved_at" in sql, "Missing resolved_at column"
