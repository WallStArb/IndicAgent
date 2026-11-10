"""Level seams: price steps in an unadjusted vendor series that no recorded split explains.

Massive admission step 4, the second gate (admission design section 5): a scan of the Massive
day archive for adjacent-session close steps, each judged by LEVEL over the spans either side and
never by the junction step alone (the todo 592 rule: a junction can look flat while a whole span
sits at the wrong level, and a one-bar print can step twice without moving the level).

A series is one ticker string's sessions in order (or an instrument's sessions stitched across its
renames by the caller). ``find_level_steps`` turns it into level steps:

1. A junction is a session whose log close step from the series' previous observation exceeds
   ``junction_cut``. A junction the next observation reverses (their sum within ``transient_tol``)
   is a one-bar print, not a seam; both junctions are dropped and counted.
2. Each remaining junction's level step is ln(median close of up to ``level_sessions``
   observations from the junction on / median of up to ``level_sessions`` before it), each side
   bounded by the neighbouring junctions so no second step enters a median. A junction whose
   level step is under ``junction_cut`` (the level came back) is transient and dropped, and the
   survivors' spans are measured again without it.

``classify_step`` then reads one level step, in this order:

- ``explained``: recorded splits whose first new-scale session lies within ``explain_sessions`` of
  the junction (a presence gap widens the window over the gap) and whose combined factor f reads
  the level step as unadjusted (``corporate_actions.scale_step``: -ln f within rel_tol * |ln f|).
  Each source (vendor endpoint, our corporate_action) is tried on its own, so a split recorded by
  both is never multiplied twice.
- ``identity_suspect``: the series' string changed hands across the junction: an identity break
  (a list date, an events-chain boundary, a delisting of the string) lies in (previous
  observation, junction], or the presence gap exceeds ``max_halt_gap`` sessions. A reused ticker
  steps without any split; it is never a missing-split finding.
- ``thin_halted``: a presence gap of more than ``halt_gap`` sessions, a side with fewer than half
  of ``level_sessions`` observations, or a median volume under ``thin_volume`` shares.
- ``unexplained``: anything else, with the simplest recognised split ratio the level step reads as
  and its residual (the candidate missing split), the volume step (a split multiplies share volume by f), and whether a
  recorded split nearby fails to explain it (a ratio disagreement witness).

``tape_reading`` answers the converse for one recorded split: does the vendor's own unadjusted
tape step by its factor at its date (``tape_step``), stay flat (``tape_flat``), step by something
else (``tape_conflict``), or not cover it (``no_tape``)?

Pure: arrays in, records out; thresholds are parameters (the caller's definitional constants and
APR), no I/O.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

import numpy as np

from src.intelligence.bars.corporate_actions import ScaleStep, SplitRatioRule, scale_step

SeamClass = Literal["explained", "identity_suspect", "thin_halted", "unexplained"]
SEAM_CLASSES: tuple[SeamClass, ...] = (
    "explained",
    "identity_suspect",
    "thin_halted",
    "unexplained",
)
TapeReading = Literal["tape_step", "tape_flat", "tape_conflict", "no_tape"]


@dataclass(frozen=True)
class SeamParams:
    """The detector's cuts. Definitions, not tunables: changing one changes the classified
    corpus, so the report records them beside the APR values."""

    junction_cut: float  # |ln close step| a junction exceeds
    transient_tol: float  # |step + next step| at or under it: a one-bar print
    level_sessions: int  # observations per side in a level median
    explain_sessions: int  # a recorded split this many sessions from the junction may explain it
    halt_gap: int  # missing sessions above this: halted
    max_halt_gap: int  # missing sessions above this: the string may have changed hands
    thin_volume: float  # median shares per session under this: thin
    rel_tol: float  # threshold.split_continuity.rel_tol: a step reads as split f
    ratio_rule: SplitRatioRule  # the recognised split ratios a candidate is snapped to


@dataclass(frozen=True)
class LevelStep:
    """One level step of a series: positions index the series' arrays."""

    position: int  # the junction's observation (first on the new level)
    session: int  # its session ordinal
    prev_session: int  # the previous observation's session ordinal
    junction_step: float  # ln(close / previous close)
    level_step: float  # ln(median after / median before), span-bounded
    gap: int  # sessions missing between the two observations
    n_before: int
    n_after: int
    volume_step: float | None  # ln(median volume after / before); None when a side has none
    median_volume: float


