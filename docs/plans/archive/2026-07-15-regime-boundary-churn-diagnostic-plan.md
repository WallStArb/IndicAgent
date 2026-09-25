# Regime Boundary-Churn Diagnostic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a read-only diagnostic script that measures whether hard-argmax regime-label
boundary churn is materially destructive to `alpha_score` stability, per a pre-committed
decision gate, using only already-existing corpus data.

**Architecture:** A single self-contained script (`scripts/analysis/regime_boundary_churn_check.py`,
matching the existing `ic_sharpe_stride_bias_check.py`/`crowding_proxy_regression.py` pattern)
split internally into pure functions (boundary classification, weight alignment, scoring,
verdict computation — unit-testable without a DB) and a thin async fetch/orchestration layer
(`asyncpg`, matching `ensemble_trainer.py`'s idiom). No new tables, no writes, no APR keys
(analysis script, outside `src/`/`services/`).

**Tech Stack:** Python 3.14, `asyncpg`, `numpy`, existing `ConfigService`/`Settings`, pytest.

## Global Constraints

- Read-only: no writes to any table, no new migrations, no Kafka.
- V1 scope: `regime_group='equity'` only, `tf` in `("5m", "15m", "1h", "1d")` — matches
  `ensemble_trainer.py`'s current hardcoded scope (not yet `regime_group`-aware). `rates`
  has no trained `ensemble_weights` to compare against; the untrained-neighbor handling
  built in Task 8 reports this honestly rather than needing separate group logic.
- Reuse, never re-derive: tier cut points come from `build_tiers()` in
  `src/intelligence/regime_signals/breadth_vol.py` (imported directly), bucket assignment
  from `_bucket()` in `services/cross_sectional_regime_model.py` (imported directly),
  scoring from the exact `X @ (weights * ic_signs)` expression `ensemble_trainer.py` uses.
- Sample size target: 50,000 `(ts, symbol)` rows total across the 4 timeframes, capped at
  20,000 per timeframe so 5m (far more bars) doesn't starve 1d of representation.
- Decision gate (both required per `tf`): boundary-adjacent timestamps ≥5% of all
  timestamps; median boundary-crossing effect size ≥1.5× the clean (same-regime-only)
  noise floor.
- Spec: `docs/plans/archive/2026-07-15-regime-boundary-churn-diagnostic-design.md`.

---

### Task 1: Constants, dataclasses, and boundary-window derivation

**Files:**
- Create: `scripts/analysis/regime_boundary_churn_check.py`
- Test: `tests/unit/test_regime_boundary_churn_check.py`

**Interfaces:**
- Produces: `SAMPLE_SIZE_TARGET`, `HARD_CAP_PER_TF`, `WINDOW_STEP_MULTIPLIER`,
  `BOUNDARY_ADJACENT_FRACTION_GATE`, `EFFECT_SIZE_MULTIPLIER_GATE`, `TFS` module constants;
  `BoundaryAdjacency`, `AlignedWeights`, `CellVerdict` dataclasses;
  `derive_boundary_window(step_series: np.ndarray, multiplier: float = WINDOW_STEP_MULTIPLIER) -> float`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_regime_boundary_churn_check.py
from __future__ import annotations

import numpy as np

from scripts.analysis.regime_boundary_churn_check import (
    WINDOW_STEP_MULTIPLIER,
    derive_boundary_window,
)


def test_derive_boundary_window_scales_with_median_step():
    # Steps alternate 0.01, 0.03 -> median abs step = 0.02
    series = np.array([0.10, 0.11, 0.14, 0.15, 0.18, 0.19])
    window = derive_boundary_window(series, multiplier=2.0)
    assert window == 0.04


def test_derive_boundary_window_empty_or_singleton_is_zero():
    assert derive_boundary_window(np.array([])) == 0.0
    assert derive_boundary_window(np.array([0.5])) == 0.0


def test_derive_boundary_window_default_multiplier_constant():
    series = np.array([0.0, 0.02, 0.04, 0.06])
    assert derive_boundary_window(series) == 0.02 * WINDOW_STEP_MULTIPLIER
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_regime_boundary_churn_check.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'scripts.analysis.regime_boundary_churn_check'`

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/analysis/regime_boundary_churn_check.py
"""Regime boundary-churn materiality diagnostic (todo 080 / L5-1 Phase 0).

Read-only. Measures whether hard-argmax cross-sectional regime-label boundary crossings
are a materially destructive source of alpha_score discontinuity, per a pre-committed
decision gate, BEFORE any soft-blending scoring mechanism is designed. See
docs/plans/archive/2026-07-15-regime-boundary-churn-diagnostic-design.md for full rationale.

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

from dataclasses import dataclass

import numpy as np

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_regime_boundary_churn_check.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/analysis/regime_boundary_churn_check.py tests/unit/test_regime_boundary_churn_check.py
git commit -m "feat(analysis): add boundary-churn diagnostic skeleton + window derivation"
```

---

### Task 2: Timestamp boundary-adjacency classification

**Files:**
- Modify: `scripts/analysis/regime_boundary_churn_check.py`
- Test: `tests/unit/test_regime_boundary_churn_check.py`

**Interfaces:**
- Consumes: `BoundaryAdjacency` (Task 1). `_bucket` from `services.cross_sectional_regime_model`
  (signature: `_bucket(vals: np.ndarray, tiers: list[tuple[str, float]]) -> np.ndarray`).
- Produces: `classify_timestamp_adjacency(sig1: float, sig2: float, tiers1: list[tuple[str, float]], tiers2: list[tuple[str, float]], window1: float, window2: float) -> BoundaryAdjacency`.

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/unit/test_regime_boundary_churn_check.py
from scripts.analysis.regime_boundary_churn_check import classify_timestamp_adjacency

_TIERS1 = [("low", 0.33), ("mid", 0.67), ("high", float("inf"))]
_TIERS2 = [("bear", 0.40), ("neutral", 0.60), ("bull", float("inf"))]


def test_classify_not_adjacent_when_far_from_any_boundary():
    result = classify_timestamp_adjacency(0.50, 0.50, _TIERS1, _TIERS2, window1=0.02, window2=0.02)
    assert result.actual_label == "mid_neutral"
    assert not result.axis1_adjacent
    assert not result.axis2_adjacent
    assert result.neighbor_labels == ()


def test_classify_single_axis_adjacent():
    # sig1=0.335 is within 0.02 of the 0.33 boundary; sig2=0.50 is far from both breadth cuts.
    result = classify_timestamp_adjacency(0.335, 0.50, _TIERS1, _TIERS2, window1=0.02, window2=0.02)
    assert result.actual_label == "mid_neutral"
    assert result.axis1_adjacent
    assert not result.axis2_adjacent
    assert result.neighbor_labels == ("low_neutral",)


def test_classify_corner_case_both_axes_adjacent():
    # sig1=0.335 near the low/mid vix cut; sig2=0.605 near the neutral/bull breadth cut.
    result = classify_timestamp_adjacency(0.335, 0.605, _TIERS1, _TIERS2, window1=0.02, window2=0.02)
    assert result.actual_label == "mid_bull"
    assert result.axis1_adjacent and result.axis2_adjacent
    assert set(result.neighbor_labels) == {"low_bull", "mid_neutral", "low_neutral"}


def test_classify_narrow_middle_tier_double_adjacency_on_one_axis():
    # sig1=0.50 sits in "mid" but within 0.20 of BOTH the 0.33 and 0.67 boundaries when
    # window1 is wide -- both neighbors on axis 1 must be reported, not just one.
    result = classify_timestamp_adjacency(0.50, 0.50, _TIERS1, _TIERS2, window1=0.20, window2=0.02)
    assert result.actual_label == "mid_neutral"
    assert result.axis1_adjacent
    assert set(result.neighbor_labels) == {"low_neutral", "high_neutral"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_regime_boundary_churn_check.py -v -k classify`
Expected: FAIL with `ImportError: cannot import name 'classify_timestamp_adjacency'`

- [ ] **Step 3: Write minimal implementation**

```python
# Append to scripts/analysis/regime_boundary_churn_check.py, after the imports section add:
from services.cross_sectional_regime_model import _bucket  # noqa: E402


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_regime_boundary_churn_check.py -v -k classify`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/analysis/regime_boundary_churn_check.py tests/unit/test_regime_boundary_churn_check.py
git commit -m "feat(analysis): add timestamp boundary-adjacency classification"
```

---

### Task 3: Weight alignment and bar scoring

**Files:**
- Modify: `scripts/analysis/regime_boundary_churn_check.py`
- Test: `tests/unit/test_regime_boundary_churn_check.py`

**Interfaces:**
- Consumes: `AlignedWeights` (Task 1).
- Produces: `align_weight_vectors(signed_weights_a: dict[str, float], signed_weights_b: dict[str, float]) -> AlignedWeights`;
  `score_bar(feature_values: dict[str, float], feature_names: tuple[str, ...], signed_weights: np.ndarray) -> float`.

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/unit/test_regime_boundary_churn_check.py
from scripts.analysis.regime_boundary_churn_check import align_weight_vectors, score_bar


def test_align_weight_vectors_unions_and_zero_pads():
    a = {"momentum_z_fast": 0.6, "obv_z": 0.4}
    b = {"momentum_z_fast": 0.5, "range_pct": -0.5}
    aligned = align_weight_vectors(a, b)
    assert aligned.feature_names == ("momentum_z_fast", "obv_z", "range_pct")
    assert aligned.signed_weights_a.tolist() == [0.6, 0.4, 0.0]
    assert aligned.signed_weights_b.tolist() == [0.5, 0.0, -0.5]


def test_score_bar_matches_manual_dot_product():
    feature_values = {"momentum_z_fast": 2.0, "obv_z": -1.0, "range_pct": 0.5}
    feature_names = ("momentum_z_fast", "obv_z", "range_pct")
    signed_weights = np.array([0.6, 0.4, 0.0])
    score = score_bar(feature_values, feature_names, signed_weights)
    expected = 2.0 * 0.6 + -1.0 * 0.4 + 0.5 * 0.0
    # Tolerance, not ==: np.dot and plain Python arithmetic aren't guaranteed
    # bit-identical (e.g. FMA on some platforms).
    assert abs(score - expected) < 1e-9


def test_score_bar_treats_missing_and_non_finite_as_zero():
    feature_values = {"momentum_z_fast": float("nan"), "obv_z": -1.0}
    feature_names = ("momentum_z_fast", "obv_z", "range_pct")
    signed_weights = np.array([0.6, 0.4, -0.5])
    score = score_bar(feature_values, feature_names, signed_weights)
    expected = 0.0 * 0.6 + -1.0 * 0.4 + 0.0 * -0.5
    assert abs(score - expected) < 1e-9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_regime_boundary_churn_check.py -v -k "align or score_bar"`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# Append to scripts/analysis/regime_boundary_churn_check.py
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
        [
            v if np.isfinite(v) else 0.0
            for v in (feature_values.get(f, 0.0) for f in feature_names)
        ],
        dtype=float,
    )
    return float(np.dot(x, signed_weights))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_regime_boundary_churn_check.py -v -k "align or score_bar"`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/analysis/regime_boundary_churn_check.py tests/unit/test_regime_boundary_churn_check.py
git commit -m "feat(analysis): add weight alignment and bar scoring"
```

---

### Task 4: Cell verdict computation (the decision gate itself)

**Files:**
- Modify: `scripts/analysis/regime_boundary_churn_check.py`
- Test: `tests/unit/test_regime_boundary_churn_check.py`

**Interfaces:**
- Consumes: `CellVerdict` (Task 1); `BOUNDARY_ADJACENT_FRACTION_GATE`, `EFFECT_SIZE_MULTIPLIER_GATE` (Task 1).
- Produces: `compute_cell_verdict(regime_group: str, tf: str, n_boundary_adjacent_timestamps: int, n_total_timestamps: int, effect_sizes: np.ndarray, clean_noise_floor: float, n_untrained_neighbor_bars: int, n_scored_bars: int) -> CellVerdict`.

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/unit/test_regime_boundary_churn_check.py
from scripts.analysis.regime_boundary_churn_check import compute_cell_verdict


def test_verdict_passes_when_both_criteria_met():
    verdict = compute_cell_verdict(
        regime_group="equity",
        tf="5m",
        n_boundary_adjacent_timestamps=600,
        n_total_timestamps=10_000,  # 6% >= 5% gate
        effect_sizes=np.array([0.30, 0.32, 0.35, 0.40]),  # median 0.335
        clean_noise_floor=0.20,  # 0.335 >= 1.5 * 0.20 = 0.30
        n_untrained_neighbor_bars=5,
        n_scored_bars=595,
    )
    assert verdict.boundary_adjacent_fraction == 0.06
    assert verdict.criterion_1_pass is True
    assert verdict.criterion_2_pass is True
    assert verdict.overall_pass is True


def test_verdict_fails_on_low_boundary_fraction():
    verdict = compute_cell_verdict(
        regime_group="equity",
        tf="1d",
        n_boundary_adjacent_timestamps=10,
        n_total_timestamps=10_000,  # 0.1% < 5% gate
        effect_sizes=np.array([0.50, 0.55]),
        clean_noise_floor=0.10,
        n_untrained_neighbor_bars=0,
        n_scored_bars=10,
    )
    assert verdict.criterion_1_pass is False
    assert verdict.overall_pass is False


def test_verdict_fails_when_effect_indistinguishable_from_noise():
    verdict = compute_cell_verdict(
        regime_group="equity",
        tf="1h",
        n_boundary_adjacent_timestamps=600,
        n_total_timestamps=10_000,
        effect_sizes=np.array([0.10, 0.11, 0.12]),  # median 0.11
        clean_noise_floor=0.20,  # 0.11 < 1.5 * 0.20 = 0.30
        n_untrained_neighbor_bars=0,
        n_scored_bars=600,
    )
    assert verdict.criterion_1_pass is True
    assert verdict.criterion_2_pass is False
    assert verdict.overall_pass is False


def test_verdict_handles_zero_noise_floor_without_dividing_by_zero():
    verdict = compute_cell_verdict(
        regime_group="equity",
        tf="1h",
        n_boundary_adjacent_timestamps=600,
        n_total_timestamps=10_000,
        effect_sizes=np.array([0.10]),
        clean_noise_floor=0.0,
        n_untrained_neighbor_bars=0,
        n_scored_bars=600,
    )
    assert verdict.criterion_2_pass is False


def test_verdict_handles_no_boundary_adjacent_timestamps():
    verdict = compute_cell_verdict(
        regime_group="equity",
        tf="1d",
        n_boundary_adjacent_timestamps=0,
        n_total_timestamps=10_000,
        effect_sizes=np.array([]),
        clean_noise_floor=0.10,
        n_untrained_neighbor_bars=0,
        n_scored_bars=0,
    )
    assert verdict.median_effect_size == 0.0
    assert verdict.overall_pass is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_regime_boundary_churn_check.py -v -k verdict`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# Append to scripts/analysis/regime_boundary_churn_check.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_regime_boundary_churn_check.py -v -k verdict`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/analysis/regime_boundary_churn_check.py tests/unit/test_regime_boundary_churn_check.py
git commit -m "feat(analysis): add decision-gate verdict computation"
```

---

### Task 5: Fetch layer — regime time series and tier cut points

**Files:**
- Modify: `scripts/analysis/regime_boundary_churn_check.py`
- Test: `tests/unit/test_regime_boundary_churn_check.py`

**Interfaces:**
- Consumes: `REGIME_GROUP`, `TFS` (Task 1); `build_tiers` from `src.intelligence.regime_signals.breadth_vol`.
- Produces: `async def fetch_regime_series(conn: asyncpg.Connection, tf: str) -> list[asyncpg.Record]`
  (columns: `ts`, `regime_label`, `sig1`, `sig2` — one row per `(REGIME_GROUP, tf, ts)`, ordered by `ts`);
  `load_equity_tiers(cfg: Any) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]`.

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/unit/test_regime_boundary_churn_check.py
from scripts.analysis.regime_boundary_churn_check import _REGIME_SERIES_SQL


def test_regime_series_sql_scopes_to_equity_group_and_orders_by_ts():
    assert "regime_group = 'equity'" in _REGIME_SERIES_SQL
    assert "ORDER BY ts" in _REGIME_SERIES_SQL
    assert "regime_prob_vector" in _REGIME_SERIES_SQL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_regime_boundary_churn_check.py -v -k regime_series_sql`
Expected: FAIL with `ImportError: cannot import name '_REGIME_SERIES_SQL'`

- [ ] **Step 3: Write minimal implementation**

```python
# Append to scripts/analysis/regime_boundary_churn_check.py, near the top-level imports add:
from typing import Any

import asyncpg  # noqa: E402

from src.intelligence.regime_signals.breadth_vol import PROB_KEYS, build_tiers  # noqa: E402

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


async def fetch_regime_series(conn: asyncpg.Connection, tf: str) -> list[asyncpg.Record]:
    """One row per (REGIME_GROUP, tf, ts): ts, regime_label, sig1, sig2. Ordered by ts."""
    return await conn.fetch(_REGIME_SERIES_SQL, PROB_KEYS[0], PROB_KEYS[1], tf)


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_regime_boundary_churn_check.py -v -k regime_series_sql`
Expected: PASS

- [ ] **Step 5: Verify the SQL runs against the live schema (manual smoke check, not part of the test suite)**

Run:
```bash
PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c \
  "SELECT ts, regime_label, (regime_prob_vector->>'vix_pct')::double precision AS sig1, (regime_prob_vector->>'breadth_frac')::double precision AS sig2 FROM market_regimes WHERE regime_group = 'equity' AND tf = '5m' ORDER BY ts LIMIT 3;"
```
Expected: 3 rows, no error.

- [ ] **Step 6: Commit**

```bash
git add scripts/analysis/regime_boundary_churn_check.py tests/unit/test_regime_boundary_churn_check.py
git commit -m "feat(analysis): add regime time-series fetch and tier cut-point loading"
```

---

### Task 6: Fetch layer — signed weights per regime and clean noise floor

**Files:**
- Modify: `scripts/analysis/regime_boundary_churn_check.py`
- Test: `tests/unit/test_regime_boundary_churn_check.py`

**Interfaces:**
- Produces: `async def fetch_signed_weights_by_regime(conn: asyncpg.Connection, tf: str, weight_version: str, ic_input_column: str) -> tuple[dict[str, dict[str, float]], int]`
  (dict: outer key = `regime_label`, inner = `{feature_name: weight * ic_sign}`; int = count
  of features skipped because no exact-match ic_sign was found -- see below for why this
  should normally be 0. `ic_input_column` must be `ensemble_trainer.py`'s
  `_resolve_ic_input_column(alpha.ensemble.ic_input)` result -- caller-resolved, not
  re-derived here);
  `async def fetch_clean_noise_floor(conn: asyncpg.Connection, tf: str, weight_version: str) -> float`
  (median `|Δalpha_score|` over same-symbol, same-regime-label consecutive bar pairs).

**Correctness note (found during Task 6's review, fixed before this text was written):** the
LATERAL join reconstructing `ic_sign` must match the EXACT `feature_ic_scores` row
`ensemble_trainer.py`'s `select_features_per_stratum` actually selected -- that's the row
with the highest `quality_weight` across every `(lookahead_bars, training_window_end)`
combination on record, NOT the most recent `training_window_end` (a feature's IC estimate,
and even its sign, can differ across training windows). `ensemble_weights.ic_sharpe` is
stored as exactly that winning row's `ic_input_column` value, copied verbatim with no
arithmetic -- so joining on `fic.{ic_input_column} = ew.ic_sharpe` (exact float equality,
safe here since no computation separates the two values) uniquely identifies the actual
winning row regardless of which `training_window_end` it came from.

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/unit/test_regime_boundary_churn_check.py
from scripts.analysis.regime_boundary_churn_check import (
    _CLEAN_NOISE_FLOOR_SQL,
    _SIGNED_WEIGHTS_SQL_TEMPLATE,
    fetch_signed_weights_by_regime,
)


def test_signed_weights_sql_joins_ic_sign_via_lateral_on_exact_selected_value():
    sql = _SIGNED_WEIGHTS_SQL_TEMPLATE.format(ic_input_column="ic_shrunk")
    assert "ensemble_weights" in sql
    assert "LATERAL" in sql
    assert "fic.lookahead_bars = ew.lookahead_bars" in sql
    assert "symbol = 'UNIVERSE'" in sql
    # The actual fix: match the exact stored value ensemble_trainer.py copied verbatim --
    # not select via training_window_end recency, since production's real selection
    # criterion is highest quality_weight, not most recent. training_window_end DESC is
    # still present, but only as a defensive tiebreak after the exact-match filter (in case
    # two different training windows ever produce a bit-identical statistic by coincidence),
    # never as the primary selection mechanism.
    assert "fic.ic_shrunk = ew.ic_sharpe" in sql
    assert "ORDER BY fic.training_window_end DESC" in sql


class _FakeConnSignedWeights:
    """Fake asyncpg.Connection returning canned rows for fetch_signed_weights_by_regime."""

    def __init__(self, rows):
        self._rows = rows

    async def fetch(self, sql, *args):
        return self._rows


@pytest.mark.asyncio
async def test_fetch_signed_weights_by_regime_skips_null_ic_sign_and_counts_it():
    rows = [
        {"regime": "mid_neutral", "feature_name": "momentum_z_fast", "weight": 0.6, "ic_sign": 1},
        {"regime": "mid_neutral", "feature_name": "obv_z", "weight": 0.4, "ic_sign": None},
    ]
    conn = _FakeConnSignedWeights(rows)
    weights_by_regime, n_skipped = await fetch_signed_weights_by_regime(
        conn, "5m", "run_x", "ic_shrunk"
    )
    assert weights_by_regime == {"mid_neutral": {"momentum_z_fast": 0.6}}
    assert n_skipped == 1


def test_clean_noise_floor_sql_excludes_regime_transition_bars():
    # The whole point: the noise floor must NOT include the churn effect it's the
    # baseline for -- only consecutive same-symbol bars where regime_label held constant.
    assert "regime_label = prev_regime_label" in _CLEAN_NOISE_FLOOR_SQL
    assert "PARTITION BY" in _CLEAN_NOISE_FLOOR_SQL
    assert "regime_group = 'equity'" in _CLEAN_NOISE_FLOOR_SQL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_regime_boundary_churn_check.py -v -k "signed_weights_sql or clean_noise_floor_sql or fetch_signed_weights"`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# Append to scripts/analysis/regime_boundary_churn_check.py
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


async def fetch_signed_weights_by_regime(
    conn: asyncpg.Connection, tf: str, weight_version: str, ic_input_column: str
) -> tuple[dict[str, dict[str, float]], int]:
    """{regime_label: {feature_name: weight * ic_sign}} for every trained regime in tf, plus
    a count of features skipped because the exact-match join found no ic_sign. select_
    features_per_stratum only ever selects rows with a non-null ic_sign, so a miss here is
    an anomaly worth surfacing, not something to silently guess a sign for -- skip the
    feature rather than default to +1 and risk treating a contrarian feature as
    non-contrarian.
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


async def fetch_clean_noise_floor(
    conn: asyncpg.Connection, tf: str, weight_version: str
) -> float:
    """Median |delta alpha_score| across same-symbol, same-regime-label consecutive bars."""
    rows = await conn.fetch(_CLEAN_NOISE_FLOOR_SQL, tf, weight_version)
    deltas = np.array([float(r["delta"]) for r in rows], dtype=float)
    if len(deltas) == 0:
        return 0.0
    return float(np.median(deltas))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_regime_boundary_churn_check.py -v -k "signed_weights_sql or clean_noise_floor_sql"`
Expected: PASS

- [ ] **Step 5: Verify both queries run against the live schema (manual smoke check)**

Run:
```bash
.venv/bin/python -c "
import asyncio, asyncpg
from scripts.analysis.regime_boundary_churn_check import _SIGNED_WEIGHTS_SQL_TEMPLATE, _CLEAN_NOISE_FLOOR_SQL

async def main():
    conn = await asyncpg.connect('postgresql://postgres:postgres@localhost:5432/indicagent')
    sql = _SIGNED_WEIGHTS_SQL_TEMPLATE.format(ic_input_column='ic_shrunk')
    r1 = await conn.fetch(sql, '5m', 'run_2025122405150000')
    r2 = await conn.fetch(_CLEAN_NOISE_FLOOR_SQL, '5m', 'run_2025122405150000')
    print('signed_weights rows:', len(r1), 'noise_floor rows:', len(r2))
    await conn.close()

asyncio.run(main())
"
```
Expected: prints two counts, no error. `'run_2025122405150000'` is the live
`alpha.ensemble.weight_version` as of 2026-07-15 (verify with
`PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT config_value FROM
config_state WHERE config_key = 'alpha.ensemble.weight_version';"` if it may have changed).
**0 rows for both is expected right now**, not a bug: `ensemble_weights`/`ensemble_alpha` are
currently empty because the in-flight corpus pipeline hasn't reached its `ensemble_trainer`/
`alpha_publisher` steps yet for this epoch. Only an exception (SQL error) is a failure of this
step — a clean 0-row result confirms the query is valid against the live schema.

- [ ] **Step 6: Commit**

```bash
git add scripts/analysis/regime_boundary_churn_check.py tests/unit/test_regime_boundary_churn_check.py
git commit -m "feat(analysis): add signed-weight and clean-noise-floor fetch queries"
```

---

### Task 7: Fetch layer — stratified feature_vectors sampling

**Files:**
- Modify: `scripts/analysis/regime_boundary_churn_check.py`
- Test: `tests/unit/test_regime_boundary_churn_check.py`

**Interfaces:**
- Consumes: `HARD_CAP_PER_TF`, `SAMPLE_SIZE_TARGET` (Task 1).
- Produces: `allocate_sample_sizes(boundary_counts_by_tf: dict[str, int], target_total: int = SAMPLE_SIZE_TARGET, hard_cap: int = HARD_CAP_PER_TF) -> dict[str, int]`;
  `async def fetch_sampled_feature_vectors(conn: asyncpg.Connection, tf: str, timestamps: list, feature_names: tuple[str, ...], n: int) -> list[asyncpg.Record]`.

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/unit/test_regime_boundary_churn_check.py
from scripts.analysis.regime_boundary_churn_check import allocate_sample_sizes


def test_allocate_sample_sizes_proportional_to_boundary_counts():
    counts = {"5m": 8_000, "15m": 1_500, "1h": 400, "1d": 100}
    allocation = allocate_sample_sizes(counts, target_total=10_000, hard_cap=20_000)
    total = sum(counts.values())
    assert allocation["5m"] == round(10_000 * 8_000 / total)
    assert allocation["1d"] == round(10_000 * 100 / total)
    assert sum(allocation.values()) <= 10_000 + 4  # rounding slack, not a hard cap breach


def test_allocate_sample_sizes_respects_hard_cap():
    counts = {"5m": 100_000, "15m": 100, "1h": 100, "1d": 100}
    allocation = allocate_sample_sizes(counts, target_total=50_000, hard_cap=20_000)
    assert allocation["5m"] == 20_000


def test_allocate_sample_sizes_never_exceeds_available_count():
    counts = {"5m": 30, "15m": 1_500, "1h": 400, "1d": 100}
    allocation = allocate_sample_sizes(counts, target_total=50_000, hard_cap=20_000)
    assert allocation["5m"] == 30


from datetime import UTC, datetime

from scripts.analysis.regime_boundary_churn_check import fetch_sampled_feature_vectors


class _FakeConnSampledFeatureVectors:
    """Fake asyncpg.Connection: fetchrow() returns a canned symbol count, fetch() returns
    canned rows and records the SQL + timestamp list it was called with."""

    def __init__(self, n_symbols: int, rows: list[dict]):
        self._n_symbols = n_symbols
        self._rows = rows
        self.fetch_calls: list[tuple[str, tuple]] = []

    async def fetchrow(self, sql, *args):
        return {"n": self._n_symbols}

    async def fetch(self, sql, *args):
        self.fetch_calls.append((sql, args))
        return self._rows


_TS = [datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, 0, 5, tzinfo=UTC)]


@pytest.mark.asyncio
async def test_fetch_sampled_feature_vectors_avoids_order_by_random_in_sql():
    # The whole point of the fix: no expensive full-relation sort in the actual query.
    conn = _FakeConnSampledFeatureVectors(n_symbols=2, rows=[{"symbol": "SPY", "bar_ts": _TS[0]}])
    await fetch_sampled_feature_vectors(conn, "5m", _TS, ("momentum_z_fast",), 10)
    assert len(conn.fetch_calls) == 1
    sql, args = conn.fetch_calls[0]
    assert "ORDER BY random()" not in sql
    assert "LIMIT" not in sql


@pytest.mark.asyncio
async def test_fetch_sampled_feature_vectors_truncates_to_n_in_python():
    rows = [{"symbol": f"S{i}", "bar_ts": _TS[0]} for i in range(5)]
    conn = _FakeConnSampledFeatureVectors(n_symbols=5, rows=rows)
    result = await fetch_sampled_feature_vectors(conn, "5m", _TS, ("momentum_z_fast",), 3)
    assert len(result) == 3


@pytest.mark.asyncio
async def test_fetch_sampled_feature_vectors_handles_empty_timestamps_and_zero_n():
    conn = _FakeConnSampledFeatureVectors(n_symbols=5, rows=[])
    assert await fetch_sampled_feature_vectors(conn, "5m", [], ("momentum_z_fast",), 10) == []
    assert await fetch_sampled_feature_vectors(conn, "5m", _TS, ("momentum_z_fast",), 0) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_regime_boundary_churn_check.py -v -k "allocate_sample_sizes or fetch_sampled_feature_vectors"`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

**Performance note (found during Task 7's review, fixed before this text was written):** the
first version of `fetch_sampled_feature_vectors` used `ORDER BY random() LIMIT n` directly in
SQL. Measured against realistic scale (5,000 timestamps, `n=20,000`): **~205 seconds** for one
fetch. Root cause: `feature_vectors` is a large compressed TimescaleDB hypertable (~25M rows
at 5m) — `ORDER BY random()` forces Postgres to decompress and materialize *every* matching
row before it can sort and apply `LIMIT`, since there's no way to short-circuit a random sort
against an indexed scan. This directly contradicted the module's own "cheap to re-run"
premise. Fixed by pre-sampling the *timestamp* list in Python (cheap — no full-relation sort
needed) before querying, then fetching only the rows at those pre-selected timestamps and
truncating to `n` in Python if oversampled. Measured after the fix, same scale: **~0.12
seconds** (~1700x faster).

```python
# Append to scripts/analysis/regime_boundary_churn_check.py
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
    sorting by random() in SQL -- see this task's performance note above. Sampling
    ~n/n_symbols timestamps first, then fetching only those, keeps the query a plain indexed
    filter with no full-relation sort.
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
```

Also add `import math` and `import random` to the module's top-level imports (alongside the
existing `from dataclasses import dataclass` / `from typing import Any` block).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_regime_boundary_churn_check.py -v -k "allocate_sample_sizes or fetch_sampled_feature_vectors"`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/analysis/regime_boundary_churn_check.py tests/unit/test_regime_boundary_churn_check.py
git commit -m "feat(analysis): add stratified sample allocation and feature_vectors fetch"
```

---

### Task 8: Orchestration — wire the pipeline together with untrained-neighbor handling

**Files:**
- Modify: `scripts/analysis/regime_boundary_churn_check.py`
- Test: `tests/unit/test_regime_boundary_churn_check.py`

**Interfaces:**
- Consumes: everything from Tasks 1-7.
- Produces: `def score_sampled_bars(sampled_rows: list[dict], adjacency_by_ts: dict, weights_by_regime: dict[str, dict[str, float]]) -> tuple[np.ndarray, int]`
  (returns `(effect_sizes, n_untrained_neighbor_bars)` — the pure orchestration core, DB-free
  and directly testable with synthetic fixtures);
  `async def run_diagnostic(conn: asyncpg.Connection, cfg: Any, weight_version: str) -> list[CellVerdict]`
  (`cfg` is an initialized `ConfigService` -- caller-owned, matching how `conn` is already
  caller-owned, rather than `run_diagnostic` constructing its own DB-backed service internally)
  (thin async wrapper calling the fetch layer then `score_sampled_bars` then `compute_cell_verdict`
  per tf).

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/unit/test_regime_boundary_churn_check.py
from scripts.analysis.regime_boundary_churn_check import score_sampled_bars


def test_score_sampled_bars_scores_trained_pairs_and_counts_untrained():
    # Two sampled bars at the same boundary-adjacent ts, different symbols.
    sampled_rows = [
        {"symbol": "SPY", "bar_ts": "t1", "momentum_z_fast": 2.0, "obv_z": -1.0},
        {"symbol": "QQQ", "bar_ts": "t1", "momentum_z_fast": 1.0, "obv_z": 1.0},
        {"symbol": "IWM", "bar_ts": "t2", "momentum_z_fast": 0.5, "obv_z": 0.5},
    ]
    adjacency_by_ts = {
        "t1": type(
            "A", (), {"actual_label": "mid_neutral", "neighbor_labels": ("low_neutral",)}
        )(),
        # t2's neighbor regime ("high_neutral") has no trained weights below.
        "t2": type(
            "A", (), {"actual_label": "mid_neutral", "neighbor_labels": ("high_neutral",)}
        )(),
    }
    weights_by_regime = {
        "mid_neutral": {"momentum_z_fast": 0.6, "obv_z": 0.4},
        "low_neutral": {"momentum_z_fast": 0.3, "obv_z": 0.2},
        # 'high_neutral' deliberately absent -- untrained neighbor for t2.
    }

    effect_sizes, n_untrained = score_sampled_bars(sampled_rows, adjacency_by_ts, weights_by_regime)

    # t1 (2 symbols) scored against both mid_neutral and low_neutral weights; t2 excluded
    # from effect_sizes (untrained neighbor) but counted.
    assert len(effect_sizes) == 2
    assert n_untrained == 1

    spy_actual = 2.0 * 0.6 + -1.0 * 0.4
    spy_neighbor = 2.0 * 0.3 + -1.0 * 0.2
    expected_spy_effect = abs(spy_actual - spy_neighbor)
    # Tolerance, not exact `in` membership: np.dot vs plain Python arithmetic
    # aren't guaranteed bit-identical.
    assert any(abs(e - expected_spy_effect) < 1e-9 for e in effect_sizes)


def test_score_sampled_bars_excludes_bars_with_untrained_actual_regime_too():
    sampled_rows = [{"symbol": "SPY", "bar_ts": "t1", "momentum_z_fast": 2.0}]
    adjacency_by_ts = {
        "t1": type("A", (), {"actual_label": "high_bull", "neighbor_labels": ("mid_bull",)})()
    }
    weights_by_regime = {"mid_bull": {"momentum_z_fast": 0.5}}  # 'high_bull' never trained

    effect_sizes, n_untrained = score_sampled_bars(sampled_rows, adjacency_by_ts, weights_by_regime)
    assert len(effect_sizes) == 0
    assert n_untrained == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_regime_boundary_churn_check.py -v -k score_sampled_bars`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# Append to scripts/analysis/regime_boundary_churn_check.py
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
            actual_score = score_bar(feature_values, aligned.feature_names, aligned.signed_weights_a)
            neighbor_score = score_bar(feature_values, aligned.feature_names, aligned.signed_weights_b)
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
            all_feature_names = tuple(
                sorted({f for w in weights_by_regime.values() for f in w})
            )
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_regime_boundary_churn_check.py -v -k score_sampled_bars`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add scripts/analysis/regime_boundary_churn_check.py tests/unit/test_regime_boundary_churn_check.py
git commit -m "feat(analysis): wire orchestration pipeline with untrained-neighbor handling"
```

---

### Task 9: CLI entrypoint, verdict reporting, and full verification

**Files:**
- Modify: `scripts/analysis/regime_boundary_churn_check.py`
- Test: `tests/unit/test_regime_boundary_churn_check.py`

**Interfaces:**
- Consumes: `run_diagnostic` (Task 8).
- Produces: `format_verdict_table(verdicts: list[CellVerdict]) -> str`; `main() -> None` (CLI entrypoint).

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/unit/test_regime_boundary_churn_check.py
from scripts.analysis.regime_boundary_churn_check import format_verdict_table


def test_format_verdict_table_reports_pass_and_fail_verdicts():
    verdicts = [
        compute_cell_verdict(
            "equity", "5m", 600, 10_000, np.array([0.35]), 0.20, 5, 595
        ),
        compute_cell_verdict(
            "equity", "1d", 10, 10_000, np.array([0.5]), 0.10, 0, 10
        ),
    ]
    table = format_verdict_table(verdicts)
    assert "5m" in table and "PASS" in table
    assert "1d" in table and "FAIL" in table
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_regime_boundary_churn_check.py -v -k format_verdict_table`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

```python
# Append to scripts/analysis/regime_boundary_churn_check.py
def format_verdict_table(verdicts: list[CellVerdict]) -> str:
    """Same reporting shape as ops_ensemble_ic_gate.py's verdict output."""
    lines = [
        f"{'regime_group':<12} {'tf':<5} {'boundary_frac':>13} {'median_effect':>13} "
        f"{'noise_floor':>11} {'untrained':>9} {'verdict':>8}"
    ]
    for v in verdicts:
        verdict_str = "PASS" if v.overall_pass else "FAIL"
        lines.append(
            f"{v.regime_group:<12} {v.tf:<5} {v.boundary_adjacent_fraction:>13.4f} "
            f"{v.median_effect_size:>13.4f} {v.clean_noise_floor:>11.4f} "
            f"{v.n_untrained_neighbor_bars:>9} {verdict_str:>8}"
        )
    return "\n".join(lines)


def main() -> None:
    import argparse
    import asyncio

    from src.config.config_service import ConfigService
    from src.config.settings import Settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weight-version", default=None, help="Overrides alpha.ensemble.weight_version.")
    args = parser.parse_args()

    async def _run() -> None:
        settings = Settings()
        cfg = ConfigService(database_url=settings.database_url)
        await cfg.initialize()
        conn = await asyncpg.connect(settings.database_url)
        try:
            weight_version = args.weight_version or await cfg.get(
                "alpha.ensemble.weight_version", "v1"
            )
            verdicts = await run_diagnostic(conn, cfg, weight_version)
        finally:
            await conn.close()
            await cfg.close()
        print(format_verdict_table(verdicts))

    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_regime_boundary_churn_check.py -v -k format_verdict_table`
Expected: PASS

- [ ] **Step 5: Run the full new test file and lint**

Run: `.venv/bin/pytest tests/unit/test_regime_boundary_churn_check.py -v`
Expected: all tests PASS (should be ~25 tests across all 9 tasks).

Run: `.venv/bin/ruff check scripts/analysis/regime_boundary_churn_check.py tests/unit/test_regime_boundary_churn_check.py --fix && .venv/bin/black scripts/analysis/regime_boundary_churn_check.py tests/unit/test_regime_boundary_churn_check.py`
Expected: clean (no unfixable errors).

- [ ] **Step 6: Run the full unit suite to confirm no regressions**

Run: `.venv/bin/pytest tests/unit/ -q`
Expected: all pass, same as the pre-existing baseline (no failures introduced).

- [ ] **Step 7: Manual end-to-end smoke run against live data**

Run: `.venv/bin/python scripts/analysis/regime_boundary_churn_check.py`
Expected: prints a verdict table with one row per tf in `("5m", "15m", "1h", "1d")`, no
exception. (A `weight_version` mismatch producing all-empty `weights_by_regime` — hence
`n_scored_bars=0` for every row — is a valid, informative result, not a bug; note it in the
commit/PR if seen, since it would mean the diagnostic ran before the in-flight corpus
pipeline's `ensemble_trainer` step landed fresh weights.)

- [ ] **Step 8: Commit**

```bash
git add scripts/analysis/regime_boundary_churn_check.py tests/unit/test_regime_boundary_churn_check.py
git commit -m "feat(analysis): add CLI entrypoint and verdict reporting for boundary-churn diagnostic"
```
