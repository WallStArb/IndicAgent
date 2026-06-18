"""PG ENUM enforcement tests — Phase 134 Plan 03.

Three exhaustiveness tests (unit, no DB):
  1. SignalOutcome: 9 members including condition_expired
  2. EntryType: 5 members
  3. SignalStatus: 4 members

Three round-trip insert tests (DB-backed, skip if DB unavailable):
  4. trade_executions.outcome — every SignalOutcome value accepted; invalid rejected (22P02)
  5. trade_frames.entry_type — every EntryType value accepted; invalid rejected (22P02)
  6. signal_events.status — every SignalStatus value accepted; invalid rejected (22P02)

Round-trip tests use indicagent_test (not the live corpus). A session-scoped fixture
bootstraps the test DB with the minimal schema: ENUM types + the 3 tables. Connecting
to the production indicagent DB from a test suite is a data integrity risk — a crash
before rollback or any asyncpg transaction failure would write to training data.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest

from src.intelligence.trading.signal_outcome import EntryType, SignalOutcome
from src.persistence.repository.signal_events_repository import SignalStatus

# ---------------------------------------------------------------------------
# Test DB bootstrap (session-scoped)
# ---------------------------------------------------------------------------

_TEST_DB_URL = "postgresql://postgres:postgres@localhost:5432/indicagent_test"
_ADMIN_DB_URL = "postgresql://postgres:postgres@localhost:5432/postgres"

_BOOTSTRAP_SQL = """
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'signal_outcome_type') THEN
        CREATE TYPE signal_outcome_type AS ENUM (
            'never_activated', 'stopped_at_entry', 'stopped_in_trade',
            'target_1', 'target_1_2', 'target_full',
            'ttl_expired_ahead', 'ttl_expired_behind', 'condition_expired'
        );
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'entry_type_type') THEN
        CREATE TYPE entry_type_type AS ENUM (
            'at_close', 'at_pullback', 'at_limit', 'at_reclaim', 'zone_proximal'
        );
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'signal_status_type') THEN
        CREATE TYPE signal_status_type AS ENUM (
            'pending', 'active', 'regime_suppressed', 'expired'
        );
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS signal_events (
    signal_id       uuid                NOT NULL,
    ts              timestamptz         NOT NULL,
    symbol          text                NOT NULL,
    tf              text                NOT NULL,
    setup_plugin    text                NOT NULL,
    direction       text                NOT NULL,
    raw_confidence  double precision    NOT NULL,
    status          signal_status_type  NOT NULL DEFAULT 'pending',
    PRIMARY KEY (signal_id, ts)
);

