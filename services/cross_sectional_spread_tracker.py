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

MANUAL/ON-DEMAND ONLY (design decision 1): `CrossSectionalSpreadTracker` is deliberately NOT
registered on a systemd timer and NOT added to `service_auditor._DAG_ORDER` -- mirroring
`alpha_scorer.py`'s own module-docstring precedent. Four reasons: (a) `alpha_scorer.py`,
`counterfactual_tracker.py`, and `tag_calibrator.py` are all manual/on-demand with no systemd
unit -- a registered timer here would make this service the outlier; (b) CLAUDE.md's "prove
edge before production infra" -- a construction that has not yet cleared its own Validation
Gates does not earn scheduled infrastructure; (c) CLAUDE.md records that all indicagent
systemd timers are confirmed disabled as of 2026-07-02, so a registered timer would create a
false impression of a cadence that does not actually run; (d) the `--backfill` pass populates
the full 2006-2026 history in one shot, handing Gate 1 roughly 130 OOS day-clusters
immediately rather than waiting on calendar time. Revisit only if this construction clears all
three Validation Gates.

RECOVERY (design decision 5): a crashed run's watermark and prior-leg turnover seed both
derive only from COMMITTED `construction_spreads` rows, never from anything the crashed run
held only in memory. Because writes are flushed in `bar_ts` order in fixed-size chunks, a
crash can only ever truncate a contiguous TAIL of the intended row set -- the next incremental
run recomputes exactly those bars, seeding turnover from the last surviving persisted row, and
produces a table identical to an uninterrupted run.

Usage:
    python services/cross_sectional_spread_tracker.py                    # incremental compute-and-persist
    python services/cross_sectional_spread_tracker.py --backfill         # full-corpus first pass
    python services/cross_sectional_spread_tracker.py --evaluate-gate    # read-only Gate 1
    python services/cross_sectional_spread_tracker.py --evaluate-attribution  # read-only Gate 2
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import asyncpg  # noqa: E402
import numpy as np  # noqa: E402
import structlog  # noqa: E402

from services._batch_utils import cfg as _cfg  # noqa: E402
from services._batch_utils import load_apr_dict_async as _load_apr  # noqa: E402
from services.counterfactual_tracker import (  # noqa: E402
    _DEFAULT_BOOTSTRAP_RANDOM_STATE,
    evaluate_frame_gate,
    frame_gate_passes,
)
from src.config.settings import Settings  # noqa: E402
from src.core.agent.base_batch import BaseBatch  # noqa: E402
from src.core.database_manager import _setup_codecs  # noqa: E402
from src.observability.corpus_manifest import CorpusManifest  # noqa: E402
from src.observability.otel import OTelInitError, init_otel_providers  # noqa: E402

_logger = structlog.get_logger(__name__)

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


# ---------------------------------------------------------------------------
# Validation Gate 1 (--evaluate-gate mode): the eight-cell OOS verdict grid, the live
# shuffled-ranking null, and the durable JSON verdict artifact.
# ---------------------------------------------------------------------------


def mean_gross_spread_over_bars(
    panel_by_bar: Mapping[Any, tuple[list[str], list[float], Mapping[str, float | None]]],
    decile_fraction: float,
) -> tuple[float | None, int]:
    """The single shared per-draw reduction used by BOTH the observed measurement and every
    shuffled-null draw (design decision 6). This is the ONLY place the eligible-bar rule
    lives -- observed-versus-null comparability depends entirely on both sides calling this
    same function over the same `panel_by_bar` mapping.

    For each `bar_ts` in the mapping, calls `decile_legs(symbols, feature_values,
    decile_fraction)`; a `None` result (too few symbols to form two disjoint legs) SKIPS the
    bar, identical to the write path's degeneracy rule (Plan 03). Otherwise calls
    `spread_from_legs` against that bar's return mapping; a `None` spread (a leg with zero
    usable returns) also skips the bar.

    Returns `(mean_spread_over_eligible_bars, n_eligible_bars)`, or `(None, 0)` when no bar
    was eligible.
    """
    total = 0.0
    n_eligible_bars = 0
    for symbols, feature_values, returns_by_symbol in panel_by_bar.values():
        legs = decile_legs(list(symbols), list(feature_values), decile_fraction)
        if legs is None:
            continue
        short_leg, long_leg = legs
        spread = spread_from_legs(returns_by_symbol, long_leg, short_leg)
        if spread is None:
            continue
        total += spread
        n_eligible_bars += 1

    if n_eligible_bars == 0:
        return None, 0
    return total / n_eligible_bars, n_eligible_bars


def shuffled_ranking_null_p(
    panel_by_bar: Mapping[Any, tuple[list[str], list[float], Mapping[str, float | None]]],
    decile_fraction: float,
    observed_mean_spread: float,
    n_shuffles: int,
    seed: int,
) -> tuple[float, float, float, int]:
    """Live shuffled-ranking null (design decision 4): is the observed ranking-driven spread
    distinguishable from the spread produced by dollar-neutral bucket formation alone?

    Each draw permutes each bar's feature-value list WITHIN that bar only -- the symbol list,
    the universe size, and the return mapping are all carried through untouched. A cross-bar
    permutation would destroy the cross-sectional structure being tested, not just the ranking
    information. This preserves, by construction (design decision 6):
    - Universe size per bar, identical in observed and null (a permutation reorders one bar's
      values across that same bar's symbols, never adds/removes a symbol).
    - `n_leg` rounding, identical because it derives from the same `n` and `decile_fraction`.
    - Symbol eligibility, identical because it was already applied by the panel query and a
      permutation never adds or removes a symbol.
    - The degeneracy rule: bars where `decile_legs` returns `None` are skipped identically in
      observed and every draw, since degeneracy depends only on `n` and `decile_fraction`,
      neither of which a permutation touches.
    - Tie-break determinism: tied values permute like any other values; `decile_legs`'
      `(feature_value, symbol)` tie-break applies unchanged, so a tied draw yields a
      deterministic split rather than an arbitrary one.

    The permutation of a bar's feature values does not depend on which return scale
    (`return_fast` vs `return_slow`) is being tested -- only on that bar's symbol count and the
    RNG's draw sequence. Calling this function once per scale with the SAME `seed` therefore
    reproduces a bit-identical sequence of within-bar permutations for both scales. NOTE this is
    weaker than the T3 script's `_generate_shuffled_feature_draws` efficiency lesson (generate
    the draws once, reuse across scales): each call here independently re-runs the permutation
    loop, so the draws are reproduced identically but not literally cached/reused -- correct,
    with the redundant work accepted given the OOS window's small size (hundreds of bars, tens
    of shuffles per call).

    Raises:
        ValueError: if the eligible-bar count is not identical across all `n_shuffles` draws --
            that would mean degeneracy somehow depends on the feature ordering, and the null
            would not be comparable to the observed value.

    Returns:
        `(null_p, null_mean, null_std, n_eligible_bars)` where
        `null_p = mean(draw_means >= observed_mean_spread)`, and `n_eligible_bars` is the
        eligible-bar count shared by every draw. The caller MUST assert this equals the
        observed pass's `n_eligible_bars`.
    """
    rng = np.random.default_rng(seed)
    draw_means: list[float] = []
    draw_n_eligible_bars: list[int] = []
    for _ in range(n_shuffles):
        permuted_panel: dict[Any, tuple[list[str], list[float], Mapping[str, float | None]]] = {}
        for bar_ts, (symbols, feature_values, returns_by_symbol) in panel_by_bar.items():
            permuted_values = rng.permutation(np.asarray(feature_values, dtype=float)).tolist()
            permuted_panel[bar_ts] = (list(symbols), permuted_values, returns_by_symbol)
        draw_mean, draw_n_eligible_bars_this = mean_gross_spread_over_bars(
            permuted_panel, decile_fraction
        )
        draw_means.append(draw_mean if draw_mean is not None else 0.0)
        draw_n_eligible_bars.append(draw_n_eligible_bars_this)

    if len(set(draw_n_eligible_bars)) > 1:
        raise ValueError(
            "shuffled_ranking_null_p: eligible-bar count varies across draws "
            f"({sorted(set(draw_n_eligible_bars))}) -- degeneracy must not depend on feature "
            "ordering, or the null is not comparable to the observed value"
        )

    draw_means_arr = np.array(draw_means, dtype=float)
    null_p = float(np.mean(draw_means_arr >= observed_mean_spread))
    null_mean = float(draw_means_arr.mean())
    null_std = float(draw_means_arr.std())
    n_eligible_bars = draw_n_eligible_bars[0] if draw_n_eligible_bars else 0
    return null_p, null_mean, null_std, n_eligible_bars


