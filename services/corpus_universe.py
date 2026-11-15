"""The corpus rerun's compute universe: every security that is a member at any month-end.

Stage 2 (todo 609): the 1d corpus is computed over the point-in-time universe of
`universe_membership`, not over the `compute_1d` flag of `instruments`. Features compute on every
name that was ever a member, so an entering name arrives with warmed features; membership at
each month-end then gates the IC panel (preregistration 2026-11-13).

The read fails loudly when the ledger or the table is empty. There is deliberately no fallback to
`get_active_contracts(dimension="compute_1d")`: a silent switch of universe would change every
corpus number without a trace.
"""

from __future__ import annotations

from typing import Any

from src.config.classification_service import current_level_name_sql
from src.config.settings import Instrument, instrument_from_instruments_row


class UniverseMembershipEmptyError(RuntimeError):
    """`universe_membership` holds no built month-end (the writer has not run)."""


_LEDGER_SQL = "SELECT count(*), count(DISTINCT rule_id), max(as_of) FROM universe_membership_build"
_INSTRUMENTS_SQL = (
    "SELECT symbol, base, contract_details, "
    f"{current_level_name_sql('instruments')} "
    "FROM instruments "
    "WHERE symbol IN (SELECT symbol FROM universe_membership) "
    "ORDER BY symbol"
)


def corpus_universe(conn: Any) -> list[Instrument]:
    """The `Instrument` of every symbol ever in `universe_membership`, ordered by symbol.

    Raises `UniverseMembershipEmptyError` when no month-end is built and RuntimeError when the
    ledger mixes rule ids. A member whose `instruments` row cannot become an Instrument raises
    (a data defect, never guessed around). Dead names are included: `is_active` is not read.
    """
    with conn.cursor() as cur:
        cur.execute(_LEDGER_SQL)
        months, rules, last = cur.fetchone()
        if not months:
            raise UniverseMembershipEmptyError(
                "universe_membership has no built month-end; run "
                "services.universe_membership_writer before the corpus rerun"
            )
        if rules != 1:
            raise RuntimeError(f"universe_membership_build mixes {rules} rule ids (last {last})")
        cur.execute(_INSTRUMENTS_SQL)
        rows = cur.fetchall()
    if not rows:
        raise UniverseMembershipEmptyError(
            f"universe_membership_build has {months} months through {last} but no member rows"
        )
    return [instrument_from_instruments_row(*row) for row in rows]
