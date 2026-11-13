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
- Universe closure: every (name, era) cell carries exactly one outcome (``OUTCOMES``);
  the bucket counts sum to the mapped total; a partial run is a ``PartialRun``, never a table.
- Disagreement ledger: precedence filing-dated corporate action, then exchange-official close, then
  Massive's continuity across eras; a 2016+ Alpaca reading corroborates and never outranks.

Every judging function raises ``VacuousCheckError`` on zero matched bars: an empty join is a
failure, never a pass.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
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
#: Round 5 constants (design 8a, amendments 2026-11-12 rules 1 to 8 and 2026-11-13).
NAME_ERA_MIN_PAIRS = 100  # consecutive matched pairs the 99 percent name-era test needs
REFERENCE_ERAS = range(2014, 2027)
COUNTER_REFERENCE_MULTIPLE = 3.0
COUNTER_FLOOR_SHARE = 0.02
OTHER_CONCENTRATION_MAX_NAMES = 50
LAST_PRINT_CAP_QUANTILE = 0.99
LAST_PRINT_BIN = 1e-4  # log units per histogram bin
LAST_PRINT_MAX_BIN = 2000
SHARED_FACTOR_BIN = 0.005  # log units
IDENTITY_MIN_RETURNS = 20  # returns the identity correlation needs after the split-sized ones
IDENTITY_SPLIT_LOG_RETURN = math.log(
    1.5
)  # a return this large on either arm is a split, not identity
STABLE_CONSTANT_MAX_LEVEL_SHARE = 0.5  # close level agreement under this: the offset is constant
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
    n_agree: int  # bars whose close agrees in LEVEL: the classification input
    n_agree_all: int  # bars where open, high, low and close all agree: the census basis
    n_class: dict[str, int] = field(default_factory=dict)  # level disagreement class counts
    n_ret_pairs: int = 0  # matched consecutive bar pairs
    n_ret_agree: int = 0  # pairs whose bar-to-bar log close return agrees
    n_intra: int = 0  # matched bars with a usable open
    n_intra_agree: int = 0  # bars whose intrabar log(close / open) agrees
    #: last_print candidates by absolute log close difference bin (``LAST_PRINT_BIN`` wide); the
    #: cap of rule 3 is applied at assembly, once the reference period's p99 is known
    lp_hist: dict[int, int] = field(default_factory=dict)

    def unexplained(self, cap_bin: int) -> int:
        """Disagreeing bars no size-capped convention explains: ``other`` plus the last_print
        candidates beyond the cap."""
        beyond = sum(n for b, n in self.lp_hist.items() if b > cap_bin)
        return self.n_class.get(CLASS_OTHER, 0) + beyond

    @property
    def share(self) -> float:
        return self.n_agree / self.n_matched

    @property
    def ret_share(self) -> float:
        """Return-based agreement (nan without a consecutive pair)."""
        return self.n_ret_agree / self.n_ret_pairs if self.n_ret_pairs else math.nan

    @property
    def intra_share(self) -> float:
        return self.n_intra_agree / self.n_intra if self.n_intra else math.nan

    def __add__(self, other: AgreementCounts) -> AgreementCounts:
        merged = Counter(self.n_class)
        merged.update(other.n_class)
        hist = Counter(self.lp_hist)
        hist.update(other.lp_hist)
        return AgreementCounts(
            self.n_matched + other.n_matched,
            self.n_agree + other.n_agree,
            self.n_agree_all + other.n_agree_all,
            dict(merged),
            self.n_ret_pairs + other.n_ret_pairs,
            self.n_ret_agree + other.n_ret_agree,
            self.n_intra + other.n_intra,
            self.n_intra_agree + other.n_intra_agree,
            dict(hist),
        )


def _tau(price: np.ndarray, increment: float) -> np.ndarray:
    """Price-space tolerance of one incumbent price: half its increment plus 1 bp of its level."""
    out: np.ndarray = HALF_INCREMENT * increment + PRICE_REL_TOL * np.abs(price)
    return out


