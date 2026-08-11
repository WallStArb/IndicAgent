# Model Selection Principle

**Version:** 1.0 (portable)
**Status:** template
**Source:** genericized from IndicAgent `docs/foundation/model-selection-principle.md` v1.1

> *"Entities should not be multiplied beyond necessity."* — William of Ockham

---

## Principle

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
- `Performance` = whatever metric the domain cares about (Sharpe ratio, win rate, accuracy, F1, latency-adjusted throughput — pick one per model class and hold it fixed)
- `Complexity` = parameter count × inference latency × training time
- `Penalty` = tunable weight (default: 0.5)

---

## Application

### Scope
- **Primary:** any learned model with tunable parameters (ML models, genetic/evolutionary agents, learned scoring functions)
- **Secondary:** parameterized deterministic models with trainable weights
- **Excluded:** fixed-rule components with no trainable parameters — complexity is static, there's nothing to penalize

### Integration Points
1. **Shadow registry / gate** — Occam evaluation runs before promotion to production
2. **Composite fitness function** — complexity penalty is one fitness component, not a hard veto
3. **Evolutionary/genetic infrastructure, if present** — prevents parameter bloat, encourages parsimony

### Failure Modes
- **Overfitting:** Complex model memorizes training data, fails in production
- **Data dredging:** Adding parameters until significance appears by chance
- **Maintenance burden:** Complex models are harder to debug and update

### Guardrails
- All Occam tests are shadow-only — never blocks production directly
- Rejection is reversible — if conditions change, re-evaluate
- Complexity scores are logged and auditable
- Human operator can override with documented justification

---

## Renaissance Rationale

### Why This Matters

1. **Data Integrity** — Simpler models are less likely to overfit. When a model memorizes noise rather than signal, it degrades decision quality.

2. **Operational Robustness** — A model with 10 parameters fails in 10 ways. A model with 1000 parameters fails in 1000 ways. Renaissance systems minimize failure modes.

3. **Computational Efficiency** — Complexity costs money. Latency matters. Training time matters. Memory footprint matters.

4. **Regime Adaptation** — Simple models adapt faster to changing conditions. Complex models carry more historical baggage.

5. **Debuggability** — When a linear model fails, you inspect coefficients. When a neural net fails, you shrug.

### What This Prevents

- **Parameter bloat** — genetic algorithms or hyperparameter searches that grow without bound
- **Redundant features** — 500 features when 50 explain 95% of variance
- **Over-engineering** — using a neural net when a logistic regression suffices
- **Silent degradation** — complexity masks incremental rot

---

## Related Principles

- **Shadow Mode First** — Occam testing applies to shadow-only candidates
- **Fail-Closed Validation** — missing complexity data raises, never defaults
- **Statistical Rigor** — bootstrap CI, p-values, sufficient sample size
- **Data Quality Over Model Complexity** — fix data before adding parameters

---

## Adopting This in a New Project

Copy this file verbatim. Fill in your project's actual `Performance` metric and where the gate lives (a promotion pipeline, a CI check, a manual review step) in a new "Implementation Reference" section at the bottom — don't invent a phase number or file path before the integration actually exists.
