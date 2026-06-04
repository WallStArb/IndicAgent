# Occam's Razor — Model Selection Principle

**Version:** 1.0
**Status:** foundational
**Milestone:** v2.8
**Last Updated:** 2026-06-03

---

## Principle

> *"Entities should not be multiplied beyond necessity."*
> — William of Ockham, 14th century

**Renaissance interpretation:** When a simpler model achieves statistically similar performance to a complex one, the complex model is unjustified and must be rejected.

---

## Formal Statement

Given two models M₁ (simple) and M₂ (complex) that solve the same problem:

**Prefer M₁ if any of the following hold:**
1. `Performance(M₁) ≈ Performance(M₂)` (statistical tie)
2. `Performance(M₁) > Performance(M₂)` (simpler wins)
3. `Performance(M₂) - Performance(M₁) < Penalty(Complexity(M₂) - Complexity(M₁))`

**Prefer M₂ only if:**
- `Performance(M₂) - Performance(M₁) > Penalty(Complexity(M₂) - Complexity(M₁))`
- The difference is statistically significant (p < 0.05)

Where:
- `Performance` = Sharpe ratio, win rate, or other relevant metric
- `Complexity` = Parameter count × inference latency × training time
- `Penalty` = Tunable weight (default: 0.5)

---

## Application in IndicAgent

### Scope
- **Primary:** ML agents (MLEvaluator, genetic agents, future AI models)
- **Secondary:** Technical indicators (if parameterized models with trainable weights)
- **Excluded:** Fixed-rule indicators (SMA, RSI) — complexity is static

### Integration Points
1. **Shadow Registry** — Occam evaluation runs before promotion
2. **Composite Fitness Function** — Complexity penalty is one fitness component
3. **Genetic Infrastructure** — Prevents bloat, encourages parsimony

### Failure Modes
- **Overfitting:** Complex model memorizes training data, fails in production
- **Data dredging:** Adding parameters until significance appears by chance
- **Maintenance burden:** Complex models are harder to debug and update

### Guardrails
- All Occam tests are shadow-only — never blocks production signals
- Rejection is reversible — if conditions change, re-evaluate
- Complexity scores are logged and auditable
- Human operator can override with documented justification

---

## Renaissance Rationale

### Why This Matters

1. **Data Integrity** — Simpler models are less likely to overfit. When a model memorizes noise rather than signal, it degrades decision quality.

2. **Operational Robustness** — A model with 10 parameters fails in 10 ways. A model with 1000 parameters fails in 1000 ways. Renaissance systems minimize failure modes.

3. **Computational Efficiency** — Complexity costs money. Latency matters. Training time matters. Memory footprint matters.

4. **Regime Adaptation** — Simple models adapt faster to regime changes. Complex models carry more historical baggage.

5. **Debuggability** — When a linear model fails, you inspect coefficients. When a neural net fails, you shrug.

### What This Prevents

- **Parameter bloat** — Genetic algorithms that grow without bound
- **Redundant features** — 500 features when 50 explain 95% of variance
- **Over-engineering** — Using a neural net when a logistic regression suffices
- **Silent degradation** — Complexity masks incremental rot

---

## Related Principles

- **Shadow Mode First** — Occam testing applies to shadow agents only
- **Fail-Closed Validation** — Missing complexity data raises, never defaults
- **Statistical Rigor** — Bootstrap CI, p-values, sufficient sample size
- **Data Quality Over Model Complexity** — Fix data before adding parameters

---

## Implementation Reference

See `docs/ideas/ai-occam-razor.md` for implementation details and `docs/plans/phases/100-occam-razor/` for execution plan.
