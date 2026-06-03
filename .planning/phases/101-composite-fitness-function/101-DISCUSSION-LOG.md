# Phase 101: Composite Fitness Function - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-02
**Phase:** 101-composite-fitness-function
**Areas discussed:** agent_fitness schema, Composite formula, Integration architecture, Novelty signal

---

## agent_fitness schema

| Option | Description | Selected |
|--------|-------------|----------|
| TimescaleDB hypertable | One row per (agent_id, evaluated_at). Full history. Variance gate computable from raw history. | ✓ |
| Snapshot table | One row per agent, updated in-place. Simpler but loses history. | |
| Both | Snapshot + hypertable. Dual-write complexity, inconsistency surface. | |

**User's choice:** Deferred to Renaissance council judgment
**Notes:** User consistently asked for Jim Simons / RenTech-level architectural reasoning. Decision: hypertable is correct because (1) TimescaleDB is already the time-series store, (2) historical fitness is signal for Phase 102 gene extraction, (3) latest row gives current state — no separate snapshot table needed. Variance gate uses DISTINCT ON latest row per agent.

**Sub-question: variance gate computation**

| Option | Description | Selected |
|--------|-------------|----------|
| Latest scores only | stddev of current composite per agent | ✓ |
| Rolling 3-cycle average per agent | Smoothed, more complex join | |

**Notes:** Latest scores answer "does the fitness function discriminate right now?" — rolling averages introduce look-back bias into a population-level gate. Per-agent stability (last 3 cycles) is a separate orthogonal gate.

---

## Composite formula

| Option | Description | Selected |
|--------|-------------|----------|
| Geometric mean | `(accuracy × novelty × calibration × regime × efficiency)^(1/5)`. Zero collapses all. | ✓ |
| Weighted linear sum | Allows strong accuracy to compensate for poor calibration. | |
| Min-threshold-then-average | Floor per dimension, then average. | |

**User's choice:** Deferred to Renaissance council judgment
**Notes:** Geometric mean is non-negotiable because calibration and novelty are structural requirements, not optimization targets. An uncalibrated agent is dangerous for position sizing regardless of accuracy. A correlated agent adds zero portfolio value. No compensation logic. Composite not emitted until all 5 dimensions clear minimum N.

**Sub-question: per-dimension minimum N**

| Option | Description | Selected |
|--------|-------------|----------|
| Conservative | accuracy 50, calibration 30, regime 10/regime × 2 min, efficiency 20 | ✓ |
| Aggressive | accuracy 30, calibration 20, regime 5/regime × 2, efficiency 10 | |

**Notes:** Conservative thresholds prevent false promotion from lucky short runs. All stored as `FITNESS_*` constants in Settings.

---

## Integration architecture

| Option | Description | Selected |
|--------|-------------|----------|
| New fitness_auditor.py | Separate oneshot script; shadow_auditor reads agent_fitness | ✓ |
| Extend shadow_auditor.py in-place | God object: analytics + lifecycle mixed | |
| PromotionGate/DemotionGate classes | Pure classes; still needs a home for computation | |

**User's choice:** Deferred to Renaissance council judgment
**Notes:** SoC principle: fitness computation (analytics DAG) and shadow governance (lifecycle state machine) are different concerns. `fitness_auditor.py` → `agent_fitness` → `shadow_auditor.py` is a clean DAG. PromotionGate/DemotionGate are pure stateless classes callable from shadow_auditor, fully testable in isolation.

---

## Novelty signal

| Option | Description | Selected |
|--------|-------------|----------|
| Pearson r on pnl_r vectors | Measures actual alpha redundancy, not analytical agreement | ✓ |
| Confidence score vectors | Measures "do agents agree?" — not the right question | |
| Long/short direction vectors | Too coarse; directional agreement ≠ PnL correlation | |

**User's choice:** Deferred to Renaissance council judgment
**Notes:** pnl_r is ground truth. Two agents can agree on analysis but produce uncorrelated outcomes — that IS unique alpha. Minimum 20 overlapping resolved signals for r to be meaningful; below 20 = 0 penalty (benefit of doubt). Population size 1 = novelty 1.0 by definition.

---

## Claude's Discretion

- Specific normalization function per dimension (sigmoid vs. clamp-and-normalize for Sharpe→accuracy, etc.)
- Whether efficiency uses `tokens_est` alone or combines with `latency_ms`
- Systemd unit name and timer interval for `fitness_auditor`

## Deferred Ideas

- Adversarial coevolution (skeptic vs. alpha agents) — post-Phase-103
- Adaptive operator selection — Phase 103
- Fitness UI / operator annotation interface — future phase
- LLM-directed fitness interpretation — future layer