def evaluate_spread_gate(
    rows: Iterable[Mapping[str, Any]],
    min_n: int,
    bootstrap_max_n: int,
    bootstrap_batch: int,
    bootstrap_random_state: int,
) -> list[dict[str, Any]]:
    """Pure grouping/verdict core for Validation Gate 1 -- delegates the day-clustered
    block-bootstrap machinery (the small-cluster-count / large-cluster-count method switch
    documented on `frame_gate_passes`) to `counterfactual_tracker.evaluate_frame_gate`
    VERBATIM. No bootstrap math is reimplemented here (design decision 5, RESEARCH.md's Todo
    186 Scope Assessment: a
    spread return is a single scalar time series per bar, not a pooled panel, so the
    day-clustered bootstrap is exactly the right machinery and a new cross-sectional block
    bootstrap is not required).

    Each input row carries `scale` (`"fast"` or `"slow"`), `cost_bps` (int), `cluster_id` (a
    `date`), and `pnl_r` (the net spread for that scale and cost tier). Groups via
    `group_key=lambda row: (row["scale"], row["cost_bps"])`.

    SHAPE CONSTRAINT (same trap `alpha_scorer.py`'s own module docstring documents):
    `evaluate_frame_gate`'s grouping core unpacks its `group_key` strictly as a 2-tuple --
    `for (dim_a, dim_b), bucket in groups.items()` -- and always populates the returned
    verdict's fields as `tf` and `regime`, regardless of what was actually grouped by. This is
    a pre-existing repo-wide pattern, not a trick invented for this phase; passing a 3-tuple
    `group_key` would raise `ValueError: too many values to unpack`. This function renames
    `tf` -> `scale` and `regime` -> `cost_bps` before returning, and renames `n_frames` ->
    `n_bars` since a spread row is a bar, not a frame.
    """
    verdicts = evaluate_frame_gate(
        list(rows),
        min_n,
        bootstrap_max_n,
        bootstrap_batch,
        bootstrap_random_state,
        group_key=lambda row: (row["scale"], row["cost_bps"]),
    )
    return [
        {
            "scale": v["tf"],
            "cost_bps": v["regime"],
            "n_bars": v["n_frames"],
            "n_clusters": v["n_clusters"],
            "ci_lower": v["ci_lower"],
            "ci_upper": v["ci_upper"],
            "passes": v["passes"],
            "coverage": v["coverage"],
        }
        for v in verdicts
    ]


def _coerce_non_finite(value: Any) -> Any:
    """Recursively replace any non-finite float (NaN, +-inf) with `None` so
    `json.dumps(allow_nan=False)` never raises on a legitimate non-finite value inside a
    verdict payload (`frame_gate_passes` legitimately returns `nan` for an under-powered
    cell)."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {k: _coerce_non_finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_coerce_non_finite(v) for v in value]
    return value


def write_verdict_artifact(
    verdict_name: str,
    payload: Mapping[str, Any],
    out_dir: Path = Path("logs/construction_verdicts"),
) -> Path:
    """Persist the full Gate verdict `payload` as strict, timestamped JSON (T-167-17) -- the
    durable audit-trail source of truth a research doc is checked against, rather than
    rotating log lines or editable prose. This is an audit-trail addition only: it introduces
    no new statistic, no new bootstrap, and no new threshold.

    Any non-finite float anywhere in `payload` is coerced to JSON `null` before serialization
    -- `frame_gate_passes` legitimately returns `nan` for an under-powered cell, and Python's
    `json.dump` would otherwise emit a bare `NaN` token, which is invalid JSON that a strict
    reader would reject, silently losing the very record this exists to preserve.
    Non-JSON-native values (e.g. `datetime.date`) serialize via `default=str`. `allow_nan=False`
    makes any coercion gap raise instead of silently writing an unreadable artifact.

    Writes two files: a timestamped `{verdict_name}_{YYYYmmddTHHMMSSZ}.json` (UTC) that a later
    run never overwrites (the record accumulates), and a `{verdict_name}_latest.json` that
    always reflects the most recent run. Returns the timestamped path.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    coerced = _coerce_non_finite(dict(payload))
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    timestamped_path = out_dir / f"{verdict_name}_{timestamp}.json"
    latest_path = out_dir / f"{verdict_name}_latest.json"
    text = json.dumps(coerced, indent=2, default=str, allow_nan=False)
    timestamped_path.write_text(text)
    latest_path.write_text(text)
    return timestamped_path


# ---------------------------------------------------------------------------
# Validation Gate 2 (--evaluate-attribution mode): attribution honesty -- decompose the
# realized spread into a static, time-invariant leg-membership benchmark plus a residual,
# and gate on what survives.
# ---------------------------------------------------------------------------


