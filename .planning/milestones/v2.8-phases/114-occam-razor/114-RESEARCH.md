# Phase 114: Occam's Razor - Research

**Researched:** 2026-06-03
**Domain:** Model Selection, Statistical Testing, Complexity-Aware Evaluation
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
**D-01: Baseline Selection — Agent Prefix Mapping**
- `_BASELINES` dict maps agent_id prefixes to `BaselineBuilder` instances
- `ml_*` → `LinearBaseline` (logistic regression with L2)
- `correlation_*` → `RuleBaseline` (correlation threshold)
- `regime_*` → `RandomBaseline` (tests if regime adds value)
- `counterfactual_*` → `NullBaseline` (no adjustment)
- Fallback: skip agent with warning if no mapping found

**D-02: Complexity Score — Log-Transformed Product**
- Formula: `complexity_score = log(params + 1) × (1 + latency_ms / 1000) × (1 + train_time_ms / 60000)`
- Log transform prevents exponential penalty on parameter count
- Normalized latency/train time prevents runaway scores
- Additive terms (1 + ...) prevent zero-division

**D-03: Statistical Test — Bootstrap CI**
- 1000 bootstrap resamples of both models' returns
- Decision rule: `ci_lower > 0` → complex wins, `ci_upper < 0` → baseline wins, CI spans 0 → tie (prefer simpler)
- Bootstrap is non-parametric, handles non-normal return distributions
- Fallback: simple t-test on sharpe deltas if bootstrap fails

**D-04: Penalty Weight — Tunable via Config, Default 0.5**
- `OccamRazorEvaluator._penalty_weight` attribute
- Settable via constructor or environment variable `OCCAM_PENALTY_WEIGHT`
- 0.5 balances performance and complexity

**D-05: Shadow Registry Enhancement — Rejection Tracking**
- New columns: `rejection_reason` (TEXT), `complexity_score` (FLOAT), `last_occam_check` (TIMESTAMPTZ)
- Update flow sets `is_shadow = TRUE` on baseline win/tie

**D-06: Fail-Closed — Missing Data Raises**
- If `complexity_score` is NULL or missing, raise `RuntimeError`
- Cannot compute penalty without complexity data

**D-07: Evaluation Window — Last 30 Days of Shadow Signals**
- Source: `signal_ledger` WHERE `timestamp > NOW() - INTERVAL '30 days'` AND `agent_id = $1` AND outcome IS NOT NULL
- Minimum sample size: `n >= 30` signals required
- Skip evaluation with warning if fewer

### Claude's Discretion
- Whether `OccamRazorEvaluator` lives in `src/intelligence/ai/evaluators/` or `src/intelligence/ai/occam/` (recommend `evaluators/`)
- Whether bootstrap CI uses 1000 or 2000 resamples (1000 is sufficient)
- Whether penalty_weight is float or int (float for finer tuning)

### Deferred Ideas (OUT OF SCOPE)
- Multi-baseline comparison (single baseline per agent type)
- Parameter budgeting across agents
- Online adaptation of penalty_weight
- Plugin-level Occam testing
- Production signal blocking
</user_constraints>

## Summary

The Occam's Razor Evaluator (ORE) implements Renaissance-style complexity-aware model selection for shadow ML agents. For each shadow agent, ORE builds a simpler baseline, runs both on identical 30-day signal outcome data, and applies a bootstrap statistical test with complexity penalty. If the baseline wins or ties, the complex model is automatically rejected via `shadow_registry` update.

**Primary recommendation:** Use sklearn for baselines, scipy for stats, integrate into AlphaSwarm's existing `_graduation_loop` — no new service required.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| numpy | >=2.0.0 | Array operations, bootstrap sampling | Already in reqs, used in stats_utils |
| scipy | >=1.15.0 | Statistical tests (spearmanr, percentile) | Existing dependency, verified in codebase |
| sklearn | (via sklearn-isotonic) | LinearRegression, LogisticRegression | Already used in confidence_calibrator |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| asyncpg | (existing) | DB queries for signal_ledger, shadow_registry | Standard DB client |
| pydantic | (existing) | ModelScore, OccamResult dataclasses | Existing validation layer |
| opentelemetry | (existing) | OTel metrics emission | Standard observability |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| sklearn.LinearRegression | Custom linear regression via numpy.linalg | sklearn is production-tested, handles edge cases |
| scipy.stats.bootstrap (v1.10+) | Manual bootstrap loop | Manual loop gives CI bounds directly, fewer deps |

