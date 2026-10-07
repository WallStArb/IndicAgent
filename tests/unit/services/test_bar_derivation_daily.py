"""Tests for services/bar_derivation.py --stage daily on d2-v2 (phase 185 plans 17, 27 and 36).

Fakes only, no DB (todo 494): a fake pool answering the daily stage's reads (APR rows,
1d-eligible instruments, bar_source_policy, D1 TRADIER/SMART/LEGACY_IMPORT TRADES
observations, splits with their evidence, stored 1d rows of every canonical source, the
lineage relkind, the revision waiver, bar_content_digest_current, flag rules) and a fake
connection that applies bar writes to an in-memory store. The contract under test: every name
runs d2-v2 (Tradier-owned names are no longer skipped); stored rows are classified by the write
contract with removal inside the name's derived span; a dry run writes nothing and reports per
name; the apply path writes one ohlcv_load row, old values to ohlcv_revision before any bar
change, new rows by insert and changed rows by the upsert, never canonical_bar_lineage; the
revision-ratio refusal and its waiver; apply refuses while canonical_bar_lineage is a table.
"""

from __future__ import annotations

import asyncio
import csv
import gzip
import json
import re
from datetime import UTC, date, datetime

import numpy as np
import pytest

import services.bar_derivation as bar_derivation_module
from services.bar_derivation import BarDerivation
from src.intelligence.bars.daily_rule import RULE_VERSION
from src.intelligence.bars.digest import DIGEST_ALGORITHM, bar_content_digest

_BATCH_ID = "22222222-2222-2222-2222-222222222222"
_FETCHED = datetime(2026, 10, 3, tzinfo=UTC)
_D1 = date(2024, 5, 1)  # stored tradier, equal
_D2 = date(2024, 5, 2)  # stored tradier, close differs
_D3 = date(2024, 6, 3)  # not stored: new
_D4 = date(2024, 6, 4)  # stored ibkr_named with equal values: changes source only
_D5 = date(2024, 6, 5)  # stored, inside the span, no observation: removed
_D6 = date(2024, 6, 6)  # Tradier observation (span end)
_D0 = date(2024, 4, 1)  # stored before the span: untouched

_DEFAULT_POLICY = {
    "timeframe": "1d",
    "symbol": None,
    "valid_from": date(1990, 1, 1),
    "valid_to": None,
    "ingress_mode": "observed",
    "primary_source": "tradier",
    "fallback_source": "ibkr",
}


