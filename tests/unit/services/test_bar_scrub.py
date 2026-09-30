"""Tests for services/bar_scrub.py (phase 185 plan 10, task 1).

Fakes only, no DB: a fake pool answering the three read shapes the library
issues (config_state APR rows, DISTINCT-symbol discovery, per-symbol bars from
market_data_ohlcv_scrub_input) and a fake connection recording every statement.
The contract under test: corroboration spans the whole run behind the D-11
ceiling, write_flags is one delete-then-insert transaction whose first statement
is SET LOCAL ROLE bar_derivation_writer and never touches
'legacy_price_sanity_status', quarantine comes strictly from the APR list, a
failed symbol read is collected while other symbols still complete, and
rules=None means every rule at 1d but only the D-14 ports intraday.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from structlog.testing import capture_logs

from services.bar_scrub import FlagRow, scrub_symbols, write_flags
from tests.unit.bars._builders import seeded_apr

_SPIKE_DAY = datetime(2024, 6, 3, tzinfo=UTC)
_BATCH = "0b8e0a34-1f2c-4d5e-9a6b-7c8d9e0f1a2b"


def _apr_rows(overrides: dict[str, object] | None = None) -> list[tuple[str, str]]:
    apr = seeded_apr()
    apr.update(overrides or {})
    return [(key, str(value)) for key, value in sorted(apr.items())]


def _daily_bars(
    spike_mult: float | None, *, n: int = 6, spike_at: int = 3, base: float = 100.0
) -> list[tuple]:
    """n daily bars near `base`; bar spike_at's high is spike_mult x the reference.

    Every other D2a rule stays silent on this series (prices wander under 1%,
    volume is constant, gaps are exactly one day), so only price_sanity can fire.
    """
    rows: list[tuple] = []
    for i in range(n):
        ts = _SPIKE_DAY + timedelta(days=i - spike_at)
        px = base + (i % 3) * 0.5
        high = px * 1.01
        if i == spike_at and spike_mult is not None:
            high = px * spike_mult
        rows.append((ts, px, high, px * 0.99, px, 1_000_000.0))
    return rows


def _stale_run_bars(n: int = 6, *, run: int = 5) -> list[tuple]:
    """n daily bars where the first `run` are identical with positive volume."""
    rows: list[tuple] = []
    for i in range(n):
        ts = _SPIKE_DAY + timedelta(days=i)
        if i < run:
            rows.append((ts, 50.0, 50.5, 49.5, 50.0, 10_000.0))
        else:
            px = 50.0 + 0.2 * (i - run + 1)
            rows.append((ts, px, px * 1.01, px * 0.99, px, 10_000.0))
    return rows


def _five_min_bars(*, jump_at: int = 4, gap_after: int = 6, n: int = 10) -> list[tuple]:
    """5m bars with a 2x open jump at jump_at and a 2h gap after gap_after.

    A 12x high sits on the jump bar too: with rules=None at 5m only the D-14
    ports run, so price_sanity must NOT flag it.
    """
    rows: list[tuple] = []
    stamp = datetime(2024, 6, 3, 14, 30, tzinfo=UTC)
    hole_slots = 0
    for i in range(n):
        if i == gap_after + 1:
            hole_slots += 24  # one 2h hole between bar gap_after and the next
        ts = stamp + timedelta(seconds=300 * (i + hole_slots))
        px = 100.0 + 0.1 * i
        open_ = px * 2.0 if i == jump_at else px
        high = open_ * 12.0 if i == jump_at else px * 1.01
        rows.append((ts, open_, high, px * 0.99, px, 5_000.0))
    return rows


class FakeConn:
    """asyncpg-shaped fake answering the library's three reads and recording writes."""

    def __init__(
        self,
        bars: dict[str, list[tuple]],
        apr_rows: list[tuple[str, str]],
        fail_symbols: frozenset[str] = frozenset(),
    ) -> None:
        self.bars = bars
        self.apr_rows = apr_rows
        self.fail_symbols = fail_symbols
        self.statements: list[tuple[str, tuple]] = []
        self.fetch_calls: list[tuple[str, tuple]] = []
        self.executemany_calls: list[tuple[str, list[tuple]]] = []

    class _Txn:
        def __init__(self, outer: FakeConn) -> None:
            self.outer = outer

        async def __aenter__(self) -> None:
            self.outer.statements.append(("<begin>", ()))

        async def __aexit__(self, *exc: object) -> bool:
            self.outer.statements.append(("<commit>", ()))
            return False

    def transaction(self) -> FakeConn._Txn:
        return self._Txn(self)

    async def fetch(self, sql: str, *args: object) -> list[tuple]:
        self.fetch_calls.append((sql, tuple(args)))
        if "config_state" in sql:
            # asyncpg Records are mapping-shaped; load_apr_dict_async indexes by
            # column name while the library's own reads are positional.
            return [{"config_key": key, "config_value": value} for key, value in self.apr_rows]
        if "DISTINCT symbol" in sql:
            return [(symbol,) for symbol in sorted(self.bars)]
        symbol = str(args[0])
        if symbol in self.fail_symbols:
            raise RuntimeError(f"read failed for {symbol}")
        return list(self.bars[symbol])

    async def execute(self, sql: str, *args: object) -> str:
        self.statements.append((sql, tuple(args)))
        return "DELETE 2"

    async def executemany(self, sql: str, args_seq: object) -> str:
        args = [tuple(a) for a in args_seq]
        self.executemany_calls.append((sql, args))
        return f"INSERT {len(args)}"


