"""ops_d191q_arbitration.py (todo 545): read-only, refuses without Tradier rows, writes the plan
JSON and the evidence report."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, date, datetime, timedelta

from scripts.ops.bars import ops_d191q_arbitration as arb
from src.intelligence.bars.derivation import Observation


def _sessions(start: date, n: int) -> list[date]:
    days, day = [], start
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _obs(route: str, day: date, close: float, volume: int = 100) -> Observation:
    return Observation(
        request_id=f"{route}-{day}",
        route=route,
        bar_date=day,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=volume,
        fetched_at=datetime(2026, 10, 27, tzinfo=UTC),
        legacy=False,
    )


class _FakeConn:
    def __init__(self, *, tradier: bool) -> None:
        self.tradier = tradier
        self.statements: list[str] = []

    async def execute(self, sql: str, *args: object) -> str:
        self.statements.append(sql)
        return "SET"

    async def fetchval(self, sql: str, *args: object) -> object:
        self.statements.append(sql)
        if "tradier" in sql:
            return date(2026, 10, 6) if self.tradier else None
        raise AssertionError(sql)

    async def fetch(self, sql: str, *args: object) -> list[dict]:
        self.statements.append(sql)
        if "config_state" in sql:
            return []
        if "count(*) AS n_rows" in sql:
            return [
                {
                    "vendor": "alpaca",
                    "kind": "sip_rth",
                    "n_rows": 300,
                    "max_served_at": datetime(2026, 10, 27, tzinfo=UTC),
                }
            ]
        if "symbol IS NULL" in sql:
            return [{"policy_id": "id-default-tradier"}, {"policy_id": "id-default-ibkr"}]
        if "ohlcv_provider_head" in sql:
            return [{"symbol": "PINS", "head": date(2019, 4, 18)}]
        if "bar_source_policy_current" in sql:
            return [
                {
                    "policy_id": "id-wdc",
                    "symbol": "WDC",
                    "valid_from": date(1990, 1, 1),
                    "valid_to": date(2026, 10, 7),
                    "primary_source": "ibkr",
                    "fallback_source": None,
                }
            ]
        if "FROM ohlcv_raw" in sql:
            return [{"symbol": "WDC"}]
        raise AssertionError(sql)


def test_refuses_without_tradier_rows(tmp_path):
    conn = _FakeConn(tradier=False)
    code = asyncio.run(
        arb.run(
            conn,
            plan_path=tmp_path / "p.json",
            report_path=tmp_path / "r.md",
            evidence_dir=tmp_path / "evidence",
        )
    )
    assert code == 2
    assert not (tmp_path / "p.json").exists() and not (tmp_path / "r.md").exists()
    assert not (tmp_path / "evidence").exists()


def test_the_session_is_read_only_and_writes_the_plan_and_report(tmp_path, monkeypatch):
    days = _sessions(date(2024, 1, 2), 100)
    spin = days[70]

    async def inputs(conn, symbol):
        observations = []
        for d in days:
            observations.append(_obs("ALPACA", d, 49.0 if d >= spin else 68.8))
            observations.append(_obs("SMART", d, 49.0 if d >= spin else 52.0))
            observations.append(_obs("TRADIER", d, 49.0 if d >= spin else 52.0))
        return observations, []

    monkeypatch.setattr(arb, "read_daily_inputs", inputs)
    conn = _FakeConn(tradier=True)
    code = asyncio.run(
        arb.run(
            conn,
            plan_path=tmp_path / "p.json",
            report_path=tmp_path / "r.md",
            evidence_dir=tmp_path / "evidence",
        )
    )
    assert code == 0
    import gzip

    (gz,) = (tmp_path / "evidence").glob("d191q_1d_plan_*.json.gz")
    assert gzip.decompress(gz.read_bytes()) == (tmp_path / "p.json").read_bytes()
    assert "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY" in conn.statements[0]
    assert not any(
        s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in conn.statements
    )
    plan = json.loads((tmp_path / "p.json").read_text())
    (row,) = plan["symbol_rows"]
    assert row["symbol"] == "WDC" and row["primary"] == "ibkr"
    assert plan["retire_symbol_rows"][0]["disposition"] == "replaced"
    assert plan["retire_default_ids"] == ["id-default-ibkr", "id-default-tradier"]
    assert plan["raw_fingerprint"]["series"]["alpaca/sip_rth"]["rows"] == 300
    report = (tmp_path / "r.md").read_text()
    import hashlib

    digest = hashlib.sha256((tmp_path / "p.json").read_bytes()).hexdigest()
    assert digest in report and "## Quarantine" in report
    assert hashlib.sha256(gz.read_bytes()).hexdigest() in report
    assert "## Window-end spans" in report
    for heading in ("## Classes", "## IBKR symbol rows", "## Hold list", "## Live symbol rows"):
        assert heading in report
    assert str(tmp_path / "p.json") in report