def static_tilt_weights(leg_rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    """Static bucket membership (design decision 1): each symbol's time-averaged net leg
    exposure over the evaluation window.

    Operationalizes `docs/research/trade-construction-layer.md`'s Gate 2 sentence:
    "regress spread returns on static bucket membership; if a fixed membership explains most
    of it, the 'forecast' is a factor exposure in disguise (edge thesis T4, cap expectations
    accordingly)." For symbol `s`, `w_s = (n_bars_long_s - n_bars_short_s) / n_bars` where
    `n_bars` is the number of rows in `leg_rows` -- one fixed weight per symbol for the whole
    window, deliberately carrying no timing information whatsoever (design decision 1). A
    construction whose P&L comes from being permanently long low-vol sectors will have a `w`
    vector that reproduces most of its return; a construction whose P&L comes from the
    forecast will not.

    RETROSPECTIVE CAVEAT (design decision 8): these weights are computed from the same window
    whose returns they are used to explain, so they are a retrospective summary that no live
    strategy could have held in advance -- they exist to test whether the realized P&L LOOKS
    like a disguised static tilt, not to describe a tradeable benchmark.

    Each row of `leg_rows` must carry `long_leg_symbols` and `short_leg_symbols` (the
    persisted per-bar leg membership).

    Raises:
        ValueError: on empty input. An empty window means the caller queried the wrong
            segment, and a silently empty weight vector would produce a static series of all
            zeros and a meaningless `static_r2` of 0.0 that LOOKS like a clean Gate 2 pass.
    """
    if not leg_rows:
        raise ValueError("static_tilt_weights: leg_rows is empty -- cannot compute static tilt")

    n_bars = len(leg_rows)
    n_long: dict[str, int] = {}
    n_short: dict[str, int] = {}
    for row in leg_rows:
        for symbol in row["long_leg_symbols"]:
            n_long[symbol] = n_long.get(symbol, 0) + 1
        for symbol in row["short_leg_symbols"]:
            n_short[symbol] = n_short.get(symbol, 0) + 1

    symbols = set(n_long) | set(n_short)
    return {symbol: (n_long.get(symbol, 0) - n_short.get(symbol, 0)) / n_bars for symbol in symbols}


def _assert_strictly_increasing_unique(bar_ts_list: Sequence[Any], fn_name: str) -> None:
    """Shared alignment guard (design decision 9): raise `ValueError` naming the offending key
    on a duplicate or non-strictly-increasing bar key sequence."""
    for i in range(1, len(bar_ts_list)):
        if bar_ts_list[i] == bar_ts_list[i - 1]:
            raise ValueError(
                f"{fn_name}: duplicate bar key {bar_ts_list[i]!r} at positions {i - 1} and {i} -- "
                "a duplicate or misaligned bar key would silently regress one bar against "
                "another, producing a confident, plausible, wrong result"
            )
        if bar_ts_list[i] < bar_ts_list[i - 1]:
            raise ValueError(
                f"{fn_name}: bar keys are not strictly increasing at position {i} "
                f"({bar_ts_list[i]!r} < {bar_ts_list[i - 1]!r})"
            )


def static_tilt_series(
    panel_by_bar: Mapping[Any, Mapping[str, float]],
    weights: Mapping[str, float],
) -> tuple[list[Any], list[float]]:
    """The counterfactual return of holding the construction's average exposure and NEVER
    rebalancing -- the benchmark series Gate 2 tests the realized spread against.

    For each `bar_ts` in `panel_by_bar` (ordered ascending), computes
    `sum(weights.get(symbol, 0.0) * return_value for symbol, return_value in
    panel_by_bar[bar_ts].items() if return_value is not None)`. A symbol with a `None` return
    at that bar is skipped, never coerced to `0.0`.

    Raises:
        ValueError: if the ordered `bar_ts` key list contains a duplicate or is not strictly
            increasing (design decision 9), naming the offending key.

    Returns:
        `(bar_ts_list, static_value_list)`, both ordered by `bar_ts` ascending.
    """
    bar_ts_list = sorted(panel_by_bar.keys())
    _assert_strictly_increasing_unique(bar_ts_list, "static_tilt_series")

    static_value_list: list[float] = []
    for bar_ts in bar_ts_list:
        bar_returns = panel_by_bar[bar_ts]
        static_value = sum(
            weights.get(symbol, 0.0) * return_value
            for symbol, return_value in bar_returns.items()
            if return_value is not None
        )
        static_value_list.append(static_value)
    return bar_ts_list, static_value_list


def attribution_verdict(
    spread_values: Sequence[float],
    static_values: Sequence[float],
    cluster_ids: Sequence[Any],
    bar_keys: Sequence[Any],
    max_static_r2: float,
    min_n: int,
    bootstrap_max_n: int,
    bootstrap_batch: int,
    bootstrap_random_state: int,
) -> dict[str, Any]:
    """Validation Gate 2 -- attribution honesty. Operationalizes
    `docs/research/trade-construction-layer.md`'s Gate 2 sentence: "spread P&L must load on
    the forecast (rank-weighted return spread), not on a static factor tilt (e.g., permanently
    long low-vol sectors) -- regress spread returns on static bucket membership; if a fixed
    membership explains most of it, the 'forecast' is a factor exposure in disguise (edge
    thesis T4, cap expectations accordingly)."

    ONE COLLAPSED BENCHMARK SERIES, NOT 80 SYMBOL DUMMIES (design decision 2): the naive
    reading of the design doc's sentence -- one dummy regressor per symbol -- has as many
    regressors as symbols in the universe against a scalar-per-bar dependent variable and
    would overfit catastrophically. Fits the single-regressor form
    `spread_t = alpha + beta * static_t + eps_t` via `numpy.linalg.lstsq` on a design matrix
    of `[static, ones]`. One regressor, one intercept, no multiple-comparisons problem, and a
    directly interpretable `static_r2`.

    GATE ON THE RESIDUAL, NOT R-SQUARED ALONE (design decision 3): `static_r2` answers "how
    much does a fixed membership explain," but the binding question is "does anything survive
    after removing it." `residual_t = spread_t - beta * static_t` -- the intercept is
    deliberately NOT subtracted, since it is the constant excess return the forecast
    contributes and is exactly what the gate wants to test. `residual_t` and `cluster_ids` are
    then fed into the SAME `frame_gate_passes` Gate 1 uses -- NO NEW BOOTSTRAP IS IMPLEMENTED
    HERE, the identical day-clustered bootstrap machinery is reused verbatim on the residual
    series. `gate2_passes` is true iff `residual_passes` is true AND `static_dominates` is
    false: something is left over, and a fixed membership does not explain most of it.

    RETROSPECTIVE, NOT CAUSAL (design decision 8): `w_s` (from `static_tilt_weights`) is
    computed from realized leg membership over the SAME window whose returns are being
    explained -- it could not have been known in advance, and no live strategy could have held
    it. This makes Gate 2 a falsification test in ONE DIRECTION ONLY: a HIGH `static_r2` is
    strong evidence the P&L is a disguised fixed tilt, while a LOW `static_r2` plus a
    surviving residual is evidence only that the P&L is NOT explained by this particular
    retrospective summary. It is emphatically NOT proof that the forecast is what generated
    the return, and it identifies no mechanism. The returned `benchmark_kind` is always the
    literal `"retrospective_time_averaged_membership"` so a future reader who sees "the
    residual survives" cannot mistake it for "we proved WHY it survives."

    ALIGNMENT VALIDATED, NOT TRUSTED (design decision 9): `bar_keys` is a fourth parallel
    sequence used only to detect misalignment, never to fit the regression. Raises `ValueError`
    on any length mismatch across the four input sequences, on any duplicate `bar_keys` entry,
    or on a non-strictly-increasing `bar_keys` order -- a silently misaligned regression would
    produce a confident, plausible, wrong `static_r2`, exactly the class of failure this
    project treats as worse than a crash.

    NO EXTRA REGRESSION DEPENDENCY, NO MULTIPLE-COMPARISONS CORRECTION (design decision 5): a
    single-regressor-plus-intercept fit needs no extra dependency beyond `numpy`, which is
    already pinned. `src/intelligence/statistics/ic_math.py`'s FDR helper is NOT needed here --
    Gate 2 produces one verdict, not a family of tests, so there is no multiple-comparisons
    correction to apply.

    Raises:
        ValueError: if `spread_values`, `static_values`, `cluster_ids`, and `bar_keys` are not
            all the same length (message names the mismatch); if `bar_keys` contains a
            duplicate or is not strictly increasing (message names the offending key).

    Returns:
        A dict with `beta`, `intercept`, `static_r2`, `static_dominates`, `n_bars`,
        `n_clusters`, `residual_ci_lower`, `residual_ci_upper`, `residual_passes`,
        `gate2_passes`, and `benchmark_kind`
        (always `"retrospective_time_averaged_membership"`).
    """
    lengths = {
        "spread_values": len(spread_values),
        "static_values": len(static_values),
        "cluster_ids": len(cluster_ids),
        "bar_keys": len(bar_keys),
    }
    if len(set(lengths.values())) > 1:
        raise ValueError(f"attribution_verdict: mismatched input sequence lengths: {lengths}")

    _assert_strictly_increasing_unique(list(bar_keys), "attribution_verdict")

    spread_arr = np.asarray(spread_values, dtype=float)
    static_arr = np.asarray(static_values, dtype=float)

    design = np.column_stack([static_arr, np.ones_like(static_arr)])
    (beta, intercept), _residuals, _rank, _sv = np.linalg.lstsq(design, spread_arr, rcond=None)
    beta = float(beta)
    intercept = float(intercept)

    fitted = beta * static_arr + intercept
    ss_res = float(np.sum((spread_arr - fitted) ** 2))
    spread_mean = float(np.mean(spread_arr))
    ss_tot = float(np.sum((spread_arr - spread_mean) ** 2))
    static_r2 = 0.0 if ss_tot == 0 else 1.0 - ss_res / ss_tot
    static_dominates = static_r2 > max_static_r2

    # design decision 3: only the beta term is removed, the intercept is retained in the
    # residual -- it is the forecast's constant excess return, precisely what the gate tests.
    residual = (spread_arr - beta * static_arr).tolist()

    residual_passes, residual_ci_lower, residual_ci_upper = frame_gate_passes(
        residual,
        list(cluster_ids),
        min_n,
        bootstrap_max_n,
        bootstrap_batch,
        bootstrap_random_state,
    )
    gate2_passes = bool(residual_passes) and not static_dominates

    return {
        "beta": beta,
        "intercept": intercept,
        "static_r2": static_r2,
        "static_dominates": static_dominates,
        "n_bars": len(spread_values),
        "n_clusters": len(set(cluster_ids)),
        "residual_ci_lower": residual_ci_lower,
        "residual_ci_upper": residual_ci_upper,
        "residual_passes": residual_passes,
        "gate2_passes": gate2_passes,
        "benchmark_kind": "retrospective_time_averaged_membership",
    }


# ---------------------------------------------------------------------------
# Panel query (reproduces the T3 script's `_FV_SQL`, scripts/analysis/
# t3_cross_sectional_long_short_ctf_momentum_check.py lines 63-78, exactly).
# ---------------------------------------------------------------------------
#
# Two fixed substitutions computed ONCE at import, never runtime interpolation of
# caller-supplied values (threat T-167-04): every filter value is bound as a $1/$2 asyncpg
# placeholder, never string-interpolated into the SQL text itself.
_PANEL_SQL_TEMPLATE = """
    SELECT fv.symbol, fv.bar_ts, fv.ctf_momentum,
           fr.return_fast, fr.return_slow
    FROM feature_vectors fv
    JOIN forward_returns fr
      ON fr.symbol = fv.symbol AND fr.tf = fv.tf AND fr.bar_ts = fv.bar_ts
    JOIN instruments i ON i.symbol = fv.symbol
    WHERE fv.tf = $1
      AND fv.ctf_momentum IS NOT NULL
      AND fr.return_type = 'executable_open_to_open'
      AND fr.complete_fast = true
      AND fr.complete_slow = true
      AND i.is_active = true
      AND i.contract_details->>'asset_class' = 'equity'
      {watermark_clause}
    ORDER BY fv.bar_ts ASC
"""

_PANEL_SQL_BACKFILL = _PANEL_SQL_TEMPLATE.format(watermark_clause="")
_PANEL_SQL_INCREMENTAL = _PANEL_SQL_TEMPLATE.format(watermark_clause="AND fv.bar_ts > $2")

# --evaluate-gate mode: read-only queries against already-persisted construction_spreads rows
# and a fresh panel re-select for the live shuffled-ranking null. `one_way_turnover IS NOT
# NULL` excludes the single genuinely-first corpus bar, whose net spread is undefined (design
# decisions, Task 1). Every filter value is bound as an asyncpg placeholder (T-167-04).
_GATE_ROWS_SQL = """
    SELECT bar_ts, bar_ts::date AS cluster_id, gross_spread_fast, gross_spread_slow,
           net_spread_fast_by_cost_bps, net_spread_slow_by_cost_bps
    FROM construction_spreads
    WHERE construction_name = $1 AND tf = $2 AND bar_ts >= $3 AND one_way_turnover IS NOT NULL
"""

# In-sample diagnostic ONLY (design decision 2, NEVER fed into gate1_passes) -- the sole `<`
# comparison against bar_ts in this module. Note the direction: this is the OPPOSITE of
# counterfactual_tracker.py's FRAME-04 in-sample exit gate's `<` on the SAME oos_start value --
# that gate is deliberately in-sample; this OOS gate (_GATE_ROWS_SQL, above) is the opposite
# and must use `>=` (design decision 1).
_GATE_ROWS_IN_SAMPLE_SQL = """
    SELECT bar_ts, bar_ts::date AS cluster_id, gross_spread_fast, gross_spread_slow,
           net_spread_fast_by_cost_bps, net_spread_slow_by_cost_bps
    FROM construction_spreads
    WHERE construction_name = $1 AND tf = $2 AND bar_ts < $3 AND one_way_turnover IS NOT NULL
"""

# Re-selects the raw panel for the OOS window using Plan 03's exact filter set, for the live
# shuffled-ranking null (design decision 4 -- never derived from persisted rows).
_GATE_PANEL_SQL = _PANEL_SQL_TEMPLATE.format(watermark_clause="AND fv.bar_ts >= $2")

# --evaluate-attribution mode (Validation Gate 2): OOS leg-membership + gross-spread rows,
# read-only. Same `one_way_turnover IS NOT NULL` exclusion as _GATE_ROWS_SQL. Ordered so the
# result is directly usable without an extra client-side sort.
_ATTRIBUTION_ROWS_SQL = """
    SELECT bar_ts, bar_ts::date AS cluster_id, long_leg_symbols, short_leg_symbols,
           gross_spread_fast, gross_spread_slow
    FROM construction_spreads
    WHERE construction_name = $1 AND tf = $2 AND bar_ts >= $3 AND one_way_turnover IS NOT NULL
    ORDER BY bar_ts ASC
"""

_INSERT_SQL = """
    INSERT INTO construction_spreads (
        construction_name, tf, bar_ts, n_universe, n_leg,
        long_leg_symbols, short_leg_symbols,
        gross_spread_fast, gross_spread_slow,
        one_way_turnover,
        net_spread_fast_by_cost_bps, net_spread_slow_by_cost_bps,
        compute_version
    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
    ON CONFLICT (construction_name, tf, bar_ts) DO NOTHING
"""


class CrossSectionalSpreadTracker(BaseBatch):
    """BaseBatch oneshot: incrementally scans the 15m equity panel, forms the decile spread
    at each bar via Plan 02's pure functions, computes turnover against the previous run's
    persisted leg membership, applies the live cost-hurdle sweep, and writes one
    `construction_spreads` row per bar. See the module docstring's MANUAL/ON-DEMAND ONLY and
    RECOVERY sections for the two load-bearing design decisions this class implements."""

    job_name = "cross-sectional-spread-tracker"
    compute_version = "1.0.0"

    def __init__(self, db_dsn: str, backfill: bool = False) -> None:
        super().__init__(db_dsn)
        self.backfill = backfill

    async def execute(self, pool: asyncpg.Pool) -> None:  # type: ignore[override]
        manifest = CorpusManifest(
            "cross_sectional_spread_tracker", CorpusManifest.DEFAULT_MANIFEST_DIR
        )
        try:
            await self._execute_inner(pool, manifest)
        except Exception as error:
            manifest.add_error(str(error))
            try:
                manifest.write()
            except Exception:
                pass
            raise
        else:
            manifest.mark_success()
            manifest_path = manifest.write()
            self.logger.info(
                "cross_sectional_spread_tracker.manifest_written",
                manifest_path=str(manifest_path),
            )

    async def _execute_inner(self, pool: asyncpg.Pool, manifest: CorpusManifest) -> None:
        async with pool.acquire() as conn:
            # (1) Load APR and validate BEFORE any panel work begins (T-167-01, ASVS V5).
            cfg_dict = await _load_apr(
                conn, extra_like_patterns=["infra.cross_sectional_spread_tracker.%"]
            )
            decile_fraction = _cfg(cfg_dict, "alpha.construction.decile_fraction", 0.10)
            null_shuffles = _cfg(cfg_dict, "alpha.construction.null_shuffles", 40)
            attribution_max_static_r2 = _cfg(
                cfg_dict, "alpha.construction.attribution_max_static_r2", 0.50
            )
            itersize = _cfg(cfg_dict, "infra.cross_sectional_spread_tracker.itersize", 5000)
            chunk_size = _cfg(cfg_dict, "infra.cross_sectional_spread_tracker.chunk_size", 5000)
            cost_bps = _parse_cost_hurdle_bps(cfg_dict)
            validate_construction_config(
                decile_fraction, cost_bps, null_shuffles, attribution_max_static_r2
            )

            # (2) Resolve the watermark. An empty table and an explicit --backfill are the
            # same work (design decisions block, step 2).
            if self.backfill:
                mode = "backfill"
                watermark = None
            else:
                watermark = await conn.fetchval(
                    "SELECT MAX(bar_ts) FROM construction_spreads "
                    "WHERE construction_name = $1 AND tf = $2",
                    _CONSTRUCTION_NAME,
                    _TF,
                )
                mode = "incremental" if watermark is not None else "backfill"

            if mode == "backfill":
                panel_sql = _PANEL_SQL_BACKFILL
                panel_params: tuple[Any, ...] = (_TF,)
            else:
                panel_sql = _PANEL_SQL_INCREMENTAL
                panel_params = (_TF, watermark)

            self.logger.info(
                "cross_sectional_spread_tracker.mode_resolved",
                mode=mode,
                watermark=str(watermark) if watermark is not None else None,
            )

            # (3) Seed prior legs from committed state only (design decision 5 / RESEARCH.md
            # Pattern 2 / Pitfall 4) -- this single query is what makes crash recovery correct.
            prior_row = await conn.fetchrow(
                "SELECT bar_ts, long_leg_symbols, short_leg_symbols FROM construction_spreads "
                "WHERE construction_name = $1 AND tf = $2 ORDER BY bar_ts DESC LIMIT 1",
                _CONSTRUCTION_NAME,
                _TF,
            )
            prior_long: frozenset[str]
            prior_short: frozenset[str]
            if prior_row is None:
                prior_long = frozenset()
                prior_short = frozenset()
                prior_leg_seed_bar_ts = None
                self.logger.info(
                    "cross_sectional_spread_tracker.prior_legs_seeded",
                    source="empty_table",
                    bar_ts=None,
                )
            else:
                prior_long = frozenset(prior_row["long_leg_symbols"])
                prior_short = frozenset(prior_row["short_leg_symbols"])
                prior_leg_seed_bar_ts = prior_row["bar_ts"]
                self.logger.info(
                    "cross_sectional_spread_tracker.prior_legs_seeded",
                    source="persisted_row",
                    bar_ts=str(prior_leg_seed_bar_ts),
                )

            n_panel_rows = 0
            n_bars_processed = 0
            n_bars_skipped_degenerate = 0
            turnovers: list[float] = []
            write_buffer: list[tuple[Any, ...]] = []
            n_written = 0

            async def flush_write_buffer() -> None:
                nonlocal n_written
                if not write_buffer:
                    return
                async with pool.acquire() as wconn:
                    await wconn.executemany(_INSERT_SQL, write_buffer)
                n_written += len(write_buffer)
                write_buffer.clear()

            def process_bar(bar_ts: Any, rows: list[dict[str, Any]]) -> None:
                nonlocal prior_long, prior_short, n_bars_processed, n_bars_skipped_degenerate
                symbols = [r["symbol"] for r in rows]
                feature_values = [r["ctf_momentum"] for r in rows]
                legs = decile_legs(symbols, feature_values, decile_fraction)
                if legs is None:
                    # Too few symbols to form two disjoint legs -- skip the bar entirely,
                    # matching the T3 script's `continue` (design decisions, step 4). Never
                    # logged per-bar (CLAUDE.md: never log per-row inside a loop over the full
                    # corpus) -- counted and reported once at the end of the run.
                    n_bars_skipped_degenerate += 1
                    return
                short_leg, long_leg = legs
                cur_long = frozenset(long_leg)
                cur_short = frozenset(short_leg)
                returns_fast = {r["symbol"]: r["return_fast"] for r in rows}
                returns_slow = {r["symbol"]: r["return_slow"] for r in rows}
                gross_fast = spread_from_legs(returns_fast, long_leg, short_leg)
                gross_slow = spread_from_legs(returns_slow, long_leg, short_leg)
                turnover = one_way_turnover(prior_long, prior_short, cur_long, cur_short)
                net_fast = net_spread_by_cost_bps(gross_fast, turnover, cost_bps)
                net_slow = net_spread_by_cost_bps(gross_slow, turnover, cost_bps)
                write_buffer.append(
                    (
                        _CONSTRUCTION_NAME,
                        _TF,
                        bar_ts,
                        len(symbols),
                        len(long_leg),
                        long_leg,
                        short_leg,
                        gross_fast,
                        gross_slow,
                        turnover,
                        net_fast,
                        net_slow,
                        self.compute_version,
                    )
                )
                if turnover is not None:
                    turnovers.append(turnover)
                n_bars_processed += 1
                prior_long, prior_short = cur_long, cur_short

            # (4) Stream the panel via a server-side cursor -- peak memory stays independent
            # of corpus size (design decision 2). Accumulate the current bar's rows into a
            # small buffer; flush a completed bar the moment bar_ts changes.
            current_bar_ts: Any = None
            current_rows: list[dict[str, Any]] = []

            async with conn.transaction():
                async for record in conn.cursor(panel_sql, *panel_params, prefetch=itersize):
                    n_panel_rows += 1
                    row = dict(record)
                    if current_bar_ts is None:
                        current_bar_ts = row["bar_ts"]
                    if row["bar_ts"] != current_bar_ts:
                        process_bar(current_bar_ts, current_rows)
                        # (5) Persist in chunks, in bar_ts order -- bounds each transaction so
                        # a crash can only ever truncate a contiguous TAIL (design decision 5).
                        if len(write_buffer) >= chunk_size:
                            await flush_write_buffer()
                        current_bar_ts = row["bar_ts"]
                        current_rows = []
                    current_rows.append(row)

                # Never forget to flush the final bar after the cursor is exhausted.
                if current_rows:
                    process_bar(current_bar_ts, current_rows)

            await flush_write_buffer()

            # (6) Report. One summary log line, never per-bar.
            turnover_mean = statistics.fmean(turnovers) if turnovers else None
            turnover_median = statistics.median(turnovers) if turnovers else None
            manifest.set_inputs(
                mode=mode,
                watermark=str(watermark) if watermark is not None else None,
                prior_leg_seed_bar_ts=(
                    str(prior_leg_seed_bar_ts) if prior_leg_seed_bar_ts is not None else None
                ),
                n_panel_rows=n_panel_rows,
                n_bars_processed=n_bars_processed,
                n_bars_skipped_degenerate=n_bars_skipped_degenerate,
                turnover_mean=turnover_mean,
                turnover_median=turnover_median,
            )
            manifest.add_output(table_name="construction_spreads", rows_total=n_written)
            if n_bars_skipped_degenerate > 0:
                # design decision 6: a non-zero degenerate-skip count must be visible in the
                # manifest's status, not only in a log line that rotates away.
                manifest.add_warning(
                    f"{n_bars_skipped_degenerate} bar(s) skipped: too few symbols to form two "
                    "disjoint decile legs"
                )
            self.logger.info(
                "cross_sectional_spread_tracker.run_complete",
                mode=mode,
                n_panel_rows=n_panel_rows,
                n_bars_processed=n_bars_processed,
                n_bars_skipped_degenerate=n_bars_skipped_degenerate,
                n_written=n_written,
                turnover_mean=turnover_mean,
                turnover_median=turnover_median,
            )


# ---------------------------------------------------------------------------
# Validation Gate 1 evaluation (--evaluate-gate CLI mode)
# ---------------------------------------------------------------------------


def _flatten_gate_rows(
    rows: Iterable[Mapping[str, Any]], cost_bps: Sequence[int]
) -> list[dict[str, Any]]:
    """Flatten `construction_spreads` rows into `evaluate_spread_gate`'s input shape: one
    record per (row, scale, cost_bps), with `pnl_r` read from the matching
    `net_spread_*_by_cost_bps` jsonb keyed by `str(cost_bps)` (asyncpg decodes jsonb columns
    to `dict` directly, no `json.loads` needed)."""
    flattened: list[dict[str, Any]] = []
    for row in rows:
        for scale, net_field in (
            ("fast", "net_spread_fast_by_cost_bps"),
            ("slow", "net_spread_slow_by_cost_bps"),
        ):
            net_by_cost = row[net_field]
            if net_by_cost is None:
                continue
            for bps in cost_bps:
                pnl_r = net_by_cost.get(str(bps))
                if pnl_r is None:
                    continue
                flattened.append(
                    {
                        "scale": scale,
                        "cost_bps": bps,
                        "cluster_id": row["cluster_id"],
                        "pnl_r": pnl_r,
                    }
                )
    return flattened


def _build_panel_by_bar(
    panel_rows: Iterable[Mapping[str, Any]], return_col: str
) -> dict[Any, tuple[list[str], list[float], dict[str, float | None]]]:
    """Group flat panel rows (one row per symbol per bar) into `mean_gross_spread_over_bars`'
    / `shuffled_ranking_null_p`'s `panel_by_bar` shape for a single return scale."""
    grouped: dict[Any, list[Mapping[str, Any]]] = {}
    for row in panel_rows:
        grouped.setdefault(row["bar_ts"], []).append(row)
    panel_by_bar: dict[Any, tuple[list[str], list[float], dict[str, float | None]]] = {}
    for bar_ts, bar_rows in grouped.items():
        symbols = [r["symbol"] for r in bar_rows]
        feature_values = [r["ctf_momentum"] for r in bar_rows]
        returns_by_symbol = {r["symbol"]: r[return_col] for r in bar_rows}
        panel_by_bar[bar_ts] = (symbols, feature_values, returns_by_symbol)
    return panel_by_bar


def _gate1_verdict_text(scale: str, binding: dict[str, Any] | None, null_clears: bool) -> str:
    """The three-way verdict distinction from the T3 script's `_run_one_scale`: a genuine
    pass, a CI-clears-but-null-not-distinguishable result (a dollar-neutral construction
    artifact, NOT a pass), or a CI-does-not-clear-zero failure."""
    if binding is None:
        return f"{scale}: no verdict cell at the binding cost tier"
    if binding["passes"] and null_clears:
        return (
            f"{scale}: PASSES real bootstrap CI (ci_lower > 0) AND clears the shuffled-ranking "
            "null (construction, not artifact) -- genuine Gate 1 candidate"
        )
    if binding["passes"] and not null_clears:
        return (
            f"{scale}: bootstrap CI clears zero, but the shuffled-ranking null cannot be "
            "distinguished from the observed result -- likely a dollar-neutral construction "
            "artifact, not real ranking signal. Do not treat as a Gate 1 pass"
        )
    return f"{scale}: does not clear its own bootstrap CI (ci_lower <= 0) -- fails at this scale"


def _parse_cost_hurdle_bps(cfg_dict: Mapping[str, Any]) -> list[int]:
    """`alpha.construction.cost_hurdle_bps_round_trip` is the phase's one json-typed APR key.
    `cfg()`'s `type(default)(val)` cast breaks on a list default (`list("[1,3,5,10]")` splits
    into characters -- Plan 01 design decision 5), so this reads the raw dict value and
    `json.loads`s it directly, falling back to the seeded default when absent."""
    raw_cost_bps = cfg_dict.get("alpha.construction.cost_hurdle_bps_round_trip")
    return json.loads(raw_cost_bps) if raw_cost_bps is not None else [1, 3, 5, 10]


async def _open_evaluation_connection(db_dsn: str) -> asyncpg.Connection:
    """Bare `asyncpg.connect` for a read-only reporting branch (no pool -- mirrors
    `counterfactual_tracker`'s evaluation-mode connections). `_setup_codecs` MUST be called
    explicitly here: unlike `BaseBatch`'s pooled `create_pool()`, a bare connection has no
    JSONB type codec registered, so jsonb columns come back as raw JSON text rather than
    `dict` (the bug Task 2 hit and fixed on this service's first live `--evaluate-gate` run)."""
    conn = await asyncpg.connect(db_dsn)
    await _setup_codecs(conn)
    return conn


async def _load_gate_evaluation_context(conn: asyncpg.Connection, mode_flag: str) -> dict[str, Any]:
    """Load and validate the APR values both `--evaluate-gate` and `--evaluate-attribution`
    need before any panel work begins (T-167-01, ASVS V5), plus the OOS boundary both modes
    gate on. `mode_flag` (e.g. `"--evaluate-gate"`) names the caller in the missing-boundary
    error message only -- the query and validation are identical for both modes."""
    cfg_dict = await _load_apr(conn)
    min_n = _cfg(cfg_dict, "alpha.scoring.min_strategy_n", 30)
    bootstrap_max_n = _cfg(cfg_dict, "alpha.scoring.bootstrap_max_n", 5000)
    bootstrap_batch = _cfg(cfg_dict, "alpha.scoring.bootstrap_batch", 1000)
    bootstrap_random_state = _cfg(
        cfg_dict, "alpha.scoring.bootstrap_random_state", _DEFAULT_BOOTSTRAP_RANDOM_STATE
    )
    decile_fraction = _cfg(cfg_dict, "alpha.construction.decile_fraction", 0.10)
    attribution_max_static_r2 = _cfg(cfg_dict, "alpha.construction.attribution_max_static_r2", 0.50)
    null_shuffles = _cfg(cfg_dict, "alpha.construction.null_shuffles", 40)
    cost_bps = _parse_cost_hurdle_bps(cfg_dict)
    validate_construction_config(
        decile_fraction, cost_bps, null_shuffles, attribution_max_static_r2
    )

    oos_start = await conn.fetchval(
        "SELECT config_value::timestamptz FROM config_state "
        "WHERE config_key = 'alpha.validation.oos_start'"
    )
    if oos_start is None:
        raise RuntimeError(
            f"cross_sectional_spread_tracker {mode_flag} FAILED: "
            "alpha.validation.oos_start is not set in config_state -- a missing OOS "
            "boundary would silently exclude every row from the gate "
            "(bar_ts >= NULL never matches)."
        )

    return {
        "min_n": min_n,
        "bootstrap_max_n": bootstrap_max_n,
        "bootstrap_batch": bootstrap_batch,
        "bootstrap_random_state": bootstrap_random_state,
        "decile_fraction": decile_fraction,
        "attribution_max_static_r2": attribution_max_static_r2,
        "null_shuffles": null_shuffles,
        "cost_bps": cost_bps,
        "oos_start": oos_start,
    }


async def _run_evaluate_gate(db_dsn: str) -> None:
    """--evaluate-gate CLI mode: Validation Gate 1 -- a day-clustered bootstrap CI over the
    persisted net-of-cost spread across the OOS window (`bar_ts >= alpha.validation.oos_start`,
    design decision 1), at every cost tier and both lookahead scales, plus a live
    shuffled-ranking null, plus a labeled in-sample diagnostic. Mirrors
    `counterfactual_tracker._run_evaluate_gate`'s shape exactly: a plain `asyncpg.connect`
    (not a pool -- this is a read-only reporting branch). No D-06 `job_completed_total`
    emission -- this performs no persistence, unlike `CrossSectionalSpreadTracker.execute()`.
    The only filesystem side effect is the verdict artifact written by
    `write_verdict_artifact`; no `construction_spreads` row is ever written here.
    """
    conn = await _open_evaluation_connection(db_dsn)
    try:
        # (1) Load and validate APR, and resolve the OOS boundary, BEFORE any panel work
        # begins (T-167-01, ASVS V5).
        ctx = await _load_gate_evaluation_context(conn, "--evaluate-gate")
        min_n = ctx["min_n"]
        bootstrap_max_n = ctx["bootstrap_max_n"]
        bootstrap_batch = ctx["bootstrap_batch"]
        bootstrap_random_state = ctx["bootstrap_random_state"]
        decile_fraction = ctx["decile_fraction"]
        attribution_max_static_r2 = ctx["attribution_max_static_r2"]
        null_shuffles = ctx["null_shuffles"]
        cost_bps = ctx["cost_bps"]
        oos_start = ctx["oos_start"]

        # (2) OOS segment -- the gate. `bar_ts >= oos_start` (design decision 1: the OPPOSITE
        # direction of counterfactual_tracker's FRAME-04 in-sample exit gate, which uses `<`
        # on the same boundary).
        oos_gate_rows = [
            dict(r) for r in await conn.fetch(_GATE_ROWS_SQL, _CONSTRUCTION_NAME, _TF, oos_start)
        ]
        oos_flattened = _flatten_gate_rows(oos_gate_rows, cost_bps)
        oos_verdicts = evaluate_spread_gate(
            oos_flattened, min_n, bootstrap_max_n, bootstrap_batch, bootstrap_random_state
        )
        for verdict in oos_verdicts:
            _logger.info("cross_sectional_spread_tracker.gate_verdict", segment="oos", **verdict)

        # (3) Live shuffled-ranking null (design decision 4: recomputed from the raw panel
        # every run, never derived from persisted rows). Fetched once, `panel_by_bar` built
        # once per scale.
        panel_rows = [dict(r) for r in await conn.fetch(_GATE_PANEL_SQL, _TF, oos_start)]

        # (4) In-sample diagnostic segment (design decision 2): a clearly labeled diagnostic,
        # NEVER fed into gate1_passes. Exists solely to make the T3 script's published
        # full-2006-2026-history numbers comparable to this OOS verdict. Fetched here, before
        # the connection closes, alongside the OOS query above.
        in_sample_gate_rows = [
            dict(r)
            for r in await conn.fetch(_GATE_ROWS_IN_SAMPLE_SQL, _CONSTRUCTION_NAME, _TF, oos_start)
        ]
    finally:
        await conn.close()

    in_sample_flattened = _flatten_gate_rows(in_sample_gate_rows, cost_bps)
    in_sample_verdicts = evaluate_spread_gate(
        in_sample_flattened, min_n, bootstrap_max_n, bootstrap_batch, bootstrap_random_state
    )
    for verdict in in_sample_verdicts:
        _logger.info(
            "cross_sectional_spread_tracker.gate_verdict",
            segment="in_sample_diagnostic",
            **verdict,
        )

    null_by_scale: dict[str, dict[str, Any]] = {}
    for scale, return_col in (("fast", "return_fast"), ("slow", "return_slow")):
        panel_by_bar = _build_panel_by_bar(panel_rows, return_col)
        observed_mean, observed_n_eligible_bars = mean_gross_spread_over_bars(
            panel_by_bar, decile_fraction
        )
        if observed_mean is None:
            raise RuntimeError(
                "cross_sectional_spread_tracker --evaluate-gate FAILED: no eligible bars in "
                f"the OOS panel for scale={scale!r} -- cannot compute the shuffled-ranking null"
            )
        null_p, null_mean, null_std, null_n_eligible_bars = shuffled_ranking_null_p(
            panel_by_bar, decile_fraction, observed_mean, null_shuffles, bootstrap_random_state
        )
        if null_n_eligible_bars != observed_n_eligible_bars:
            raise RuntimeError(
                "cross_sectional_spread_tracker --evaluate-gate FAILED: null eligible-bar "
                f"count ({null_n_eligible_bars}) != observed eligible-bar count "
                f"({observed_n_eligible_bars}) for scale={scale!r} -- the null and the "
                "observed value are being averaged over different bar sets, which would "
                "silently invalidate the Gate 1 null verdict (design decision 6)"
            )
        null_by_scale[scale] = {
            "null_p": null_p,
            "null_mean": null_mean,
            "null_std": null_std,
            "n_shuffles": null_shuffles,
            "n_eligible_bars": null_n_eligible_bars,
            "observed_mean_gross_spread": observed_mean,
        }
        _logger.info(
            "cross_sectional_spread_tracker.null_check",
            scale=scale,
            null_p=null_p,
            null_mean=null_mean,
            null_std=null_std,
            n_shuffles=null_shuffles,
            n_eligible_bars=null_n_eligible_bars,
        )

    # (5) Binding Gate 1 verdict (design decision 3, single source of truth): Gate 1 passes
    # iff, at max(cost_bps), BOTH the fast and slow cells have passes is True, AND both
    # scales' null_p is strictly below 0.05.
    binding_cost_bps = max(cost_bps)
    binding_by_scale = {v["scale"]: v for v in oos_verdicts if v["cost_bps"] == binding_cost_bps}
    fast_binding = binding_by_scale.get("fast")
    slow_binding = binding_by_scale.get("slow")
    fast_passes = bool(fast_binding is not None and fast_binding["passes"] is True)
    slow_passes = bool(slow_binding is not None and slow_binding["passes"] is True)
    fast_null_clears = null_by_scale["fast"]["null_p"] < 0.05
    slow_null_clears = null_by_scale["slow"]["null_p"] < 0.05
    gate1_passes = fast_passes and slow_passes and fast_null_clears and slow_null_clears

    verdict_text = " | ".join(
        [
            _gate1_verdict_text("fast", fast_binding, fast_null_clears),
            _gate1_verdict_text("slow", slow_binding, slow_null_clears),
        ]
    )

    _logger.info(
        "cross_sectional_spread_tracker.gate1_summary",
        gate1_passes=gate1_passes,
        binding_cost_bps=binding_cost_bps,
        fast_ci_lower=fast_binding["ci_lower"] if fast_binding else None,
        fast_ci_upper=fast_binding["ci_upper"] if fast_binding else None,
        fast_n_bars=fast_binding["n_bars"] if fast_binding else None,
        fast_n_clusters=fast_binding["n_clusters"] if fast_binding else None,
        slow_ci_lower=slow_binding["ci_lower"] if slow_binding else None,
        slow_ci_upper=slow_binding["ci_upper"] if slow_binding else None,
        slow_n_bars=slow_binding["n_bars"] if slow_binding else None,
        slow_n_clusters=slow_binding["n_clusters"] if slow_binding else None,
        fast_null_p=null_by_scale["fast"]["null_p"],
        slow_null_p=null_by_scale["slow"]["null_p"],
        verdict_text=verdict_text,
    )

    # (6) Assemble and persist the ENTIRE verdict as durable strict JSON before any human
    # transcribes it (T-167-17, design decision 7).
    payload: dict[str, Any] = {
        "gate1_passes": gate1_passes,
        "binding_cost_bps": binding_cost_bps,
        "verdict_text": verdict_text,
        "oos_grid": oos_verdicts,
        "in_sample_diagnostic_grid": in_sample_verdicts,
        "null_by_scale": null_by_scale,
        "oos_start": str(oos_start),
        "n_oos_rows": len(oos_gate_rows),
        "n_oos_day_clusters": len({row["cluster_id"] for row in oos_flattened}),
        "apr": {
            "decile_fraction": decile_fraction,
            "cost_hurdle_bps_round_trip": cost_bps,
            "null_shuffles": null_shuffles,
            "attribution_max_static_r2": attribution_max_static_r2,
            "alpha.scoring.min_strategy_n": min_n,
            "alpha.scoring.bootstrap_max_n": bootstrap_max_n,
            "alpha.scoring.bootstrap_batch": bootstrap_batch,
            "alpha.scoring.bootstrap_random_state": bootstrap_random_state,
        },
        "compute_version": CrossSectionalSpreadTracker.compute_version,
    }
    artifact_path = write_verdict_artifact("gate1", payload)
    _logger.info(
        "cross_sectional_spread_tracker.gate1_verdict_artifact_written",
        artifact_path=str(artifact_path),
    )

    manifest = CorpusManifest(
        "cross_sectional_spread_tracker_gate", CorpusManifest.DEFAULT_MANIFEST_DIR
    )
    manifest.set_inputs(
        n_cells=len(oos_verdicts), oos_start=str(oos_start), gate1_passes=gate1_passes
    )
    manifest.add_output(
        table_name="construction_spreads_gate_verdicts", rows_total=len(oos_verdicts)
    )
    manifest.mark_success()
    manifest.write()
    # No D-06 job_completed_total emission -- this performs no persistence (mirrors
    # counterfactual_tracker._run_evaluate_gate's own explicit no-persistence contract).


# ---------------------------------------------------------------------------
# Validation Gate 2 evaluation (--evaluate-attribution CLI mode)
# ---------------------------------------------------------------------------

# design decision 8: the literal caveat carried into every gate2_summary log line and verdict
# artifact -- a surviving residual falsifies the static-tilt explanation without establishing
# what does explain the return.
_ATTRIBUTION_INTERPRETATION_CAVEAT = (
    "The static-tilt benchmark is a retrospective, time-averaged summary of realized leg "
    "membership over the same window whose returns it is used to explain, not a live or "
    "causal decomposition of the strategy's mechanism. A surviving residual therefore "
    "falsifies the static-tilt explanation without establishing what does explain the return."
)


def _attribution_verdict_text(scale: str, verdict: dict[str, Any]) -> str:
    """The three-way Gate 2 verdict distinction, in the design doc's own terms (design
    decision 8's PASS-wording constraint applies here: the PASS branch states only that the
    P&L is "not explained by a static tilt," never that it is caused by or attributable to the
    forecast -- this test cannot establish the latter."""
    if verdict["gate2_passes"]:
        return (
            f"{scale}: PASS -- the residual clears zero at 95% CI (ci_lower="
            f"{verdict['residual_ci_lower']:.6f}) and a fixed membership does not explain "
            f"most of the spread (static_r2={verdict['static_r2']:.3f}); the P&L is not "
            "explained by a static tilt"
        )
    if verdict["static_dominates"]:
        return (
            f"{scale}: FAIL, static tilt -- a fixed membership explains "
            f"static_r2={verdict['static_r2']:.3f} of the spread, above the configured "
            "ceiling, so the 'forecast' is a factor exposure in disguise (edge thesis T4); "
            "cap expectations accordingly"
        )
    return (
        f"{scale}: FAIL, no residual -- after removing the static component nothing survives "
        f"at 95% CI (residual_ci_lower={verdict['residual_ci_lower']:.6f})"
    )


async def _run_evaluate_attribution(db_dsn: str) -> None:
    """--evaluate-attribution CLI mode: Validation Gate 2 -- attribution honesty. Decomposes
    the realized OOS spread (`bar_ts >= alpha.validation.oos_start`) into a static,
    time-invariant leg-membership benchmark plus a residual, then gates the residual through
    the SAME day-clustered bootstrap Gate 1 uses (`counterfactual_tracker.frame_gate_passes`,
    reused verbatim via `attribution_verdict` -- no new bootstrap machinery). Structured
    exactly like `_run_evaluate_gate`: a plain `asyncpg.connect` (not a pool -- this is a
    read-only reporting branch), no database writes, no D-06 `job_completed_total` emission --
    this performs no persistence, unlike `CrossSectionalSpreadTracker.execute()`. The only
    filesystem side effect is the verdict artifact written by `write_verdict_artifact`; no
    `construction_spreads` row is ever written here.
    """
    conn = await _open_evaluation_connection(db_dsn)
    try:
        # (1) Load and validate APR, and resolve the OOS boundary, BEFORE any panel work
        # begins (T-167-01, ASVS V5).
        ctx = await _load_gate_evaluation_context(conn, "--evaluate-attribution")
        min_n = ctx["min_n"]
        bootstrap_max_n = ctx["bootstrap_max_n"]
        bootstrap_batch = ctx["bootstrap_batch"]
        bootstrap_random_state = ctx["bootstrap_random_state"]
        decile_fraction = ctx["decile_fraction"]
        attribution_max_static_r2 = ctx["attribution_max_static_r2"]
        null_shuffles = ctx["null_shuffles"]
        cost_bps = ctx["cost_bps"]
        oos_start = ctx["oos_start"]

        # (2) OOS leg-membership + gross-spread rows -- the source of both the static tilt
        # weights and the dependent variable being regressed.
        attribution_rows = [
            dict(r)
            for r in await conn.fetch(_ATTRIBUTION_ROWS_SQL, _CONSTRUCTION_NAME, _TF, oos_start)
        ]
        # (3) Raw OOS panel for the return series -- same query Gate 1's null check uses.
        panel_rows = [dict(r) for r in await conn.fetch(_GATE_PANEL_SQL, _TF, oos_start)]
    finally:
        await conn.close()

    if not attribution_rows:
        raise RuntimeError(
            "cross_sectional_spread_tracker --evaluate-attribution FAILED: no OOS "
            "construction_spreads rows found -- run --backfill or the incremental pass first."
        )

    # (4) Static bucket membership: scale-independent, computed once over the OOS leg history.
    weights = static_tilt_weights(attribution_rows)

    attribution_rows_by_bar = {row["bar_ts"]: row for row in attribution_rows}

    verdict_by_scale: dict[str, dict[str, Any]] = {}
    for scale, return_col, gross_col in (
        ("fast", "return_fast", "gross_spread_fast"),
        ("slow", "return_slow", "gross_spread_slow"),
    ):
        panel_by_bar = _build_panel_by_bar(panel_rows, return_col)
        returns_map_by_bar = {bar_ts: v[2] for bar_ts, v in panel_by_bar.items()}

        # (5) Restrict to the INTERSECTION of bar_ts present in both sources (and to bars
        # whose gross spread at this scale is non-NULL) before regressing -- a bar present in
        # one source and not the other would misalign the series. `attribution_verdict`'s own
        # length/duplicate/ordering checks (design decision 9) are the second line of defense,
        # not the first.
        eligible_bar_ts = sorted(
            bar_ts
            for bar_ts in (set(attribution_rows_by_bar) & set(returns_map_by_bar))
            if attribution_rows_by_bar[bar_ts][gross_col] is not None
        )
        n_attribution_rows = len(attribution_rows_by_bar)
        n_panel_bars = len(returns_map_by_bar)
        n_intersection = len(eligible_bar_ts)
        _logger.info(
            "cross_sectional_spread_tracker.attribution_intersection",
            scale=scale,
            n_attribution_rows=n_attribution_rows,
            n_panel_bars=n_panel_bars,
            n_intersection=n_intersection,
        )

        intersection_panel = {bar_ts: returns_map_by_bar[bar_ts] for bar_ts in eligible_bar_ts}
        # (6) Build all four parallel sequences in ONE ordered pass over the sorted
        # intersection, so spread/static/cluster/bar-key cannot drift relative to each other.
        static_bar_ts_list, static_values = static_tilt_series(intersection_panel, weights)
        spread_values = [
            attribution_rows_by_bar[bar_ts][gross_col] for bar_ts in static_bar_ts_list
        ]
        cluster_ids = [
            attribution_rows_by_bar[bar_ts]["cluster_id"] for bar_ts in static_bar_ts_list
        ]
        bar_keys = static_bar_ts_list

        verdict = attribution_verdict(
            spread_values,
            static_values,
            cluster_ids,
            bar_keys,
            attribution_max_static_r2,
            min_n,
            bootstrap_max_n,
            bootstrap_batch,
            bootstrap_random_state,
        )
        verdict_by_scale[scale] = verdict
        _logger.info(
            "cross_sectional_spread_tracker.attribution_verdict",
            scale=scale,
            segment="oos",
            max_static_r2=attribution_max_static_r2,
            **verdict,
        )

    # (7) Binding Gate 2 verdict (design decision 7): both scales' gate2_passes must be true.
    gate2_passes_overall = bool(
        verdict_by_scale["fast"]["gate2_passes"] and verdict_by_scale["slow"]["gate2_passes"]
    )
    verdict_text = " | ".join(
        [
            _attribution_verdict_text("fast", verdict_by_scale["fast"]),
            _attribution_verdict_text("slow", verdict_by_scale["slow"]),
        ]
    )

    _logger.info(
        "cross_sectional_spread_tracker.gate2_summary",
        gate2_passes_overall=gate2_passes_overall,
        fast_static_r2=verdict_by_scale["fast"]["static_r2"],
        slow_static_r2=verdict_by_scale["slow"]["static_r2"],
        fast_residual_ci_lower=verdict_by_scale["fast"]["residual_ci_lower"],
        slow_residual_ci_lower=verdict_by_scale["slow"]["residual_ci_lower"],
        benchmark_kind="retrospective_time_averaged_membership",
        verdict_text=verdict_text,
        interpretation_caveat=_ATTRIBUTION_INTERPRETATION_CAVEAT,
    )

    # (8) Assemble and persist the ENTIRE verdict as durable strict JSON before any human
    # transcribes it (T-167-17), reusing Plan 04's helper unchanged.
    n_oos_day_clusters = len({row["cluster_id"] for row in attribution_rows})
    payload: dict[str, Any] = {
        "gate2_passes_overall": gate2_passes_overall,
        "verdict_by_scale": verdict_by_scale,
        "max_static_r2": attribution_max_static_r2,
        "static_tilt_weights": weights,
        "oos_start": str(oos_start),
        "n_oos_rows": len(attribution_rows),
        "n_oos_day_clusters": n_oos_day_clusters,
        "benchmark_kind": "retrospective_time_averaged_membership",
        "interpretation_caveat": _ATTRIBUTION_INTERPRETATION_CAVEAT,
        "compute_version": CrossSectionalSpreadTracker.compute_version,
        "verdict_text": verdict_text,
    }
    artifact_path = write_verdict_artifact("gate2", payload)
    _logger.info(
        "cross_sectional_spread_tracker.gate2_verdict_artifact_written",
        artifact_path=str(artifact_path),
    )

    manifest = CorpusManifest(
        "cross_sectional_spread_tracker_attribution", CorpusManifest.DEFAULT_MANIFEST_DIR
    )
    manifest.set_inputs(
        n_cells=len(verdict_by_scale),
        oos_start=str(oos_start),
        gate2_passes_overall=gate2_passes_overall,
    )
    manifest.add_output(
        table_name="construction_spreads_attribution_verdicts", rows_total=len(verdict_by_scale)
    )
    manifest.mark_success()
    manifest.write()
    # No D-06 job_completed_total emission -- this performs no persistence (mirrors
    # _run_evaluate_gate's own explicit no-persistence contract).


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description=(
            "Cross-Sectional Spread Tracker -- builds the T3 dollar-neutral decile "
            "long-short construction (D-03/D-04)"
        )
    )
    # Mutually exclusive: a write pass (--backfill) and either read-only gate can never be
    # requested in the same invocation -- an operator would otherwise silently get only one.
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--backfill",
        action="store_true",
        help=(
            "Process the full 2006-2026 corpus in one pass. Correct only for the first run "
            "or immediately after a construction_spreads truncate -- incremental mode is the "
            "correct choice for every subsequent invocation."
        ),
    )
    mode_group.add_argument(
        "--evaluate-gate",
        action="store_true",
        help=(
            "Evaluate Validation Gate 1 over bar_ts >= alpha.validation.oos_start per "
            "(lookahead scale, cost tier) via the day-clustered bootstrap plus a live "
            "shuffled-ranking null. Writes a JSON verdict artifact under "
            "logs/construction_verdicts/. Read-only -- writes no construction_spreads rows."
        ),
    )
    mode_group.add_argument(
        "--evaluate-attribution",
        action="store_true",
        help=(
            "Evaluate Validation Gate 2 (attribution honesty) over "
            "bar_ts >= alpha.validation.oos_start by regressing the realized spread on a "
            "static, time-invariant leg-membership benchmark and gating the residual through "
            "the same day-clustered bootstrap Gate 1 uses. The benchmark is retrospective, "
            "not causal. Writes a JSON verdict artifact under logs/construction_verdicts/. "
            "Read-only -- writes no construction_spreads rows."
        ),
    )
    args = parser.parse_args()

    try:
        init_otel_providers("indicagent-cross-sectional-spread-tracker")
    except OTelInitError as error:
        _logger.warning("cross_sectional_spread_tracker.otel_init_failed", error=str(error))

    settings = Settings()
    db_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")

    if args.evaluate_gate:
        asyncio.run(_run_evaluate_gate(db_dsn))
    elif args.evaluate_attribution:
        asyncio.run(_run_evaluate_attribution(db_dsn))
    else:
        asyncio.run(CrossSectionalSpreadTracker(db_dsn, backfill=args.backfill).run())
