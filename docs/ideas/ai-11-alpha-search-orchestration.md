# Self-Directed Alpha Search: Population Orchestration

**Version:** 1.4
**Status:** draft
**Priority:** medium
**Milestone:** future (post-v2.8)
**Last Updated:** 2026-05-30
**Tags:** agents, swarm, multi-agent, population, alpha-discovery, dead-end-registry, self-organization, shadow-governance
**Inspired by:** [AutoScientists (arXiv 2605.28655)](https://arxiv.org/html/2605.28655v1)

---

## Context

The AutoScientists paper (May 2026) frames AI research as a population management problem: given a fixed compute budget, how do you maximize the rate of discovery across parallel hypothesis threads? Their key finding — single-agent systems follow linear trajectories and can't reorganize around shifting evidence. Multi-agent populations with shared state, structured critique, and explicit failure memory converge 1.9x faster and discover qualitatively better solutions under the same budget.

This is a standalone idea for IndicAgent's alpha discovery problem. It applies directly to today's shadow governance system and would also compose naturally with the eAI evolvable agent vision — but neither depends on the other.

The problem it solves: the pipeline learns from individual signal outcomes but has no mechanism to reason about its own research agenda. It doesn't know what it hasn't tried, why previous directions failed, or which axes are saturated vs. underexplored. Strategy exploration defaults to whatever a developer adds next.

---

## Core Pattern

Three-component loop:

```
Analyst Agents         → audit shadow performance; rank strategy axes by observed edge and novelty
Breeding Coordinator   → allocate shadow budget across directions and operators
Shared Research State  → live champion set, strategy ledger, critique forum, dead-end registry
```

**Discussion phase (before shadow entry):** analyst agents propose directions on a shared forum, critique each other's rationale, then converge on a ranked queue before shadow compute is committed.

**Dead-end registry:** explicit log of strategy directions that failed — prevents the system from repeatedly rediscovering the same unprofitable combinations under slightly different parameterizations.

**Noise-aware promotion:** a candidate must confirm edge on a second independent out-of-sample window before displacing the current champion — the walk-forward equivalent of the paper's "second seed" gate.

---

## Ideas

### 1. Analyst Agents

Today, signals enter shadow mode in developer-commit order. Analyst agents replace that implicit FIFO with a prioritized queue driven by observed market evidence.

**Proposed role:** Analyst agents continuously audit `shadow_registry` and `signal_ledger` for underexplored edges. They rank candidate directions by:

- **Historical edge** — Sharpe, win rate, MFE:MAE of signals in the same direction cluster
- **Regime alignment** — directions matching current market structure score higher
- **Novelty** — distance from already-explored parameter space; saturated axes deprioritized
- **Operator ROI** — which approach (parameter nudge vs. structural change vs. new combination) has produced the most fitness lift per shadow slot

The ranked queue drives which hypotheses enter shadow next. Shadow slots become a resource to allocate, not a free-for-all.

### 2. Dead-End Registry

**Problem:** When a signal fails shadow validation, the failure is recorded per-signal. But the underlying *strategy direction* — say, "SMC BoS + VWAP reclaim in low-volatility regime" — has no tombstone. A later session can rediscover the same direction under a slightly different parameterization, consuming shadow budget to re-learn the same structural failure.

**Proposal:** `alpha_dead_ends` table alongside `shadow_registry`:

```sql
CREATE TABLE alpha_dead_ends (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    direction     TEXT NOT NULL,          -- e.g. "smc_bos + vwap_reclaim, low-vol regime"
    evidence      JSONB NOT NULL,         -- n, win_rate, sharpe, regime_conditions, sample_period
    closed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    reopen_after  TIMESTAMPTZ             -- null = permanent; non-null = re-evaluate after regime shift
);
```

Analyst agents check this registry before proposing new shadow candidates. `reopen_after` handles regime-conditional failures — a direction that fails in trending may be viable in ranging; the registry records that distinction rather than permanently closing it.

### 3. Pre-Shadow Critique Forum

**Problem:** Signals enter shadow mode on statistical registration criteria alone. There is no adversarial review of the *strategic rationale* before shadow compute is committed.

**Proposal:** Before a direction is queued for shadow testing, run a structured critique pass — extending the existing `SkepticEvaluator` to a research-governance role:

```
Proposer    → strategy rationale, supporting edge evidence, expected regime scope
Skeptic     → overfitting risk, regime fragility, correlation with existing live signals, crowding
Verdict     → approve to queue / reject to dead-end / defer pending regime confirmation
```

Critique posts live in an `alpha_forum` table: auditable, queryable, feeds analyst agent context in future cycles. The key asymmetry: critique is one LLM pass; shadow evaluation is N bars of live evaluation. The gate pays for itself after a small number of avoided dead-end rediscoveries.

### 4. Noise-Aware Promotion Gate

**Existing:** Shadow governance promotes at `bootstrap_ci_lower(pnl_r) > 0.0` with `n >= 100`.

**Enhancement:** Before live promotion, require edge confirmation across two statistically independent out-of-sample windows. Candidates that pass shadow but fail confirmation are returned to shadow with a "conditional" flag rather than promoted — not a failure, just not yet confirmed. This is the walk-forward equivalent of the paper's second-seed gate: one additional evaluation window in exchange for a substantially lower false-positive rate on live promotion decisions.

### 5. Self-Organizing Search Workstreams

The paper's highest-order contribution: agent teams self-organize around high-potential axes as evidence accumulates, then dissolve and reform when edge degrades. Applied here: analyst agents run a periodic portfolio review of active shadow directions — which clusters show improving evidence, which are plateauing, which haven't been explored under the current regime. The output is a revised allocation of shadow slots: more capacity toward high-conviction emerging directions, less toward saturated ones.

This is the mechanism by which the system directs its own research agenda rather than following a developer-imposed roadmap.

---

## Relationship to eAI

This pattern and the eAI evolvable agent vision (`ai-03-evolvable-ai-agents.md`) address adjacent problems:

| | This doc | eAI |
|---|---|---|
| **What changes** | Which strategy directions to explore | The agent genomes themselves |
| **Selection unit** | Shadow signal direction | Agent genome |
| **Fitness evaluated on** | Signal outcomes (pnl_r, Sharpe) | Composite genome fitness (Phase 095) |
| **Memory of failure** | `alpha_dead_ends` (direction-level) | Gene bank (genome-level) |
| **Critique mechanism** | Pre-shadow forum (SkepticEvaluator) | Pre-breeding critique pass |

They are naturally additive: eAI defines *how* genomes evolve; this layer defines *where to search* across the genome space. When eAI reproductive operators are in place, the analyst agents here would read genome fitness rather than signal pnl_r — same orchestration pattern, richer substrate. But neither requires the other to deliver value independently.

---

## Integration Points

| Component | Where it lives | Current state |
|---|---|---|
| `shadow_registry` | DB | Exists |
| `signal_ledger` | DB | Exists |
| `SkepticEvaluator` | `src/intelligence/ai/` | Exists as runtime evaluator |
| `alpha_dead_ends` | DB | Does not exist |
| `alpha_forum` | DB | Does not exist |
| Analyst agent | new | Does not exist |
| Shadow budget cap | config | Does not exist — needed for prioritization to matter |

The dead-end registry and forum table are pure additions — no changes to existing shadow governance. The analyst agent is the novel piece. The shadow budget cap is a prerequisite: prioritization only matters when slots are finite.

---

## Open Questions

1. **Hypothesis sourcing:** Automated (analyst derives directions from fitness data) vs. human-seeded (developer queues, analyst prioritizes). Human-seeded is the pragmatic starting point; full automation is the vision.
2. **Regime-scoped dead ends:** `reopen_after` is a time proxy for regime change. The proper solution is regime-keyed dead-end entries — a direction that fails trending gets a tombstone conditioned on trending, not a blanket close.
3. **Shadow budget cap:** Without a finite cap, the prioritization queue has no teeth. What is the right population size? This needs a decision before the analyst agent can allocate meaningfully.
4. **Forum latency:** Critique pass adds latency before shadow entry. Acceptable — shadow evaluation is orders of magnitude more expensive than a single LLM critique.

---

## Renaissance Lens

What Jim Simons and the Medallion team would make of this architecture — strengths they'd endorse, weaknesses they'd attack, and additions they'd demand.

### Strengths They'd Endorse

**Dead-end registry is the most Renaissance idea here.** Medallion maintained rigorous institutional memory of what didn't work, precisely to prevent re-exploring exhausted directions. Most quant shops don't do this — they rediscover the same failures repeatedly as researchers turn over. Explicit failure cataloging is a durable competitive advantage.

**Decorrelation-aware analyst ranking.** Simons' core insight was that the edge comes from combining many small uncorrelated signals, not finding one great signal. An analyst agent that deprioritizes saturated axes and seeks genuinely novel directions is solving the right optimization problem. Most systems optimize signal quality in isolation; this optimizes portfolio contribution.

**Regime-conditional failure memory.** The `reopen_after` mechanism acknowledges that alpha is non-stationary — a direction that failed in 2022 trending markets may be valid in 2025 ranging markets. Renaissance treats regime conditioning as foundational, not an afterthought.

**Population-level memory over per-signal memory.** Tracking failure at the *direction* level rather than the *signal instance* level is the right abstraction. Instances are noise; directions are information.

**Fixed-budget allocation as a forcing function.** Treating shadow slots as a finite resource to allocate is correct. Without scarcity, prioritization has no teeth and the system degenerates to FIFO.

---

### Weaknesses They'd Attack

**Multiple testing correction is missing — this is the critical gap.** The current shadow gate (`bootstrap_ci_lower > 0.0, n >= 100`) does not account for how many hypotheses have been tested against the same historical data. The more directions you test, the lower your significance threshold must be. Without Bonferroni correction or FDR control applied at the *population* level, the system will accumulate p-hacked signals that look valid individually but represent false discoveries in aggregate. Renaissance is obsessive about this. The analyst agent must track total hypothesis count and tighten the promotion bar as the search space is explored.

**Novelty score is a proxy, not the target.** Parameter-space distance is a rough stand-in for what Medallion actually wants: zero correlation with the existing live signal book. A direction that's novel in parameter space can still be correlated with three existing signals and add nothing to the portfolio. The analyst agent's novelty dimension should be the mutual information of the candidate against the current signal portfolio — a real decorrelation measure, not a distance heuristic.

**No capacity modeling before shadow entry.** Every signal must be evaluated for market impact and capacity before consuming shadow budget. A direction with strong edge but tiny capacity — gets crowded on entry, moves the market — is worthless at scale. Medallion famously killed signals that couldn't scale. The pre-shadow critique pass should include a capacity/turnover estimate as a quantitative gate, not an afterthought.

**LLM narrative critique is qualitatively weak.** Renaissance is deeply skeptical of qualitative reasoning. An LLM writing prose about "regime fragility" or "crowding risk" introduces exactly the narrative bias an automated system is supposed to eliminate. The critique forum structure is right; the output discipline is wrong. Every Skeptic output should be a structured quantitative score — failure-mode probabilities, not free-text rationale. The SkepticEvaluator already produces scored output at runtime; the governance role should hold the same standard.

**Human-seeded hypothesis sourcing is a liability.** The "developer adds to queue" starting point is pragmatic but introduces cognitive bias into the hypothesis funnel — the same biases an automated system exists to circumvent. Renaissance would treat this as a phase-zero state to eliminate as fast as possible, not a stable operating mode.

---

### Additions They'd Demand

**1. Information decay curves.** Medallion tracks how quickly alpha decays as signals become known or market structure shifts. The dead-end registry should distinguish *structurally dead* (edge never existed — likely a false discovery) from *decayed* (edge existed, now arbitraged away). Decayed directions are candidates for revival with fresh data or updated parameters; structurally dead ones are not. `reopen_after` is a time proxy; the real thing is a decay model fit to historical edge degradation curves per direction cluster.

**2. Independent replication gate.** Simons required independent replication of every result before production deployment — two separate teams or systems arriving at the same conclusion from different starting points. In this architecture: before live promotion, require that two independently seeded analyst agents both rank the direction as high-conviction. One agent's endorsement is a result; two independent endorsements are evidence.

**3. Bayesian prior over the search space.** Rather than treating all unexplored directions as equally promising, maintain a Bayesian prior over which axes are likely to yield edge — updated continuously as shadow results accumulate. Directions in high-prior regions deserve more budget; low-prior regions (where theory suggests no edge exists) deserve less. This is how Medallion concentrates search effort intelligently rather than exploring uniformly.

**4. Regime transition detection as a research trigger.** When the system detects a regime shift, the dead-end registry should automatically flag directions closed under the previous regime as candidates for re-evaluation. Don't wait for `reopen_after` to expire — regime change is the signal. This connects the research agenda directly to the market structure detection already in the I5 pipeline.

**5. Quantitative critique scorecard.** Replace free-text SkepticEvaluator output in the governance role with a mandatory structured scorecard:

```json
{
  "overfitting_probability": 0.0–1.0,
  "regime_fragility_score": 0.0–1.0,
  "capacity_estimate_usd": <number>,
  "portfolio_correlation": 0.0–1.0,
  "multiple_testing_adjusted_pvalue": <number>,
  "verdict": "approve | reject | defer"
}
```

Every field is a number. Verdict is derived from thresholds, not LLM judgment. Rationale prose is optional metadata, never the decision input.

---

### Net Assessment

Renaissance would view the core architecture — population-level search with institutional failure memory — as directionally correct and meaningfully ahead of how most systematic shops manage their research agenda. The dead-end registry and decorrelation-aware ranking would be immediately recognizable as sound.

They'd also view the current spec as naive in execution: the statistical rigor (multiple testing), the capacity discipline, and the quantitative output standards are all missing. A Medallion researcher reading this doc would say "right problem, wrong tools in three places." The additions above are the gap.

The eAI composability is a long-term asset. A static signal portfolio and an evolving genome population both need a population orchestration layer — the same analyst agent architecture serves both. That's good design.

---

## Related Docs

- `ai-03-evolvable-ai-agents.md` — eAI vision: genome, lifecycle, reproductive operators
- `eai-phase-recommendations.md` — eAI phase roadmap and fitness function design
- `ai-09-agent-orchestration-patterns.md` — MoA and adversarial patterns at signal evaluation time
- `ai-05-intelligence-swarm-manifest.md` — current alpha swarm architecture
