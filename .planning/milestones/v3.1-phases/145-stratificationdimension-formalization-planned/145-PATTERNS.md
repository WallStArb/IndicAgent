# Phase 145: StratificationDimension Formalization - Pattern Map

**Mapped:** 2026-08-06
**Files analyzed:** 10 (6 new source modules + 4 new test files)
**Analogs found:** 10 / 10

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `src/intelligence/stratification/contract.py` (`StratificationDimension` Protocol/ABC) | interface/contract module | transform (pure, no IO) | `src/intelligence/plugins/base.py` (`PatternPlugin`/`IndicatorPlugin` Protocol + `PluginRegistry.validate_tier`) | role-match (archived subsystem, shape-only reference — do not import) |
| `src/intelligence/stratification/gates.py` (gate 0/1/2 + effective-N-from-transitions) | service/statistics module | transform (pure functions) | `src/intelligence/statistics/ic_math.py` (`apply_bh_fdr`, `_hac_sharpe_nd`) + `services/regime_writer.py` (`_check_occupation_gate`, `_smooth_states`) | exact (statistical gate pure-function shape) |
| `src/intelligence/stratification/fdr.py` (BH-FDR wiring, per-`regime_group` cumulative history) | service/statistics module | transform (pure) | `src/intelligence/statistics/ic_math.py::apply_bh_fdr` | exact (direct reuse, thin wrapper only) |
| `src/intelligence/stratification/acausal_placebo_gate.py` (D-05 registration gate) | service/validation module | event-driven (registration-time check) + request-response (hard-raise) | `scripts/ops/alpha/ops_canary_integrity_assert.py` (`evaluate()`, `CanaryIntegrityViolation`) + `src/intelligence/feature_factory.py::_canary_acausal_placebo` | exact |
| `src/intelligence/stratification/volatility_pct.py` (D-06 pilot dimension) | service/regime-signal module | transform (compute/score split) | `src/intelligence/regime_signals/breadth_vol.py` (`compute()`/`build_tiers()`) + `causal_rank.py::causal_expanding_rank()` | exact |
| `src/intelligence/stratification/__init__.py` | package init | — | `src/intelligence/regime_signals/__init__.py` | exact (trivial) |
| `tests/unit/test_stratification_contract.py` | test | request-response (Protocol conformance + `ic_engine.py` compat shape) | `tests/unit/test_ic_engine_routing.py` (pure-function import + assert pattern) | exact |
| `tests/unit/test_stratification_gates.py` | test | transform (pure gate functions) | `tests/unit/test_regime_writer_occupation_gate.py` | exact |
| `tests/unit/test_acausal_placebo_registration.py` | test | event-driven (hard-raise on failure) | `tests/unit/test_canary_predictors.py` | exact |
| `tests/unit/test_volatility_pct_pilot.py` | test | transform (compute/score pilot, real-ish OHLCV-shaped fixtures) | `tests/unit/test_regime_signals_breadth_vol.py` + `tests/unit/test_regime_signals_causal_rank.py` | exact |

## Pattern Assignments

### `src/intelligence/stratification/contract.py` (interface, pure)

**Analog:** `src/intelligence/plugins/base.py` (archived I1-I7 subsystem — **pattern reference only, do not import from it or extend its classes**; the live `regime_signals/` modules below are the actual reuse target for the `compute()`/`score()` shape).

**Protocol shape to mirror** (`src/intelligence/plugins/base.py` lines 1-8, 50-80):
```python
from __future__ import annotations

from dataclasses import dataclass
from re import Pattern as RePattern
from typing import Any, ClassVar, Protocol

from src.core.models import AssetClass


class PatternPlugin(Protocol):
    name: ClassVar[str]
    outputs: ClassVar[set[str]]
    min_lookback: ClassVar[int]
    supports_incremental: ClassVar[bool]
    capability_tags: ClassVar[set[str]]
    inputs: ClassVar[list[InputSpec]]
    valid_asset_classes: ClassVar[frozenset[AssetClass]]
    regime_type: ClassVar[str]  # Must be "trend", "mean_reversion", or "any"

    def compute_full(
        self, frames: dict[str, Any], *, state: dict | None = None
    ) -> dict[str, Any]: ...
    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]:
        """Incremental single-bar update using accumulated state.
        ...
        """
        ...
```
Adapt: `ClassVar` identity fields (`name`, `grain`, `labels`, `causality_basis: Literal["deterministic", "expanding_window", "fitted"]`) + instance methods `compute()`/`score()` (not `compute_full`/`compute_next` — that split is I1-I7-specific incremental-vs-full-batch, not relevant here; the `regime_signals/` `compute()`/`build_tiers()` split below is the actually-relevant behavioral split).

