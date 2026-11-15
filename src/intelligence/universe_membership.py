"""Stage 2 universe membership rule: pure functions over one security's daily bars.

Preregistration `docs/plans/2026-11-13-stage2-universe-preregistration.md` (adopted 2026-11-13).
Membership is decided at each NYSE month-end t from data known at t only and is effective for the
following month. The values below are research-design constants of the preregistration and of the
spec hash of every run that reads the universe, deliberately NOT APR keys: a tunable universe
invites tuning after seeing results, so a change is a dated amendment there and a new `RULE_ID`
here, never a `config_state` write.

Rule at t, for one security (one identity, so a reused ticker is two securities upstream):

- type: Massive reference type at t is common stock, ADR common or ETF (``ELIGIBLE_TYPES``);
- bar on t: the security has a bar on t itself (a delisted or halted name has none, so it leaves
  at the first month-end after its last bar; no later data is read);
- price: close on t at or above ``min_close``;
- history: at least ``min_history_sessions`` of the security's own bars through t;
- liquidity: the median of close x volume over the last ``window_sessions`` own bars through t is
  at or above ``entry_floor`` to enter, and a current member stays while it is at or above
  ``exit_floor`` (hysteresis: the exit floor is below the entry floor, so a name between the two
  keeps its prior state and the cross-section stays stable).

The type, price, bar-on-t and history conditions are hard for members and non-members alike;
hysteresis relaxes only the liquidity floor. A non-finite value anywhere in the window means the
median is not computable and the security is not a member (no_fill: nothing is filled or
dropped). Bars after t are never read, so a decision at t cannot move when later bars arrive.

Dollar volume is close x volume per bar as stored. The product is invariant under a split
adjustment applied to both columns, so no adjustment is applied here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

import numpy as np

# Identifies the preregistered rule values. A dated amendment that changes any value below bumps
# this id; the build ledger refuses to extend a build made under another id.
RULE_ID = "stage2-2026-11-13"

# First day of the Massive archive; the first month-end considered.
ARCHIVE_START = date(2003, 9, 10)

# Massive reference types: CS common stock, ADRC ADR of a common stock, ETF.
ELIGIBLE_TYPES: frozenset[str] = frozenset({"CS", "ADRC", "ETF"})


@dataclass(frozen=True)
class MembershipRule:
    """The preregistered values (dollars, sessions)."""

    entry_floor: float = 1_000_000.0
    exit_floor: float = 500_000.0
    window_sessions: int = 60
    min_history_sessions: int = 60
    min_close: float = 1.0
    eligible_types: frozenset[str] = ELIGIBLE_TYPES

    def __post_init__(self) -> None:
        if not 0 < self.exit_floor <= self.entry_floor:
            raise ValueError("MembershipRule: need 0 < exit_floor <= entry_floor")
        if self.window_sessions < 1 or self.min_history_sessions < self.window_sessions:
            raise ValueError("MembershipRule: need 1 <= window_sessions <= min_history_sessions")


RULE = MembershipRule()


@dataclass(frozen=True)
class SecurityHistory:
    """One security's daily bars: ascending unique session dates and aligned close and volume."""

    symbol: str
    days: np.ndarray  # datetime64[D]
    close: np.ndarray  # float64
    volume: np.ndarray  # float64

    def __post_init__(self) -> None:
        if not (len(self.days) == len(self.close) == len(self.volume)):
            raise ValueError(f"SecurityHistory {self.symbol}: days, close, volume differ in length")
        if len(self.days) > 1 and not np.all(self.days[1:] > self.days[:-1]):
            raise ValueError(f"SecurityHistory {self.symbol}: days must be strictly ascending")


@dataclass(frozen=True)
class MembershipRow:
    """One member at one month-end. `entered` is False for a name kept by hysteresis."""

    as_of: date
    symbol: str
    security_type: str
    median_dollar_volume: float
    close: float
    sessions: int
    entered: bool


def month_end_sessions(sessions: Iterable[date]) -> list[date]:
    """The last session of each calendar month among `sessions` (ascending, complete months).

    The caller passes sessions through the end of the last month it wants judged: a partial
    trailing month would otherwise report its latest session as a month-end.
    """
    last: dict[tuple[int, int], date] = {}
    for day in sorted(sessions):
        last[(day.year, day.month)] = day
    return sorted(last.values())


def decide(
    history: SecurityHistory,
    as_of: date,
    security_type: str | None,
    was_member: bool,
    rule: MembershipRule = RULE,
) -> MembershipRow | None:
    """The membership row for `history.symbol` at `as_of`, or None when it is not a member.

    `security_type` is the Massive type at `as_of` (None when unknown, which is ineligible).
    """
    if security_type is None or security_type not in rule.eligible_types:
        return None
    n = int(np.searchsorted(history.days, np.datetime64(as_of, "D"), side="right"))
    if n < rule.min_history_sessions or history.days[n - 1] != np.datetime64(as_of, "D"):
        return None
    close = float(history.close[n - 1])
    if not np.isfinite(close) or close < rule.min_close:
        return None
    start = n - rule.window_sessions
    dollar = history.close[start:n] * history.volume[start:n]
    if not np.all(np.isfinite(dollar)):
        return None
    median = float(np.median(dollar))
    if median < (rule.exit_floor if was_member else rule.entry_floor):
        return None
    return MembershipRow(
        as_of=as_of,
        symbol=history.symbol,
        security_type=security_type,
        median_dollar_volume=median,
        close=close,
        sessions=n,
        entered=not was_member,
    )


def memberships_for_security(
    history: SecurityHistory,
    month_ends: Iterable[date],
    types: Mapping[date, str | None],
    *,
    was_member: bool = False,
    rule: MembershipRule = RULE,
) -> list[MembershipRow]:
    """Walk `month_ends` (ascending) for one security, carrying membership forward for the
    hysteresis. `was_member` seeds the state before the first month-end (a resumed build passes
    the previous month's membership). `types` maps each month-end to the type known on it; a
    missing key is an unknown type."""
    rows: list[MembershipRow] = []
    for as_of in month_ends:
        row = decide(history, as_of, types.get(as_of), was_member, rule)
        was_member = row is not None
        if row is not None:
            rows.append(row)
    return rows