class FakePool:
    """asyncpg.Pool-shaped fake yielding always the same connection."""

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


def _inserted_flags(conn: FakeConn, rule: str) -> list[tuple]:
    rows: list[tuple] = []
    for _, args in conn.executemany_calls:
        rows.extend(a for a in args if a[3] == rule)
    return rows


def _run_scrub(conn: FakeConn, **overrides: object) -> dict[str, int]:
    return asyncio.run(
        scrub_symbols(
            FakePool(conn),
            tf=overrides.pop("tf", "1d"),
            symbols=overrides.pop("symbols", None),
            rules=overrides.pop("rules", None),
            start=None,
            end=None,
            batch_id=_BATCH,
            **overrides,
        )
    )


def test_ten_x_high_on_two_symbols_stays_quarantined() -> None:
    """Both symbols print a ~12x high on the same day: corroboration (2 symbols
    is under min_symbols 4 anyway, and the 2.5 ceiling blocks the downgrade)
    must not clear either flag; both bars are written as quarantine price_sanity."""
    conn = FakeConn({"AAA": _daily_bars(12.0), "BBB": _daily_bars(12.0)}, _apr_rows())
    counts = _run_scrub(conn)
    assert counts["price_sanity"] == 2
    rows = _inserted_flags(conn, "price_sanity")
    assert len(rows) == 2
    assert {row[2] for row in rows} == {_SPIKE_DAY}
    assert all(row[6] is True for row in rows)  # quarantine column


def test_two_x_print_on_four_symbols_not_flagged() -> None:
    """Four symbols print a ~2x high on the same day with magnitude_threshold
    lowered to 1.5: each is CONFIRMED_CORRUPT alone, but with 3 corroborating
    others (min_symbols 4) and max_ratio under the 2.5 ceiling the verdict
    becomes MARKET_EVENT and no price_sanity flag is written."""
    bars = {f"S{i}": _daily_bars(2.0) for i in range(4)}
    conn = FakeConn(bars, _apr_rows({"alpha.quant.price_sanity.magnitude_threshold": 1.5}))
    counts = _run_scrub(conn)
    assert counts["price_sanity"] == 0
    assert _inserted_flags(conn, "price_sanity") == []


def test_quarantine_matches_apr_list() -> None:
    """quarantine on every written FlagRow equals rule membership in the APR
    quarantine list: price_sanity quarantines, stale_print does not."""
    conn = FakeConn(
        {"AAA": _daily_bars(12.0), "BBB": _stale_run_bars()},
        _apr_rows(),
    )
    _run_scrub(conn)
    ps = _inserted_flags(conn, "price_sanity")
    stale = _inserted_flags(conn, "stale_print")
    assert ps and all(row[6] is True for row in ps)
    assert stale and all(row[6] is False for row in stale)


def test_counts_cover_every_evaluated_rule_with_zeros() -> None:
    conn = FakeConn({"AAA": _daily_bars(None)}, _apr_rows())
    counts = _run_scrub(conn)
    assert counts == {
        "gap_before_next": 0,
        "non_positive_price": 0,
        "ohlc_invariant": 0,
        "price_sanity": 0,
        "return_magnitude": 0,
        "stale_print": 0,
        "volume_outlier": 0,
        "vol_scaled_jump": 0,
    }


def test_intraday_default_rules_are_d14_ports_only() -> None:
    """rules=None at 5m runs return_magnitude and gap_before_next only: the 2x
    open jump and the 2h gap flag, while the 12x high prints no price_sanity."""
    conn = FakeConn({"AAA": _five_min_bars()}, _apr_rows())
    counts = _run_scrub(conn, tf="5m")
    # two return_magnitude entries: the jump-up bar and the revert-down bar
    # (both open-to-open returns are suspect, the writer's semantics)
    assert counts == {"return_magnitude": 2, "gap_before_next": 1}
    assert _inserted_flags(conn, "price_sanity") == []
    jump_rows = _inserted_flags(conn, "return_magnitude")
    assert all(row[6] is False for row in jump_rows)


def test_explicit_rule_subset_runs_only_that_rule() -> None:
    conn = FakeConn({"BBB": _stale_run_bars()}, _apr_rows())
    counts = _run_scrub(conn, rules=frozenset({"price_sanity"}))
    assert set(counts) == {"price_sanity"}
    assert _inserted_flags(conn, "stale_print") == []


def test_failed_symbol_read_collected_and_raised_after_others_complete() -> None:
    conn = FakeConn(
        {"AAA": _daily_bars(12.0), "BBB": _daily_bars(12.0)},
        _apr_rows(),
        fail_symbols=frozenset({"BBB"}),
    )
    with pytest.raises(RuntimeError, match="1 symbol read failure.*BBB"):
        _run_scrub(conn)
    assert len(_inserted_flags(conn, "price_sanity")) == 1