**Hard-crash registration-check pattern to mirror** (`src/intelligence/plugins/base.py` lines 106-120):
```python
class ArchitectureViolation(Exception):
    """Raised when a plugin violates a mandatory architectural constraint.

    Raised at startup ... Never raised per-bar -- architecture validation is
    startup-time only, not on the hot path.
    """

def validate_tier(self, names: list[str], tier: str) -> None:
    """Raise ValueError at startup if any name is not in the registry."""
    all_known = set(self.indicators) | set(self.patterns)
    unknown = [n for n in names if n not in all_known]
    if unknown:
        raise ValueError(
            f"Tier {tier} references unregistered plugin(s): {unknown}. "
            f"Check register_plugins.py and the TIER_* constants."
        )
```
This is the exact shape for a `validate_registration(provider)` function that D-05's acausal-placebo gate hooks into — raise a custom exception (see `acausal_placebo_gate.py` below), never warn-and-continue.

**`compute()`/`score()` split to mirror** (live, not archived — `src/intelligence/regime_signals/breadth_vol.py` lines 62-112):
```python
PROB_KEYS: tuple[str, str] = ("vix_pct", "breadth_pct")

def compute(
    ref_bars: dict[str, pd.DataFrame],
    params: dict[str, Any],
) -> tuple[pd.Series, pd.Series] | None:
    """... ref_bars/params are the only inputs -- no psycopg import, no DB access."""
    ...

def build_tiers(params: dict[str, Any]) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Return threshold tier lists for the generic label worker."""
    ...
```
This is the closest live precedent for the Protocol's `compute() -> labels` / `score() -> float` split named in CONTEXT.md.

**ic_engine.py compatibility note (read-only reference, do not import into `src/intelligence/`):** `services/ic_engine.py` lines 225-236 (`_resolve_regime_scope`), 260-313 (`AmbiguousRegimeGroupError` + `_build_symbol_regime_class`), 2399-2429 (`_build_regime_passes`) are the consumer shapes the contract must stay compatible with — mirror their `dict[str, str]` / `(label_array, distinct_labels, resolved_scope)` tuple shapes in a compatibility test, never import these private functions from Ring 1.

---

### `src/intelligence/stratification/gates.py` (gate 0/1/2 + effective-N)

**Analog 1 — BH-FDR (reuse directly):** `src/intelligence/statistics/ic_math.py` lines 545-564:
```python
def apply_bh_fdr(p_values: list[float], alpha: float) -> tuple[np.ndarray, np.ndarray]:
    """Benjamini-Hochberg FDR correction over one family of p-values. ...
    Returns (reject, p_corrected) as parallel arrays in the same order as p_values.
    Returns two empty arrays for an empty input (no family to correct).
    """
    if not p_values:
        return np.array([], dtype=bool), np.array([], dtype=float)
    reject, p_corrected, _, _ = multipletests(p_values, alpha=alpha, method="fdr_bh")
    return reject, p_corrected
```
Import as `from src.intelligence.statistics.ic_math import apply_bh_fdr` — do not hand-roll a fourth copy (three existing call sites already avoided this).