def return_agreement(
    massive_adj: Ohlc,
    incumbent: Ohlc,
    massive_pos: np.ndarray,
    incumbent_pos: np.ndarray,
    increment: float,
) -> tuple[int, int, int, int]:
    """Level-invariant agreement (counts: pairs, pair agrees, bars, bar agrees).

    ``massive_adj`` and ``incumbent`` are matched bars, aligned; ``massive_pos`` and
    ``incumbent_pos`` are each bar's position in its own (filtered, time-ordered) series, so two
    matched bars are CONSECUTIVE only when both positions advance by exactly one.

    Bar-to-bar: with c the close, a pair agrees when
    ``|ln(cM_t / cM_{t-1}) - ln(cI_t / cI_{t-1})| <= tau(cI_t) / cI_t + tau(cI_{t-1}) / cI_{t-1}``,
    ``tau(p) = increment / 2 + 1e-4 * p`` (the design's half increment plus 1 bp, each side's price
    error divided by its level and added). Intrabar: a bar agrees when
    ``|ln(cM / oM) - ln(cI / oI)| <= tau(cI) / cI + tau(oI) / oI``. A constant level factor
    (an incumbent non-split adjustment) cancels in both. NaN or non-positive values disagree."""
    mc, ic = massive_adj[3], incumbent[3]
    with np.errstate(divide="ignore", invalid="ignore"):
        consec = (massive_pos[1:] - massive_pos[:-1] == 1) & (
            incumbent_pos[1:] - incumbent_pos[:-1] == 1
        )
        r_m = np.log(mc[1:] / mc[:-1])
        r_i = np.log(ic[1:] / ic[:-1])
        tol = _tau(ic[1:], increment) / ic[1:] + _tau(ic[:-1], increment) / ic[:-1]
        pair_ok = np.abs(r_m - r_i) <= tol
        i_m = np.log(mc / massive_adj[0])
        i_i = np.log(ic / incumbent[0])
        itol = _tau(ic, increment) / ic + _tau(incumbent[0], increment) / incumbent[0]
        bar_ok = np.abs(i_m - i_i) <= itol
        usable_open = (
            np.isfinite(massive_adj[0])
            & np.isfinite(incumbent[0])
            & (massive_adj[0] > 0)
            & (incumbent[0] > 0)
        )
    return (
        int(np.count_nonzero(consec)),
        int(np.count_nonzero(consec & pair_ok)),
        int(np.count_nonzero(usable_open)),
        int(np.count_nonzero(bar_ok)),
    )


def classify_disagreements(
    massive_adj: Ohlc,
    incumbent: Ohlc,
    massive_prev_adj: Ohlc | None,
    massive_next_adj: Ohlc | None,
    increment: float,
    name_median_log_ratio: float,
    stable_offset: bool,
    last_bucket: np.ndarray | None = None,
) -> np.ndarray:
    """A class label per matched bar (object array; '' where the bar agrees).

    ``massive_adj`` is the factor-adjusted Massive series aligned with the incumbent;
    ``massive_prev_adj`` / ``massive_next_adj`` the same series one bar earlier / later in Massive's
    own order (NaN where absent), for the time-shift reading; ``last_bucket`` flags the final
    bucket of a session (the closing auction and late prints land there). Order of reading
    (round 5 rule 3, rounding first): rounding (within 1.5 increments plus 1 bp on every field),
    time_shift (all four fields agree with the previous or the next Massive bar), last_print (the
    Massive close lies inside the incumbent bar's high-low range, and open, high and low agree, or
    the bar is the session's last bucket with the open agreeing), scale (the name carries a stable
    constant level offset of any size, ``stable_offset``, and this bar's close ratio sits within
    0.5 percent of the name's median), else other. last_print is a CANDIDATE here: its size cap (the reference period's p99 of the
    absolute log close difference) is applied at assembly, see ``AgreementCounts.lp_hist``."""
    n = len(incumbent[0])
    labels = np.full(n, "", dtype=object)

    def within(a: Ohlc, inc: Ohlc, slack: float) -> np.ndarray:
        ok = np.ones(n, dtype=bool)
        for x, y in zip(a, inc, strict=True):
            ok &= np.abs(x - y) <= slack + PRICE_REL_TOL * np.abs(y)
        return ok

    half = HALF_INCREMENT * increment
    agree = within(massive_adj, incumbent, half)
    rounding = within(massive_adj, incumbent, ROUNDING_INCREMENTS * increment)
    shift = np.zeros(n, dtype=bool)
    for other in (massive_prev_adj, massive_next_adj):
        if other is not None:
            shift |= within(other, incumbent, half)
    field_ok = [
        np.abs(massive_adj[k] - incumbent[k]) <= _tau(incumbent[k], increment) for k in range(3)
    ]
    ohl = field_ok[0] & field_ok[1] & field_ok[2]
    if last_bucket is not None:
        # the last bucket may carry an extra print in high or low; the open must still agree
        ohl = ohl | (last_bucket & field_ok[0])
    close_in_range = (massive_adj[3] >= incumbent[2] - _tau(incumbent[2], increment)) & (
        massive_adj[3] <= incumbent[1] + _tau(incumbent[1], increment)
    )
    last_print = ohl & close_in_range
    with np.errstate(divide="ignore", invalid="ignore"):
        bar_log = np.log(massive_adj[3] / incumbent[3])
    scale = (
        np.abs(bar_log - name_median_log_ratio) <= SCALE_CLASS_BAR_TOL
        if stable_offset
        else np.zeros(n, dtype=bool)
    )
    pending = ~agree
    for label, mask in (
        (CLASS_ROUNDING, rounding),
        (CLASS_TIME_SHIFT, shift),
        (CLASS_LAST_PRINT, last_print),
        (CLASS_SCALE, scale),
    ):
        take = pending & mask
        labels[take] = label
        pending &= ~take
    labels[pending] = CLASS_OTHER
    return labels