def test_dry_run_computes_but_writes_nothing() -> None:
    conn = FakeConn({"AAA": _daily_bars(12.0)}, _apr_rows())
    counts = _run_scrub(conn, write=False)
    assert counts["price_sanity"] == 1
    assert conn.executemany_calls == []
    assert all("DELETE FROM bar_quality_flag" not in sql for sql, _ in conn.statements)


def test_quarantine_key_sink_collects_written_quarantine_keys() -> None:
    conn = FakeConn({"AAA": _daily_bars(12.0), "BBB": _stale_run_bars()}, _apr_rows())
    sink: list[tuple[str, str, datetime]] = []
    _run_scrub(conn, quarantine_key_sink=sink)
    assert sink == [("price_sanity", "AAA", _SPIKE_DAY)]


# ---------------------------------------------------------------------------
# write_flags statement shape
# ---------------------------------------------------------------------------


def _flag_row(rule: str = "price_sanity", quarantine: bool = True) -> FlagRow:
    return FlagRow(
        timestamp=_SPIKE_DAY,
        rule=rule,
        rule_version="scrub-v1",
        fields=("high",),
        quarantine=quarantine,
        detail={"max_ratio": 12.0},
    )


def test_write_flags_delete_then_insert_under_writer_role() -> None:
    conn = FakeConn({}, [])
    n = asyncio.run(
        write_flags(
            conn,
            tf="1d",
            symbol="AAA",
            rules_evaluated=frozenset({"price_sanity", "vol_scaled_jump"}),
            flags=[_flag_row()],
            start=None,
            end=None,
            batch_id=_BATCH,
        )
    )
    assert n == 1
    kinds = [sql for sql, _ in conn.statements]
    assert kinds[0] == "<begin>"
    assert kinds[1].strip() == "SET LOCAL ROLE bar_derivation_writer"
    assert kinds[-1] == "<commit>"
    deletes = [sql for sql in kinds if sql.strip().startswith("DELETE FROM bar_quality_flag")]
    assert len(deletes) == 1
    insert_sql, insert_args = conn.executemany_calls[0]
    assert "INSERT INTO bar_quality_flag" in insert_sql
    (arg,) = insert_args
    assert arg[0] == "AAA" and arg[1] == "1d" and arg[3] == "price_sanity"
    assert arg[8] == _BATCH


def test_write_flags_prune_stale_deletes_other_rules_except_legacy() -> None:
    conn = FakeConn({}, [])
    with capture_logs() as logs:
        asyncio.run(
            write_flags(
                conn,
                tf="1d",
                symbol="AAA",
                rules_evaluated=frozenset({"price_sanity"}),
                flags=[],
                start=None,
                end=None,
                batch_id=_BATCH,
                prune_stale=True,
            )
        )
    deletes = [
        sql for sql, _ in conn.statements if sql.strip().startswith("DELETE FROM bar_quality_flag")
    ]
    assert len(deletes) == 2
    assert "rule = ANY($3::text[])" in deletes[0]
    assert "rule <> ALL($3::text[])" in deletes[1]
    assert "'legacy_price_sanity_status'" in deletes[1]
    # the seam audit's quarantine flags belong to plan 15, not the scrub pass
    assert "'split_seam'" in deletes[1]
    assert any(
        event.get("event") == "bar_scrub.pruned_stale_flags" and event.get("deleted") == 2
        for event in logs
    )


def test_write_flags_refuses_legacy_rule_in_evaluated_set() -> None:
    conn = FakeConn({}, [])
    with pytest.raises(ValueError, match="legacy_price_sanity_status"):
        asyncio.run(
            write_flags(
                conn,
                tf="1d",
                symbol="AAA",
                rules_evaluated=frozenset({"legacy_price_sanity_status"}),
                flags=[],
                start=None,
                end=None,
                batch_id=_BATCH,
            )
        )


def test_scrub_symbols_refuses_legacy_and_view_disagreement_rules() -> None:
    conn = FakeConn({"AAA": _daily_bars(None)}, _apr_rows())
    with pytest.raises(ValueError, match="legacy_price_sanity_status"):
        _run_scrub(conn, rules=frozenset({"legacy_price_sanity_status"}))
    with pytest.raises(ValueError, match="view_disagreement"):
        _run_scrub(conn, rules=frozenset({"view_disagreement"}))


def test_scrub_symbols_passes_start_end_into_bar_reads() -> None:
    conn = FakeConn({"AAA": _daily_bars(12.0)}, _apr_rows())
    start = _SPIKE_DAY - timedelta(days=1)
    end = _SPIKE_DAY + timedelta(days=1)
    asyncio.run(
        scrub_symbols(
            FakePool(conn),
            tf="1d",
            symbols=None,
            rules=None,
            start=start,
            end=end,
            batch_id=_BATCH,
        )
    )
    bar_reads = [
        args
        for sql, args in conn.fetch_calls
        if "market_data_ohlcv_scrub_input" in sql and "DISTINCT symbol" not in sql
    ]
    assert bar_reads and all(args[-2:] == (start, end) for args in bar_reads)
