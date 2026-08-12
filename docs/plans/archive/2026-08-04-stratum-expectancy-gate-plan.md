# Stratum Expectancy Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract `frame_gate_passes`/`evaluate_frame_gate` out of `services/counterfactual_tracker.py` into a new Ring 1 module (`src/intelligence/statistics/gate_math.py`, mirroring `ic_math.py`'s existing precedent), repoint both current consumers at the new location, and add one new reusable specialization — `evaluate_stratum_expectancy_gate` — for the `(regime, direction)` stratification question todo 179 had to answer ad hoc.

**Architecture:** Pure-function extraction with zero behavior change (proven by an equivalence test before either consumer is touched), followed by two mechanical import-path migrations, followed by one small additive specialization built entirely on the already-generic `evaluate_frame_gate` core — no new bootstrap statistics anywhere in this plan.

**Tech Stack:** Python, numpy, scipy.stats.bootstrap (already a dependency, unchanged), pytest.

## Global Constraints

- No behavior change to `frame_gate_passes` or `evaluate_frame_gate` — moved verbatim, not rewritten.
- `services/counterfactual_tracker.py` and `services/cross_sectional_spread_tracker.py`'s existing test suites (`tests/unit/test_counterfactual_tracker.py`, `tests/unit/test_counterfactual_tracker_exit_priority.py`, `tests/unit/test_cross_sectional_spread_tracker.py`) must pass unmodified — zero edits to those test files anywhere in this plan.
- No live wiring: this plan does not touch `alpha_publisher.py`, `ensemble_trainer.py`, or any construction. Per `docs/plans/archive/2026-08-04-stratum-expectancy-gate-design.md`'s explicit non-goal.
- No persisted verdict table, no row-assembly helpers — out of scope per the design doc.
- Ring rules: `gate_math.py` lives in Ring 1 (`src/intelligence/statistics/`) since `regime`/`direction` are domain vocabulary (fails Ring 0's portability test), matching `ic_math.py`'s own placement. `services/` (Ring 2) importing from `src/intelligence/` (Ring 1) is explicitly permitted per `docs/foundation/naming-system.md` §2.

---

### Task 1: Extract `gate_math.py` with an equivalence test

**Files:**
- Create: `src/intelligence/statistics/gate_math.py`
- Test: `tests/unit/test_gate_math.py`

**Interfaces:**
- Produces: `_DEFAULT_BOOTSTRAP_RANDOM_STATE: int`, `frame_gate_passes(pnl_r_values: Sequence[float], cluster_ids: Sequence[Any], min_n: int, bootstrap_max_n: int, bootstrap_batch: int, bootstrap_random_state: int = _DEFAULT_BOOTSTRAP_RANDOM_STATE) -> tuple[bool, float, float]`, `evaluate_frame_gate(rows: Iterable[dict[str, Any]], min_n: int, bootstrap_max_n: int, bootstrap_batch: int, bootstrap_random_state: int = _DEFAULT_BOOTSTRAP_RANDOM_STATE, group_key: Callable[[dict[str, Any]], tuple[Any, Any]] | None = None, min_clusters: int | None = None) -> list[dict[str, Any]]` — all three used verbatim by Task 2/3.

- [ ] **Step 1: Write the new module with the two functions moved verbatim**

Create `src/intelligence/statistics/gate_math.py`:

```python
"""Day-clustered block-bootstrap gate math — shared statistical core for any
construction that needs to ask "does this stratum's realized pnl clear a rigorous,
non-circular expectancy bar?"

Extracted from services/counterfactual_tracker.py (todo 249, 2026-08-04):
services/cross_sectional_spread_tracker.py was already importing these same
functions directly from counterfactual_tracker.py -- a Ring 2 service reaching into
another Ring 2 service's internals for what is actually generic statistics with zero
DB/Kafka/daemon dependency of its own. Moving the math here (Ring 1, matching
src/intelligence/statistics/ic_math.py's own precedent for exactly this situation)
gives every consumer a stable import target that doesn't depend on
counterfactual_tracker.py's own service lifecycle.

Pure functions only -- no DB, no config loading, no module-global mutable state
besides _DEFAULT_BOOTSTRAP_RANDOM_STATE.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any

import numpy as np
from scipy.stats import bootstrap

_DEFAULT_BOOTSTRAP_RANDOM_STATE = 42


def frame_gate_passes(
    pnl_r_values: Sequence[float],
    cluster_ids: Sequence[Any],
    min_n: int,
    bootstrap_max_n: int,
    bootstrap_batch: int,
    bootstrap_random_state: int = _DEFAULT_BOOTSTRAP_RANDOM_STATE,
) -> tuple[bool, float, float]:
    """FRAME-04 day-clustered block-bootstrap exit gate (review H4).

    Aggregates pnl to per-cluster (calendar-day) means BEFORE resampling -- overlapping hold
    horizons make per-frame i.i.d. resampling anticonservative (a gate that can pass on noise
    defeats the phase's purpose). Below bootstrap_max_n day-clusters, uses
    scipy.stats.bootstrap (method='BCa', one-sided alternative='greater', batch=
    bootstrap_batch to cap peak resample-matrix memory). Above bootstrap_max_n clusters,
    BCa's jackknife (N leave-one-out evaluations) is computationally infeasible and its
    bias-correction negligible at that cluster count, so an analytic one-sided 95% CLT lower
    bound is used instead: mean - 1.645 * std(ddof=1) / sqrt(n_clusters).

    Returns (passes, ci_lower, ci_upper). passes iff ci_lower > 0.
    Returns (False, nan, nan) when len(pnl_r_values) < min_n (the alpha.scoring.
    min_strategy_n frame-count sufficiency floor) or when fewer than 2 day-clusters exist
    (a bootstrap CI cannot be formed from <2 blocks).

    bootstrap_random_state seeds scipy's BCa resampling (alpha.scoring.bootstrap_random_state
    APR key, default 42) so the frozen SHADOW-REVIEW.md "no post-hoc gate renegotiation" verdict
    is reproducible across identical re-runs (code-review WR-01) -- changing this key invalidates
    any prior gate verdict for cells that used the BCa path (len(cluster_means) <= bootstrap_max_n).
    """
    if len(pnl_r_values) < min_n:
        return False, float("nan"), float("nan")

    cluster_members: dict[Any, list[float]] = {}
    for pnl, cluster_id in zip(pnl_r_values, cluster_ids):
        cluster_members.setdefault(cluster_id, []).append(pnl)
    # Sorted at two levels (todo 172), not raw dict/list insertion order: cluster_id is a
    # calendar date (bar_ts::date), so sorting clusters also gives chronological order for
    # free. BCa resampling below is seeded with a FIXED bootstrap_random_state -- a fixed
    # seed draws specific index positions from cluster_means, so an array whose element
    # order depended on row-fetch order (TimescaleDB doesn't guarantee stable interleaving
    # across parallel chunk scans for a plain ORDER BY bar_ts) made the resulting CI
    # silently non-reproducible run-to-run on unchanged data. Sorting each cluster's own
    # pnl values before averaging additionally makes np.mean's summation order
    # deterministic -- floating-point addition is not associative, so leaving within-
    # cluster order to row-fetch order would still leave ULP-level noise in cluster_means
    # even after the (larger) inter-cluster ordering bug above is fixed.
    cluster_means = np.array(
        [float(np.mean(sorted(cluster_members[cid]))) for cid in sorted(cluster_members)],
        dtype=float,
    )

    if len(cluster_means) < 2:
        return False, float("nan"), float("nan")

    if len(cluster_means) <= bootstrap_max_n:
        result = bootstrap(
            (cluster_means,),
            np.mean,
            confidence_level=0.95,
            alternative="greater",
            method="BCa",
            batch=bootstrap_batch,
            random_state=np.random.default_rng(bootstrap_random_state),
        )
        ci_lower = float(result.confidence_interval.low)
        ci_upper = float(result.confidence_interval.high)
    else:
        # Analytic one-sided 95% CLT lower bound -- BCa's jackknife is infeasible at this
        # cluster count and its bias correction negligible here (review H4).
        n_clusters = len(cluster_means)
        mean = float(np.mean(cluster_means))
        std = float(np.std(cluster_means, ddof=1))
        ci_lower = mean - 1.645 * std / np.sqrt(n_clusters)
        ci_upper = float("inf")

    return bool(ci_lower > 0), ci_lower, ci_upper


def evaluate_frame_gate(
    rows: Iterable[dict[str, Any]],
    min_n: int,
    bootstrap_max_n: int,
    bootstrap_batch: int,
    bootstrap_random_state: int = _DEFAULT_BOOTSTRAP_RANDOM_STATE,
    group_key: Callable[[dict[str, Any]], tuple[Any, Any]] | None = None,
    min_clusters: int | None = None,
) -> list[dict[str, Any]]:
    """Pure grouping/aggregation core for day-clustered bootstrap gate evaluation.

    Takes an in-memory iterable of dicts with keys tf, regime, cluster_id, pnl_r -- pnl_r is
    the GROSS realized counterfactual_pnl_r (D-01); this function applies no adjustment to
    it whatsoever. Groups rows by group_key (default: (tf, regime), the FRAME-04 in-sample
    exit gate's original grouping -- omitting group_key preserves that behavior byte-for-byte).
    A second caller (the OOS regime-stratified promotion gate, todo 165) reuses this same
    core with group_key=lambda row: (row["direction"], row["regime"]) rather than
    duplicating the day-clustered bootstrap machinery.

    Passes each cell's per-frame calendar-date cluster_id straight into frame_gate_passes
    unmodified (day-clustered, review H4), and respects the min_n frame-count sufficiency
    floor via that same call.

    min_clusters (optional): a day-cluster coverage floor distinct from min_n's frame-count
    floor -- a cell can clear min_n on frame count alone while resting on too few
    independent day-observations for the bootstrap CI to mean anything (todo 165). When set,
    a cell with n_clusters < min_clusters is marked coverage="insufficient" and its "passes"
    field is forced to None (neither pass nor fail) regardless of frame_gate_passes' own
    verdict -- never silently counted as a failure. Cells at/above the floor (or when
    min_clusters is None, preserving current callers' behavior) get coverage="evaluated".

    Returns one verdict dict per group_key cell: tf, regime, n_frames, n_clusters, ci_lower,
    ci_upper, passes, coverage. (tf/regime keys are populated from the group_key tuple's two
    elements regardless of what group_key actually groups by, so existing callers that group
    by (tf, regime) see unchanged field names.)
    """
    if group_key is None:
        group_key = lambda row: (row["tf"], row["regime"])  # noqa: E731

    groups: dict[tuple[Any, Any], dict[str, list[Any]]] = {}
    for row in rows:
        key = group_key(row)
        bucket = groups.setdefault(key, {"pnl_r": [], "cluster_id": []})
        bucket["pnl_r"].append(row["pnl_r"])
        bucket["cluster_id"].append(row["cluster_id"])

    verdicts: list[dict[str, Any]] = []
    for (dim_a, dim_b), bucket in groups.items():
        passes, ci_lower, ci_upper = frame_gate_passes(
            bucket["pnl_r"],
            bucket["cluster_id"],
            min_n,
            bootstrap_max_n,
            bootstrap_batch,
            bootstrap_random_state,
        )
        n_clusters = len(set(bucket["cluster_id"]))
        coverage = "evaluated"
        if min_clusters is not None and n_clusters < min_clusters:
            coverage = "insufficient"
            passes = None
        verdicts.append(
            {
                "tf": dim_a,
                "regime": dim_b,
                "n_frames": len(bucket["pnl_r"]),
                "n_clusters": n_clusters,
                "ci_lower": ci_lower,
                "ci_upper": ci_upper,
                "passes": passes,
                "coverage": coverage,
            }
        )
    return verdicts
```

- [ ] **Step 2: Write the equivalence test proving the extraction is behavior-preserving**

Create `tests/unit/test_gate_math.py`:

```python
"""Unit tests: src/intelligence/statistics/gate_math.py -- the extracted day-clustered
bootstrap gate core (todo 249), plus evaluate_stratum_expectancy_gate (Task 4).
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.intelligence.statistics.gate_math import (
    evaluate_frame_gate,
    frame_gate_passes,
)


def test_frame_gate_passes_below_min_n_returns_nan():
    passes, ci_lower, ci_upper = frame_gate_passes(
        [0.1, 0.2], ["2026-01-01", "2026-01-02"], min_n=5,
        bootstrap_max_n=5000, bootstrap_batch=1000,
    )
    assert passes is False
    assert ci_lower != ci_lower  # nan
    assert ci_upper != ci_upper  # nan


def test_frame_gate_passes_below_two_clusters_returns_nan():
    passes, ci_lower, ci_upper = frame_gate_passes(
        [0.1, 0.2, 0.3], ["2026-01-01", "2026-01-01", "2026-01-01"], min_n=1,
        bootstrap_max_n=5000, bootstrap_batch=1000,
    )
    assert passes is False
    assert ci_lower != ci_lower  # nan


def test_frame_gate_passes_analytic_path_above_bootstrap_max_n():
    """Above bootstrap_max_n clusters, uses the analytic CLT lower bound (ci_upper=inf)."""
    pnl_r_values = [1.0] * 20
    cluster_ids = [f"2026-01-{d:02d}" for d in range(1, 21)]
    passes, ci_lower, ci_upper = frame_gate_passes(
        pnl_r_values, cluster_ids, min_n=1, bootstrap_max_n=10, bootstrap_batch=1000,
    )
    assert ci_upper == float("inf")
    assert passes is True  # all pnl_r=1.0, mean is way above zero


def test_evaluate_frame_gate_groups_by_tf_and_regime():
    rows = [
        {"tf": "5m", "regime": "trending_up", "cluster_id": "2026-01-01", "pnl_r": 0.5},
        {"tf": "5m", "regime": "trending_up", "cluster_id": "2026-01-01", "pnl_r": 0.6},
        {"tf": "5m", "regime": "ranging", "cluster_id": "2026-01-01", "pnl_r": -0.2},
        {"tf": "1h", "regime": "trending_up", "cluster_id": "2026-01-01", "pnl_r": 0.3},
    ]
    verdicts = evaluate_frame_gate(rows, min_n=1, bootstrap_max_n=5000, bootstrap_batch=1000)
    cells = {(v["tf"], v["regime"]) for v in verdicts}
    assert cells == {("5m", "trending_up"), ("5m", "ranging"), ("1h", "trending_up")}


def test_evaluate_frame_gate_min_clusters_marks_insufficient():
    rows = [
        {"tf": "1h", "regime": "high_neutral", "cluster_id": f"day-{i}", "pnl_r": 0.1}
        for i in range(5)
    ] + [
        {"tf": "1h", "regime": "low_bull", "cluster_id": f"day-{i}", "pnl_r": 0.1}
        for i in range(25)
    ]
    verdicts = evaluate_frame_gate(
        rows, min_n=1, bootstrap_max_n=5000, bootstrap_batch=1000, min_clusters=20
    )
    by_regime = {v["regime"]: v for v in verdicts}
    assert by_regime["high_neutral"]["coverage"] == "insufficient"
    assert by_regime["high_neutral"]["passes"] is None
    assert by_regime["low_bull"]["coverage"] == "evaluated"
    assert by_regime["low_bull"]["passes"] is not None


def test_gate_math_equivalence_with_counterfactual_tracker_output():
    """Equivalence proof (design doc requirement): identical fixture data through the
    extracted gate_math functions must match services.counterfactual_tracker's
    frame_gate_passes/evaluate_frame_gate byte-for-byte, once Task 2 repoints that module
    to import from here. Import both under their current names -- after Task 2 lands,
    services.counterfactual_tracker.frame_gate_passes IS this module's frame_gate_passes
    (same function object via re-export), so this test asserts object identity, the
    strongest possible equivalence proof.
    """
    from services.counterfactual_tracker import (
        evaluate_frame_gate as tracker_evaluate_frame_gate,
    )
    from services.counterfactual_tracker import (
        frame_gate_passes as tracker_frame_gate_passes,
    )

    assert tracker_frame_gate_passes is frame_gate_passes
    assert tracker_evaluate_frame_gate is evaluate_frame_gate
```

- [ ] **Step 3: Run the new tests to verify they fail import (module doesn't exist as a consumer target yet is fine — the file itself was just created, so only the LAST test should fail)**

Run: `.venv/bin/pytest tests/unit/test_gate_math.py -v`
Expected: first 5 tests PASS (they only import from the new `gate_math.py`, which now exists with real implementations). `test_gate_math_equivalence_with_counterfactual_tracker_output` FAILS with `AssertionError` (object identity), because Task 2 hasn't repointed `counterfactual_tracker.py` yet — this is the expected, correct failure state at this point in the plan.

- [ ] **Step 4: Commit**

```bash
git add src/intelligence/statistics/gate_math.py tests/unit/test_gate_math.py
git commit -m "feat(intelligence): extract gate_math.py from counterfactual_tracker.py (todo 249)"
```

---

### Task 2: Repoint `counterfactual_tracker.py` at the extracted module

**Files:**
- Modify: `services/counterfactual_tracker.py`

**Interfaces:**
- Consumes: `frame_gate_passes`, `evaluate_frame_gate`, `_DEFAULT_BOOTSTRAP_RANDOM_STATE` from `src.intelligence.statistics.gate_math` (Task 1).
- Produces: nothing new — `services.counterfactual_tracker.frame_gate_passes`/`evaluate_frame_gate`/`_DEFAULT_BOOTSTRAP_RANDOM_STATE` remain accessible at their current import path (re-exported), so `tests/unit/test_counterfactual_tracker.py`'s existing `from services.counterfactual_tracker import (..., evaluate_frame_gate)` continues to work unmodified.

- [ ] **Step 1: Remove the local definitions, import from gate_math instead**

In `services/counterfactual_tracker.py`:

1. Delete the local `_DEFAULT_BOOTSTRAP_RANDOM_STATE = 42` definition (line 84) and both function definitions: `frame_gate_passes` (lines 173-248) and `evaluate_frame_gate` (lines 921-989), including their docstrings and the `# FRAME-04 gate evaluation` section comment immediately above `evaluate_frame_gate`.

2. Remove the now-unused `from scipy.stats import bootstrap` import (only `frame_gate_passes` used it) — verify with `grep -n "bootstrap" services/counterfactual_tracker.py` that no other line in the file references `bootstrap` before removing.

3. Add, near the top of the file's own imports (alongside its other `from src...` imports if any, otherwise directly after the stdlib/third-party import block):

```python
from src.intelligence.statistics.gate_math import (
    _DEFAULT_BOOTSTRAP_RANDOM_STATE,
    evaluate_frame_gate,
    frame_gate_passes,
)
```

This makes `frame_gate_passes`, `evaluate_frame_gate`, and `_DEFAULT_BOOTSTRAP_RANDOM_STATE` available as module-level attributes of `services.counterfactual_tracker` exactly as before (Python re-exposes any name imported at module scope), so every internal call site in this file (e.g. the `--evaluate-gate` CLI mode's use of `_DEFAULT_BOOTSTRAP_RANDOM_STATE` as an APR fallback default, and `cross_sectional_spread_tracker.py`'s existing cross-import, addressed in Task 3) keeps working with zero further changes in this file.

- [ ] **Step 2: Run the equivalence test to verify it now passes**

Run: `.venv/bin/pytest tests/unit/test_gate_math.py::test_gate_math_equivalence_with_counterfactual_tracker_output -v`
Expected: PASS — `services.counterfactual_tracker.frame_gate_passes` is now the identical function object as `src.intelligence.statistics.gate_math.frame_gate_passes`.

- [ ] **Step 3: Run the full existing counterfactual_tracker test suites to verify zero regressions**

Run: `.venv/bin/pytest tests/unit/test_counterfactual_tracker.py tests/unit/test_counterfactual_tracker_exit_priority.py -v`
Expected: PASS, identical pass count to before this task's changes. No test file in this command was edited.

- [ ] **Step 4: Commit**

```bash
git add services/counterfactual_tracker.py
git commit -m "refactor(counterfactual-tracker): import gate math from gate_math.py (todo 249)"
```

---

### Task 3: Repoint `cross_sectional_spread_tracker.py` at the extracted module

**Files:**
- Modify: `services/cross_sectional_spread_tracker.py`

**Interfaces:**
- Consumes: `_DEFAULT_BOOTSTRAP_RANDOM_STATE`, `evaluate_frame_gate`, `frame_gate_passes` from `src.intelligence.statistics.gate_math` (Task 1) — identical names, only the import source changes.

- [ ] **Step 1: Change the import source**

In `services/cross_sectional_spread_tracker.py`, find (around line 92-96):

```python
from services.counterfactual_tracker import (  # noqa: E402
    _DEFAULT_BOOTSTRAP_RANDOM_STATE,
    evaluate_frame_gate,
    frame_gate_passes,
)
```

Replace with:

```python
from src.intelligence.statistics.gate_math import (  # noqa: E402
    _DEFAULT_BOOTSTRAP_RANDOM_STATE,
    evaluate_frame_gate,
    frame_gate_passes,
)
```

No other line in this file changes — every call site (`frame_gate_passes` at line 711, `evaluate_frame_gate` at line 424, `_DEFAULT_BOOTSTRAP_RANDOM_STATE` at line 1159) refers to these names unqualified, so the import-source change is the only edit needed.

- [ ] **Step 2: Run the existing cross_sectional_spread_tracker test suite to verify zero regressions**

Run: `.venv/bin/pytest tests/unit/test_cross_sectional_spread_tracker.py -v`
Expected: PASS, identical pass count to before this task's changes. This test file was not edited.

- [ ] **Step 3: Commit**

```bash
git add services/cross_sectional_spread_tracker.py
git commit -m "refactor(cross-sectional-spread-tracker): import gate math from gate_math.py (todo 249)"
```

---

### Task 4: Add `evaluate_stratum_expectancy_gate`

**Files:**
- Modify: `src/intelligence/statistics/gate_math.py`
- Test: `tests/unit/test_gate_math.py`

**Interfaces:**
- Produces: `evaluate_stratum_expectancy_gate(rows: Iterable[Mapping[str, Any]], min_n: int, bootstrap_max_n: int, bootstrap_batch: int, bootstrap_random_state: int, min_clusters: int | None = None) -> list[dict[str, Any]]` — the reusable primitive this whole plan exists to deliver. No consumer in this codebase calls it yet (per the design doc's explicit non-goal); it exists as tested, ready infrastructure.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_gate_math.py`:

```python
from src.intelligence.statistics.gate_math import evaluate_stratum_expectancy_gate


def test_evaluate_stratum_expectancy_gate_groups_by_regime_and_direction():
    rows = [
        {"regime": "mid_bull", "direction": "long", "cluster_id": "2026-01-01", "pnl_r": 0.1},
        {"regime": "mid_bull", "direction": "long", "cluster_id": "2026-01-02", "pnl_r": 0.2},
        {"regime": "mid_bull", "direction": "short", "cluster_id": "2026-01-01", "pnl_r": -0.1},
        {"regime": "high_neutral", "direction": "long", "cluster_id": "2026-01-01", "pnl_r": 0.3},
    ]
    verdicts = evaluate_stratum_expectancy_gate(
        rows, min_n=1, bootstrap_max_n=5000, bootstrap_batch=1000, bootstrap_random_state=42
    )
    cells = {(v["regime"], v["direction"]) for v in verdicts}
    assert cells == {
        ("mid_bull", "long"),
        ("mid_bull", "short"),
        ("high_neutral", "long"),
    }
    # Field names are regime/direction, never the generic tf/regime evaluate_frame_gate
    # returns internally (naming-system.md Whiteboard Test -- see design doc).
    for v in verdicts:
        assert "tf" not in v
        assert set(v.keys()) == {
            "regime", "direction", "n_bars", "n_clusters",
            "ci_lower", "ci_upper", "passes", "coverage",
        }


def test_evaluate_stratum_expectancy_gate_degenerate_cluster_count():
    """Fewer than 2 day-clusters in a cell -> (False, nan, nan), reused unmodified from
    frame_gate_passes' existing documented contract (no reimplementation)."""
    rows = [
        {"regime": "mid_bull", "direction": "long", "cluster_id": "2026-01-01", "pnl_r": 0.1},
        {"regime": "mid_bull", "direction": "long", "cluster_id": "2026-01-01", "pnl_r": 0.2},
    ]
    verdicts = evaluate_stratum_expectancy_gate(
        rows, min_n=1, bootstrap_max_n=5000, bootstrap_batch=1000, bootstrap_random_state=42
    )
    assert verdicts[0]["passes"] is False
    assert verdicts[0]["ci_lower"] != verdicts[0]["ci_lower"]  # nan


def test_evaluate_stratum_expectancy_gate_min_clusters_coverage_floor():
    rows = [
        {"regime": "mid_bull", "direction": "long", "cluster_id": f"day-{i}", "pnl_r": 0.1}
        for i in range(5)
    ] + [
        {"regime": "high_neutral", "direction": "long", "cluster_id": f"day-{i}", "pnl_r": 0.1}
        for i in range(25)
    ]
    verdicts = evaluate_stratum_expectancy_gate(
        rows, min_n=1, bootstrap_max_n=5000, bootstrap_batch=1000,
        bootstrap_random_state=42, min_clusters=20,
    )
    by_regime = {v["regime"]: v for v in verdicts}
    assert by_regime["mid_bull"]["coverage"] == "insufficient"
    assert by_regime["mid_bull"]["passes"] is None
    assert by_regime["high_neutral"]["coverage"] == "evaluated"
    assert by_regime["high_neutral"]["passes"] is not None


def test_evaluate_stratum_expectancy_gate_delegates_to_evaluate_frame_gate():
    """No bootstrap math reimplemented here (design doc requirement) -- proven by asserting
    the function's own source contains no 'bootstrap(' call and no 'np.mean'/'np.std' of its
    own, only a call into evaluate_frame_gate."""
    import inspect

    source = inspect.getsource(evaluate_stratum_expectancy_gate)
    assert "evaluate_frame_gate(" in source
    assert "bootstrap(" not in source
    assert "np.std(" not in source
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/pytest tests/unit/test_gate_math.py -k stratum_expectancy -v`
Expected: FAIL with `ImportError: cannot import name 'evaluate_stratum_expectancy_gate'`.

- [ ] **Step 3: Implement `evaluate_stratum_expectancy_gate`**

Append to `src/intelligence/statistics/gate_math.py`, after `evaluate_frame_gate`:

```python
def evaluate_stratum_expectancy_gate(
    rows: Iterable[dict[str, Any]],
    min_n: int,
    bootstrap_max_n: int,
    bootstrap_batch: int,
    bootstrap_random_state: int,
    min_clusters: int | None = None,
) -> list[dict[str, Any]]:
    """Day-clustered bootstrap expectancy verdict per (regime, direction) stratum.

    Each input row carries `regime`, `direction`, `cluster_id` (a calendar date), and
    `pnl_r` (the realized or simulated per-bar return for that stratum). Delegates
    entirely to `evaluate_frame_gate` with `group_key=lambda r: (r["regime"],
    r["direction"])` -- no bootstrap logic is reimplemented here, matching
    `evaluate_spread_gate`'s own precedent in `cross_sectional_spread_tracker.py`
    (design decision: docs/plans/archive/2026-08-04-stratum-expectancy-gate-design.md).

    Answers the question todo 179 (.planning/todos/completed/179-gate166-concurrent-
    exposure-diagnostic.md) had to answer by hand: does a given regime x direction
    stratum have a statistically valid, non-zero expected value, or is it noise?

    Returns one verdict dict per (regime, direction) cell: `regime`, `direction`,
    `n_bars`, `n_clusters`, `ci_lower`, `ci_upper`, `passes`, `coverage`. `passes=True`
    means this stratum's day-clustered bootstrap CI lower bound clears zero -- a
    statistically valid, non-zero expected value, not proof of a tradeable edge on its
    own (the caller must also check `n_bars`/`n_clusters`/`coverage` against whatever
    sufficiency floor its own context requires).

    No consumer wires this into a live construction yet (per the design doc's explicit
    non-goal) -- this is tested, reusable infrastructure, not an active gate.
    """
    verdicts = evaluate_frame_gate(
        rows,
        min_n,
        bootstrap_max_n,
        bootstrap_batch,
        bootstrap_random_state,
        group_key=lambda row: (row["regime"], row["direction"]),
        min_clusters=min_clusters,
    )
    return [
        {
            "regime": v["tf"],
            "direction": v["regime"],
            "n_bars": v["n_frames"],
            "n_clusters": v["n_clusters"],
            "ci_lower": v["ci_lower"],
            "ci_upper": v["ci_upper"],
            "passes": v["passes"],
            "coverage": v["coverage"],
        }
        for v in verdicts
    ]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/pytest tests/unit/test_gate_math.py -v`
Expected: PASS, all tests in the file.

- [ ] **Step 5: Full-repo verification**

Run: `.venv/bin/ruff check src/intelligence/statistics/gate_math.py tests/unit/test_gate_math.py services/counterfactual_tracker.py services/cross_sectional_spread_tracker.py`
Expected: clean, no findings.

Run: `.venv/bin/black --check src/intelligence/statistics/gate_math.py tests/unit/test_gate_math.py services/counterfactual_tracker.py services/cross_sectional_spread_tracker.py`
Expected: clean, no reformatting needed (or run without `--check` once to apply formatting, then re-stage).

Run: `.venv/bin/pytest tests/unit/ -q`
Expected: full suite green, pass count >= the pre-plan baseline (no test removed, several added).

- [ ] **Step 6: Commit**

```bash
git add src/intelligence/statistics/gate_math.py tests/unit/test_gate_math.py
git commit -m "feat(intelligence): add evaluate_stratum_expectancy_gate (todo 249)"
```

---

## Self-Review Notes

- **Spec coverage:** design doc's module layout (Task 1/4), consumer migration (Task 2/3), testing section (equivalence test in Task 1, unit tests in Task 4), and naming section (verified field names in Task 4's grouping test) are each covered by a task.
- **Type consistency:** `evaluate_stratum_expectancy_gate`'s signature, field names (`regime`/`direction`/`n_bars`/`n_clusters`/`ci_lower`/`ci_upper`/`passes`/`coverage`), and its delegation shape match the design doc's specification exactly and are asserted directly in Task 4's tests.
- **No placeholders:** every step contains complete, real code — no "add tests for the above," no "similar to Task N."
