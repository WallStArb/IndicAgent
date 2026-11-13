"""Massive load checks, name-level half (admission design section 8a, stage C): pure math.

Companion of ``massive_load_checks`` (the systemic stages). Pure Ring 1: arrays and dataclasses in,
verdicts out. The runner is ``scripts/ops/bars/ops_massive_load_checks.py``.

Rules quoted from the design table. The thresholds here are PRE-REGISTERED constants of a one-shot
admission gate, not APR parameters (an operator-tunable gate threshold invites tuning after the
results are seen): they live in the design document and change only by a dated amendment.

- A bar agrees when ``abs(Massive / factor - incumbent) <= half the incumbent's price increment +
  1 bp of the incumbent price``. The verdict basis is the CLOSE (the design's price-agreement row
  names no field; the 1d census row names all of O, H, L, C separately, so the census reads
  ``n_agree_all`` and the verdicts read ``n_agree``). The factor is the cumulative
  split scale from the FROZEN corporate-action list, never fitted from the compared series.
- 99 percent of consecutive matched return pairs per name-era (level agreement is reported, not
  gated; design 8a, sixth review). Disagreements are
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
from dataclasses import dataclass, field, replace
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
MIN_JUDGED_NAMES = 20  # judged names an (era, timeframe) needs for counters and verdicts
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
CLASS_CLOSE_DEFINITION = "close_definition"  # 1d: incumbent close is Massive's last RTH 5m close
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
    #: level statistics of the name-era (NaN / False on a sum of several): median and interquartile
    #: range of the per-bar log close ratio, the stable-offset predicate and an in-era level break
    median_log: float = math.nan
    iqr: float = math.nan
    stable_offset: bool = False
    break_step: float = math.nan
    break_pre_median: float = math.nan  # median log ratio before the break (Massive / incumbent)
    #: definition witness (1d, design 8a sixth review R4): over the matched days with a Massive last
    #: RTH 5m close, the days where the incumbent close matches the day-file close and the days
    #: where it matches the last-trade close (``WITNESS_REL_TOL`` median-relative test)
    n_alt: int = 0
    n_alt_dayfile: int = 0
    n_alt_last: int = 0
    #: the label each ``close_definition`` bar would have had without that class, with the
    #: last_print size bins of those that would have been last_print: what an unwitnessed era
    #: restores (``fold_definition``)
    def_fallback: dict[str, int] = field(default_factory=dict)
    def_fallback_hist: dict[int, int] = field(default_factory=dict)

    def explained_bars(self, label: str, cap_bin: int) -> int:
        """Bars of one explained class; ``last_print`` only within the size cap."""
        n = self.n_class.get(label, 0)
        if label == CLASS_LAST_PRINT:
            n -= sum(c for b, c in self.lp_hist.items() if b > cap_bin)
        return n

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
            n_alt=self.n_alt + other.n_alt,
            n_alt_dayfile=self.n_alt_dayfile + other.n_alt_dayfile,
            n_alt_last=self.n_alt_last + other.n_alt_last,
            def_fallback=dict(Counter(self.def_fallback) + Counter(other.def_fallback)),
            def_fallback_hist=dict(
                Counter(self.def_fallback_hist) + Counter(other.def_fallback_hist)
            ),
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


def _rolling_median(values: np.ndarray, window: int) -> np.ndarray:
    """Centred rolling median (edge-padded, NaN ignored): the local level of a drifting ratio."""
    if len(values) == 0:
        return values
    half = window // 2
    padded = np.pad(values, half, mode="edge")
    view = np.lib.stride_tricks.sliding_window_view(padded, 2 * half + 1)
    with np.errstate(all="ignore"):
        out: np.ndarray = np.nanmedian(view, axis=1)
    return out


def classify_disagreements(
    massive_adj: Ohlc,
    incumbent: Ohlc,
    massive_prev_adj: Ohlc | None,
    massive_next_adj: Ohlc | None,
    increment: float,
    scale_centers: Sequence[float],
    scale_all: bool,
    last_bucket: np.ndarray | None = None,
    last_trade_close: np.ndarray | None = None,
) -> np.ndarray:
    """A class label per matched bar (object array; '' where the bar agrees).

    ``massive_adj`` is the factor-adjusted Massive series aligned with the incumbent;
    ``massive_prev_adj`` / ``massive_next_adj`` the same series one bar earlier / later in Massive's
    own order (NaN where absent), for the time-shift reading; ``last_bucket`` flags the final
    bucket of a session (the closing auction and late prints land there). Order of reading
    (round 5 rule 3, rounding first): rounding (within 1.5 increments plus 1 bp on every field),
    scale (the name carries a stable constant level offset, ``stable_offset``, and this bar's close
    ratio sits within 0.5 percent of the name's median: it explains its bars before any look-alike
    class), time_shift (all four fields agree with the previous or the next Massive bar),
    last_print (the Massive close lies inside the incumbent bar's high-low range, and open, high
    and low agree, or the bar is the session's last bucket with the open agreeing), else other. last_print is a CANDIDATE here: its size cap (the reference period's p99 of the
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
    # a stable offset (one centre), a split-sized level break (the levels before and after it) or
    # a level drift (every disagreeing bar) is the scale class that level_class_share measures
    scale = np.zeros(n, dtype=bool)
    if (
        scale_all
    ):  # a drift name: within tolerance of the LOCAL drift level, larger errors stay other
        scale |= np.abs(bar_log - _rolling_median(bar_log, DRIFT_WINDOW)) <= SCALE_CLASS_BAR_TOL
    for centre in scale_centers:
        scale |= np.abs(bar_log - centre) <= SCALE_CLASS_BAR_TOL
    # the incumbent close is Massive's last regular-hours trade (its definition of the close)
    definition = np.zeros(n, dtype=bool)
    if last_trade_close is not None:
        definition = np.abs(last_trade_close - incumbent[3]) <= (
            HALF_INCREMENT * increment + WITNESS_REL_TOL * np.abs(incumbent[3])
        )
    pending = ~agree
    take = pending & scale  # a stable offset explains its bars before any look-alike class
    labels[take] = CLASS_SCALE
    pending &= ~take
    take = pending & definition
    labels[take] = CLASS_CLOSE_DEFINITION
    pending &= ~take
    for label, mask in (
        (CLASS_ROUNDING, rounding),
        (CLASS_TIME_SHIFT, shift),
        (CLASS_LAST_PRINT, last_print),
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
    massive_prev_scale: np.ndarray | None = None,
    massive_next_scale: np.ndarray | None = None,
    last_trade_close: np.ndarray | None = None,
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
    # each neighbour bar is divided by its OWN split scale (a split can fall between two bars)
    prev_scale = scale if massive_prev_scale is None else massive_prev_scale
    next_scale = scale if massive_next_scale is None else massive_next_scale
    prev = tuple(m / prev_scale for m in massive_prev_raw) if massive_prev_raw is not None else None
    nxt = tuple(m / next_scale for m in massive_next_raw) if massive_next_raw is not None else None
    with np.errstate(divide="ignore", invalid="ignore"):
        log_ratio = np.log(adj[3] / incumbent[3])
    median_log, iqr = _median_iqr(log_ratio)
    level_share = float(fields[3].mean())
    tolerance_log = (
        HALF_INCREMENT * increment / float(np.nanmedian(np.abs(incumbent[3]))) + PRICE_REL_TOL
    )
    stable = is_stable_offset(level_share, iqr, median_log, tolerance_log)
    # the break test only runs when the level disagrees somewhere (benign names never reach it)
    break_step, break_pre = (
        level_break_step(log_ratio) if level_share < NAME_ERA_AGREE_MIN else (math.nan, math.nan)
    )
    pairs = pair_ok = bars = bar_ok = 0
    if massive_pos is not None and incumbent_pos is not None:
        pairs, pair_ok, bars, bar_ok = return_agreement(
            adj, incumbent, massive_pos, incumbent_pos, increment  # type: ignore[arg-type]
        )
    level = scale_class(
        median_log, stable, level_share, pair_ok / pairs if pairs else math.nan, break_step
    )
    centres = (
        [median_log]
        if stable
        else [break_pre, break_pre + break_step] if math.isfinite(break_step) else []
    )
    labels = classify_disagreements(
        adj,
        incumbent,
        prev,
        nxt,
        increment,
        centres,
        level == SCALE_LEVEL_DRIFT,
        last_bucket,  # type: ignore[arg-type]
        None if last_trade_close is None else last_trade_close / scale,
    )
    disagree = ~fields[3]
    fallback: dict[str, int] = {}
    fallback_hist: dict[int, int] = {}
    if last_trade_close is not None and (labels[disagree] == CLASS_CLOSE_DEFINITION).any():
        plain = classify_disagreements(
            adj,
            incumbent,
            prev,
            nxt,
            increment,
            centres,
            level == SCALE_LEVEL_DRIFT,
            last_bucket,  # type: ignore[arg-type]
            None,
        )
        was = disagree & (labels == CLASS_CLOSE_DEFINITION)
        fallback = dict(Counter(str(x) for x in plain[was]))
        fallback_hist = last_print_histogram(np.where(was, plain, ""), adj[3], incumbent[3])
    classes = Counter(str(x) for x in labels[disagree])
    hist = last_print_histogram(np.where(disagree, labels, ""), adj[3], incumbent[3])
    n_alt = n_alt_day = n_alt_last = 0
    if last_trade_close is not None:
        have = np.isfinite(last_trade_close)
        tol = HALF_INCREMENT * increment + WITNESS_REL_TOL * np.abs(incumbent[3])
        day_ok = np.abs(adj[3] - incumbent[3]) <= tol
        last_ok = np.abs(last_trade_close / scale - incumbent[3]) <= tol
        n_alt = int(have.sum())
        n_alt_day = int((have & day_ok).sum())
        n_alt_last = int((have & last_ok).sum())
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
        median_log,
        iqr,
        stable,
        break_step,
        break_pre,
        n_alt,
        n_alt_day,
        n_alt_last,
        fallback,
        fallback_hist,
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
    #: DECORRELATED names (correlation computed on enough returns, under 0.9), over those and the
    #: judged names; thin-evidence names never count. A systemic price corruption decorrelates the
    #: pair and would otherwise hide behind the unresolved identity
    identity_unresolved_share: float = 0.0
    #: explained classes are explained AT THE REFERENCE RATE: the share of judged names where the
    #: class covers more than 0.5 percent of the name's bars (``scale`` is level_class_share)
    time_shift_share: float = 0.0
    rounding_share: float = 0.0
    last_print_share: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {name: getattr(self, name) for name in COUNTER_NAMES}


COUNTER_NAMES = (
    "flagged_share",
    "level_class_share",
    "shared_factor_share",
    "identity_unresolved_share",
    "time_shift_share",
    "rounding_share",
    "last_print_share",
)
EXPLAINED_COUNTERS = {
    "time_shift_share": CLASS_TIME_SHIFT,
    "rounding_share": CLASS_ROUNDING,
    "last_print_share": CLASS_LAST_PRINT,
}


def era_counters(
    names: Sequence[NameFacts], n_identity_unresolved: int = 0, cap_bin: int = 0
) -> EraCounters:
    """The rule 2 counters. A name's return-agreement failure counts toward ``flagged_share`` only
    when its disagreement is UNEXPLAINED (more than 0.5 percent of its pairs fall outside the
    declared conventions at ``cap_bin``), so the counter measures what the stop rule measures and a
    close-convention era reaches ``unresolved`` instead of stopping."""
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
        sum(f.flagged and _unexplained(f, cap_bin) for f in names) / n,
        sum(bool(f.level_class) for f in names) / n,
        (max(bins.values()) / n) if bins else 0.0,
        unresolved_share,
        *(
            sum(
                f.counts.explained_bars(label, cap_bin)
                > OTHER_INVESTIGATE_MAX_SHARE * f.counts.n_matched
                for f in names
            )
            / n
            for label in EXPLAINED_COUNTERS.values()
        ),
    )


def definition_shares(names: Sequence[NameFacts]) -> tuple[float, float]:
    """(day-file match share, last-trade match share) of the incumbent close over the judged
    names' days that have a Massive last RTH 5m close; NaN without such a day."""
    n = sum(f.counts.n_alt for f in names)
    if n == 0:
        return math.nan, math.nan
    return (
        sum(f.counts.n_alt_dayfile for f in names) / n,
        sum(f.counts.n_alt_last for f in names) / n,
    )


def close_definition_witnessed(names: Sequence[NameFacts]) -> bool:
    """The incumbent's 1d close follows Massive's last regular-hours trade rather than the
    official day-file close: the last-trade match exceeds the day-file match by
    ``DEFINITION_MARGIN``. Calibrated on 2014 to 2026, where the day-file match is 90 to 99
    percent and the last-trade match 30 to 40 (a margin near -0.55), so no reference era trips it;
    2006 reads +0.50."""
    day, last = definition_shares(names)
    return not math.isnan(day) and last - day > DEFINITION_MARGIN


def fold_definition(f: NameFacts) -> NameFacts:
    """Without a witness each close_definition bar returns to the label it would have had without
    that class (stored with the part), so an unwitnessed era reads exactly as the classifier
    without the witness would."""
    n = f.counts.n_class.get(CLASS_CLOSE_DEFINITION, 0)
    if not n:
        return f
    mix = dict(f.counts.n_class)
    mix.pop(CLASS_CLOSE_DEFINITION)
    for label, count in f.counts.def_fallback.items():
        mix[label] = mix.get(label, 0) + count
    hist = dict(Counter(f.counts.lp_hist) + Counter(f.counts.def_fallback_hist))
    return replace(f, counts=replace(f.counts, n_class=mix, lp_hist=hist))


def _unexplained(f: NameFacts, cap_bin: int) -> bool:
    return f.counts.unexplained(cap_bin) > OTHER_INVESTIGATE_MAX_SHARE * f.counts.n_matched


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
    cap_bin: int = 0  # the last_print size cap the era was judged at (for diagnostics)
    close_definition_witnessed: bool = False
    share_dayfile: float = math.nan  # definition witness shares (1d), both carried in the era table
    share_last_trade: float = math.nan


def judge_era(
    timeframe: str,
    names: Sequence[NameFacts],
    thresholds: Mapping[str, float],
    cap_bin: int,
    n_identity_unresolved: int = 0,
    definition_witnessed: bool = False,
) -> EraVerdict:
    """The verdict of one era and timeframe (round 5 rules 2 to 5).

    ``stop``: any rule 2 counter above its threshold, or unexplained ``other`` above 0.5 percent of
    all matched pairs that more than 50 names carry (or that remains above 0.5 percent without
    the carriers). Otherwise a raw return residual above 0.5 percent (on 1d also a capped
    last_print share above the reference rate) is ``unresolved`` for 1d
    (rule 5, data driven) and ``ok_convention`` for 5m (rule 4, fully explained by size-capped
    classes); else ``ok``. No judged name is ``no_detector``, an explicit row, never a silent
    skip and never a pass. A stop outranks unresolved."""
    counters = era_counters(names, n_identity_unresolved, cap_bin)
    thin = len(names) < MIN_JUDGED_NAMES
    if thin:
        # too few judged names for the counters, the residual and empty_clean_set; only a
        # decorrelation backed by enough evidence (decorrelated plus judged names) can stop it
        enough = len(names) + n_identity_unresolved >= MIN_JUDGED_NAMES
        stops = (
            [f"identity_unresolved_share>{thresholds['identity_unresolved_share']:.4f}"]
            if enough
            and counters.identity_unresolved_share > thresholds["identity_unresolved_share"]
            else []
        )
        verdict = ERA_STOP if stops else ERA_NO_DETECTOR if not names else ERA_UNRESOLVED
        reasons = tuple(stops) or (("no_judged_names",) if not names else ("thin_era",))
        n_matched = sum(f.counts.n_matched for f in names)
        return EraVerdict(
            timeframe, verdict, reasons, len(names), n_matched,
            sum(f.counts.n_ret_pairs for f in names), math.nan, math.nan, 0, (),
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
    over = [key for key in COUNTER_NAMES if counters.as_dict()[key] > thresholds[key]]
    # on 1d a capped last_print above the reference rate is a which-side-is-right question (the
    # day-file close is the official auction print): it needs a third witness, so it is the close
    # convention (unresolved), not a stop. A real close defect lands beyond the cap as ``other``
    # and a date shift trips time_shift_share, both of which still stop.
    convention = timeframe == "1d" and "last_print_share" in over
    reasons: list[str] = [
        f"{key}>{thresholds[key]:.4f}"
        for key in over
        if not (convention and key == "last_print_share")
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
    elif definition_witnessed and timeframe == "1d":
        # the incumbent's close is Massive's last regular-hours trade, the day file the official
        # close: a definition difference, never a stop (the served policy takes Massive for the era)
        verdict = ERA_UNRESOLVED
        reasons.append("close_definition_witnessed")
    elif convention or residual > OTHER_INVESTIGATE_MAX_SHARE:
        verdict = ERA_UNRESOLVED if timeframe == "1d" else ERA_OK_CONVENTION
        reasons.append("return_residual_explained" if timeframe != "1d" else "close_convention")
    else:
        verdict = ERA_OK
    mix = dict(total.n_class)
    day_share, last_share = definition_shares(names) if timeframe == "1d" else (math.nan, math.nan)
    return EraVerdict(
        timeframe, verdict, tuple(reasons), counters.n_judged, total.n_matched, total.n_ret_pairs,
        residual, other_share, len(carriers), concentration, counters, dict(thresholds), mix,
        close_definition_witnessed=definition_witnessed and timeframe == "1d",
        share_dayfile=day_share, share_last_trade=last_share,
    )  # fmt: skip


# --- scale factor ------------------------------------------------------------------------------
def _median_iqr(log_ratio: np.ndarray) -> tuple[float, float]:
    """Median and interquartile range of a per-bar log close ratio (NaN bars ignored)."""
    q1, med, q3 = np.nanpercentile(log_ratio, [25, 50, 75])
    return float(med), float(q3 - q1)


def is_stable_offset(
    level_share: float, dispersion: float, median_log: float, tolerance_log: float
) -> bool:
    """The one predicate of a stable constant level offset: most bars sit out of tolerance (level
    agreement under half), the per-bar log ratio barely moves, and its median exceeds the per-bar
    agreement tolerance (half the increment over the price level, plus 1 bp): a median near zero
    with noisy bars is not an offset, a 5 bp offset on a 250 dollar name is."""
    return (
        level_share < STABLE_CONSTANT_MAX_LEVEL_SHARE
        and dispersion <= STABLE_LEVEL_IQR
        and abs(median_log) > tolerance_log
    )


def counts_as_systemic(scale_class_: str, median_log_ratio: float, break_step: float) -> bool:
    """Whether a name-era's level class feeds the era counters (the one materiality rule): a stable
    offset only when it exceeds the scale tolerance (a 5 bp offset is listed, not systemic);
    ``level_drift`` and an in-era level break always, since their median can sit near zero."""
    if not scale_class_:
        return False
    return (
        scale_class_ == SCALE_LEVEL_DRIFT
        or math.isfinite(break_step)
        or abs(median_log_ratio) > SCALE_LEVEL_TOL
    )


def level_break_step(log_ratio: np.ndarray) -> tuple[float, float]:
    """The step of an in-era level break that reads as a split, else NaN.

    Candidate breaks on a grid of ``STEP_GRID`` points (each side at least
    ``STEP_MIN_SEGMENT_SHARE`` of the bars and ``STEP_MIN_SEGMENT_BARS``): the step is the median
    of the per-bar log close ratio after the break minus before it. It counts when both sides are
    stable (interquartile range within ``STABLE_LEVEL_IQR``), the step exceeds the scale tolerance
    and its ratio matches a split within ``SPLIT_LIKE_TOL``: a split missing from the frozen table
    persists to the end (or the start) of the era. The largest such step wins. Returns
    (step, median before the break): the pre-break residual is the Massive / incumbent level the
    frozen split witness compares against."""
    r = log_ratio[np.isfinite(log_ratio)]
    r = r[:: max(1, len(r) // STEP_MAX_POINTS)]
    n = len(r)
    seg = max(STEP_MIN_SEGMENT_BARS, math.ceil(STEP_MIN_SEGMENT_SHARE * n))
    if n < 2 * seg:
        return math.nan, math.nan
    best = pre = math.nan
    for k in np.unique(np.linspace(seg, n - seg, STEP_GRID).astype(int)):
        before, after = r[:k], r[k:]
        med_b, iqr_b = _median_iqr(before)
        med_a, iqr_a = _median_iqr(after)
        step = med_a - med_b
        if (
            abs(step) > SCALE_LEVEL_TOL
            and iqr_b <= STABLE_LEVEL_IQR
            and iqr_a <= STABLE_LEVEL_IQR
            and split_like_ratio(math.exp(abs(step))) is not None
            and (math.isnan(best) or abs(step) > abs(best))
        ):
            best, pre = step, med_b
    return best, pre


#: A level offset is "stable" when the interquartile range of the per-bar log close ratio is at
#: most 50 bp (design 8a, amendment 2026-11-13 constants table).
STABLE_LEVEL_IQR = 0.005
WITNESS_REL_TOL = 2e-4  # median-relative close match of the definition witness (2 bp)
DEFINITION_MARGIN = 0.25  # last-trade match share must exceed the day-file share by this
DRIFT_WINDOW = 21  # bars of the rolling median that defines a drift name's local level
WITNESS_TOL = 0.01  # relative match of a residual to a split product (frozen-list witness)
TAPE_WITNESS_TOL = 0.02  # relative match of Massive's tape step to the recorded split factor
WITNESS_MAX_SPLITS = 16  # subsets of the frozen splits are enumerated up to this many
STEP_MIN_SEGMENT_SHARE = 0.05  # the shorter side of a level break: share of the bars ...
STEP_MIN_SEGMENT_BARS = 5  # ... and at least this many bars
STEP_GRID = 64  # candidate break points per name-era
STEP_MAX_POINTS = 2000  # the series is stride-thinned to this length (bounds cost, not the verdict)
#: Ratios a split table can hold; a stable level factor within 0.5 percent of one reads as a
#: split-like offset (a candidate missing split), anything else as a non-split adjustment.
SPLIT_LIKE_TOL = 0.005
#: Ratios above 1 only: ``split_like_ratio`` reads exp(|log factor|), so a reverse split is its
#: reciprocal's forward ratio.
SPLIT_LIKE_RATIOS = tuple(sorted({float(n) for n in range(2, 21)} | {1.5, 2.5, 3.5, 4 / 3, 5 / 3}))
SCALE_ADJUSTMENT_LEVEL = "adjustment_level"
SCALE_SPLIT_LIKE = "split_like_level"
SCALE_LEVEL_DRIFT = "level_drift"


def split_like_ratio(factor: float) -> float | None:
    """The split ratio a level factor reads as (within 0.5 percent), else None."""
    for ratio in SPLIT_LIKE_RATIOS:
        if abs(factor / ratio - 1.0) <= SPLIT_LIKE_TOL:
            return ratio
    return None


def scale_class(
    median_log_ratio: float,
    stable_offset: bool,
    level_share: float,
    ret_share: float,
    break_step: float = math.nan,
) -> str:
    """Level classification of a name-year (lead ruling 2026-11-12, R3c; stability test 2026-11-13).

    A stable constant offset (``is_stable_offset``, evaluated once by ``price_agreement``):
    ``split_like_level`` when it reads as a split ratio, a candidate
    split missing from the frozen table; ``adjustment_level`` otherwise, an incumbent non-split
    adjustment. An in-era level break that reads as a split (``level_break_step`` finite) is
    ``split_like_level`` too: a split missing from the frozen table, wherever it falls in the era.
    ``level_drift``: a level disagreement under 99 percent while the returns agree at 99 percent
    or better, with neither a stable constant nor such a step (a small drift). Anything else:
    empty."""
    if stable_offset:
        if split_like_ratio(math.exp(abs(median_log_ratio))) is not None:
            return SCALE_SPLIT_LIKE
        return SCALE_ADJUSTMENT_LEVEL
    if math.isfinite(break_step):
        return SCALE_SPLIT_LIKE
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
    one). NaN when fewer than ``IDENTITY_MIN_RETURNS`` returns remain (thin); a constant series
    with enough returns correlates at 0 (decorrelated) unless both arms are flat and identical
    (agreement)."""
    keep = (
        np.isfinite(returns_a)
        & np.isfinite(returns_b)
        & (np.abs(returns_a) <= IDENTITY_SPLIT_LOG_RETURN)
        & (np.abs(returns_b) <= IDENTITY_SPLIT_LOG_RETURN)
    )
    a, b = returns_a[keep], returns_b[keep]
    if len(a) < IDENTITY_MIN_RETURNS:
        return math.nan  # thin: the only way an identity correlation is missing
    flat_a, flat_b = np.std(a) == 0, np.std(b) == 0
    if flat_a and flat_b:
        return 1.0 if np.array_equal(a, b) else 0.0  # both flat and identical: agreement
    if flat_a or flat_b:
        return 0.0  # one flat (stale) side is a disagreement, not missing evidence
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
    supports: str  # "massive", "incumbent", or "incumbent_overscaled" (frozen residual of f)
    citation: str
    splits: tuple[str, ...] = ()  # effective dates of the frozen splits a frozen witness cites


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
    incumbent_rescaled: bool = False,
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
        if sides == {"incumbent_overscaled"}:
            # the incumbent was divided once too many: an incumbent or rescale problem, never a
            # Massive defect; when rule 7 rescaled that route the calendar_audit row is suspect
            if incumbent_rescaled:
                return LedgerRow(
                    name, span, claimed_defect, tuple(witnesses), VERDICT_UNRESOLVED,
                    session_id, "rescale_conflict",
                )  # fmt: skip
            verdict = VERDICT_INCUMBENT_DEFECT
        elif sides == {"incumbent"}:
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
    level_factor: float, splits_after: Sequence[tuple[str, float]], tol: float = WITNESS_TOL
) -> Witness | None:
    """The frozen corporate-action list as a witness for one disputed name-era. ``level_factor`` is
    the residual Massive / incumbent after Massive is divided by the frozen splits (for an in-era
    break, the pre-break residual); ``splits_after`` holds (effective date, factor) of the frozen
    splits that explain the cumulative scale of the era's bars: every one on or after the era's
    first session. Dividing by a split of factor f moves the bars up to its effective date onto
    the new scale, so an incumbent that lacks the split leaves a residual of 1/f: the dated record
    explains the dispute and supports Massive. A residual of f means the incumbent was divided once too many
    (``incumbent_overscaled``), never a Massive defect. The residual is tested against the product of EVERY non-empty
    subset of the splits (an incumbent lacking some of them; the count per name is small). The
    witness is cited only when exactly one subset matches: several matching subsets are
    ambiguous and give no witness, as does no match (never invented)."""
    ordered = sorted(splits_after)
    if len(ordered) > WITNESS_MAX_SPLITS:
        return None
    matches: list[tuple[tuple[tuple[str, float], ...], float, str]] = []
    for mask in range(1, 1 << len(ordered)):
        subset = tuple(ordered[i] for i in range(len(ordered)) if mask >> i & 1)
        product = math.prod(f for _, f in subset)
        for candidate, supports in ((1.0 / product, "massive"), (product, "incumbent_overscaled")):
            if abs(level_factor / candidate - 1.0) <= tol:
                matches.append((subset, product, supports))
    if len(matches) != 1:
        return None
    subset, product, supports = matches[0]
    if len(subset) == 1:
        effective, factor = subset[0]
        citation = f"frozen corporate_action split {effective} x{factor}"
    else:
        citation = (
            "frozen corporate_action splits "
            + ", ".join(f"{e} x{f}" for e, f in subset)
            + f" (product x{product})"
        )
    return Witness("filing_dated_corporate_action", supports, citation, tuple(e for e, _ in subset))


def massive_tape_witness(
    close_before: float,
    close_after: float,
    factor: float,
    effective: str,
    tol: float = TAPE_WITNESS_TOL,
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