def last_print_histogram(
    labels: np.ndarray, massive_close: np.ndarray, incumbent_close: np.ndarray
) -> dict[int, int]:
    """Bin counts of the absolute log close difference of the last_print-labelled bars."""
    sel = labels == CLASS_LAST_PRINT
    if not sel.any():
        return {}
    with np.errstate(divide="ignore", invalid="ignore"):
        diff = np.abs(np.log(massive_close[sel] / incumbent_close[sel]))
    bins = np.minimum(
        np.nan_to_num(diff, nan=LAST_PRINT_MAX_BIN * LAST_PRINT_BIN, posinf=1.0) / LAST_PRINT_BIN,
        LAST_PRINT_MAX_BIN,
    ).astype(np.int64)
    values, counts = np.unique(bins, return_counts=True)
    return {int(v): int(c) for v, c in zip(values, counts, strict=True)}


def price_agreement(
    massive_raw: Ohlc,
    scale: np.ndarray,
    incumbent: Ohlc,
    increment: float,
    *,
    massive_prev_raw: Ohlc | None = None,
    massive_next_raw: Ohlc | None = None,
    last_bucket: np.ndarray | None = None,
    massive_pos: np.ndarray | None = None,
    incumbent_pos: np.ndarray | None = None,
) -> AgreementCounts:
    """Level and (when positions are given) return agreement of matched bars (arrays aligned bar
    for bar). Raises when nothing matched."""
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
        log_ratio = np.log(adj[3] / incumbent[3])
    median_log = float(np.nanmedian(log_ratio))
    q1, q3 = np.nanpercentile(log_ratio, [25, 75])
    stable = bool(
        fields[3].mean() < STABLE_CONSTANT_MAX_LEVEL_SHARE and q3 - q1 <= STABLE_LEVEL_IQR
    )
    labels = classify_disagreements(
        adj, incumbent, prev, nxt, increment, median_log, stable, last_bucket  # type: ignore[arg-type]
    )
    disagree = ~fields[3]
    classes = Counter(str(x) for x in labels[disagree])
    hist = last_print_histogram(np.where(disagree, labels, ""), adj[3], incumbent[3])
    pairs = pair_ok = bars = bar_ok = 0
    if massive_pos is not None and incumbent_pos is not None:
        pairs, pair_ok, bars, bar_ok = return_agreement(
            adj, incumbent, massive_pos, incumbent_pos, increment  # type: ignore[arg-type]
        )
    return AgreementCounts(
        n,
        int(fields[3].sum()),
        int(all_agree.sum()),
        dict(classes),
        pairs,
        pair_ok,
        bars,
        bar_ok,
        hist,
    )


