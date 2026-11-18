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
- price: the AS-TRADED close on t at or above ``min_close``. Canonical closes are split-adjusted
  by every split on record, including splits after t, so the stored close is un-adjusted by the
  product of the factors of splits whose effective_date is on or after t (the inverse of
  `split_rescale`: a bar dated on or before a split's effective_date was divided by its factor).
  A $0.40 name that later reverse-splits 1:20 stored $8 and still fails; a $5 name that later
  splits 10:1 stored $0.50 and still passes. The test and the stored close use what traded on t;
- history: at least ``min_history_sessions`` of the security's own bars through t (the 60 bars
  include t itself; "60 sessions before t" read strictly would need 61, a one-session difference
  recorded in docs/plans/2026-11-15-universe-membership-design.md);
- liquidity: the median of close x volume over the last ``window_sessions`` own bars through t is
  at or above ``entry_floor`` to enter, and a current member stays while it is at or above
  ``exit_floor`` (hysteresis: the exit floor is below the entry floor, so a name between the two
  keeps its prior state and the cross-section stays stable);
- 5m tier (amendment 2026-11-15): a member whose same median is at or above ``tier_entry_floor``
  is in the 5m tier, and a tier member stays while it is at or above ``tier_exit_floor``. The tier
  has its own hysteresis state, is nested in the membership by construction (its floors are at
  or above the membership floors) and leaves with it.

The type, price, bar-on-t and history conditions are hard for members and non-members alike;
hysteresis relaxes only the liquidity floor. A non-finite value anywhere in the window means the
median is not computable and the security is not a member (no_fill: nothing is filled or
dropped). Bars after t are never read, so a decision at t cannot move when later bars arrive.

Dollar volume is close x volume per bar as stored. The product is invariant under a split
adjustment applied to both columns, so the liquidity window needs no un-adjustment; only the
price test needs the as-traded close.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

import numpy as np

from src.intelligence.bars.split_rescale import SplitFactor

# Identifies the preregistered rule values. A dated amendment that changes any value below bumps
# this id; the build ledger refuses to extend a build made under another id.
RULE_ID = "stage2-2026-11-15"

# One definition of "ever a member" and of the build ledger, read by the corpus universe
# (services/corpus_universe.py) and by the research snapshot (research/snapshot.py), so the
# corpus and the IC panel cannot diverge on the name set (todo 609 I1).
LEDGER_SUMMARY_SQL = (
    "SELECT count(*), count(DISTINCT rule_id), max(as_of) FROM universe_membership_build"
)
LEDGER_RULE_ID_SQL = "SELECT min(rule_id) FROM universe_membership_build"
EVER_MEMBER_SQL = "SELECT symbol FROM universe_membership"
# The one tier predicate: the corpus's ever-in-the-tier list and the research tier rows are both built
# from it, so a change to it moves both (a test compares them).
TIER_5M_PREDICATE = "tier_5m"
EVER_TIER_5M_SQL = f"SELECT symbol FROM universe_membership WHERE {TIER_5M_PREDICATE}"
TIER_MEMBER_ROWS_SQL = (
    f"SELECT as_of, symbol FROM universe_membership WHERE {TIER_5M_PREDICATE} "
    "ORDER BY as_of, symbol"
)

# First day of the Massive archive; the first month-end considered.
ARCHIVE_START = date(2003, 9, 10)

# Massive reference types: CS common stock, ADRC ADR of a common stock, ETF.
ELIGIBLE_TYPES: frozenset[str] = frozenset({"CS", "ADRC", "ETF"})


@dataclass(frozen=True)
class MembershipRule:
    """The preregistered values (dollars, sessions)."""

    entry_floor: float = 1_000_000.0
    exit_floor: float = 500_000.0
    tier_entry_floor: float = 25_000_000.0
    tier_exit_floor: float = 12_500_000.0
    window_sessions: int = 60
    min_history_sessions: int = 60
    min_close: float = 1.0
    eligible_types: frozenset[str] = ELIGIBLE_TYPES

    def __post_init__(self) -> None:
        if not 0 < self.exit_floor <= self.entry_floor:
            raise ValueError("MembershipRule: need 0 < exit_floor <= entry_floor")
        if not self.entry_floor <= self.tier_entry_floor or not (
            self.exit_floor <= self.tier_exit_floor <= self.tier_entry_floor
        ):
            raise ValueError(
                "MembershipRule: the tier floors must sit at or above the membership floors"
            )
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
    splits: tuple[SplitFactor, ...] = ()  # every market split on record for the symbol

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
    close: float  # as traded on as_of, not the split-adjusted canonical close
    sessions: int
    entered: bool
    tier_5m: bool  # in the 5m tier (amendment 2026-11-15); implies membership


def month_end_sessions(sessions: Iterable[date]) -> list[date]:
    """The last session of each calendar month among `sessions` (ascending, complete months).

    The caller passes sessions through the end of the last month it wants judged: a partial
    trailing month would otherwise report its latest session as a month-end.
    """
    last: dict[tuple[int, int], date] = {}
    for day in sorted(sessions):
        last[(day.year, day.month)] = day
    return sorted(last.values())


def as_traded_close(canonical_close: float, as_of: date, splits: Iterable[SplitFactor]) -> float:
    """The close that traded on `as_of`: the canonical (split-adjusted) close times the factor of
    every split with effective_date on or after `as_of`, rounded to 6 places (prices are served
    with at most 4, so rounding only removes the float noise of the round trip)."""
    scale = math.prod(split.factor for split in splits if split.effective_date >= as_of)
    return round(canonical_close * scale, 6)


def decide(
    history: SecurityHistory,
    as_of: date,
    security_type: str | None,
    was_member: bool,
    rule: MembershipRule = RULE,
    *,
    was_tier: bool = False,
) -> MembershipRow | None:
    """The membership row for `history.symbol` at `as_of`, or None when it is not a member.

    `security_type` is the Massive type at `as_of` (None when unknown, which is ineligible).
    `was_tier` is the 5m tier state at the previous month-end; it only counts for a name that
    stays a member, so leaving the membership resets it.
    """
    if security_type is None or security_type not in rule.eligible_types:
        return None
    n = int(np.searchsorted(history.days, np.datetime64(as_of, "D"), side="right"))
    if n < rule.min_history_sessions or history.days[n - 1] != np.datetime64(as_of, "D"):
        return None
    close = as_traded_close(float(history.close[n - 1]), as_of, history.splits)
    if not math.isfinite(close) or close < rule.min_close:
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
        tier_5m=median >= (rule.tier_exit_floor if was_tier else rule.tier_entry_floor),
    )


def memberships_for_security(
    history: SecurityHistory,
    month_ends: Iterable[date],
    types: Mapping[date, str | None],
    *,
    was_member: bool = False,
    was_tier: bool = False,
    rule: MembershipRule = RULE,
) -> list[MembershipRow]:
    """Walk `month_ends` (ascending) for one security, carrying membership forward for the
    hysteresis. `was_member` and `was_tier` seed the state before the first month-end (a resumed
    build passes the previous month's membership and tier). `types` maps each month-end to the type known on it; a
    missing key is an unknown type."""
    rows: list[MembershipRow] = []
    for as_of in month_ends:
        row = decide(history, as_of, types.get(as_of), was_member, rule, was_tier=was_tier)
        was_member = row is not None
        was_tier = row is not None and row.tier_5m
        if row is not None:
            rows.append(row)
    return rows
