"""`_replace_group_tf` against a real PostgreSQL (todo 420, 186-18 follow-up).

The test shadows `market_regimes` and `market_regimes_override` with session temp tables of the
same shape, so the function's unqualified names resolve to them and no permanent table is read or
written. Equality: the end state equals the old delete-everything-and-reinsert result for a mix of
unchanged, changed, new and orphaned rows, and the rows physically written equal the diff (rows
untouched by the replace keep their `xmin`).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from services.cross_sectional_regime_model import (
    ReplaceGuards,
    ReplaceRefused,
    _replace_group_tf,
)

pytestmark = [pytest.mark.integration, pytest.mark.requires_db]

_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent_test"
_T0 = datetime(2024, 1, 1, tzinfo=UTC)
_GUARDS = ReplaceGuards(
    max_orphan_fraction=1.0, max_changed_fraction=1.0, operator="test", reason="test"
)


@pytest.fixture
def conn():
    connection = psycopg.connect(_TEST_DB_URL)
    connection.autocommit = False
    with connection.cursor() as cur:
        cur.execute(
            "CREATE TEMP TABLE market_regimes (regime_group text NOT NULL, tf text NOT NULL, "
            "ts timestamptz NOT NULL, regime_label text NOT NULL, regime_prob_vector jsonb, "
            "PRIMARY KEY (regime_group, tf, ts))"
        )
        cur.execute(
            "CREATE TEMP TABLE market_regimes_override (override_id bigserial PRIMARY KEY, "
            "decided_at timestamptz NOT NULL, regime_group text, tf text, stored bigint, "
            "orphaned bigint, changed bigint, accepted_orphans bigint, accepted_changed bigint, "
            "operator text, reason text)"
        )
    connection.commit()
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def _row(group, tf, i, label, p=0.5):
    return (group, tf, _T0 + timedelta(days=i), label, {"p": p})


def _seed(conn, rows):
    import json

    with conn.cursor() as cur:
        for r in rows:
            cur.execute(
                "INSERT INTO market_regimes VALUES (%s, %s, %s, %s, %s::jsonb)",
                (r[0], r[1], r[2], r[3], json.dumps(r[4])),
            )
    conn.commit()


def _table(conn, group, tf):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ts, regime_label, regime_prob_vector, xmin::text::bigint FROM market_regimes "
            "WHERE regime_group = %s AND tf = %s ORDER BY ts",
            (group, tf),
        )
        return cur.fetchall()


def test_end_state_equals_delete_all_and_reinsert_and_writes_only_the_diff(conn):
    stored = (
        [_row("equity", "1d", i, "a") for i in range(0, 6)]  # 0-5 unchanged
        + [_row("equity", "1d", i, "old") for i in range(6, 9)]  # 6-8 changed label
        + [_row("equity", "1d", 9, "a", p=0.1)]  # 9 changed vector only
        + [_row("equity", "1d", i, "orphan") for i in range(20, 24)]  # 20-23 orphaned
        + [_row("equity", "5m", 0, "other_tf"), _row("rates", "1d", 0, "other_group")]
    )
    _seed(conn, stored)
    produced = (
        [_row("equity", "1d", i, "a") for i in range(0, 6)]
        + [_row("equity", "1d", i, "new_label") for i in range(6, 9)]
        + [_row("equity", "1d", 9, "a", p=0.9)]
        + [_row("equity", "1d", i, "fresh") for i in range(30, 33)]  # 30-32 new
    )
    before = {r[0]: r for r in _table(conn, "equity", "1d")}

    result = _replace_group_tf(conn, "equity", "1d", produced, guards=_GUARDS, dry_run=False)

    assert (result.stored, result.produced) == (14, 13)
    assert (result.orphaned, result.changed, result.new) == (4, 4, 3)
    assert (result.rows_deleted, result.rows_upserted) == (4, 7)
    after = _table(conn, "equity", "1d")
    want = sorted((r[2], r[3], r[4]) for r in produced)
    assert [(ts, label, vec) for ts, label, vec, _x in after] == want
    # rows written == the diff: unchanged rows keep their xmin, the 7 changed and new rows do not
    moved = [ts for ts, _l, _v, xmin in after if ts not in before or before[ts][3] != xmin]
    assert len(moved) == 7
    untouched = [ts for ts, _l, _v, xmin in after if ts in before and before[ts][3] == xmin]
    assert len(untouched) == 6
    # other cells are untouched
    assert len(_table(conn, "equity", "5m")) == 1 and len(_table(conn, "rates", "1d")) == 1


def test_an_identical_rerun_writes_nothing(conn):
    rows = [_row("equity", "1d", i, "a") for i in range(5)]
    _seed(conn, rows)
    before = _table(conn, "equity", "1d")
    result = _replace_group_tf(conn, "equity", "1d", rows, guards=_GUARDS, dry_run=False)
    assert (result.orphaned, result.changed, result.new) == (0, 0, 0)
    assert _table(conn, "equity", "1d") == before  # same values and same xmin: not rewritten


def test_the_override_decision_is_committed_with_the_rows(conn):
    _seed(conn, [_row("equity", "1d", i, "a") for i in range(10)])
    guards = ReplaceGuards(
        0.01, 0.01, accept_orphans=10, accept_changed=0, operator="bg", reason="r"
    )
    result = _replace_group_tf(
        conn, "equity", "1d", [_row("equity", "1d", 100, "b")], guards=guards, dry_run=False
    )
    assert result.orphaned == 10
    with conn.cursor() as cur:
        cur.execute(
            "SELECT regime_group, tf, orphaned, accepted_orphans, operator, reason FROM market_regimes_override"
        )
        assert cur.fetchall() == [("equity", "1d", 10, 10, "bg", "r")]


def test_a_refused_replace_leaves_rows_and_the_record_untouched(conn):
    _seed(conn, [_row("equity", "1d", i, "a") for i in range(10)])
    before = _table(conn, "equity", "1d")
    guards = ReplaceGuards(0.01, 0.01, accept_orphans=9, operator="bg", reason="r")
    with pytest.raises(ReplaceRefused):
        _replace_group_tf(
            conn, "equity", "1d", [_row("equity", "1d", 100, "b")], guards=guards, dry_run=False
        )
    assert _table(conn, "equity", "1d") == before
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM market_regimes_override")
        assert cur.fetchone()[0] == 0


def test_a_second_connection_on_the_same_cell_is_refused_while_the_first_holds_its_lock(conn):
    _seed(conn, [_row("equity", "1d", 0, "a")])
    other = psycopg.connect(_TEST_DB_URL)
    try:
        with other.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('market_regimes|equity|1d'))")
        with pytest.raises(ReplaceRefused, match="cell lock"):
            _replace_group_tf(
                conn, "equity", "1d", [_row("equity", "1d", 0, "b")], guards=_GUARDS, dry_run=False
            )
        other.rollback()
        # another cell is not blocked
        _replace_group_tf(
            conn, "equity", "1h", [_row("equity", "1h", 0, "b")], guards=_GUARDS, dry_run=False
        )
    finally:
        other.close()