CREATE TABLE IF NOT EXISTS trade_frames (
    frame_id    uuid            NOT NULL PRIMARY KEY,
    signal_id   uuid            NOT NULL,
    signal_ts   timestamptz     NOT NULL,
    entry_type  entry_type_type NOT NULL,
    direction   text            NOT NULL,
    was_selected boolean        NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS trade_executions (
    execution_id    uuid                NOT NULL PRIMARY KEY,
    frame_id        uuid                NOT NULL REFERENCES trade_frames(frame_id),
    outcome         signal_outcome_type,
    exit_reason     text,
    CONSTRAINT chk_te_exit_reason CHECK (
        exit_reason IS NULL OR exit_reason IN (
            'stop_loss', 'chandelier_stop', 'condition_expired',
            'ttl_expired', 'ttl_expired_ahead', 'ttl_expired_behind',
            'target_hit'
        )
    )
);
"""


def _bootstrap_test_db() -> bool:
    """Create indicagent_test and apply minimal schema. Returns True on success."""
    try:
        import asyncpg

        async def _run_bootstrap():
            # Create DB if needed (must connect to postgres, not indicagent_test)
            conn = await asyncpg.connect(_ADMIN_DB_URL)
            try:
                exists = await conn.fetchval(
                    "SELECT 1 FROM pg_database WHERE datname = 'indicagent_test'"
                )
                if not exists:
                    await conn.execute("CREATE DATABASE indicagent_test")
            finally:
                await conn.close()

            # Apply minimal schema
            conn = await asyncpg.connect(_TEST_DB_URL)
            try:
                await conn.execute(_BOOTSTRAP_SQL)
            finally:
                await conn.close()

        asyncio.run(_run_bootstrap())
        return True
    except Exception:
        return False


@pytest.fixture(scope="session", autouse=True)
def _ensure_test_db():
    """Session-scoped fixture: bootstrap indicagent_test before round-trip tests run."""
    _bootstrap_test_db()


# ---------------------------------------------------------------------------
# DB connectivity helper (shared by round-trip tests)
# ---------------------------------------------------------------------------


def _get_db_url() -> str | None:
    """Return indicagent_test URL for round-trip tests.

    Always uses the test DB — never the production corpus.
    """
    return _TEST_DB_URL


def _run(coro):
    """Run an async coroutine synchronously — compatible with Python 3.14."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Test 1: SignalOutcome exhaustiveness
# ---------------------------------------------------------------------------


class TestSignalOutcomeEnumExhaustive:
    """SignalOutcome must have exactly 9 members including condition_expired.

    If a new outcome is added without a companion PG ENUM migration, this test
    fails loud — preventing a silent write-time rejection in production.
    """

    _EXPECTED_VALUES = frozenset(
        {
            "never_activated",
            "stopped_at_entry",
            "stopped_in_trade",
            "target_1",
            "target_1_2",
            "target_full",
            "ttl_expired_ahead",
            "ttl_expired_behind",
            "condition_expired",  # 9th member — added Phase 134 Plan 01
        }
    )

    def test_signal_outcome_enum_exhaustive(self):
        """SignalOutcome has exactly 9 members, all in the expected set."""
        assert len(SignalOutcome) == 9, (
            f"Expected 9 SignalOutcome members, got {len(SignalOutcome)}. "
            "A new member requires a companion PG ENUM migration — "
            "add a new value to signal_outcome_type in the DB."
        )
        actual = {m.value for m in SignalOutcome}
        assert actual == self._EXPECTED_VALUES, (
            f"SignalOutcome values mismatch.\n"
            f"  Expected: {sorted(self._EXPECTED_VALUES)}\n"
            f"  Actual:   {sorted(actual)}"
        )

    def test_condition_expired_is_present(self):
        """condition_expired (9th member) must exist in SignalOutcome."""
        assert SignalOutcome.CONDITION_EXPIRED.value == "condition_expired"

    def test_signal_outcome_str_subclass(self):
        """SignalOutcome extends str — members compare equal to their value strings."""
        for member in SignalOutcome:
            assert member == member.value, (
                f"SignalOutcome.{member.name} == {member.value!r} should hold "
                "due to str subclass — asyncpg compat guarantee."
            )


# ---------------------------------------------------------------------------
# Test 2: EntryType exhaustiveness
# ---------------------------------------------------------------------------


class TestEntryTypeEnumExhaustive:
    """EntryType must have exactly 5 members matching trade_frames.entry_type valid values."""

    _EXPECTED_VALUES = frozenset(
        {
            "at_close",
            "at_pullback",
            "at_limit",
            "at_reclaim",
            "zone_proximal",
        }
    )

    def test_entry_type_enum_exhaustive(self):
        """EntryType has exactly 5 members, all in the expected set."""
        assert len(EntryType) == 5, (
            f"Expected 5 EntryType members, got {len(EntryType)}. "
            "A new member requires a companion PG ENUM migration."
        )
        actual = {m.value for m in EntryType}
        assert actual == self._EXPECTED_VALUES, (
            f"EntryType values mismatch.\n"
            f"  Expected: {sorted(self._EXPECTED_VALUES)}\n"
            f"  Actual:   {sorted(actual)}"
        )

    def test_entry_type_str_subclass(self):
        """EntryType extends str — members compare equal to their value strings."""
        for member in EntryType:
            assert member == member.value


# ---------------------------------------------------------------------------
# Test 3: SignalStatus exhaustiveness
# ---------------------------------------------------------------------------


class TestSignalStatusEnumExhaustive:
    """SignalStatus must have exactly 4 members matching signal_events.status valid values."""

    _EXPECTED_VALUES = frozenset(
        {
            "pending",
            "active",
            "regime_suppressed",
            "expired",
        }
    )

    def test_signal_status_enum_exhaustive(self):
        """SignalStatus has exactly 4 members, all in the expected set."""
        assert len(SignalStatus) == 4, (
            f"Expected 4 SignalStatus members, got {len(SignalStatus)}. "
            "A new member requires a companion PG ENUM migration."
        )
        actual = {m.value for m in SignalStatus}
        assert actual == self._EXPECTED_VALUES, (
            f"SignalStatus values mismatch.\n"
            f"  Expected: {sorted(self._EXPECTED_VALUES)}\n"
            f"  Actual:   {sorted(actual)}"
        )

    def test_signal_status_str_subclass(self):
        """SignalStatus extends str — members compare equal to their value strings."""
        for member in SignalStatus:
            assert member == member.value


# ---------------------------------------------------------------------------
# Round-trip tests (DB-backed) — Tests 4, 5, 6
#
# Each test:
#   - For every valid enum value: INSERT in a transaction, assert no error, ROLLBACK
#   - For one invalid value: INSERT in a transaction, assert asyncpg raises 22P02
#
# All insertions are rolled back — no persistent data is written.
# Each test creates its own asyncpg connection (compatible with asyncio.run()).
# ---------------------------------------------------------------------------


class _Rollback(Exception):
    """Sentinel exception used to force asyncpg transaction rollback in round-trip tests."""


def _db_url_or_skip() -> str:
    """Return DB URL or skip the test if unavailable."""
    url = _get_db_url()
    if url is None:
        pytest.skip("DB URL unavailable (settings not configured)")
    return url  # type: ignore[return-value]


class TestRoundtripOutcomeEnum:
    """Round-trip inserts for trade_executions.outcome (signal_outcome_type PG ENUM).

    For each of the 9 SignalOutcome values: INSERT a minimal trade_executions row,
    assert success, ROLLBACK. Also asserts an invalid value raises PG error 22P02.
    """

    def test_roundtrip_outcome_enum(self):
        """All 9 SignalOutcome values are accepted; invalid value raises 22P02."""
        import asyncpg

        url = _db_url_or_skip()

        async def _run_all():
            try:
                conn = await asyncpg.connect(url)
            except Exception as error:
                pytest.skip(f"Cannot connect to DB: {error}")

            try:
                # Valid values — every SignalOutcome member
                for member in SignalOutcome:
                    await _insert_outcome(conn, member.value, expect_success=True)

                # Explicit regression guards for the two critical values
                await _insert_outcome(conn, "condition_expired", expect_success=True)
                await _insert_outcome(conn, "stopped_in_trade", expect_success=True)

                # Invalid value — must be rejected with 22P02
                await _insert_outcome(conn, "bogus_outcome", expect_success=False)
            finally:
                await conn.close()

        _run(_run_all())

    def test_roundtrip_outcome_enum_requires_9_members(self):
        """Sanity: round-trip loop covers all 9 SignalOutcome members."""
        assert len(SignalOutcome) == 9


class TestRoundtripEntryTypeEnum:
    """Round-trip inserts for trade_frames.entry_type (entry_type_type PG ENUM).

    For each of the 5 EntryType values: INSERT a minimal trade_frames row,
    assert success, ROLLBACK. Also asserts an invalid value raises PG error 22P02.
    """

    def test_roundtrip_entry_type_enum(self):
        """All 5 EntryType values are accepted; invalid value raises 22P02."""
        import asyncpg

        url = _db_url_or_skip()

        async def _run_all():
            try:
                conn = await asyncpg.connect(url)
            except Exception as error:
                pytest.skip(f"Cannot connect to DB: {error}")

            try:
                for member in EntryType:
                    await _insert_entry_type(conn, member.value, expect_success=True)

                await _insert_entry_type(conn, "at_market", expect_success=False)
            finally:
                await conn.close()

        _run(_run_all())


class TestRoundtripStatusEnum:
    """Round-trip inserts for signal_events.status (signal_status_type PG ENUM).

    For each of the 4 SignalStatus values: INSERT a minimal signal_events row,
    assert success, ROLLBACK. Also asserts an invalid value raises PG error 22P02.
    """

    def test_roundtrip_status_enum(self):
        """All 4 SignalStatus values accepted; invalid value raises 22P02."""
        import asyncpg

        url = _db_url_or_skip()

        async def _run_all():
            try:
                conn = await asyncpg.connect(url)
            except Exception as error:
                pytest.skip(f"Cannot connect to DB: {error}")

            try:
                for member in SignalStatus:
                    await _insert_status(conn, member.value, expect_success=True)

                await _insert_status(conn, "cancelled", expect_success=False)
            finally:
                await conn.close()

        _run(_run_all())


# ---------------------------------------------------------------------------
# Shared DB insert helpers
# ---------------------------------------------------------------------------


async def _insert_outcome(conn, outcome_value: str, *, expect_success: bool) -> None:
    """INSERT signal_events + trade_frames + trade_executions, then ROLLBACK.

    If expect_success=True: asserts the INSERT succeeds.
    If expect_success=False: asserts the INSERT raises PG 22P02.
    """
    signal_id = uuid.uuid4()
    frame_id = uuid.uuid4()
    execution_id = uuid.uuid4()
    ts = datetime.now(UTC)

    if expect_success:
        try:
            async with conn.transaction():
                await _insert_parent_signal(conn, signal_id, ts)
                await _insert_parent_frame(conn, frame_id, signal_id, ts, "at_close")
                await conn.execute(
                    "INSERT INTO trade_executions (execution_id, frame_id, outcome) VALUES ($1, $2, $3)",
                    execution_id,
                    frame_id,
                    outcome_value,
                )
                raise _Rollback()
        except _Rollback:
            pass  # expected — transaction rolled back cleanly
    else:
        raised = False
        try:
            async with conn.transaction():
                await _insert_parent_signal(conn, signal_id, ts)
                await _insert_parent_frame(conn, frame_id, signal_id, ts, "at_close")
                await conn.execute(
                    "INSERT INTO trade_executions (execution_id, frame_id, outcome) VALUES ($1, $2, $3)",
                    execution_id,
                    frame_id,
                    outcome_value,
                )
        except Exception as error:
            err_str = str(error)
            raised = True
            assert (
                "22P02" in err_str or "invalid input value for enum" in err_str
            ), f"Expected PG 22P02 for invalid outcome {outcome_value!r}, got: {err_str}"
        assert raised, f"Expected PG 22P02 for {outcome_value!r} but no exception was raised"


async def _insert_entry_type(conn, entry_type_value: str, *, expect_success: bool) -> None:
    """INSERT signal_events + trade_frames with given entry_type, then ROLLBACK."""
    signal_id = uuid.uuid4()
    frame_id = uuid.uuid4()
    ts = datetime.now(UTC)

    if expect_success:
        try:
            async with conn.transaction():
                await _insert_parent_signal(conn, signal_id, ts)
                await _insert_parent_frame(conn, frame_id, signal_id, ts, entry_type_value)
                raise _Rollback()
        except _Rollback:
            pass
    else:
        raised = False
        try:
            async with conn.transaction():
                await _insert_parent_signal(conn, signal_id, ts)
                await _insert_parent_frame(conn, frame_id, signal_id, ts, entry_type_value)
        except Exception as error:
            err_str = str(error)
            raised = True
            assert (
                "22P02" in err_str or "invalid input value for enum" in err_str
            ), f"Expected PG 22P02 for invalid entry_type {entry_type_value!r}, got: {err_str}"
        assert raised, f"Expected PG 22P02 for {entry_type_value!r} but no exception was raised"


async def _insert_status(conn, status_value: str, *, expect_success: bool) -> None:
    """INSERT signal_events with given status, then ROLLBACK."""
    signal_id = uuid.uuid4()
    ts = datetime.now(UTC)

    if expect_success:
        try:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO signal_events
                        (signal_id, ts, symbol, tf, setup_plugin, direction, raw_confidence, status)
                    VALUES ($1, $2, 'TEST', '1m', 'test_plugin', 'long', 0.5, $3)
                    """,
                    signal_id,
                    ts,
                    status_value,
                )
                raise _Rollback()
        except _Rollback:
            pass
    else:
        raised = False
        try:
            async with conn.transaction():
                await conn.execute(
                    """
                    INSERT INTO signal_events
                        (signal_id, ts, symbol, tf, setup_plugin, direction, raw_confidence, status)
                    VALUES ($1, $2, 'TEST', '1m', 'test_plugin', 'long', 0.5, $3)
                    """,
                    signal_id,
                    ts,
                    status_value,
                )
        except Exception as error:
            err_str = str(error)
            raised = True
            assert (
                "22P02" in err_str or "invalid input value for enum" in err_str
            ), f"Expected PG 22P02 for invalid status {status_value!r}, got: {err_str}"
        assert raised, f"Expected PG 22P02 for {status_value!r} but no exception was raised"


async def _insert_parent_signal(conn, signal_id: uuid.UUID, ts: datetime) -> None:
    """Insert a minimal signal_events row (parent for FK constraints)."""
    await conn.execute(
        """
        INSERT INTO signal_events
            (signal_id, ts, symbol, tf, setup_plugin, direction, raw_confidence, status)
        VALUES ($1, $2, 'TEST', '1m', 'test_plugin', 'long', 0.5, 'pending')
        """,
        signal_id,
        ts,
    )


async def _insert_parent_frame(
    conn, frame_id: uuid.UUID, signal_id: uuid.UUID, ts: datetime, entry_type: str
) -> None:
    """Insert a minimal trade_frames row (parent for FK constraints)."""
    await conn.execute(
        """
        INSERT INTO trade_frames
            (frame_id, signal_id, signal_ts, entry_type, direction, was_selected)
        VALUES ($1, $2, $3, $4, 'long', false)
        """,
        frame_id,
        signal_id,
        ts,
        entry_type,
    )
