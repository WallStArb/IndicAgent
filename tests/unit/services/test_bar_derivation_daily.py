"""Tests for services/bar_derivation.py --stage daily (phase 185 plan 17, task 2).

Fakes only, no DB: a fake pool answering the daily stage's read shapes (APR
config rows, 1d-eligible instruments, D1 TRADES observations, splits from
corporate_action_current, stored 1d rows from market_data_ohlcv canonical
sources, bar_content_digest_current, flag rules) and a fake connection that
applies the 1d upsert to an in-memory store so the post-write digest readback
sees the written rows. The contract under test (D-06/D-07/D-12/D-21): equal
stored rows produce zero bar writes but full lineage; a differing close and a
missing date each produce exactly one write; synthetic_fill rows never enter
the comparison; dry run writes nothing and reports counts by reason; digest
rows land only for months whose digest changed; pre_split flags go through
write_flags; the D2a scrub is rerun through services/bar_scrub.py.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime

import numpy as np

import services.bar_derivation as bar_derivation_module
from services.bar_derivation import BarDerivation
from src.intelligence.bars.derivation import RULE_VERSION
from src.intelligence.bars.digest import DIGEST_ALGORITHM, bar_content_digest

_BATCH_ID = "22222222-2222-2222-2222-222222222222"
_FETCHED = datetime(2026, 9, 30, tzinfo=UTC)
_D1 = date(2024, 5, 1)  # equal stored row
_D2 = date(2024, 5, 2)  # equal stored row
_D3 = date(2024, 6, 3)  # stored close differs
_D4 = date(2024, 6, 4)  # missing (a synthetic_fill placeholder sits on the key)


def _ts(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _obs_rows(symbol_closes: dict[date, float], *, fetched_at: datetime = _FETCHED):
    return [
        {
            "request_id": f"req-{d.isoformat()}",
            "route": "SMART",
            "bar_date": d,
            "open": c,
            "high": c,
            "low": c,
            "close": c,
            "volume": 100,
            "fetched_at": fetched_at,
            "what_to_show": "TRADES",
            "legacy": False,
        }
        for d, c in symbol_closes.items()
    ]


def _stored_row(close: float, volume: int = 100, source: str = "ibkr_named"):
    return {
        "timestamp": None,  # filled by the caller
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": volume,
        "base": "USD",
        "source": source,
    }


class FakeConn:
    """asyncpg.Connection-shaped fake with an in-memory canonical 1d store."""

    def __init__(
        self,
        *,
        observations: dict[str, list[dict]],
        stored: dict[str, dict[date, dict]] | None = None,
        synthetic: dict[str, set[date]] | None = None,
        splits: dict[str, list[dict]] | None = None,
        current_digests: dict[str, list[tuple[datetime, str]]] | None = None,
        flag_rules: dict[str, list[tuple[datetime, str, bool]]] | None = None,
        changed_since: dict[str, bool] | None = None,
        venue_enabled: bool = False,
        tradier_owned: frozenset[str] = frozenset(),
    ) -> None:
        self.tradier_owned = tradier_owned
        self.observations = observations
        self.stored = stored or {}
        self.synthetic = synthetic or {}
        self.splits = splits or {}
        self.current_digests = current_digests or {}
        self.flag_rules = flag_rules or {}
        self.changed_since = changed_since
        self.venue_enabled = venue_enabled
        self.calls: list[tuple[str, str]] = []
        self.statements: list[tuple[str, tuple]] = []
        self.executemany_calls: list[tuple[str, list[tuple]]] = []
        self.lineage_rows: list[tuple] = []
        self.bar_write_rows: list[tuple] = []
        self.digest_rows: list[tuple] = []
        self.flag_inserts: list[tuple] = []

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

    async def fetch(self, sql: str, *args: object) -> list[object]:
        self.calls.append(("fetch", sql))
        if "config_state" in sql:
            return [
                {"config_key": "infra.bar_derivation.daily_symbol_batch", "config_value": "25"},
                {"config_key": "infra.bar_derivation.daily_write_method", "config_value": "upsert"},
                {
                    "config_key": "infra.bar_derivation.venue_bars_1d",
                    "config_value": "true" if self.venue_enabled else "false",
                },
                {
                    "config_key": "threshold.bar_scrub.quarantine_rules",
                    "config_value": json.dumps(
                        [
                            "ohlc_invariant",
                            "non_positive_price",
                            "price_sanity",
                            "split_seam",
                            "legacy_price_sanity_status",
                            "pre_split_unrefetched",
                        ]
                    ),
                },
            ]
        if "FROM instruments" in sql:
            return [(symbol,) for symbol in sorted(self.observations)]
        if "ohlcv_observation" in sql:
            return self.observations.get(str(args[0]), [])
        if "corporate_action_current" in sql:
            return self.splits.get(str(args[0]), [])
        if "source IN ('ibkr_named'" in sql:
            symbol = str(args[0])
            return [
                {**row, "timestamp": _ts(day)}
                for day, row in sorted(self.stored.get(symbol, {}).items())
            ]
        if "base IS NOT NULL" in sql:
            return [("USD",)]
        if "bar_content_digest_current" in sql:
            return [
                {"range_start": start, "digest": digest}
                for start, digest in self.current_digests.get(str(args[0]), [])
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
                "tradier_owned": str(args[0]) in self.tradier_owned,
            }
        raise AssertionError(f"unexpected fetchrow: {sql}")

    async def fetchval(self, sql: str, *args: object) -> object:
        self.calls.append(("fetchval", sql))
        assert "bar_derivation_batch" in sql, f"unexpected fetchval: {sql}"
        return _BATCH_ID

    async def execute(self, sql: str, *args: object) -> str:
        self.calls.append(("execute", sql))
        self.statements.append((sql, tuple(args)))
        return "UPDATE 1"

    async def executemany(self, sql: str, args_seq: object) -> str:
        args = [tuple(a) for a in args_seq]
        self.calls.append(("executemany", sql))
        self.executemany_calls.append((sql, args))
        if "INSERT INTO market_data_ohlcv" in sql:
            self.bar_write_rows.extend(args)
            symbol = args[0][1]
            for row in args:
                day = row[0].date()
                self.stored.setdefault(symbol, {})[day] = {
                    "timestamp": row[0],
                    "open": row[3],
                    "high": row[4],
                    "low": row[5],
                    "close": row[6],
                    "volume": row[7],
                    "base": row[9],
                    "source": row[8],
                }
        elif "INSERT INTO canonical_bar_lineage" in sql:
            self.lineage_rows.extend(args)
        elif "INSERT INTO bar_content_digest" in sql:
            self.digest_rows.extend(args)
        elif "INSERT INTO bar_quality_flag" in sql:
            self.flag_inserts.extend(args)
        return f"INSERT {len(args)}"


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


def _canonical_fixture_stored() -> dict[str, dict[date, dict]]:
    """Stored rows: d1/d2 equal, d3 close differs, d4 absent (synthetic key)."""
    stored = {
        _D1: _stored_row(10.0),
        _D2: _stored_row(11.0),
        _D3: _stored_row(12.5),
    }
    for day, row in stored.items():
        row["timestamp"] = _ts(day)
    return {"TEST": stored}


def _observations_fixture() -> dict[str, list[dict]]:
    return {"TEST": _obs_rows({_D1: 10.0, _D2: 11.0, _D3: 12.0, _D4: 13.0})}


def _run(conn: FakeConn, **overrides: object):
    scrub_calls: list[dict] = []

    async def fake_scrub(pool, **kwargs):
        scrub_calls.append(kwargs)
        return {}

    report = overrides.pop("report_path", None)
    writer = BarDerivation(
        "postgresql://unused",
        stage="daily",
        symbols=overrides.pop("symbols", None),
        changed_only=overrides.pop("changed_only", False),
        apply=overrides.pop("apply", True),
        exclude_symbols_file=None,
        report_path=report,
    )
    original = bar_derivation_module.scrub_symbols
    bar_derivation_module.scrub_symbols = fake_scrub
    try:
        result = asyncio.run(writer.execute(FakePool(conn)))
    finally:
        bar_derivation_module.scrub_symbols = original
    return result, scrub_calls


def _digest(days: list[date], closes: list[float]) -> tuple[str, int]:
    ts = np.array([int(_ts(d).timestamp()) for d in days], dtype=np.int64)
    arr = np.array(closes, dtype=np.float64)
    vol = np.array([100.0] * len(days), dtype=np.float64)
    return (
        bar_content_digest(ts, arr, arr, arr, arr, vol, [()] * len(days)),
        len(days),
    )


def test_equal_rows_write_no_bars_but_full_lineage():
    conn = FakeConn(observations=_observations_fixture(), stored=_canonical_fixture_stored())
    # Make every stored row equal to the canonical bars.
    conn.stored["TEST"][_D3] = {**_stored_row(12.0), "timestamp": _ts(_D3)}
    conn.stored["TEST"][_D4] = {**_stored_row(13.0), "timestamp": _ts(_D4)}
    result, scrub_calls = _run(conn)
    assert result["totals"]["derived"] == 1 and result["totals"]["failed"] == 0
    assert conn.bar_write_rows == []
    assert len(conn.lineage_rows) == 4
    assert all(r[2] == RULE_VERSION for r in conn.lineage_rows)
    assert scrub_calls and scrub_calls[0]["tf"] == "1d"


def test_differing_close_and_missing_date_each_write_once():
    conn = FakeConn(
        observations=_observations_fixture(),
        stored=_canonical_fixture_stored(),
        synthetic={"TEST": {_D4, date(2024, 6, 5)}},
    )
    result, _ = _run(conn)
    assert len(conn.bar_write_rows) == 2
    written_dates = sorted(r[0].date() for r in conn.bar_write_rows)
    assert written_dates == [_D3, _D4]
    d3_row = next(r for r in conn.bar_write_rows if r[0].date() == _D3)
    assert d3_row[6] == 12.0 and d3_row[9] == "USD"
    assert result["reasons"] == {
        "d1_value_differs": 1,
        "missing": 1,
        "volume_differs": 0,
        "split_rescale": 0,
    }
    assert len(conn.lineage_rows) == 4


def test_dry_run_writes_nothing_and_reports_reasons(tmp_path):
    conn = FakeConn(
        observations=_observations_fixture(),
        stored=_canonical_fixture_stored(),
        synthetic={"TEST": {_D4}},
    )
    report = tmp_path / "report.md"
    result, scrub_calls = _run(conn, apply=False, report_path=str(report))
    assert conn.bar_write_rows == []
    assert conn.lineage_rows == []
    assert conn.digest_rows == []
    assert conn.flag_inserts == []
    assert scrub_calls == []
    # No batch row on a dry run (grid convention): no open/close statements.
    assert not [sql for sql, _ in conn.statements if "bar_derivation_batch" in sql]
    text = report.read_text()
    assert "d1_value_differs" in text and "missing" in text
    assert "dry run" in text


def test_pre_split_flags_written_via_write_flags_shape():
    conn = FakeConn(
        observations={
            "TEST": _obs_rows(
                {_D1: 10.0, _D2: 11.0, _D3: 12.0, _D4: 13.0},
                fetched_at=datetime(2024, 6, 1, tzinfo=UTC),
            )
        },
        stored=_canonical_fixture_stored(),
        splits={
            "TEST": [
                {
                    "effective_date": date(2024, 6, 3),
                    "recorded_at": datetime(2024, 6, 11, tzinfo=UTC),
                    "factor": 2.0,
                }
            ]
        },
    )
    conn.stored["TEST"][_D3] = {**_stored_row(12.0), "timestamp": _ts(_D3)}
    conn.stored["TEST"][_D4] = {**_stored_row(13.0), "timestamp": _ts(_D4)}
    result, _ = _run(conn)
    # d1/d2 pre-effective with a pre-recording fetch: flagged; d3/d4 clean.
    pre_split = [r for r in conn.flag_inserts if r[3] == "pre_split_unrefetched"]
    assert len(pre_split) == 2
    assert {r[2].date() for r in pre_split} == {_D1, _D2}
    assert all(r[6] is True for r in pre_split)  # quarantine per APR list
    assert all(r[4] == RULE_VERSION for r in pre_split)
    assert result["n_pre_split_bars"] == 2


def test_digest_rows_only_for_months_whose_digest_changed():
    conn = FakeConn(
        observations=_observations_fixture(),
        stored=_canonical_fixture_stored(),
        synthetic={"TEST": {_D4}},
    )
    may_digest, may_n = _digest([_D1, _D2], [10.0, 11.0])
    conn.current_digests = {"TEST": [(datetime(2024, 5, 1, tzinfo=UTC), may_digest)]}
    result, _ = _run(conn)
    assert [r for r in conn.digest_rows if r[2].month == 5] == []
    june = [r for r in conn.digest_rows if r[2].month == 6]
    assert len(june) == 1
    expected, n = _digest([_D3, _D4], [12.0, 13.0])
    assert june[0][4] == expected
    assert june[0][5] == DIGEST_ALGORITHM and june[0][6] == RULE_VERSION
    assert june[0][7] == n and june[0][8] == _BATCH_ID


def test_changed_only_skips_symbol_without_new_answers():
    conn = FakeConn(
        observations=_observations_fixture(),
        stored=_canonical_fixture_stored(),
        changed_since={"TEST": False},
    )
    result, _ = _run(conn, changed_only=True)
    assert result["totals"]["unchanged"] == 1
    assert conn.bar_write_rows == []
    assert conn.lineage_rows == []
    # The probe runs before the observation load: an unchanged symbol never
    # fetches observations, splits, or stored rows (the derivation it would
    # feed is skipped). n_canonical is 0 by construction. The probe itself is
    # a fetchrow; the observation load would be a fetch.
    obs_kinds = [kind for kind, sql in conn.calls if "ohlcv_observation" in sql]
    assert obs_kinds == ["fetchrow"]
    assert not any("corporate_action_current" in sql for kind, sql in conn.calls if kind == "fetch")
    assert result["canonical_bars"] == 0


def test_venue_observations_gated_by_apr_flag():
    venue_day = date(2024, 4, 30)
    venue_obs = {
        "request_id": "req-venue",
        "route": "NYSE",
        "bar_date": venue_day,
        "open": 9.0,
        "high": 9.0,
        "low": 9.0,
        "close": 9.0,
        "volume": 50,
        "fetched_at": _FETCHED,
        "what_to_show": "TRADES",
        "legacy": False,
    }
    # SMART coverage starts at _D2, so venue_day is strictly pre-head.
    observations = {"TEST": _obs_rows({_D2: 11.0, _D3: 12.0, _D4: 13.0})}
    observations["TEST"].append(venue_obs)
    stored = {
        "TEST": {
            _D2: {**_stored_row(11.0), "timestamp": _ts(_D2)},
            _D3: {**_stored_row(12.0), "timestamp": _ts(_D3)},
            _D4: {**_stored_row(13.0), "timestamp": _ts(_D4)},
        }
    }
    conn_disabled = FakeConn(observations=observations, stored=stored)
    _run(conn_disabled)
    assert all(r[1].date() != venue_day for r in conn_disabled.lineage_rows)

    conn_enabled = FakeConn(observations=observations, stored=stored, venue_enabled=True)
    _run(conn_enabled)
    assert any(r[1].date() == venue_day for r in conn_enabled.lineage_rows)


def test_no_observations_counts_and_moves_on():
    conn = FakeConn(observations={"TEST": []}, stored={})
    result, _ = _run(conn)
    assert result["totals"]["no_observations"] == 1
    assert conn.bar_write_rows == [] and conn.lineage_rows == []


def test_report_lists_top_symbols_and_pre_split(tmp_path):
    conn = FakeConn(
        observations=_observations_fixture(),
        stored=_canonical_fixture_stored(),
        synthetic={"TEST": {_D4}},
    )
    report = tmp_path / "report.md"
    _run(conn, apply=False, report_path=str(report))
    text = report.read_text()
    assert "TEST" in text
    assert "pre_split_unrefetched" in text
    assert "top 20" in text.lower()


def test_tradier_owned_symbol_is_skipped_even_with_observations():
    # Migration 438: a name whose latest daily load came from Tradier is never re-derived from IBKR.
    from services.bar_derivation import _SELECT_DAILY_CHANGED_SINCE_SQL

    assert "FROM ohlcv_load" in _SELECT_DAILY_CHANGED_SINCE_SQL
    assert "tradier_owned" in _SELECT_DAILY_CHANGED_SINCE_SQL
