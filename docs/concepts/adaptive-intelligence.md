# Adaptive Intelligence

**Version:** 1.0
**Status:** current
**Last Updated:** 2026-05-30
**Tags:** adaptive-weighting, statistical-validation, signal-quality, feedback-loops

> Every component that influences a decision must earn that influence through statistical proof, and must lose it when evidence degrades.

## The Problem It Solves

A system with fixed weights and hardcoded thresholds degrades as market regimes shift. Parameters tuned on 2024 data will be wrong in 2026. A mean-reversion parameter calibrated during a low-volatility regime is dangerous in a high-volatility one. The naive solution — "re-tune annually" — requires manual intervention, introduces look-ahead bias in the tuning process, and misses intra-year regime changes entirely. The system must adapt continuously and autonomously.

## The Principle

Adaptation operates at three levels, each with its own feedback loop:

1. **Individual signals** — each signal goes through a shadow period before affecting production scoring. Promotion requires statistical proof of positive edge. Demotion is automatic when edge disappears.

2. **CIS weights** — the bucket weights that determine which evidence sources to trust are learned from signal outcomes, not manually set. They update as market behavior changes.

3. **Agents** — AI agents (swarm, narrative) start in shadow mode. They observe and produce analysis, but their outputs have no production impact until statistical gates are passed. Mutation and recombination (v2.8) extend this to agent parameter evolution.

The fitness dataset — `signal_events` + `trade_frames` + `trade_executions` — is the continuous learning signal for all three levels. It is never dropped.

## How IndicAgent Applies It

**Shadow governance lifecycle:**

```
1. SHADOW MODE   — Observe live data, produce outputs, zero production impact
2. EVALUATION    — Outcomes accumulate in signal_ledger
3. GATE          — n >= 100 resolved signals AND bootstrap_ci_lower(pnl_r) > 0.0 at 95%
4. PROMOTION     — Component gains production influence
5. LIVE          — Continuous monitoring continues; gate re-evaluated each cycle
6. DEMOTION      — EV[R] < -0.05 for 3 consecutive cycles → automatic disable
```

**Auto-enrollment:** `shadow_registry_ensure()` at service startup enrolls every I7 plugin and AI agent. Uses ON CONFLICT DO NOTHING — custom gate parameters in DB are never overwritten.

**CIS weight learning:** When `version > 0` exists in `cis_weights` table, the scorer loads it at startup. Logistic regression over signal outcomes per bucket produces version N+1 weights. Every CISResult carries `weights_version` — full traceability from score to weight set.

**Performance multipliers:** Rolling 30-day Sharpe and win rate per (setup_plugin, timeframe, symbol, regime). Sharpe-normalized rank produces `perf_multiplier` in [0.5, 1.5]. Gate: N < 30 → `perf_multiplier = 1.0` (neutral). No data = no advantage, not penalized.

**eAI genome mutations (v2.8):** `BaseAIWorker` subclasses with a `genome` parameter dict. Reproductive operators (mutation, crossover, selection) are applied between evaluation cycles. Shadow governance handles statistical gating before any mutant agent affects production.

**Key substrate (live now):**
- `shadow_registry` table — auto-enrollment, state tracking
- `signal_events` / `trade_frames` / `trade_executions` — fitness evaluation dataset (3-table schema)
- `signal_ledger` — JOIN view for backward-compat queries
- `LineageRecorder` — full ancestry per agent call
- `bootstrap_ci_lower()` — statistical gate in `src/core/stats_utils.py`
- `ShadowTransitionEvent` — promotion/demotion published to Kafka

## Invariants

- Nothing goes to production without `n >= 100` resolved signals AND positive bootstrap CI at 95%.
- Demotion is automatic — it cannot be overridden by configuration or manual DB edit.
- The fitness dataset (`signal_events` / `trade_frames` / `trade_executions`) is never dropped — no retention policy, ever.
- CIS weights must be version-tracked — `weights_version` column on every signal in `signal_events`.
- `N < 30` in `signal_metrics` means neutral multiplier (1.0), not penalized (< 1.0). Insufficient data is not evidence of poor performance.

## Recipe

When designing an adaptive system:

1. **Define your fitness metric before building.** What is the system trying to optimize? Sharpe ratio? Win rate above threshold? `pnl_r > 0` at 95% CI? The metric must be defined before the first component enters shadow mode.
2. **Separate observation from influence.** Shadow mode components observe live data and produce outputs, but those outputs do not affect decisions. This lets you measure real-world performance without risking real capital.
3. **Gate on sample size, not just metric value.** `pnl_r > 0` with `n=5` is noise. `pnl_r > 0` with `n=100` and `bootstrap_ci_lower > 0` is signal. Require both.
4. **Demotion must be automatic and inviolable.** If demotion can be overridden by configuration, it will be overridden during drawdowns — exactly when it should fire.
5. **Never drop the fitness dataset.** Signal outcomes are the ground truth. Without them, you cannot evaluate, cannot adapt, and cannot backtest future systems on historical data.
6. **Design for data accumulation requirements.** A component needs 100+ resolved signals before it can be evaluated. In low-volume environments, this can take months. Calibrate shadow periods to expected data arrival rates.

## See Also

- Implementation: `docs/intelligence/intelligence-ai.md` — shadow governance lifecycle, auto-enrollment, eAI substrate table
- Fitness dataset: `docs/intelligence/intelligence-foundation.md` — signal_ledger schema, CIS weight learning
- Research vision: `docs/research/ai-03-evolvable-ai-agents.md` — full eAI design
- v2.8 roadmap: `docs/research/eai-phase-recommendations.md` — genome mutations, fitness function, Phase 101-103
- Related concept: `docs/concepts/evidence-graded-signals.md` — CIS weight adaptation
- Related concept: `docs/concepts/swarm-intelligence.md` — agent shadow governance