def name_era_agreement_ok(counts: AgreementCounts) -> bool:
    """99 percent of consecutive pairs per name-era on the return-based measure (a constant level
    factor cannot move it). Needs ``NAME_ERA_MIN_PAIRS`` pairs: fewer is no detector, which the
    caller must test first (``has_detector``); here it raises, never passes."""
    if not has_detector(counts):
        raise VacuousCheckError(
            f"name_era_agreement_ok: {counts.n_ret_pairs} pairs, need {NAME_ERA_MIN_PAIRS}"
        )
    return counts.ret_share >= NAME_ERA_AGREE_MIN


def has_detector(counts: AgreementCounts) -> bool:
    return counts.n_ret_pairs >= NAME_ERA_MIN_PAIRS


# --- era verdicts (round 5, design 8a rules 1 to 5) ---------------------------------------------
@dataclass(frozen=True)
class NameFacts:
    """One judged name-era of one timeframe (it has a detector and a resolved identity)."""

    name: str
    counts: AgreementCounts
    flagged: bool  # fails the 99 percent return test
    level_class: str  # "" or a scale class
    median_log_ratio: float


@dataclass(frozen=True)
class EraCounters:
    """The era-level counters of rule 2 over the judged names of one timeframe."""

    n_judged: int
    flagged_share: float
    level_class_share: float
    shared_factor_share: float
    #: names with a detector whose identity correlation failed, over those and the judged names: a
    #: systemic price corruption decorrelates the pair and hides behind identity_unresolved
    identity_unresolved_share: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {
            "flagged_share": self.flagged_share,
            "level_class_share": self.level_class_share,
            "shared_factor_share": self.shared_factor_share,
            "identity_unresolved_share": self.identity_unresolved_share,
        }


COUNTER_NAMES = (
    "flagged_share",
    "level_class_share",
    "shared_factor_share",
    "identity_unresolved_share",
)


def era_counters(names: Sequence[NameFacts], n_identity_unresolved: int = 0) -> EraCounters:
    n = len(names)
    unresolved_share = (
        n_identity_unresolved / (n + n_identity_unresolved) if n or n_identity_unresolved else 0.0
    )
    if n == 0:
        return EraCounters(0, math.nan, math.nan, math.nan, unresolved_share)
    bins = Counter(
        round(f.median_log_ratio / SHARED_FACTOR_BIN)
        for f in names
        if math.isfinite(f.median_log_ratio) and abs(f.median_log_ratio) > SCALE_LEVEL_TOL
    )
    return EraCounters(
        n,
        sum(f.flagged for f in names) / n,
        sum(bool(f.level_class) for f in names) / n,
        (max(bins.values()) / n) if bins else 0.0,
        unresolved_share,
    )


def counter_thresholds(reference: Iterable[EraCounters]) -> dict[str, float]:
    """Per counter: the larger of 3 times its maximum over the reference eras and 2 percent."""
    refs = [c for c in reference if c.n_judged > 0]
    out: dict[str, float] = {}
    for name in COUNTER_NAMES:
        top = max((c.as_dict()[name] for c in refs), default=0.0)
        out[name] = max(COUNTER_REFERENCE_MULTIPLE * top, COUNTER_FLOOR_SHARE)
    return out


def last_print_cap_bin(reference_hists: Iterable[Mapping[int, int]]) -> int:
    """The bin holding the p99 of the last_print candidates' absolute log close difference over
    the reference period (0 when the reference holds none: nothing beyond a rounding-sized
    difference is then explained)."""
    total: Counter[int] = Counter()
    for hist in reference_hists:
        total.update(hist)
    n = sum(total.values())
    if n == 0:
        return 0
    running = 0
    for b in sorted(total):
        running += total[b]
        if running >= LAST_PRINT_CAP_QUANTILE * n:
            return b
    return max(total)


ERA_OK, ERA_OK_CONVENTION, ERA_UNRESOLVED = "ok", "ok_convention", "unresolved"
ERA_STOP, ERA_NO_DETECTOR = "stop", "no_detector"


@dataclass(frozen=True)
class EraVerdict:
    timeframe: str
    verdict: str  # ok | ok_convention | unresolved | stop | no_detector
    reasons: tuple[str, ...]
    n_judged: int
    n_matched: int
    n_ret_pairs: int
    return_residual: float
    other_share: float  # unexplained pairs over ALL matched pairs: the one basis
    n_other_carriers: int
    other_concentration: tuple[str, ...]  # carrier names flagged when at most 50 carry the excess
    counters: EraCounters
    thresholds: dict[str, float]
    class_mix: dict[str, int]
    calibration: str = ""  # the eras that calibrated the thresholds and the cap, or "self"


