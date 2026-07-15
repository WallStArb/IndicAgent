"""Regime boundary-churn materiality diagnostic (todo 080 / L5-1 Phase 0).

Read-only. Measures whether hard-argmax cross-sectional regime-label boundary crossings
are a materially destructive source of alpha_score discontinuity, per a pre-committed
decision gate, BEFORE any soft-blending scoring mechanism is designed. See
docs/plans/2026-07-15-regime-boundary-churn-diagnostic-design.md for full rationale.

Decision gate, per (regime_group, tf) -- both required:
  1. Boundary-adjacent timestamps are >= BOUNDARY_ADJACENT_FRACTION_GATE of all timestamps.
  2. Median boundary-crossing effect size >= EFFECT_SIZE_MULTIPLIER_GATE x the clean
     (same-regime-only) bar-to-bar alpha_score noise floor.

V1 scope: regime_group='equity' only -- matches ensemble_trainer.py's current hardcoded
scope (not yet regime_group-aware). 'rates' has no trained ensemble_weights; cells with no
trained weights report via the untrained-neighbor path (Task 8), not a separate code path.

Results reflect whichever ensemble_weights/ensemble_alpha are live when this runs --
preliminary, cheap to re-run after any corpus refresh, not a permanent verdict.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Any

import asyncpg  # noqa: E402
import numpy as np

from services.cross_sectional_regime_model import _bucket  # noqa: E402
from src.intelligence.regime_signals.breadth_vol import PROB_KEYS, build_tiers  # noqa: E402

# Sample size target across all timeframes combined (~50k rows gives ample power for a
# median-based effect-size comparison without pulling the full corpus).
SAMPLE_SIZE_TARGET = 50_000
# Hard cap per tf so one large timeframe (5m) can't starve smaller ones (1d) of
# representation in the proportional allocation.
HARD_CAP_PER_TF = 20_000
# Boundary window = this many multiples of the signal's own median bar-to-bar step size.
# Self-calibrating: generalizes across bounded [0,1] signals (vix_pct, breadth_frac) and
# unbounded z-scores (curve_z, credit_z) without group-specific window logic.
WINDOW_STEP_MULTIPLIER = 2.0
# Decision gate criterion 1: boundary-adjacent timestamps must be at least this fraction of
# all timestamps in a (regime_group, tf) cell for the churn effect to be aggregately material.
BOUNDARY_ADJACENT_FRACTION_GATE = 0.05
# Decision gate criterion 2: median boundary-crossing effect size must exceed this multiple
# of the clean noise floor to be distinguishable from ordinary feature-driven movement.
EFFECT_SIZE_MULTIPLIER_GATE = 1.5

TFS: tuple[str, ...] = ("5m", "15m", "1h", "1d")
REGIME_GROUP = "equity"

# Scoped to REGIME_GROUP (V1: 'equity' only, see module docstring). regime_prob_vector
# stores the two raw continuous signal values that fed hard bucketing (NOT a posterior --
# see design doc), keyed prob_keys[0]/prob_keys[1] == PROB_KEYS from breadth_vol.py.
_REGIME_SERIES_SQL = """
    SELECT ts, regime_label,
           (regime_prob_vector->>$1)::double precision AS sig1,
           (regime_prob_vector->>$2)::double precision AS sig2
    FROM market_regimes
    WHERE regime_group = 'equity' AND tf = $3
    ORDER BY ts