def find_level_steps(
    sessions: np.ndarray, close: np.ndarray, volume: np.ndarray, params: SeamParams
) -> tuple[list[LevelStep], int]:
    """The level steps of one series and the number of junctions dropped as one-bar prints.

    sessions are strictly increasing ordinals, close strictly positive. Raises otherwise."""
    n = len(close)
    if not (len(sessions) == n == len(volume)):
        raise ValueError("sessions, close and volume must be parallel")
    if n < 2:
        return [], 0
    if np.any(np.diff(sessions) <= 0):
        raise ValueError("sessions must be strictly increasing")
    if not np.all(np.isfinite(close)) or np.any(close <= 0):
        raise ValueError("close must be finite and positive")
    step = np.diff(np.log(close))  # step[i - 1] is the junction into position i
    junctions = np.flatnonzero(np.abs(step) > params.junction_cut) + 1
    printed: set[int] = set()
    for a, b in zip(junctions[:-1], junctions[1:], strict=True):
        if b == a + 1 and abs(step[a - 1] + step[b - 1]) <= params.transient_tol:
            printed.update((int(a), int(b)))
    kept = [int(j) for j in junctions if int(j) not in printed]
    k = params.level_sessions

    def sides(idx: int, pos: int) -> tuple[slice, slice]:
        lo = kept[idx - 1] if idx else 0
        hi = kept[idx + 1] if idx + 1 < len(kept) else n
        return slice(max(lo, pos - k), pos), slice(pos, min(hi, pos + k))

    def level_of(idx: int, pos: int) -> float:
        before, after = sides(idx, pos)
        return math.log(float(np.median(close[after])) / float(np.median(close[before])))

    # A junction whose level comes back is transient; it is dropped and the survivors' spans are
    # measured again without it, so a dropped junction never truncates a real step's side.
    while True:
        survivors = [p for i, p in enumerate(kept) if abs(level_of(i, p)) > params.junction_cut]
        if len(survivors) == len(kept):
            break
        kept = survivors
    out: list[LevelStep] = []
    for idx, pos in enumerate(kept):
        before, after = sides(idx, pos)
        level = level_of(idx, pos)
        vol_b, vol_a = volume[before], volume[after]
        vb, va = float(np.median(vol_b)), float(np.median(vol_a))
        out.append(
            LevelStep(
                position=pos,
                session=int(sessions[pos]),
                prev_session=int(sessions[pos - 1]),
                junction_step=round(float(step[pos - 1]), 6),
                level_step=round(level, 6),
                gap=int(sessions[pos] - sessions[pos - 1] - 1),
                n_before=len(vol_b),
                n_after=len(vol_a),
                volume_step=round(math.log(va / vb), 6) if va > 0 and vb > 0 else None,
                median_volume=float(np.median(np.concatenate([vol_b, vol_a]))),
            )
        )
    return out, len(printed)


@dataclass(frozen=True)
class RecordedFactor:
    """A recorded split as the detector reads it: its first new-scale session and factor."""

    first_new_session: int
    factor: float  # old-scale / new-scale price
    source: str  # who recorded it (the vendor endpoint, corporate_action)
    ref: str  # its id, for the evidence column


@dataclass(frozen=True)
class SeamVerdict:
    seam_class: SeamClass
    reason: str
    explained_by: tuple[str, ...] = ()  # refs of the explaining splits
    implied_ratio: float | None = None  # simplest recognised split ratio (old/new price)
    ratio_residual: float | None = None  # level step + ln(implied ratio)
    volume_agrees: bool | None = None  # the volume step reads as the implied ratio
    nearby_unexplaining: tuple[str, ...] = ()  # refs of recorded splits nearby that fail