def judge_era(
    timeframe: str,
    names: Sequence[NameFacts],
    thresholds: Mapping[str, float],
    cap_bin: int,
    n_identity_unresolved: int = 0,
) -> EraVerdict:
    """The verdict of one era and timeframe (round 5 rules 2 to 5).

    ``stop``: any rule 2 counter above its threshold, or unexplained ``other`` above 0.5 percent of
    all matched pairs that more than 50 names carry (or that remains above 0.5 percent without
    the carriers). Otherwise a raw return residual above 0.5 percent is ``unresolved`` for 1d
    (rule 5, data driven) and ``ok_convention`` for 5m (rule 4, fully explained by size-capped
    classes); else ``ok``. No judged name is ``no_detector``, an explicit row, never a silent
    skip and never a pass. A stop outranks unresolved."""
    counters = era_counters(names, n_identity_unresolved)
    if not names:
        reasons = [
            f"{key}>{thresholds[key]:.4f}"
            for key in COUNTER_NAMES
            if counters.as_dict()[key] > thresholds[key]
        ]
        return EraVerdict(
            timeframe, ERA_STOP if reasons else ERA_NO_DETECTOR,
            tuple(reasons) or ("no_judged_names",), 0, 0, 0, math.nan, math.nan, 0, (),
            counters, dict(thresholds), {},
        )  # fmt: skip
    total = names[0].counts
    for f in names[1:]:
        total = total + f.counts
    residual = 1.0 - total.ret_share if total.n_ret_pairs else math.nan
    unexplained = total.unexplained(cap_bin)
    other_share = unexplained / total.n_matched
    carrier_facts = [
        f
        for f in names
        if f.counts.unexplained(cap_bin) > OTHER_INVESTIGATE_MAX_SHARE * f.counts.n_matched
    ]
    carriers = tuple(sorted(f.name for f in carrier_facts))
    reasons: list[str] = [
        f"{key}>{thresholds[key]:.4f}"
        for key in COUNTER_NAMES
        if counters.as_dict()[key] > thresholds[key]
    ]
    concentration: tuple[str, ...] = ()
    if other_share > OTHER_INVESTIGATE_MAX_SHARE:
        rest = total.n_matched - sum(f.counts.n_matched for f in carrier_facts)
        rest_other = unexplained - sum(f.counts.unexplained(cap_bin) for f in carrier_facts)
        if len(carriers) <= OTHER_CONCENTRATION_MAX_NAMES and (
            rest > 0 and rest_other / rest <= OTHER_INVESTIGATE_MAX_SHARE
        ):
            concentration = carriers
        else:
            reasons.append("unexplained_other")
    if all(f.level_class for f in names):
        reasons.append("empty_clean_set")
    if reasons:
        verdict = ERA_STOP
    elif residual > OTHER_INVESTIGATE_MAX_SHARE:
        verdict = ERA_UNRESOLVED if timeframe == "1d" else ERA_OK_CONVENTION
        reasons.append("return_residual_explained" if timeframe != "1d" else "close_convention")
    else:
        verdict = ERA_OK
    mix = dict(total.n_class)
    return EraVerdict(
        timeframe, verdict, tuple(reasons), counters.n_judged, total.n_matched, total.n_ret_pairs,
        residual, other_share, len(carriers), concentration, counters, dict(thresholds), mix,
    )  # fmt: skip


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


#: Runner-defined (not in the design table): a name-year level offset is "stable" when the
#: interquartile range of its per-bar log close ratio is at most 50 bp.
STABLE_LEVEL_IQR = 0.005
#: Ratios a split table can hold; a stable level factor within 0.5 percent of one reads as a
#: split-like offset (a candidate missing split), anything else as a non-split adjustment.
SPLIT_LIKE_TOL = 0.005
SPLIT_LIKE_RATIOS = tuple(
    sorted(
        {float(n) for n in range(2, 21)}
        | {1.5, 2.5, 3.5, 4 / 3, 5 / 3}
        | {1 / n for n in range(2, 21)}
        | {2 / 3, 0.4, 2 / 7, 3 / 4, 3 / 5}
    )
)
SCALE_ADJUSTMENT_LEVEL = "adjustment_level"
SCALE_SPLIT_LIKE = "split_like_level"
SCALE_LEVEL_DRIFT = "level_drift"