"""

# Per-feature signed weight (weight * ic_sign) for every trained regime in one tf. ic_sign
# lives only in feature_ic_scores, not ensemble_weights.
#
# {ic_input_column} is the ONE piece of production-selection logic this reconstructs: which
# feature_ic_scores row ensemble_trainer.py actually used. select_features_per_stratum picks,
# per feature, the row with the HIGHEST quality_weight across every (lookahead_bars,
# training_window_end) combination on record -- not the most recent training_window_end (a
# feature's IC estimate, and even its sign, can differ across training windows, and this is
# exactly the marginal/weak-signal population this diagnostic exists to scrutinize). But
# ensemble_weights.ic_sharpe is stored as EXACTLY that winning row's ic_input_column value,
# copied verbatim with no arithmetic (ensemble_trainer.py: `float(ic_sharpes[i])` where
# ic_sharpes[i] = selected[i]["ic_sharpe"] = the raw ic_input_column value) -- so joining on
# fic.{ic_input_column} = ew.ic_sharpe (exact float equality, safe here since no computation
# separates the two values) uniquely identifies the actual winning row, regardless of which
# training_window_end it came from. The trailing ORDER BY training_window_end DESC is a
# defensive tiebreak only (not the selection mechanism) -- for the extremely unlikely case
# where two different training windows produce a bit-identical statistic by coincidence, this
# guarantees a deterministic pick instead of an arbitrary one. ic_input_column is never user
# input -- it's resolved by ensemble_trainer.py's own _resolve_ic_input_column() from a fixed
# 2-value enum (_IC_INPUT_COLUMNS), safe to interpolate.
_SIGNED_WEIGHTS_SQL_TEMPLATE = """
    SELECT ew.regime, ew.feature_name, ew.weight, fic.ic_sign
    FROM ensemble_weights ew
    JOIN LATERAL (
        SELECT ic_sign
        FROM feature_ic_scores fic
        WHERE fic.tf = ew.tf AND fic.regime = ew.regime
          AND fic.feature_name = ew.feature_name AND fic.lookahead_bars = ew.lookahead_bars
          AND fic.symbol = 'POOLED' AND fic.feature_status_at_eval = 'active'
          AND fic.{ic_input_column} = ew.ic_sharpe
        ORDER BY fic.training_window_end DESC
        LIMIT 1
    ) fic ON true
    WHERE ew.symbol = 'UNIVERSE' AND ew.tf = $1 AND ew.weight_version = $2
"""

# Bar-to-bar |delta alpha_score| for consecutive bars of the SAME symbol where the
# cross-sectional regime_label did NOT change -- the clean noise floor, deliberately
# excluding every transition bar so it can't be contaminated by the churn effect it's
# meant to be the baseline for.
_CLEAN_NOISE_FLOOR_SQL = """
    WITH ordered AS (
        SELECT
            ea.symbol, ea.bar_ts, ea.alpha_score, mr.regime_label,
            LAG(ea.alpha_score) OVER (PARTITION BY ea.symbol ORDER BY ea.bar_ts) AS prev_alpha_score,
            LAG(mr.regime_label) OVER (PARTITION BY ea.symbol ORDER BY ea.bar_ts) AS prev_regime_label
        FROM ensemble_alpha ea
        JOIN market_regimes mr
          ON mr.regime_group = 'equity' AND mr.tf = ea.tf AND mr.ts = ea.bar_ts
        WHERE ea.tf = $1 AND ea.weight_version = $2
    )
    SELECT abs(alpha_score - prev_alpha_score) AS delta
    FROM ordered
    WHERE prev_alpha_score IS NOT NULL AND regime_label = prev_regime_label
"""


async def fetch_regime_series(conn: asyncpg.Connection, tf: str) -> list[asyncpg.Record]:
    """One row per (REGIME_GROUP, tf, ts): ts, regime_label, sig1, sig2. Ordered by ts."""
    return await conn.fetch(_REGIME_SERIES_SQL, PROB_KEYS[0], PROB_KEYS[1], tf)


async def fetch_signed_weights_by_regime(
    conn: asyncpg.Connection, tf: str, weight_version: str, ic_input_column: str
) -> tuple[dict[str, dict[str, float]], int]:
    """{regime_label: {feature_name: weight * ic_sign}} for every trained regime in tf, plus
    a count of features skipped because the exact-match join found no ic_sign (see
    _SIGNED_WEIGHTS_SQL_TEMPLATE's docstring for why the join should normally always find
    one). select_features_per_stratum only ever selects rows with a non-null ic_sign, so a
    miss here is an anomaly worth surfacing, not something to silently guess a sign for --
    skip the feature rather than default to +1 and risk treating a contrarian feature as
    non-contrarian.

    ic_input_column must be one of ensemble_trainer.py's _IC_INPUT_COLUMNS values
    ("ic_sharpe_hac" or "ic_shrunk") -- never raw user input.
    """
    sql = _SIGNED_WEIGHTS_SQL_TEMPLATE.format(ic_input_column=ic_input_column)
    rows = await conn.fetch(sql, tf, weight_version)
    result: dict[str, dict[str, float]] = {}
    n_skipped_null_sign = 0
    for row in rows:
        if row["ic_sign"] is None:
            n_skipped_null_sign += 1
            continue
        regime_dict = result.setdefault(row["regime"], {})
        regime_dict[row["feature_name"]] = float(row["weight"]) * float(row["ic_sign"])
    return result, n_skipped_null_sign


async def fetch_clean_noise_floor(conn: asyncpg.Connection, tf: str, weight_version: str) -> float:
    """Median |delta alpha_score| across same-symbol, same-regime-label consecutive bars."""
    rows = await conn.fetch(_CLEAN_NOISE_FLOOR_SQL, tf, weight_version)
    deltas = np.array([float(r["delta"]) for r in rows], dtype=float)
    if len(deltas) == 0:
        return 0.0
    return float(np.median(deltas))


async def load_equity_tiers(cfg: Any) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Tier cut points for the equity group, via the exact production function --
    never retyped, so this can't silently drift from what cross_sectional_regime_model.py
    actually applies. APR namespace is 'alpha.equity_regime' -- the equity group's
    params_prefix in cross_sectional_regime_model.py's group config (migration 229 renamed
    this from the pre-Phase-144 'alpha.regime.*' shape; confirmed live in config_state).

    Uses ConfigService.get() (async, DB-backed on cache miss), not get_sync() -- get_sync()
    only reads an already-warmed in-memory cache and silently returns the default on a cold
    cache, which would defeat the point of reading live APR values here. This script is
    async top-to-bottom with no hot-path constraint that would justify get_sync().
    """
    params = {
        "vix_low_pct": await cfg.get("alpha.equity_regime.vix_low_pct", 0.33),
        "vix_high_pct": await cfg.get("alpha.equity_regime.vix_high_pct", 0.67),
        "breadth_bear": await cfg.get("alpha.equity_regime.breadth_bear", 0.40),
        "breadth_bull": await cfg.get("alpha.equity_regime.breadth_bull", 0.60),
    }
    return build_tiers(params)


