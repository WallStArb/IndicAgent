# Occam's Razor Evaluator — Complexity-Aware Model Selection

**Version:** 1.0
**Status:** proposed
**Priority:** high
**Milestone:** v2.8 (Phase 100)
**Last Updated:** 2026-06-03
**Tags:** model-selection, complexity-penalty, shadow-governance, statistical-testing, renaissance

---

## Philosophy

Complex models are a liability. They overfit, they break in opaque ways, and they waste computation. Renaissance systems prefer simplicity unless complexity earns its keep through **statistically significant** performance gains.

The Occam's Razor Evaluator (ORE) enforces this principle. For every shadow ML agent, ORE builds a simpler baseline, runs both on identical data, and applies a statistical test with a complexity penalty. If the baseline wins or ties, the complex model is rejected.

**This is not a suggestion — it's a gate.**

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         OccamRazorEvaluator (ORE)                            │
│                                                                              │
│  For each shadow ML agent:                                                    │
│    1. Build simple baseline (linear/logistic/rule-based)                      │
│    2. Run both on same data/features (last N days of shadow signals)         │
│    3. Compute complexity penalty (params × latency × train_time)             │
│    4. Statistical test: is complex model significantly better?               │
│    5. Fail-closed: reject if baseline wins or ties                            │
│                                                                              │
│  Metrics:                                                                    │
│    - occam_razor_evaluations_total{agent_id}                                 │
│    - occam_razor_rejections_total{agent_id, reason}                          │
│    - occam_razor_complexity_ratio{agent_id}                                  │
│    - occam_razor_sharpe_delta{agent_id}                                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Baseline Registry

ORE maps each ML agent type to an appropriate baseline:

| Agent Type | Baseline | Rationale |
|------------|-----------|-----------|
| `ml_scorer` | `LinearBaseline` | Logistic regression with L2 regularization |
| `correlation_*` | `RuleBaseline` | Simple correlation threshold (e.g., ρ > 0.7) |
| `regime_coherence_*` | `RandomBaseline` | Random regime assignment (tests if regime adds value) |
| `counterfactual_*` | `NullBaseline` | No counterfactual adjustment (baseline is raw signal) |
| `genetic_*` | `SimpleBaseline` | Best single-feature model from genetic pool |

**Baseline builders are pluggable.** Add new mappings in `_BASELINES` registry.

---

## Statistical Test

### Performance Comparison

For each model (complex and baseline), compute:
- `sharpe` — Annualized Sharpe ratio from shadow signal returns
- `win_rate` — Fraction of profitable signals
- `pnl_r` — Total return normalized by max drawdown
- `n` — Sample size (number of signals evaluated)

### Complexity Score

```
complexity_score = log(params + 1) × (1 + latency_ms / 1000) × (1 + train_time_ms / 60000)
```

- `params` — Number of trainable parameters
- `latency_ms` — Inference latency per signal
- `train_time_ms` — Training time for last model update

Log-transform params prevents exponential penalty. Normalized latency/train time prevents runaway scores.

### Decision Rule

```
raw_delta = sharpe_complex - sharpe_baseline
complexity_ratio = complexity_complex / complexity_baseline
penalty = log(complexity_ratio) if complexity_ratio > 1 else 0

adjusted_delta = raw_delta - penalty_weight × penalty

# Bootstrap CI for statistical significance
n_bootstrap = 1000
bootstrap_deltas = []
for i in range(n_bootstrap):
    # Resample both models' returns and recompute sharpe delta
    ...

ci_lower = percentile(bootstrap_deltas, 2.5)
ci_upper = percentile(bootstrap_deltas, 97.5)

if ci_lower > 0:
    winner = "complex"      # Statistically superior
elif ci_upper < 0:
    winner = "baseline"     # Baseline wins
else:
    winner = "tie"          # Inconclusive → prefer simpler
```

**Tunable parameter:** `penalty_weight` (default: 0.5). Higher = stronger preference for simplicity.

---

## Implementation Sketch

