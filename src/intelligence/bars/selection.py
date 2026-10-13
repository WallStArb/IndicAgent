"""Canonical bar selection from raw rows by policy, a pure function (phase 191 plan 02).

Design: docs/plans/2026-10-12-unified-raw-bar-table-design.md (Canonical section). For each
(symbol, timeframe, timestamp) the canonical row is the one the highest-ranked vendor holds in
`ohlcv_raw`; within a vendor the kind with the lowest CVR `bar_kind` sort_order wins. The ranking
comes from `bar_source_policy` (the symbol-specific row covering the slot date beats the
timeframe default, then primary_source, then fallback_source).

Selection is a function of the raw rows and the policy only, never of write order: shuffling the
candidates cannot change the result. A missing policy row raises (a slot without a policy fails
loud, as the daily rule does). A slot no ranked vendor holds yields nothing (missing is NaN, no
fill). Rows of vendor `derived` and kind `smart_adjusted` are never selected.

Pure Ring 1: no database access, no services imports.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from src.intelligence.bars.vendor_kind import VENDOR_DERIVED

NEVER_SELECTED_KINDS = frozenset({"smart_adjusted"})


@dataclass(frozen=True)
class PolicyRow:
    """A bar_source_policy row (symbol None is the timeframe default)."""

    timeframe: str
    symbol: str | None
    valid_from: date
    valid_to: date | None
    primary_source: str
    fallback_source: str | None

    def covers(self, slot_date: date) -> bool:
        return self.valid_from <= slot_date and (self.valid_to is None or slot_date < self.valid_to)


@dataclass(frozen=True)
class Candidate:
    """One vendor-served row of ohlcv_raw."""

    timestamp: datetime
    symbol: str
    timeframe: str
    vendor: str
    kind: str
    open: float
    high: float
    low: float
    close: float
    volume: int | None


def rank_vendors(
    policy_rows: Iterable[PolicyRow], symbol: str, timeframe: str, slot_date: date
) -> list[str]:
    """Vendors in selection order for a slot; LookupError when no policy row covers it."""
    covering = [p for p in policy_rows if p.timeframe == timeframe and p.covers(slot_date)]
    for scope in (symbol, None):
        scoped = [p for p in covering if p.symbol == scope]
        if len(scoped) > 1:
            raise ValueError(
                f"{len(scoped)} bar_source_policy rows cover {symbol} {timeframe} {slot_date}"
            )
        if scoped:
            row = scoped[0]
            return [row.primary_source] + ([row.fallback_source] if row.fallback_source else [])
    raise LookupError(f"no bar_source_policy row covers {symbol} {timeframe} {slot_date}")


def select_slot(
    candidates: Iterable[Candidate], ranking: Sequence[str], kind_order: Mapping[str, int]
) -> Candidate | None:
    """The winning candidate of one slot, or None when no ranked vendor holds it."""
    eligible = [
        c
        for c in candidates
        if c.vendor != VENDOR_DERIVED and c.kind not in NEVER_SELECTED_KINDS and c.vendor in ranking
    ]
    for vendor in ranking:
        held = [c for c in eligible if c.vendor == vendor]
        if held:
            unknown = sorted({c.kind for c in held} - kind_order.keys())
            if unknown:
                raise KeyError(f"kind(s) {unknown} have no CVR bar_kind sort_order")
            return min(held, key=lambda c: (kind_order[c.kind], c.kind))
    return None


def select_all(
    candidates: Iterable[Candidate],
    policy_rows: Sequence[PolicyRow],
    kind_order: Mapping[str, int],
) -> list[Candidate]:
    """The winner of every slot present in `candidates`, sorted by (symbol, timeframe, timestamp)."""
    slots: dict[tuple[str, str, datetime], list[Candidate]] = defaultdict(list)
    for c in candidates:
        slots[(c.symbol, c.timeframe, c.timestamp)].append(c)
    winners: list[Candidate] = []
    for (symbol, timeframe, timestamp), held in sorted(slots.items()):
        ranking = rank_vendors(policy_rows, symbol, timeframe, timestamp.astimezone(UTC).date())
        winner = select_slot(held, ranking, kind_order)
        if winner is not None:
            winners.append(winner)
    return winners