@dataclass(frozen=True)
class BoundaryAdjacency:
    axis1_adjacent: bool
    axis2_adjacent: bool
    actual_label: str
    neighbor_labels: tuple[str, ...]


@dataclass(frozen=True)
class AlignedWeights:
    feature_names: tuple[str, ...]
    signed_weights_a: np.ndarray
    signed_weights_b: np.ndarray


@dataclass(frozen=True)
class CellVerdict:
    regime_group: str
    tf: str
    boundary_adjacent_fraction: float
    n_boundary_adjacent_timestamps: int
    n_total_timestamps: int
    median_effect_size: float
    clean_noise_floor: float
    n_untrained_neighbor_bars: int
    n_scored_bars: int
    criterion_1_pass: bool
    criterion_2_pass: bool
    overall_pass: bool


def derive_boundary_window(
    step_series: np.ndarray, multiplier: float = WINDOW_STEP_MULTIPLIER
) -> float:
    """Median absolute bar-to-bar step size of a regime signal, scaled by multiplier.

    Self-calibrating boundary window: derived from the signal's own typical movement
    rather than an externally imposed percentage, so it generalizes to both bounded [0,1]
    signals and unbounded z-scores without group-specific logic.
    """
    if len(step_series) < 2:
        return 0.0
    steps = np.abs(np.diff(step_series))
    return float(np.median(steps)) * multiplier


def _neighbors_across_axis(
    value: float, tiers: list[tuple[str, float]], window: float
) -> list[str]:
    """Tier names reachable by crossing a boundary within `window` of `value`.

    Loops every boundary (not just the two flanking value's own tier) so a narrow middle
    tier with a wide window correctly reports both neighbors, not just one.
    """
    boundaries = [upper for _, upper in tiers[:-1]]
    names = [name for name, _ in tiers]
    neighbors: list[str] = []
    for i, boundary in enumerate(boundaries):
        if abs(value - boundary) <= window:
            other_name = names[i + 1] if value < boundary else names[i]
            neighbors.append(other_name)
    return neighbors