def _ts(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _obs(day: date, close: float, *, route: str = "TRADIER", volume: int | None = 100) -> dict:
    return {
        "request_id": f"{route}-{day.isoformat()}",
        "route": route,
        "bar_date": day,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": volume,
        "fetched_at": _FETCHED,
        "what_to_show": "TRADES",
        "legacy": route == "LEGACY_IMPORT",
    }


def _row(close: float, source: str = "tradier", volume: int | None = 100) -> dict:
    return {
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": volume,
        "base": "USD",
        "source": source,
    }


def _fixture() -> tuple[dict[str, list[dict]], dict[str, dict[date, dict]]]:
    observations = {
        "TEST": [
            _obs(_D1, 10.0),
            _obs(_D2, 11.0),
            _obs(_D3, 12.0),
            _obs(_D4, 13.0),
            _obs(_D6, 14.0),
        ]
    }
    stored = {
        "TEST": {
            _D0: _row(9.0),
            _D1: _row(10.0),
            _D2: _row(11.5),
            _D4: _row(13.0, source="ibkr_named"),
            _D5: _row(13.5),
            _D6: _row(14.0),
        }
    }
    return observations, stored


class FakeConn:
    """asyncpg.Connection-shaped fake with an in-memory canonical 1d store."""

    def __init__(
        self,
        *,
        observations: dict[str, list[dict]],
        stored: dict[str, dict[date, dict]] | None = None,
        splits: dict[str, list[dict]] | None = None,
        policy: list[dict] | None = None,
        current_digests: dict[str, list[tuple[datetime, str]]] | None = None,
        flag_rules: dict[str, list[tuple[datetime, str, bool]]] | None = None,
        changed_since: dict[str, bool] | None = None,
        tradier_owned: frozenset[str] = frozenset(),
        lineage_relkind: str = "v",
        waived: bool = False,
        apr: dict[str, str] | None = None,
    ) -> None:
        self.observations = observations
        self.stored = stored or {}
        self.splits = splits or {}
        self.policy = [dict(_DEFAULT_POLICY)] if policy is None else policy
        self.current_digests = current_digests or {}
        self.flag_rules = flag_rules or {}
        self.changed_since = changed_since
        self.tradier_owned = tradier_owned
        self.lineage_relkind = lineage_relkind
        self.waived = waived
        self.apr = {
            "infra.bar_derivation.daily_symbol_batch": "25",
            "infra.bar_derivation.daily_write_method": "upsert",
            "threshold.bar_integrity.fallback_basis_window_sessions": "20",
            "threshold.bar_integrity.fallback_basis_tolerance_bp": "10",
            "threshold.bar_integrity.max_revision_ratio": "0.02",
            "threshold.bar_integrity.revision_ratio_min_stored": "500",
            "threshold.bar_scrub.quarantine_rules": json.dumps(
                ["ohlc_invariant", "price_sanity", "pre_split_unrefetched"]
            ),
            **(apr or {}),
        }
        self.calls: list[tuple[str, str]] = []
        self.statements: list[tuple[str, tuple]] = []
        self.executemany_calls: list[tuple[str, list[tuple]]] = []
        self.digest_rows: list[tuple] = []
        self.flag_inserts: list[tuple] = []
        self.digest_read_sources: list[tuple] = []
        self.stored_read_sources: list[tuple] = []

    class _Txn:
        def __init__(self, outer: FakeConn) -> None:
            self.outer = outer

        async def __aenter__(self) -> None:
            self.outer.calls.append(("<begin>", ""))

        async def __aexit__(self, *exc: object) -> bool:
            self.outer.calls.append(("<commit>" if not exc[0] else "<rollback>", ""))
            return False

    def transaction(self) -> FakeConn._Txn:
        return self._Txn(self)

    def _stored_rows(self, symbol: str, sources: tuple) -> list[dict]:
        return [
            {**row, "timestamp": _ts(day)}
            for day, row in sorted(self.stored.get(symbol, {}).items())
            if row["source"] in sources
        ]

    async def fetch(self, sql: str, *args: object) -> list[object]:
        self.calls.append(("fetch", sql))
        if "config_state" in sql:
            return [{"config_key": k, "config_value": v} for k, v in self.apr.items()]
        if "FROM instruments" in sql:
            return [(symbol,) for symbol in sorted(self.observations)]
        if "FROM bar_source_policy" in sql:
            return self.policy
        if "ohlcv_observation" in sql:
            routes = set(args[1])  # type: ignore[arg-type]
            return [o for o in self.observations.get(str(args[0]), []) if o["route"] in routes]
        if "corporate_action_current" in sql:
            return self.splits.get(str(args[0]), [])
        if "/* stored_1d */" in sql:
            sources = tuple(args[1])  # type: ignore[arg-type]
            self.stored_read_sources.append(sources)
            return self._stored_rows(str(args[0]), sources)
        if "source = ANY($2" in sql:
            sources = tuple(args[1])  # type: ignore[arg-type]
            self.digest_read_sources.append(sources)
            return self._stored_rows(str(args[0]), sources)
        if "bar_content_digest_current" in sql:
            return [
                {
                    "range_start": entry[0],
                    "digest": entry[1],
                    "rule_version": entry[2] if len(entry) > 2 else RULE_VERSION,
                }
                for entry in self.current_digests.get(str(args[0]), [])
            ]
        if "bar_quality_flag" in sql:
            return [
                {"timestamp": t, "rule": rule, "quarantine": q}
                for t, rule, q in self.flag_rules.get(str(args[0]), [])
            ]
        raise AssertionError(f"unexpected fetch: {sql}")

    async def fetchrow(self, sql: str, *args: object) -> object:
        self.calls.append(("fetchrow", sql))
        if "changed_since" in sql:
            since = (self.changed_since or {}).get(str(args[0]), True)
            return {
                "has_obs": bool(self.observations.get(str(args[0]))),
                "obs_since": since,
                "action_since": False,
                "policy_since": False,
                "tradier_owned": str(args[0]) in self.tradier_owned,
            }
        raise AssertionError(f"unexpected fetchrow: {sql}")

    async def fetchval(self, sql: str, *args: object) -> object:
        self.calls.append(("fetchval", sql))
        if "pg_class" in sql:
            return self.lineage_relkind
        if "/* revision_waiver */" in sql:
            return self.waived
        assert "bar_derivation_batch" in sql, f"unexpected fetchval: {sql}"
        return _BATCH_ID

    async def execute(self, sql: str, *args: object) -> str:
        self.calls.append(("execute", sql))
        self.statements.append((sql, tuple(args)))
        if "DELETE FROM market_data_ohlcv" in sql:
            symbol, keys = str(args[0]), list(args[1])  # type: ignore[arg-type]
            for ts in keys:
                del self.stored[symbol][ts.date()]
            return f"DELETE {len(keys)}"
        if "INSERT INTO ohlcv_load" in sql:
            return "INSERT 0 1"
        return "UPDATE 1"

    async def executemany(self, sql: str, args_seq: object) -> str:
        args = [tuple(a) for a in args_seq]
        self.calls.append(("executemany", sql))
        self.executemany_calls.append((sql, args))
        if "INSERT INTO market_data_ohlcv" in sql:
            for row in args:
                self.stored.setdefault(row[1], {})[row[0].date()] = {
                    "open": row[3],
                    "high": row[4],
                    "low": row[5],
                    "close": row[6],
                    "volume": row[7],
                    "source": row[8],
                    "base": row[9],
                }
        elif "INSERT INTO bar_content_digest" in sql:
            self.digest_rows.extend(args)
        elif "INSERT INTO bar_quality_flag" in sql:
            self.flag_inserts.extend(args)
        return f"INSERT {len(args)}"

    # -- views over what was written --------------------------------------------------------

    def executed(self, fragment: str) -> list[tuple]:
        return [args for sql, args in self.statements if fragment in sql]

    def many(self, fragment: str) -> list[tuple]:
        return [row for sql, rows in self.executemany_calls if fragment in sql for row in rows]

    def order(self, *fragments: str) -> list[int]:
        flat = [sql for _kind, sql in self.calls]
        return [next(i for i, sql in enumerate(flat) if f in sql) for f in fragments]


class FakePool:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    class _Acquire:
        def __init__(self, conn: FakeConn) -> None:
            self.conn = conn

        async def __aenter__(self) -> FakeConn:
            return self.conn

        async def __aexit__(self, *exc: object) -> bool:
            return False

    def acquire(self) -> FakePool._Acquire:
        return self._Acquire(self.conn)


def _run(conn: FakeConn, **overrides: object):
    scrub_calls: list[dict] = []
    scrub_effect = overrides.pop("scrub_effect", None)

    async def fake_scrub(pool, **kwargs):
        scrub_calls.append(kwargs)
        pool.conn.calls.append(("scrub", ""))
        if scrub_effect is not None:
            scrub_effect(pool.conn)  # type: ignore[operator]
        return {}

    writer = BarDerivation(
        "postgresql://unused",
        stage="daily",
        symbols=overrides.pop("symbols", None),
        changed_only=overrides.pop("changed_only", False),
        apply=overrides.pop("apply", True),
        exclude_symbols_file=None,
        report_path=overrides.pop("report_path", None),
        rewrite_digests=overrides.pop("rewrite_digests", False),
        restore_snapshot=overrides.pop("restore_snapshot", None),
    )
    original = bar_derivation_module.scrub_symbols
    bar_derivation_module.scrub_symbols = fake_scrub
    try:
        result = asyncio.run(writer.execute(FakePool(conn)))
    finally:
        bar_derivation_module.scrub_symbols = original
    return result, scrub_calls


def _digest(days: list[date], closes: list[float]) -> str:
    ts = np.array([int(_ts(d).timestamp()) for d in days], dtype=np.int64)
    arr = np.array(closes, dtype=np.float64)
    vol = np.array([100.0] * len(days), dtype=np.float64)
    return bar_content_digest(ts, arr, arr, arr, arr, vol, [()] * len(days))


# --- dry run -----------------------------------------------------------------------------------


def test_dry_run_classifies_every_canonical_source_and_writes_nothing(tmp_path):
    observations, stored = _fixture()
    conn = FakeConn(observations=observations, stored=stored)
    report = tmp_path / "dryrun.tsv"
    result, scrub_calls = _run(conn, apply=False, report_path=str(report))
    assert result["rows"] == {
        "new": 1,  # _D3
        "changed": 2,  # _D2 value, _D4 source only
        "unchanged": 2,  # _D1, _D6
        "removed": 1,  # _D5; _D0 sits before the span and stays
    }
    assert result["totals"]["derived"] == 1
    assert conn.stored_read_sources == [("ibkr_named", "ibkr_venue", "ibkr_fallback", "tradier")]
    # Nothing written: no statement, no batch, no scrub.
    assert conn.statements == [] and conn.executemany_calls == [] and scrub_calls == []
    assert not any("pg_class" in sql for _kind, sql in conn.calls)
    rows = list(csv.DictReader(report.open(), delimiter="\t"))
    assert [r["symbol"] for r in rows] == ["TEST"]
    (row,) = rows
    assert row["group"] == "mixed"
    assert (row["new"], row["changed"], row["unchanged"], row["removed"]) == ("1", "2", "2", "1")
    assert row["changed_source_only"] == "1" and row["outside_span"] == "1"
    assert row["refused_interior"] == "0" and row["would_refuse"] == "false"


def test_tradier_owned_names_are_derived_not_skipped():
    observations, stored = _fixture()
    conn = FakeConn(observations=observations, stored=stored, tradier_owned=frozenset({"TEST"}))
    result, _ = _run(conn, apply=False)
    assert result["totals"].get("tradier_owned", 0) == 0
    assert result["totals"]["derived"] == 1


def test_dry_run_reports_refused_interior_dates_and_groups(tmp_path):
    days = [date(2024, 1, d) for d in (2, 3, 4, 5, 8, 9, 10)]
    hole = days[3]
    obs = [_obs(d, 100.0) for d in days if d != hole]
    obs += [_obs(d, 101.0, route="SMART") for d in days]  # 100 bp away: refused
    conn = FakeConn(
        observations={"TEST": obs, "ONLY": [_obs(d, 5.0, route="SMART") for d in days]},
        stored={"TEST": {d: _row(100.0) for d in days if d != hole}},
    )
    report = tmp_path / "dryrun.tsv"
    result, _ = _run(conn, apply=False, report_path=str(report))
    rows = {r["symbol"]: r for r in csv.DictReader(report.open(), delimiter="\t")}
    assert rows["TEST"]["refused_interior"] == "1"
    assert rows["TEST"]["refused_dates"] == hole.isoformat()
    assert rows["TEST"]["group"] == "tradier_only"
    # No stored rows and no Tradier answer: every IBKR bar is a head.
    assert rows["ONLY"]["group"] == "none" and rows["ONLY"]["head"] == str(len(days))
    assert result["refused_interior"] == 1


def test_dry_run_reports_refused_heads(tmp_path):
    # 2:1 basis between the vendors over the overlap (XLY-like): the IBKR head is refused.
    days = [date(2024, 1, d) for d in (2, 3, 4, 5, 8, 9, 10)]
    obs = [_obs(d, 100.0) for d in days[2:]]
    obs += [_obs(d, 200.0, route="SMART") for d in days]
    conn = FakeConn(
        observations={"TEST": obs},
        stored={"TEST": {d: _row(200.0, source="ibkr_named") for d in days}},
    )
    report = tmp_path / "dryrun.tsv"
    result, _ = _run(conn, apply=False, report_path=str(report))
    (row,) = csv.DictReader(report.open(), delimiter="\t")
    assert row["head"] == "0" and row["refused_head"] == "2"
    assert row["removed"] == "2"
    assert result["refused_head"] == 2


def test_a_missing_policy_row_fails_the_symbol_loud():
    observations, stored = _fixture()
    conn = FakeConn(observations=observations, stored=stored, policy=[])
    with pytest.raises(RuntimeError, match="no bar_source_policy row"):
        _run(conn, apply=False)


# --- apply -----------------------------------------------------------------------------------


def test_apply_refuses_while_canonical_bar_lineage_is_a_table():
    observations, stored = _fixture()
    conn = FakeConn(observations=observations, stored=stored, lineage_relkind="r")
    with pytest.raises(RuntimeError, match="185-38"):
        _run(conn)
    assert conn.statements == [] and conn.executemany_calls == []


def test_apply_writes_the_contract_and_no_lineage():
    observations, stored = _fixture()
    conn = FakeConn(observations=observations, stored=stored)
    result, scrub_calls = _run(conn)
    # One ohlcv_load row: derived 1d into market_data_ohlcv, the four counts, the batch.
    ((load_args),) = conn.executed("INSERT INTO ohlcv_load")
    load = dict(
        zip(
            (
                "load_id symbol timeframe source requested_start requested_end outcome n_bars "
                "n_new n_changed n_unchanged n_removed first_bar last_bar detail caller batch_id "
                "destination"
            ).split(),
            load_args,
        )
    )
    assert (load["symbol"], load["timeframe"], load["source"]) == ("TEST", "1d", "derived")
    assert (load["outcome"], load["destination"], load["batch_id"]) == (
        "applied",
        "market_data_ohlcv",
        _BATCH_ID,
    )
    assert (load["n_new"], load["n_changed"], load["n_unchanged"], load["n_removed"]) == (
        1,
        2,
        2,
        1,
    )
    assert json.loads(load["detail"])["rule_version"] == RULE_VERSION
    # Old values of changed and removed rows, origin load, under the load row.
    revisions = conn.many("INSERT INTO ohlcv_revision")
    assert {(r[3].date(), r[7], r[9], r[10]) for r in revisions} == {
        (_D2, 11.5, "tradier", "load"),
        (_D4, 13.0, "ibkr_named", "load"),
        (_D5, 13.5, "tradier", "load"),
    }
    assert {r[0] for r in revisions} == {load["load_id"]}
    # Removed by key, new by insert, changed by the upsert on the changed set only.
    ((delete_args),) = conn.executed("DELETE FROM market_data_ohlcv")
    assert [ts.date() for ts in delete_args[1]] == [_D5]
    inserts = [
        row
        for sql, rows in conn.executemany_calls
        if "INSERT INTO market_data_ohlcv" in sql and "ON CONFLICT" not in sql
        for row in rows
    ]
    assert [r[0].date() for r in inserts] == [_D3]
    upserts = conn.many("ON CONFLICT")
    assert sorted(r[0].date() for r in upserts) == [_D2, _D4]
    assert {r[0].date(): r[8] for r in upserts}[_D4] == "tradier"
    # Revisions land before any bar change, all inside the role switch.
    role, load_i, revision, delete, upsert = conn.order(
        "SET LOCAL ROLE bar_derivation_writer",
        "INSERT INTO ohlcv_load",
        "INSERT INTO ohlcv_revision",
        "DELETE FROM market_data_ohlcv",
        "ON CONFLICT",
    )
    assert role < load_i < revision < delete < upsert
    assert not any("INTO canonical_bar_lineage" in sql for _kind, sql in conn.calls)
    assert conn.stored["TEST"][_D2]["close"] == 11.0 and _D5 not in conn.stored["TEST"]
    assert scrub_calls and scrub_calls[0]["symbols"] == ["TEST"]
    assert result["totals"]["derived"] == 1


def test_a_second_apply_over_the_same_answers_writes_no_bar():
    observations, stored = _fixture()
    conn = FakeConn(observations=observations, stored=stored)
    _run(conn)
    conn.statements.clear()
    conn.executemany_calls.clear()
    _run(conn)
    ((load_args),) = conn.executed("INSERT INTO ohlcv_load")
    assert load_args[8:12] == (0, 0, 5, 0)
    assert not conn.executed("DELETE FROM market_data_ohlcv")
    assert not conn.many("INSERT INTO market_data_ohlcv")
    assert not conn.many("INSERT INTO ohlcv_revision")


def test_open_batch_gets_rule_d2v2_and_the_integrity_and_scrub_keys(monkeypatch):
    observations, stored = _fixture()
    conn = FakeConn(observations=observations, stored=stored)
    seen: dict = {}

    async def fake_open(conn, **kwargs):
        seen.update(kwargs)
        return _BATCH_ID

    monkeypatch.setattr(bar_derivation_module, "open_batch", fake_open)
    _run(conn)
    assert seen["stage"] == "daily" and seen["rule_version"] == "d2-v2"
    keys = set(seen["apr_snapshot"])
    assert "threshold.bar_integrity.fallback_basis_tolerance_bp" in keys
    assert "threshold.bar_integrity.max_revision_ratio" in keys
    assert "threshold.bar_scrub.quarantine_rules" in keys
    assert "infra.bar_derivation.daily_symbol_batch" in keys


def _ratio_fixture(**conn_kwargs) -> FakeConn:
    observations, stored = _fixture()
    return FakeConn(
        observations=observations,
        stored=stored,
        apr={"threshold.bar_integrity.revision_ratio_min_stored": "5"},
        **conn_kwargs,
    )


def test_revision_ratio_breach_writes_only_a_refused_load():
    conn = _ratio_fixture(waived=False)
    with pytest.raises(RuntimeError, match="refused"):
        _run(conn)
    ((load_args),) = conn.executed("INSERT INTO ohlcv_load")
    assert load_args[6] == "refused"
    assert not conn.many("INSERT INTO market_data_ohlcv")
    assert not conn.many("INSERT INTO ohlcv_revision")
    assert not conn.executed("DELETE FROM market_data_ohlcv")
    assert not conn.flag_inserts


def test_revision_ratio_is_waived_by_a_recorded_action_or_a_first_load():
    conn = _ratio_fixture(waived=True)
    _run(conn)
    ((load_args),) = conn.executed("INSERT INTO ohlcv_load")
    assert load_args[6] == "applied"
    assert conn.many("ON CONFLICT")


def test_revision_ratio_applies_only_at_or_above_min_stored():
    observations, stored = _fixture()
    conn = FakeConn(observations=observations, stored=stored, waived=False)  # min_stored 500
    _run(conn)
    assert conn.executed("INSERT INTO ohlcv_load")[0][6] == "applied"
    assert not any("/* revision_waiver */" in sql for _kind, sql in conn.calls)


def test_the_waiver_reads_corporate_actions_and_policy_after_the_last_applied_load():
    from services.bar_derivation import _SELECT_REVISION_WAIVER_SQL as sql

    assert "corporate_action" in sql and "bar_source_policy" in sql
    assert "outcome = 'applied'" in sql and "source = 'derived'" in sql


def test_derivation_flags_go_through_write_flags_with_rule_d2v2():
    days = [date(2024, 1, d) for d in (2, 3, 4, 5, 8)]
    observations = {
        "TEST": [_obs(days[0], 10.0, route="SMART")]
        + [_obs(d, 10.0) for d in days[1:]]
        + [_obs(d, 10.0, route="SMART") for d in days[1:]]
        + [_obs(date(2024, 1, 9), 10.0, volume=None)]
    }
    conn = FakeConn(observations=observations, stored={})
    _run(conn)
    by_rule = {(r[3], r[2].date()): r for r in conn.flag_inserts}
    seam = by_rule[("fallback_seam", days[1])]
    assert seam[4] == RULE_VERSION and seam[6] is False
    detail = json.loads(seam[7])
    assert detail["n_head_bars"] == 1 and detail["median_ratio"] == 1.0
    assert by_rule[("no_provider_volume", date(2024, 1, 9))][6] is False
    head_bar = conn.stored["TEST"][days[0]]
    assert head_bar["source"] == "ibkr_fallback"


def test_scrub_then_digests_at_d2v2_after_the_writes():
    observations, stored = _fixture()
    conn = FakeConn(observations=observations, stored=stored)

    def add_flag(c: FakeConn) -> None:
        c.flag_rules.setdefault("TEST", []).append((_ts(_D1), "volume_spike", False))

    _run(conn, scrub_effect=add_flag)
    kinds = [kind for kind, sql in conn.calls if kind == "scrub" or "bar_content_digest" in sql]
    assert kinds.index("scrub") < kinds.index("executemany")
    assert {r[6] for r in conn.digest_rows} == {RULE_VERSION}
    assert {r[5] for r in conn.digest_rows} == {DIGEST_ALGORITHM}
    may = [r for r in conn.digest_rows if r[2].month == 5]
    ts = np.array([int(_ts(d).timestamp()) for d in (_D1, _D2)], dtype=np.int64)
    arr = np.array([10.0, 11.0], dtype=np.float64)
    vol = np.array([100.0, 100.0], dtype=np.float64)
    assert may[0][4] == bar_content_digest(ts, arr, arr, arr, arr, vol, [("volume_spike",), ()])


def test_digest_failure_fails_the_run_after_the_scrub(monkeypatch):
    observations, stored = _fixture()
    conn = FakeConn(observations=observations, stored=stored)

    async def boom(conn, **kwargs):
        raise RuntimeError("digest write refused")

    monkeypatch.setattr(bar_derivation_module, "write_1d_digests", boom)
    with pytest.raises(RuntimeError, match="digest TEST"):
        _run(conn)


def test_changed_only_skips_symbol_without_new_answers():
    observations, stored = _fixture()
    conn = FakeConn(observations=observations, stored=stored, changed_since={"TEST": False})
    result, _ = _run(conn, changed_only=True)
    assert result["totals"]["unchanged"] == 1
    assert not any("ohlcv_observation" in sql for kind, sql in conn.calls if kind == "fetch")
    assert not conn.statements or all("ohlcv_load" not in sql for sql, _ in conn.statements)


def test_no_observations_counts_and_moves_on():
    conn = FakeConn(observations={"TEST": []}, stored={})
    result, _ = _run(conn)
    assert result["totals"]["no_observations"] == 1
    assert not conn.executed("INSERT INTO ohlcv_load")


# --- statements ------------------------------------------------------------------------------


def test_changed_since_probe_keeps_its_name_and_tradier_owned_column():
    # ibkr_history_fetcher.py (phase 189) imports it as _DAILY_SOURCE_PROBE_SQL.
    from services.bar_derivation import _SELECT_DAILY_CHANGED_SINCE_SQL as sql

    assert "AS tradier_owned" in sql and "FROM ohlcv_load" not in sql  # policy since 185-38
    assert "AS policy_since" in sql and "bar_source_policy" in sql


def test_daily_stage_calls_d2v2_and_writes_no_lineage():
    from tests.unit._source_grep_helpers import read_source

    source = read_source("services", "bar_derivation.py")
    assert "derive_daily_v2" in source
    assert "_UPSERT_LINEAGE_SQL" not in source
    assert not re.search(r"(?:INSERT\s+INTO|UPDATE|COPY)\s+canonical_bar_lineage\b", source)


def test_observation_read_takes_the_d2v2_routes():
    from services.bar_derivation import _D2V2_ROUTES, _SELECT_DAILY_OBSERVATIONS_SQL

    assert set(_D2V2_ROUTES) == {"TRADIER", "SMART", "LEGACY_IMPORT"}
    assert "o.route = ANY($2::text[])" in _SELECT_DAILY_OBSERVATIONS_SQL
    assert "q.caller NOT LIKE 'test-%'" in _SELECT_DAILY_OBSERVATIONS_SQL


def test_write_1d_digests_reads_every_canonical_source():
    from services.bar_derivation import write_1d_digests
    from src.intelligence.bars.sources import CANONICAL_1D_SOURCES, TRADIER_RULE_VERSION

    stored = {_D1: _row(10.0), _D2: _row(11.0)}
    conn = FakeConn(observations={}, stored={"TEST": stored})
    n = asyncio.run(
        write_1d_digests(conn, symbol="TEST", batch_id=_BATCH_ID, rule_version=TRADIER_RULE_VERSION)
    )
    assert n == 1
    assert conn.digest_read_sources == [CANONICAL_1D_SOURCES]
    (row,) = conn.digest_rows
    assert row[4] == _digest([_D1, _D2], [10.0, 11.0])
    assert row[6] == TRADIER_RULE_VERSION and row[7] == 2 and row[8] == _BATCH_ID
    assert ("execute", "SET LOCAL ROLE bar_derivation_writer") in conn.calls
    conn.current_digests = {"TEST": [(row[2], row[4])]}
    assert (
        asyncio.run(
            write_1d_digests(
                conn, symbol="TEST", batch_id=_BATCH_ID, rule_version=TRADIER_RULE_VERSION
            )
        )
        == 0
    )


# --- rewrite digests and restore (plan 185-38 Task 2) -----------------------------------------


def test_rewrite_digests_rewrites_every_month_at_d2v2_even_when_content_is_equal():
    stored = {_D1: _row(10.0), _D2: _row(11.0), _D3: _row(12.0)}
    may = _digest([_D1, _D2], [10.0, 11.0])
    june = _digest([_D3], [12.0])
    conn = FakeConn(
        observations={"TEST": [_obs(_D1, 10.0)]},
        stored={"TEST": stored},
        current_digests={
            "TEST": [(_ts(date(2024, 5, 1)), may, "tradier-v1"), (_ts(date(2024, 6, 1)), june)]
        },
    )
    result, scrub_calls = _run(conn, rewrite_digests=True, symbols=["TEST"])
    # May's content is equal but its rule is tradier-v1; June is already d2-v2 and equal.
    assert [(r[2].month, r[4], r[6]) for r in conn.digest_rows] == [(5, may, RULE_VERSION)]
    assert result["digests_written"] == 1
    assert not conn.many("INSERT INTO market_data_ohlcv") and scrub_calls == []
    assert not conn.executed("INSERT INTO ohlcv_load")


def test_rewrite_digests_dry_run_counts_without_writing():
    stored = {_D1: _row(10.0)}
    conn = FakeConn(
        observations={"TEST": [_obs(_D1, 10.0)]},
        stored={"TEST": stored},
        current_digests={"TEST": [(_ts(date(2024, 5, 1)), _digest([_D1], [10.0]), "d2-v1")]},
    )
    result, _ = _run(conn, rewrite_digests=True, symbols=["TEST"], apply=False)
    assert result["digests_written"] == 1 and conn.digest_rows == []


_SNAPSHOT_COLUMNS = (
    "timestamp,symbol,timeframe,open,high,low,close,volume,source,base,price_sanity_status"
)


def _snapshot(tmp_path, rows):
    path = tmp_path / "market_data_ohlcv_1d_pre_d2v2.csv.gz"
    with gzip.open(path, "wt") as handle:
        handle.write(_SNAPSHOT_COLUMNS + "\n")
        for symbol, day, close, source in rows:
            handle.write(
                f"{day.isoformat()} 00:00:00+00,{symbol},1d,{close},{close},{close},{close},"
                f"100,{source},,\n"
            )
    return str(path)


def test_restore_rewrites_the_symbol_from_the_snapshot_through_the_contract(tmp_path):
    snapshot = _snapshot(
        tmp_path,
        [
            ("TEST", _D1, 10.0, "tradier"),
            ("TEST", _D2, 11.5, "ibkr_named"),
            ("TEST", _D5, 13.5, "tradier"),
            ("OTHER", _D1, 99.0, "tradier"),
        ],
    )
    stored = {_D1: _row(10.0), _D2: _row(11.0), _D3: _row(12.0)}
    conn = FakeConn(observations={"TEST": [_obs(_D1, 10.0)]}, stored={"TEST": stored})
    result, scrub_calls = _run(conn, restore_snapshot=snapshot, symbols=["TEST"])
    assert {d: (r["close"], r["source"]) for d, r in conn.stored["TEST"].items()} == {
        _D1: (10.0, "tradier"),
        _D2: (11.5, "ibkr_named"),
        _D5: (13.5, "tradier"),
    }
    ((load_args),) = conn.executed("INSERT INTO ohlcv_load")
    assert load_args[15] == "bar_derivation-restore" and load_args[6] == "applied"
    assert load_args[8:12] == (1, 1, 1, 1)  # new D5, changed D2, unchanged D1, removed D3
    detail = json.loads(load_args[14])
    assert detail["waiver"] == "restore" and detail["snapshot"] == snapshot
    revisions = conn.many("INSERT INTO ohlcv_revision")
    assert {(r[3].date(), r[7]) for r in revisions} == {(_D2, 11.0), (_D3, 12.0)}
    assert "OTHER" not in conn.stored
    assert scrub_calls and scrub_calls[0]["symbols"] == ["TEST"]
    assert conn.digest_rows
    assert result["rows"] == {"new": 1, "changed": 1, "unchanged": 1, "removed": 1}


def test_restore_without_apply_reports_counts_only(tmp_path):
    snapshot = _snapshot(tmp_path, [("TEST", _D1, 10.0, "tradier")])
    stored = {_D1: _row(10.0), _D2: _row(11.0)}
    conn = FakeConn(observations={}, stored={"TEST": stored})
    result, _ = _run(conn, restore_snapshot=snapshot, symbols=["TEST"], apply=False)
    assert result["rows"]["removed"] == 1
    assert conn.statements == [] and conn.executemany_calls == []


def test_restore_needs_symbols(tmp_path):
    snapshot = _snapshot(tmp_path, [("TEST", _D1, 10.0, "tradier")])
    conn = FakeConn(observations={}, stored={})
    with pytest.raises(ValueError, match="--symbols"):
        _run(conn, restore_snapshot=snapshot)
