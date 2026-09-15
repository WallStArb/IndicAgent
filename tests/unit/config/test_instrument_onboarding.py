"""Unit tests for src/config/instrument_onboarding.py's onboard_instrument().

Covers the qualification gate (V5 / T-174-02), the metadata mandate (D-08),
the tag-vocabulary gate (ITR rule), parameterization (T-174-02), and the
transaction contract (T-174-42) -- the caller's outer transaction is never
stolen or closed by this helper.

No live database, no live IBKR: a fake asyncpg-shaped connection records every
(sql, args) pair and every transaction enter/exit, and a fake qualifier
implements the InstrumentQualifier Protocol without ever touching ib_async.
"""

from __future__ import annotations

from typing import Any

import pytest
from structlog.testing import capture_logs

from src.config.instrument_onboarding import (
    OnboardingRejected,
    onboard_instrument,
)
from src.core.models import AssetClass, Instrument

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeTransactionCM:
    """Fake asyncpg transaction-context manager.

    Never swallows exceptions (asyncpg's real Transaction doesn't either) --
    __aexit__ returns False/None so the caller sees the original exception.
    Records entered/exited/exc_type on itself so tests can assert on a
    specific transaction() call's outcome directly.
    """

    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn
        self.entered = False
        self.exited = False
        self.exc_type: type[BaseException] | None = None

    async def __aenter__(self) -> _FakeTransactionCM:
        self.entered = True
        self._conn.tx_stack.append(self)
        self._conn.transaction_log.append(("enter", self))
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self.exited = True
        self.exc_type = exc_type
        self._conn.transaction_log.append(("exit", self, exc_type))
        if self._conn.tx_stack and self._conn.tx_stack[-1] is self:
            self._conn.tx_stack.pop()
        return False


class FakeConnection:
    """Fake asyncpg-shaped connection.

    fail_on: a substring; any execute() whose sql contains this substring
    raises RuntimeError, simulating a mid-transaction write failure (used by
    the atomicity case).
    """

    def __init__(
        self,
        known_tags: set[str] | None = None,
        fail_on: str | None = None,
    ) -> None:
        self.statements: list[tuple[str, tuple]] = []
        self.tx_stack: list[_FakeTransactionCM] = []
        self.transaction_log: list[tuple] = []
        self.transaction_call_count = 0
        self.commit_calls = 0
        self.rollback_calls = 0
        self._known_tags = known_tags or set()
        self._fail_on = fail_on

    def transaction(self) -> _FakeTransactionCM:
        self.transaction_call_count += 1
        return _FakeTransactionCM(self)

    async def commit(self) -> None:
        self.commit_calls += 1

    async def rollback(self) -> None:
        self.rollback_calls += 1

    async def fetch(self, sql: str, *args: Any) -> list[dict]:
        self.statements.append((sql, args))
        if "tag_vocabulary" in sql:
            requested = args[0]
            return [{"tag": t} for t in requested if t in self._known_tags]
        return []

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.statements.append((sql, args))
        return None

    async def execute(self, sql: str, *args: Any) -> str:
        self.statements.append((sql, args))
        if self._fail_on and self._fail_on in sql:
            raise RuntimeError(f"simulated failure: {self._fail_on}")
        return "INSERT 0 1"


class FakeQualifier:
    """Fake InstrumentQualifier -- no IBKR, no event loop I/O."""

    def __init__(self, qualifies: bool = True) -> None:
        self.qualifies = qualifies
        self.calls: list[Instrument] = []

    async def qualify_instrument(
        self,
        instrument: Instrument,
        *,
        ibkr_symbol: str = "",
        trading_class: str = "",
    ) -> bool:
        self.calls.append(instrument)
        return self.qualifies


def _make_instrument(symbol: str) -> Instrument:
    return Instrument(
        symbol=symbol,
        base=symbol,
        name=f"{symbol} Test Co",
        asset_class=AssetClass.EQUITY,
        exchange="SMART",
        sector="technology",
        tick_size=0.01,
        session_id="nyse",
        point_value=1.0,
        provider_meta={},
    )


_SOME_METADATA = {
    "listing_date": "2020-01-01",
    "underlying_index": None,
    "issuer": "Test Issuer",
    "description": "test description",
}


def _statements_starting_with(conn: FakeConnection, prefix: str) -> list[tuple[str, tuple]]:
    return [(sql, args) for sql, args in conn.statements if sql.strip().startswith(prefix)]


# ---------------------------------------------------------------------------
# Case 1: qualification rejection writes nothing (V5 / T-174-02)
# ---------------------------------------------------------------------------


async def test_qualification_rejection_writes_nothing() -> None:
    conn = FakeConnection()
    qualifier = FakeQualifier(qualifies=False)
    instrument = _make_instrument("BADTICK")

    with pytest.raises(OnboardingRejected):
        await onboard_instrument(conn, instrument, qualifier=qualifier, metadata=_SOME_METADATA)

    assert _statements_starting_with(conn, "INSERT INTO instruments") == []
    assert conn.statements == []