def classify_timestamp_adjacency(
    sig1: float,
    sig2: float,
    tiers1: list[tuple[str, float]],
    tiers2: list[tuple[str, float]],
    window1: float,
    window2: float,
) -> BoundaryAdjacency:
    """Classify one (regime_group, tf, ts) timestamp's boundary adjacency.

    market_regimes is keyed (regime_group, tf, ts) with no symbol dimension -- this
    classifies the timestamp itself, shared by every symbol's row at that ts. Uses the
    production _bucket() function for the actual label so this can never silently drift
    from what cross_sectional_regime_model.py assigns in production.
    """
    label1 = str(_bucket(np.array([sig1]), tiers1)[0])
    label2 = str(_bucket(np.array([sig2]), tiers2)[0])
    actual_label = f"{label1}_{label2}"

    axis1_neighbors = _neighbors_across_axis(sig1, tiers1, window1)
    axis2_neighbors = _neighbors_across_axis(sig2, tiers2, window2)

    neighbor_labels: list[str] = []
    for n1 in axis1_neighbors:
        neighbor_labels.append(f"{n1}_{label2}")
    for n2 in axis2_neighbors:
        neighbor_labels.append(f"{label1}_{n2}")
    for n1 in axis1_neighbors:
        for n2 in axis2_neighbors:
            neighbor_labels.append(f"{n1}_{n2}")

    return BoundaryAdjacency(
        axis1_adjacent=bool(axis1_neighbors),
        axis2_adjacent=bool(axis2_neighbors),
        actual_label=actual_label,
        neighbor_labels=tuple(dict.fromkeys(neighbor_labels)),
    )


def align_weight_vectors(
    signed_weights_a: dict[str, float], signed_weights_b: dict[str, float]
) -> AlignedWeights:
    """Zero-pad both weight dicts onto the union of their feature names.

    Different regimes' ensemble_weights may cover different selected feature sets --
    a feature present in one but absent in the other must contribute correctly rather
    than being silently dropped or misaligned.
    """
    feature_names = tuple(sorted(set(signed_weights_a) | set(signed_weights_b)))
    a = np.array([signed_weights_a.get(f, 0.0) for f in feature_names], dtype=float)
    b = np.array([signed_weights_b.get(f, 0.0) for f in feature_names], dtype=float)
    return AlignedWeights(feature_names=feature_names, signed_weights_a=a, signed_weights_b=b)


def score_bar(
    feature_values: dict[str, float],
    feature_names: tuple[str, ...],
    signed_weights: np.ndarray,
) -> float:
    """alpha_score = X[bar] @ signed_weights -- the exact ensemble_trainer.py Step 6 pattern.

    signed_weights must already be weight * ic_sign (see the fetch layer, Task 6). Missing
    or non-finite feature values are treated as 0, matching alpha_score.py's convention.
    """
    x = np.array(
        [v if np.isfinite(v) else 0.0 for v in (feature_values.get(f, 0.0) for f in feature_names)],
        dtype=float,
    )
    return float(np.dot(x, signed_weights))


def compute_cell_verdict(
    regime_group: str,
    tf: str,
    n_boundary_adjacent_timestamps: int,
    n_total_timestamps: int,
    effect_sizes: np.ndarray,
    clean_noise_floor: float,
    n_untrained_neighbor_bars: int,
    n_scored_bars: int,
) -> CellVerdict:
    """Apply the pre-committed decision gate to one (regime_group, tf) cell.

    Both criteria required for overall_pass -- see module docstring / design doc for the
    rationale (materiality of exposure, materiality of effect size vs a noise floor that
    excludes the churn effect itself).
    """
    boundary_adjacent_fraction = (
        n_boundary_adjacent_timestamps / n_total_timestamps if n_total_timestamps > 0 else 0.0
    )
    median_effect_size = float(np.median(effect_sizes)) if len(effect_sizes) > 0 else 0.0

    criterion_1_pass = boundary_adjacent_fraction >= BOUNDARY_ADJACENT_FRACTION_GATE
    criterion_2_pass = (
        clean_noise_floor > 0
        and median_effect_size >= EFFECT_SIZE_MULTIPLIER_GATE * clean_noise_floor
    )

    return CellVerdict(
        regime_group=regime_group,
        tf=tf,
        boundary_adjacent_fraction=boundary_adjacent_fraction,
        n_boundary_adjacent_timestamps=n_boundary_adjacent_timestamps,
        n_total_timestamps=n_total_timestamps,
        median_effect_size=median_effect_size,
        clean_noise_floor=clean_noise_floor,
        n_untrained_neighbor_bars=n_untrained_neighbor_bars,
        n_scored_bars=n_scored_bars,
        criterion_1_pass=criterion_1_pass,
        criterion_2_pass=criterion_2_pass,
        overall_pass=criterion_1_pass and criterion_2_pass,
    )


