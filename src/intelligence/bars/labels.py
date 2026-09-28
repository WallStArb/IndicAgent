"""D0 data-quality labels for a research attempt (D-04).

Every attempt carries four typed labels describing the data it read, recorded
with the attempt in the S0 manifest and the S6 evidence: venue truncation
share (cells on names whose history starts at a venue move), the dividend
label (total-return flag plus the share of cells without dividend coverage),
the survivorship bound (literature haircut plus delisting-return sensitivity
per unified design 12.2) and the scrub-flag share (cells on D2a-flagged bars).

These labels describe exposure. They never gate a verdict by themselves:
D-04 fixes them as a bound reported beside the statistic, so a bad label is a
disclosed limitation, not a rejected run. Old verdicts are not re-run; labels
are computed for new attempts only.

Inputs arrive as arrays from the DB read helper (plan 16, which needs D1 and
the re-run inventory first). Survivorship seeds are APR keys under
alpha.survivorship.* (migration 382, Shumway 1997 and Shumway and Warther
1999); callers load them into a plain mapping and pass
``SurvivorshipRule.from_apr``. ``d2_rule_version`` is the D2 rule version the
attempt read (D-07), carried unchanged into the manifest.

Pure: arrays in, labels out; no database, no config service, no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

# Routing codes -> survivorship literature exchange buckets. A mirror of the
# provider's venue codes (the pure module must not import the provider).
_NASDAQ_CODES = frozenset({"ISLAND", "NASDAQ"})
_NYSE_AMEX_CODES = frozenset({"NYSE", "AMEX", "ARCA", "BATS"})


def _exchange_bucket(code: str) -> str:
    """Literature bucket for an exchange routing code.

    ISLAND is Nasdaq's order-routing code. Unknown codes map to the nasdaq
    bucket: it carries the larger hazard and the larger loss (the seeds:
    0.056 x -0.55 vs 0.012 x -0.30), so an unmapped exchange overstates the
    bound instead of understating it.
    """
    normalized = code.strip().upper()
    if normalized in _NASDAQ_CODES:
        return "nasdaq"
    if normalized in _NYSE_AMEX_CODES:
        return "nyse_amex"
    return "nasdaq"


@dataclass(frozen=True)
class SurvivorshipRule:
    """Delisting assumptions behind the survivorship bound (APR-seeded).

    Delisting returns are the Shumway-style performance-delisting losses, both
    ``[ASSUMED]`` literature numbers; hazards are the annual probability a
    name delists for performance reasons. Bounds mirror the config_schema
    ranges of migration 382 so a value that escaped the schema is refused here
    too.
    """

    delisting_return_nasdaq: float
    delisting_return_nyse_amex: float
    hazard_nasdaq_annual: float
    hazard_nyse_amex_annual: float
    haircut_small_cap_annual: float
    trading_days_per_year: int

    def __post_init__(self) -> None:
        for name in ("delisting_return_nasdaq", "delisting_return_nyse_amex"):
            value = getattr(self, name)
            if not -1.0 <= value <= 0.0:
                raise ValueError(f"{name} must be in [-1, 0], got {value}")
        for name in (
            "hazard_nasdaq_annual",
            "hazard_nyse_amex_annual",
            "haircut_small_cap_annual",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1], got {value}")
        if self.trading_days_per_year < 1:
            raise ValueError(
                f"trading_days_per_year must be >= 1, got {self.trading_days_per_year}"
            )

    @classmethod
    def from_apr(cls, apr: Mapping[str, Any]) -> SurvivorshipRule:
        """Build the rule from a caller-loaded APR mapping.

        Keys are the full dotted alpha.survivorship.* names; this module never
        reads the config service itself.
        """
        return cls(
            delisting_return_nasdaq=float(apr["alpha.survivorship.delisting_return.nasdaq"]),
            delisting_return_nyse_amex=float(apr["alpha.survivorship.delisting_return.nyse_amex"]),
            hazard_nasdaq_annual=float(apr["alpha.survivorship.hazard.nasdaq_annual"]),
            hazard_nyse_amex_annual=float(apr["alpha.survivorship.hazard.nyse_amex_annual"]),
            haircut_small_cap_annual=float(apr["alpha.survivorship.haircut.small_cap_annual"]),
            trading_days_per_year=int(apr["alpha.survivorship.trading_days_per_year"]),
        )

    def daily_hazard(self, bucket: str) -> float:
        """Per-session delisting probability for a literature bucket."""
        annual = self.hazard_nasdaq_annual if bucket == "nasdaq" else self.hazard_nyse_amex_annual
        return annual / self.trading_days_per_year

    def delisting_return(self, bucket: str) -> float:
        """Delisting return for a literature bucket."""
        return (
            self.delisting_return_nasdaq if bucket == "nasdaq" else self.delisting_return_nyse_amex
        )


def venue_truncation_share(cell_symbols: np.ndarray, moved_symbols: frozenset[str]) -> float:
    """Share of an attempt's cells on names whose history starts at a venue move.

    ``cell_symbols`` holds one symbol per (name, session) cell, any shape; the
    share is moved cells over all cells. An attempt with no cells has no
    measured exposure and reports 0.0.
    """
    arr = np.asarray(cell_symbols)
    if arr.size == 0:
        return 0.0
    mask = np.fromiter(
        (symbol in moved_symbols for symbol in arr.ravel()),
        dtype=bool,
        count=arr.size,
    ).reshape(arr.shape)
    return float(mask.mean())


@dataclass(frozen=True)
class DividendLabel:
    """Dividend exposure of the attempt (todo 428, todo 449 coverage).

    ``total_return`` is the spec's panel.total_return flag; outside dividend
    coverage a name's dividends are unknown, never zero, so
    ``uncovered_share`` sizes that unknown.
    """

    total_return: bool
    uncovered_share: float


def dividend_label(total_return: bool, div_covered: np.ndarray) -> DividendLabel:
    """Label from the spec's total-return flag and a per-cell coverage mask.

    ``div_covered`` is boolean per cell (the session lies inside the symbol's
    dividend coverage). Non-boolean input is refused: a silently coerced
    integer mask would mislabel coverage.
    """
    arr = np.asarray(div_covered)
    if arr.dtype != np.dtype(bool):
        raise TypeError(f"div_covered must be boolean, got dtype {arr.dtype}")
    if arr.size == 0:
        return DividendLabel(total_return=bool(total_return), uncovered_share=0.0)
    return DividendLabel(
        total_return=bool(total_return),
        uncovered_share=float(np.logical_not(arr).mean()),
    )


def scrub_flag_share(cell_keys: np.ndarray, flagged_keys: frozenset) -> float:
    """Share of the attempt's cells sitting on D2a-flagged bars (D-09).

    ``cell_keys`` is a 1-D array of (symbol, ts_seconds) pairs, either a
    structured array or an object array of tuples; ``flagged_keys`` holds the
    (symbol, ts_seconds) pairs the scrub stage flagged. Flagged keys outside
    the attempt's cells do not count: the label sizes this attempt's exposure,
    not the flag table.
    """
    arr = np.asarray(cell_keys)
    if arr.ndim != 1:
        raise ValueError(f"cell_keys must be 1-D, got shape {arr.shape}")
    if arr.size == 0 or not flagged_keys:
        return 0.0
    hits = 0
    for row in arr:
        key = tuple(row.tolist()) if isinstance(row, np.void) else tuple(row)
        if key in flagged_keys:
            hits += 1
    return hits / arr.size


@dataclass(frozen=True)
class SurvivorshipBound:
    """The survivorship bound reported beside the statistic (design 12.2).

    ``haircut_annual`` is the literature small-cap haircut scaled by the
    attempt's small-cap share. ``expected_delisting_drag_annual`` is the
    annualized hazard-weighted expected loss on gross exposure (a hedged book
    is not immune: each side's names can delist), the conservative single
    exchange at unit exposure when no weights are given. ``sensitivity`` is
    the signed book-level expected annual return change from booking
    delistings, None without weights.
    """

    haircut_annual: float
    expected_delisting_drag_annual: float
    sensitivity: float | None


def _per_name_delisting_impact(rule: SurvivorshipRule, exchange_of: Sequence[str]) -> np.ndarray:
    """Signed per-name expected per-session return change from a delisting:
    daily hazard x delisting return, one entry per name in exchange_of order.
    """
    impacts = []
    for code in exchange_of:
        bucket = _exchange_bucket(code)
        impacts.append(rule.daily_hazard(bucket) * rule.delisting_return(bucket))
    return np.array(impacts)


def delisting_sensitivity(
    weights: np.ndarray, exchange_of: Sequence[str], rule: SurvivorshipRule
) -> float:
    """Signed delisting-return sensitivity of a book (design 12.2).

    Expected per-session return change = sum over names of w[t, n] x
    daily_hazard(exchange_n) x delisting_return(exchange_n), averaged over
    sessions and annualized (x trading_days_per_year; the daily hazard divides
    it back out, so a constant book sees the annual number directly). A flat
    long/short with the same exchange mix on both sides nets to zero; the
    names most exposed (reversal books) carry the largest magnitude.
    """
    w = np.asarray(weights, dtype=float)
    if w.ndim != 2:
        raise ValueError(f"weights must be 2-D [T, N], got shape {w.shape}")
    if w.shape[0] < 1:
        raise ValueError("weights must hold at least one session")
    if w.shape[1] != len(exchange_of):
        raise ValueError(
            f"weights name axis ({w.shape[1]}) and exchange_of ({len(exchange_of)}) disagree"
        )
    if not np.isfinite(w).all():
        raise ValueError("weights must be finite")
    per_session = w @ _per_name_delisting_impact(rule, exchange_of)
    return float(per_session.mean() * rule.trading_days_per_year)


def survivorship_bound(
    rule: SurvivorshipRule,
    *,
    small_cap_share: float,
    weights: np.ndarray | None = None,
    exchange_of: Sequence[str] | None = None,
) -> SurvivorshipBound:
    """Bound from the haircut plus the delisting sensitivity (design 12.2).

    With ``weights`` the drag is the hazard-weighted expected |delisting
    return| loss on gross exposure, annualized; without them it is the
    conservative exchange's hazard x |delisting return| at unit exposure
    (nasdaq under the seeded values). ``weights`` without ``exchange_of`` is a
    caller error, refused loudly rather than defaulted.
    """
    if not 0.0 <= small_cap_share <= 1.0:
        raise ValueError(f"small_cap_share must be in [0, 1], got {small_cap_share}")
    haircut = small_cap_share * rule.haircut_small_cap_annual
    conservative_unit_drag = max(
        rule.hazard_nasdaq_annual * abs(rule.delisting_return_nasdaq),
        rule.hazard_nyse_amex_annual * abs(rule.delisting_return_nyse_amex),
    )
    if weights is None:
        return SurvivorshipBound(
            haircut_annual=float(haircut),
            expected_delisting_drag_annual=float(conservative_unit_drag),
            sensitivity=None,
        )
    if exchange_of is None:
        raise ValueError("weights require exchange_of")
    sensitivity = delisting_sensitivity(weights, exchange_of, rule)
    w = np.asarray(weights, dtype=float)
    gross_drag = float(
        (np.abs(w) @ np.abs(_per_name_delisting_impact(rule, exchange_of))).mean()
        * rule.trading_days_per_year
    )
    return SurvivorshipBound(
        haircut_annual=float(haircut),
        expected_delisting_drag_annual=gross_drag,
        sensitivity=sensitivity,
    )


@dataclass(frozen=True)
class DataQualityLabels:
    """The four D0 labels plus the D2 rule version the attempt read (D-07).

    The manifest block is carried unchanged by the S0 manifest and the S6
    evidence (D-04); ``d2_rule_version`` is the hook that makes every recorded
    attempt name the derivation rule behind its bars.
    """

    d2_rule_version: str | None
    venue_truncation_share: float
    dividends: DividendLabel
    survivorship: SurvivorshipBound
    scrub_flag_share: float

    def to_manifest(self) -> dict:
        """A JSON-able manifest block (plain scalars only)."""
        return {
            "d2_rule_version": self.d2_rule_version,
            "venue_truncation_share": float(self.venue_truncation_share),
            "dividends": {
                "total_return": bool(self.dividends.total_return),
                "uncovered_share": float(self.dividends.uncovered_share),
            },
            "survivorship": {
                "haircut_annual": float(self.survivorship.haircut_annual),
                "expected_delisting_drag_annual": float(
                    self.survivorship.expected_delisting_drag_annual
                ),
                "sensitivity": (
                    None
                    if self.survivorship.sensitivity is None
                    else float(self.survivorship.sensitivity)
                ),
            },
            "scrub_flag_share": float(self.scrub_flag_share),
        }


def build_labels(
    *,
    d2_rule_version: str | None,
    cell_symbols: np.ndarray,
    moved_symbols: frozenset[str],
    total_return: bool,
    div_covered: np.ndarray,
    cell_keys: np.ndarray,
    flagged_keys: frozenset,
    rule: SurvivorshipRule,
    small_cap_share: float,
    weights: np.ndarray | None = None,
    exchange_of: Sequence[str] | None = None,
) -> DataQualityLabels:
    """Compute all four labels for one attempt from its inputs (pure).

    One call site for the attempt manifest: every input is a keyword argument,
    so the plan 16 read helper forwards exactly what it loaded. Optional
    weights/exchange_of carry the delisting sensitivity when the attempt has a
    book.
    """
    return DataQualityLabels(
        d2_rule_version=d2_rule_version,
        venue_truncation_share=venue_truncation_share(cell_symbols, moved_symbols),
        dividends=dividend_label(total_return, div_covered),
        survivorship=survivorship_bound(
            rule,
            small_cap_share=small_cap_share,
            weights=weights,
            exchange_of=exchange_of,
        ),
        scrub_flag_share=scrub_flag_share(cell_keys, flagged_keys),
    )
