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

The D-14 ports (return_magnitude, gap_before_next) reproduce forward_return_writer's
formulas as bar rules before phase 186 deletes that writer: return_magnitude flags
bar i for |ln(open[i+1]/open[i])| beyond the tf ceiling (the writer's return_fast at
T = i-1), and gap_before_next flags bar i when the next traded bar is more than
gap_multiplier x tf_seconds and less than gap_max_seconds away (the writer's
has_gap_before_entry). view_disagreement is exported standalone rather than wired
into run_rules because it needs the adjusted-close view alongside the trades view
(plan 12's derivation and plan 17's daily pass call it with both series).

RULE_VERSION must be bumped on any behavior change: every bar_quality_flag row
written from these rules carries it (plan 04's schema).
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

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
    """Coerce an APR value to int via float (text forms with a decimal stay exact)."""
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


_OHLCV_FIELDS = ("open", "high", "low", "close", "volume")


def ohlc_invariant(bars: SymbolBars) -> list[BarFlag]:
    """high >= max(open, close), low <= min(open, close) and high >= low, per bar."""
    high_below_body = bars.high < np.maximum(bars.open, bars.close)
    low_above_body = bars.low > np.minimum(bars.open, bars.close)
    high_below_low = bars.high < bars.low
    any_violation = high_below_body | low_above_body | high_below_low
    flags: list[BarFlag] = []
    for i in np.flatnonzero(any_violation):
        violations: list[str] = []
        fields: list[str] = []
        if high_below_body[i]:
            violations.append("high_below_body")
            fields.append("high")
        if low_above_body[i]:
            violations.append("low_above_body")
            fields.append("low")
        if high_below_low[i]:
            violations.append("high_below_low")
            for name in ("high", "low"):
                if name not in fields:
                    fields.append(name)
        flags.append(
            BarFlag(
                index=int(i),
                rule="ohlc_invariant",
                fields=tuple(fields),
                detail={"violations": violations},
            )
        )
    return flags


def non_positive_price(bars: SymbolBars) -> list[BarFlag]:
    """Any OHLCV field at or below zero, with the offending fields named."""
    arrays = {
        "open": bars.open,
        "high": bars.high,
        "low": bars.low,
        "close": bars.close,
        "volume": bars.volume,
    }
    mask = np.zeros(bars.close.size, dtype=bool)
    for arr in arrays.values():
        mask |= arr <= 0  # NaN fails this comparison, so missing stays unflagged
    flags: list[BarFlag] = []
    for i in np.flatnonzero(mask):
        fields = tuple(name for name in _OHLCV_FIELDS if arrays[name][i] <= 0)
        flags.append(
            BarFlag(
                index=int(i),
                rule="non_positive_price",
                fields=fields,
                detail={"values": {name: float(arrays[name][i]) for name in fields}},
            )
        )
    return flags


def vol_scaled_jump(bars: SymbolBars, params: ScrubParams) -> list[BarFlag]:
    """|ln(c[i]/c[i-1])| > jump_sigma x rolling sigma of the prior returns.

    The sigma window (jump_vol_window returns, excluding bar i's own) must be full
    before anything can flag, so short series and series warmups are never judged.
    Bars with a recorded corporate action are never flagged (a split is a price
    scale, not a print). Informational by default (D-08/D-09).
    """
    n = bars.close.size
    w = int(params.jump_vol_window)
    flags: list[BarFlag] = []
    if n < 2 or w < 1:
        return flags
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.diff(np.log(bars.close))  # r[j] is the return entering bar j + 1
        # Bar i's own return is r[i - 1]; its sigma window is the w returns before
        # that, r[i - 1 - w : i - 1], which needs i - 1 - w >= 0.
        if n <= w + 1:
            return flags
        wins = sliding_window_view(r, w)  # wins[j] = r[j : j + w]
        idx = np.arange(w + 1, n)
        sigma = wins[idx - 1 - w].std(axis=1)
        own = np.abs(r[idx - 1])
        ratio = own / sigma
        hit = idx[np.isfinite(ratio) & (sigma > 0) & (ratio > params.jump_sigma)]
    for i in hit:
        if int(i) in bars.corporate_action_indices:
            continue
        flags.append(
            BarFlag(
                index=int(i),
                rule="vol_scaled_jump",
                fields=("close",),
                detail={
                    "abs_log_return": float(np.abs(r[i - 1])),
                    "sigma": float(sigma[i - w - 1]),
                    "z": float(ratio[i - w - 1]),
                },
            )
        )
    return flags


def stale_print(bars: SymbolBars, params: ScrubParams) -> list[BarFlag]:
    """Runs of at least stale_run_min consecutive identical-OHLC bars, volume > 0.

    Run-length encoded in numpy (the one permitted scan): bar i extends a run when
    its OHLC equals the previous bar's. Every bar of a qualifying run is flagged.
    Zero-volume flat bars are the known synthetic calendar fill, not a stale print,
    so a run containing one is never flagged. Informational by default.
    """
    n = bars.close.size
    run_min = int(params.stale_run_min)
    if n == 0:
        return []
    same = np.zeros(n, dtype=bool)
    if n > 1:
        same[1:] = (
            (bars.open[1:] == bars.open[:-1])
            & (bars.high[1:] == bars.high[:-1])
            & (bars.low[1:] == bars.low[:-1])
            & (bars.close[1:] == bars.close[:-1])
        )
    block_start = ~same  # bar 0 always starts a block
    block_id = np.cumsum(block_start) - 1  # 0-based ordinal, indexes starts/lengths
    starts = np.flatnonzero(block_start)
    lengths = np.diff(np.append(starts, n))
    block_volume_ok = np.minimum.reduceat(bars.volume > 0, starts)
    qualifying = np.flatnonzero((lengths >= run_min) & block_volume_ok)
    flags: list[BarFlag] = []
    for i in np.flatnonzero(np.isin(block_id, qualifying)):
        flags.append(
            BarFlag(
                index=int(i),
                rule="stale_print",
                fields=("open", "high", "low", "close"),
                detail={"run_length": int(lengths[block_id[i]])},
            )
        )
    return flags


def volume_outlier(bars: SymbolBars, params: ScrubParams) -> list[BarFlag]:
    """Robust z of log volume over the trailing window: |log v - median| / (1.4826 x MAD).

    The 1.4826 constant rescales MAD to a normal standard deviation (a mathematical
    constant, APR-exempt). A window with zero MAD (constant volume) carries no
    dispersion to judge and never flags; the trailing window includes the current
    bar. Informational by default.
    """
    n = bars.volume.size
    w = int(params.volume_window)
    flags: list[BarFlag] = []
    if w < 1 or n < w:
        return flags
    with np.errstate(divide="ignore", invalid="ignore"):
        log_vol = np.log(np.where(bars.volume > 0, bars.volume, np.nan))
        wins = sliding_window_view(log_vol, w)  # wins[j] covers bars j .. j + w - 1
        med = np.median(wins, axis=1)
        mad = np.median(np.abs(wins - med[:, None]), axis=1)
        own = log_vol[w - 1 :]
        robust = np.abs(own - med) / (1.4826 * mad)
        hit = (
            np.flatnonzero(np.isfinite(robust) & (mad > 0) & (robust > params.volume_outlier_mad))
            + w
            - 1
        )
    for i in hit:
        flags.append(
            BarFlag(
                index=int(i),
                rule="volume_outlier",
                fields=("volume",),
                detail={
                    "robust_z": float(robust[i - w + 1]),
                    "median_log_volume": float(med[i - w + 1]),
                },
            )
        )
    return flags


def view_disagreement(
    trades_close: np.ndarray,
    adjusted_close: np.ndarray,
    explained: frozenset[int],
    *,
    rel: float,
) -> list[BarFlag]:
    """A day whose adjusted/trades ratio step exceeds rel and is not explained.

    D7/IBKR view disagreement as a standalone rule: it needs the ADJUSTED_LAST
    series alongside the TRADES series, so plan 12's derivation and plan 17's daily
    pass call it directly rather than through run_rules (SymbolBars carries one
    view). explained holds bar positions with a recorded corporate action or
    dividend; index is the first bar of the new ratio regime.
    """
    trades = np.asarray(trades_close, dtype=np.float64)
    adjusted = np.asarray(adjusted_close, dtype=np.float64)
    if trades.shape != adjusted.shape:
        raise ValueError(f"view_disagreement: shape mismatch {trades.shape} vs {adjusted.shape}")
    n = trades.size
    flags: list[BarFlag] = []
    if n < 2:
        return flags
    with np.errstate(divide="ignore", invalid="ignore"):
        valid = (trades > 0) & (adjusted > 0)
        ratio = np.where(valid, adjusted / trades, np.nan)
        step = np.abs(ratio[1:] / ratio[:-1] - 1)
    for j in np.flatnonzero(np.isfinite(step) & (step > rel)):
        i = int(j) + 1
        if i in explained:
            continue
        flags.append(
            BarFlag(
                index=i,
                rule="view_disagreement",
                fields=("close",),
                detail={
                    "ratio_step": float(step[j]),
                    "prev_ratio": float(ratio[j]),
                    "ratio": float(ratio[i]),
                },
            )
        )
    return flags


def return_magnitude(bars: SymbolBars, params: ScrubParams) -> list[BarFlag]:
    """D-14 port of return_*_suspect: |ln(open[i+1]/open[i])| beyond the tf ceiling.

    forward_return_writer flagged |ln(open[T+2]/open[T+1])| at bar T; the bar rule
    attributes the same return to the entry bar (T + 1 = i). The ceiling is the
    tf's 1-bar APR baseline scaled by sqrt(lookahead), lookahead 1 here. The last
    bar has no next open and is never flagged. Informational by default.
    """
    n = bars.open.size
    flags: list[BarFlag] = []
    if n < 2:
        return flags
    ceiling = params.max_abs_return * math.sqrt(1)
    cur = bars.open[:-1]
    nxt = bars.open[1:]
    safe = (cur > 0) & (nxt > 0)
    ratio = np.ones(n - 1)
    ratio[safe] = nxt[safe] / cur[safe]
    r = np.log(ratio)
    for j in np.flatnonzero(safe & (np.abs(r) > ceiling)):
        flags.append(
            BarFlag(
                index=int(j),
                rule="return_magnitude",
                fields=("open",),
                detail={
                    "abs_log_return": float(np.abs(r[j])),
                    "ceiling": float(ceiling),
                },
            )
        )
    return flags


def gap_before_next(bars: SymbolBars, params: ScrubParams) -> list[BarFlag]:
    """D-14 port of has_gap_before_entry: a trading gap before the next stored bar.

    Flags bar i when ts[i+1] - ts[i] is more than gap_multiplier x tf_seconds and
    less than gap_max_seconds (the floor guards 1-bar noise, the ceiling excludes
    known overnight/weekend calendar structure). At 1d the floor alone is
    3 x 86400 s > 14400 s, so the rule can never fire. Informational.
    """
    ts = bars.ts_seconds
    n = ts.size
    flags: list[BarFlag] = []
    if n < 2:
        return flags
    tf_seconds = _tf_seconds(bars.tf)
    gaps = ts[1:] - ts[:-1]
    hit = np.flatnonzero(
        (gaps > params.gap_multiplier * tf_seconds) & (gaps < params.gap_max_seconds)
    )
    for j in hit:
        flags.append(
            BarFlag(
                index=int(j),
                rule="gap_before_next",
                fields=("timestamp",),
                detail={"gap_seconds": int(gaps[j]), "tf_seconds": int(tf_seconds)},
            )
        )
    return flags


def run_rules(bars: SymbolBars, params: ScrubParams) -> ScrubResult:
    """Run every single-symbol D2a rule over one symbol's bars.

    Cross-symbol corroboration is deliberately NOT applied here (see price_sanity):
    the caller collects price_sanity_candidates across symbols, then applies
    count_corroborating + corroborated_verdict before writing flags.
    view_disagreement is equally cross-view, not cross-symbol only -- it needs the
    adjusted-close series and is called separately by the derivation stages.
    """
    per_rule: dict[str, list[BarFlag]] = {
        "ohlc_invariant": ohlc_invariant(bars),
        "non_positive_price": non_positive_price(bars),
        "vol_scaled_jump": vol_scaled_jump(bars, params),
        "stale_print": stale_print(bars, params),
        "volume_outlier": volume_outlier(bars, params),
        "return_magnitude": return_magnitude(bars, params),
        "gap_before_next": gap_before_next(bars, params),
    }
    ps_flags, candidates = price_sanity(bars, params)
    flags: list[BarFlag] = list(ps_flags)
    counts = {"price_sanity": len(ps_flags)}
    for rule, rule_flags in per_rule.items():
        flags.extend(rule_flags)
        counts[rule] = len(rule_flags)
    return ScrubResult(
        flags=tuple(flags),
        counts=counts,
        price_sanity_candidates=candidates,
    )