**Analog 2 — autocorrelation-adjusted effective-N prior art (study, don't import):** `src/intelligence/statistics/ic_math.py` lines 967-1006 (`_hac_sharpe_nd`) — Newey-West Bartlett-kernel inflation factor; same "autocorrelation shrinks effective N" family as D-04's transition-counting estimator, useful as an optional cross-check, not the primary implementation.

**Analog 3 — transition-counting effective-N (pattern to write, informed by, do not import):** `services/regime_writer.py` lines 400-416 (`_smooth_states`) — the `min_hold_bars` smoother that makes regime labels autocorrelated; `services/regime_writer.py` lines 419-463 (`_check_occupation_gate`) — the exact `(bool, dict)` diagnostics-return shape to mirror for a new `effective_n_from_transitions()` function:
```python
def _smooth_states(raw_states: np.ndarray, min_hold: int) -> np.ndarray:
    """Minimum holding-period smoother. Requires min_hold consecutive bars of the same
    new state before confirming a transition. Causal — no look-ahead."""
    if min_hold <= 1:
        return raw_states.copy()
    n = len(raw_states)
    smoothed = raw_states.copy()
    current = int(raw_states[0])
    for t in range(1, n):
        if t < min_hold:
            smoothed[t] = current
            continue
        window = raw_states[t - min_hold + 1 : t + 1]
        if np.all(window == raw_states[t]):
            current = int(raw_states[t])
        smoothed[t] = current
    return smoothed


def _check_occupation_gate(
    smoothed_states: np.ndarray,
    n_components: int,
    min_state_occupation: float,
    converged: bool,
) -> tuple[bool, dict[str, Any]]:
    """Guard against degenerate HMM fits before their labels can be written.
    ... Guards run in this order BEFORE any division by len(smoothed_states) so
    empty/short input can never divide-by-zero or index out of range.
    """
    n_obs = len(smoothed_states)
    if n_obs == 0:
        return True, {"reason": "empty_series", "n_obs": 0}
    if n_obs < n_components:
        return True, {"reason": "insufficient_obs", "n_obs": n_obs, "n_components": n_components}
    if not converged:
        return True, {"reason": "not_converged", "n_obs": n_obs}
    occupation = {
        int(k): float(np.count_nonzero(smoothed_states == k)) / n_obs for k in range(n_components)
    }
    ...
```
**Ring-boundary note (CRITICAL):** `services/regime_writer.py` is Ring 2 (`services/`). `src/intelligence/stratification/gates.py` (Ring 1) must NOT `from services.regime_writer import _smooth_states` or `_check_occupation_gate` — read these for the algorithm/guard-ordering shape only. Write `effective_n_from_transitions(labels: np.ndarray) -> int` as a new, decoupled function that accepts a plain already-smoothed label array (guard-order pattern: empty check → short-sequence check → transition count), e.g.:
```python
def effective_n_from_transitions(labels: np.ndarray) -> int:
    """Effective sample size proxy: count of independent state-visits (runs) in an
    already-smoothed regime-label sequence, not raw bar count."""
    if len(labels) == 0:
        return 0
    transitions = int(np.count_nonzero(np.diff(labels) != 0))
    return transitions + 1
```

**Analog 4 — walk-forward pure-boundary-function docstring style** (`ic_math.py` lines 572-612, `build_walk_forward_folds`) — mirror this docstring style (states the pure-function contract, cites every prior duplicated call site this extraction replaces, documents the omission/skip convention) for any new gate function's docstring.

---

### `src/intelligence/stratification/fdr.py` (thin BH-FDR wrapper scoped to `regime_group`)

**Analog:** same as `gates.py` Analog 1 above — `src/intelligence/statistics/ic_math.py::apply_bh_fdr` (lines 545-564). This module should be a thin call-site wrapper only (collect the cumulative per-`regime_group` candidate-test p-value list → one `apply_bh_fdr` call → scatter `reject`/`p_corrected` back), following the module's own docstring guidance that the scatter-back step stays local to each caller, not shared.

---

### `src/intelligence/stratification/acausal_placebo_gate.py` (D-05 registration gate)

**Analog:** `scripts/ops/alpha/ops_canary_integrity_assert.py` (full file read, 412 lines) — live, production, tested gate.

**Exception + pure-`evaluate()`-function structure** (lines 97-107, 149-165, 240-243):
```python
class CanaryIntegrityViolation(RuntimeError):
    """Raised on a hard-halt condition -- a proven broken measurement pipeline."""


def _clears_gate(row: dict[str, Any]) -> bool:
    """The exact eligibility predicate _ELIGIBILITY_BASE_WHERE (ensemble_trainer.py)
    reads: ic_ci_lower > 0 AND passes_fdr. ..."""
    ci_lower = row["ic_ci_lower"]
    return bool(ci_lower is not None and ci_lower > 0 and row["passes_fdr"])


def evaluate(
    rows: list[dict[str, Any]],
    fdr_alpha: float = _FDR_ALPHA_DEFAULT,
    tail_alpha: float = _BINOMIAL_TAIL_ALPHA_DEFAULT,
    pooled_tail_alpha: float = _POOLED_TAIL_ALPHA_DEFAULT,
) -> dict[str, Any]:
    """Pure evaluation function -- no IO, fully unit-testable without a DB.

    Returns a report dict on success; raises CanaryIntegrityViolation with a
    message naming every offending canary + stratum on any hard-halt condition.
    """
    if not rows:
        raise CanaryIntegrityViolation(
            "no canary rows found for the latest feature_ic_scores vintage -- the "
            "corpus run had no canary coverage; this gate cannot validate anything"
        )
    ...
    if failures:
        raise CanaryIntegrityViolation("; ".join(failures))
    return report
```

**The deliberate look-ahead construction to generalize per-provider** (`src/intelligence/feature_factory.py` lines 1899-1911):
```python
def _canary_acausal_placebo(closes: np.ndarray, i: int, eps: float = 1e-10) -> float:
    """Deliberate look-ahead leak (positive control): pairs bar i with the
    return realized from bars i+1 -> i+2 (i.e. 2 bars in the future relative
    to i) -- the exact ret_lag_1 shape, forward-shifted instead of
    backward-shifted. Must clear the IC significance gate spectacularly:
    proves this pipeline can detect contamination when it is genuinely
    present. Falls back to 0.0 when the future bars don't exist yet ...
    """
    if i + 2 >= len(closes) or closes[i + 1] <= eps:
        return 0.0
    return float(math.log(closes[i + 2] / closes[i + 1]))
```
**Generalization direction (per D-05's rationale in RESEARCH.md Pattern 5):** the new gate takes a `StratificationDimension` provider, runs its `compute()` against a deliberately shuffled/future-shifted version of its own raw input, and asserts the resulting labels carry **no** informative signal — the INVERSE assertion from `_canary_acausal_placebo` (which must be detected as leaking) — because here the provider's `causality_basis` claim is being falsified, not confirmed-detectable. Keep the same hard-raise, no-IO, `evaluate(provider, ...) -> report` structure; raise a new `AcausalPlaceboRegistrationViolation(RuntimeError)` (mirrors `CanaryIntegrityViolation`) on failure.

**CLI/script wrapper structure to mirror if a standalone script is chosen** (lines 51-68, 325-348, 359-412 — `argparse` setup, `asyncpg.create_pool`, `try/except (ViolationType) as violation: print(..., file=sys.stderr); return 1`).

---

### `src/intelligence/stratification/volatility_pct.py` (D-06 pilot dimension)

**Analog:** `src/intelligence/regime_signals/breadth_vol.py` (full file, 146 lines) + `src/intelligence/regime_signals/causal_rank.py` (full file, 50 lines).

**Module docstring style to mirror** (`breadth_vol.py` lines 1-46) — states signal construction, cites the correctness invariant (causal rank only, never whole-series `pandas.rank`), cites the calibration history/todo that motivated the current cut points, and states the TF-scaling convention (`compute()` receives already-scaled window ints; stays TF-agnostic itself).

**`causal_expanding_rank` — reuse directly, do not reimplement** (`causal_rank.py` lines 1-51, full file):
```python
"""Causal expanding percentile rank -- shared by every regime signal module. ..."""
from __future__ import annotations

import bisect
import math

import pandas as pd


def causal_expanding_rank(series: pd.Series) -> pd.Series:
    """Causal bisect-based expanding percentile rank -- generic over any input series.

    Each position's rank is computed against all PRIOR valid values only -- never future
    ones. NaN guard: skip NaN values (do not insert into window -- preserves bisect sort
    invariant). Tie handling: average rank = (bisect_left + bisect_right) / 2 / n.
    """
    sorted_window: list[float] = []
    causal_ranks: list[float] = []
    for val in series:
        if math.isnan(val):
            causal_ranks.append(float("nan"))
            continue
        if not sorted_window:
            bisect.insort(sorted_window, val)
            causal_ranks.append(1.0)
            continue
        left = bisect.bisect_left(sorted_window, val)
        right = bisect.bisect_right(sorted_window, val)
        rank = (left + right) / 2 / len(sorted_window)
        bisect.insort(sorted_window, val)
        causal_ranks.append(rank)
    return pd.Series(causal_ranks, index=series.index, dtype=float)
```
Import as `from src.intelligence.regime_signals.causal_rank import causal_expanding_rank` — zero reason to write a new percentile-rank implementation (documented history of two independent look-ahead bugs from guessed absolute thresholds instead of this rank transform, todo 092).

**`compute()`/`build_tiers()` shape to adapt from cross-sectional (SPY-only) to per-symbol grain** (`breadth_vol.py` lines 62-127):
```python
def compute(
    ref_bars: dict[str, pd.DataFrame],
    params: dict[str, Any],
) -> tuple[pd.Series, pd.Series] | None:
    if "SPY" not in ref_bars:
        return None
    realized_vol_window = int(params.get("realized_vol_window", 20))
    vix_z_window = int(params.get("vix_z_window", 252))
    ...
    spy_df = ref_bars["SPY"].set_index("timestamp").sort_index()
    spy_close = spy_df["close"].astype(float)
    if len(spy_close) < realized_vol_window + vix_z_window:
        return None
    vix_pct = _compute_vix_pct_rank(spy_close, realized_vol_window, vix_z_window)
    ...
    return vix_pct, breadth_pct


def build_tiers(params: dict[str, Any]) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    vix_low = float(params.get("vix_low_pct", 0.33))
    vix_high = float(params.get("vix_high_pct", 0.67))
    return ([("low", vix_low), ("mid", vix_high), ("high", float("inf"))], ...)


def _compute_vix_pct_rank(
    spy_close: pd.Series, realized_vol_window: int, vix_z_window: int
) -> pd.Series:
    """SPY realized-vol z-score causal expanding percentile rank."""
    log_ret = np.log(spy_close / spy_close.shift(1))
    realized_vol = log_ret.rolling(window=realized_vol_window, min_periods=realized_vol_window).std()
    rv_mean = realized_vol.rolling(window=vix_z_window, min_periods=vix_z_window).mean()
    rv_std = realized_vol.rolling(window=vix_z_window, min_periods=vix_z_window).std()
    vix_z = (realized_vol - rv_mean) / rv_std.where(rv_std > 1e-10)
    return _causal_expanding_rank(vix_z)
```
`volatility_pct`'s pilot adapts this exact "log-return realized vol → rolling z-score → causal rank" shape from a single-symbol cross-sectional input (SPY) to a per-symbol grain (`grain: "per_symbol"`, not `"cross_sectional"`) — RESEARCH.md's Assumption A1 recommends reusing an already-computed causal volatility feature (`atr_z`, `garman_klass_vol_z`, or `yang_zhang_vol_z` — all live `feature_vectors` columns, confirmed at `src/intelligence/schemas.py` lines 1318, 1642-1643) as the raw input to `causal_expanding_rank()` directly, rather than recomputing realized vol from scratch.

**Smoothing-parity note (Pitfall 5):** if `volatility_pct` applies its own `min_hold_bars`-equivalent smoothing for parity with the HMM's substitution-test comparison, it must document (in the module docstring, same style as `breadth_vol.py`'s CALIBRATION note) whether labels are pre- or post-smoothing before being handed to `effective_n_from_transitions()`.

---

### `tests/unit/test_stratification_contract.py` (Protocol conformance + `ic_engine.py` compat)

**Analog:** `tests/unit/test_ic_engine_routing.py` (full file, 118 lines) — pure-function import pattern, project-root `sys.path` insert, class-per-behavior test organization:
```python
"""Unit tests: ic_engine symbol -> regime group routing (Phase 144 Plan 05).

_build_symbol_regime_class is a pure function -- tested directly, mirroring the
import pattern established by test_ic_engine_staleness.py (project-root sys.path
insert, no fixtures/mocks needed for a pure dict-in/dict-out helper).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.ic_engine import AmbiguousRegimeGroupError, _build_symbol_regime_class

_EQUITY_GROUP = {"name": "equity", "tag_filter": ["eq_*", "intl_*"], "enabled": True}
_RATES_GROUP = {"name": "rates", "tag_filter": ["fi_*"], "enabled": True}
_GROUPS = [_EQUITY_GROUP, _RATES_GROUP]


class TestBuildSymbolRegimeClass:
    def test_fi_symbol_routes_to_rates(self):
        tags = {"TLT": {"fi_treasury"}, ...}
        result = _build_symbol_regime_class(tags, _GROUPS)
        assert result["TLT"] == "rates"
    ...
    def test_overlapping_tag_filters_raise_ambiguous_error(self):
        ...
        with pytest.raises(AmbiguousRegimeGroupError):
            _build_symbol_regime_class(tags, [_RATES_GROUP, overlapping_group])
```
**Note (RESEARCH.md Pitfall 4 precedent-carve-out):** this test file is the one place in the codebase where importing `from services.ic_engine import ...` directly into a test is already-established practice (testing `ic_engine.py`'s own code, not a Ring-1-importing-Ring-2 production dependency). `test_stratification_contract.py`'s `ic_engine.py`-compatibility test should follow this same pattern — import `_build_symbol_regime_class`/`_build_regime_passes` from `services.ic_engine` for the *test* only, and assert the `StratificationDimension` contract's output shape is consumable by them, without the production `src/intelligence/stratification/` module itself ever importing `services.ic_engine`.

---

### `tests/unit/test_stratification_gates.py` (gate 0/1/2, effective-N, FDR wiring)

**Analog:** `tests/unit/test_regime_writer_occupation_gate.py` (full file, 135 lines) — pure-numpy guard-order test organization (empty → short → non-converged → degenerate, each its own test, plus one "skip marker shape is uniform" cross-cutting test):
```python
"""Unit test: regime writer degenerate-model occupation-fraction gate (P2b).
...
No DB, no GaussianHMM. Pure numpy.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from services.regime_writer import _check_occupation_gate

_MIN_OCCUPATION = 0.05


def test_degenerate_model_is_flagged_for_skip():
    smoothed_states = np.array([0] * 960 + [1] * 10 + [2] * 10 + [3] * 10 + [4] * 10)
    is_degenerate, info = _check_occupation_gate(
        smoothed_states, n_components=5, min_state_occupation=_MIN_OCCUPATION, converged=True
    )
    assert is_degenerate is True
    assert info["reason"] == "degenerate_occupation"
    assert info["min_fraction"] < _MIN_OCCUPATION


def test_empty_series_flagged_no_divide_by_zero():
    is_degenerate, info = _check_occupation_gate(
        np.array([]), n_components=5, min_state_occupation=_MIN_OCCUPATION, converged=True
    )
    assert is_degenerate is True
    assert info["reason"] == "empty_series"


def test_skip_marker_shape_is_uniform_across_all_skip_reasons():
    """All skip paths ... return the same (bool, dict) shape with a 'reason' key --
    the caller handles all uniformly."""
    ...
```
Apply the identical guard-order test structure to `effective_n_from_transitions()` (empty array → single-element array → normal transition-count case) and add a `-k fdr` test class calling `apply_bh_fdr` through the new `fdr.py` wrapper with a hand-constructed cumulative p-value list, asserting the correction is applied once per `regime_group`'s pooled history, not per-candidate in isolation (per RESEARCH.md's Phase Requirements → Test Map row for D-03).

---

### `tests/unit/test_acausal_placebo_registration.py` (D-05 registration gate)

**Analog:** `tests/unit/test_canary_predictors.py` (715 lines — read header + fixture section) — imports the pure functions directly from the production module under test, no DB/mocks:
```python
"""Unit tests for canary/control predictors (Phase 143.1 Plan 02, todo 068).

RED-first coverage for Component D: 5 new genuine FeatureVector fields
(canary_noise_gaussian, canary_noise_uniform, canary_constant,
canary_near_constant, canary_acausal_placebo) plus the corpus-run integrity
assertion (Task 3, scripts/ops/alpha/ops_canary_integrity_assert.py).

Negative controls (noise/constant/near-constant) must never carry IC. The
acausal placebo is a deliberate look-ahead leak (positive control) and must
clear an IC significance gate spectacularly, proving the pipeline can detect
contamination when it is genuinely present.
"""
from __future__ import annotations

import dataclasses
import math
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from src.intelligence.feature_cache import FeatureCache
from src.intelligence.feature_factory import (
    _CANARY_CONSTANT_VALUE,
    FeatureFactory,
    FeatureFactoryConfig,
    _canary_acausal_placebo,
    ...
)
```
Mirror this "RED-first, negative-control-must-never-clear / positive-control-must-always-clear" test framing for the new gate: construct a fake/minimal `StratificationDimension` provider whose `compute()` is causally correct → must pass registration; a second provider whose `compute()` is given a deliberately future-shifted input → must raise the new `AcausalPlaceboRegistrationViolation` (mirrors `CanaryIntegrityViolation`'s `pytest.raises` usage pattern seen throughout `test_ic_engine_routing.py`).

---

### `tests/unit/test_volatility_pct_pilot.py` (D-06 pilot provider)

**Analog:** `tests/unit/test_regime_signals_breadth_vol.py` (304 lines, read header + first test class) + `tests/unit/test_regime_signals_causal_rank.py` (full file, 48 lines).

**Fixture-construction and import-path pattern** (`test_regime_signals_breadth_vol.py` lines 1-43):
```python
"""Unit tests for breadth_vol signal module. CI-clean: no DB, no network. ..."""
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[2]))

from src.intelligence.regime_signals.breadth_vol import (
    PROB_KEYS,
    _compute_breadth,
    _compute_vix_pct_rank,
    build_tiers,
    compute,
)

_UTC = pd.Timestamp("2020-01-01", tz="UTC")


def _make_bars(symbol: str, closes: list[float]) -> pd.DataFrame:
    ts = pd.date_range(_UTC, periods=len(closes), freq="1D")
    return pd.DataFrame({"timestamp": ts, "close": closes})


class TestComputeReturnShape:
    def test_returns_two_series(self):
        ...
        result = compute(ref_bars, params)
        assert result is not None
        s1, s2 = result
        assert isinstance(s1, pd.Series)
        assert isinstance(s2, pd.Series)
```

**Causal-property regression test — mandatory, mirror exactly** (`test_regime_signals_causal_rank.py` lines 1-48, full file):
```python
class TestCausalExpandingRank:
    def test_first_value_ranks_one(self):
        result = causal_expanding_rank(pd.Series([5.0, 1.0, 9.0]))
        assert result.iloc[0] == 1.0

    def test_causal_property_future_value_does_not_change_past_ranks(self):
        rng = np.random.default_rng(11)
        series_n = pd.Series(rng.normal(size=60))
        ranks_n = causal_expanding_rank(series_n)
        series_n1 = pd.concat([series_n, pd.Series([1000.0])], ignore_index=True)
        ranks_n1 = causal_expanding_rank(series_n1)
        assert np.allclose(ranks_n.to_numpy(), ranks_n1.iloc[:60].to_numpy())

    def test_nan_passthrough_does_not_pollute_sorted_window(self):
        ...

    def test_output_bounded_zero_to_one(self):
        ...
```
`test_volatility_pct_pilot.py` needs both: (a) the fixture/shape tests mirroring `test_regime_signals_breadth_vol.py`'s `TestComputeReturnShape` class (adapted to per-symbol grain, not cross-sectional), and (b) a "causal property" regression test in the same style as `test_regime_signals_causal_rank.py`'s `test_causal_property_future_value_does_not_change_past_ranks` — RESEARCH.md's Phase Requirements → Test Map row for D-06 explicitly calls for the pilot's `compute()`/`score()` to be exercised against real 3-5 symbol `market_data_ohlcv_tradeable` data (planner's call whether this lands in `tests/unit/` with fixture data or `tests/integration/` with a live DB connection — see RESEARCH.md's Wave 0 test map).

---

## Shared Patterns

### Ring-boundary discipline (applies to every new `src/intelligence/stratification/` file)
**Source:** CLAUDE.md Ring rule + RESEARCH.md Pitfall 4.
**Apply to:** `gates.py`, `acausal_placebo_gate.py`, `contract.py`, `volatility_pct.py`.
Never `from services.regime_writer import ...` or `from services.ic_engine import ...` in production code under `src/intelligence/`. Treat `_smooth_states`, `_check_occupation_gate`, `_resolve_regime_scope`, `_build_symbol_regime_class`, `_build_regime_passes` as pattern references (read, mirror the algorithm/guard order), never import targets. The one sanctioned exception is *test* code following `test_ic_engine_routing.py`'s existing precedent of importing `services.ic_engine` internals for the purpose of testing `ic_engine.py` itself/asserting compatibility — that precedent does not extend to production imports.

### Pure-function, no-IO gate structure
**Source:** `scripts/ops/alpha/ops_canary_integrity_assert.py::evaluate()` (lines 149-165) and `src/intelligence/statistics/ic_math.py::apply_bh_fdr`/`build_walk_forward_folds`.
**Apply to:** every function in `gates.py`, `fdr.py`, `acausal_placebo_gate.py`.
Every gate function takes plain data structures (arrays, lists of dicts, `np.ndarray` label sequences) as input — no DB connection, no Kafka client, no `Settings()` — so every gate is `pytest`-testable with zero fixtures/mocks. DB reads (the `volatility_pct` pilot's real OHLCV data) happen at the call site, not inside the gate functions themselves.

### Hard-raise on gate failure, never warn-and-swallow
**Source:** `CanaryIntegrityViolation` (`ops_canary_integrity_assert.py` lines 97-98, 240-243) and `ArchitectureViolation`/`ValueError` (`src/intelligence/plugins/base.py` lines 10-16, 106-120) and `AmbiguousRegimeGroupError` (`services/ic_engine.py` lines 260-268).
**Apply to:** `acausal_placebo_gate.py` (new `AcausalPlaceboRegistrationViolation(RuntimeError)`), any hard-fail path in `gates.py`.
Every one of these existing exception classes is a plain, undecorated subclass of a stdlib exception type (`RuntimeError`, `ValueError`, `Exception`) with a docstring explaining *why* it exists and *when* it fires — no custom `__init__`, no error-code taxonomy. Match this minimalism. Raise with a message naming every offending case (not just "a violation occurred") — see `evaluate()`'s `offenders = ", ".join(...)` pattern (lines 140, 200-208).

### Docstring convention: cite the todo/incident motivating the pattern
**Source:** `causal_rank.py` (lines 1-9), `breadth_vol.py`'s CALIBRATION note (lines 25-40), `ic_math.py::apply_bh_fdr`'s docstring (lines 548-556).
**Apply to:** every new module and non-trivial function in this phase.
Every analog module's docstring names the specific todo number and the specific prior bug/incident that motivated its current shape (e.g. "todo 092 breadth_frac fix", "independently hand-rolled at three call sites... before this extraction"). New code should cite D-01 through D-07 by number in the same way — matches this project's own established documentation convention (per CLAUDE.md's "Documentation Standards" — canonical docs stand alone with rationale) and directly supports RESEARCH.md Pitfall 3's requirement to comment the D-07 APR-deferral exception in the code itself, not just in a design doc.

### `alpha.regime_stratification.fdr_alpha`/`.max_correlation` as documented-exception module constants (not yet APR-backed)
**Source:** RESEARCH.md Pitfall 3, no direct code analog exists yet (this is new-pattern-to-establish, not reuse) — closest structural precedent is `ops_canary_integrity_assert.py`'s own module-level defaults (lines 67-72):
```python
_FDR_ALPHA_DEFAULT = 0.05
_BINOMIAL_TAIL_ALPHA_DEFAULT = 0.01
# POOLED is the eligibility-relevant family ... -- see 2026-08-02 E7 addendum.
_POOLED_TAIL_ALPHA_DEFAULT = 0.001
```
**Apply to:** wherever `fdr.py`/`gates.py` needs these two values.
Follow this exact shape (module-level `_SCREAMING_SNAKE_CASE` constant with a comment citing its provenance) for `alpha.regime_stratification.fdr_alpha`/`.max_correlation`, but the comment must additionally cite D-07 and Phase 170 explicitly as the reason it is a temporary, ratified exception to CLAUDE.md's migrate-as-you-go APR mandate — not merely "this is the default," per RESEARCH.md Pitfall 3's explicit instruction.

## No Analog Found

None — every file in scope has at least a role-match analog (the Protocol/ABC file's closest analog, `src/intelligence/plugins/base.py`, is an archived subsystem used for shape reference only, not import; this is noted, not a gap).

## Metadata

**Analog search scope:** `src/intelligence/` (plugins/, regime_signals/, statistics/, feature_factory.py, concept_registry_service.py), `services/` (ic_engine.py, regime_writer.py — read-only reference), `scripts/ops/alpha/ops_canary_integrity_assert.py`, `tests/unit/` (test_ic_engine_routing.py, test_regime_writer_occupation_gate.py, test_canary_predictors.py, test_regime_signals_breadth_vol.py, test_regime_signals_causal_rank.py)
**Files scanned:** 14 source/test files read in full or targeted non-overlapping ranges; ~10 additional files grep'd for line-number location only
**Pattern extraction date:** 2026-08-06
