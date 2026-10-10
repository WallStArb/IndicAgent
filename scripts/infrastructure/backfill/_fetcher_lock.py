"""The single IBKR history advisory lock (phase 189 plan 02, CD-07/CD-09).

IBKR serves one history stream per account at useful speed (todo 449 measurement), so
exactly one process may fetch history at a time. This fail-fast singleton replaced the
two-tier history ResourceLease (retired by plan 189-08) for every IBKR history caller: the
fetcher and each manual IBKR history tool (ops_d1_bootstrap, ops_venue_study,
ops_intraday_venue_recovery, the rate-limit probe) take this lock, and a second caller is refused immediately instead of queueing behind the holder.

The lock is a PostgreSQL session-level advisory lock (pg_try_advisory_lock, never the
blocking form) on a dedicated autocommit connection held for the holder's lifetime. The
server releases it when the connection closes or the process dies, so a crashed holder never
blocks the next run (T-189-05). The holder shows in pg_stat_activity as
``lock:<name>:<holder>``.

src/core/resource_lease.py stays as a generic Ring 0 primitive and is not used here; this
IBKR-specific lock lives beside its consumers.
"""

from __future__ import annotations

import hashlib
from types import TracebackType

import psycopg
import structlog

logger = structlog.get_logger(__name__)

# A name distinct from the retired two-tier history lease's, so the two keys never collided
# while both existed.
# FROZEN (phase 190 decision): the advisory key is sha256 of this name and is shared by
# ops_d1_bootstrap, ops_venue_study, ops_intraday_venue_recovery, the rate-limit probe,
# classification sourcing and the onboard manifest; the fetcher module renamed to
# ohlcv_history_fetcher.py without touching this value, because a piecemeal rename would let
# two fetchers hold different keys simultaneously (the one-writer invariant dies silently).
# Renaming requires moving every consumer in one commit.
FETCHER_LOCK_NAME = "ibkr_history_fetcher"

# Exact string: plan 08's ops_head_rerun matches it in subprocess output.
# FROZEN (phase 190 decision): value byte-identical across the code-identifier rename;
# ops_head_rerun.py matches it exactly in subprocess output.
LOCK_HELD_MESSAGE = "ibkr history fetcher lock held by another process; exiting"

# PostgreSQL truncates application_name to NAMEDATALEN - 1 bytes.
_APPLICATION_NAME_MAX = 63


def fetcher_lock_key(name: str = FETCHER_LOCK_NAME) -> int:
    """Stable 64-bit signed key: the first 8 bytes of sha256(name), big-endian, signed (the
    ResourceLease derivation). Never Python's hash(), which is salted per process."""
    return int.from_bytes(hashlib.sha256(name.encode()).digest()[:8], "big", signed=True)


class FetcherLockHeld(RuntimeError):
    """Another process holds the IBKR history fetcher lock."""


class FetcherLock:
    """Fail-fast, process-lifetime singleton lock.

    Usage::

        with FetcherLock(dsn, holder="ibkr-history-fetcher"):
            run()           # FetcherLockHeld raised before this if held elsewhere

    ``name`` exists for tests only; production callers use the default.
    """

    def __init__(self, dsn: str, holder: str, name: str = FETCHER_LOCK_NAME) -> None:
        self._dsn = dsn
        self._holder = holder
        self._name = name
        self._key = fetcher_lock_key(name)
        self._conn: psycopg.Connection | None = None

    @property
    def application_name(self) -> str:
        return f"lock:{self._name}:{self._holder}"[:_APPLICATION_NAME_MAX]

    @property
    def held(self) -> bool:
        return self._conn is not None

    def acquire(self) -> bool:
        """Try once; True when this process now holds the lock. Never waits."""
        if self._conn is not None:
            return True
        conn = psycopg.connect(self._dsn, autocommit=True, application_name=self.application_name)
        try:
            granted = bool(
                conn.execute("SELECT pg_try_advisory_lock(%s)", (self._key,)).fetchone()[0]
            )
        except BaseException:
            conn.close()
            raise
        if not granted:
            conn.close()
            return False
        self._conn = conn
        logger.info("fetcher_lock.acquired", name=self._name, holder=self._holder)
        return True

    def hold_or_refuse(self) -> None:
        """Acquire, or raise FetcherLockHeld(LOCK_HELD_MESSAGE)."""
        if not self.acquire():
            raise FetcherLockHeld(LOCK_HELD_MESSAGE)

    def release(self) -> None:
        """Unlock, keeping nothing open. Closing the connection would release it anyway; the
        explicit unlock makes the release visible in the log."""
        if self._conn is None:
            return
        try:
            self._conn.execute("SELECT pg_advisory_unlock(%s)", (self._key,))
            logger.info("fetcher_lock.released", name=self._name, holder=self._holder)
        except psycopg.Error as error:
            logger.warning("fetcher_lock.release_failed", name=self._name, error=str(error))
        self._close_conn()

    def close(self) -> None:
        """Release and close; safe to call more than once."""
        self.release()

    def _close_conn(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                conn.close()
            except psycopg.Error:
                pass

    def __enter__(self) -> FetcherLock:
        self.hold_or_refuse()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