def allocate_sample_sizes(
    boundary_counts_by_tf: dict[str, int],
    target_total: int = SAMPLE_SIZE_TARGET,
    hard_cap: int = HARD_CAP_PER_TF,
) -> dict[str, int]:
    """Per-tf sample allocation, proportional to each tf's boundary-adjacent timestamp
    count, capped so one large tf (5m) can't starve smaller ones (1d) of representation,
    and never asking for more than a tf actually has available.
    """
    total = sum(boundary_counts_by_tf.values())
    if total == 0:
        return dict.fromkeys(boundary_counts_by_tf, 0)
    allocation: dict[str, int] = {}
    for tf, count in boundary_counts_by_tf.items():
        proportional = round(target_total * count / total)
        allocation[tf] = min(proportional, hard_cap, count)
    return allocation


async def fetch_sampled_feature_vectors(
    conn: asyncpg.Connection,
    tf: str,
    timestamps: list,
    feature_names: tuple[str, ...],
    n: int,
) -> list[asyncpg.Record]:
    """Random sample of up to n (symbol, bar_ts) rows from feature_vectors at the given
    boundary-adjacent timestamps. feature_names come from fetch_signed_weights_by_regime's
    keys (information-schema-governed registry names, not user input -- safe to interpolate
    into the column list, matching ensemble_trainer.py's own col_list convention).

    Pre-samples the TIMESTAMP list in Python rather than pulling every matching row and
    sorting by random() in SQL: feature_vectors is a large compressed TimescaleDB hypertable
    (~25M rows at 5m), and ORDER BY random() over the full matching set forces decompressing
    and materializing every row before it can sort+limit (measured ~205s for one realistic
    fetch during Task 7's review -- unacceptable for a script whose whole premise is being
    cheap to re-run). Sampling ~n/n_symbols timestamps first, then fetching only those, keeps
    the query a plain indexed filter with no full-relation sort.
    """
    if not timestamps or n <= 0:
        return []

    symbol_count_row = await conn.fetchrow(
        "SELECT count(DISTINCT symbol) AS n FROM feature_vectors WHERE tf = $1", tf
    )
    n_symbols = max(1, symbol_count_row["n"])
    n_timestamps_needed = max(1, math.ceil(n / n_symbols))

    sampled_timestamps = (
        random.sample(timestamps, n_timestamps_needed)
        if n_timestamps_needed < len(timestamps)
        else timestamps
    )

    col_list = ", ".join(f'"{c}"' for c in feature_names)
    rows = await conn.fetch(
        f"""
        SELECT symbol, bar_ts, {col_list}
        FROM feature_vectors
        WHERE tf = $1 AND bar_ts = ANY($2::timestamptz[])
        """,
        tf,
        sampled_timestamps,
    )
    return rows[:n] if len(rows) > n else rows


def score_sampled_bars(
    sampled_rows: list[dict],
    adjacency_by_ts: dict,
    weights_by_regime: dict[str, dict[str, float]],
) -> tuple[np.ndarray, int]:
    """Score every sampled (symbol, ts) bar against its actual regime's weights and each
    relevant neighbor regime's weights (per its BoundaryAdjacency.neighbor_labels), via
    align_weight_vectors + score_bar. A bar whose actual OR neighbor regime never trained
    (no entry in weights_by_regime) is excluded from effect_sizes and counted separately
    -- never silently dropped without a trace.

    Returns (effect_sizes, n_untrained_neighbor_bars). Pure / DB-free: sampled_rows and
    adjacency_by_ts are already-fetched data, not live connections.
    """
    effect_sizes: list[float] = []
    n_untrained = 0

    for row in sampled_rows:
        adjacency = adjacency_by_ts.get(row["bar_ts"])
        if adjacency is None:
            continue
        actual_weights = weights_by_regime.get(adjacency.actual_label)
        if actual_weights is None:
            n_untrained += len(adjacency.neighbor_labels) or 1
            continue

        feature_values = {k: v for k, v in row.items() if k not in ("symbol", "bar_ts")}

        for neighbor_label in adjacency.neighbor_labels:
            neighbor_weights = weights_by_regime.get(neighbor_label)
            if neighbor_weights is None:
                n_untrained += 1
                continue
            aligned = align_weight_vectors(actual_weights, neighbor_weights)
            actual_score = score_bar(
                feature_values, aligned.feature_names, aligned.signed_weights_a
            )
            neighbor_score = score_bar(
                feature_values, aligned.feature_names, aligned.signed_weights_b
            )
            effect_sizes.append(abs(actual_score - neighbor_score))

    return np.array(effect_sizes, dtype=float), n_untrained