**Installation:**
No new packages required — all dependencies already in `requirements.txt`.

## Architecture Patterns

### Recommended Project Structure
```
src/intelligence/ai/
├── evaluators/
│   ├── occam_razor_evaluator.py  # Main evaluator
│   └── baseline.py                # BaselineBuilder protocol + implementations
├── alpha/
│   └── ml_scorer_agent.py        # Reference: MLEvaluator pattern
```

### Pattern 1: BaselineBuilder Protocol
**What:** Protocol interface for building simple baseline models
**When to use:** All baseline implementations must conform to this interface
**Example:**
```python
# src/intelligence/ai/evaluators/baseline.py
from __future__ import annotations
from typing import Protocol, Any
import numpy as np
from sklearn.linear_model import LogisticRegression

class BaselineModel(Protocol):
    """Baseline model interface."""
    def predict(self, features: np.ndarray) -> np.ndarray: ...

class BaselineBuilder(Protocol):
    """Build a simple baseline for a given agent type."""
    def build(self, features: np.ndarray, targets: np.ndarray) -> BaselineModel:
        ...

class LinearBaseline(BaselineBuilder):
    """Logistic regression baseline with L2 regularization."""
    def build(self, features: np.ndarray, targets: np.ndarray) -> BaselineModel:
        model = LogisticRegression(penalty='l2', C=1.0, random_state=42)
        model.fit(features, targets)
        return model
```

### Pattern 2: Bootstrap CI (Existing Codebase Pattern)
**What:** Use existing `bootstrap_ci_lower()` from `src/core/stats_utils.py`
**When to use:** Statistical significance testing for Sharpe delta
**Example:**
```python
# Source: src/core/stats_utils.py (verified existing code)
import numpy as np

def bootstrap_ci_lower(pnl_r_values: list[float], alpha: float = 0.05, n_boot: int = 1000) -> float:
    if len(pnl_r_values) < 10:
        return float('-inf')
    rng = np.random.default_rng(42)
    arr = np.array(pnl_r_values)
    boot_means = np.array([rng.choice(arr, size=len(arr), replace=True).mean() for _ in range(n_boot)])
    return float(np.percentile(boot_means, alpha / 2 * 100))
```

### Pattern 3: AlphaSwarm Integration
**What:** ORE runs as part of existing `_graduation_loop` (15-min cycle)
**When to use:** Periodic evaluation without new systemd service
**Example:**
```python
# services/alpha_swarm.py (addition to existing _graduation_loop)
async def _graduation_loop(self) -> None:
    interval_s: float = getattr(self.settings, "swarm_graduation_interval_s", 900)
    while self.running:
        try:
            await asyncio.sleep(interval_s)
            await self._run_graduation_cycle()
            await self._run_occam_razor_cycle()  # NEW
        except asyncio.CancelledError:
            break
        except Exception as error:
            self.logger.error("graduation_cycle_failed", err=str(error))
```

### Anti-Patterns to Avoid
- **Baseline with complexity penalty:** Baseline models must be complexity-zero by definition (complexity_score = 1.0)
- **Blocking graduation loop:** ORE evaluation must not block signal processing — wrap in try/except, log warnings
- **Direct shadow_registry writes without ACID:** Use single UPDATE transaction for rejection

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Linear regression | Custom via numpy.linalg.lstsq | sklearn.LinearRegression/LogisticRegression | Handles edge cases (singular matrices), standard API |
| Statistical tests | Manual t-test, percentile calc | scipy.stats.spearmanr, numpy.percentile | Verified, tested, handles NaN |
| Bootstrap loop | Custom random sampling | Extend existing `bootstrap_ci_lower()` pattern | Consistent with codebase, fixed seed for reproducibility |
| Complexity scoring | Ad-hoc formulas | Log-transformed product from CONTEXT D-02 | Proven in spec, handles exponential vs linear scaling |
| Shadow registry sync | Direct DB writes | ACID transaction with rollback | Data integrity, Renaissance principle |

