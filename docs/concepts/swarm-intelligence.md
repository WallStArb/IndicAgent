# Swarm Intelligence

**Version:** 1.1
**Status:** design (dormant-pending-design, not confirmed running — see banner)
**Last Updated:** 2026-09-04
**Tags:** multi-agent, ensemble, specialist-agents, mixture-of-experts

> No single AI agent makes a decision — specialist agents each assess one dimension, and their outputs are composed into a calibrated multiplier.

> **Status note (2026-09-04):** This describes I8's target-state design, not currently-running
> production behavior. `BaseAIWorker`/`alpha_swarm`/`narrative_swarm` have had zero commits
> since the v3.0 rebuild started 2026-06-20, and both `indicagent-alpha-swarm` and
> `indicagent-narrative-compute` are `disabled`/`inactive` per `systemctl status` — dormant, not
> archived like the v2.x I1-I7 tiers. The design below is worth preserving as the intended
> shape if this stack is revived; treat every "How IndicAgent Applies It" claim below as intent,
> not observed behavior. Check `systemctl status` and `git log` before citing this as live.

## The Problem It Solves

A single LLM call cannot reliably synthesize multi-dimensional market intelligence. It lacks specialization — the same call that assesses momentum must also assess regime coherence, order flow, and historical analogs. Without adversarial checking, the model has no mechanism to catch its own overconfident conclusions. And confidence scores from a single model are uncalibrated: "87% confidence" has no empirical meaning without outcome data mapping scores to actual win rates.

## The Principle

Mixture of Agents (MoA): specialized agents each assess one analytical dimension independently. Their outputs are composed into a calibrated multiplier. No single agent makes a decision — the composite does. This mirrors how trading desks actually work: a fundamental analyst, a technician, a risk manager, and a devil's advocate each contribute a view, and the PM synthesizes them.

Independence is the key requirement. Agents that analyze the same dimension provide no benefit over a single agent. The adversarial agent (skeptic) is mandatory — without explicit challenge, a swarm of agreeing specialists produces groupthink, not confirmation.

## How IndicAgent Applies It

Five specialist agents form the Alpha Swarm:

| Agent | Dimension | Approach |
|-------|-----------|----------|
| `correlation` | Cross-asset correlation context | Compares signal to related instruments (VX, SPY, sector ETFs) |
| `regime_coherence` | Signal-regime alignment | Checks whether signal direction matches I4 regime consensus |
| `counterfactual` | Why this trade might fail | Generates the bear case for a bull signal (and vice versa) |
| `skeptic` | Adversarial review | Challenges all other agents' conclusions; mandatory for coevolution |
| `ml_scorer_v1` | Historical analog scoring | Local model (no LLM call), 50ms latency budget |

Each agent returns a score that feeds into a composite `swarm_multiplier`. The multiplier is applied to `calibrated_confidence` after all other calibration layers:

```
swarm_multiplier = f(correlation, regime_coherence, counterfactual, skeptic, ml_score)
adjusted_confidence = calibrated_confidence × swarm_multiplier
```

**Shadow governance:** Every swarm agent starts in shadow mode. It produces analysis but the output does not affect signal scoring until the statistical gate is passed (`n >= 100` resolved signals AND `bootstrap_ci_lower(pnl_r) > 0.0`). Current policy: discount-only — agents may reduce confidence but cannot boost above 1.0 until sufficient outcome data proves positive edge.

**Latency:** All LLM agents have `latency_budget_ms = 120,000` (120s). `ml_scorer_v1` is 50ms (local model). The effective Ollama model is set by `OLLAMA_MODEL` in `.env` (`nemotron-3-nano:4b` as of this writing — the `settings.py` code default `gemma4:e4b` is not pulled locally, so a missing `.env` entry breaks all LLM calls); design-time latency figures should be re-measured against whatever model is actually configured before being cited. Agents run non-blocking: swarm analysis is a confidence overlay, not a signal gate.

**Mandatory attribute:** Every `BaseAIWorker` subclass declares `prompt_version` from its `ACTIVE_VERSION` constant. Auto-injected into `llm_calls` for prompt A/B testing across the swarm.

## Invariants

- Swarm agents are discount-only until sufficient outcome data proves positive edge — they cannot boost confidence above the pre-swarm calibrated value.
- The skeptic agent must always be live. Adversarial coevolution requires a challenger; removing it collapses the swarm to agreeing specialists.
- `swarm_multiplier` is applied after all other calibration — it is the final adjustment, not an intermediate one.
- Every swarm agent call is persisted to `llm_calls` with full context. No silent failures.
- Agents **must** use `self._llm_generate(context, ...)` — never `self._llm.generate()` directly. Auto-injects audit context.

## Recipe

When designing a swarm intelligence system:

1. **Define specialization criteria before agent count.** Each agent should assess exactly one dimension that the others cannot. If two agents are assessing the same thing, merge them.
2. **Include an adversarial agent.** A swarm without a skeptic is a confirmation machine. The adversarial agent's job is to find the case for the opposite conclusion.
3. **Shadow mode before production.** New agents must demonstrate positive edge before their output affects decisions. The swarm is self-healing: agents that degrade are automatically demoted.
4. **Choose composition function carefully.** Averaging multipliers treats all agents equally. Weighting by historical accuracy introduces feedback bias. Start with equal weights and learn from outcome data.
5. **Design for latency asymmetry.** LLM agents are slow (50-120s). Local model agents are fast (<100ms). Compose them so the slow agents can be non-blocking without delaying the signal.
6. **Calibrate the multiplier range.** Discount-only until proven otherwise — positive edge must be demonstrated before boosting. Start the multiplier range at [0.5, 1.0] and only widen it after statistical validation.

## See Also

- Implementation: `docs/intelligence/intelligence-ai.md` — BaseAIWorker protocol, shadow governance, LLM audit trail
- Calibration: `docs/intelligence/intelligence-foundation.md` — calibration chain, swarm overlay position
- Code: `services/alpha_swarm_agent.py`, `src/intelligence/ai/alpha/`
- Related concept: `docs/concepts/adaptive-intelligence.md` — how shadow governance gates swarm agents
- Related concept: `docs/concepts/evidence-graded-signals.md` — how swarm multiplier relates to CIS calibration
