"""Unit tests for the split-seam audit (scripts/ops/bars/ops_seam_audit.py), fakes only."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from scripts.ops.bars import ops_seam_audit as mod

_KW = {"rel_tol": 0.002, "min_run": 5, "ratio_snap_tol": 0.01}
_START = date(2026, 1, 1)


def _days(n: int) -> list[date]:
    return [_START + timedelta(days=i) for i in range(n)]


def _series(prices: list[float]) -> dict[date, float]:
    return dict(zip(_days(len(prices)), prices, strict=True))


def _split_case() -> tuple[dict[date, float], dict[date, float]]:
    fresh = _series([50.0 + 0.1 * i for i in range(30)])
    stored = {d: (v * 2.0 if i < 20 else v) for i, (d, v) in enumerate(fresh.items())}
    return stored, fresh


def test_two_for_one_seam_is_a_split_ending_on_the_last_old_scale_day() -> None:
    stored, fresh = _split_case()
    audit = mod.audit_symbol(stored, fresh, **_KW)
    assert audit.skipped is None
    assert len(audit.splits) == 1 and not audit.unexplained
    split = audit.splits[0]
    assert split.kind == "split" and split.factor == pytest.approx(2.0)
    assert split.effective_date == _days(20)[19]


def test_news_move_is_no_seam_and_no_corporate_action() -> None:
    fresh = _series([50.0 + 0.1 * i for i in range(30)])
    audit = mod.audit_symbol(dict(fresh), fresh, **_KW)
    assert not audit.splits and not audit.unexplained


def test_non_constant_disagreement_is_unexplained_never_a_split() -> None:
    fresh = _series([50.0] * 30)
    stored = {d: 50.0 * (1.0 + 0.03 * i) if i < 20 else 50.0 for i, d in enumerate(_days(30))}
    audit = mod.audit_symbol(stored, fresh, **_KW)
    assert not audit.splits
    assert audit.unexplained  # the disagreement is listed, not forced into a split


def test_constant_ratio_that_snaps_to_no_split_is_unexplained() -> None:
    fresh = _series([50.0 + 0.1 * i for i in range(30)])
    stored = {d: v * 1.01 if i < 20 else v for i, (d, v) in enumerate(fresh.items())}
    audit = mod.audit_symbol(stored, fresh, **_KW)
    assert not audit.splits and len(audit.unexplained) == 1


def test_run_reaching_the_last_compared_day_is_unexplained() -> None:
    fresh = _series([50.0 + 0.1 * i for i in range(30)])
    stored = {d: v * 2.0 for d, v in fresh.items()}
    audit = mod.audit_symbol(stored, fresh, **_KW)
    assert not audit.splits and audit.unexplained


def test_too_little_overlap_is_skipped() -> None:
    fresh = _series([50.0, 51.0])
    audit = mod.audit_symbol(dict(fresh), fresh, **_KW)
    assert audit.skipped is not None


def test_symbols_run_mrna_and_alms_first() -> None:
    assert mod.order_symbols(["ZZZ", "ALMS", "AAPL", "MRNA"]) == ["MRNA", "ALMS", "AAPL", "ZZZ"]


def test_flags_cover_every_stored_bar_through_the_effective_date_only() -> None:
    stored, fresh = _split_case()
    audit = mod.audit_symbol(stored, fresh, **_KW)
    stamps = [datetime(d.year, d.month, d.day, tzinfo=UTC) for d in sorted(stored)]
    flags = mod.split_seam_flags(stamps, audit.splits, quarantine=True)
    assert [f.timestamp for f in flags] == stamps[:20]
    assert all(f.rule == "split_seam" and f.quarantine for f in flags)
    assert flags[0].detail["cumulative_factor"] == pytest.approx(2.0)


def test_apply_writes_one_corporate_action_and_flags_in_one_transaction() -> None:
    stored, fresh = _split_case()
    audit = mod.audit_symbol(stored, fresh, **_KW)
    conn = _FakeConn()
    stamps = [datetime(d.year, d.month, d.day, tzinfo=UTC) for d in sorted(stored)]
    asyncio.run(
        mod.apply_symbol(
            conn,
            symbol="AAA",
            audit=audit,
            stored_timestamps=stamps,
            evidence_request_ids=["r-fresh", "r-legacy"],
            batch_id="b1",
            quarantine=True,
            write_flags_fn=conn.write_flags,
        )
    )
    inserts = [c for c in conn.calls if "INSERT INTO corporate_action" in c[0]]
    assert len(inserts) == 1
    args = inserts[0][1]
    assert args[0] == "AAA" and args[1] == "split" and args[3] == pytest.approx(2.0)
    assert args[4] == ["r-fresh", "r-legacy"]
    assert conn.flag_calls and len(conn.flag_calls[0]["flags"]) == 20
    assert conn.transactions == 1


def test_apply_skips_an_equivalent_existing_corporate_action() -> None:
    stored, fresh = _split_case()
    audit = mod.audit_symbol(stored, fresh, **_KW)
    conn = _FakeConn(existing=[("existing-id", 2.0)])
    asyncio.run(
        mod.apply_symbol(
            conn,
            symbol="AAA",
            audit=audit,
            stored_timestamps=[],
            evidence_request_ids=["r"],
            batch_id="b1",
            quarantine=True,
            write_flags_fn=conn.write_flags,
        )
    )
    assert not [c for c in conn.calls if "INSERT INTO corporate_action" in c[0]]


def test_evidence_ids_must_be_non_empty() -> None:
    stored, fresh = _split_case()
    audit = mod.audit_symbol(stored, fresh, **_KW)
    with pytest.raises(ValueError):
        asyncio.run(
            mod.apply_symbol(
                _FakeConn(),
                symbol="AAA",
                audit=audit,
                stored_timestamps=[],
                evidence_request_ids=[],
                batch_id="b1",
                quarantine=True,
                write_flags_fn=lambda *a, **k: None,
            )
        )


class _Tx:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> None:
        self._conn.transactions += 1

    async def __aexit__(self, *exc: Any) -> None:
        return None


class _FakeConn:
    def __init__(self, existing: list[tuple[str, float]] | None = None) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.flag_calls: list[dict[str, Any]] = []
        self.transactions = 0
        self._existing = existing or []

    def transaction(self) -> _Tx:
        return _Tx(self)

    async def execute(self, sql: str, *args: Any) -> str:
        self.calls.append((sql, args))
        return "OK"

    async def fetch(self, sql: str, *args: Any) -> list[tuple[str, float]]:
        self.calls.append((sql, args))
        return self._existing

    async def write_flags(self, conn: Any, **kwargs: Any) -> int:
        self.flag_calls.append(kwargs)
        return len(kwargs["flags"])