# ---------------------------------------------------------------------------
# Case 2: happy path writes all four tables
# ---------------------------------------------------------------------------


async def test_happy_path_writes_all_four_tables() -> None:
    conn = FakeConnection(known_tags={"single_name_equity", "geopolitical"})
    qualifier = FakeQualifier(qualifies=True)
    instrument = _make_instrument("CCJ")

    result = await onboard_instrument(
        conn,
        instrument,
        qualifier=qualifier,
        tags=[
            ("single_name_equity", 1.0, {"reason": "individual company stock"}),
            ("geopolitical", 0.7, {"reason": "supply chain risk"}),
        ],
        metadata=_SOME_METADATA,
    )

    assert len(_statements_starting_with(conn, "INSERT INTO instruments")) == 1
    assert len(_statements_starting_with(conn, "INSERT INTO instrument_tags")) == 2
    assert len(_statements_starting_with(conn, "INSERT INTO instrument_metadata")) == 1
    assert len(_statements_starting_with(conn, "INSERT INTO backfill_status")) == 4
    assert result.backfill_rows_seeded == 4
    assert result.tags_inserted == 2
    assert result.metadata_written is True
    assert result.instrument_inserted is True


# ---------------------------------------------------------------------------
# Case 3: metadata omission without a reason is a hard error (D-08)
# ---------------------------------------------------------------------------


async def test_metadata_omission_without_reason_raises_valueerror() -> None:
    conn = FakeConnection()
    qualifier = FakeQualifier(qualifies=True)
    instrument = _make_instrument("NOMETA")

    with pytest.raises(ValueError):
        await onboard_instrument(
            conn,
            instrument,
            qualifier=qualifier,
            metadata=None,
            metadata_skip_reason="",
        )

    assert conn.statements == []
    # Fails before the qualification gate even runs -- omission is caught first.
    assert qualifier.calls == []


# ---------------------------------------------------------------------------
# Case 4: metadata omission with a reason is allowed but loud
# ---------------------------------------------------------------------------


async def test_metadata_omission_with_reason_logs_warning_event() -> None:
    conn = FakeConnection()
    qualifier = FakeQualifier(qualifies=True)
    instrument = _make_instrument("ETNX")

    with capture_logs() as cap_logs:
        result = await onboard_instrument(
            conn,
            instrument,
            qualifier=qualifier,
            metadata=None,
            metadata_skip_reason="ETN, no issuer listing record",
        )

    assert result.metadata_written is False
    assert _statements_starting_with(conn, "INSERT INTO instrument_metadata") == []
    events = [e["event"] for e in cap_logs]
    assert "instrument_onboarding.metadata_skipped" in events, f"Expected warning in {events}"
    entry = next(e for e in cap_logs if e["event"] == "instrument_onboarding.metadata_skipped")
    assert entry["log_level"] == "warning"
    assert entry["symbol"] == "ETNX"
    assert entry["reason"] == "ETN, no issuer listing record"


# ---------------------------------------------------------------------------
# Case 5: unregistered tag is rejected
# ---------------------------------------------------------------------------


async def test_unregistered_tag_rejected() -> None:
    conn = FakeConnection(known_tags=set())
    qualifier = FakeQualifier(qualifies=True)
    instrument = _make_instrument("TAGX")

    with pytest.raises(OnboardingRejected, match="not_a_real_tag"):
        await onboard_instrument(
            conn,
            instrument,
            qualifier=qualifier,
            tags=[("not_a_real_tag", 1.0, {"reason": "invented at insert time"})],
            metadata=_SOME_METADATA,
        )

    assert _statements_starting_with(conn, "INSERT INTO instruments") == []
    assert _statements_starting_with(conn, "INSERT INTO instrument_tags") == []


# ---------------------------------------------------------------------------
# Case 6: parameterization -- hostile symbol string never reaches SQL text
# ---------------------------------------------------------------------------


async def test_hostile_symbol_reaches_db_only_as_bound_parameter() -> None:
    conn = FakeConnection()
    qualifier = FakeQualifier(qualifies=True)
    hostile = "AAPL'); DROP TABLE instruments;--"
    instrument = _make_instrument(hostile)

    result = await onboard_instrument(
        conn, instrument, qualifier=qualifier, metadata=_SOME_METADATA
    )

    assert result.symbol == hostile
    assert conn.statements  # writes did happen
    for sql, _args in conn.statements:
        assert "DROP TABLE" not in sql
        assert hostile not in sql
    assert any(hostile in args for _sql, args in conn.statements)


# ---------------------------------------------------------------------------
# Case 7: defaults -- compute_eligible/live_tradeable bind False
# ---------------------------------------------------------------------------


