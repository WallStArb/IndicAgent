# Adaptive Intelligence

**Version:** 2.0
**Status:** current
**Last Updated:** 2026-09-04
**Tags:** adaptive-weighting, statistical-validation, evidence-gated-lifecycle, feedback-loops

> Every component that influences a decision must earn that influence through statistical proof, and must lose it when evidence degrades.

> **v2.x → v3.0 note:** The original substrate for this principle — `signal_events` /
> `trade_frames` / `trade_executions`, `shadow_registry_ensure()`, CIS weight learning — was the
> I7 plugin-tier adaptive-weighting system. That whole stack is ARCHIVED, no live consumer since
> 2026-07-02. The principle survived the rebuild; its live substrate today is the **Unified
> Concept Registry** (UCR — `docs/foundation/unified-concept-registry.md`), which governs feature
> and ensemble-strategy promotion in the v3.0 pipeline. The AI-agent tier of this principle
> (level 3 below) has no live successor yet — I8 (`alpha_swarm`/`narrative_swarm`) is
> dormant-pending-design, zero commits since 2026-06-20, both services disabled/inactive.

## The Problem It Solves

A system with fixed weights and hardcoded thresholds degrades as market regimes shift. Parameters tuned on 2024 data will be wrong in 2026. A mean-reversion parameter calibrated during a low-volatility regime is dangerous in a high-volatility one. The naive solution — "re-tune annually" — requires manual intervention, introduces look-ahead bias in the tuning process, and misses intra-year regime changes entirely. The system must adapt continuously and autonomously.

## The Principle

Adaptation operates at two live levels today, plus one dormant level carried over from the v2.x design:

1. **Features and ensemble strategies** — each concept (a `FeatureVector` field, or an ensemble weighting strategy) goes through a `candidate` → `shadow_only` stage before affecting production scoring. Promotion to `active` requires statistical proof of positive edge over the current baseline. Demotion to `deprecated` is automatic when edge disappears or a challenger wins repeatedly.

2. **AI agents (dormant)** — the v2.x design called for `alpha_swarm`/`narrative_swarm` agents to start in shadow mode, observe and produce analysis with zero production impact until statistical gates passed, with mutation/recombination (v2.8 "eAI") extending this to agent parameter evolution. This tier has no live implementation as of this writing — I8 is target-state, not confirmed-running.

The fitness signal for level 1 — IC (information coefficient) measured against `forward_returns.return_type = 'executable_open_to_open'` — is the continuous learning signal. Nothing is measured on unexecutable (theoretical) returns.

## How IndicAgent Applies It

**Concept lifecycle (Unified Concept Registry, live):**

```
1. CANDIDATE      — Concept exists in concept_registry, not yet measured against a baseline
2. SHADOW_ONLY     — Measured, not yet winning consistently, or gate gap not yet met
3. COMPARISON      — ops_ensemble_weight_compare.py (ensemble_strategy) or ic_engine.py's
                      post-run lifecycle hook (feature) runs an A/B win-decision against the
                      current baseline, deterministically -- no LLM in the path
4. GATE            — min_promotion_consecutive wins in a row, AND min_new_observations of
                      fresh evidence since the last eval, AND (if the concept requires it)
                      BH-FDR multiplicity correction proven to have run and survived
5. PROMOTION       — CAS (compare-and-swap) status flip candidate/shadow_only → active,
                      logged to concept_transition_log with trigger_reason
6. ACTIVE          — Continuous monitoring; re-evaluated each comparison round
7. DEMOTION        — demotion_performance / demotion_decay / demotion_redundancy →
                      deprecated (operator_override is the only human-triggered path to
                      deprecated; automated paths never target it)
```

**The one code path rule (Invariant 1):** `ConceptRegistryService.record_comparison_outcome()` is the ONLY code path that flips an *existing* concept's `status`. No LLM, no proposer override, ever. The pure decision core (`decide_comparison_action()`) is unit-tested without a DB connection; the service wraps it in one transaction with a `FOR UPDATE` row lock and a compare-and-swap status write. Migration-time genesis seeding (a new `FeatureVector` field's `concept_registry` row landing pre-populated as `status='active'`) is the sole exception — that's schema-definition-time DDL, not a runtime lifecycle transition.