**Key insight:** Custom solutions for statistical testing are error-prone. Use sklearn/scipy for baseline models and scipy for tests — these are domain-correct, well-tested, and already dependencies.

## Common Pitfalls

### Pitfall 1: Insufficient Sample Size (n < 30)
**What goes wrong:** Bootstrap CI produces unreliable bounds, false rejections
**Why it happens:** New agents or regime-specific segments don't have enough resolved signals
**How to avoid:** Skip evaluation with warning when `n < 30`, log sample_size metric
**Warning signs:** High rejection rate, many "skipped" log entries

### Pitfall 2: Missing Complexity Metadata
**What goes wrong:** `RuntimeError` raised per D-06, evaluation halts
**Why it happens:** ML models don't publish parameter count, latency, or train_time
**How to avoid:** MANDATORY: complexity_score must be populated before ORE runs. Add to ml_models table or shadow_registry
**Warning signs:** ORE logs "missing complexity_score" exceptions

### Pitfall 3: Zero-Variance Returns
**What goes wrong:** Sharpe ratio is NaN or infinite, bootstrap fails
**Why it happens:** All signals have identical outcome (e.g., all losses or all wins)
**How to avoid:** Guard against `std() < 1e-9` before Sharpe computation, skip evaluation
**Warning signs:** `sharpe=nan` in metrics, bootstrap exceptions

### Pitfall 4: Baseline Overfitting
**What goes wrong:** Baseline performs suspiciously well, invalidates Occam test
**Why it happens:** RuleBaseline over-tuned to training data, LinearBaseline on non-linear problem
**How to avoid:** Use simple, untuned baselines only (default hyperparameters, single threshold)
**Warning signs:** Baseline sharpe > complex sharpe consistently

### Pitfall 5: CI Spanning Zero (Tie) Misclassification
**What goes wrong:** Tie cases treated as "promote" when they should reject
**Why it happens:** Inverted logic on `ci_lower > 0` condition
**How to avoid:** D-03 decision rule is authoritative: `ci_lower > 0` → complex wins ONLY, else reject
**Warning signs:** High promotion rate despite baseline competitiveness

## Code Examples

Verified patterns from existing codebase:

### Existing Bootstrap Pattern (HIGH confidence)
```python
# Source: src/core/stats_utils.py (verified existing code)
def bootstrap_ci_lower(
    pnl_r_values: list[float],
    alpha: float = 0.05,
    n_boot: int = 1000,
) -> float:
    if len(pnl_r_values) < 10:
        return float("-inf")
    rng = np.random.default_rng(42)
    arr = np.array(pnl_r_values)
    boot_means = np.array(
        [rng.choice(arr, size=len(arr), replace=True).mean() for _ in range(n_boot)]
    )
    return float(np.percentile(boot_means, alpha / 2 * 100))
```

### Existing Statistical Testing Pattern (HIGH confidence)
```python
# Source: src/intelligence/ml/information_coefficient.py (verified)
import numpy as np
from scipy import stats

# Guard: zero-variance inputs produce nan correlation
if conf_arr.std() < 1e-9 or pnl_arr.std() < 1e-9:
    logger.warning("ic_zero_variance n=%d", len(pairs))
    return None, None, len(pairs)

ic_score, p_value = stats.pearsonr(conf_arr, pnl_arr)
```

