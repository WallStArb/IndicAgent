"""Pure tests for the ohlcv_raw backfill SQL builders and report arithmetic (plan 191-03)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from scripts.ops.bars import ops_raw_backfill as mod
from src.intelligence.bars.vendor_kind import LABEL_TO_VENDOR_KIND


def test_label_values_come_from_vendor_kind_and_skip_derived():
    sql = mod.build_vendor_kind_values_sql()
    for label, (vendor, kind) in LABEL_TO_VENDOR_KIND.items():
        if vendor == "derived" or kind in mod.CANONICAL_ONLY_KINDS:
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


def test_finalize_unexplained_canonical_diff_fails_and_logged_disagreement_does_not():
    t = _balanced()
    t["canonical_vendor"].update(twin_equal=4, twin_diff=1)
    r = mod.finalize_report(t)
    assert r["value_mismatches"] == 1 and r["exit_code"] == 1
    t = _balanced()
    t["canonical_vendor"].update(twin_equal=5, twin_diff=0)
    t["store_disagreement"]["canonical_vs_archive"] = 3  # informational: logged as revisions
    r = mod.finalize_report(t)
    assert r["value_mismatches"] == 0 and r["exit_code"] == 0


def test_canonical_class_count_excludes_keys_whose_value_is_logged():
    sql = mod._count_class_sql("src AS (SELECT 1)", logged_is_explained=True)
    assert "NOT EXISTS" in sql and "raw-backfill-191" in sql
    assert "NOT EXISTS" not in mod._count_class_sql("src AS (SELECT 1)")


def test_reconcile_replaces_only_on_a_later_serve_and_logs_canonical_only_values():
    displaced = mod.reconcile_displaced_sql("src AS (SELECT 1)")
    assert "s.served_at > r.served_at" in displaced and "IS DISTINCT FROM" in displaced
    update = mod.reconcile_update_sql("src AS (SELECT 1)")
    assert "UPDATE ohlcv_raw r" in update and "s.served_at > r.served_at" in update
    canonical = mod.reconcile_canonical_only_sql("src AS (SELECT 1)")
    assert "NOT EXISTS" in canonical and "NULL::uuid" in canonical


def test_canonical_only_kinds_never_enter_raw_from_the_label_map():
    assert all(kind not in mod.CANONICAL_ONLY_KINDS for _v, kind in mod.vendor_labels().values())
    assert "ibkr_fallback" not in mod.vendor_labels()


def test_write_reconcile_revisions_makes_one_load_per_vendor_and_timeframe():
    class Cur:
        def __init__(self):
            self.loads = 0
            self.revs = 0

        def execute(self, sql, params=None):
            if "INSERT INTO ohlcv_load" in sql:
                self.loads += 1
            if "INSERT INTO ohlcv_revision" in sql:
                self.revs += len(params) // 13

    ts = datetime(2026, 9, 23, 13, 30, tzinfo=UTC)
    rows = [
        (ts, "AEP", "5m", "ibkr", "named", 1.0, 2.0, 0.5, 1.5, 48913, None),
        (ts, "AEP", "1d", "ibkr", "smart_trades", 1.0, 2.0, 0.5, 1.5, 10, None),
    ]
    cur = Cur()
    assert mod.write_reconcile_revisions(cur, "AEP", "canonical", rows) == 2
    assert (cur.loads, cur.revs) == (2, 2)


def test_finalize_1d_row_without_request_id_is_unexplained():
    t = _balanced()
    t["raw_null_provenance"]["1d|served_at_set|request_id_null|load_id_null"] = 2
    assert mod.finalize_report(t)["unexplained"] == 2


# --- revision reconstruction (plan 191-04, D-191-E) ---------------------------------------


def _obs_sql() -> str:
    return mod.build_observation_values_sql(
        mod.map_observation_triples([("ibkr", "SMART", "TRADES")])
    )


def test_superseded_runs_sql_is_symbol_wide_and_excludes_test_callers():
    sql = mod.superseded_runs_sql(_obs_sql())
    assert "%(lo)s" not in sql and "%(hi)s" not in sql
    assert "%(symbol)s" in sql
    assert "NOT LIKE 'test-%%'" in sql
    assert "g.run < g.last_run" in sql
    assert "ORDER BY fetched_at, request_id" in sql


def test_superseded_runs_exclude_runs_first_served_before_the_session_close():
    sql = mod.superseded_runs_sql(_obs_sql())
    assert "min(fetched_at) AS first_fetched_at" in sql
    assert "g.first_fetched_at >= sc.close_at" in sql
    # AAPL 2026-09-30: a session close row (20:00 UTC) is in the calendar VALUES
    assert "('2026-09-30'::date, '2026-09-30T20:00:00+00:00'::timestamptz)" in sql
    # the balance check applies the same filter, so wrongly stored rows surface as unexplained
    assert "g.first_fetched_at >= sc.close_at" in mod.revision_balance_sql(_obs_sql())


def test_windowed_observation_cte_is_unchanged():
    assert "%(lo)s" in mod.observation_current_cte(_obs_sql())


def test_plan_groups_runs_by_vendor_and_ordinal_across_kinds():
    d1, d2 = datetime(2020, 1, 2).date(), datetime(2020, 1, 3).date()
    runs = [
        (d1, "ibkr", "named", 1, "r1", 1.0, 2.0, 0.5, 1.5, 10),
        (d1, "ibkr", "venue", 1, "r2", 1.0, 2.0, 0.5, 1.5, 10),
        (d2, "ibkr", "named", 2, "r3", 1.0, 2.0, 0.5, 1.6, 10),
        (d2, "tradier", "consolidated", 1, "r4", 1.0, 2.0, 0.5, 1.5, 10),
    ]
    plans = mod.plan_revision_loads("AAA", runs)
    assert [(p.vendor, p.ordinal, len(p.rows)) for p in plans] == [
        ("ibkr", 1, 2),
        ("ibkr", 2, 1),
        ("tradier", 1, 1),
    ]
    first = plans[0]
    assert first.first_bar == d1 and first.last_bar == d1
    assert "ordinal=1;" in first.detail and "raw-backfill-191" in first.detail


def test_existing_ordinals_parse_from_load_detail():
    class Cur:
        def execute(self, *_a):
            pass

        def fetchall(self):
            return [("ibkr", "raw-backfill-191 revisions ordinal=3; bar_date x to y"), ("a", None)]

    assert mod.existing_revision_ordinals(Cur(), "AAA") == {("ibkr", 3)}


def test_write_skips_loads_already_written():
    class Cur:
        def __init__(self):
            self.loads = 0
            self.revs = 0

        def execute(self, sql, params=None):
            if "INSERT INTO ohlcv_load" in sql:
                self.loads += 1
            if "INSERT INTO ohlcv_revision" in sql:
                self.revs += len(params) // 12

    d = datetime(2020, 1, 2).date()
    plans = mod.plan_revision_loads(
        "AAA",
        [
            (d, "ibkr", "named", 1, "r1", 1.0, 2.0, 0.5, 1.5, 10),
            (d, "ibkr", "named", 2, "r2", 1.0, 2.0, 0.5, 1.6, 10),
        ],
    )
    cur = Cur()
    assert mod.write_revision_loads(cur, plans, {("ibkr", 1)}) == (1, 1)
    assert (cur.loads, cur.revs) == (1, 1)
    cur2 = Cur()
    assert mod.write_revision_loads(cur2, plans, {("ibkr", 1), ("ibkr", 2)}) == (0, 0)


def test_revision_unexplained_counts_missing_and_extra_rows():
    assert mod.revision_unexplained(runs=10, missing=0, stored=10) == 0
    assert mod.revision_unexplained(runs=10, missing=2, stored=8) == 2
    assert mod.revision_unexplained(runs=10, missing=0, stored=12) == 2


def test_finalize_counts_unexplained_revisions():
    totals = mod.new_report_totals()
    totals["revisions"] = {"superseded_runs": 5, "missing": 1, "stored": 4}
    assert mod.finalize_report(totals)["unexplained"] == 1
    assert totals["exit_code"] == 1


def test_canonical_disagreeing_select_is_driven_from_the_archive_twin():
    sql = mod.canonical_disagreeing_select_sql()
    assert "FROM ohlcv_intraday_raw_archive a" in sql
    # 191-15: the archive keeps its source label; canonical is reached by (vendor, kind)
    assert "l.label = a.source" in sql
    assert "m.vendor = l.vendor AND m.kind = l.kind" in sql
    assert "m.source" not in sql
    assert "m.timeframe <> '1d'" in sql and "'ibkr_fallback'" not in sql


def test_canonical_select_filters_raw_pairs_without_a_source_join():
    """191-15: canonical rows carry (vendor, kind); the raw-eligible filter is a pair
    membership test, never a join on a source label."""
    sql = mod.canonical_select_sql()
    assert "FROM market_data_ohlcv m" in sql
    assert "m.vendor, m.kind" in sql and "m.source" not in sql
    assert "ON l.label = m.source" not in sql
    for vendor, kind in sorted(set(mod.vendor_labels().values())):
        assert f"('{vendor}', '{kind}')" in sql
    assert "('derived', '5m_grid')" not in sql


def test_canonical_balance_sql_reads_pairs_not_source():
    for sql in (mod._CANONICAL_VS_ARCHIVE_SQL, mod._CANONICAL_DISAGREE_SAMPLE_SQL):
        assert "m.source" not in sql and "a.source = m.source" not in sql
    assert "GROUP BY 1, 2, 3" in mod._EXCLUSION_SQL and "source" not in mod._EXCLUSION_SQL
    twin = mod._canonical_1d_twin_sql()
    assert "k.source = m.vendor" in twin and "m.source" not in twin
    union = mod._union_keys_sql(
        mod.build_observation_values_sql([("ibkr", "SMART", "TRADES", "smart_trades")])
    )
    assert "l.label = m.source" not in union and "m.vendor, m.kind" in union


def test_forming_revision_select_targets_runs_first_served_before_the_close():
    sql = mod.forming_revision_symbols_sql()
    assert "l.caller = 'raw-backfill-191'" in sql
    assert "o.fetched_at < sc.close_at" in sql
    assert "('2026-09-30'::date, '2026-09-30T20:00:00+00:00'::timestamptz)" in sql


def test_rebuild_deletes_reconstruction_loads_then_rewrites():
    calls: list[str] = []

    class Cur:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def execute(self, sql, params=None):
            calls.append(sql.split()[0] + " " + ("ohlcv_load" if "ohlcv_load" in sql else "other"))

        def fetchall(self):
            return []

    class Conn:
        commits = 0

        def cursor(self):
            return Cur()

        def commit(self):
            self.commits += 1

        def rollback(self):
            pass

    conn = Conn()
    mod.rebuild_symbol_revisions(conn, "AAA", obs_values_sql=_obs_sql())
    assert calls[0] == "DELETE ohlcv_load"
    assert conn.commits == 1