```python
# src/intelligence/ai/evaluators/occam_razor_evaluator.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol
import numpy as np
from scipy import stats

from src.core.ai.base_agent import BaseAIWorker
from src.core.ai.output import AgentOutput
from src.intelligence.ai.context import SignalContext


@dataclass
class ModelScore:
    """Performance score for a single model."""
    agent_id: str
    sharpe: float
    win_rate: float
    pnl_r: float
    complexity_score: float
    n: int


@dataclass
class OccamResult:
    """Result of Occam's Razor comparison."""
    complex_model: ModelScore
    baseline: ModelScore
    winner: str  # "complex" | "baseline" | "tie"
    confidence: float  # 95% CI width or p-value
    recommendation: str  # "promote" | "reject"


class BaselineBuilder(Protocol):
    """Build a simple baseline for a given agent type."""
    def build(self, features: np.ndarray, targets: np.ndarray) -> BaselineModel:
        ...


class LinearBaseline(BaselineBuilder):
    """Linear regression/classification baseline."""
    def build(self, features: np.ndarray, targets: np.ndarray) -> BaselineModel:
        # sklearn LinearRegression or LogisticRegression
        # L2 regularization, default hyperparameters
        ...


class RuleBaseline(BaselineBuilder):
    """Rule-based baseline (e.g., correlation threshold)."""
    def build(self, features: np.ndarray, targets: np.ndarray) -> BaselineModel:
        # Simple thresholds, moving averages, z-score signals
        ...


class OccamRazorEvaluator(BaseAIWorker):
    """Evaluates whether complex models justify their complexity.

    For each shadow ML agent:
    1. Build a simple baseline (linear/rule-based)
    2. Evaluate both on same data window
    3. Apply statistical test with complexity penalty
    4. Fail-closed: reject if baseline wins or ties
    """

    agent_id = "occam_razor"
    group = "alpha"
    tiers_needed = ["i7"]
    shadow_only = True
    prompt_version = "1.0"

    # Baseline registry: agent_prefix -> baseline_builder
    _BASELINES: dict[str, BaselineBuilder] = {
        "ml": LinearBaseline(),
        "correlation": RuleBaseline(),
        "regime": RuleBaseline(),
        "counterfactual": RuleBaseline(),
    }

    def __init__(self, llm_chain, pool, settings):
        super().__init__(llm_chain, pool, settings)
        self._penalty_weight = 0.5  # Tunable via config

    async def _compute(self, context: SignalContext) -> AgentOutput:
        """Run Occam's Razor test on all shadow ML agents."""
        ml_agents = [a for a in self._agents if self._is_ml_agent(a)]

        results: list[OccamResult] = []
        for agent in ml_agents:
            baseline_type = self._get_baseline_type(agent.agent_id)
            if baseline_type is None:
                continue

            # Get evaluation data from recent shadow signals
            features, targets = await self._get_agent_data(agent, window_days=30)

            # Build and evaluate baseline
            baseline = baseline_type.build(features, targets)
            baseline_score = await self._evaluate(baseline, features, targets)

            # Get complex model's score (from shadow registry)
            complex_score = await self._get_agent_score(agent)

            # Statistical comparison
            result = self._compare(complex_score, baseline_score)
            results.append(result)

            # Fail-closed: reject if baseline wins
            if result.winner != "complex":
                await self._reject_agent(agent, result)

        return AgentOutput(
            signal=None,
            metadata={"occam_results": [r.model_dump() for r in results]},
        )

    def _compare(self, complex: ModelScore, baseline: ModelScore) -> OccamResult:
        """Statistical comparison with complexity penalty."""
        raw_delta = complex.sharpe - baseline.sharpe
        complexity_ratio = complex.complexity_score / baseline.complexity_score
        penalty = np.log(complexity_ratio) if complexity_ratio > 1 else 0

        adjusted_delta = raw_delta - self._penalty_weight * penalty

        # Bootstrap CI
        bootstrap_deltas = self._bootstrap_ci(complex, baseline, n=1000)
        ci_lower, ci_upper = np.percentile(bootstrap_deltas, [2.5, 97.5])

        if ci_lower > 0:
            winner, recommendation = "complex", "promote"
        elif ci_upper < 0:
            winner, recommendation = "baseline", "reject"
        else:
            winner, recommendation = "tie", "reject"

        return OccamResult(
            complex_model=complex,
            baseline=baseline,
            winner=winner,
            confidence=ci_upper - ci_lower,
            recommendation=recommendation,
        )

    async def _reject_agent(self, agent: BaseAIWorker, result: OccamResult) -> None:
        """Update shadow_registry and log rejection."""
        # UPDATE shadow_registry SET is_shadow = TRUE, rejection_reason = ...
        # Emit metric: occam_razor_rejections_total{agent_id, reason}
        ...
```

---

## Integration

### 1. Agent Registry (`config/agents.yaml`)

```yaml
alpha:
  - skeptic
  - correlation_v1
  - regime_coherence_v1
  - counterfactual_v1
  - ml_scorer_v1
  - occam_razor  # New evaluator
```

### 2. Shadow Registry Enhancement

Add columns to `shadow_registry`:
```sql
ALTER TABLE shadow_registry ADD COLUMN rejection_reason TEXT;
ALTER TABLE shadow_registry ADD COLUMN complexity_score FLOAT;
ALTER TABLE shadow_registry ADD COLUMN last_occam_check TIMESTAMPTZ;
```

### 3. Metrics

```python
# src/observability/metrics.py
occam_razor_evaluations_total = create_counter(...)
occam_razor_rejections_total = create_counter(...)  # {agent_id, reason}
occam_razor_complexity_ratio = create_histogram(...)  # {agent_id}
occam_razor_sharpe_delta = create_histogram(...)  # {agent_id}
```

---

## Failure Modes and Guardrails

| Failure Mode | Detection | Mitigation |
|--------------|-----------|------------|
| Insufficient data | `n < 30` signals | Skip evaluation, log warning |
| Baseline builder missing | No registry entry | Skip agent, alert operator |
| Complexity data missing | `complexity_score = NULL` | Raise, don't default |
| Bootstrap fails | Exception during resampling | Fall back to simple delta test |
| Over-aggressive penalty | High rejection rate | Tune `penalty_weight` downward |

**All guardrails are fail-closed.** Missing data or errors raise, never default to "promote."

---

## Renaissance Alignment

### Data Integrity
- Simpler models are less prone to overfitting
- Statistical tests ensure significance, not noise

### Ruthless Complexity Elimination
- Explicit complexity penalty
- Rejection is automatic, not operator-dependent

### Fail-Closed Validation
- Missing complexity data raises
- Ties default to rejection, not promotion

### Auditability
- Every rejection logged with reason
- Complexity scores tracked over time
- Bootstrap CIs recorded

---

## Related Work

- **Phase 101 (Composite Fitness Function)** — Occam penalty as one fitness component
- **Phase 095 (Pydantic AI Agent Execution)** — All AI agents inherit from BaseAIWorker
- **Phase 096 (Agent Registry)** — ORE registered and built via YAML

---

## Future Extensions

1. **Multi-baseline comparison** — Test against multiple simple baselines, pick the best
2. **Parameter budgeting** — Allocate complexity budget across agents, prevent bloat
3. **Online adaptation** — Adjust penalty_weight based on recent rejection rates
4. **Plugin-level Occam** — Extend to technical indicators if trainable weights added
