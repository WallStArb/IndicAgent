"""Pure arithmetic of the 1d integrity verdict report (phase 185 plan 33; data layer integrity
design section 6). D7 (services/bar_reconciliation_audit.py) reads the inputs and writes the
verdicts; nothing here touches a database or the APR.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date

from src.intelligence.bars.daily_rule import PolicyRow, resolve_policy
from src.intelligence.bars.sources import SOURCE_IBKR_FALLBACK

_PRIMARY_LABEL = {"tradier": "tradier", "ibkr": "ibkr_named"}


@dataclass(frozen=True)
class Verdict:
    """One integrity verdict row: a (symbol, timeframe, check) judged against its threshold."""

    symbol: str
    timeframe: str
    check: str
    passed: bool
    metric_value: float
    threshold_value: float


def session_coverage(
    bar_dates: Collection[date], empty_dates: Collection[date], sessions: Collection[date]
) -> float:
    """Share of sessions that hold a bar or an answered-empty record; 1.0 when there are none."""
    if not sessions:
        return 1.0
    answered = set(bar_dates) | set(empty_dates)
    return len(answered.intersection(sessions)) / len(sessions)


def policy_conformance(
    rows: Sequence[tuple[date, str]],
    policy_rows: Sequence[PolicyRow],
    tradier_dates: Collection[date],
    *,
    symbol: str,
) -> list[date]:
    """Dates of (date, source) rows whose source contradicts the policy row open on that date.

    The source must be the policy's primary label; ibkr_fallback is accepted only under a policy
    that names IBKR as fallback, on a date with no Tradier observation.
    """
    bad: list[date] = []
    for bar_date, source in rows:
        policy = resolve_policy(policy_rows, symbol, bar_date)
        if source == _PRIMARY_LABEL.get(policy.primary_source):
            continue
        if (
            source == SOURCE_IBKR_FALLBACK
            and policy.fallback_source == "ibkr"
            and bar_date not in tradier_dates
        ):
            continue
        bad.append(bar_date)
    return sorted(bad)
