# Phase 145: StratificationDimension Formalization - Research

**Researched:** 2026-08-06
**Domain:** Backend governance/contract design (Python `Protocol`/ABC + statistical gate
mechanisms) for a regime-conditioning layer, in a solo-operator quant research codebase
(no live production consumer changes)
**Confidence:** HIGH (every load-bearing claim below is grep/psql-verified against live code and
the live DB, not inferred from docs alone)

## Summary

This phase writes real Python code — a `StratificationDimension` `Protocol`/ABC, a BH-FDR
correction step, an effective-N-from-transitions estimator, and an acausal-placebo registration
gate — but it does **not** get to write to the live `concept_registry` schema. Direct psql
verification confirms `concept_registry.domain` still CHECK-constrains to
`('feature', 'ensemble_strategy')` only, and `concept_gate_stack` (the table `regime_model`'s
three-stage cascade needs, per the design doc) does not exist in the live schema at all — both
match CONTEXT.md's D-07 exactly. This has a concrete consequence the planner must design around:
**the `volatility_pct` pilot cannot write a real `concept_transition_log` row** (hard FK to
`concept_registry.concept_id`, which cannot hold a `domain='regime_model'` row yet). The pilot's
output must be a standalone artifact (JSON, doc, or a scratch/staging table) shaped like the
eventual `concept_transition_log` row, explicitly marked "pending Phase 170 backfill" — not a
live registry write.

The good news: almost everything else this phase needs is already-proven, reusable code, not new
design. BH-FDR correction is a one-line call to the existing `apply_bh_fdr()` helper
(`src/intelligence/statistics/ic_math.py`), already used by three other call sites — no new
dependency, no hand-rolled multiple-comparisons math. The causal-expanding-rank pattern D-06's
`volatility_pct` pilot needs already exists twice (`src/intelligence/regime_signals/causal_rank.py`'s
shared `causal_expanding_rank()`, and `breadth_vol.py`'s `_compute_vix_pct_rank()` — the exact
"realized-vol z-score -> causal rank -> tier bucket" shape to adapt to per-symbol grain). The
effective-N-from-transitions estimator has two candidate implementations already in the codebase
to mirror: `regime_writer.py`'s `_smooth_states()` (which already tracks the min-hold-bars
smoothing D-04 blames for autocorrelation, and from which "number of transitions" is one
`np.diff() != 0` call away) and `ic_math.py`'s `_hac_sharpe_nd()` (the Newey-West variance-inflation
factor already computed for IC Sharpe — mathematically the same "effective sample size shrinks
under positive autocorrelation" idea, just for a rolling-window IC series instead of a discrete
regime-state sequence). The acausal-placebo mechanism D-05 generalizes already exists as a running,
tested, production gate (`scripts/ops/alpha/ops_canary_integrity_assert.py` +
`feature_factory.py`'s `_canary_acausal_placebo()`) — read in full below, this is the pattern to
extend into a per-provider registration check, not reinvent.

Two real tensions the planner needs to resolve explicitly, not silently default on: (1) CLAUDE.md's
APR mandate says any new hard-coded numeric threshold is an architecture violation requiring an
immediate migration — but D-07 explicitly defers the `alpha.regime_stratification.fdr_alpha`/
`.max_correlation` APR migration until after Phase 170. (2) the `StratificationDimension` contract
must stay compatible with `ic_engine.py`'s existing two-axis hand-wiring (`mr_dict`/
`_resolve_regime_scope`/`_build_regime_passes`) without this phase actually touching
`ic_engine.py` — the planner needs a concrete compatibility check (e.g. a test asserting the
contract's `compute()`/`score()` signature can produce what `_build_regime_passes` already
consumes), not just a design aspiration.

**Primary recommendation:** build the Protocol/ABC and all three gate mechanisms as pure,
DB-independent Python functions/classes under `src/intelligence/` (mirroring
`src/intelligence/plugins/base.py`'s `PatternPlugin` Protocol shape and
`src/intelligence/regime_signals/`'s existing per-symbol-vs-cross-sectional module split),
reuse `apply_bh_fdr`/`causal_expanding_rank`/`_smooth_states`-style transition-counting outright,
run the `volatility_pct` pilot against 3-5 real `market_data_ohlcv_tradeable`-sourced symbols with
its gate results written to a standalone artifact (not `concept_registry`), and defer every actual
schema/migration write to the already-scheduled Phase 170 follow-up.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| `StratificationDimension` Protocol/ABC definition | Ring 1 (`src/intelligence/`) | — | Domain vocabulary (regime, stratum, dimension) — not portable Ring 0 infra per CLAUDE.md's Ring rule |
| `volatility_pct` provider implementation (pilot) | Ring 1 (`src/intelligence/regime_signals/` or a new sibling module) | — | Mirrors existing `breadth_vol.py`/`curve_credit.py`/`fx_dollar_carry.py` per-dimension module pattern |
| BH-FDR correction across candidate pool | Ring 1 (reuse `src/intelligence/statistics/ic_math.py`) | — | Pure statistical function, already lives in the shared statistics module, not domain-specific |
| Effective-N-from-transitions estimator | Ring 1 (new function, likely `src/intelligence/statistics/` or co-located with the gate cascade) | — | Statistical primitive; candidate home is `ic_math.py` alongside `_hac_sharpe_nd` (same "autocorrelation shrinks effective N" family) |
| Acausal-placebo registration gate | Ring 1/Ring 2 boundary — pure check function in Ring 1, invocation as a standalone script or pytest fixture in Ring 2 (`scripts/ops/` or `tests/unit/`) | — | Mirrors `ops_canary_integrity_assert.py`'s existing split: pure `evaluate()` function + a thin script/CLI wrapper |
| `concept_registry` row-grain encoding (Option B) | Database schema (deferred) | — | No code owns this in Phase 145 — schema write is explicitly deferred to Phase 170 (D-07); this phase only documents/ratifies the convention |
| Consumer compatibility check vs. `ic_engine.py` | Ring 2 (`services/ic_engine.py`, read-only in this phase) | — | `ic_engine.py` is not modified this phase, but the contract shape must be validated against its existing `mr_dict`/`_resolve_regime_scope` call sites (a test, not a code change) |

## Project Constraints (from CLAUDE.md)

These are binding on the plan; flag any conflict explicitly rather than silently defaulting.

- **Ring rule:** new Protocol/ABC + gate code belongs in `src/intelligence/` (Ring 1, domain
  vocabulary — "regime," "stratification dimension" are domain terms). It must not import from
  `services/` (Ring 2). `src/core/`/`src/observability/` (Ring 0) must stay free of this phase's
  domain vocabulary.
- **APR mandate vs. D-07 tension (real conflict, not a formality):** CLAUDE.md requires "any
  numeric threshold, weight, period, or count encountered in `src/` or `services/` that is not
  APR-backed MUST be migrated in the same session" (migrate-as-you-go). D-07 explicitly defers
  the `alpha.regime_stratification.fdr_alpha`/`.max_correlation` APR migration until after Phase
  170. **The planner must resolve this explicitly** — likely resolution: treat these as
  research-pilot-scoped Python constants/dataclass defaults with an inline comment citing D-07
  and the Phase 170 dependency, not a bare magic number (the APR-exempt list's closest analog is
  "statistical concept definitions," but that doesn't cleanly cover a tunable FDR alpha or
  correlation threshold — this is a genuine, temporary, user-ratified exception to migrate-as-you-go,
  not an oversight, and should be documented as such in the code itself).
- **Never drop data that could contain signal:** every candidate-dimension test (pass or fail)
  must be logged somewhere durable even though it can't go into `concept_transition_log` yet (see
  Common Pitfalls below) — the standalone pilot-artifact requirement follows directly from this
  principle, not just from the FK constraint.