def split_like_ratio(factor: float) -> float | None:
    """The split ratio a level factor reads as (within 0.5 percent), else None."""
    for ratio in SPLIT_LIKE_RATIOS:
        if abs(factor / ratio - 1.0) <= SPLIT_LIKE_TOL:
            return ratio
    return None


def level_dispersion(
    massive_close_raw: np.ndarray, scale: np.ndarray, incumbent_close: np.ndarray
) -> float:
    """Interquartile range of the per-bar log close ratio (the factor is the given frozen one)."""
    if len(scale) == 0:
        raise VacuousCheckError("level_dispersion: no matched bar")
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.log(massive_close_raw / scale / incumbent_close)
    q1, q3 = np.nanpercentile(ratio, [25, 75])
    return float(q3 - q1)


def scale_class(
    median_log_ratio: float, dispersion: float, level_share: float, ret_share: float
) -> str:
    """Level classification of a name-year (lead ruling 2026-11-12, R3c; stability test 2026-11-13).

    A stable constant offset of ANY size (close level agreement under half of the bars, dispersion
    within ``STABLE_LEVEL_IQR``): ``split_like_level`` when it reads as a split ratio, a candidate
    split missing from the frozen table; ``adjustment_level`` otherwise, an incumbent non-split
    adjustment. ``level_drift``: a level disagreement under 99 percent while the returns agree at
    99 percent or better and the offset is not a stable constant. Anything else: empty."""
    if level_share < STABLE_CONSTANT_MAX_LEVEL_SHARE and dispersion <= STABLE_LEVEL_IQR:
        if split_like_ratio(math.exp(abs(median_log_ratio))) is not None:
            return SCALE_SPLIT_LIKE
        return SCALE_ADJUSTMENT_LEVEL
    if (
        level_share < NAME_ERA_AGREE_MIN
        and not math.isnan(ret_share)
        and ret_share >= NAME_ERA_AGREE_MIN
    ):
        return SCALE_LEVEL_DRIFT
    return ""


# --- identity ----------------------------------------------------------------------------------
def return_correlation(returns_a: np.ndarray, returns_b: np.ndarray) -> float:
    """Correlation of two aligned log-return series after dropping the split-sized returns (an
    absolute log return above ln 1.5 on either arm: a split is a scale event, never an identity
    one). NaN when fewer than ``IDENTITY_MIN_RETURNS`` returns remain or a series is constant."""
    keep = (
        np.isfinite(returns_a)
        & np.isfinite(returns_b)
        & (np.abs(returns_a) <= IDENTITY_SPLIT_LOG_RETURN)
        & (np.abs(returns_b) <= IDENTITY_SPLIT_LOG_RETURN)
    )
    a, b = returns_a[keep], returns_b[keep]
    if len(a) < IDENTITY_MIN_RETURNS or np.std(a) == 0 or np.std(b) == 0:
        return math.nan
    return float(np.corrcoef(a, b)[0, 1])


