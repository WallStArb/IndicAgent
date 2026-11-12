"""Massive load checks, name-level half (admission design section 8a, stage C): pure math.

Companion of ``massive_load_checks`` (the systemic stages). Pure Ring 1: arrays and dataclasses in,
verdicts out. The runner is ``scripts/ops/bars/ops_massive_load_checks.py``.

Rules quoted from the design table (spec constants, not tunables):

- A bar agrees when ``abs(Massive / factor - incumbent) <= half the incumbent's price increment +
  1 bp of the incumbent price``. The verdict basis is the CLOSE (the design's price-agreement row
  names no field; the 1d census row names all of O, H, L, C separately, so the census reads
  ``n_agree_all`` and the verdicts read ``n_agree``). The factor is the cumulative
  split scale from the FROZEN corporate-action list, never fitted from the compared series.
- 99 percent of matched bars per name-era, 99.5 percent vendor-wide (per era). Disagreements are
  classified rounding / last_print / scale / time_shift / other; above 0.5 percent ``other``
  vendor-wide: investigate before any switch.
- Scale factor (587 class): per name-year, median log close ratio within 10 bp of 0.
- Identity: a pair whose daily return correlation is under 0.9 is identity-unresolved, never a
  scale finding.
- Universe closure: every (name, era) cell carries exactly one outcome in pass | gap_list | stop;
  the bucket counts sum to the mapped total; a partial run is a ``PartialRun``, never a table.
- Disagreement ledger: precedence filing-dated corporate action, then exchange-official close, then
  Massive's continuity across eras; a 2016+ Alpaca reading corroborates and never outranks.

Every judging function raises ``VacuousCheckError`` on zero matched bars: an empty join is a
failure, never a pass.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from src.intelligence.bars.massive_load_checks import VacuousCheckError

# --- spec constants (design section 8a) --------------------------------------------------------
PRICE_REL_TOL = 1e-4  # 1 bp
HALF_INCREMENT = 0.5
NAME_ERA_AGREE_MIN = 0.99
VENDOR_AGREE_MIN = 0.995
OTHER_INVESTIGATE_MAX_SHARE = 0.005
SCALE_LEVEL_TOL = 0.001  # 10 bp on the median log close ratio
IDENTITY_MIN_CORRELATION = 0.9
DISPUTE_WINDOW_SESSIONS = 10
#: Stored price increment per incumbent arm: IBKR stores adjusted prices at cent precision
#: (design 8a); Alpaca keeps sub-penny SIP prices at four decimals.
INCUMBENT_INCREMENT = {"ibkr": 0.01, "alpaca": 0.0001}
#: Classification: a bar whose own log ratio lies this close (log units) to the name-year median
#: reads as a scale disagreement when that median is itself outside the scale tolerance; a bar
#: within ``ROUNDING_INCREMENTS`` increments (plus 1 bp) reads as rounding.
SCALE_CLASS_BAR_TOL = 0.005
ROUNDING_INCREMENTS = 1.5

CLASS_ROUNDING, CLASS_LAST_PRINT, CLASS_SCALE = "rounding", "last_print", "scale"
CLASS_TIME_SHIFT, CLASS_OTHER = "time_shift", "other"
CLASSES = (CLASS_ROUNDING, CLASS_LAST_PRINT, CLASS_SCALE, CLASS_TIME_SHIFT, CLASS_OTHER)

Ohlc = tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]


def agree_mask(
    massive_raw: np.ndarray, scale: np.ndarray, incumbent: np.ndarray, increment: float
) -> np.ndarray:
    """Per bar field: abs(Massive / factor - incumbent) within half an increment plus 1 bp."""
    diff = np.abs(massive_raw / scale - incumbent)
    agree: np.ndarray = diff <= HALF_INCREMENT * increment + PRICE_REL_TOL * np.abs(incumbent)
    return agree


@dataclass(frozen=True)
class AgreementCounts:
    n_matched: int
    n_agree: int  # bars whose close agrees: the verdict basis
    n_agree_all: int  # bars where open, high, low and close all agree: the census basis
    n_class: dict[str, int] = field(default_factory=dict)  # disagreement class counts

    @property
    def share(self) -> float:
        return self.n_agree / self.n_matched

    def __add__(self, other: AgreementCounts) -> AgreementCounts:
        merged = Counter(self.n_class)
        merged.update(other.n_class)
        return AgreementCounts(
            self.n_matched + other.n_matched,
            self.n_agree + other.n_agree,
            self.n_agree_all + other.n_agree_all,
            dict(merged),
        )


def classify_disagreements(
    massive_adj: Ohlc,
    incumbent: Ohlc,
    massive_prev_adj: Ohlc | None,
    massive_next_adj: Ohlc | None,
    increment: float,
    name_median_log_ratio: float,
    last_bucket: np.ndarray | None = None,
) -> np.ndarray:
    """A class label per matched bar (object array; '' where the bar agrees).

    ``massive_adj`` is the factor-adjusted Massive series aligned with the incumbent;
    ``massive_prev_adj`` / ``massive_next_adj`` the same series one bar earlier / later in Massive's
    own order (NaN where absent), for the time-shift reading; ``last_bucket`` flags the final
    bucket of a session (the closing auction and late prints land there). Order of reading:
    time_shift (all four fields agree with the previous or the next Massive bar), last_print (open,
    high and low agree and the close does not, or the bar is the session's last bucket: last-print
    eligibility differs between SIP and a vendor's own filter), rounding (within 1.5 increments
    plus 1 bp on every field), scale (the name's median log ratio is outside the scale tolerance
    and this bar's close ratio sits within 0.5 percent of it), else other."""
    n = len(incumbent[0])
    labels = np.full(n, "", dtype=object)

    def within(a: Ohlc, inc: Ohlc, slack: float) -> np.ndarray:
        ok = np.ones(n, dtype=bool)
        for x, y in zip(a, inc, strict=True):
            ok &= np.abs(x - y) <= slack + PRICE_REL_TOL * np.abs(y)
        return ok

    agree = within(massive_adj, incumbent, HALF_INCREMENT * increment)
    rounding = within(massive_adj, incumbent, ROUNDING_INCREMENTS * increment)
    shift = np.zeros(n, dtype=bool)
    for other in (massive_prev_adj, massive_next_adj):
        if other is not None:
            shift |= within(other, incumbent, HALF_INCREMENT * increment)
    ohl = np.ones(n, dtype=bool)
    for k in range(3):
        ohl &= np.abs(
            massive_adj[k] - incumbent[k]
        ) <= HALF_INCREMENT * increment + PRICE_REL_TOL * np.abs(incumbent[k])
    with np.errstate(divide="ignore", invalid="ignore"):
        bar_log = np.log(massive_adj[3] / incumbent[3])
    name_off = abs(name_median_log_ratio) > SCALE_LEVEL_TOL
    scale = (
        name_off & (np.abs(bar_log - name_median_log_ratio) <= SCALE_CLASS_BAR_TOL)
        if name_off
        else np.zeros(n, dtype=bool)
    )
    if last_bucket is not None:
        ohl = ohl | last_bucket
    pending = ~agree
    for label, mask in (
        (CLASS_TIME_SHIFT, shift),
        (CLASS_LAST_PRINT, ohl),
        (CLASS_ROUNDING, rounding),
        (CLASS_SCALE, scale),
    ):
        take = pending & mask
        labels[take] = label
        pending &= ~take
    labels[pending] = CLASS_OTHER
    return labels


def price_agreement(
    massive_raw: Ohlc,
    scale: np.ndarray,
    incumbent: Ohlc,
    increment: float,
    *,
    massive_prev_raw: Ohlc | None = None,
    massive_next_raw: Ohlc | None = None,
    last_bucket: np.ndarray | None = None,
) -> AgreementCounts:
    """Agreement of matched bars (arrays aligned bar for bar). Raises when nothing matched."""
    n = len(scale)
    if n == 0:
        raise VacuousCheckError("price_agreement: no matched bar")
    fields = [
        agree_mask(m, scale, i, increment) for m, i in zip(massive_raw, incumbent, strict=True)
    ]
    all_agree = fields[0] & fields[1] & fields[2] & fields[3]
    adj = tuple(m / scale for m in massive_raw)
    prev = tuple(m / scale for m in massive_prev_raw) if massive_prev_raw is not None else None
    nxt = tuple(m / scale for m in massive_next_raw) if massive_next_raw is not None else None
    with np.errstate(divide="ignore", invalid="ignore"):
        median_log = float(np.nanmedian(np.log(adj[3] / incumbent[3])))
    labels = classify_disagreements(
        adj, incumbent, prev, nxt, increment, median_log, last_bucket  # type: ignore[arg-type]
    )
    classes = Counter(str(x) for x in labels[~fields[3]])
    return AgreementCounts(n, int(fields[3].sum()), int(all_agree.sum()), dict(classes))


def name_era_agreement_ok(counts: AgreementCounts) -> bool:
    if counts.n_matched <= 0:
        raise VacuousCheckError("name_era_agreement_ok: no matched bar")
    return counts.share >= NAME_ERA_AGREE_MIN


@dataclass(frozen=True)
class VendorWide:
    n_matched: int
    share: float
    other_share: float
    verdict: str  # ok | stop
    investigate: bool  # 'other' above 0.5 percent vendor-wide


def vendor_wide(counts: Iterable[AgreementCounts]) -> VendorWide:
    """Vendor-wide agreement over the judged name-eras of one era: 99.5 percent or stop."""
    total: AgreementCounts | None = None
    for c in counts:
        total = c if total is None else total + c
    if total is None or total.n_matched <= 0:
        raise VacuousCheckError("vendor_wide: no matched bar in any name-era")
    other = total.n_class.get(CLASS_OTHER, 0) / total.n_matched
    return VendorWide(
        total.n_matched,
        total.share,
        other,
        "ok" if total.share >= VENDOR_AGREE_MIN else "stop",
        other > OTHER_INVESTIGATE_MAX_SHARE,
    )


# --- scale factor ------------------------------------------------------------------------------
def scale_check(
    massive_close_raw: np.ndarray, scale: np.ndarray, incumbent_close: np.ndarray
) -> float:
    """The median log close ratio ln(Massive / factor / incumbent) of a name-year. The factor is
    given (frozen splits), never estimated here. Raises on zero matched bars."""
    if len(scale) == 0:
        raise VacuousCheckError("scale_check: no matched bar")
    with np.errstate(divide="ignore", invalid="ignore"):
        return float(np.median(np.log(massive_close_raw / scale / incumbent_close)))


def scale_ok(median_log_ratio: float) -> bool:
    return abs(median_log_ratio) <= SCALE_LEVEL_TOL


# --- identity ----------------------------------------------------------------------------------
def identity_correlation(massive_close_adj: np.ndarray, incumbent_close: np.ndarray) -> float:
    """Correlation of daily log returns of two aligned adjusted close series. Needs at least 3
    aligned closes (two returns) and non-constant returns, else the identity is unresolved (NaN)."""
    if len(massive_close_adj) < 3:
        return math.nan
    a = np.diff(np.log(massive_close_adj))
    b = np.diff(np.log(incumbent_close))
    if np.std(a) == 0 or np.std(b) == 0:
        return math.nan
    return float(np.corrcoef(a, b)[0, 1])


def identity_resolved(correlation: float) -> bool:
    return not math.isnan(correlation) and correlation >= IDENTITY_MIN_CORRELATION


# --- pre-classification ------------------------------------------------------------------------
ERA_NO_ACTION, ERA_SPLITS_ONLY, ERA_NON_SPLIT = "no_action", "splits_only", "non_split_adjustment"


def preclassify_name_era(splits_in_window: int, non_split_listed: bool) -> str:
    """Name-era class, fixed from the frozen lists BEFORE any comparison: a name-era on the
    non-split adjustment list is a convention difference (price and scale checks do not apply);
    otherwise no_action or splits_only by the frozen split count in the window."""
    if non_split_listed:
        return ERA_NON_SPLIT
    return ERA_SPLITS_ONLY if splits_in_window > 0 else ERA_NO_ACTION


def alpaca_epoch_seam_possible(
    served_min: date | None, served_max: date | None, split_effective_dates: Sequence[date]
) -> bool:
    """An Alpaca capture-epoch seam is possible in a name-era when a recorded market split's
    effective date lies after the first capture and not after the last capture of the era's Alpaca
    rows: bars captured before it carry the old basis, bars captured after it the new one."""
    if served_min is None or served_max is None:
        return False
    return any(served_min < d <= served_max for d in split_effective_dates)


# --- universe closure --------------------------------------------------------------------------
OUTCOME_PASS, OUTCOME_GAP, OUTCOME_STOP = "pass", "gap_list", "stop"
OUTCOMES = (OUTCOME_PASS, OUTCOME_GAP, OUTCOME_STOP)


@dataclass(frozen=True)
class Partition:
    n_mapped_cells: int
    counts: dict[str, int]
    cells: dict[tuple[str, int], tuple[str, str]]  # (name, era) -> (outcome, reason)


@dataclass(frozen=True)
class PartialRun:
    """The run did not judge every expected cell: reported as partial, never as a result table."""

    n_expected: int
    n_judged: int
    missing: tuple[tuple[str, int], ...]


def close_partition(
    expected: Iterable[tuple[str, int]],
    outcomes: Mapping[tuple[str, int], tuple[str, str]],
    stop_eras: Iterable[int] = (),
) -> Partition | PartialRun:
    """The complete partition of the expected (name, era) cells, or a ``PartialRun``.

    A cell in a ``stop_eras`` era carries ``stop`` (a systemic failure stops step 7 for the era)
    whatever its own outcome. An outcome outside ``OUTCOMES``, or a cell judged but not expected,
    raises (a wrong partition is a bug, not a result)."""
    cells = list(dict.fromkeys(expected))
    if not cells:
        raise VacuousCheckError("close_partition: no expected cell")
    stops = set(stop_eras)
    unknown = [c for c in outcomes if c not in set(cells)]
    if unknown:
        raise ValueError(f"cells judged but not expected: {unknown[:3]}")
    missing = tuple(c for c in cells if c not in outcomes)
    if missing:
        return PartialRun(len(cells), len(cells) - len(missing), missing)
    final: dict[tuple[str, int], tuple[str, str]] = {}
    for cell in cells:
        outcome, reason = outcomes[cell]
        if outcome not in OUTCOMES:
            raise ValueError(f"cell {cell}: outcome {outcome!r} is not one of {OUTCOMES}")
        final[cell] = (
            (OUTCOME_STOP, "systemic_stop_in_era") if cell[1] in stops else (outcome, reason)
        )
    counts = {o: 0 for o in OUTCOMES}
    for outcome, _ in final.values():
        counts[outcome] += 1
    if sum(counts.values()) != len(cells):
        raise ValueError("partition buckets do not sum to the mapped total")
    return Partition(len(cells), counts, final)


# --- disagreement ledger -----------------------------------------------------------------------
#: Precedence, strongest first (design 8a amendment 2026-11-10). ``alpaca_2016_plus`` corroborates
#: and never outranks; ``ibkr_1d_official_close`` witnesses only Massive-against-IBKR disputes.
WITNESS_PRECEDENCE = (
    "filing_dated_corporate_action",
    "exchange_official_close",
    "ibkr_1d_official_close",
    "massive_continuity",
)
CORROBORATOR = "alpaca_2016_plus"
DISPUTE_MASSIVE_VS_IBKR = "massive_vs_ibkr"
DISPUTE_MASSIVE_INTERNAL = "massive_internal"
VERDICT_INCUMBENT_DEFECT = "incumbent_defect"
VERDICT_MASSIVE_DEFECT = "massive_defect"
VERDICT_UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class Witness:
    kind: str
    supports: str  # "massive" or "incumbent"
    citation: str


@dataclass(frozen=True)
class LedgerRow:
    name: str
    span: str
    claimed_defect: str
    witnesses: tuple[Witness, ...]
    verdict: str
    deciding_session_id: str
    decided_by: str  # the witness kind that decided, or "none"


def ledger_verdict(
    name: str,
    span: str,
    claimed_defect: str,
    witnesses: Sequence[Witness],
    dispute_kind: str,
    session_id: str,
) -> LedgerRow:
    """Decide one disputed case by the stated precedence. The first witness kind in
    ``WITNESS_PRECEDENCE`` present decides (several witnesses of one kind must agree, else the case
    is unresolved). An incumbent defect call needs a third witness: Massive is the yardstick, but a
    case with only the Alpaca corroborator, or none, is unresolved. ``ibkr_1d_official_close`` is
    ignored in a Massive-internal dispute (it would be circular there)."""
    usable = [
        w
        for w in witnesses
        if w.kind in WITNESS_PRECEDENCE
        and not (w.kind == "ibkr_1d_official_close" and dispute_kind != DISPUTE_MASSIVE_VS_IBKR)
    ]
    for kind in WITNESS_PRECEDENCE:
        same = [w for w in usable if w.kind == kind]
        if not same:
            continue
        sides = {w.supports for w in same}
        if len(sides) > 1:
            return LedgerRow(
                name, span, claimed_defect, tuple(witnesses), VERDICT_UNRESOLVED, session_id, kind
            )
        verdict = VERDICT_MASSIVE_DEFECT if sides == {"incumbent"} else VERDICT_INCUMBENT_DEFECT
        return LedgerRow(name, span, claimed_defect, tuple(witnesses), verdict, session_id, kind)
    return LedgerRow(
        name, span, claimed_defect, tuple(witnesses), VERDICT_UNRESOLVED, session_id, "none"
    )


# --- disputed-date windows (the 1d census) -----------------------------------------------------
def dispute_window_sessions(
    sessions: Sequence[date], disputed: date, half_width: int = DISPUTE_WINDOW_SESSIONS
) -> list[date]:
    """The ``half_width`` sessions either side of a disputed date, and the date's own session (or
    the next one when it is not a session). Empty when the date lies beyond the session list."""
    ordered = sorted(sessions)
    pos = next((i for i, d in enumerate(ordered) if d >= disputed), None)
    if pos is None:
        return []
    return ordered[max(0, pos - half_width) : pos + half_width + 1]
