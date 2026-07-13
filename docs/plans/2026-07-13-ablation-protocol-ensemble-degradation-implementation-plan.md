# Ablation Protocol for Ensemble Degradation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `scripts/ops/alpha/ops_ensemble_ablation.py` (todo 084), a pre-committed leave-one-family-out ablation report: for every `feature_registry.group_name` family, zero that family's ensemble weights, recompute the composite alpha score on the OOS window, re-measure IC per stratum, and emit a marginal-attribution markdown table plus a `CorpusManifest` run record, so "what died" after an ensemble degradation is answered mechanically before any human hypothesis enters the room.

**Architecture:** A single diagnostic ops script (EIC-05 sibling: asyncpg pool from `Settings().database_url`, markdown to stdout, exit code always 0) whose statistical kernels are pure module-level functions unit-tested without any DB. Both the baseline arm and every ablated arm are computed by the IDENTICAL code path (`X @ signed_weights` replicated from `services/ensemble_trainer.py`, then pooled cross-symbol means, then `ic_math` measurement); the stored `ensemble_alpha.alpha_score` is used only as a replication cross-check on the baseline, never as the baseline itself, so a baseline/ablated methodology mismatch is structurally impossible. Results land in two places: the human-readable markdown report, and a `CorpusManifest("ensemble_ablation")` JSON scoped by `weight_version` (that is what the todo's "results go in the run manifest" means concretely; see `services/ensemble_trainer.py` lines 486-533 for the pattern).

**Tech Stack:** Python 3, asyncpg, numpy, `src/intelligence/statistics/ic_math.py` (Spearman IC, Fisher-z CI, two-sample IC difference test, BH-FDR), `src/observability/corpus_manifest.py`, pytest.

## Global Constraints

Binding project-wide rules; every task's requirements implicitly include these.

- **Executable returns only (CLAUDE.md Invariant 1):** every query touching `forward_returns` filters `fr.return_type = 'executable_open_to_open'`. No exceptions, including joins whose return columns are "only" cross-checked.
- **OOS boundary:** the ablation reads `fv.bar_ts >= oos_start` where `oos_start` comes from `config_state` key `alpha.validation.oos_start` (live value `2025-12-24T05:15:00Z`). The `>=` operator is the project's OOS convention (`scripts/ops/corpus/ops_oos_holdout_eval.py::_oos_mask`, line 87: `ts >= oos_start`); it partitions cleanly against the training side's `bar_ts < oos_start` (`services/ensemble_ic_engine.py::_WORKER_FETCH_SQL`) with no gap and no overlap. Missing/NULL `oos_start` is a loud abort, never a silent full-corpus run.
- **Completeness gating:** a forward return is usable only when `complete_<scale> AND isfinite(return_<scale>)`, matching `services/ic_engine.py` lines 1848-1850. Applied BEFORE cross-symbol pooling (a censored per-symbol return must never leak into a pooled mean). This is stricter than `ensemble_ic_engine.py` (which relies on NULL returns alone); the stricter convention wins for new measurement code.
- **IC math reuse:** all correlation/CI/significance math comes from `src/intelligence/statistics/ic_math.py`: `compute_ic_vectorized` (Spearman via Pearson-on-ranks), `_fisher_z_ci` (95% CI), `fisher_z_difference_p` (two-sample IC delta test, conservative under positive dependence, exactly this script's two-arms-on-the-same-bars shape), `apply_bh_fdr`, `_nan_to_none`. Never `scipy.stats.spearmanr`, never hand-rolled correlation, never an IC without a CI.
- **Identical-code-path invariant:** baseline and ablated composite scores differ ONLY in which weight entries are zeroed. Same `X` matrix (float32, `NULL -> 0.0`, per `ensemble_trainer.py` lines 823-826), same matmul, same pooling, same subsampling stride, same gates.
- **Subsampling:** `stride = max(alpha.ic.subsample_min_stride, lookahead_bars)` per scale, applied to the pooled per-bar series, matching `ensemble_ic_engine.py` lines 770-773.
- **APR:** no new APR keys. Consume existing keys via `services/_batch_utils.load_apr_dict_async` + `cfg` with fallbacks identical to the engines': `alpha.ic.subsample_min_stride` (5), `alpha.ic.min_reliable_n` (100), `alpha.ic.fdr_alpha` (0.05), `alpha.ic.lookahead.fast/mid/slow/extended` (1/5/20/60), `alpha.ensemble.weight_version` ('v1'). The reconstruction tolerance is a CLI flag with a documented default (scripts/ are outside the APR src/services mandate; EIC-05's `_DEFAULT_MIN_OBS_PER_REGIME` is the precedent).
- **Exit code always 0** (diagnostic, not a gate; `ops_ensemble_ic_diagnosis.py` convention). Aborts print a loud `FAILED` header and record a manifest error, then return 0.
- **Exception variable name is `error`** (`except X as error:`), never `exc`.
- **Timestamps:** `datetime.now(UTC)` only; serialize via str() into the manifest (CorpusManifest uses `default=str`).
- **No `prometheus_client`**, no OTel needed (ops script, not a daemon; EIC-05 has neither).
- **Naming:** concept `ensemble_ablation`; file `scripts/ops/alpha/ops_ensemble_ablation.py`; manifest step_name `ensemble_ablation` with `scope_suffix = weight_version`.
- **Tests never touch DB/Kafka** (`tests/unit/` CI-clean rule). Pure functions only; `CorpusManifest` is exercised against `tmp_path` (real file I/O to a temp dir, no mocking needed).
- **Commit messages:** no AI attribution lines of any kind, no em dashes (user global CLAUDE.md overrides any tool default footer).
- **Family count correction:** `feature_registry.group_name` has exactly 11 distinct live values (`calendar, control, cross_tf, macro, momentum, oscillator, regime, session, structure, volatility, volume`), not the "~10" the todo estimates. The script derives the family list from the DB at runtime (`SELECT DISTINCT group_name`), never hardcodes it.
- **`control` family stays IN the sweep** (explicit decision): canaries are excluded from ensemble eligibility by `feature_status_at_eval = 'active'`, so `control` should appear in zero `ensemble_weights` rows. Both possible outcomes are informative: absent everywhere confirms the eligibility filter and gives a free mechanism no-op check; present anywhere is a loud governance-breach flag in the report AND a manifest warning (a canary carrying ensemble weight means the eligibility filter is broken, or the ablation code is wrong if zeroing it moves IC materially).

---

## Design summary (read before Task 1)

**Data flow per stratum `(tf, regime)`** (strata enumerated from `ensemble_weights` for the target `weight_version`, `symbol = 'UNIVERSE'`; 17 `(tf, regime)` pairs live today across 5m/15m/1d):

1. Load that stratum's weight rows joined to `feature_registry.group_name`. Build `signed_weights = weight * sign(ic_sharpe)`. `ensemble_weights` has no `ic_sign` column; the stored `ic_sharpe` is the exact ic_input-resolved, sign-carrying per-feature value the trainer held at scoring time (`ensemble_trainer.py` line 924), so its sign is the drift-free sign source (re-reading `feature_ic_scores` would race against post-hoc ic_engine re-runs). Under the live champion (`sign_symmetric=False`) every eligible feature has `ic_ci_lower > 0`, so all signs are +1 and this reduces to the trainer's exact `signed_weights`. The reconstruction check (step 4) verifies this empirically rather than assuming it.
2. Fetch the OOS panel: `feature_vectors JOIN market_regimes` (the trainer's exact stratum join) `JOIN forward_returns` (executable filter, return + complete columns) `LEFT JOIN ensemble_alpha` (stored baseline score for the replication check), `WHERE fv.tf = $1 AND mr.regime_label = $2 AND fv.bar_ts >= oos_start`, ordered `bar_ts, symbol`. Column subset = this stratum's weighted feature names only (the OOS window is ~6.5 months, so a single fetch per stratum fits comfortably; no chunking needed, unlike ic_engine's multi-year full-width pass).
3. Build `X` exactly as the trainer does: `float(r[c]) if r[c] is not None else 0.0`, `dtype=np.float32`.
4. `baseline_scores = X @ signed_weights` (float32 @ float64 auto-promotes to float64, same as the trainer's scoring matmul). Compare against stored `ensemble_alpha.alpha_score` where present: `max |diff| / std(stored)` must be `<= --reconstruction-tol` (default 0.01; the trainer's own float32 validation measured worst-case ~0.2% relative divergence, see its lines 810-822 comment). A mismatch means weights/regime labels drifted since the trainer ran (or an ablation bug); the report flags REPLICATION MISMATCH loudly and the stratum's attribution is labeled untrustworthy.
5. Pool cross-symbol per bar: group by `bar_ts` (regime and tf are constant within the stratum), mean across symbols. This is the `alpha_ensemble_ic` POOLED convention (`ensemble_ic_engine.py::_aggregate_pooled_series`, Pitfall 5: group before averaging), chosen so the baseline arm's IC is directly comparable to the pooled `alpha_ensemble_ic` rows where the degradation was originally observed. Our vectorized `pool_means_by_bar` is equivalence-TESTED against `_aggregate_pooled_series` (Task 2), so the two implementations cannot silently diverge. Returns are complete-gated per symbol-row BEFORE pooling.
6. Per family: zero that family's entries in `signed_weights`, recompute scores through the identical path, pool.
7. Per scale (`fast/mid/slow/extended`): stride-subsample the pooled series, gate `n >= min_reliable_n`, IC + Fisher-z CI per arm, `delta_ic = ic_baseline - ic_ablated` (positive delta = removing the family hurt = the family was contributing), `fisher_z_difference_p(ic_baseline, n, ic_ablated, n)`. A near-constant ablated series (family was effectively the whole model) is reported as DEGENERATE with `ic_ablated = None`, never as a fake IC of 0.0.
8. One corpus-wide `apply_bh_fdr` call across all delta p-values (project convention: one multipletests call per family of tests, informational here, not a gate).
9. Render markdown (replication section, per-stratum attribution tables, per-family cross-strata summary, control-family section) and write the manifest.

**Why Fisher-z CI and not the block bootstrap:** the 143.1 scope boundary (143.1-CONTEXT resolved item 3) deliberately keeps `ensemble_ic_engine.py` and `ops_oos_holdout_eval.py` on `_fisher_z_ci` this phase; this script measures the same composite-score object as `ensemble_ic_engine` and must stay CI-comparable with the `alpha_ensemble_ic` rows the operator will read next to it. The primary statistic here is the between-arm delta (via `fisher_z_difference_p`, conservative under the positive dependence of two arms measured on identical bars), not the per-arm CI. Upgrade to the bootstrap CI together with `ensemble_ic_engine`, not before.

**File structure:**

| File | Responsibility |
|---|---|
| `scripts/ops/alpha/ops_ensemble_ablation.py` | Everything: pure kernels (weight zeroing, pooling, arm IC, reconstruction check, attribution assembly, rendering, manifest recording) at module level for direct test import, plus async `main()` doing all DB I/O. Single file matches every EIC-05-family precedent (`ops_ensemble_weight_compare.py` etc.). |
| `tests/unit/test_ensemble_ablation.py` | All unit tests. Imports pure helpers via the `sys.path` + `from ops_ensemble_ablation import ...` pattern of `tests/unit/test_ensemble_weight_compare.py`. No DB, no Kafka. |

---

### Task 1: Script skeleton and weight-vector kernels

**Files:**
- Create: `scripts/ops/alpha/ops_ensemble_ablation.py`
- Create: `tests/unit/test_ensemble_ablation.py`

**Interfaces:**
- Consumes: `services/ensemble_ic_engine.py`'s `_SCALES` tuple and `_SCALE_RETURN_COLUMNS` dict (existing), `ic_math` functions (existing).
- Produces (later tasks rely on these exact names):
  - `signed_weights_from_rows(weights: np.ndarray, ic_sharpes: np.ndarray) -> np.ndarray` (float64)
  - `zero_family(signed_weights: np.ndarray, group_names: list[str], family: str) -> np.ndarray`
  - `weight_mass_fraction(signed_weights: np.ndarray, group_names: list[str], family: str) -> float`
  - Module constants `_BASELINE_ARM = "__baseline__"`, `_CONTROL_FAMILY = "control"`, `_DEGENERATE_STD = 1e-12`, `_DEFAULT_RECONSTRUCTION_TOL = 0.01`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_ensemble_ablation.py`:

```python
"""Unit tests: todo 084 leave-one-family-out ensemble ablation protocol.

All statistical kernels in scripts/ops/alpha/ops_ensemble_ablation.py are pure
module-level functions tested here without any DB or Kafka (project unit-test rule).
The load-bearing properties under test are statistical-correctness properties:
identical code path for baseline and ablated arms, sign convention, complete-gating,
pooling equivalence with ensemble_ic_engine._aggregate_pooled_series, degenerate-arm
handling, and the SQL invariants (executable returns filter, OOS >= boundary).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

_scripts_alpha_dir = _project_root / "scripts" / "ops" / "alpha"
if str(_scripts_alpha_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_alpha_dir))

from ops_ensemble_ablation import (
    _BASELINE_ARM,
    _CONTROL_FAMILY,
    signed_weights_from_rows,
    weight_mass_fraction,
    zero_family,
)

# ---------------------------------------------------------------------------
# Task 1: weight-vector kernels
# ---------------------------------------------------------------------------


def test_signed_weights_sign_convention():
    """sign comes from stored ensemble_weights.ic_sharpe: negative ic_sharpe flips
    the weight (sign-symmetric challenger case); non-negative keeps it positive
    (champion case, where all eligible features have ic_ci_lower > 0)."""
    weights = np.array([0.2, 0.3, 0.5])
    ic_sharpes = np.array([0.8, -0.4, 0.0])
    signed = signed_weights_from_rows(weights, ic_sharpes)
    assert signed.dtype == np.float64
    np.testing.assert_allclose(signed, [0.2, -0.3, 0.5])


def test_zero_family_zeroes_only_that_family_and_copies():
    signed = np.array([0.2, -0.3, 0.5])
    groups = ["momentum", "volume", "momentum"]
    ablated = zero_family(signed, groups, "momentum")
    np.testing.assert_allclose(ablated, [0.0, -0.3, 0.0])
    # input untouched (must be a copy, or arms contaminate each other)
    np.testing.assert_allclose(signed, [0.2, -0.3, 0.5])


def test_zero_family_absent_family_is_identity():
    signed = np.array([0.2, -0.3])
    ablated = zero_family(signed, ["momentum", "volume"], _CONTROL_FAMILY)
    np.testing.assert_allclose(ablated, signed)


def test_weight_mass_fraction_uses_absolute_mass():
    """|-0.3| counts as mass 0.3: a contrarian feature's contribution share must not
    be understated (or netted against longs) by signed summation."""
    signed = np.array([0.2, -0.3, 0.5])
    groups = ["momentum", "volume", "momentum"]
    assert weight_mass_fraction(signed, groups, "volume") == 0.3 / 1.0
    assert weight_mass_fraction(signed, groups, "momentum") == 0.7 / 1.0
    assert weight_mass_fraction(signed, groups, _CONTROL_FAMILY) == 0.0


def test_weight_mass_fraction_zero_total_returns_zero():
    assert weight_mass_fraction(np.zeros(3), ["a", "b", "c"], "a") == 0.0


def test_baseline_arm_sentinel_is_not_a_plausible_group_name():
    assert _BASELINE_ARM == "__baseline__"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_ensemble_ablation.py -v`
Expected: FAIL at collection with `ModuleNotFoundError: No module named 'ops_ensemble_ablation'`

- [ ] **Step 3: Write minimal implementation**

Create `scripts/ops/alpha/ops_ensemble_ablation.py`:

```python
#!/usr/bin/env python3
"""
ops_ensemble_ablation.py -- todo 084: pre-committed leave-one-family-out ablation
protocol for ensemble degradation (G-2, fable-2026-07-07-renaissance-layer-refinements
section 11).

When ensemble OOS IC degrades between epochs, this script is the mechanical first
pass that replaces ad-hoc EIC-05-style forensics: for every feature_registry
group_name family (11 live values as of 2026-07-13: calendar, control, cross_tf,
macro, momentum, oscillator, regime, session, structure, volatility, volume), zero
that family's ensemble_weights, recompute the composite alpha score on the OOS
window through the IDENTICAL code path as the baseline, and re-measure IC per
(tf, regime, scale) stratum. Output: a marginal-attribution markdown table on
stdout plus a CorpusManifest("ensemble_ablation") run record scoped by
weight_version. Answers "what died" in one batch run before any human hypothesis
enters the room.

METHODOLOGY INVARIANTS (statistical correctness, non-negotiable):
- Baseline and ablated arms share one code path: X (float32, NULL -> 0.0, the
  ensemble_trainer.py convention) @ signed_weights, then cross-symbol per-bar mean
  pooling (the alpha_ensemble_ic POOLED convention, equivalence-tested against
  ensemble_ic_engine._aggregate_pooled_series), then per-scale stride subsampling,
  then ic_math measurement. The ONLY difference between arms is which weight
  entries are zeroed. The stored ensemble_alpha.alpha_score is used exclusively as
  a replication cross-check on the recomputed baseline (normalized max abs diff
  vs --reconstruction-tol), never as the baseline itself -- so a baseline/ablated
  methodology mismatch is structurally impossible, and a REPLICATION MISMATCH flag
  means the weights/regime labels drifted since ensemble_trainer ran (or this
  script has a bug); either way the stratum's attribution is untrustworthy and
  says so loudly.
- Executable returns only (CLAUDE.md Invariant 1): forward_returns is always read
  WHERE return_type = 'executable_open_to_open'.
- OOS only: fv.bar_ts >= alpha.validation.oos_start. The >= operator matches
  ops_oos_holdout_eval._oos_mask and partitions exactly against the training
  side's bar_ts < oos_start (ensemble_ic_engine) -- no gap, no overlap. A missing
  oos_start aborts loudly; it never silently measures the full corpus.
- Completeness gate: a return participates only when complete_<scale> AND
  isfinite(return_<scale>) (ic_engine.py convention), applied per symbol-row
  BEFORE pooling so censored returns never leak into a pooled mean.
- Sign convention: ensemble_weights has no ic_sign column; sign(ic_sharpe) is used
  (the stored ic_sharpe is the exact sign-carrying ic_input-resolved value the
  trainer held at scoring time, line 924). Verified empirically by the
  reconstruction check rather than assumed.
- IC math is reused from src/intelligence/statistics/ic_math.py (Spearman via
  compute_ic_vectorized, Fisher-z CI, fisher_z_difference_p for the between-arm
  delta -- conservative under the positive dependence of two arms measured on the
  same bars -- and one corpus-wide apply_bh_fdr pass over all delta p-values).
  Fisher-z (not the block bootstrap) is deliberate: this script must stay
  CI-comparable with alpha_ensemble_ic's pooled rows, which stay on Fisher-z this
  phase (143.1-CONTEXT resolved item 3). Upgrade both together.
- 'control' (canary) family stays in the sweep by design: it should be absent from
  ensemble_weights entirely (feature_status_at_eval='active' excludes canaries);
  if present, the report and manifest flag a governance breach, and a material IC
  delta from zeroing it indicts the ablation mechanism itself, not the model.

This report is diagnostic; remediation decisions are human/operator. Exit code is
always 0 (ops_ensemble_ic_diagnosis.py convention).

Usage:
    python scripts/ops/alpha/ops_ensemble_ablation.py
    python scripts/ops/alpha/ops_ensemble_ablation.py --weight-version run_2025122405150000
"""

from __future__ import annotations

import asyncio
import dataclasses
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

import asyncpg
import numpy as np

from services._batch_utils import cfg as _cfg
from services._batch_utils import load_apr_dict_async as _load_apr
from services.ensemble_ic_engine import _SCALE_RETURN_COLUMNS, _SCALES
from src.config.settings import Settings
from src.intelligence.statistics.ic_math import (
    _fisher_z_ci,
    _nan_to_none,
    apply_bh_fdr,
    compute_ic_vectorized,
    fisher_z_difference_p,
)
from src.observability.corpus_manifest import CorpusManifest

# Sentinel arm name for the all-families baseline. Dunder-wrapped so it can never
# collide with a real feature_registry.group_name (snake_case identifiers).
_BASELINE_ARM = "__baseline__"

# The canary family (feature_registry.is_control rows share this group_name).
_CONTROL_FAMILY = "control"

# Std threshold below which an arm's pooled score series is degenerate (near
# constant): Spearman IC is undefined on a constant series, so the arm is reported
# as DEGENERATE rather than as a fake IC of 0.0. [conventional] numerical-zero
# guard, same magnitude as ic_math's internal 1e-10/1e-12 denominators -- a
# statistical concept definition, not a tunable (APR-exempt).
_DEGENERATE_STD = 1e-12

# Default for --reconstruction-tol: max |recomputed - stored| / std(stored) allowed
# before flagging REPLICATION MISMATCH. ensemble_trainer.py's own float32
# validation (its lines 810-822 comment) measured worst-case ~0.2% relative
# divergence at the mv_condition_max gate boundary; 1% gives headroom for the
# float32 X reconstruction while still catching any sign/ordering/NaN-handling bug
# (which produce O(100%) distortions, not O(1%)). CLI-overridable; scripts/ sit
# outside the APR src/services mandate (EIC-05 fallback-constant precedent).
_DEFAULT_RECONSTRUCTION_TOL = 0.01


# ---------------------------------------------------------------------------
# Weight-vector kernels (pure)
# ---------------------------------------------------------------------------


def signed_weights_from_rows(weights: np.ndarray, ic_sharpes: np.ndarray) -> np.ndarray:
    """Replicate ensemble_trainer.py's `signed_weights = weights * ic_signs`
    (line 962) from stored ensemble_weights columns.

    ensemble_weights has no ic_sign column; sign is inferred from the stored
    ic_sharpe (the exact ic_input-resolved sign-carrying value the trainer wrote,
    line 924). ic_sharpe >= 0 -> +1 (never 0: a zero sign would silently zero the
    weight, and the champion's ic_ci_lower > 0 eligibility makes exact-zero
    ic_sharpe impossible for a weighted feature anyway). The reconstruction check
    against stored ensemble_alpha verifies this empirically per stratum.
    """
    signs = np.where(np.asarray(ic_sharpes, dtype=np.float64) < 0.0, -1.0, 1.0)
    return np.asarray(weights, dtype=np.float64) * signs


def zero_family(signed_weights: np.ndarray, group_names: list[str], family: str) -> np.ndarray:
    """Return a COPY of signed_weights with every entry belonging to `family`
    zeroed -- the leave-one-family-out arm. Copy semantics are load-bearing: arms
    must never mutate the shared baseline vector.
    """
    out = signed_weights.copy()
    mask = np.array([g == family for g in group_names], dtype=bool)
    out[mask] = 0.0
    return out


def weight_mass_fraction(
    signed_weights: np.ndarray, group_names: list[str], family: str
) -> float:
    """Fraction of total ABSOLUTE weight mass carried by `family` (context column
    for the attribution table). Absolute, not signed: a contrarian feature's share
    must not net against longs. Returns 0.0 for an all-zero vector.
    """
    abs_w = np.abs(np.asarray(signed_weights, dtype=np.float64))
    total = float(abs_w.sum())
    if total < 1e-12:
        return 0.0
    mask = np.array([g == family for g in group_names], dtype=bool)
    return float(abs_w[mask].sum()) / total
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_ensemble_ablation.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/ops/alpha/ops_ensemble_ablation.py tests/unit/test_ensemble_ablation.py
git commit -m "feat(ablation): script skeleton and weight-vector kernels for todo 084"
```

---

### Task 2: Cross-symbol pooling kernel, equivalence-tested against `_aggregate_pooled_series`

**Files:**
- Modify: `scripts/ops/alpha/ops_ensemble_ablation.py` (append after `weight_mass_fraction`)
- Test: `tests/unit/test_ensemble_ablation.py` (append)

**Interfaces:**
- Consumes: `services.ensemble_ic_engine._aggregate_pooled_series` (test-side only, as the equivalence oracle), `_SCALES`, `_SCALE_RETURN_COLUMNS`.
- Produces:
  - `apply_complete_gate(returns: np.ndarray, complete: np.ndarray) -> np.ndarray` (copy with NaN where not complete)
  - `pool_means_by_bar(bar_idx: np.ndarray, n_bars: int, values: np.ndarray) -> np.ndarray` (length `n_bars`, NaN where a bar has zero finite members)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_ensemble_ablation.py`:

```python
from datetime import UTC, datetime

from services.ensemble_ic_engine import _aggregate_pooled_series

from ops_ensemble_ablation import apply_complete_gate, pool_means_by_bar

# ---------------------------------------------------------------------------
# Task 2: pooling kernel
# ---------------------------------------------------------------------------


def test_apply_complete_gate_nans_incomplete_and_copies():
    """ic_engine convention (lines 1848-1850): a return is usable only when
    complete AND finite. Gate applied pre-pooling; input untouched."""
    returns = np.array([0.01, 0.02, np.nan, 0.04])
    complete = np.array([True, False, True, True])
    gated = apply_complete_gate(returns, complete)
    assert np.isfinite(gated[0]) and gated[0] == 0.01
    assert np.isnan(gated[1])  # complete=False censored even though value present
    assert np.isnan(gated[2])  # already NaN stays NaN
    assert gated[3] == 0.04
    assert returns[1] == 0.02  # input not mutated


def test_pool_means_by_bar_matches_aggregate_pooled_series():
    """Equivalence oracle: our vectorized pooling must produce the exact same
    cross-symbol means as ensemble_ic_engine._aggregate_pooled_series (the
    alpha_ensemble_ic POOLED convention, Pitfall 5: group before averaging),
    including None/NaN-skipping semantics. Two symbols, three bars, one missing
    value and one bar with a single member."""
    t1 = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    t2 = datetime(2026, 1, 5, 14, 35, tzinfo=UTC)
    t3 = datetime(2026, 1, 5, 14, 40, tzinfo=UTC)
    oracle_rows = [
        {"bar_ts": t1, "regime_label": "low_bull", "alpha_score": 1.0,
         "return_fast": 0.01, "return_mid": None, "return_slow": None, "return_extended": None},
        {"bar_ts": t1, "regime_label": "low_bull", "alpha_score": 3.0,
         "return_fast": 0.03, "return_mid": None, "return_slow": None, "return_extended": None},
        {"bar_ts": t2, "regime_label": "low_bull", "alpha_score": 5.0,
         "return_fast": None, "return_mid": None, "return_slow": None, "return_extended": None},
        {"bar_ts": t3, "regime_label": "low_bull", "alpha_score": 2.0,
         "return_fast": 0.02, "return_mid": None, "return_slow": None, "return_extended": None},
        {"bar_ts": t3, "regime_label": "low_bull", "alpha_score": 4.0,
         "return_fast": 0.06, "return_mid": None, "return_slow": None, "return_extended": None},
    ]
    oracle = _aggregate_pooled_series(oracle_rows, "5m")  # sorted by bar_ts

    bar_ts_arr = np.array([t1, t1, t2, t3, t3], dtype=object)
    unique_ts, bar_idx = np.unique(bar_ts_arr, return_inverse=True)
    alpha = np.array([1.0, 3.0, 5.0, 2.0, 4.0])
    ret_fast = np.array([0.01, 0.03, np.nan, 0.02, 0.06])

    pooled_alpha = pool_means_by_bar(bar_idx, len(unique_ts), alpha)
    pooled_fast = pool_means_by_bar(bar_idx, len(unique_ts), ret_fast)

    assert list(unique_ts) == [r["bar_ts"] for r in oracle]
    np.testing.assert_allclose(pooled_alpha, [r["alpha_score"] for r in oracle])
    # oracle returns None for the all-missing bar; ours returns NaN
    oracle_fast = [np.nan if r["return_fast"] is None else r["return_fast"] for r in oracle]
    np.testing.assert_allclose(pooled_fast, oracle_fast)


def test_pool_means_by_bar_all_nan_bar_is_nan_not_zero():
    """A bar with zero finite members must pool to NaN (unmeasurable), never a
    silent 0.0 -- 0.0 would enter downstream rank correlations as fake data."""
    bar_idx = np.array([0, 0, 1])
    values = np.array([np.nan, np.nan, 5.0])
    pooled = pool_means_by_bar(bar_idx, 2, values)
    assert np.isnan(pooled[0])
    assert pooled[1] == 5.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_ensemble_ablation.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'apply_complete_gate' from 'ops_ensemble_ablation'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/ops/alpha/ops_ensemble_ablation.py`:

```python
# ---------------------------------------------------------------------------
# Cross-symbol pooling (pure) -- alpha_ensemble_ic POOLED convention
# ---------------------------------------------------------------------------


def apply_complete_gate(returns: np.ndarray, complete: np.ndarray) -> np.ndarray:
    """Censor incomplete forward returns BEFORE pooling: a return participates only
    when complete_<scale> is true AND the value is finite (services/ic_engine.py
    lines 1848-1850). Returns a copy with NaN at censored positions; NaN is then
    skipped by pool_means_by_bar, so a censored per-symbol return can never leak
    into a pooled cross-symbol mean.
    """
    out = np.asarray(returns, dtype=np.float64).copy()
    out[~np.asarray(complete, dtype=bool)] = np.nan
    return out


def pool_means_by_bar(bar_idx: np.ndarray, n_bars: int, values: np.ndarray) -> np.ndarray:
    """Cross-symbol mean per bar: the alpha_ensemble_ic POOLED aggregation grain
    (group by bar_ts within a fixed (tf, regime) stratum, average across symbols
    BEFORE any IC math -- ensemble_ic_engine._aggregate_pooled_series / RESEARCH
    Pitfall 5). Vectorized via bincount instead of reusing _aggregate_pooled_series
    directly because each stratum pools 12 arms over the same bar grouping and the
    dict-per-row oracle would rebuild row dicts per arm; equivalence with the
    oracle is pinned by test_pool_means_by_bar_matches_aggregate_pooled_series so
    the two implementations cannot silently diverge.

    Args:
        bar_idx: [n_rows] int array mapping each (symbol, bar) row to its bar's
            index in time-sorted unique-bar order (np.unique(..., return_inverse)).
        n_bars: number of distinct bars (len of np.unique's first output).
        values: [n_rows] float array; NaN entries are skipped (missing member,
            not a zero observation).

    Returns:
        [n_bars] float64 array of per-bar means; NaN where a bar has zero finite
        members (unmeasurable, never a silent 0.0).
    """
    values = np.asarray(values, dtype=np.float64)
    finite = np.isfinite(values)
    sums = np.bincount(bar_idx[finite], weights=values[finite], minlength=n_bars)
    counts = np.bincount(bar_idx[finite], minlength=n_bars)
    out = np.full(n_bars, np.nan)
    has_members = counts > 0
    out[has_members] = sums[has_members] / counts[has_members]
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_ensemble_ablation.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/ops/alpha/ops_ensemble_ablation.py tests/unit/test_ensemble_ablation.py
git commit -m "feat(ablation): pooling kernel equivalence-tested against _aggregate_pooled_series"
```

---

### Task 3: Arm IC measurement and baseline reconstruction check

**Files:**
- Modify: `scripts/ops/alpha/ops_ensemble_ablation.py` (append)
- Test: `tests/unit/test_ensemble_ablation.py` (append)

**Interfaces:**
- Consumes: `compute_ic_vectorized`, `_fisher_z_ci`, `_nan_to_none` from `ic_math` (already imported in Task 1); `_DEGENERATE_STD`.
- Produces:
  - `@dataclasses.dataclass(frozen=True) class ArmIC: ic: float; ci_lower: float | None; ci_upper: float | None; n: int`
  - `compute_arm_ic(pooled_alpha: np.ndarray, pooled_returns: np.ndarray, stride: int, min_reliable_n: int) -> ArmIC | None`
  - `reconstruction_check(recomputed: np.ndarray, stored: np.ndarray, tol: float) -> tuple[int, float | None, bool]` returning `(n_compared, norm_max_diff, ok)`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_ensemble_ablation.py`:

```python
from ops_ensemble_ablation import ArmIC, compute_arm_ic, reconstruction_check

# ---------------------------------------------------------------------------
# Task 3: arm IC measurement + reconstruction check
# ---------------------------------------------------------------------------


def _monotone_series(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Perfectly rank-aligned alpha/returns pair: Spearman IC exactly 1.0."""
    rng = np.random.default_rng(42)
    alpha = np.sort(rng.normal(size=n))
    returns = np.sort(rng.normal(size=n))
    return alpha, returns


def test_compute_arm_ic_perfect_rank_alignment():
    alpha, returns = _monotone_series(300)
    arm = compute_arm_ic(alpha, returns, stride=1, min_reliable_n=100)
    assert arm is not None
    assert arm.n == 300
    assert arm.ic == 1.0
    # CI machinery present, never a bare correlation (project rule)
    assert arm.ci_lower is not None and arm.ci_upper is not None
    assert arm.ci_lower <= arm.ic <= arm.ci_upper


def test_compute_arm_ic_stride_subsamples_before_gating():
    """stride = max(subsample_min_stride, lookahead_bars) applied to the pooled
    series (ensemble_ic_engine lines 770-773): 300 bars at stride 60 -> 5 obs,
    below min_reliable_n -> None, even though the raw series was long enough."""
    alpha, returns = _monotone_series(300)
    assert compute_arm_ic(alpha, returns, stride=60, min_reliable_n=100) is None


def test_compute_arm_ic_nan_pairs_excluded_from_n():
    alpha, returns = _monotone_series(300)
    returns = returns.copy()
    returns[:150] = np.nan
    arm = compute_arm_ic(alpha, returns, stride=1, min_reliable_n=100)
    assert arm is not None
    assert arm.n == 150


def test_compute_arm_ic_degenerate_series_is_none_not_zero():
    """Zeroing the only weighted family makes the composite constant; Spearman on a
    constant is UNDEFINED. Must return None (rendered DEGENERATE), never IC=0.0 --
    an IC of 0.0 would fake 'family removal made the model exactly neutral'."""
    returns = np.linspace(-1.0, 1.0, 300)
    constant_alpha = np.zeros(300)
    assert compute_arm_ic(constant_alpha, returns, stride=1, min_reliable_n=100) is None


def test_compute_arm_ic_identical_code_path_for_identical_inputs():
    """The zero-delta property the control family relies on: an arm whose weights
    equal the baseline's must produce the bit-identical ArmIC (same function, same
    inputs). Guards against any future baseline-only shortcut."""
    alpha, returns = _monotone_series(300)
    a = compute_arm_ic(alpha, returns, stride=3, min_reliable_n=50)
    b = compute_arm_ic(alpha.copy(), returns.copy(), stride=3, min_reliable_n=50)
    assert a == b


def test_reconstruction_check_pass_and_mismatch():
    stored = np.array([1.0, 2.0, 3.0, 4.0])
    n, diff, ok = reconstruction_check(stored.copy(), stored, tol=0.01)
    assert (n, diff, ok) == (4, 0.0, True)
    off = stored + np.array([0.0, 0.0, 0.0, 1.0])  # 1.0 abs diff vs std ~1.118
    n, diff, ok = reconstruction_check(off, stored, tol=0.01)
    assert n == 4 and diff is not None and diff > 0.01 and ok is False


def test_reconstruction_check_no_stored_overlap_is_skipped_not_failed():
    """Stored ensemble_alpha may not cover OOS bars (e.g. trainer ran before those
    bars existed): zero overlap is SKIPPED (ok=True, diff None), not a mismatch."""
    recomputed = np.array([1.0, 2.0])
    stored = np.array([np.nan, np.nan])
    assert reconstruction_check(recomputed, stored, tol=0.01) == (0, None, True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_ensemble_ablation.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'ArmIC' from 'ops_ensemble_ablation'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/ops/alpha/ops_ensemble_ablation.py`:

```python
# ---------------------------------------------------------------------------
# Arm IC measurement + reconstruction check (pure)
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ArmIC:
    """One arm's measured IC on one (stratum, scale) cell."""

    ic: float
    ci_lower: float | None
    ci_upper: float | None
    n: int


def compute_arm_ic(
    pooled_alpha: np.ndarray,
    pooled_returns: np.ndarray,
    stride: int,
    min_reliable_n: int,
) -> ArmIC | None:
    """Measure one arm's Spearman IC with Fisher-z CI on a pooled per-bar series.

    THE shared measurement path: baseline and every ablated arm go through this
    exact function with the exact same pooled_returns/stride/min_reliable_n, so
    the only between-arm difference is the alpha series itself (identical-code-path
    invariant). Mirrors ensemble_ic_engine's per-cell sequence: stride subsample
    (independence of overlapping forward returns) -> finite-pair mask ->
    min_reliable_n gate -> compute_ic_vectorized -> _fisher_z_ci.

    Returns None when the cell is unmeasurable: fewer than min_reliable_n valid
    pairs after subsampling, or a degenerate (near-constant) alpha series --
    Spearman is undefined on a constant, and reporting 0.0 would be a silent wrong
    answer (e.g. zeroing the only weighted family must read DEGENERATE, not
    "exactly neutral").
    """
    sub_idx = np.arange(0, len(pooled_alpha), stride)
    alpha_sub = np.asarray(pooled_alpha, dtype=np.float64)[sub_idx]
    returns_sub = np.asarray(pooled_returns, dtype=np.float64)[sub_idx]
    valid = np.isfinite(alpha_sub) & np.isfinite(returns_sub)
    n_valid = int(valid.sum())
    if n_valid < min_reliable_n:
        return None
    alpha_valid = alpha_sub[valid]
    returns_valid = returns_sub[valid]
    if float(np.std(alpha_valid)) < _DEGENERATE_STD:
        return None
    ic_vector = compute_ic_vectorized(alpha_valid.reshape(-1, 1), returns_valid)
    ci_lower_arr, ci_upper_arr = _fisher_z_ci(ic_vector, n_valid)
    return ArmIC(
        ic=float(ic_vector[0]),
        ci_lower=_nan_to_none(float(ci_lower_arr[0])),
        ci_upper=_nan_to_none(float(ci_upper_arr[0])),
        n=n_valid,
    )


def reconstruction_check(
    recomputed: np.ndarray, stored: np.ndarray, tol: float
) -> tuple[int, float | None, bool]:
    """Verify the recomputed baseline against stored ensemble_alpha.alpha_score.

    Compares only bars where a stored score exists (stored is NaN where the LEFT
    JOIN found no row). Normalization: max |recomputed - stored| / std(stored) --
    scale-free, robust to near-zero individual scores where a relative tolerance
    would explode. Zero overlap returns (0, None, True): SKIPPED, not a failure
    (the trainer may simply predate those OOS bars).

    A False here means the trainer's inputs drifted since it ran (re-run
    ensemble_trainer before trusting attribution) or this script's replication of
    the scoring formula is wrong -- either way the stratum's deltas are
    untrustworthy and the report must say so loudly.
    """
    mask = np.isfinite(np.asarray(stored, dtype=np.float64))
    n_compared = int(mask.sum())
    if n_compared == 0:
        return 0, None, True
    stored_masked = np.asarray(stored, dtype=np.float64)[mask]
    recomputed_masked = np.asarray(recomputed, dtype=np.float64)[mask]
    max_abs_diff = float(np.max(np.abs(recomputed_masked - stored_masked)))
    denom = max(float(np.std(stored_masked)), 1e-12)
    norm_max_diff = max_abs_diff / denom
    return n_compared, norm_max_diff, norm_max_diff <= tol
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_ensemble_ablation.py -v`
Expected: 16 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/ops/alpha/ops_ensemble_ablation.py tests/unit/test_ensemble_ablation.py
git commit -m "feat(ablation): arm IC measurement and baseline reconstruction check"
```

---

### Task 4: SQL constants, fetch-SQL builder, config binding, panel-array preparation

**Files:**
- Modify: `scripts/ops/alpha/ops_ensemble_ablation.py` (append)
- Test: `tests/unit/test_ensemble_ablation.py` (append)

**Interfaces:**
- Consumes: `_SCALES`, `_SCALE_RETURN_COLUMNS` (imported in Task 1); `_cfg` from `services._batch_utils`.
- Produces:
  - `_STRATA_SQL: str`, `_WEIGHTS_SQL: str`, `_FAMILIES_SQL: str` (module constants)
  - `build_stratum_fetch_sql(feature_names: list[str]) -> str` (asyncpg placeholders `$1..$4` = tf, regime, weight_version, oos_start)
  - `@dataclasses.dataclass(frozen=True) class AblationConfig: subsample_min_stride: int; min_reliable_n: int; fdr_alpha: float; lookahead_fast: int; lookahead_mid: int; lookahead_slow: int; lookahead_extended: int` with `@property lookaheads -> dict[str, int]` and `@classmethod from_apr(cfg: dict[str, Any]) -> AblationConfig`
  - `prepare_stratum_arrays(fv_rows: list[Any], feature_names: list[str]) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, np.ndarray], np.ndarray]` returning `(bar_idx, unique_flag_placeholder_see_below, X, gated_returns_by_scale, stored_alpha)`. Exact return contract: `(bar_ts_arr [n_rows] object, X [n_rows, n_features] float32, gated_returns_by_scale {scale: [n_rows] float64 complete-gated}, stored_alpha [n_rows] float64 NaN-where-missing)` -- 4 items; `bar_idx`/`n_bars` are derived by the caller via `np.unique(bar_ts_arr, return_inverse=True)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_ensemble_ablation.py`:

```python
from ops_ensemble_ablation import (
    _FAMILIES_SQL,
    _STRATA_SQL,
    _WEIGHTS_SQL,
    AblationConfig,
    build_stratum_fetch_sql,
    prepare_stratum_arrays,
)

# ---------------------------------------------------------------------------
# Task 4: SQL invariants + config + panel preparation
# ---------------------------------------------------------------------------


def test_fetch_sql_statistical_invariants():
    """The three non-negotiable measurement invariants, pinned as SQL text so a
    refactor cannot silently drop them: executable returns filter, OOS >= boundary,
    complete_* columns fetched for gating. Plus weight_version scoping on the
    stored-baseline join (never blend another variant's alpha into the check)."""
    sql = build_stratum_fetch_sql(["momentum_z_fast", "obv_z"])
    assert "return_type = 'executable_open_to_open'" in sql
    assert "fv.bar_ts >= $4" in sql
    for scale in ("fast", "mid", "slow", "extended"):
        assert f"fr.return_{scale}" in sql
        assert f"fr.complete_{scale}" in sql
    assert 'fv."momentum_z_fast"' in sql and 'fv."obv_z"' in sql
    assert "ea.weight_version = $3" in sql
    # trainer's exact stratum join: market_regimes on (asset_class, tf, ts)
    assert "mr.asset_class = 'equity'" in sql
    assert "ORDER BY fv.bar_ts, fv.symbol" in sql


def test_weights_and_strata_sql_scope_to_universe_and_version():
    assert "symbol = 'UNIVERSE'" in _STRATA_SQL
    assert "weight_version = $1" in _STRATA_SQL
    assert "ew.symbol = 'UNIVERSE'" in _WEIGHTS_SQL
    assert "ew.weight_version = $1" in _WEIGHTS_SQL
    assert "freg.group_name" in _WEIGHTS_SQL
    assert "group_name" in _FAMILIES_SQL


def test_ablation_config_from_apr_defaults_match_engines():
    """Fallback defaults must be byte-identical to EnsembleICConfig.from_apr's --
    a divergent fallback would silently measure with different gates on a DB
    missing a key."""
    config = AblationConfig.from_apr({})
    assert config.subsample_min_stride == 5
    assert config.min_reliable_n == 100
    assert config.fdr_alpha == 0.05
    assert config.lookaheads == {"fast": 1, "mid": 5, "slow": 20, "extended": 60}


def test_ablation_config_from_apr_reads_keys():
    config = AblationConfig.from_apr(
        {
            "alpha.ic.subsample_min_stride": 7,
            "alpha.ic.min_reliable_n": 150,
            "alpha.ic.fdr_alpha": 0.10,
            "alpha.ic.lookahead.fast": 2,
            "alpha.ic.lookahead.mid": 10,
            "alpha.ic.lookahead.slow": 40,
            "alpha.ic.lookahead.extended": 120,
        }
    )
    assert config.subsample_min_stride == 7
    assert config.min_reliable_n == 150
    assert config.fdr_alpha == 0.10
    assert config.lookaheads == {"fast": 2, "mid": 10, "slow": 40, "extended": 120}


def test_prepare_stratum_arrays_trainer_conventions():
    """X follows ensemble_trainer.py lines 823-826 exactly: NULL -> 0.0, float32.
    Returns are complete-gated per row; stored alpha NaN where the LEFT JOIN
    found no ensemble_alpha row."""
    t1 = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    t2 = datetime(2026, 1, 5, 14, 35, tzinfo=UTC)
    rows = [
        {
            "symbol": "SPY", "bar_ts": t1, "f_a": 1.5, "f_b": None,
            "return_fast": 0.01, "return_mid": 0.02, "return_slow": 0.03, "return_extended": 0.04,
            "complete_fast": True, "complete_mid": False, "complete_slow": True, "complete_extended": True,
            "stored_alpha": 0.7,
        },
        {
            "symbol": "TLT", "bar_ts": t2, "f_a": -0.5, "f_b": 2.0,
            "return_fast": None, "return_mid": 0.05, "return_slow": None, "return_extended": 0.06,
            "complete_fast": True, "complete_mid": True, "complete_slow": True, "complete_extended": False,
            "stored_alpha": None,
        },
    ]
    bar_ts_arr, X, gated, stored = prepare_stratum_arrays(rows, ["f_a", "f_b"])
    assert X.dtype == np.float32
    np.testing.assert_allclose(X, [[1.5, 0.0], [-0.5, 2.0]])
    assert list(bar_ts_arr) == [t1, t2]
    assert gated["fast"][0] == 0.01
    assert np.isnan(gated["mid"][0])       # complete_mid=False censored
    assert np.isnan(gated["fast"][1])      # NULL return
    assert gated["mid"][1] == 0.05
    assert np.isnan(gated["extended"][1])  # complete_extended=False censored
    assert stored[0] == 0.7 and np.isnan(stored[1])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_ensemble_ablation.py -v`
Expected: FAIL at collection with `ImportError: cannot import name '_FAMILIES_SQL' from 'ops_ensemble_ablation'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/ops/alpha/ops_ensemble_ablation.py`:

```python
# ---------------------------------------------------------------------------
# SQL + config binding + panel preparation
# ---------------------------------------------------------------------------

# Strata = the trainer's own output grain: (tf, regime) per weight_version, all
# rows symbol='UNIVERSE' (universe-level weights; 100% of live rows carry this).
_STRATA_SQL = """
    SELECT DISTINCT tf, regime
    FROM ensemble_weights
    WHERE weight_version = $1 AND symbol = 'UNIVERSE'
    ORDER BY tf, regime
"""

# Per-stratum weight vector joined to feature_registry for the family label.
# The trainer's registry-alignment gate guarantees every feature_name has exactly
# one feature_registry row, so this join can never drop a weighted feature.
_WEIGHTS_SQL = """
    SELECT ew.feature_name, ew.weight, ew.ic_sharpe, ew.lookahead_bars,
           freg.group_name
    FROM ensemble_weights ew
    JOIN feature_registry freg ON freg.feature_name = ew.feature_name
    WHERE ew.weight_version = $1 AND ew.symbol = 'UNIVERSE'
      AND ew.tf = $2 AND ew.regime = $3
    ORDER BY ew.feature_name
"""

# Sweep families from the registry at runtime (11 live values as of 2026-07-13),
# never a hardcoded list -- includes 'control' by design (see module docstring).
_FAMILIES_SQL = "SELECT DISTINCT group_name FROM feature_registry ORDER BY group_name"


def build_stratum_fetch_sql(feature_names: list[str]) -> str:
    """OOS panel fetch for one (tf, regime) stratum.

    Placeholders: $1=tf, $2=regime_label, $3=weight_version, $4=oos_start.
    - feature_vectors JOIN market_regimes: the trainer's exact stratum join
      (ensemble_trainer.py lines 792-799) -- feature_vectors.regime holds
      per-symbol HMM labels; the cross-sectional stratum label lives in
      market_regimes (asset_class='equity', tf, ts=bar_ts).
    - JOIN forward_returns with the executable filter (Invariant 1) plus the four
      return_* AND complete_* columns for pre-pooling completeness gating.
    - LEFT JOIN ensemble_alpha scoped to this weight_version: stored baseline for
      the replication check only (LEFT: missing stored rows are a skipped check,
      not lost measurement bars).
    - fv.bar_ts >= $4: the OOS boundary, >= per ops_oos_holdout_eval._oos_mask,
      exactly complementary to the training side's bar_ts < oos_start.
    - ORDER BY fv.bar_ts, fv.symbol: the trainer's scoring order.
    feature_names come from ensemble_weights/information-schema-governed registry
    rows, not user input (same trust argument as the trainer's col_list f-string).
    """
    col_list = ", ".join(f'fv."{c}"' for c in feature_names)
    return_cols = ", ".join(f"fr.{_SCALE_RETURN_COLUMNS[s]}" for s in _SCALES)
    complete_cols = ", ".join(f"fr.complete_{s}" for s in _SCALES)
    return f"""
        SELECT fv.symbol, fv.bar_ts, {col_list}, {return_cols}, {complete_cols},
               ea.alpha_score AS stored_alpha
        FROM feature_vectors fv
        JOIN market_regimes mr
          ON mr.asset_class = 'equity' AND mr.tf = fv.tf AND mr.ts = fv.bar_ts
        JOIN forward_returns fr
          ON fr.symbol = fv.symbol AND fr.tf = fv.tf AND fr.bar_ts = fv.bar_ts
          AND fr.return_type = 'executable_open_to_open'
        LEFT JOIN ensemble_alpha ea
          ON ea.symbol = fv.symbol AND ea.tf = fv.tf AND ea.bar_ts = fv.bar_ts
          AND ea.weight_version = $3
        WHERE fv.tf = $1 AND mr.regime_label = $2 AND fv.bar_ts >= $4
        ORDER BY fv.bar_ts, fv.symbol
    """


@dataclasses.dataclass(frozen=True)
class AblationConfig:
    """Frozen APR snapshot bound once at startup (compile-time binding, the
    EnsembleICConfig pattern). Fallback defaults are byte-identical to
    EnsembleICConfig.from_apr's for the shared keys -- a divergent fallback would
    silently measure with different gates on a DB missing a key. No new APR keys:
    every threshold here already exists under alpha.ic.*.
    """

    subsample_min_stride: int
    min_reliable_n: int
    fdr_alpha: float
    lookahead_fast: int
    lookahead_mid: int
    lookahead_slow: int
    lookahead_extended: int

    @property
    def lookaheads(self) -> dict[str, int]:
        return {
            "fast": self.lookahead_fast,
            "mid": self.lookahead_mid,
            "slow": self.lookahead_slow,
            "extended": self.lookahead_extended,
        }

    @classmethod
    def from_apr(cls, cfg: dict[str, Any]) -> AblationConfig:
        return cls(
            subsample_min_stride=_cfg(cfg, "alpha.ic.subsample_min_stride", 5),
            min_reliable_n=_cfg(cfg, "alpha.ic.min_reliable_n", 100),
            fdr_alpha=_cfg(cfg, "alpha.ic.fdr_alpha", 0.05),
            lookahead_fast=_cfg(cfg, "alpha.ic.lookahead.fast", 1),
            lookahead_mid=_cfg(cfg, "alpha.ic.lookahead.mid", 5),
            lookahead_slow=_cfg(cfg, "alpha.ic.lookahead.slow", 20),
            lookahead_extended=_cfg(cfg, "alpha.ic.lookahead.extended", 60),
        )


def prepare_stratum_arrays(
    fv_rows: list[Any], feature_names: list[str]
) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray], np.ndarray]:
    """Convert fetched panel rows (asyncpg Records or dicts) into scoring arrays.

    X replicates ensemble_trainer.py lines 823-826 exactly: NULL -> 0.0, float32
    (the reconstruction check depends on matching the trainer's dtype path).
    Returns are complete-gated per row via apply_complete_gate. stored_alpha is
    NaN where the LEFT JOIN found no ensemble_alpha row.

    Returns:
        (bar_ts_arr [n_rows] object, X [n_rows, n_features] float32,
         gated_returns_by_scale {scale: [n_rows] float64}, stored_alpha [n_rows]).
    """
    bar_ts_arr = np.array([r["bar_ts"] for r in fv_rows], dtype=object)
    X = np.array(
        [[float(r[c]) if r[c] is not None else 0.0 for c in feature_names] for r in fv_rows],
        dtype=np.float32,
    )
    gated_returns_by_scale: dict[str, np.ndarray] = {}
    for scale in _SCALES:
        return_col = _SCALE_RETURN_COLUMNS[scale]
        raw = np.array(
            [float(r[return_col]) if r[return_col] is not None else np.nan for r in fv_rows]
        )
        complete = np.array([bool(r[f"complete_{scale}"]) for r in fv_rows])
        gated_returns_by_scale[scale] = apply_complete_gate(raw, complete)
    stored_alpha = np.array(
        [float(r["stored_alpha"]) if r["stored_alpha"] is not None else np.nan for r in fv_rows]
    )
    return bar_ts_arr, X, gated_returns_by_scale, stored_alpha
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_ensemble_ablation.py -v`
Expected: 21 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/ops/alpha/ops_ensemble_ablation.py tests/unit/test_ensemble_ablation.py
git commit -m "feat(ablation): SQL constants, APR config binding, panel preparation"
```

---

### Task 5: Per-stratum attribution assembly and corpus-wide BH-FDR on deltas

**Files:**
- Modify: `scripts/ops/alpha/ops_ensemble_ablation.py` (append)
- Test: `tests/unit/test_ensemble_ablation.py` (append)

**Interfaces:**
- Consumes: `zero_family`, `weight_mass_fraction`, `pool_means_by_bar`, `compute_arm_ic`, `ArmIC` (Tasks 1-3); `fisher_z_difference_p`, `apply_bh_fdr` from `ic_math`.
- Produces:
  - `@dataclasses.dataclass(frozen=True) class AttributionRow` with fields exactly: `tf: str; regime: str; scale: str; family: str; n_features_zeroed: int; weight_mass_zeroed: float; n_obs: int; ic_baseline: float | None; ci_lower: float | None; ci_upper: float | None; ic_ablated: float | None; delta_ic: float | None; diff_p: float | None; bh_adjusted_p: float | None; delta_passes_fdr: bool | None; flag: str`
  - `compute_stratum_attribution(tf: str, regime: str, families: list[str], group_names: list[str], signed_weights: np.ndarray, X: np.ndarray, bar_idx: np.ndarray, n_bars: int, pooled_returns_by_scale: dict[str, np.ndarray], config: AblationConfig) -> list[AttributionRow]`
  - `apply_delta_fdr(rows: list[AttributionRow], fdr_alpha: float) -> list[AttributionRow]`
  - Flag string constants: `_FLAG_ABSENT = "family absent from this stratum"`, `_FLAG_DEGENERATE = "DEGENERATE (ablated composite near-constant; family was effectively the whole model)"`, `_FLAG_BASELINE_UNMEASURABLE = "BASELINE UNMEASURABLE (insufficient N after stride/completeness gates)"`, `_FLAG_CONTROL_BREACH = "CONTROL FAMILY CARRIES WEIGHT (governance breach: canaries must never be ensemble-eligible)"`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_ensemble_ablation.py`:

```python
from ops_ensemble_ablation import (
    _FLAG_ABSENT,
    _FLAG_BASELINE_UNMEASURABLE,
    _FLAG_CONTROL_BREACH,
    _FLAG_DEGENERATE,
    AblationConfig,
    AttributionRow,
    apply_delta_fdr,
    compute_stratum_attribution,
)

# ---------------------------------------------------------------------------
# Task 5: attribution assembly
# ---------------------------------------------------------------------------

_TEST_CONFIG = AblationConfig(
    subsample_min_stride=1,
    min_reliable_n=50,
    fdr_alpha=0.05,
    lookahead_fast=1,
    lookahead_mid=1,
    lookahead_slow=1,
    lookahead_extended=1,
)


def _one_symbol_panel(n_bars: int = 400):
    """Single-symbol panel (pooling is identity): 2 features, feature 0
    ('momentum') is a perfect rank predictor of returns, feature 1 ('volume') is
    seeded noise. bar_idx = arange since one row per bar."""
    rng = np.random.default_rng(7)
    returns = rng.normal(size=n_bars)
    predictor = returns.copy()          # rank-identical to returns
    noise = rng.normal(size=n_bars)
    X = np.column_stack([predictor, noise]).astype(np.float32)
    bar_idx = np.arange(n_bars)
    pooled_returns = {s: returns.astype(np.float64) for s in ("fast", "mid", "slow", "extended")}
    return X, bar_idx, n_bars, pooled_returns


def test_attribution_zeroing_predictive_family_drops_ic():
    X, bar_idx, n_bars, pooled_returns = _one_symbol_panel()
    rows = compute_stratum_attribution(
        tf="5m", regime="low_bull",
        families=["momentum", "volume", "control"],
        group_names=["momentum", "volume"],
        signed_weights=np.array([1.0, 0.05]),
        X=X, bar_idx=bar_idx, n_bars=n_bars,
        pooled_returns_by_scale=pooled_returns,
        config=_TEST_CONFIG,
    )
    fast = {r.family: r for r in rows if r.scale == "fast"}
    baseline = fast["__baseline__"]
    assert baseline.ic_baseline is not None and baseline.ic_baseline > 0.9
    momentum = fast["momentum"]
    # removing the predictive family must reduce IC: positive marginal contribution
    assert momentum.delta_ic is not None and momentum.delta_ic > 0.5
    assert momentum.ic_ablated is not None and momentum.ic_ablated < 0.3
    assert momentum.diff_p is not None
    # noise family removal barely moves IC
    volume = fast["volume"]
    assert volume.delta_ic is not None and abs(volume.delta_ic) < 0.1
    # both arms measured on the identical bar set
    assert momentum.n_obs == baseline.n_obs == volume.n_obs


def test_attribution_absent_family_is_flagged_not_computed():
    X, bar_idx, n_bars, pooled_returns = _one_symbol_panel()
    rows = compute_stratum_attribution(
        tf="5m", regime="low_bull",
        families=["momentum", "volume", "control"],
        group_names=["momentum", "volume"],
        signed_weights=np.array([1.0, 0.05]),
        X=X, bar_idx=bar_idx, n_bars=n_bars,
        pooled_returns_by_scale=pooled_returns,
        config=_TEST_CONFIG,
    )
    control = [r for r in rows if r.family == "control" and r.scale == "fast"][0]
    assert control.flag == _FLAG_ABSENT
    assert control.n_features_zeroed == 0
    assert control.delta_ic is None and control.ic_ablated is None


def test_attribution_control_family_with_weight_is_governance_breach():
    X, bar_idx, n_bars, pooled_returns = _one_symbol_panel()
    rows = compute_stratum_attribution(
        tf="5m", regime="low_bull",
        families=["momentum", "control"],
        group_names=["momentum", "control"],   # canary somehow carries weight
        signed_weights=np.array([1.0, 0.05]),
        X=X, bar_idx=bar_idx, n_bars=n_bars,
        pooled_returns_by_scale=pooled_returns,
        config=_TEST_CONFIG,
    )
    control = [r for r in rows if r.family == "control" and r.scale == "fast"][0]
    assert control.flag == _FLAG_CONTROL_BREACH
    assert control.n_features_zeroed == 1
    assert control.delta_ic is not None  # still measured: near-zero delta expected


def test_attribution_sole_family_zeroed_is_degenerate_not_zero_ic():
    X, bar_idx, n_bars, pooled_returns = _one_symbol_panel()
    rows = compute_stratum_attribution(
        tf="5m", regime="low_bull",
        families=["momentum"],
        group_names=["momentum", "momentum"],
        signed_weights=np.array([1.0, 0.05]),
        X=X, bar_idx=bar_idx, n_bars=n_bars,
        pooled_returns_by_scale=pooled_returns,
        config=_TEST_CONFIG,
    )
    momentum = [r for r in rows if r.family == "momentum" and r.scale == "fast"][0]
    assert momentum.flag == _FLAG_DEGENERATE
    assert momentum.ic_ablated is None and momentum.delta_ic is None


def test_attribution_unmeasurable_baseline_short_circuits_scale():
    """min_reliable_n above the bar count: baseline unmeasurable -> exactly one
    row per scale (the flagged baseline row), no family rows computed against a
    nonexistent baseline."""
    X, bar_idx, n_bars, pooled_returns = _one_symbol_panel(n_bars=30)
    rows = compute_stratum_attribution(
        tf="5m", regime="low_bull",
        families=["momentum", "volume"],
        group_names=["momentum", "volume"],
        signed_weights=np.array([1.0, 0.05]),
        X=X, bar_idx=bar_idx, n_bars=n_bars,
        pooled_returns_by_scale=pooled_returns,
        config=_TEST_CONFIG,
    )
    fast_rows = [r for r in rows if r.scale == "fast"]
    assert len(fast_rows) == 1
    assert fast_rows[0].family == "__baseline__"
    assert fast_rows[0].flag == _FLAG_BASELINE_UNMEASURABLE


def test_apply_delta_fdr_one_corpus_wide_pass():
    """One multipletests family across ALL delta p-values (project convention);
    rows without a diff_p (baseline/absent/degenerate) stay None."""
    base = dict(
        tf="5m", regime="low_bull", scale="fast", n_features_zeroed=1,
        weight_mass_zeroed=0.5, n_obs=200, ic_baseline=0.5, ci_lower=0.4,
        ci_upper=0.6, ic_ablated=0.1, delta_ic=0.4, bh_adjusted_p=None,
        delta_passes_fdr=None, flag="",
    )
    rows = [
        AttributionRow(family="momentum", diff_p=0.001, **base),
        AttributionRow(family="volume", diff_p=0.90, **base),
        AttributionRow(family="__baseline__", diff_p=None, **base),
    ]
    corrected = apply_delta_fdr(rows, fdr_alpha=0.05)
    assert corrected[0].delta_passes_fdr is True
    assert corrected[0].bh_adjusted_p is not None
    assert corrected[1].delta_passes_fdr is False
    assert corrected[2].bh_adjusted_p is None and corrected[2].delta_passes_fdr is None


def test_apply_delta_fdr_empty_is_noop():
    assert apply_delta_fdr([], fdr_alpha=0.05) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_ensemble_ablation.py -v`
Expected: FAIL at collection with `ImportError: cannot import name '_FLAG_ABSENT' from 'ops_ensemble_ablation'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/ops/alpha/ops_ensemble_ablation.py`:

```python
# ---------------------------------------------------------------------------
# Attribution assembly (pure)
# ---------------------------------------------------------------------------

_FLAG_ABSENT = "family absent from this stratum"
_FLAG_DEGENERATE = (
    "DEGENERATE (ablated composite near-constant; family was effectively the whole model)"
)
_FLAG_BASELINE_UNMEASURABLE = (
    "BASELINE UNMEASURABLE (insufficient N after stride/completeness gates)"
)
_FLAG_CONTROL_BREACH = (
    "CONTROL FAMILY CARRIES WEIGHT (governance breach: canaries must never be "
    "ensemble-eligible)"
)


@dataclasses.dataclass(frozen=True)
class AttributionRow:
    """One line of the marginal-attribution table: one (stratum, scale, arm).

    family == _BASELINE_ARM rows describe the all-families baseline (ic_ablated/
    delta_ic/diff_p are None there). delta_ic = ic_baseline - ic_ablated: positive
    means removing the family REDUCED OOS IC, i.e. the family was contributing.
    ci_lower/ci_upper describe the arm this row measures (baseline row -> baseline
    CI; family row -> ablated-arm CI).
    """

    tf: str
    regime: str
    scale: str
    family: str
    n_features_zeroed: int
    weight_mass_zeroed: float
    n_obs: int
    ic_baseline: float | None
    ci_lower: float | None
    ci_upper: float | None
    ic_ablated: float | None
    delta_ic: float | None
    diff_p: float | None
    bh_adjusted_p: float | None
    delta_passes_fdr: bool | None
    flag: str


def compute_stratum_attribution(
    tf: str,
    regime: str,
    families: list[str],
    group_names: list[str],
    signed_weights: np.ndarray,
    X: np.ndarray,
    bar_idx: np.ndarray,
    n_bars: int,
    pooled_returns_by_scale: dict[str, np.ndarray],
    config: AblationConfig,
) -> list[AttributionRow]:
    """Leave-one-family-out attribution for one (tf, regime) stratum.

    Every arm -- the baseline and each family's zeroed variant -- goes through the
    identical sequence: X @ arm_weights (the trainer's scoring matmul, line 963),
    pool_means_by_bar (cross-symbol mean per bar), compute_arm_ic (stride
    subsample, gates, Spearman IC, Fisher-z CI). Pooled arm scores are computed
    ONCE per arm (pooling is scale-independent); the per-scale loop only re-runs
    the subsample + measurement step against that scale's gated returns.

    A family with zero weighted features in this stratum yields a _FLAG_ABSENT
    row per scale (delta None) -- 'control' landing here on every stratum is the
    EXPECTED outcome and doubles as the eligibility-filter check. A control family
    that DOES carry weight is measured normally but flagged _FLAG_CONTROL_BREACH.
    diff_p uses fisher_z_difference_p, which is conservative (over-estimates p)
    under the positive dependence of two arms measured on the same bars -- the
    safe direction for a postmortem attribution.
    """
    rows: list[AttributionRow] = []

    pooled_by_arm: dict[str, np.ndarray] = {
        _BASELINE_ARM: pool_means_by_bar(bar_idx, n_bars, X @ signed_weights)
    }
    family_n_features: dict[str, int] = {}
    family_mass: dict[str, float] = {}
    for family in families:
        n_features = sum(1 for g in group_names if g == family)
        family_n_features[family] = n_features
        family_mass[family] = weight_mass_fraction(signed_weights, group_names, family)
        if n_features > 0:
            ablated_weights = zero_family(signed_weights, group_names, family)
            pooled_by_arm[family] = pool_means_by_bar(bar_idx, n_bars, X @ ablated_weights)

    for scale in _SCALES:
        stride = max(config.subsample_min_stride, config.lookaheads[scale])
        pooled_returns = pooled_returns_by_scale[scale]
        baseline = compute_arm_ic(
            pooled_by_arm[_BASELINE_ARM], pooled_returns, stride, config.min_reliable_n
        )
        if baseline is None:
            rows.append(
                AttributionRow(
                    tf=tf, regime=regime, scale=scale, family=_BASELINE_ARM,
                    n_features_zeroed=0, weight_mass_zeroed=0.0, n_obs=0,
                    ic_baseline=None, ci_lower=None, ci_upper=None, ic_ablated=None,
                    delta_ic=None, diff_p=None, bh_adjusted_p=None,
                    delta_passes_fdr=None, flag=_FLAG_BASELINE_UNMEASURABLE,
                )
            )
            continue

        rows.append(
            AttributionRow(
                tf=tf, regime=regime, scale=scale, family=_BASELINE_ARM,
                n_features_zeroed=0, weight_mass_zeroed=0.0, n_obs=baseline.n,
                ic_baseline=baseline.ic, ci_lower=baseline.ci_lower,
                ci_upper=baseline.ci_upper, ic_ablated=None, delta_ic=None,
                diff_p=None, bh_adjusted_p=None, delta_passes_fdr=None, flag="",
            )
        )

        for family in families:
            n_features = family_n_features[family]
            is_control_breach = family == _CONTROL_FAMILY and n_features > 0
            if n_features == 0:
                rows.append(
                    AttributionRow(
                        tf=tf, regime=regime, scale=scale, family=family,
                        n_features_zeroed=0, weight_mass_zeroed=0.0,
                        n_obs=baseline.n, ic_baseline=baseline.ic, ci_lower=None,
                        ci_upper=None, ic_ablated=None, delta_ic=None, diff_p=None,
                        bh_adjusted_p=None, delta_passes_fdr=None, flag=_FLAG_ABSENT,
                    )
                )
                continue

            ablated = compute_arm_ic(
                pooled_by_arm[family], pooled_returns, stride, config.min_reliable_n
            )
            if ablated is None:
                rows.append(
                    AttributionRow(
                        tf=tf, regime=regime, scale=scale, family=family,
                        n_features_zeroed=n_features,
                        weight_mass_zeroed=family_mass[family], n_obs=baseline.n,
                        ic_baseline=baseline.ic, ci_lower=None, ci_upper=None,
                        ic_ablated=None, delta_ic=None, diff_p=None,
                        bh_adjusted_p=None, delta_passes_fdr=None,
                        flag=_FLAG_DEGENERATE,
                    )
                )
                continue

            delta_ic = baseline.ic - ablated.ic
            diff_p = fisher_z_difference_p(baseline.ic, baseline.n, ablated.ic, ablated.n)
            rows.append(
                AttributionRow(
                    tf=tf, regime=regime, scale=scale, family=family,
                    n_features_zeroed=n_features,
                    weight_mass_zeroed=family_mass[family], n_obs=ablated.n,
                    ic_baseline=baseline.ic, ci_lower=ablated.ci_lower,
                    ci_upper=ablated.ci_upper, ic_ablated=ablated.ic,
                    delta_ic=delta_ic,
                    diff_p=None if np.isnan(diff_p) else float(diff_p),
                    bh_adjusted_p=None, delta_passes_fdr=None,
                    flag=_FLAG_CONTROL_BREACH if is_control_breach else "",
                )
            )
    return rows


def apply_delta_fdr(rows: list[AttributionRow], fdr_alpha: float) -> list[AttributionRow]:
    """One corpus-wide BH-FDR pass across every delta p-value (the project's
    one-multipletests-call-per-family convention, via ic_math.apply_bh_fdr).
    Informational, not a gate: the report prints bh_adjusted_p/delta_passes_fdr so
    an operator can distinguish real family deaths from multiplicity noise across
    ~strata x scales x families comparisons. Rows without a diff_p (baseline,
    absent, degenerate) pass through unchanged.
    """
    indexed_p = [(i, r.diff_p) for i, r in enumerate(rows) if r.diff_p is not None]
    if not indexed_p:
        return list(rows)
    reject, p_corrected = apply_bh_fdr([p for _, p in indexed_p], fdr_alpha)
    out = list(rows)
    for flat_idx, (row_idx, _) in enumerate(indexed_p):
        out[row_idx] = dataclasses.replace(
            out[row_idx],
            bh_adjusted_p=float(p_corrected[flat_idx]),
            delta_passes_fdr=bool(reject[flat_idx]),
        )
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_ensemble_ablation.py -v`
Expected: 28 passed

- [ ] **Step 5: Commit**

```bash
git add scripts/ops/alpha/ops_ensemble_ablation.py tests/unit/test_ensemble_ablation.py
git commit -m "feat(ablation): per-stratum attribution assembly with corpus-wide delta FDR"
```

---

### Task 6: Markdown report renderer and manifest recorder

**Files:**
- Modify: `scripts/ops/alpha/ops_ensemble_ablation.py` (append)
- Test: `tests/unit/test_ensemble_ablation.py` (append)

**Interfaces:**
- Consumes: `AttributionRow`, flag constants (Task 5); `CorpusManifest` (imported Task 1).
- Produces:
  - `@dataclasses.dataclass(frozen=True) class ReplicationRecord: tf: str; regime: str; n_bars: int; n_compared: int; norm_max_diff: float | None; ok: bool`
  - `render_report(weight_version: str, oos_start: Any, families: list[str], rows: list[AttributionRow], replication: list[ReplicationRecord], config: AblationConfig, reconstruction_tol: float) -> list[str]` (list of markdown lines; caller prints)
  - `record_manifest(manifest_dir: Path, weight_version: str, oos_start: Any, families: list[str], rows: list[AttributionRow], replication: list[ReplicationRecord], error: str | None = None) -> Path`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_ensemble_ablation.py`:

```python
import json

from ops_ensemble_ablation import ReplicationRecord, record_manifest, render_report

# ---------------------------------------------------------------------------
# Task 6: report + manifest
# ---------------------------------------------------------------------------


def _fixture_rows_and_replication():
    base = dict(
        tf="5m", regime="low_bull", scale="fast", n_obs=200, ci_lower=0.1,
        ci_upper=0.5, bh_adjusted_p=None, delta_passes_fdr=None,
    )
    rows = [
        AttributionRow(family="__baseline__", n_features_zeroed=0,
                       weight_mass_zeroed=0.0, ic_baseline=0.30, ic_ablated=None,
                       delta_ic=None, diff_p=None, flag="", **base),
        AttributionRow(family="momentum", n_features_zeroed=4,
                       weight_mass_zeroed=0.6, ic_baseline=0.30, ic_ablated=0.05,
                       delta_ic=0.25, diff_p=0.001, flag="", **base),
        AttributionRow(family="control", n_features_zeroed=0,
                       weight_mass_zeroed=0.0, ic_baseline=0.30, ic_ablated=None,
                       delta_ic=None, diff_p=None, flag=_FLAG_ABSENT, **base),
    ]
    rows = apply_delta_fdr(rows, fdr_alpha=0.05)
    replication = [
        ReplicationRecord(tf="5m", regime="low_bull", n_bars=5000, n_compared=5000,
                          norm_max_diff=0.0002, ok=True),
        ReplicationRecord(tf="1d", regime="high_bear", n_bars=120, n_compared=120,
                          norm_max_diff=0.9, ok=False),
    ]
    return rows, replication


def test_render_report_contains_required_sections_and_flags():
    rows, replication = _fixture_rows_and_replication()
    lines = render_report(
        weight_version="run_x", oos_start="2025-12-24T05:15:00Z",
        families=["control", "momentum"], rows=rows, replication=replication,
        config=_TEST_CONFIG, reconstruction_tol=0.01,
    )
    text = "\n".join(lines)
    assert "run_x" in text and "2025-12-24T05:15:00Z" in text
    assert "REPLICATION MISMATCH" in text          # the 1d/high_bear failure, loud
    assert "momentum" in text and "0.25" in text   # the attribution delta
    assert "control family absent from all strata" in text
    assert "diagnostic" in text                     # remediation-is-human footer


def test_render_report_control_breach_escalates():
    rows, replication = _fixture_rows_and_replication()
    breach = dataclasses.replace(
        rows[1], family="control", n_features_zeroed=1, flag=_FLAG_CONTROL_BREACH
    )
    lines = render_report(
        weight_version="run_x", oos_start="ts", families=["control", "momentum"],
        rows=[*rows, breach], replication=replication, config=_TEST_CONFIG,
        reconstruction_tol=0.01,
    )
    text = "\n".join(lines)
    assert "GOVERNANCE BREACH" in text


def test_record_manifest_success_shape(tmp_path):
    rows, replication = _fixture_rows_and_replication()
    path = record_manifest(
        manifest_dir=tmp_path, weight_version="run_x", oos_start="ts",
        families=["control", "momentum"], rows=rows, replication=replication,
    )
    assert path.name == "ensemble_ablation__run_x.json"  # scope_suffix pattern
    data = json.loads(path.read_text())
    # replication mismatch recorded as a warning -> status 'partial', not 'success'
    assert data["status"] == "partial"
    assert data["inputs"]["weight_version"] == "run_x"
    assert data["outputs"]["ensemble_ablation_attribution"]["rows_total"] == len(rows)
    assert any("REPLICATION MISMATCH" in w for w in data["warnings"])


def test_record_manifest_clean_run_is_success(tmp_path):
    rows, _ = _fixture_rows_and_replication()
    replication = [ReplicationRecord(tf="5m", regime="low_bull", n_bars=10,
                                     n_compared=10, norm_max_diff=0.0, ok=True)]
    path = record_manifest(
        manifest_dir=tmp_path, weight_version="run_y", oos_start="ts",
        families=["momentum"], rows=rows, replication=replication,
    )
    data = json.loads(path.read_text())
    assert data["status"] == "success"


def test_record_manifest_error_run_is_failed(tmp_path):
    path = record_manifest(
        manifest_dir=tmp_path, weight_version="run_z", oos_start="ts",
        families=[], rows=[], replication=[], error="boom",
    )
    data = json.loads(path.read_text())
    assert data["status"] == "failed"
    assert "boom" in data["errors"]
```

Also add `import dataclasses` to the test file's import block at the top (below `import sys`).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/unit/test_ensemble_ablation.py -v`
Expected: FAIL at collection with `ImportError: cannot import name 'ReplicationRecord' from 'ops_ensemble_ablation'`

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/ops/alpha/ops_ensemble_ablation.py`:

```python
# ---------------------------------------------------------------------------
# Report rendering + manifest recording
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ReplicationRecord:
    """Per-stratum baseline reconstruction check result (see reconstruction_check)."""

    tf: str
    regime: str
    n_bars: int
    n_compared: int
    norm_max_diff: float | None
    ok: bool


def _fmt(value: Any, digits: int = 4) -> str:
    """Uniform markdown cell formatting: '-' for None, fixed digits for floats."""
    if value is None:
        return "-"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def render_report(
    weight_version: str,
    oos_start: Any,
    families: list[str],
    rows: list[AttributionRow],
    replication: list[ReplicationRecord],
    config: AblationConfig,
    reconstruction_tol: float,
) -> list[str]:
    """Render the full markdown report as a list of lines (caller prints).

    Sections: header/config, replication check, per-(tf, regime, scale)
    attribution tables (families sorted by delta_ic descending -- biggest marginal
    contributors first), per-family cross-strata summary, control-family verdict.
    This report is diagnostic; remediation decisions are human/operator (EIC-05
    convention).
    """
    lines: list[str] = []
    lines.append("## Ensemble Ablation Report (todo 084, leave-one-family-out)")
    lines.append("")
    lines.append(f"- weight_version: `{weight_version}`")
    lines.append(f"- OOS window: `bar_ts >= {oos_start}` (alpha.validation.oos_start)")
    lines.append(f"- families swept: {', '.join(families)}")
    lines.append(
        f"- gates: min_reliable_n={config.min_reliable_n}, "
        f"subsample_min_stride={config.subsample_min_stride}, "
        f"fdr_alpha={config.fdr_alpha}, reconstruction_tol={reconstruction_tol}"
    )
    lines.append(
        "- delta_ic = ic_baseline - ic_ablated: positive means removing the family "
        "REDUCED OOS IC (the family was contributing). diff_p is conservative under "
        "the arms' positive dependence; bh_p is one corpus-wide BH-FDR pass."
    )

    # --- Section 1: replication check ---------------------------------------
    lines.append("")
    lines.append("### Section 1: Baseline replication check (recomputed vs stored ensemble_alpha)")
    lines.append("")
    mismatches = [r for r in replication if not r.ok]
    if mismatches:
        lines.append(
            "> **REPLICATION MISMATCH** in "
            f"{len(mismatches)}/{len(replication)} strata: the recomputed baseline "
            "does not match stored ensemble_alpha.alpha_score. Weights/regime labels "
            "have likely drifted since ensemble_trainer ran (or the ablation's "
            "replication is buggy). Attribution for flagged strata is UNTRUSTWORTHY; "
            "re-run ensemble_trainer for this weight_version, then re-run this report."
        )
        lines.append("")
    lines.append("| tf | regime | n_bars | n_compared | norm_max_diff | verdict |")
    lines.append("|---|---|---|---|---|---|")
    for r in replication:
        verdict = "ok" if r.ok else "REPLICATION MISMATCH"
        if r.n_compared == 0:
            verdict = "skipped (no stored overlap)"
        lines.append(
            f"| {r.tf} | {r.regime} | {r.n_bars} | {r.n_compared} | "
            f"{_fmt(r.norm_max_diff, 6)} | {verdict} |"
        )

    # --- Section 2: per-stratum attribution ---------------------------------
    lines.append("")
    lines.append("### Section 2: Marginal attribution per (tf, regime, scale)")
    untrusted = {(r.tf, r.regime) for r in mismatches}
    strata = sorted({(r.tf, r.regime, r.scale) for r in rows})
    for tf, regime, scale in strata:
        cell_rows = [r for r in rows if (r.tf, r.regime, r.scale) == (tf, regime, scale)]
        baseline_rows = [r for r in cell_rows if r.family == _BASELINE_ARM]
        header_suffix = " [UNTRUSTED: replication mismatch]" if (tf, regime) in untrusted else ""
        lines.append("")
        lines.append(f"#### {tf} / {regime} / {scale}{header_suffix}")
        lines.append("")
        if baseline_rows and baseline_rows[0].flag == _FLAG_BASELINE_UNMEASURABLE:
            lines.append(f"> {_FLAG_BASELINE_UNMEASURABLE}")
            continue
        family_rows = sorted(
            (r for r in cell_rows if r.family != _BASELINE_ARM),
            key=lambda r: (r.delta_ic is None, -(r.delta_ic or 0.0)),
        )
        b = baseline_rows[0]
        lines.append(
            f"baseline: ic={_fmt(b.ic_baseline)} "
            f"[{_fmt(b.ci_lower)}, {_fmt(b.ci_upper)}], n={b.n_obs}"
        )
        lines.append("")
        lines.append(
            "| family | n_feat | weight_mass | ic_ablated | delta_ic | diff_p | bh_p "
            "| sig | flag |"
        )
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for r in family_rows:
            lines.append(
                f"| {r.family} | {r.n_features_zeroed} | {_fmt(r.weight_mass_zeroed)} "
                f"| {_fmt(r.ic_ablated)} | {_fmt(r.delta_ic)} | {_fmt(r.diff_p, 6)} "
                f"| {_fmt(r.bh_adjusted_p, 6)} | {_fmt(r.delta_passes_fdr)} | {r.flag} |"
            )

    # --- Section 3: per-family cross-strata summary --------------------------
    lines.append("")
    lines.append("### Section 3: Per-family summary across all measurable strata")
    lines.append("")
    lines.append(
        "| family | strata present | mean delta_ic | max delta_ic | fdr-significant cells |"
    )
    lines.append("|---|---|---|---|---|")
    for family in families:
        f_rows = [r for r in rows if r.family == family and r.delta_ic is not None]
        n_sig = sum(1 for r in f_rows if r.delta_passes_fdr)
        mean_d = float(np.mean([r.delta_ic for r in f_rows])) if f_rows else None
        max_d = float(np.max([r.delta_ic for r in f_rows])) if f_rows else None
        lines.append(
            f"| {family} | {len(f_rows)} | {_fmt(mean_d)} | {_fmt(max_d)} | {n_sig} |"
        )

    # --- Section 4: control-family verdict -----------------------------------
    lines.append("")
    lines.append("### Section 4: Control (canary) family verdict")
    lines.append("")
    control_weighted = [
        r for r in rows if r.family == _CONTROL_FAMILY and r.n_features_zeroed > 0
    ]
    if not control_weighted:
        lines.append(
            "control family absent from all strata (expected: "
            "feature_status_at_eval='active' excludes canaries from eligibility). "
            "The absent-family no-op doubles as the ablation-mechanism sanity check."
        )
    else:
        lines.append(
            f"> **GOVERNANCE BREACH**: control family carries weight in "
            f"{len(control_weighted)} (stratum, scale) cells -- canaries must never "
            "be ensemble-eligible. Investigate ensemble_trainer eligibility before "
            "trusting any other row of this report."
        )
        sig_control = [r for r in control_weighted if r.delta_passes_fdr]
        if sig_control:
            lines.append(
                f"> **ABLATION MECHANISM SUSPECT**: zeroing control moved IC with "
                f"FDR significance in {len(sig_control)} cells -- a canary family "
                "cannot carry real marginal IC; suspect the ablation code, not the model."
            )

    lines.append("")
    lines.append("---")
    lines.append("This report is diagnostic; remediation decisions are human/operator.")
    return lines


def record_manifest(
    manifest_dir: Path,
    weight_version: str,
    oos_start: Any,
    families: list[str],
    rows: list[AttributionRow],
    replication: list[ReplicationRecord],
    error: str | None = None,
) -> Path:
    """Write the CorpusManifest run record -- the todo's 'results go in the run
    manifest' target. step_name 'ensemble_ablation', scope_suffix=weight_version
    (the ensemble_trainer pattern: champion + challenger runs coexist and must not
    stomp each other's manifest file). Replication mismatches and control-family
    breaches become manifest warnings (status 'partial'); a hard failure becomes a
    manifest error (status 'failed'). Nothing downstream gates on this manifest
    today; it is the durable, machine-readable record a future epoch-over-epoch
    comparison can diff.
    """
    manifest = CorpusManifest("ensemble_ablation", manifest_dir)
    manifest.scope_suffix = weight_version
    manifest.set_inputs(
        weight_version=weight_version,
        oos_start=str(oos_start),
        families=families,
        n_strata=len({(r.tf, r.regime) for r in rows}),
    )
    if rows:
        rows_by_tf: dict[str, int] = {}
        for r in rows:
            rows_by_tf[r.tf] = rows_by_tf.get(r.tf, 0) + 1
        manifest.add_output(
            table_name="ensemble_ablation_attribution",
            rows_total=len(rows),
            rows_by_tf=rows_by_tf,
        )
    for r in replication:
        if not r.ok:
            manifest.add_warning(
                f"REPLICATION MISMATCH {r.tf}/{r.regime}: norm_max_diff="
                f"{r.norm_max_diff} over {r.n_compared} bars"
            )
    n_control_weighted = len(
        {(r.tf, r.regime) for r in rows if r.family == _CONTROL_FAMILY and r.n_features_zeroed > 0}
    )
    if n_control_weighted:
        manifest.add_warning(
            f"GOVERNANCE BREACH: control family carries weight in "
            f"{n_control_weighted} strata"
        )
    if error is not None:
        manifest.add_error(error)
    else:
        manifest.mark_success()
    return manifest.write()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/unit/test_ensemble_ablation.py -v`
Expected: 33 passed

Note: `test_record_manifest_error_run_is_failed` exercises `CorpusManifest.write()` with zero outputs, which appends a "No outputs recorded" warning; status stays `failed` because `add_error` was called (add_warning only upgrades `in_progress` to `partial`). If the assertion on `data["status"]` fails, check ordering of `add_error` vs `write`, not the test.

- [ ] **Step 5: Commit**

```bash
git add scripts/ops/alpha/ops_ensemble_ablation.py tests/unit/test_ensemble_ablation.py
git commit -m "feat(ablation): markdown report renderer and manifest recorder"
```

---

### Task 7: `main()` wiring, CLI, prerequisite gates, full verification

**Files:**
- Modify: `scripts/ops/alpha/ops_ensemble_ablation.py` (append)
- Test: full suite + lint (no new unit tests: `main()` is DB I/O glue; every kernel it calls is covered, matching `ops_ensemble_weight_compare.py`'s convention of testing pure helpers only)

**Interfaces:**
- Consumes: everything from Tasks 1-6; `CorpusManifest.ensure_success_for`; `load_apr_dict_async`; `Settings`.
- Produces: `async def main() -> int` and the `if __name__ == "__main__":` entrypoint. Exit code always 0.

- [ ] **Step 1: Write the implementation**

Append to `scripts/ops/alpha/ops_ensemble_ablation.py`:

```python
# ---------------------------------------------------------------------------
# Entrypoint (all DB I/O lives here; kernels above are pure)
# ---------------------------------------------------------------------------


def _abort(message: str, manifest_dir: Path, weight_version: str, oos_start: Any) -> int:
    """Loud diagnostic abort: print a FAILED header, record a failed manifest,
    return 0 (exit code always 0 -- EIC-05 convention; the FAILURE signal is the
    printed banner + manifest status, not the exit code)."""
    print(f"## Ensemble Ablation Report\n\nFAILED: {message}")
    try:
        record_manifest(
            manifest_dir=manifest_dir, weight_version=weight_version,
            oos_start=oos_start, families=[], rows=[], replication=[], error=message,
        )
    except Exception as error:
        print(f"(manifest write also failed: {error})")
    return 0


async def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Leave-one-family-out ensemble ablation report (todo 084)"
    )
    parser.add_argument(
        "--weight-version",
        default=None,
        help=(
            "Weight variant to ablate; defaults to the champion "
            "(alpha.ensemble.weight_version APR value)"
        ),
    )
    parser.add_argument(
        "--reconstruction-tol",
        type=float,
        default=_DEFAULT_RECONSTRUCTION_TOL,
        help=(
            "Max |recomputed - stored| / std(stored) before flagging REPLICATION "
            f"MISMATCH (default {_DEFAULT_RECONSTRUCTION_TOL}; see module constant "
            "comment for provenance)"
        ),
    )
    parser.add_argument(
        "--manifest-dir",
        type=Path,
        default=CorpusManifest.DEFAULT_MANIFEST_DIR,
        help="Corpus manifest directory (default: the pipeline-shared location)",
    )
    args = parser.parse_args()

    settings = Settings()
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn=dsn)
    try:
        async with pool.acquire() as conn:
            apr_cfg = await _load_apr(conn)
            config = AblationConfig.from_apr(apr_cfg)
            weight_version = (
                args.weight_version
                if args.weight_version
                else _cfg(apr_cfg, "alpha.ensemble.weight_version", "v1")
            )

            # OOS boundary: crash-loud read (ensemble_ic_engine CR-01 pattern) --
            # a missing oos_start must never silently measure the full corpus.
            try:
                oos_start = await conn.fetchval(
                    "SELECT config_value::timestamptz FROM config_state "
                    "WHERE config_key = 'alpha.validation.oos_start'"
                )
            except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError) as error:
                return _abort(
                    f"alpha.validation.oos_start is not a valid timestamp: {error}",
                    args.manifest_dir, weight_version, None,
                )
            if oos_start is None:
                return _abort(
                    "alpha.validation.oos_start is not set in config_state; an OOS "
                    "ablation without a boundary would silently include training data.",
                    args.manifest_dir, weight_version, None,
                )

            # Trust gate on the weight source: nonzero ensemble_weights rows are
            # not evidence the trainer run that wrote them finished
            # (CorpusManifest.ensure_success_for closes exactly this gap).
            try:
                CorpusManifest.ensure_success_for(
                    args.manifest_dir, "ensemble_trainer",
                    scope_suffix=weight_version, weight_version=weight_version,
                )
            except RuntimeError as error:
                return _abort(
                    f"ensemble_trainer prerequisite not satisfied: {error}",
                    args.manifest_dir, weight_version, oos_start,
                )

            family_rows = await conn.fetch(_FAMILIES_SQL)
            families = [r["group_name"] for r in family_rows]
            strata = await conn.fetch(_STRATA_SQL, weight_version)
            if not strata:
                return _abort(
                    f"no ensemble_weights strata for weight_version={weight_version!r}",
                    args.manifest_dir, weight_version, oos_start,
                )

            all_rows: list[AttributionRow] = []
            replication: list[ReplicationRecord] = []
            for stratum in strata:
                tf, regime = stratum["tf"], stratum["regime"]
                weight_recs = await conn.fetch(_WEIGHTS_SQL, weight_version, tf, regime)
                if not weight_recs:
                    continue
                feature_names = [r["feature_name"] for r in weight_recs]
                group_names = [r["group_name"] for r in weight_recs]
                signed_weights = signed_weights_from_rows(
                    np.array([float(r["weight"]) for r in weight_recs]),
                    np.array([float(r["ic_sharpe"]) for r in weight_recs]),
                )

                fv_rows = await conn.fetch(
                    build_stratum_fetch_sql(feature_names),
                    tf, regime, weight_version, oos_start,
                )
                if len(fv_rows) < 2:
                    replication.append(
                        ReplicationRecord(tf=tf, regime=regime, n_bars=len(fv_rows),
                                          n_compared=0, norm_max_diff=None, ok=True)
                    )
                    continue

                bar_ts_arr, X, gated_returns, stored_alpha = prepare_stratum_arrays(
                    fv_rows, feature_names
                )
                unique_ts, bar_idx = np.unique(bar_ts_arr, return_inverse=True)
                n_bars = len(unique_ts)

                baseline_scores = X @ signed_weights
                n_compared, norm_max_diff, ok = reconstruction_check(
                    baseline_scores, stored_alpha, args.reconstruction_tol
                )
                replication.append(
                    ReplicationRecord(tf=tf, regime=regime, n_bars=len(fv_rows),
                                      n_compared=n_compared,
                                      norm_max_diff=norm_max_diff, ok=ok)
                )

                pooled_returns_by_scale = {
                    scale: pool_means_by_bar(bar_idx, n_bars, gated_returns[scale])
                    for scale in _SCALES
                }
                all_rows.extend(
                    compute_stratum_attribution(
                        tf=tf, regime=regime, families=families,
                        group_names=group_names, signed_weights=signed_weights,
                        X=X, bar_idx=bar_idx, n_bars=n_bars,
                        pooled_returns_by_scale=pooled_returns_by_scale,
                        config=config,
                    )
                )

        all_rows = apply_delta_fdr(all_rows, config.fdr_alpha)
        report_lines = render_report(
            weight_version=weight_version, oos_start=oos_start, families=families,
            rows=all_rows, replication=replication, config=config,
            reconstruction_tol=args.reconstruction_tol,
        )
        print("\n".join(report_lines))
        manifest_path = record_manifest(
            manifest_dir=args.manifest_dir, weight_version=weight_version,
            oos_start=oos_start, families=families, rows=all_rows,
            replication=replication,
        )
        print(f"\nmanifest: {manifest_path}")
        return 0
    finally:
        await pool.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 2: Smoke-check the CLI surface (no DB required)**

Run: `.venv/bin/python scripts/ops/alpha/ops_ensemble_ablation.py --help`
Expected: argparse usage text listing `--weight-version`, `--reconstruction-tol`, `--manifest-dir`; exit 0.

- [ ] **Step 3: Lint and format**

Run: `.venv/bin/ruff check scripts/ops/alpha/ops_ensemble_ablation.py tests/unit/test_ensemble_ablation.py --fix && .venv/bin/black scripts/ops/alpha/ops_ensemble_ablation.py tests/unit/test_ensemble_ablation.py`
Expected: no remaining ruff errors; black reports files unchanged or reformatted.
If ruff flags the module-level imports below the `sys.path.insert` line (E402), add `# noqa: E402` to those imports exactly as sibling ops scripts do; do not reorder the imports above the path insert.

- [ ] **Step 4: Run the full unit suite**

Run: `.venv/bin/pytest tests/unit/ -q`
Expected: all green except the pre-existing, unrelated `test_no_smooth_or_backward_in_factory` failure (known, documented in project memory). Zero NEW failures.

- [ ] **Step 5: Commit**

```bash
git add scripts/ops/alpha/ops_ensemble_ablation.py tests/unit/test_ensemble_ablation.py
git commit -m "feat(ablation): main wiring, CLI, prerequisite gates for todo 084"
```

- [ ] **Step 6: Close out todo 084**

```bash
git mv .planning/todos/pending/084-ablation-protocol-ensemble-degradation.md .planning/todos/completed/084-ablation-protocol-ensemble-degradation.md
grep -rn "084" docs/foundation docs/research docs/intelligence .planning/todos/PRIORITIES.md
```

Update every hit that treats 084 as open (PRIORITIES.md ranking entry; the G-2 bullet in `docs/research/fable-2026-07-07-renaissance-layer-refinements.md` needs no edit, it is a historical proposal record, but if `docs/research/measurement-ic-engine.md` names 084 as the 0a precursor, annotate it as shipped with the script path). State corrected facts plainly, no review-narrative annotations. Then:

```bash
git add -A .planning/todos docs
git commit -m "docs(todo-084): close ablation protocol todo, shipped as ops_ensemble_ablation.py"
```

---

## Statistical Correctness Checklist (verified during plan self-review; executor re-verifies at the end)

- [x] **Executable returns filter in every `forward_returns` read:** the script has exactly one `forward_returns` touchpoint, `build_stratum_fetch_sql`, which hardcodes `fr.return_type = 'executable_open_to_open'` in the JOIN condition and is pinned by `test_fetch_sql_statistical_invariants`.
- [x] **OOS boundary respected:** single fetch path uses `fv.bar_ts >= $4` with `$4 = alpha.validation.oos_start` (crash-loud when unset); `>=` matches `ops_oos_holdout_eval._oos_mask` and complements the training side's `<`. Pinned by test.
- [x] **Baseline and ablated arms share one code path:** both are `X @ weights_variant -> pool_means_by_bar -> compute_arm_ic`; the baseline is `zero_family`-free but structurally identical (`compute_stratum_attribution` builds `pooled_by_arm` uniformly). Pinned by `test_compute_arm_ic_identical_code_path_for_identical_inputs` plus the control no-op semantics.
- [x] **IC math reused from `ic_math.py`:** `compute_ic_vectorized`, `_fisher_z_ci`, `fisher_z_difference_p`, `apply_bh_fdr`, `_nan_to_none`. No `scipy.stats.spearmanr`, no hand-rolled correlation, no IC without a CI (ArmIC always carries the Fisher-z CI).
- [x] **`complete_*` gating applied consistently:** `apply_complete_gate` censors per symbol-row BEFORE pooling (ic_engine's `complete AND isfinite` convention); pooled NaN propagates into `compute_arm_ic`'s valid mask. Pinned by `test_apply_complete_gate_nans_incomplete_and_copies` and `test_prepare_stratum_arrays_trainer_conventions`.
- [x] **Trainer formula replicated, not reinvented:** `X` build (`NULL -> 0.0`, float32), `market_regimes` stratum join, `ORDER BY bar_ts, symbol`, and the scoring matmul all mirror `ensemble_trainer.py` lines 792-826/962-963; the reconstruction check against stored `ensemble_alpha` converts "replicated" from an assumption into a per-run measurement.
- [x] **Subsampling/independence:** `stride = max(subsample_min_stride, lookahead_bars)` on the pooled series, identical to `ensemble_ic_engine` lines 770-773; `min_reliable_n` gate after the finite-pair mask. 1d strata will mostly report BASELINE UNMEASURABLE on a ~6.5-month OOS window (structurally underpowered, same as the EIC finding); that is honest output, not a bug.
- [x] **Degenerate arms never fake IC=0.0:** `_DEGENERATE_STD` guard returns None -> DEGENERATE flag.
- [x] **Multiplicity handled:** one corpus-wide `apply_bh_fdr` pass over all delta p-values, informational columns `bh_adjusted_p`/`delta_passes_fdr`.
- [x] **Sign convention risk bounded:** `sign(ic_sharpe)` inference is empirically verified by the reconstruction check each run; a wrong sign produces an O(100%) reconstruction distortion, far above the 1% tolerance.

## Self-review notes (issues found and fixed inline)

1. Task 4's Interfaces block originally described a 5-tuple return for `prepare_stratum_arrays`; the implementation and tests use the 4-tuple `(bar_ts_arr, X, gated_returns_by_scale, stored_alpha)` with `bar_idx`/`n_bars` derived by the caller. The Interfaces block now states the 4-item contract explicitly.
2. Pooling was originally drafted as 12 calls to `_aggregate_pooled_series` per stratum (dict-per-row rebuild per arm); replaced with the vectorized `pool_means_by_bar` pinned to the oracle by an equivalence test, keeping DRY-by-verification instead of DRY-by-import while removing the per-arm dict churn.
3. `fisher_z_difference_p` returns NaN for n <= 3; `compute_stratum_attribution` maps NaN to None before it reaches the report/FDR pass (BH must never receive NaN).
4. Spec coverage against todo 084's proposal text: leave-one-family-out over `group_name` (yes, all 11, runtime-derived), zero weights + recompute alpha on OOS + re-measure (yes, Tasks 4-5), marginal-attribution table per stratum (yes, Section 2 + Section 3 summary), no new tables with results in the run manifest (yes, `record_manifest`; the only artifacts are stdout markdown and the manifest JSON), a script over `ensemble_weights`/`feature_vectors`/`forward_returns` (yes, plus the deliberate `ensemble_alpha` LEFT JOIN for the replication check and `market_regimes` for the stratum join, both required for correctness), EIC-05 conventions (asyncpg via Settings, markdown stdout, exit 0, `error` naming: all matched).