- **Silent wrong answers are worse than loud crashes:** the acausal-placebo gate (D-05) must
  hard-fail registration, not warn-and-continue, consistent with `ops_canary_integrity_assert.py`'s
  existing `CanaryIntegrityViolation` (raised, not logged-and-swallowed).
- **Naming:** any new module/function follows the existing `regime_signals/` naming style
  (`breadth_vol.py`, `curve_credit.py`, `fx_dollar_carry.py` — signal_type name as filename,
  `compute()`/`build_tiers()`/`PROB_KEYS` as the per-module public surface). A new
  `StratificationDimension`-conformant `volatility_pct.py` module should follow this convention
  if placed alongside the existing signal modules, or the planner may choose a new subpackage —
  either way, keep the existing modules' public-surface shape (`compute()`, `score()`) as the
  contract to match.
- **Testing:** `.venv/bin/pytest tests/unit/ -v` must stay green; `ruff check . --fix` and
  `black .` before commit.

## Standard Stack

### Core

| Library | Version (verified) | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `statsmodels` | `>=0.14.6` (pyproject.toml) / `>=0.14.4` (requirements.txt) — both already installed and importable in `.venv` [VERIFIED: local `.venv` import check] | BH-FDR (`multipletests`, `method="fdr_bh"`) for D-03 | Already the project's sole FDR-correction dependency, used identically by `ic_engine.py`, `ensemble_ic_engine.py`, `ops_oos_holdout_eval.py`, and now wrapped once in `src/intelligence/statistics/ic_math.py::apply_bh_fdr` — **reuse this wrapper, do not call `multipletests` directly a fourth time** |
| `scipy` | `>=1.15.0` (requirements.txt), already installed [VERIFIED: local `.venv` import check] | `scipy.stats` already used for binomial tail bounds (`ops_canary_integrity_assert.py`) and Fisher-z CI math (`ic_math.py`) | Standard project dependency; no new usage needed beyond what's already imported for this phase's scope |
| `numpy`/`pandas` | already project-wide standard | Transition counting, causal expanding rank, percentile bucketing | No new dependency |

**No new package installs required for this phase.** Every statistical primitive needed
(BH-FDR, autocorrelation-adjusted variance, causal ranking, binomial tail bounds) is already a
project dependency with an existing, tested, reusable implementation.

### Supporting