async def run_diagnostic(
    conn: asyncpg.Connection, cfg: Any, weight_version: str
) -> list[CellVerdict]:
    """Full pipeline for REGIME_GROUP, one CellVerdict per tf in TFS.

    cfg is a caller-owned, already-initialized ConfigService (see load_equity_tiers'
    docstring for why this uses cfg.get(), not cfg.get_sync()).

    Two passes, deliberately: allocate_sample_sizes needs every tf's boundary-adjacent
    count up front to share the ~50k sample budget proportionally (Task 7) -- calling it
    per-tf inside a single loop would let each tf independently request up to its own
    hard_cap (up to 4x hard_cap total), defeating the cross-tf sharing the budget exists
    for.
    """
    from services.ensemble_trainer import _resolve_ic_input_column

    tiers1, tiers2 = await load_equity_tiers(cfg)
    # Default matches EnsembleConfig.from_apr's own default (ensemble_trainer.py:171) --
    # not re-derived independently, so this can't silently diverge if the config_state row
    # is ever missing.
    ic_input = await cfg.get("alpha.ensemble.ic_input", "ic_sharpe_hac")
    ic_input_column = _resolve_ic_input_column(ic_input)

    # Pass 1: fetch each tf's regime series and classify boundary adjacency.
    per_tf: dict[str, dict] = {}
    for tf in TFS:
        series = await fetch_regime_series(conn, tf)
        if len(series) < 2:
            continue

        sig1_arr = np.array([r["sig1"] for r in series])
        sig2_arr = np.array([r["sig2"] for r in series])
        window1 = derive_boundary_window(sig1_arr)
        window2 = derive_boundary_window(sig2_arr)

        adjacency_by_ts = {}
        for r in series:
            adj = classify_timestamp_adjacency(
                r["sig1"], r["sig2"], tiers1, tiers2, window1, window2
            )
            if adj.axis1_adjacent or adj.axis2_adjacent:
                adjacency_by_ts[r["ts"]] = adj

        per_tf[tf] = {
            "adjacency_by_ts": adjacency_by_ts,
            "n_total": len(series),
        }

    # Allocation computed once, across every tf's boundary-adjacent count together.
    boundary_counts_by_tf = {tf: len(d["adjacency_by_ts"]) for tf, d in per_tf.items()}
    allocation = allocate_sample_sizes(boundary_counts_by_tf)

    # Pass 2: fetch weights/noise-floor/sample and score, per tf, using the shared allocation.
    verdicts: list[CellVerdict] = []
    for tf, d in per_tf.items():
        adjacency_by_ts = d["adjacency_by_ts"]
        n_boundary_adjacent = len(adjacency_by_ts)
        n_total = d["n_total"]

        weights_by_regime, n_skipped_null_sign = await fetch_signed_weights_by_regime(
            conn, tf, weight_version, ic_input_column
        )
        if n_skipped_null_sign > 0:
            # Anomalous per fetch_signed_weights_by_regime's docstring -- worth surfacing,
            # not silently absorbing (this repo's "silent wrong answers are worse than loud
            # crashes" principle).
            print(f"WARNING: tf={tf} skipped {n_skipped_null_sign} features with null ic_sign")
        clean_noise_floor = await fetch_clean_noise_floor(conn, tf, weight_version)

        effect_sizes = np.array([], dtype=float)
        n_untrained = 0
        n_scored = 0
        n_sample = allocation.get(tf, 0)
        if n_sample > 0 and weights_by_regime:
            all_feature_names = tuple(sorted({f for w in weights_by_regime.values() for f in w}))
            sampled = await fetch_sampled_feature_vectors(
                conn, tf, list(adjacency_by_ts.keys()), all_feature_names, n_sample
            )
            sampled_rows = [dict(r) for r in sampled]
            effect_sizes, n_untrained = score_sampled_bars(
                sampled_rows, adjacency_by_ts, weights_by_regime
            )
            n_scored = len(sampled_rows)

        verdicts.append(
            compute_cell_verdict(
                regime_group=REGIME_GROUP,
                tf=tf,
                n_boundary_adjacent_timestamps=n_boundary_adjacent,
                n_total_timestamps=n_total,
                effect_sizes=effect_sizes,
                clean_noise_floor=clean_noise_floor,
                n_untrained_neighbor_bars=n_untrained,
                n_scored_bars=n_scored,
            )
        )

    return verdicts