@lru_cache(maxsize=8)
def _ratio_grid(rule: SplitRatioRule) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Every recognised split ratio p/q in lowest terms, both orientations: (ratio, ln ratio,
    smaller term), cached per rule (the grid is a few hundred ratios, read once per step)."""
    terms = {
        (p, q)
        for q in range(1, rule.max_denominator + 1)
        for p in range(1, rule.max_numerator + 1)
        if p != q and math.gcd(p, q) == 1
    }
    pairs = sorted(terms | {(q, p) for p, q in terms})
    ratio = np.array([p / q for p, q in pairs])
    return ratio, np.log(ratio), np.array([min(p, q) for p, q in pairs])


def simplest_split_ratio(
    level_step: float, rule: SplitRatioRule, rel_tol: float
) -> tuple[float, float] | None:
    """The simplest recognised split ratio f (old/new price) whose unadjusted step -ln f reads
    the level step (scale_step's unadjusted band: within rel_tol * |ln f| of -ln f), and the
    residual level_step + ln f; None when no ratio reads it.

    Simplest is the smaller term first (q of a forward p:q, p of a reverse one; the
    recognised_split_ratio convention, smallest denominator wins), then the nearest within it: a
    4:1 reads as 4, not 3, though the scale tolerance admits both. Not the nearest overall: the
    recognised grid (q up to 4, p up to 50) is dense enough that some ratio sits within a
    fraction of a percent of any step, so nearness alone carries no evidence."""
    ratio, log_ratio, term = _ratio_grid(rule)
    gap = np.abs(level_step + log_ratio)
    readable = np.flatnonzero(gap <= rel_tol * np.abs(log_ratio))
    if not len(readable):
        return None
    best = readable[np.lexsort((gap[readable], term[readable]))[0]]
    return float(ratio[best]), round(level_step + float(log_ratio[best]), 6)


def classify_step(
    step: LevelStep,
    recorded: Sequence[RecordedFactor],
    identity_breaks: Sequence[int],
    params: SeamParams,
) -> SeamVerdict:
    """One level step's class (module docstring). recorded holds the series' recorded splits,
    identity_breaks the session ordinals at which its string may have changed hands. Pure."""
    lo = step.prev_session + 1 - params.explain_sessions
    hi = step.session + params.explain_sessions
    near = [r for r in recorded if lo <= r.first_new_session <= hi]
    for source in sorted({r.source for r in near}):
        group = [r for r in near if r.source == source]
        factor = math.prod(r.factor for r in group)
        if factor != 1 and scale_step(step.level_step, factor, params.rel_tol) == "unadjusted":
            return SeamVerdict(
                "explained",
                f"{source} split(s) x{factor:.6g} read the level step {step.level_step:+.3f}",
                tuple(r.ref for r in group),
            )
    snapped = simplest_split_ratio(step.level_step, params.ratio_rule, params.rel_tol)
    ratio, residual = snapped if snapped is not None else (None, None)
    volume_agrees = (
        None
        if step.volume_step is None or ratio is None
        else scale_step(-step.volume_step, ratio, params.rel_tol) == "unadjusted"
    )
    evidence = dict(
        implied_ratio=ratio,
        ratio_residual=residual,
        volume_agrees=volume_agrees,
        nearby_unexplaining=tuple(r.ref for r in near),
    )
    breaks = [b for b in identity_breaks if step.prev_session < b <= step.session]
    if breaks or step.gap > params.max_halt_gap:
        why = (
            f"identity break at session {breaks[0]}"
            if breaks
            else f"{step.gap} sessions missing before the step"
        )
        return SeamVerdict("identity_suspect", why, **evidence)
    half = params.level_sessions / 2
    if step.gap > params.halt_gap:
        return SeamVerdict("thin_halted", f"{step.gap} sessions missing", **evidence)
    if step.n_before < half or step.n_after < half:
        return SeamVerdict(
            "thin_halted", f"sides of {step.n_before}/{step.n_after} observations", **evidence
        )
    if step.median_volume < params.thin_volume:
        return SeamVerdict(
            "thin_halted", f"median volume {step.median_volume:.0f} shares", **evidence
        )
    why = f"level step {step.level_step:+.3f}" + (
        "" if ratio is None else f" ~ x{ratio:.4g} (residual {residual:+.3f})"
    )
    if near:
        why += "; a recorded split nearby does not explain it"
    return SeamVerdict("unexplained", why, **evidence)


def junction_levels(
    sessions: np.ndarray,
    values: np.ndarray,
    junction: int,
    k: int,
    bounds: tuple[int, int] | None = None,
) -> tuple[float, float] | None:
    """Medians of up to k values before the junction session and of up to k from it on (the
    level either side of a break), each side inside bounds (session ordinals, the upper one
    exclusive) when given; None when a side is empty."""
    pos = int(np.searchsorted(sessions, junction))
    lo, hi = (0, len(sessions)) if bounds is None else np.searchsorted(sessions, bounds)
    before, after = values[max(int(lo), pos - k) : pos], values[pos : min(int(hi), pos + k)]
    if not len(before) or not len(after):
        return None
    return float(np.median(before)), float(np.median(after))


SpanVerdict = Literal[
    "canonical_matches_massive",
    "pre_span_off",
    "post_span_off",
    "constant_offset",
    "both_spans_off",
]


def span_verdict(log_k_before: float, log_k_after: float, level_tol: float) -> SpanVerdict:
    """An adjusted incumbent against the vendor (adjusted by the recorded splits) either side of
    a break, by level (the 592 rule): log k is ln(incumbent / vendor) per span; a span within
    level_tol of 0 sits at the vendor's level."""
    pre_ok, post_ok = abs(log_k_before) <= level_tol, abs(log_k_after) <= level_tol
    if pre_ok and post_ok:
        return "canonical_matches_massive"
    if post_ok:
        return "pre_span_off"
    if pre_ok:
        return "post_span_off"
    if abs(log_k_before - log_k_after) <= level_tol:
        return "constant_offset"
    return "both_spans_off"


IncumbentReading = Literal["incumbent_flat", "incumbent_moves", "incumbent_other"]


def incumbent_reading(
    level_step: float,
    incumbent_level_step: float,
    rule: SplitRatioRule,
    rel_tol: float,
    level_tol: float,
) -> tuple[IncumbentReading, float | None]:
    """An unexplained vendor step read against an adjusted incumbent's level step at the same
    junction (canonical 1d: IBKR before 2016, independent of the vendor): both carry it within
    level_tol (incumbent_moves: a real move two vendors witness); the excess vendor step reads as
    a recognised split the incumbent adjusted (incumbent_flat: a split missing from every record,
    with its ratio); anything else (incumbent_other). Returns (reading, the excess's ratio)."""
    excess = level_step - incumbent_level_step
    if abs(excess) <= level_tol:
        return "incumbent_moves", None
    snapped = simplest_split_ratio(excess, rule, rel_tol)
    if snapped is not None and abs(snapped[1]) <= level_tol:
        return "incumbent_flat", snapped[0]
    return "incumbent_other", None


_TAPE: dict[ScaleStep, TapeReading] = {
    "unadjusted": "tape_step",
    "adjusted": "tape_flat",
    "conflict": "tape_conflict",
}


def tape_reading(
    sessions: np.ndarray,
    close: np.ndarray,
    first_new_session: int,
    factor: float,
    bounds: tuple[int, int],
    params: SeamParams,
) -> tuple[TapeReading, float | None]:
    """Whether an unadjusted series carries a recorded split: the level step across its first
    new-scale session (medians of up to level_sessions observations a side, inside bounds, the
    neighbouring recorded splits' sessions) read against the factor, and the level step.

    no_tape when a side has no observation within explain_sessions + halt_gap sessions of the
    split, or bounds leave a side empty."""
    pos = int(np.searchsorted(sessions, first_new_session))
    reach = params.explain_sessions + params.halt_gap
    if pos == 0 or pos == len(sessions):
        return "no_tape", None
    if sessions[pos - 1] < first_new_session - reach or sessions[pos] > first_new_session + reach:
        return "no_tape", None
    levels = junction_levels(sessions, close, first_new_session, params.level_sessions, bounds)
    if levels is None:
        return "no_tape", None
    level = round(math.log(levels[1] / levels[0]), 6)
    return _TAPE[scale_step(level, factor, params.rel_tol)], level