**Gate parameters are APR-resolved**, not hardcoded — a per-concept `concept_gate` override when non-NULL, else the domain default under `alpha.concept_registry.<domain>_*`.

**Key substrate (live now):**
- `concept_registry` / `concept_gate` / `concept_transition_log` / `concept_annotation` / `concept_parent` tables
- `ConceptRegistryService` (`src/intelligence/concept_registry_service.py`) — sole status-flip authority
- `ops_ensemble_weight_compare.py` — drives `domain='ensemble_strategy'` comparisons (async)
- `ic_engine.py`'s post-run lifecycle hook — drives `domain='feature'` comparisons (sync, `record_transition_sync()`)
- `bootstrap_ci_lower()` / IC confidence-interval gating — statistical gate in `src/core/stats_utils.py`

**Key substrate (dormant, I8 — described for historical/design continuity only):**
- `shadow_registry` table, `shadow_registry_ensure()` auto-enrollment
- `LineageRecorder` — full ancestry per agent call
- `ShadowTransitionEvent` — promotion/demotion published to Kafka
- eAI genome mutations: `BaseAIWorker` subclasses with a `genome` parameter dict; reproductive operators (mutation, crossover, selection) applied between evaluation cycles

## Invariants

- Nothing is promoted to `active` without clearing the concept's `concept_gate` (consecutive wins, minimum new evidence, and FDR proof where required).
- Demotion reasons are a closed, DB-enforced vocabulary (`concept_transition_log.trigger_reason` CHECK constraint) — `promotion`, `demotion_performance`, `demotion_decay`, `demotion_redundancy`, `operator_override`, `parent_cascade`, `candidate_timeout`, `implementation_change`, `genesis_seed`. A typo'd reason raises a Python `ValueError` before it can hit the DB constraint mid-transaction.
- `deprecated` is operator-only — no automated comparison outcome ever targets it.
- IC measurement is executable-returns-only (`return_type = 'executable_open_to_open'`) — theoretical close-to-close returns overstate IC by capturing untradeable overnight gaps.
- (Dormant, I8) `N < 30` in `signal_metrics` was designed to mean neutral multiplier (1.0), not penalized — insufficient data is not evidence of poor performance. No live consumer of this rule today.

## Recipe

When designing an adaptive system:

1. **Define your fitness metric before building.** What is the system trying to optimize? Sharpe ratio? Win rate above threshold? `pnl_r > 0` at 95% CI? The metric must be defined before the first component enters shadow mode.
2. **Separate observation from influence.** Shadow mode components observe live data and produce outputs, but those outputs do not affect decisions. This lets you measure real-world performance without risking real capital.
3. **Gate on sample size, not just metric value.** `pnl_r > 0` with `n=5` is noise. `pnl_r > 0` with `n=100` and `bootstrap_ci_lower > 0` is signal. Require both.
4. **Demotion must be automatic and inviolable.** If demotion can be overridden by configuration, it will be overridden during drawdowns — exactly when it should fire.
5. **Never drop the fitness dataset.** Signal outcomes are the ground truth. Without them, you cannot evaluate, cannot adapt, and cannot backtest future systems on historical data.
6. **Design for data accumulation requirements.** A component needs 100+ resolved signals before it can be evaluated. In low-volume environments, this can take months. Calibrate shadow periods to expected data arrival rates.

## See Also

- Live substrate: `docs/foundation/unified-concept-registry.md` — full UCR spec, invariants, domain coverage
- Research vision (dormant tier): `docs/research/ai-03-evolvable-ai-agents.md` — full eAI design
- v2.8 roadmap (dormant tier): `docs/research/eai-phase-recommendations.md` — genome mutations, fitness function, Phase 101-103
- Related concept: `docs/concepts/evidence-graded-signals.md` — evidence-gated promotion
- Related concept: `docs/concepts/swarm-intelligence.md` — agent shadow governance (dormant)
