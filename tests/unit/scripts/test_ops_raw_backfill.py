"""Pure tests for the ohlcv_raw backfill SQL builders and report arithmetic (plan 191-03)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scripts.ops.bars import ops_raw_backfill as mod
from src.intelligence.bars.vendor_kind import LABEL_TO_VENDOR_KIND


def test_label_values_come_from_vendor_kind_and_skip_derived():
    sql = mod.build_vendor_kind_values_sql()
    for label, (vendor, kind) in LABEL_TO_VENDOR_KIND.items():
        if vendor == "derived":
            assert f"'{label}'" not in sql
        else:
            assert f"('{label}', '{vendor}', '{kind}')" in sql


def test_observation_values_map_through_observation_kind():
    mapped = mod.map_observation_triples(
        [
            ("ibkr", "SMART", "TRADES"),
            ("ibkr", "SMART", "ADJUSTED_LAST"),
            ("tradier", "TRADIER", "TRADES"),
        ]
    )
    sql = mod.build_observation_values_sql(mapped)
    assert "'smart_trades'" in sql and "'smart_adjusted'" in sql and "'consolidated'" in sql


def test_unmapped_observation_triple_raises():
    with pytest.raises(ValueError):
        mod.map_observation_triples([("ibkr", "SMART", "BID")])


def test_literal_rejects_injection():
    with pytest.raises(ValueError):
        mod._lit("x'; drop table y; --")


def test_canonical_pass_excludes_1d_and_invents_nothing():
    sql = mod.canonical_select_sql()
    assert "m.timeframe <> '1d'" in sql
    assert "NULL::timestamptz AS served_at" in sql
    assert "NULL::uuid AS request_id" in sql and "NULL::uuid AS load_id" in sql
    assert "derived_5m" not in sql


def test_archive_pass_uses_true_archived_at():
    sql = mod.archive_select_sql()
    assert "a.archived_at AS served_at" in sql
    assert "NULL::uuid AS request_id" in sql


def test_observation_pass_excludes_test_callers_and_stamps_first_serve_of_latest_value():
    sql = mod.observation_select_sql(
        mod.build_observation_values_sql([("ibkr", "SMART", "TRADES", "smart_trades")])
    )
    assert "NOT LIKE 'test-%%'" in sql
    assert "DISTINCT ON (symbol, bar_date, vendor, kind)" in sql
    assert "AT TIME ZONE 'UTC'" in sql
    assert "fetched_at AS served_at" in sql


def test_insert_is_idempotent_on_the_full_key():
    sql = mod.insert_sql("SELECT 1")
    assert sql.endswith("ON CONFLICT (timestamp, symbol, timeframe, vendor, kind) DO NOTHING")
    assert sql.startswith("INSERT INTO ohlcv_raw")


def test_split_range_is_day_aligned_and_covers_window():
    lo, hi = mod.window_bounds(2025)
    parts = mod.split_range(lo, hi, 7)
    assert parts[0][0] == lo and parts[-1][1] == hi
    assert all(a[1] == b[0] for a, b in zip(parts, parts[1:], strict=False))
    assert all(p[0] == p[0].replace(hour=0, minute=0) for p in parts)
    assert mod.split_range(lo, hi, 1) == [(lo, hi)]
    assert len(mod.split_range(lo, datetime(2025, 1, 3, tzinfo=UTC), 50)) == 2


def test_window_is_current_only_when_counts_equal():
    c = mod.WindowCounts(1, 2, 3)
    done = {("AAPL", 2024): {"canonical": 1, "archive": 2, "observation": 3}}
    assert mod.window_is_current(done, "AAPL", 2024, c)
    assert not mod.window_is_current(done, "AAPL", 2024, mod.WindowCounts(2, 2, 3))
    assert not mod.window_is_current(done, "MSFT", 2024, c)


def _balanced():
    t = mod.new_report_totals()
    for cls in ("canonical_vendor", "archive", "observation"):
        t[cls].update(source_rows=5, twin_equal=5)
    return t


def test_finalize_balanced_exits_zero():
    t = mod.finalize_report(_balanced())
    assert t["unexplained"] == 0 and t["value_mismatches"] == 0 and t["exit_code"] == 0


def test_finalize_missing_twin_is_unexplained():
    t = _balanced()
    t["archive"].update(twin_equal=4, twin_missing=1)
    assert mod.finalize_report(t)["exit_code"] == 1


def test_finalize_unlabelled_source_is_unexplained():
    t = _balanced()
    t["unlabelled_source_rows"]["canonical"]["mystery"] = 3
    assert mod.finalize_report(t)["unexplained"] == 3


def test_finalize_canonical_diff_needs_store_disagreement_and_still_fails_gate():
    t = _balanced()
    t["canonical_vendor"].update(twin_equal=4, twin_diff=1)
    r = mod.finalize_report(t)
    assert r["value_mismatches"] == 1
    t = _balanced()
    t["canonical_vendor"].update(twin_equal=4, twin_diff=1)
    t["store_disagreement"]["canonical_vs_archive"] = 1
    r = mod.finalize_report(t)
    assert r["value_mismatches"] == 0 and r["exit_code"] == 1


def test_finalize_1d_row_without_request_id_is_unexplained():
    t = _balanced()
    t["raw_null_provenance"]["1d|served_at_set|request_id_null|load_id_null"] = 2
    assert mod.finalize_report(t)["unexplained"] == 2