### Existing AlphaSwarm Graduation Pattern (HIGH confidence)
```python
# Source: services/alpha_swarm.py (verified)
async def _evaluate_agent(self, agent_id: str) -> None:
    """Per-agent Spearman weight learning: query 30d lineage, UPSERT."""
    async with self._pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT sl.tf AS timeframe,
                   sl.multiplier AS multiplier,
                   ledger.pnl_r AS pnl_r
            FROM signal_lineage sl
            JOIN signal_ledger_full ledger ON ledger.signal_id = sl.signal_id
            WHERE sl.event_type = 'agent_prediction'
              AND sl.source = $1
              AND ledger.outcome IS NOT NULL
              AND sl.ts > NOW() - INTERVAL '30 days'
            """,
            agent_id,
        )
        # ... compute rho, UPSERT to swarm_agent_weights
```

### Existing OTel Metrics Pattern (HIGH confidence)
```python
# Source: src/observability/metrics.py (verified)
SWARM_AGENT_WEIGHT = point_gauge(
    "swarm_agent_weight",
    description="Per-agent graduation weight from Spearman correlation"
)
# Usage:
SWARM_AGENT_WEIGHT.set(weight, {"agent_id": agent_id, "timeframe": tf})
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual model selection | Automated Occam testing | Phase 114 (this phase) | Reject over-complex models automatically |
| Single metric (Sharpe) | Multi-metric + complexity penalty | Phase 114 | Prevents gaming via parameter bloat |
| Human-in-the-loop promotion | Shadow-first auto-rejection | v2.5 (Phase 77) | Evidence-based promotion, zero manual work |
| Bootstrap CI not available | scipy.stats.bootstrap (v1.10+) | 2021 | Could simplify manual loop (future optimization) |

**Deprecated/outdated:**
- Manual baseline comparison: Replaced by automated ORE evaluation
- Unbounded complexity: Complexity penalty gates parameter bloat
- Shadow mode optional: All new agents start `shadow_only=True` (Phase 77)

## Open Questions

1. **Complexity metadata source for ml_scorer_v1**
   - What we know: ml_models table has status, promoted_at, but no param count
   - What's unclear: Where to store `params`, `latency_ms`, `train_time_ms` for complexity_score
   - Recommendation: Add columns to ml_models table (`param_count`, `inference_latency_ms`, `training_time_ms`)

2. **ORE evaluation frequency**
   - What we know: AlphaSwarm graduation loop runs every 15 min (configurable)
   - What's unclear: Should ORE run on every graduation cycle or less frequently?
   - Recommendation: Run on every graduation cycle — cheap relative to LLM calls, provides rapid feedback

3. **Baseline for genetic agents (future Phase 102)**
   - What we know: Not in scope for Phase 114, but genetic agents will need baselines
   - What's unclear: What baseline type for "best single feature from genetic pool"?
   - Recommendation: `SimpleBaseline` that picks the highest-IC single feature as baseline

## Sources

### Primary (HIGH confidence)
- `src/core/stats_utils.py` — bootstrap_ci_lower implementation (verified existing code)
- `src/intelligence/ml/information_coefficient.py` — scipy.stats.pearsonr pattern, zero-variance guard (verified)
- `services/alpha_swarm.py` — _graduation_loop, _evaluate_agent patterns, DB query structure (verified)
- `src/observability/metrics.py` — OTel metric creation patterns (verified)
- `src/intelligence/ml/confidence_calibrator.py` — sklearn.isotonic.IsotonicRegression usage (verified)

### Secondary (MEDIUM confidence)
- `docs/foundation/occam-razor.md` — Principle statement, Renaissance rationale
- `docs/ideas/ai-occam-razor.md` — Implementation spec, architecture sketch
- `src/intelligence/ai/AUTHORING.md` — Agent authoring protocol, shadow enrollment
- `.planning/phases/114-occam-razor/114-CONTEXT.md` — Locked decisions (D-01 through D-07)

### Tertiary (LOW confidence)
- None — all sources verified against code or official docs

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all dependencies verified in requirements.txt and existing code
- Architecture: HIGH — patterns verified in existing AlphaSwarm, stats_utils, information_coefficient
- Pitfalls: HIGH — based on verified code patterns and Renaissance principles

**Research date:** 2026-06-03
**Valid until:** 2026-07-03 (30 days — ML stack stable, Occam's Razor principle foundational)
