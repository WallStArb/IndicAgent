"""D2a bar-scrubbing rules: pure, APR-parameterized functions over bar arrays.

Phase 185 plan 05 (D-08, D-10, D-11, D-13, D-14). Every rule in this module is a
pure function over numpy arrays: no database, no config service, no I/O, no logging.
Thresholds arrive in a frozen ScrubParams built by ScrubParams.from_apr() from a
plain mapping the caller loaded (plan 10 reads config_state through the project's
config service; this module never touches a DB itself).

The price_sanity rule reuses classify_candidate_bar from
src/intelligence/statistics/price_sanity.py unchanged (D-13): it is run here as a
batch rule over arrays, with the same neighbor semantics the dry-run scanner used
(prev bar's close, next bar's open; a missing neighbor at a series boundary is
always AMBIGUOUS and never a flag). run_rules returns the raw non-PLAUSIBLE
verdicts in price_sanity_candidates; the cross-symbol corroboration pass that
consumes them belongs to the caller (plan 10), because it needs every symbol's
candidates at once.

Cross-symbol corroboration must not clear a print beyond the magnitude threshold
(D-11): corroborated_verdict() blocks the downgrade whenever the verdict's max_ratio
exceeds threshold.bar_scrub.corroboration_max_clearable_ratio, so the 2010-05-06
Flash Crash stub prints and EWW 2006-11-07 stay CONFIRMED_CORRUPT.

RULE_VERSION must be bumped on any behavior change: every bar_quality_flag row
written from these rules carries it (plan 04's schema).
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np

from src.intelligence.statistics.price_sanity import (
    CandidateVerdict,
    apply_cross_symbol_downgrade,
    classify_candidate_bar,
)

RULE_VERSION: str = "scrub-v1"

# Definitional unit table (APR-exempt: a timeframe's length in seconds is a unit
# conversion, not a tunable).
_TF_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "1d": 86400,
}


@dataclass(frozen=True)
class BarFlag:
    """One rule firing on one bar.

    index is the bar's position in the SymbolBars array the rule ran over; fields
    names the offending OHLCV fields; detail is JSON-safe context for
    bar_quality_flag.detail.
    """

    index: int
    rule: str
    fields: tuple[str, ...]
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ScrubParams:
    """Every scrub-rule threshold for one (ruleset, timeframe).

    Built from APR via from_apr(); the seeded values live in migration 381
    (threshold.bar_scrub.*, plus the reused alpha.quant.* and
    alpha.forward_returns.* keys).
    """

    jump_sigma: float
    jump_vol_window: int
    stale_run_min: int
    volume_outlier_mad: float
    volume_window: int
    corroboration_max_clearable_ratio: float
    view_disagreement_rel: float
    magnitude_threshold: float
    neighbor_agreement_threshold: float
    min_symbols: int
    corroboration_window_seconds: int
    max_abs_return: float
    gap_multiplier: int
    gap_max_seconds: int
    quarantine_rules: frozenset[str]

    @classmethod
    def from_apr(cls, apr: Mapping[str, object], tf: str) -> ScrubParams:
        """Build params from an APR mapping (str values from config_state are fine)."""
        rules_raw = apr["threshold.bar_scrub.quarantine_rules"]
        if isinstance(rules_raw, str):
            rules_raw = json.loads(rules_raw)
        return cls(
            jump_sigma=_as_float(apr["threshold.bar_scrub.jump_sigma"]),
            jump_vol_window=_as_int(apr["threshold.bar_scrub.jump_vol_window"]),
            stale_run_min=_as_int(apr["threshold.bar_scrub.stale_run_min"]),
            volume_outlier_mad=_as_float(apr["threshold.bar_scrub.volume_outlier_mad"]),
            volume_window=_as_int(apr["threshold.bar_scrub.volume_window"]),
            corroboration_max_clearable_ratio=_as_float(
                apr["threshold.bar_scrub.corroboration_max_clearable_ratio"]
            ),
            view_disagreement_rel=_as_float(apr["threshold.bar_scrub.view_disagreement_rel"]),
            magnitude_threshold=_as_float(apr["alpha.quant.price_sanity.magnitude_threshold"]),
            neighbor_agreement_threshold=_as_float(
                apr["alpha.quant.price_sanity.neighbor_agreement_threshold"]
            ),
            min_symbols=_as_int(apr["alpha.quant.cross_symbol_corroboration.min_symbols"]),
            corroboration_window_seconds=_as_int(
                _as_float(apr["alpha.quant.cross_symbol_corroboration.window_minutes"]) * 60
            ),
            max_abs_return=_as_float(apr[f"alpha.quant.max_abs_return.{tf}"]),
            gap_multiplier=_as_int(apr["alpha.forward_returns.gap_multiplier"]),
            gap_max_seconds=_as_int(apr["alpha.forward_returns.gap_max_seconds"]),
            quarantine_rules=frozenset(rules_raw),
        )


@dataclass(frozen=True)
class SymbolBars:
    """One symbol's traded bars for one timeframe, ordered by timestamp.

    ts_seconds is int64 epoch seconds; open/high/low/close/volume are float64.
    corporate_action_indices holds bar positions with a recorded corporate action
    (D-21/D-24), which volatility-scaled jump rules must not flag.
    """

    symbol: str
    tf: str
    ts_seconds: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    corporate_action_indices: frozenset[int] = frozenset()


@dataclass(frozen=True)
class ScrubResult:
    """All flags one run_rules pass produced, plus per-rule counts.

    price_sanity_candidates carries every non-PLAUSIBLE (index, verdict) pair so
    the caller can run the cross-symbol corroboration pass across symbols before
    writing flags (the pass needs every symbol's candidates at once).
    """

    flags: tuple[BarFlag, ...]
    counts: dict[str, int]
    price_sanity_candidates: tuple[tuple[int, CandidateVerdict], ...]


def _as_float(value: object) -> float:
    """Coerce an APR value (config_state serves text) to float."""
    return float(value)


def _as_int(value: object) -> int:
    """Coerce an APR value to int via float ('60.0' text form stays exact)."""
    return int(float(value))


def _tf_seconds(tf: str) -> int:
    try:
        return _TF_SECONDS[tf]
    except KeyError as error:
        raise ValueError(f"unknown timeframe {tf!r}") from error


def _finite_or_none(value: float) -> float | None:
    """JSON-safe max_ratio: jsonb rejects Infinity/NaN, so non-finite becomes None."""
    return float(value) if math.isfinite(value) else None


def price_sanity(
    bars: SymbolBars, params: ScrubParams
) -> tuple[list[BarFlag], tuple[tuple[int, CandidateVerdict], ...]]:
    """D-13: classify_candidate_bar run as a batch rule over the bar array.

    Candidate selection mirrors the dry-run scanner (_scan_and_classify): every bar
    is classified against its immediate neighbors (prev close / next open), and
    every non-PLAUSIBLE verdict is a candidate. Only CONFIRMED_CORRUPT becomes a
    flag here; AMBIGUOUS never flags (missing or untrustworthy neighbors), and the
    cross-symbol corroboration pass (corroborated_verdict, plan 10) decides which
    CONFIRMED_CORRUPT flags survive as MARKET_EVENT -- after the D-11 ceiling.
    """
    n = bars.close.size
    flags: list[BarFlag] = []
    candidates: list[tuple[int, CandidateVerdict]] = []
    for i in range(n):
        prev_close = float(bars.close[i - 1]) if i > 0 else None
        next_open = float(bars.open[i + 1]) if i < n - 1 else None
        verdict = classify_candidate_bar(
            open_=float(bars.open[i]),
            high=float(bars.high[i]),
            low=float(bars.low[i]),
            close=float(bars.close[i]),
            prev_close=prev_close,
            next_open=next_open,
            magnitude_threshold=params.magnitude_threshold,
            neighbor_agreement_threshold=params.neighbor_agreement_threshold,
        )
        if verdict.verdict == "PLAUSIBLE":
            continue
        candidates.append((i, verdict))
        if verdict.verdict == "CONFIRMED_CORRUPT":
            flags.append(
                BarFlag(
                    index=i,
                    rule="price_sanity",
                    fields=tuple(verdict.implausible_fields),
                    detail={
                        "verdict": verdict.verdict,
                        "max_ratio": _finite_or_none(verdict.max_ratio),
                        "neighbor_ratio": (
                            _finite_or_none(verdict.neighbor_ratio)
                            if verdict.neighbor_ratio is not None
                            else None
                        ),
                        "reason": verdict.reason,
                    },
                )
            )
    return flags, tuple(candidates)


def count_corroborating(
    candidates: Mapping[str, np.ndarray], window_seconds: int
) -> dict[tuple[str, int], int]:
    """For each (symbol, ts) candidate, how many OTHER symbols have a candidate within.

    Pure: candidates maps symbol -> int64 ts array. A symbol with two candidates
    inside the window still counts once (corroboration is per-symbol, matching the
    SQL primitive's set semantics).
    """
    symbols = sorted(candidates)
    arrays = [np.asarray(candidates[s], dtype=np.int64) for s in symbols]
    out: dict[tuple[str, int], int] = {}
    for idx, symbol in enumerate(symbols):
        own = arrays[idx]
        if own.size == 0:
            continue
        within = np.zeros(own.shape, dtype=np.int64)
        for jdx, other in enumerate(arrays):
            if jdx == idx or other.size == 0:
                continue
            close = np.abs(own[:, None] - other[None, :]) <= window_seconds
            within += close.any(axis=1).astype(np.int64)
        out.update({(symbol, int(ts)): int(k) for ts, k in zip(own.tolist(), within.tolist())})
    return out


def corroborated_verdict(
    verdict: CandidateVerdict,
    n_corroborating: int,
    *,
    min_symbols: int,
    max_clearable_ratio: float,
) -> CandidateVerdict:
    """apply_cross_symbol_downgrade behind the D-11 ceiling.

    Returns the verdict unchanged when it is not CONFIRMED_CORRUPT, or when its
    max_ratio exceeds max_clearable_ratio (a print that far off its neighbors is
    corrupt no matter how many symbols moved: the Flash Crash defect). Otherwise
    delegates to the shared downgrade (subject plus n_corroborating others must
    reach min_symbols before the verdict becomes MARKET_EVENT).
    """
    if verdict.verdict != "CONFIRMED_CORRUPT" or verdict.max_ratio > max_clearable_ratio:
        return verdict
    return apply_cross_symbol_downgrade(verdict, n_corroborating, min_symbols)


def is_quarantine(flag: BarFlag, params: ScrubParams) -> bool:
    """Whether a flag's rule is in the APR-controlled quarantine list (D-09)."""
    return flag.rule in params.quarantine_rules


def run_rules(bars: SymbolBars, params: ScrubParams) -> ScrubResult:
    """Run every single-symbol D2a rule over one symbol's bars.

    Cross-symbol corroboration is deliberately NOT applied here (see price_sanity):
    the caller collects price_sanity_candidates across symbols, then applies
    count_corroborating + corroborated_verdict before writing flags.
    """
    ps_flags, candidates = price_sanity(bars, params)
    flags = list(ps_flags)
    counts = {"price_sanity": len(ps_flags)}
    return ScrubResult(
        flags=tuple(flags),
        counts=counts,
        price_sanity_candidates=candidates,
    )
