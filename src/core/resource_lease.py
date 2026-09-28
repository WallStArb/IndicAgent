"""Session-level advisory-lock resource lease (Ring 0, phase 185 plan 09, D-29).

One process at a time may hold a named resource: the lease is a PostgreSQL
session-level advisory lock (``pg_advisory_lock``) taken on a dedicated
connection. Properties this module is responsible for, and nothing else:

- No stale lease: the server releases a session lock when the holder's session
  dies, so a crashed holder never blocks the next one.
- Fair handoff: PostgreSQL grants queued advisory-lock requests in arrival
  order, so a holder that unlocks at a unit boundary and immediately re-requests
  queues behind the waiter it just yielded to.
- Tiered yielding: a BULK holder yields at the next checkpoint whenever any
  waiter exists; a PRIORITY holder yields only to a waiting PRIORITY holder.

Ring 0 portable infrastructure: no domain vocabulary, no imports from
``services/``. The connection is identified in ``pg_stat_activity`` as
``lease:<name>:<tier>:<holder>`` so waiters can be classified by tier without
guessing at pids.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum

import psycopg
import structlog

logger = structlog.get_logger(__name__)


class Tier(StrEnum):
    """Yield class of a lease holder: BULK yields to any waiter, PRIORITY only
    to another PRIORITY waiter."""

    BULK = "bulk"
    PRIORITY = "priority"


class LeaseTimeout(RuntimeError):
    """Raised when the lease cannot be acquired within the requested timeout."""


def _lock_key(name: str) -> int:
    """Stable 64-bit signed key for a lease name: the first 8 bytes of the
    sha256 digest, big-endian, signed. Never Python's ``hash()`` -- it is salted
    per process, so two processes would hash one name to two different keys and
    the lease would silently stop serializing."""
    digest = hashlib.sha256(name.encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


class ResourceLease:
    """Advisory-lock lease on a dedicated connection.

    Usage::

        with ResourceLease(dsn, name, tier=Tier.BULK, holder="job") as lease:
            lease.acquire(None)          # None = wait unbounded
            for unit in units:
                process(unit)
                lease.checkpoint()       # yield here if a waiter exists

    ``acquire`` opens the connection lazily; ``checkpoint`` verifies the lock is
    still held by this session and re-acquires it if the connection was lost
    (a reconnect is a new session that holds nothing).
    """

    def __init__(self, dsn: str, name: str, *, tier: Tier, holder: str) -> None:
        self._dsn = dsn
        self._name = name
        self._tier = Tier(tier)
        self._holder = holder
        self._key = _lock_key(name)
        # pg_locks stores a 64-bit advisory key split across two 32-bit columns:
        # classid = high half, objid = low half (objid itself is only 32 bits, so
        # matching the full key against it raises "OID out of range").
        self._classid = (self._key >> 32) & 0xFFFFFFFF
        self._objid = self._key & 0xFFFFFFFF
        self._conn: psycopg.Connection | None = None
        self._last_timeout_s: float | None = None

    @property
    def key(self) -> int:
        """The 64-bit advisory-lock key for this lease name."""
        return self._key

    @property
    def tier(self) -> Tier:
        return self._tier

    # -- connection handling --------------------------------------------------

    def _application_name(self) -> str:
        return f"lease:{self._name}:{self._tier.value}:{self._holder}"

    def _connect(self) -> psycopg.Connection:
        conn = psycopg.connect(
            self._dsn, autocommit=True, application_name=self._application_name()
        )
        return conn

    def _ensure_conn(self) -> psycopg.Connection:
        """Return a live connection, reconnecting once if the old one died."""
        if self._conn is not None:
            try:
                self._conn.execute("SELECT pg_backend_pid()")
                return self._conn
            except psycopg.Error:
                try:
                    self._conn.close()
                except Exception:  # noqa: BLE001 - already dead; nothing to preserve
                    pass
                self._conn = None
        self._conn = self._connect()
        return self._conn

    def backend_pid(self) -> int:
        """Backend pid of the lease connection (diagnostics and test identity)."""
        conn = self._ensure_conn()
        return int(conn.execute("SELECT pg_backend_pid()").fetchone()[0])

    # -- lock primitives ------------------------------------------------------

    def _lock(self, timeout_s: float | None) -> None:
        """Blocking ``pg_advisory_lock`` bounded by a statement timeout.

        The timeout is implemented as ``statement_timeout`` (lock waits are
        interruptible by it), reset to disabled afterwards so the connection's
        later statements are never silently bounded.
        """
        conn = self._ensure_conn()
        timeout_ms = 0 if timeout_s is None else max(1, int(timeout_s * 1000))
        try:
            conn.execute(f"SET statement_timeout = {timeout_ms}")
            conn.execute("SELECT pg_advisory_lock(%s)", (self._key,))
        except psycopg.errors.QueryCanceled as error:
            raise LeaseTimeout(
                f"lease {self._name!r} not acquired within {timeout_s}s "
                f"(tier={self._tier.value}, holder={self._holder!r})"
            ) from error
        finally:
            try:
                conn.execute("SET statement_timeout = 0")
            except psycopg.Error:
                pass
        self._last_timeout_s = timeout_s
        logger.info(
            "resource_lease.acquired",
            name=self._name,
            tier=self._tier.value,
            holder=self._holder,
        )

    def _unlock(self) -> None:
        conn = self._ensure_conn()
        conn.execute("SELECT pg_advisory_unlock(%s)", (self._key,))

    # -- public API -----------------------------------------------------------

    def acquire(self, timeout_s: float | None) -> None:
        """Take the lease, waiting up to ``timeout_s`` seconds (None: unbounded).

        Raises :class:`LeaseTimeout` when the timeout elapses first.
        """
        self._lock(timeout_s)

    def waiters(self) -> list[str]:
        """Tiers of sessions waiting on this lease key, as strings.

        A waiter created by this module reports its tier (parsed from the
        ``lease:<name>:<tier>:<holder>`` application name); anything else
        reports its raw application name so it is never silently dropped.
        """
        conn = self._ensure_conn()
        rows = conn.execute(
            "SELECT a.application_name FROM pg_locks l "
            "JOIN pg_stat_activity a ON a.pid = l.pid "
            "WHERE l.locktype = 'advisory' AND l.classid = %s AND l.objid = %s "
            "AND NOT l.granted",
            (self._classid, self._objid),
        ).fetchall()
        return [self._tier_of(app or "") for (app,) in rows]

    @staticmethod
    def _tier_of(application_name: str) -> str:
        parts = application_name.split(":")
        if len(parts) == 4 and parts[0] == "lease":
            return parts[2]
        return application_name

    def _held_by_this_session(self) -> bool:
        conn = self._ensure_conn()
        row = conn.execute(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
            "AND classid = %s AND objid = %s AND pid = pg_backend_pid() AND granted",
            (self._classid, self._objid),
        ).fetchone()
        return bool(row[0])

    def checkpoint(self) -> bool:
        """Call at a safe unit boundary. Yields to a waiter when this holder's
        tier must (BULK: any waiter; PRIORITY: a PRIORITY waiter), re-acquiring
        behind it, and returns True. With no waiter to yield to, verifies the
        lease is still held by this session, re-acquiring (with a log line) if
        the connection was lost, and returns False.
        """
        waiting = self.waiters()
        must_yield = (
            any(tier == Tier.PRIORITY.value for tier in waiting)
            if self._tier == Tier.PRIORITY
            else bool(waiting)
        )
        if not must_yield:
            if not self._held_by_this_session():
                logger.warning(
                    "resource_lease.lease_lost_reacquiring",
                    name=self._name,
                    tier=self._tier.value,
                    holder=self._holder,
                )
                self._lock(self._last_timeout_s)
            return False
        self._unlock()
        # Queues behind the waiter: arrival order decides, and the waiter's
        # request arrived while this holder still held the lock.
        self._lock(self._last_timeout_s)
        return True

    def release(self) -> None:
        """Release the lease if the connection still holds it (no-op otherwise)."""
        if self._conn is None:
            return
        try:
            if self._held_by_this_session():
                self._unlock()
                logger.info(
                    "resource_lease.released",
                    name=self._name,
                    tier=self._tier.value,
                    holder=self._holder,
                )
        except psycopg.Error as error:
            logger.warning(
                "resource_lease.release_failed",
                name=self._name,
                holder=self._holder,
                error=str(error),
            )

    def close(self) -> None:
        """Close the lease connection (the server releases any held lock)."""
        if self._conn is not None:
            try:
                self._conn.close()
            except psycopg.Error:
                pass
            self._conn = None

    def __enter__(self) -> ResourceLease:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.release()
        self.close()
