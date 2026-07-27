#!/usr/bin/env python3
"""CrossSectionalSpreadTracker — pure construction primitives for Phase 167's dollar-neutral
decile long-short spread.

This module is the productionization of
`scripts/analysis/t3_cross_sectional_long_short_ctf_momentum_check.py` — the Edge Source
Thesis T3 falsification script that passed decisively (STATE.md, 2026-07-26). Everything here
is a pure, side-effect-free function with no DB or Kafka I/O, so equivalence to the proof
script's ranking mechanic can be asserted directly in a unit test, and Plan 03's service becomes
thin orchestration over already-proven math.

CORRECTNESS INVARIANTS:
- Legs are FLAT equal-weight, never vol-scaled (design decision 1, RESEARCH.md Pitfall 1). The
  design doc's Minimal Design step 3 says "vol-scaled per symbol," but the T3 script that
  actually earned this phase uses `long_leg[return_col].mean() - short_leg[return_col].mean()`.
  Build exactly what was proven; vol-scaling is a separate, testable enhancement with its own
  before/after comparison, never a silent upgrade folded in here.
- The ranked feature is `ctf_momentum` directly, never `ensemble_alpha` (D-01/D-02) — a single
  feature, no composite score. This module never reads `ensemble_alpha`.
- `decile_legs` breaks ties deterministically by `(feature_value, symbol)` ascending (design
  decision 2). This is a RECORDED REPRODUCIBILITY DIVERGENCE from the T3 proof script, which
  ranks via pandas `sort_values(feature)` whose tie order depends on input row order. On a
  continuous z-scored feature exact ties are effectively measure-zero, so this does not change
  what T3 proved — it makes the persisted output reproducible across runs. If a future feature
  with a discrete or heavily-quantized distribution is ever ranked by this machinery, that
  "ties are irrelevant" judgment must be re-examined (Codex review, MEDIUM).
- `one_way_turnover` returns `None`, never `0.0`, when no predecessor legs exist (design
  decision 3, RESEARCH.md Pitfall 4). A turnover of exactly 0.0 or 1.0 at every incremental run
  boundary is Pitfall 4's stated symptom of a service that treats "first bar this run" as having
  no predecessor; returning `None` makes that failure mode structurally detectable instead of
  indistinguishable from a legitimate zero-turnover bar.
- `net_spread_by_cost_bps` computes every cost tier LIVE from realized turnover, every run
  (D-05) — never a cached "it survives" conclusion, and never reads the directional-trade
  cost-hurdle APR key (RESEARCH.md Pitfall 5 — that key belongs to a different mechanism with
  different cost dynamics; see this function's docstring for the exact key name).
- A missing (`None`) or non-finite (NaN / +-inf) feature value entering `decile_legs` raises
  `ValueError` naming the offending symbol rather than being silently sorted (design decision
  5). Python's tuple sort on a NaN key is partition-dependent and non-transitive — it raises
  nothing and produces a plausible-looking but arbitrary leg assignment, exactly the "silent
  wrong answer" CLAUDE.md forbids.

Usage:
    Plan 03 adds the CLI entrypoint and `BaseBatch` orchestration that calls these functions.
    This module has no `__main__` block of its own.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services.counterfactual_tracker import _DEFAULT_BOOTSTRAP_RANDOM_STATE  # noqa: E402,F401

# D-04: the only timeframe this phase measures.
_TF = "15m"

# D-01/D-02: ranked directly, never ensemble_alpha. A single feature, no composite score.
_FEATURE = "ctf_momentum"

# construction_spreads.construction_name — identifies this construction among future ones.
_CONSTRUCTION_NAME = "ctf_momentum_decile_ls"


def decile_legs(
    ranked_symbols: Sequence[str],
    feature_values: Sequence[float],
    decile_fraction: float,
) -> tuple[list[str], list[str]] | None:
    """Split a cross-section into a dollar-neutral (short_leg, long_leg) pair.

    Reproduces the T3 script's `_decile_spread_per_bar`/`_legs_per_bar` ranking mechanic
    exactly: `n_leg = max(1, round(n * decile_fraction))`, `None` returned when
    `n < 2 * n_leg` (too few symbols to form two disjoint legs). The T3 script ranks ascending
    via `sort_values(feature_col)`, so `iloc[:n_leg]` (the lowest feature values) is the SHORT
    leg and `iloc[-n_leg:]` (the highest) is the LONG leg — this function preserves that
    short-is-lowest / long-is-highest correspondence.

    Tie-break: symbols are sorted by `(feature_value, symbol)` ascending, not just
    `feature_value`. This is an intentional, RECORDED REPRODUCIBILITY DIVERGENCE from the T3
    script (design decision 2) — pandas `sort_values` on a single column leaves tie order
    dependent on input row order, which is fine for a one-off script but not for a persisted,
    reproducible table. The judgment that exact ties are effectively measure-zero rests on
    `ctf_momentum` being a continuous z-scored feature; it would need re-examination before this
    machinery ranks a discrete or heavily-quantized feature.

    A `None` or non-finite (NaN / +-inf) feature value raises `ValueError` naming the offending
    symbol rather than being sorted (design decision 5) — an unguarded sort on a NaN key is
    partition-dependent and non-transitive, silently producing a plausible-looking but arbitrary
    split.

    Raises:
        ValueError: if `len(ranked_symbols) != len(feature_values)`, or if any feature value is
            `None` or fails `math.isfinite`.

    Returns:
        `(short_leg, long_leg)` symbol lists, or `None` if the cross-section is too small to
        form two disjoint legs.
    """
    if len(ranked_symbols) != len(feature_values):
        raise ValueError(
            "ranked_symbols and feature_values must be the same length, got "
            f"{len(ranked_symbols)} and {len(feature_values)}"
        )

    for symbol, value in zip(ranked_symbols, feature_values, strict=True):
        if value is None or not math.isfinite(value):
            raise ValueError(
                f"feature value for symbol {symbol!r} is missing or non-finite: {value!r}"
            )

    n = len(ranked_symbols)
    n_leg = max(1, int(round(n * decile_fraction)))
    if n < 2 * n_leg:
        return None

    ranked = sorted(zip(feature_values, ranked_symbols, strict=True))
    short_leg = [symbol for _, symbol in ranked[:n_leg]]
    long_leg = [symbol for _, symbol in ranked[-n_leg:]]
    return short_leg, long_leg


def spread_from_legs(
    returns_by_symbol: Mapping[str, float | None],
    long_leg: Sequence[str],
    short_leg: Sequence[str],
) -> float | None:
    """Dollar-neutral flat equal-weight spread: mean(long returns) - mean(short returns).

    Symbols whose return is `None` (or absent from `returns_by_symbol`) are skipped, never
    coerced to `0.0` — a fabricated zero return would silently distort the leg mean. Returns
    `None` if either leg ends up with zero usable returns, never a spread computed against an
    empty leg.
    """
    long_returns = [r for s in long_leg if (r := returns_by_symbol.get(s)) is not None]
    short_returns = [r for s in short_leg if (r := returns_by_symbol.get(s)) is not None]
    if not long_returns or not short_returns:
        return None
    return (sum(long_returns) / len(long_returns)) - (sum(short_returns) / len(short_returns))


def one_way_turnover(
    prev_long: frozenset[str],
    prev_short: frozenset[str],
    cur_long: frozenset[str],
    cur_short: frozenset[str],
) -> float | None:
    """Mean one-way leg turnover between the prior bar's legs and the current bar's legs.

    Matches the T3 script's `_cost_hurdle_check` exactly: `n_leg = len(cur_long)` (the CURRENT
    universe size, never `len(prev_long)` — the universe can change bar to bar, and the script's
    choice is the one whose result was measured), `long_changed = len(cur_long - prev_long) /
    n_leg`, `short_changed = len(cur_short - prev_short) / n_leg`, returning their mean.

    Returns `None`, never `0.0`, when both `prev_long` and `prev_short` are empty (design
    decision 3) — that is the "no predecessor bar exists" case (the first bar of an incremental
    run), and RESEARCH.md Pitfall 4 names a turnover of exactly `0.0` at every run boundary as
    the symptom of a service that fakes this case as a legitimate zero-turnover bar. Also
    returns `None` if `cur_long` is empty (undefined denominator).
    """
    if not prev_long and not prev_short:
        return None
    n_leg = len(cur_long)
    if n_leg == 0:
        return None
    long_changed = len(cur_long - prev_long) / n_leg
    short_changed = len(cur_short - prev_short) / n_leg
    return (long_changed + short_changed) / 2


def net_spread_by_cost_bps(
    gross_spread: float | None,
    turnover: float | None,
    cost_bps: Sequence[int],
) -> dict[str, float] | None:
    """Todo-030 cost-hurdle sweep computed LIVE from realized turnover (D-05).

    Returns `{str(bps): gross_spread - (bps / 10000.0) * turnover for bps in cost_bps}`. Keys
    are `str(bps)` because this dict is persisted as `jsonb` and JSON object keys must be
    strings. This is computed fresh every run from the ACTUAL turnover this specific
    construction realized — never a cached "it survives" conclusion, and never reads the
    per-tf directional-trade cost-hurdle key (namespace `alpha.quant`, config key
    `cost_hurdle` + `.<tf>` suffix — RESEARCH.md Pitfall 5: that key belongs to a different
    mechanism with different cost dynamics).

    Returns `None` if either `gross_spread` or `turnover` is `None` — never a dict of
    zero-cost-adjusted values that would look like a real (and misleadingly favorable) result.
    """
    if gross_spread is None or turnover is None:
        return None
    return {str(bps): gross_spread - (bps / 10000.0) * turnover for bps in cost_bps}


def validate_construction_config(
    decile_fraction: float,
    cost_bps: Sequence[int],
    null_shuffles: int,
    attribution_max_static_r2: float,
) -> None:
    """Range-validate the construction's APR-bound parameters (T-167-01, ASVS V5).

    Raises `ValueError` naming the offending key and its observed value on any out-of-range
    input. Never clamps, never logs a warning and continues — CLAUDE.md: "silent wrong answers
    are worse than loud crashes."

    Raises:
        ValueError: if `decile_fraction` is not in `(0, 0.5]` (at exactly 0.5 the two legs
            consume the entire universe; above it they would overlap); if `cost_bps` is empty or
            contains any non-positive value; if `null_shuffles < 1`; if
            `attribution_max_static_r2` is not in the open interval `(0, 1)`.
    """
    if not (0 < decile_fraction <= 0.5):
        raise ValueError(f"decile_fraction must be in (0, 0.5], got {decile_fraction}")
    if not cost_bps:
        raise ValueError("cost_bps must not be empty")
    for bps in cost_bps:
        if bps <= 0:
            raise ValueError(f"cost_bps entries must all be positive, got {bps}")
    if null_shuffles < 1:
        raise ValueError(f"null_shuffles must be >= 1, got {null_shuffles}")
    if not (0 < attribution_max_static_r2 < 1):
        raise ValueError(
            "attribution_max_static_r2 must be in (0, 1), got " f"{attribution_max_static_r2}"
        )