async def test_defaults_bind_compute_eligible_and_live_tradeable_false() -> None:
    conn = FakeConnection()
    qualifier = FakeQualifier(qualifies=True)
    instrument = _make_instrument("DEFAULT1")

    await onboard_instrument(conn, instrument, qualifier=qualifier, metadata=_SOME_METADATA)

    [(_sql, args)] = _statements_starting_with(conn, "INSERT INTO instruments")
    # Positional args: symbol, base, contract_details_json, compute_eligible, live_tradeable
    assert args[3] is False
    assert args[4] is False


# ---------------------------------------------------------------------------
# Case 8: atomicity -- a write failure propagates through the transaction
# context without the helper calling commit or rollback itself.
# ---------------------------------------------------------------------------


async def test_atomicity_exception_propagates_without_commit_or_rollback() -> None:
    conn = FakeConnection(fail_on="INSERT INTO instrument_metadata")
    qualifier = FakeQualifier(qualifies=True)
    instrument = _make_instrument("ATOMIC1")

    with pytest.raises(RuntimeError):
        await onboard_instrument(conn, instrument, qualifier=qualifier, metadata=_SOME_METADATA)

    assert conn.commit_calls == 0
    assert conn.rollback_calls == 0
    assert conn.transaction_call_count == 1
    enter_exit_events = [entry for entry in conn.transaction_log if entry[0] == "exit"]
    assert len(enter_exit_events) == 1
    _label, tx, exc_type = enter_exit_events[0]
    assert tx.exited is True
    assert exc_type is RuntimeError


# ---------------------------------------------------------------------------
# Case 9: the caller's transaction boundary is not stolen -- neither commit()
# nor rollback() is ever called on any path, and the bulk-caller shape (an
# outer transaction holding two sequential onboard_instrument() calls, the
# second of which is rejected) leaves the outer transaction open.
# ---------------------------------------------------------------------------


async def test_never_calls_commit_or_rollback_on_any_path() -> None:
    # Happy path
    conn = FakeConnection(known_tags={"single_name_equity"})
    qualifier = FakeQualifier(qualifies=True)
    await onboard_instrument(
        conn,
        _make_instrument("HAPPY1"),
        qualifier=qualifier,
        tags=[("single_name_equity", 1.0, {"reason": "x"})],
        metadata=_SOME_METADATA,
    )
    assert conn.commit_calls == 0
    assert conn.rollback_calls == 0
    assert conn.transaction_call_count == 1

    # Rejected path (qualification failure)
    conn2 = FakeConnection()
    rejecting_qualifier = FakeQualifier(qualifies=False)
    with pytest.raises(OnboardingRejected):
        await onboard_instrument(
            conn2,
            _make_instrument("REJECT1"),
            qualifier=rejecting_qualifier,
            metadata=_SOME_METADATA,
        )
    assert conn2.commit_calls == 0
    assert conn2.rollback_calls == 0

    # Raising path (mid-transaction failure)
    conn3 = FakeConnection(fail_on="INSERT INTO instrument_metadata")
    qualifier3 = FakeQualifier(qualifies=True)
    with pytest.raises(RuntimeError):
        await onboard_instrument(
            conn3,
            _make_instrument("RAISE1"),
            qualifier=qualifier3,
            metadata=_SOME_METADATA,
        )
    assert conn3.commit_calls == 0
    assert conn3.rollback_calls == 0
    assert conn3.transaction_call_count == 1


async def test_outer_transaction_survives_rejected_inner_onboarding() -> None:
    """Plan 08 / Plan 12 bulk-onboarding pattern: a caller holds its own outer
    transaction across hundreds of onboard_instrument() calls. One rejected
    symbol must unwind only its own savepoint scope -- the outer transaction
    stays open and under the caller's control.
    """
    conn = FakeConnection(known_tags=set())  # no tags registered -> any tag rejected
    qualifier = FakeQualifier(qualifies=True)
    good = _make_instrument("GOOD1")
    bad = _make_instrument("BAD1")

    outer_tx = conn.transaction()
    async with outer_tx:
        result = await onboard_instrument(conn, good, qualifier=qualifier, metadata=_SOME_METADATA)
        assert result.instrument_inserted is True
        assert outer_tx.exited is False

        with pytest.raises(OnboardingRejected):
            await onboard_instrument(
                conn,
                bad,
                qualifier=qualifier,
                tags=[("unregistered_tag", 1.0, {"reason": "x"})],
                metadata=_SOME_METADATA,
            )

        # The outer transaction context has NOT exited -- the rejected inner
        # onboarding only unwound its own (savepoint) scope.
        assert outer_tx.exited is False

    assert outer_tx.exited is True
    assert conn.commit_calls == 0
    assert conn.rollback_calls == 0
    # outer + good's inner scope + bad's inner scope = 3 transaction() calls total
    assert conn.transaction_call_count == 3
