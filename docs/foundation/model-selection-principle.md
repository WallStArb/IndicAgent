# Model Selection Principle

**Version:** 1.2
**Status:** design
**Last Updated:** 2026-09-04

> *"Entities should not be multiplied beyond necessity."* — William of Ockham

**Status note (2026-09-04):** The principle itself (prefer the simpler model absent a statistically significant performance gap) is sound and durable — downgraded from `current` to `design` because the "Application in IndicAgent" integration below (Shadow Registry Occam gate, Composite Fitness Function, genetic infrastructure) was never implemented. No `occam`/`Occam`-named code, config, or test exists anywhere in the current tree; the only trace is planning docs for a phase originally called "100-occam-razor" in an older phase-numbering scheme (see Implementation Reference). Treat this doc as design intent, not a description of running code.

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
- `Performance` = Sharpe ratio, win rate, or other relevant metric
- `Complexity` = Parameter count × inference latency × training time
- `Penalty` = Tunable weight (default: 0.5)

---

## Application in IndicAgent

### Scope
- **Primary (dormant):** ML agents — `MLEvaluator` (`src/intelligence/ai/alpha/ml_scorer_agent.py`) exists in code but is part of the I8 AI stack, which has had zero commits since the v3.0 rebuild and whose services are `disabled`/`inactive` (see root `CLAUDE.md`'s Architecture note) — not confirmed-running
- **Secondary:** Technical indicators (if parameterized models with trainable weights)
- **Excluded:** Fixed-rule indicators (SMA, RSI) — complexity is static
- **Never built:** genetic agents / genetic infrastructure — no such code exists anywhere in the tree; this remains an unimplemented design idea, not a scoped-in future item with a concrete plan

### Integration Points (design intent — none of these three are wired into live code)
1. **Shadow Registry** — Occam evaluation would run before promotion
2. **Composite Fitness Function** — complexity penalty as one fitness component
3. **Genetic Infrastructure** — bloat prevention, parsimony encouragement

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

Never implemented. Planning docs exist under an older phase-numbering scheme ("100-occam-razor" — see `git log --oneline --all -i --grep=occam`), but no source file, config key, or test with "occam" or "genetic" in its name exists anywhere in the current tree, and the `.planning/phases/` directory referenced by a prior version of this doc no longer exists (`.planning/` now uses `.planning/milestones/`). Current phase 114 in the live numbering is an unrelated ensemble-measurement todo (`.planning/todos/completed/114-ensemble-measurement-missing-functional-slot.md`). Treat "Phase 114" as dead numbering — if this principle is ever built, it needs a fresh phase.
<!-- verified via repo-wide grep, 2026-09-04: zero matches for occam|genetic outside this doc and old planning history -->
