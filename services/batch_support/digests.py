"""Kernel code identity and per-month bar content digests."""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Iterable, Sequence
from datetime import UTC, datetime
from typing import Any

from src.core.code_identity import FIRST_PARTY_PACKAGES, code_key, import_closure
from src.core.service_utils import format_iso_ts

# ---------------------------------------------------------------------------
# Provenance identity helpers (phase 186 plan 14, D-23): the per-kernel code key and the
# per-symbol bar content digest that, with the APR snapshot, make a unit's identity.
# ---------------------------------------------------------------------------


def kernel_code_key(
    modules: Iterable[str],
    *,
    own: Iterable[str] = (),
    packages: Collection[str] = FIRST_PARTY_PACKAGES,
) -> str:
    """Code identity of one job: sha256 over the AST-normalized source of the entry modules, every
    first-party module they import (transitively, found with `ast`, imports inside functions
    included) and the `own` modules, as 64 lowercase hex (D-23; see `src.core.code_identity`).

    The caller names the entry modules of the computation; the import closure is derived, so an
    import added to a computation module moves the key without a hand-kept list to update. Not
    ic_engine's all-imports key (`code_content_key`, which hashes everything loaded into the
    process): a module outside the closure never moves it. `own` modules are hashed as files
    without following their imports (a writer's orchestration module). Names are de-duplicated
    and sorted, so order does not matter. An empty entry list raises ValueError and a name that
    cannot be resolved raises ModuleNotFoundError, never a silent skip.
    """
    return code_key(kernel_code_modules(modules, own=own, packages=packages))


def kernel_code_modules(
    modules: Iterable[str],
    *,
    own: Iterable[str] = (),
    packages: Collection[str] = FIRST_PARTY_PACKAGES,
) -> tuple[str, ...]:
    """The sorted module names `kernel_code_key` hashes for these entries."""
    entries = sorted(set(modules))
    if not entries:
        raise ValueError("kernel_code_key: at least one module name is required")
    return import_closure(entries, own, packages)


_BAR_DIGEST_SQL = (
    "SELECT symbol, range_start, digest FROM bar_content_digest_current "
    "WHERE timeframe = %s AND symbol = ANY(%s) AND range_start >= %s AND range_start < %s"
)
_BAR_DIGEST_EMPTY_MONTH = "empty"
BAR_DIGEST_ABSENT_SYMBOL = "absent"


def _month_starts(start: datetime, end_exclusive: datetime) -> list[datetime]:
    """UTC calendar month starts covering [start, end_exclusive)."""
    months = []
    cursor = start.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cursor < end_exclusive:
        months.append(cursor)
        cursor = (
            cursor.replace(year=cursor.year + 1, month=1)
            if cursor.month == 12
            else cursor.replace(month=cursor.month + 1)
        )
    return months


def bar_content_digests(
    conn: Any, tf: str, symbols: Sequence[str], start: datetime, end_exclusive: datetime
) -> dict[str, str]:
    """One digest per symbol for bars of `tf` in [start, end_exclusive), composed from phase
    185's month digests (`bar_content_digest_current`, the one definition of the bar content
    digest; nothing is re-hashed here and no second row encoding exists).

    Per symbol: sha256 over the month-ordered (month, digest) pairs, where a month in range with
    no digest row contributes the literal "empty", so a month gaining rows (a recovery, a
    scrub revision) flips the result; absence is explicit input, never a skipped aggregate.
    A symbol with no digest row at all maps to "absent": the caller must treat that as
    revision detection being blind for that symbol (digests only exist once 185 has written
    them), not as a stable value.

    Granularity is the calendar month: the month containing `end_exclusive` is digested whole,
    so a revision of a bar in that month after `end_exclusive` also moves the result
    (conservative over-invalidation); months wholly after it never do. The caller owns the read
    connection; this function does not commit.
    """
    for name, value in (("start", start), ("end_exclusive", end_exclusive)):
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError(f"bar_content_digests: {name} must be a tz-aware datetime")
    if start >= end_exclusive:
        raise ValueError("bar_content_digests: start must be before end_exclusive")
    months = _month_starts(start, end_exclusive)
    with conn.cursor() as cur:
        cur.execute(_BAR_DIGEST_SQL, (tf, list(symbols), months[0], end_exclusive))
        rows = cur.fetchall()
    by_symbol: dict[str, dict[datetime, str]] = {}
    for symbol, range_start, digest in rows:
        by_symbol.setdefault(symbol, {})[range_start.astimezone(UTC)] = digest
    out: dict[str, str] = {}
    for symbol in symbols:
        present = by_symbol.get(symbol)
        if not present:
            out[symbol] = BAR_DIGEST_ABSENT_SYMBOL
            continue
        lines = [
            f"{format_iso_ts(month)}:{present.get(month, _BAR_DIGEST_EMPTY_MONTH)}"
            for month in months
        ]
        out[symbol] = hashlib.sha256("\n".join(lines).encode()).hexdigest()
    return out