None — this phase adds no new runtime dependency.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `ic_math.apply_bh_fdr` | Hand-rolled BH-FDR (sort p-values, apply `i/m * alpha` rule manually) | Explicitly rejected by CLAUDE.md's Ring 0 "no heavy deps" instinct doesn't apply here — `statsmodels` is already a project dependency, not a new one, so there is no dependency-weight argument for hand-rolling. Hand-rolling would also contradict this project's own established "don't duplicate the multipletests call a fourth time" pattern (`ic_math.py`'s own docstring explicitly names this as the reason the wrapper was extracted) |
| Transition-count effective-N | A full HAC/Newey-West-style continuous-time correction on the regime-state indicator series | Simpler transition-counting (runs in the smoothed state sequence) is the more direct proxy for "independent state visits" that D-04's own rationale asks for, and is trivially derived from `_smooth_states()`'s existing output. A full HAC treatment (mirroring `_hac_sharpe_nd`) is a reasonable **secondary/cross-check** approach worth citing as prior art, but transition-counting is cheaper and more interpretable for a regime-label sequence specifically (HAC's Bartlett-kernel weighting is designed for continuous return-like series, not discrete labels) |

## Package Legitimacy Audit

**Not applicable — this phase installs no new external packages.** `statsmodels` and `scipy` are
pre-existing project dependencies (verified importable in `.venv`); no `pip install` or
`requirements.txt`/`pyproject.toml` change is needed. The Package Legitimacy Gate protocol is
skipped per its own scope ("whenever this phase installs external packages").

## Architecture Patterns

### System Architecture Diagram

```
                         ┌─────────────────────────────────────────┐
                         │   StratificationDimension Protocol/ABC   │
                         │   (new, src/intelligence/, this phase)   │
                         │   name / grain / labels / causality_basis│
                         │   compute() -> labels   score() -> float │
                         └───────────────┬───────────────────────────┘
                                         │ implemented by
                    ┌────────────────────┼────────────────────────┐
                    │                    │                        │
         ┌──────────▼─────────┐ ┌────────▼──────────┐   ┌─────────▼──────────┐
         │ hmm_price_vol       │ │ cross_sectional_*  │   │ volatility_pct      │
         │ (EXISTING,          │ │ (EXISTING,          │   │ (NEW — this phase's │
         │  regime_writer.py,   │ │  cross_sectional_   │   │  ONLY built pilot,   │
         │  not modified this  │ │  regime_model.py,   │   │  D-06)               │
         │  phase — contract-   │ │  not modified this  │   │  causal expanding    │
         │  shape audit only)   │ │  phase — contract-   │   │  rank on a realized- │
         │                      │ │  shape audit only)   │   │  vol feature, per    │
         │                      │ │                      │   │  symbol              │
         └──────────┬──────────┘ └──────────┬───────────┘   └──────────┬──────────┘
                    │                        │                          │
                    └──────────┬─────────────┴──────────────┬───────────┘
                               │  candidate dimension enters  │
                               ▼   the 3-stage gate cascade    │
                  ┌─────────────────────────────────────────┐ │
                  │ Gate 0: structural redundancy pre-filter │ │
                  │  (free, no query — orthogonality vs.     │ │
                  │   incumbent's own observation dims)      │ │
                  └────────────────┬──────────────────────────┘
                                   ▼
                  ┌─────────────────────────────────────────┐
                  │ Gate 0.5 (NEW, D-05): acausal-placebo    │
                  │  registration check — generalizes        │
                  │  ops_canary_integrity_assert.py's         │
                  │  positive-control mechanism per-provider  │
                  └────────────────┬──────────────────────────┘
                                   ▼
                  ┌─────────────────────────────────────────┐
                  │ Gate 1: orthogonality study (Pearson/MI   │
                  │  vs. incumbents; alpha.regime_             │
                  │  stratification.max_correlation)          │
                  └────────────────┬──────────────────────────┘
                                   ▼
                  ┌─────────────────────────────────────────┐
                  │ Gate 2: substitution test (partial IC),   │
                  │  N > effective-N floor (NEW, D-04:        │
                  │  derived from regime-transition counts,   │
                  │  not raw bar count)                       │
                  └────────────────┬──────────────────────────┘
                                   ▼
                  ┌─────────────────────────────────────────┐
                  │ BH-FDR correction across the cumulative   │
                  │  candidate-dimension test history for     │
                  │  this regime_group (NEW, D-03 —            │
                  │  ic_math.apply_bh_fdr, one call per        │
                  │  regime_group's test history)              │
                  └────────────────┬──────────────────────────┘
                                   ▼
                  ┌─────────────────────────────────────────┐
                  │ PENDING artifact (NOT concept_registry —  │
                  │  domain CHECK doesn't admit 'regime_model' │
                  │  yet, concept_gate_stack table doesn't     │
                  │  exist yet). Shaped like the eventual      │
                  │  concept_transition_log row; backfilled     │
                  │  once Phase 170 lands.                      │
                  └─────────────────────────────────────────┘

    ─────────────────────────────────────────────────────────────────────────
    OUT OF SCOPE THIS PHASE (read-only compatibility check only):
    services/ic_engine.py's existing hand-wired routing —
      mr_dict (ts -> cross-sectional label) + _resolve_regime_scope() +
      _build_regime_passes() + _build_symbol_regime_class() (tag -> regime_group)
    ─────────────────────────────────────────────────────────────────────────
```

### Recommended Project Structure

```
src/intelligence/
├── stratification/                      # NEW package (or a single module — planner's call
│   │                                     # given the small scope: one Protocol + one pilot)
│   ├── __init__.py
│   ├── contract.py                      # StratificationDimension Protocol/ABC
│   ├── gates.py                         # structural pre-filter, orthogonality study,
│   │                                     # substitution test, effective-N estimator
│   ├── acausal_placebo_gate.py          # D-05 per-provider registration check (generalizes
│   │                                     # ops_canary_integrity_assert.py's mechanism)
│   └── fdr.py                           # thin wrapper around ic_math.apply_bh_fdr, scoped
│                                         # to "cumulative candidate history per regime_group"
├── regime_signals/                      # EXISTING — cross-sectional per-regime_group modules
│   ├── breadth_vol.py                   # pattern to mirror for volatility_pct's compute()/score()
│   ├── causal_rank.py                   # REUSE causal_expanding_rank() directly
│   ├── curve_credit.py
│   └── fx_dollar_carry.py
└── statistics/
    └── ic_math.py                       # REUSE apply_bh_fdr(), study _hac_sharpe_nd() as the
                                          # effective-N-via-autocorrelation prior art

tests/unit/
├── test_stratification_contract.py      # NEW — Protocol conformance tests
├── test_stratification_gates.py         # NEW — gate 0/1/2 pure-function tests
├── test_volatility_pct_pilot.py         # NEW — the D-06 pilot's provider implementation
└── test_acausal_placebo_registration.py # NEW — D-05 registration gate tests
```

### Pattern 1: Protocol shape — mirror `PatternPlugin`, not a from-scratch design

**What:** `src/intelligence/plugins/base.py` already has a `Protocol`-based plugin contract
(`IndicatorPlugin`, `PatternPlugin`) with `ClassVar`-typed identity/capability attributes plus
`compute_full()`/`compute_next()` methods, and a `validate_tier()` function that hard-crashes at
startup on a missing/misconfigured registration. This is **archived v2.x code** (the I1-I7
plugin system has no live consumer per `src/intelligence/CLAUDE.md`'s banner) — do not import
from it or extend it — but its *shape* is exactly the prior art the design doc
(`stratification-dimension-unification.md`) cites as validated internal precedent for "one
Protocol, many competing providers, hard-validated registration."

**When to use:** As the structural template for `StratificationDimension`'s own `Protocol`
definition — `ClassVar` fields for identity (`name`, `grain`, `labels`, `causality_basis`),
instance methods for behavior (`compute()`, `score()`), and a `validate_registration()`-style
hard-crash check playing the same role `validate_tier()` plays for I7 plugins (this is where
D-05's acausal-placebo gate hooks in, at registration time, not at every `compute()` call).

**Example:**
```python
# Source: src/intelligence/plugins/base.py (archived subsystem, pattern reference only)
class PatternPlugin(Protocol):
    name: ClassVar[str]
    outputs: ClassVar[set[str]]
    min_lookback: ClassVar[int]
    supports_incremental: ClassVar[bool]
    capability_tags: ClassVar[set[str]]
    inputs: ClassVar[list[InputSpec]]
    valid_asset_classes: ClassVar[frozenset[AssetClass]]
    regime_type: ClassVar[str]

    def compute_full(self, frames: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]: ...
    def compute_next(self, windows: dict[str, Any], *, state: dict | None = None) -> dict[str, Any]: ...

def validate_tier(self, names: list[str], tier: str) -> None:
    """Raise ValueError at startup if any name is not in the registry."""
    all_known = set(self.indicators) | set(self.patterns)
    unknown = [n for n in names if n not in all_known]
    if unknown:
        raise ValueError(f"Tier {tier} references unregistered plugin(s): {unknown}. ...")
```

### Pattern 2: `compute()`/`score()` split — mirror `breadth_vol.py`, not a new design

**What:** The existing `regime_signals/` modules already implement the exact
label-vs-continuous-score split the `StratificationDimension` contract needs:
`compute(ref_bars, params) -> (score_series, score_series)` returns continuous percentile-rank
values; `build_tiers(params)` separately maps those continuous values into named buckets. This is
directly the `score()`/`compute()`-returns-`labels` split the contract sketch specifies.

**When to use:** As the direct template for the `volatility_pct` pilot provider. Adapt
`_compute_vix_pct_rank()`'s "log-return realized vol -> rolling z-score -> `causal_expanding_rank()`"
shape from SPY-only to per-symbol (grain: `per_symbol`, not `cross_sectional`) — this can reuse an
already-computed causal volatility feature (`atr_z`, `garman_klass_vol_z`, or `yang_zhang_vol_z`,
all live columns in `feature_vectors`, all already causally z-scored) as the raw input to
`causal_expanding_rank()`, avoiding a second volatility computation from scratch.

**Example:**
```python
# Source: src/intelligence/regime_signals/breadth_vol.py (live, production module)
def compute(ref_bars: dict[str, pd.DataFrame], params: dict[str, Any]) -> tuple[pd.Series, pd.Series] | None:
    ...
    vix_pct = _compute_vix_pct_rank(spy_close, realized_vol_window, vix_z_window)
    breadth_pct = _causal_expanding_rank(breadth.reindex(vix_pct.index))
    return vix_pct, breadth_pct

def build_tiers(params: dict[str, Any]) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    vix_low = float(params.get("vix_low_pct", 0.33))
    vix_high = float(params.get("vix_high_pct", 0.67))
    return ([("low", vix_low), ("mid", vix_high), ("high", float("inf"))], ...)
```

### Pattern 3: Causal expanding rank — reuse directly, do not reimplement

**What:** `src/intelligence/regime_signals/causal_rank.py::causal_expanding_rank()` is already
the shared, tested, look-ahead-safe percentile-rank primitive every existing regime signal module
uses (extracted specifically to stop this exact bisect logic from being duplicated per module,
per its own docstring — including a documented history of two independent look-ahead bugs from
guessed absolute thresholds instead of this rank transform, todo 092).

**When to use:** `volatility_pct`'s `score()` implementation should call this function directly —
zero reason to write a new percentile-rank implementation for this phase.

**Example:**
```python
# Source: src/intelligence/regime_signals/causal_rank.py (live, shared by breadth_vol.py,
# curve_credit.py, fx_dollar_carry.py, commodity_momentum_ts.py)
def causal_expanding_rank(series: pd.Series) -> pd.Series:
    """Each position's rank is computed against all PRIOR valid values only."""
    sorted_window: list[float] = []
    causal_ranks: list[float] = []
    for val in series:
        if math.isnan(val):
            causal_ranks.append(float("nan")); continue
        if not sorted_window:
            bisect.insort(sorted_window, val); causal_ranks.append(1.0); continue
        left = bisect.bisect_left(sorted_window, val)
        right = bisect.bisect_right(sorted_window, val)
        rank = (left + right) / 2 / len(sorted_window)
        bisect.insort(sorted_window, val)
        causal_ranks.append(rank)
    return pd.Series(causal_ranks, index=series.index, dtype=float)
```

### Pattern 4: Effective-N from transitions — derive from `_smooth_states()`'s output

**What:** `services/regime_writer.py::_smooth_states()` (line ~400) is the live `min_hold_bars`
smoother D-04's rationale names as the cause of regime-state autocorrelation. Its output — a
smoothed integer state-label array — is exactly the input a transition-counting effective-N
estimator needs. "Number of transitions" is `int(np.count_nonzero(np.diff(smoothed_states) != 0))`;
"number of independent state-visits" (the effective-N proxy D-04 asks for) is transitions + 1 (one
run for the initial state, one more per transition).

**When to use:** As the direct input to the new effective-N-floor function this phase must write
(new code — no existing function computes this specific quantity, unlike BH-FDR and causal rank).
`_smooth_states()` itself should not be imported cross-module from `services/` into
`src/intelligence/` (Ring boundary — `services/` is Ring 2, `src/intelligence/` is Ring 1, and Ring
1 must not import from Ring 2); instead, either (a) accept an already-smoothed label array as this
function's input (decoupling it from `regime_writer.py` entirely — the caller supplies the
sequence), or (b) if the smoothing logic itself needs to be shared, extract `_smooth_states()`
into a Ring 0/Ring 1-appropriate shared location as a small preparatory step. Given this phase's
narrow pilot scope, **(a) is the lower-risk choice** — the effective-N function takes a label
sequence as a plain argument and has no dependency on where that sequence came from.

**Example (new code to write, not existing):**
```python
# Pattern to write, informed by services/regime_writer.py::_smooth_states (Ring 2, read for
# reference only — do not import) and src/intelligence/statistics/ic_math.py::_hac_sharpe_nd
# (Ring 1, same "autocorrelation shrinks effective N" family, importable if useful as a
# cross-check)
def effective_n_from_transitions(labels: np.ndarray) -> int:
    """Effective sample size proxy: count of independent state-visits (runs) in an
    already-smoothed regime-label sequence, not raw bar count. A run of 500
    consecutive 'trending_up' bars is one independent observation of that state,
    not 500."""
    if len(labels) == 0:
        return 0
    transitions = int(np.count_nonzero(np.diff(labels) != 0))
    return transitions + 1
```

### Pattern 5: Acausal-placebo mechanism — generalize, don't reinvent

**What:** `scripts/ops/alpha/ops_canary_integrity_assert.py` (read in full during this research)
is a live, production, tested gate with exactly the shape D-05 needs generalized:
1. A deliberately acausal "positive control" (`_canary_acausal_placebo` in `feature_factory.py`,
   pairs bar `i` with the return realized 2 bars in the future — the exact look-ahead shape the
   check exists to catch).
2. A pure `evaluate(rows, ...) -> report` function (no IO — fully unit-testable), separate from
   the SQL fetch and the script entry point.
3. Hard-halt via a custom exception (`CanaryIntegrityViolation`) when the positive control does
   **not** clear its significance gate — "this pipeline failed to detect a deliberate look-ahead
   leak, meaning it cannot be trusted to detect a real one either."

**When to use:** As the direct template for D-05's per-provider registration check. The natural
generalization: instead of one hardcoded feature column checked against `feature_ic_scores`, the
new gate takes a `StratificationDimension` provider, runs its `compute()` against a
deliberately-shuffled/future-shifted version of its own input, and asserts the resulting labels
carry **no** informative IC — the inverse assertion from the existing positive-control canary
(which asserts a deliberately-leaked feature IS detected), because a `StratificationDimension`
provider's `causality_basis` is a claim about itself, not a claim the measurement pipeline should
independently confirm can be caught. Mirror the pure-function-plus-thin-wrapper structure exactly.

**Example:**
```python
# Source: scripts/ops/alpha/ops_canary_integrity_assert.py (live, wired into
# scripts/ops/corpus/ops_corpus_pipeline_run.sh after the ic_engine step)
class CanaryIntegrityViolation(RuntimeError):
    """Raised on a hard-halt condition -- a proven broken measurement pipeline."""

def evaluate(rows, fdr_alpha=..., tail_alpha=..., pooled_tail_alpha=...) -> dict[str, Any]:
    """Pure evaluation function -- no IO, fully unit-testable without a DB."""
    ...
    if placebo_pooled_seen and not placebo_pooled_cleared:
        failures.append(
            "canary_acausal_placebo (positive control) did NOT clear the significance "
            "gate in the POOLED stratum -- this pipeline failed to detect a deliberate "
            "look-ahead leak, meaning it cannot be trusted to detect a real one either"
        )
    if failures:
        raise CanaryIntegrityViolation("; ".join(failures))
    return report
```

### Anti-Patterns to Avoid

- **Writing a real `concept_registry` row for `regime_model` this phase:** the live `domain`
  CHECK constraint will reject it (`ARRAY['feature'::text, 'ensemble_strategy'::text]`,
  verified live via `\d concept_registry`). Do not attempt a migration to widen this CHECK —
  D-07 explicitly defers that to Phase 170.
- **Hand-rolling BH-FDR:** `ic_math.apply_bh_fdr()` already exists, is already the third
  extraction of this exact "collect p-values → one `multipletests` call → scatter results back"
  shape (per its own docstring), and a fourth hand-rolled copy would directly contradict that
  extraction's stated purpose.
- **Reusing `concept_registry.group_name` to encode `regime_group`:** this column exists live
  (verified via `\d concept_registry`) but is already semantically owned by `domain='feature'`'s
  own taxonomy (`momentum`/`volume`/`volatility`/etc. — see `production/migrations/169_feature_registry.sql`'s
  CHECK vocabulary). D-01's Option B correctly encodes `regime_group` into `name`
  (`hmm_price_vol__equity`) precisely to avoid this collision — don't "discover" `group_name` as
  a shortcut during planning and repurpose it.
- **Modifying `services/ic_engine.py` in this phase:** CONTEXT.md's Integration Points note is
  explicit — confirm compatibility, don't rewire. The compatibility check should be a test (e.g.
  asserting the contract's output shape is consumable by `_build_regime_passes`'s existing
  input contract), not a code change to `ic_engine.py` itself.
- **Importing `services/regime_writer.py` functions into `src/intelligence/`:** Ring rule
  violation (Ring 2 → Ring 1 import direction is backwards). Reference `_smooth_states()`'s logic
  as a pattern, don't import it.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Multiple-comparisons correction across candidate-dimension tests (D-03) | A manual Benjamini-Hochberg implementation | `src/intelligence/statistics/ic_math.py::apply_bh_fdr()` | Already the project's single, tested, statsmodels-backed wrapper; three existing call sites already avoided duplicating this |
| Causal percentile ranking for `volatility_pct` (D-06) | A new bisect-based or pandas-`.rank()`-based rank function | `src/intelligence/regime_signals/causal_rank.py::causal_expanding_rank()` | Already look-ahead-safe, already the shared primitive for every existing regime signal module, already has a documented history of the exact bug class (todo 092) a from-scratch reimplementation risks reintroducing |
| Autocorrelation-adjusted variance/effective-N reasoning | An ad-hoc heuristic disconnected from the rest of the codebase's statistical conventions | Study `ic_math.py::_hac_sharpe_nd()`'s Newey-West Bartlett-kernel inflation-factor approach as the cross-check/second-opinion method, even if the primary D-04 estimator is transition-counting | Keeps the two "effective sample size shrinks under autocorrelation" corrections in this codebase (IC Sharpe's HAC correction, and this phase's regime-transition correction) conceptually consistent rather than inventing an unrelated third convention |
| A new "does this look ahead" check for a provider's `compute()` | A bespoke shuffle/permutation test for `StratificationDimension` specifically | Generalize `ops_canary_integrity_assert.py`'s existing acausal-placebo mechanism (`_canary_acausal_placebo`'s forward-shift construction + the pure-`evaluate()`-function structure) | The forward-shift construction and the hard-halt-on-failure discipline are already proven in production; a second, differently-shaped acausal check for regime dimensions would be exactly the "rediscovered per audit" failure this whole phase exists to prevent (per the design doc's own framing) |

**Key insight:** this phase's actual engineering surface is small — one new Protocol/ABC, one
new effective-N function, and a wiring/orchestration layer that calls three already-existing
statistical primitives (BH-FDR, causal rank, and the acausal-placebo pattern) in a new sequence.
The temptation to treat "formalize the governance layer" as license to write a lot of new
statistical machinery should be resisted; almost all of the actual math already exists in this
codebase.

## Common Pitfalls

### Pitfall 1: Assuming `concept_registry`/`concept_transition_log` can receive real writes this phase

**What goes wrong:** A plan task that says "log the pilot's gate results to `concept_transition_log`"
will fail at execution time — `concept_transition_log.concept_id` has a hard `NOT NULL` FK to
`concept_registry(concept_id)`, and `concept_registry.domain` cannot hold `'regime_model'` (CHECK
constraint verified live). There is no `concept_registry` row to reference.
**Why it happens:** The design docs (`stratification-dimension-unification.md`,
`concept-unified-registry.md`) describe the target state fluently enough that it's easy to plan
against the target schema instead of the live one.
**How to avoid:** Every plan task touching "log to the registry" must explicitly target a
standalone artifact (a JSON file under `docs/analysis/` or `.planning/`, or a lightweight
non-`concept_registry` scratch table created just for this pilot) shaped like the eventual
`concept_transition_log` row (`domain`, `name`, `from_status`, `to_status`, `trigger_reason`,
`gate_metric`, `gate_n`, `ci_lower`, `regime_scope`, `triggered_at`, `notes`), with an explicit
"pending Phase 170 backfill" marker.
**Warning signs:** Any migration file in this phase's plan that touches `concept_registry`'s
`domain` CHECK, or any INSERT into `concept_transition_log`/`concept_gate_stack`.

### Pitfall 2: `concept_gate_stack` doesn't exist — the three-stage cascade has nowhere to live in SQL yet

**What goes wrong:** `concept-unified-registry.md` specs `concept_gate_stack` as the table both
`regime_model`'s cascade and `confluence`'s six-gate stack need. Direct psql check
(`\d concept_gate_stack`) confirms it is not a live table. A plan that assumes it exists (e.g. "add
a row to `concept_gate_stack` for each of the 3 gates") will fail.
**Why it happens:** Same as Pitfall 1 — the reference doc describes reference architecture, not
current live schema.
**How to avoid:** The 3-stage cascade this phase builds is pure Python (a function or small class
sequence), not a DB-backed state machine, until Phase 170 lands `concept_gate_stack` for real.
**Warning signs:** Any SQL DDL in this phase's plan mentioning `concept_gate_stack`.

### Pitfall 3: The APR migrate-as-you-go mandate vs. D-07's deferred-migration decision

**What goes wrong:** CLAUDE.md's own enforcement language ("Hard-coded numeric thresholds...
in `src/` or `services/` is an architecture violation") could be read as requiring an immediate
migration for `alpha.regime_stratification.fdr_alpha`/`.max_correlation`, directly contradicting
D-07's explicit sequencing decision.
**Why it happens:** D-07 is a real, deliberate, user-ratified exception to the general rule, made
for a specific reason (the migration would need to touch the same `concept_registry`-adjacent
schema surface Phase 170 owns) — but nothing marks it as an *exception* to CLAUDE.md's mandate in
the code itself, so a future reader (or a mechanical CI-style check, if one is ever added) could
flag it as drift.
**How to avoid:** Whatever holds these two values in Phase 145's code (a dataclass, a
module-level constant, a config object) should carry an explicit code comment citing D-07 and
todo/phase 170 as the reason it is not yet APR-backed, matching this project's own convention
of documenting *why* an exception exists rather than leaving it silently non-conformant.
**Warning signs:** A bare `0.05` or `alpha_val = 0.10` with no comment anywhere near D-03/D-04's
gate logic.

### Pitfall 4: Ring-boundary violation pulling `regime_writer.py`/`ic_engine.py` logic into `src/intelligence/`

**What goes wrong:** The most natural-looking implementation of the effective-N estimator or the
`ic_engine.py` compatibility check is "just import `_smooth_states`/`_resolve_regime_scope` from
`services/`" — but `src/intelligence/` (Ring 1) must not import from `services/` (Ring 2) per
CLAUDE.md's Ring rule.
**Why it happens:** The relevant functions are private (leading underscore) module-level
functions in `services/regime_writer.py` and `services/ic_engine.py`, not designed for
cross-module reuse, and the temptation to just import them anyway (Python doesn't enforce the
Ring boundary) is real.
**How to avoid:** Treat those functions as *pattern references* (read, mirror the algorithm), not
import targets. The effective-N function should take a plain `np.ndarray`/`list` of labels as
input, decoupled from where that sequence came from. The `ic_engine.py` compatibility check
should be a test asserting shape/contract compatibility (e.g. "a dict of `{ts: label}` the
contract's `compute()` could plausibly produce is consumable by code shaped like
`_build_regime_passes`'s input contract"), not a test that imports and calls `ic_engine.py`
internals directly, unless that access pattern already exists (e.g. `test_ic_engine_routing.py`
already imports `_build_symbol_regime_class` directly from `services.ic_engine` — that precedent
exists for *testing* `ic_engine.py`'s own code, which is different from *importing it as a
dependency* from `src/intelligence/` production code).
**Warning signs:** `from services.regime_writer import _smooth_states` or similar inside
`src/intelligence/`.

### Pitfall 5: Conflating `min_hold_bars`'s existing smoothing with a new smoothing step

**What goes wrong:** `feature.hmm.min_hold_bars = 3` (live APR value, verified) already smooths
the incumbent HMM's raw states before they're written to `feature_vectors.regime`. If the
effective-N estimator (or the `volatility_pct` pilot, which the design doc explicitly notes
"the same smoothing applies to a percentile-rank series") re-applies its own independent
smoothing pass on top of an already-smoothed sequence, or on a differently-smoothed sequence,
the transition count won't be comparable across dimensions.
**Why it happens:** Smoothing is applied at write time in `regime_writer.py`; a new pilot module
computing `volatility_pct` fresh has no smoothing unless it explicitly adds one, and the
effective-N estimator doesn't know whether its input was already smoothed.
**How to avoid:** Document explicitly, in the effective-N function's docstring and the pilot's
own code, whether the labels passed in are pre-smoothed or raw — and if `volatility_pct` gets its
own `min_hold_bars`-equivalent smoothing pass (the design doc suggests it should, for parity with
the HMM), use the *same* `min_hold_bars` value (or an explicitly-justified different one) so
effective-N comparisons across dimensions in the substitution test aren't comparing
differently-autocorrelated sequences.
**Warning signs:** A substitution test comparing IC Sharpe between HMM-smoothed labels and
raw (unsmoothed) `volatility_pct` labels.

## Code Examples

See Architecture Patterns section above (Patterns 1-5) — all five carry real, sourced code from
this codebase, not synthetic examples. No additional standalone examples needed; the patterns
above are the code examples for this phase's domain.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| Regime label/scope hand-wired per-caller (`is_pooled`/`cross_sectional` booleans -> `_resolve_regime_scope`'s 3-value enum) | A shared `Protocol` every dimension implements, scope generalized to `(dimension, regime_group)` pairs | This phase, if built as designed — not yet shipped | `ic_engine.py`'s own hand-wiring is explicitly NOT touched this phase (out of scope); the "impact" is contract-level compatibility validated now, actual `ic_engine.py` migration to the contract is future work, not part of Phase 145 |
| `feature_ic_scores.regime` mixing unqualified label strings across dimensions | `regime_scope` column (Phase 141.1) qualifies the *source* (3-value enum: `cross_sectional`/`pooled`/`symbol_hmm`) | Phase 141.1, already shipped | Confirmed live and unchanged by this phase — this phase's contract generalizes the *concept* (dimension identity) further than `regime_scope`'s 3-value enum currently does, but does not touch `regime_scope` itself |
| One global `concept_registry.status` per candidate | Two fully-specced row-grain options (A: one row per dimension; B: one row per `(dimension, regime_group)`) | Ratified this phase (D-01: Option B) | Ratification only — the schema encoding itself (Option B's `name`-suffix convention, e.g. `hmm_price_vol__equity`) is documented and agreed but not written to a live table until Phase 170 |

**Deprecated/outdated:** none directly deprecated by this phase — this is additive governance
work, not a replacement of a working mechanism.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `atr_z`/`garman_klass_vol_z`/`yang_zhang_vol_z` (existing `feature_vectors` columns) are suitable raw inputs for `volatility_pct`'s realized-vol measure, rather than requiring a fresh, `volatility_pct`-specific computation | Pattern 2 | Low — these are all already causal, already z-scored volatility proxies; worst case the planner picks a different one or computes a dedicated realized-vol series, a small scope change, not a redesign |
| A2 | Placing the new code under `src/intelligence/stratification/` (a new subpackage) rather than inside `src/intelligence/regime_signals/` alongside the existing per-`regime_group` modules is the right structural choice | Recommended Project Structure | Low — this is a naming/location choice with no functional consequence; the planner has full discretion here and either placement is defensible given `regime_signals/` currently holds only *cross-sectional* dispatcher modules while the Protocol/pilot spans both grains |
| A3 | The effective-N estimator should live as a new standalone function rather than being generalized from (or replacing) `ic_math.py::_hac_sharpe_nd`'s inflation-factor logic | Pattern 4, Don't Hand-Roll | Medium — if a future reviewer decides the two effective-N mechanisms (HAC inflation for IC Sharpe, transition-counting for regime cells) should actually be unified into one shared primitive, this phase's separate implementation would need a follow-up consolidation. Not wrong, just a design choice with a plausible alternative; flagged here so the planner considers it explicitly rather than by default |

**If this table is empty:** N/A — see entries above. All three are structural/placement choices
with low-to-medium reversibility risk, not factual claims about the codebase (those were all
verified live via grep/psql during this research session).

## Open Questions

1. **Where should the pilot's gate results actually be written, concretely?**
   - What we know: it cannot go into `concept_registry`/`concept_transition_log` (verified live
     schema blocks this). CONTEXT.md's Claude's Discretion section explicitly leaves "whether the
     effective-N floor derivation is a one-time empirical study written up in a doc, or a
     runtime-computed value per gate invocation" to the planner.
   - What's unclear: whether the pilot's full gate-cascade output (all 3 stages' pass/fail +
     metrics) should be a single new doc under `docs/analysis/` (matching the existing convention,
     e.g. `docs/analysis/hmm-parameter-lookahead-pilot-spy-1h.md`), a JSON artifact under
     `.planning/`, or a lightweight non-production scratch table.
   - Recommendation: mirror `docs/analysis/hmm-parameter-lookahead-pilot-spy-1h.md`'s existing
     precedent (a written analysis doc with the exact numbers, explicitly marked
     "concept_transition_log-shaped, pending Phase 170 backfill") — this project already has a
     working convention for "empirical pilot result that will eventually feed a registry," and
     reusing it avoids inventing a new artifact type for one phase.

2. **Does the acausal-placebo registration gate (D-05) run once at "registration" time only, or
   on every gate-cascade invocation?**
   - What we know: `ops_canary_integrity_assert.py`'s mechanism runs every corpus pipeline run
     (continuous re-verification, not one-time). D-05's text says "no provider may enter gate 0...
     without first passing" — phrased as a precondition, suggesting once-per-provider, not
     once-per-run.
   - What's unclear: whether "Incumbents are re-measured, not grandfathered" (the design doc's
     existing governance rule, re-running the substitution test at every measurement epoch) should
     also apply to the acausal-placebo check specifically, or whether that check is a one-time
     registration gate that never needs re-running once a provider's `compute()` code is
     unchanged.
   - Recommendation: given CONTEXT.md leaves "exact implementation... test harness location"
     explicitly to the planner's discretion, this is squarely a planning decision, but the
     evidence leans toward "re-run whenever the provider's `compute()` implementation changes"
     (a code-content-keyed check, similar in spirit to `ic_engine.py`'s existing fingerprint
     invalidation on `code_content_key` changes) rather than either pure extreme.

3. **Does `_smooth_states()`-equivalent logic need to be extracted into a shared Ring-appropriate
   location as part of this phase, or is duplicating a small smoothing helper acceptable for the
   pilot's scope?**
   - What we know: Ring rule forbids `src/intelligence/` importing from `services/`. The
     `volatility_pct` pilot plausibly needs the same `min_hold_bars` smoothing behavior for a fair
     substitution-test comparison (see Pitfall 5).
   - What's unclear: whether a small, duplicated smoothing function (with an explicit comment
     noting it mirrors `regime_writer.py::_smooth_states()`) is acceptable for a one-pilot-dimension
     phase, or whether the "don't duplicate" instinct that produced `causal_rank.py`'s extraction
     should apply here too, meaning `_smooth_states()` should be extracted to a Ring 0/1-appropriate
     shared location as a small preparatory task within this phase.
   - Recommendation: given this phase runs exactly one pilot dimension (D-06), a small duplicated
     function with an explicit cross-reference comment is proportionate; extraction is better
     motivated once a second per-symbol dimension needs the same smoothing (the same "wait until
     the pattern is proven twice" bar `concept_gate_stack`'s own extraction used, per
     `concept-unified-registry.md`'s own reasoning).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL/TimescaleDB (`indicagent` DB) | `volatility_pct` pilot's real-data substitution test, effective-N derivation against real regime-transition data | ✓ | live, reachable via `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent` | — |
| `.venv` (project virtualenv) | All Python execution/tests | ✓ | `.venv/bin/pytest` present and functional | — |
| `statsmodels` | BH-FDR (`apply_bh_fdr`) | ✓ | `>=0.14.6` per pyproject.toml, confirmed importable | — |
| `scipy` | Binomial tail bounds if the acausal-placebo gate mirrors that part of `ops_canary_integrity_assert.py` too | ✓ | `>=1.15.0`, confirmed importable | — |
| `market_data_ohlcv_tradeable` (view) | Any OHLCV read for the `volatility_pct` pilot's realized-vol computation | ✓ | live view, CI-enforced boundary (`tests/unit/test_market_data_ohlcv_boundary.py`) | — |
| `concept_registry`/`concept_gate_stack` (schema) | The "real" governed registration this phase's design targets | ✗ (domain CHECK + missing table, both verified live) | — | Standalone pilot artifact (doc/JSON), explicitly deferred to Phase 170 — see Pitfalls 1-2 |

**Missing dependencies with no fallback:** none — the one missing piece (`concept_registry`
domain support) has an explicit, already-decided fallback (D-07's deferred-write plan).

**Missing dependencies with fallback:** `concept_registry`/`concept_gate_stack` schema support —
fallback is a standalone pilot artifact, per Pitfalls 1-2 and Open Question 1.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (project standard, `pytest.ini` at repo root) |
| Config file | `/home/bg/dev/indicagent/pytest.ini` — `testpaths = tests`, `python_files = test_*.py`, `asyncio_mode = auto` |
| Quick run command | `.venv/bin/pytest tests/unit/test_stratification_<name>.py -x -q` (per new test file) |
| Full suite command | `.venv/bin/pytest tests/unit/ -v` |

### Phase Requirements → Test Map

No formal `REQUIREMENTS.md` IDs exist for this phase (confirmed — `.planning/REQUIREMENTS.md`
does not exist in this project; this phase's roadmap entry itself states "phase has no formal
REQUIREMENTS.md IDs mapped"). Mapping instead against CONTEXT.md's decisions, which function as
this phase's real requirements:

| Decision | Behavior | Test Type | Automated Command | File Exists? |
|----------|----------|-----------|-------------------|-------------|
| D-01 (row-grain, Option B) | `name` encodes `(dimension, regime_group)` correctly, e.g. `hmm_price_vol__equity` != `hmm_price_vol__rates` | unit | `pytest tests/unit/test_stratification_contract.py -x -q` | ❌ Wave 0 |
| D-03 (BH-FDR across candidate pool) | `apply_bh_fdr` called once per `regime_group`'s cumulative candidate test history, not per-candidate in isolation | unit | `pytest tests/unit/test_stratification_gates.py -x -q -k fdr` | ❌ Wave 0 |
| D-04 (effective-N from transitions) | `effective_n_from_transitions()` returns transitions+1, handles empty/degenerate sequences without crashing, matches `_check_occupation_gate`-style guard discipline (empty/short input handled before division) | unit | `pytest tests/unit/test_stratification_gates.py -x -q -k effective_n` | ❌ Wave 0 |
| D-05 (acausal-placebo registration gate) | A provider whose `compute()` is deliberately given a future-shifted input fails registration (hard-raise); a causally-correct provider passes | unit | `pytest tests/unit/test_acausal_placebo_registration.py -x -q` | ❌ Wave 0 |
| D-06 (`volatility_pct` pilot, full gate stack) | End-to-end: pilot dimension clears/fails gate 0 -> 0.5 -> 1 -> 2 -> FDR, against real 3-5 symbol data | integration (real DB read via `market_data_ohlcv_tradeable`) | `pytest tests/unit/test_volatility_pct_pilot.py -x -q` (or `tests/integration/` if it needs a live DB connection — planner's call based on whether it's mocked/fixture data or live) | ❌ Wave 0 |
| Compatibility with `ic_engine.py` (CONTEXT.md's code_context note) | Contract's `compute()`/`score()` output shape is consumable by code shaped like `_build_regime_passes`'s existing input contract, without modifying `ic_engine.py` | unit | `pytest tests/unit/test_stratification_contract.py -x -q -k ic_engine_compat` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** the relevant single new test file (`-x -q` fast-fail)
- **Per wave merge:** `.venv/bin/pytest tests/unit/ -v` (full suite)
- **Phase gate:** full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/unit/test_stratification_contract.py` — Protocol/ABC conformance + `ic_engine.py`
      compatibility check
- [ ] `tests/unit/test_stratification_gates.py` — gate 0 (structural pre-filter), gate 1
      (orthogonality), gate 2 (substitution test), effective-N estimator, BH-FDR wiring
- [ ] `tests/unit/test_acausal_placebo_registration.py` — D-05's per-provider registration gate
- [ ] `tests/unit/test_volatility_pct_pilot.py` — D-06's pilot provider implementation
- No new framework/config install needed — pytest is already fully configured project-wide.

## Security Domain

`security_enforcement` is absent from `.planning/config.json` (treated as enabled per this
process's default), but this phase has effectively no attack surface: no new HTTP endpoints, no
new auth/session code, no new user input parsing, no new secrets, no new cryptography. It is a
backend statistical/governance contract operating entirely on internal corpus data the pipeline
already trusts.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No new auth surface — internal batch/library code only |
| V3 Session Management | No | N/A |
| V4 Access Control | No | N/A — same access model as every other `src/intelligence/`/`services/` module (operator-only, no multi-tenant boundary in this codebase) |
| V5 Input Validation | Marginal | The `StratificationDimension` Protocol's `causality_basis` field should be validated against its `Literal['deterministic', 'expanding_window', 'fitted']` enum at registration time (this is exactly what D-05's gate enforces empirically, going beyond simple type validation) — treat the registration gate itself as this phase's V5 control |
| V6 Cryptography | No | No new cryptographic code |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| A provider self-declares `causality_basis` incorrectly (claims `expanding_window` while actually leaking future data) | Tampering (of a governance claim, not of external input — an internal-trust-boundary integrity issue, not a classic injection/auth vector) | D-05's acausal-placebo registration gate — the whole point of this phase's causal safeguard; do not treat this as out of scope for "security" just because the threat actor is a future developer's bug, not an external attacker — the project's own principle ("silent wrong answers are worse than loud crashes") is this codebase's security posture for exactly this class of risk |
| A candidate dimension's promotion evidence is cherry-picked (tested across many strata, best one reported) | Repudiation (an unauditable claim about "this dimension works") | `concept_gate.regime_scope`'s existing "pre-registration rule" (declared before evaluation, never chosen after seeing per-stratum results) — this phase's pilot must pre-declare its `regime_group`/symbol scope before running the substitution test, not select the best-looking result after the fact |

## Sources

### Primary (HIGH confidence — direct code/schema verification this session)
- `services/ic_engine.py` (live, read via `Read`/`grep`) — `_resolve_regime_scope` (line 225),
  `_build_symbol_regime_class` (line 271), `_compute_symbol_tf`'s `mr_dict` handling and
  `_build_regime_passes` call (lines 2470-2730)
- `services/regime_writer.py` (live, read via `grep`/`Read`) — `_smooth_states` (~line 400),
  `_check_occupation_gate` (line 419), `_compute_hmm_churn` (line 466)
- `services/cross_sectional_regime_model.py` (live, read via `Read`) — module docstring, dispatcher
  shape, `_resolve_group_symbols` (line 179)
- `scripts/ops/alpha/ops_canary_integrity_assert.py` (live, read in full) — `evaluate()`,
  `CanaryIntegrityViolation`, `_binomial_tail_bound`, `_family_bound_check`
- `src/intelligence/feature_factory.py` (live, read via `grep`/`Read`) — `_canary_acausal_placebo`
  (line 1899)
- `src/intelligence/regime_signals/breadth_vol.py`, `causal_rank.py` (live, read via `Read`) —
  `compute()`, `build_tiers()`, `causal_expanding_rank()`
- `src/intelligence/statistics/ic_math.py` (live, read via `Read`/`grep`) — `apply_bh_fdr` (line
  ~545), `_hac_sharpe_nd` (line 967)
- `src/intelligence/plugins/base.py` (live but archived subsystem, read via `Read`) —
  `PatternPlugin`/`IndicatorPlugin` Protocol, `validate_tier`
- `src/intelligence/concept_registry_service.py` (live, read via `Read`/`grep`) — service
  structure, invariant documentation
- Live DB schema (psql, `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent`):
  `\d concept_registry`, `\d concept_gate`, `\d concept_gate_stack` (does not exist),
  `\d concept_transition_log`, `config_state` queries for `alpha.ic.min_obs_per_regime`,
  `alpha.ic.hac_max_lag`, `alpha.decay.regime_shift_fraction`, `feature.hmm.min_hold_bars`,
  `alpha.regime.groups`
- `.venv` import check (`statsmodels`, `scipy` both importable)
- `pytest.ini` (test framework config)
- `.planning/config.json` (`nyquist_validation: true`, `security_enforcement` absent)

### Secondary (MEDIUM confidence — design docs, cross-checked against live code above)
- `docs/research/stratification-dimension-unification.md` (v1.2, extensively re-verified inline
  by its own authors through 2026-08-06 — read in full)
- `docs/research/concept-unified-registry.md` § Domain Vetting (`regime_model`, `confluence`
  subsections) and § schema DDL (`concept_registry`, `concept_gate`, `concept_gate_stack`,
  `concept_transition_log`) (read in full for the relevant sections)

### Tertiary (LOW confidence)
- None — this research relied entirely on primary code/schema verification and a heavily
  self-re-verified design doc, not unverified web search (this phase has no external-library
  research component; it is entirely internal-codebase archaeology).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies, both `statsmodels`/`scipy` confirmed already
  installed and used identically elsewhere in this codebase
- Architecture: HIGH — every pattern cited is live, read-in-full code in this repository, not
  inferred or reconstructed from documentation
- Pitfalls: HIGH — the two most consequential pitfalls (concept_registry domain CHECK,
  concept_gate_stack non-existence) are directly psql-verified against the live database, not
  assumed from the design doc's own (admittedly extensively self-corrected) narrative
- Row-grain/governance design questions (D-01 through D-07): N/A for confidence — these are
  already-ratified user decisions from CONTEXT.md, not open research questions; this document
  treats them as constraints, not hypotheses

**Research date:** 2026-08-06
**Valid until:** 30 days (stable internal codebase; the one fast-moving external dependency is
Phase 170's landing date, which would change the "cannot write to concept_registry yet" finding —
re-verify the live `\d concept_registry` domain CHECK before planning execution if Phase 170 has
landed since this research was written)