def identity_correlation(massive_close_adj: np.ndarray, incumbent_close: np.ndarray) -> float:
    """Correlation of daily log returns of two aligned adjusted close series (consecutive matched
    sessions), see ``return_correlation``."""
    with np.errstate(divide="ignore", invalid="ignore"):
        return return_correlation(
            np.diff(np.log(massive_close_adj)), np.diff(np.log(incumbent_close))
        )


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
#: Round 5 rule 6: outcomes are separated. ``flagged`` is a data defect, ``unresolved`` waits for a
#: witness, ``no_detector`` has no incumbent overlap to judge (a missing detector is not a failure),
#: ``unmapped`` is an active instrument with no Massive rows, ``stop`` is a systemic failure.
OUTCOME_PASS, OUTCOME_FLAGGED, OUTCOME_UNRESOLVED = "pass", "flagged", "unresolved"
OUTCOME_NO_DETECTOR, OUTCOME_NOT_LISTED = "no_detector", "not_listed_in_era"
OUTCOME_UNMAPPED, OUTCOME_STOP = "unmapped", "stop"
OUTCOMES = (
    OUTCOME_PASS,
    OUTCOME_FLAGGED,
    OUTCOME_UNRESOLVED,
    OUTCOME_NO_DETECTOR,
    OUTCOME_NOT_LISTED,
    OUTCOME_UNMAPPED,
    OUTCOME_STOP,
)
#: Outcomes an era stop does not reach: no Massive bar is loaded for them, or no detector speaks.
STOP_EXEMPT_OUTCOMES = (OUTCOME_NOT_LISTED, OUTCOME_NO_DETECTOR, OUTCOME_UNMAPPED)


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
    stop_eras: Mapping[int, str] | Iterable[int] = (),
    exempt_outcomes: Collection[str] = STOP_EXEMPT_OUTCOMES,
) -> Partition | PartialRun:
    """The complete partition of the expected (name, era) cells, or a ``PartialRun``.

    A cell in a ``stop_eras`` era carries ``stop`` (a systemic failure stops step 7 for the era;
    the mapping gives the reason, ``systemic_stop:<reason>``) whatever its own outcome, except a
    cell whose outcome is in ``exempt_outcomes`` (nothing loads for it, or no detector judged it). An outcome outside ``OUTCOMES``, or a cell judged but not
    expected, raises (a wrong partition is a bug, not a result)."""
    cells = list(dict.fromkeys(expected))
    if not cells:
        raise VacuousCheckError("close_partition: no expected cell")
    stops: dict[int, str] = (
        dict(stop_eras) if isinstance(stop_eras, Mapping) else {e: "era" for e in stop_eras}
    )
    cell_set = set(cells)
    unknown = [c for c in outcomes if c not in cell_set]
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
        if cell[1] in stops and outcome not in exempt_outcomes:
            final[cell] = (OUTCOME_STOP, f"systemic_stop:{stops[cell[1]]}")
        else:
            final[cell] = (outcome, reason)
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
    case with only the Alpaca corroborator, or none, is unresolved. ``massive_continuity`` is
    Massive, not a third party: when it decides, it can call a Massive defect but leaves an
    incumbent defect unresolved. ``ibkr_1d_official_close`` is ignored in a Massive-internal
    dispute (it would be circular there)."""
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
        if sides == {"incumbent"}:
            verdict = VERDICT_MASSIVE_DEFECT
        elif kind == "massive_continuity":
            verdict = VERDICT_UNRESOLVED
        else:
            verdict = VERDICT_INCUMBENT_DEFECT
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


# --- ledger witnesses with no new data ---------------------------------------------------------
def frozen_split_witness(
    level_factor: float, splits_in_window: Sequence[tuple[str, float]], tol: float = 0.01
) -> Witness | None:
    """The frozen corporate-action list as a witness for one disputed name-era. ``level_factor`` is
    the residual Massive / incumbent after Massive is divided by the frozen splits;
    ``splits_in_window`` holds (effective date, factor). Dividing by a split of factor f moves the
    bars up to its effective date onto the new scale, so an incumbent that lacks the split leaves
    a residual of 1/f: the dated record explains the dispute and supports Massive. A residual of f
    points the other way (Massive a split factor above the incumbent after the division, which no
    missing split explains), so the record supports the incumbent there. Neither within ``tol``:
    no witness (never invented)."""
    for effective, factor in splits_in_window:
        for candidate, supports in ((1.0 / factor, "massive"), (factor, "incumbent")):
            if abs(level_factor / candidate - 1.0) <= tol:
                return Witness(
                    "filing_dated_corporate_action",
                    supports,
                    f"frozen corporate_action split {effective} x{factor}",
                )
    return None


def massive_tape_witness(
    close_before: float, close_after: float, factor: float, effective: str, tol: float = 0.02
) -> Witness | None:
    """Massive's own continuity witness for a recorded split: Massive's unadjusted tape steps by
    the split factor across its effective date (close on the last old-scale session over the close
    on the next, within ``tol``). A tape that steps by the factor supports the recorded split; it
    corroborates and never alone convicts the incumbent (see ``ledger_verdict``)."""
    if not (close_before > 0 and close_after > 0):
        return None
    if abs((close_before / close_after) / factor - 1.0) <= tol:
        return Witness(
            "massive_continuity", "massive", f"massive tape steps x{factor} across {effective}"
        )
    return None
