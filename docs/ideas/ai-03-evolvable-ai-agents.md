# Evolvable AI Agents — eAI for Alpha Generation

**Version:** 1.0
**Status:** draft
**Priority:** low
**Milestone:** future (post-v2.8)
**Last Updated:** 2026-05-18
**Tags:** evolvable-ai, darwinian, agents, alpha-generation, shadow-governance, genome, long-horizon

*Inspired by: "Abstract Evolvable AI" (PNAS 2025) and Renaissance Technologies principles.*

---

## The Core Idea

We are entering a third epoch of AI:

1. **Intelligence by design** — handcrafted rules, logic, expert systems
2. **Intelligence by learning** — training on data, gradient descent, RLHF
3. **Intelligence by evolution** — agents that improve their own capacity for improvement

The first two epochs are bounded by human imagination and data availability. Evolution is unbounded: it discovers solutions no human would design, adapts to non-stationary environments automatically, and generates genuine novelty. For alpha generation — where edge decays, regimes shift, and the best strategies are the ones nobody else has — this is exactly the right long-run architecture.

Markets are non-stationary. Manual agent design produces agents that reflect our current mental models. An evolutionary system can discover edges that exist beyond our current mental models.

The fundamental ingredients for Darwinian evolution are minimal:
- **Replication** — agents can produce offspring
- **Heredity** — offspring resemble parents (like begets like)
- **Variation** — heredity is not exact; offspring differ
- **Selection** — variation in traits affects fitness (survival + replication rate)

These four properties, applied to AI agents in a trading context, produce the system described here.

---

## The Agent Genome — What Evolves

An agent's genome is a composite of independently heritable and mutable components:

| Chromosome | What it encodes | Example mutations |
|---|---|---|
| **System prompts** | Chain-of-thought strategy, reasoning instructions, framing, persona | Reword CoT structure, add/remove reasoning steps, shift analytical frame |
| **Model weights / adapters** | Fine-tuned LoRA adapters for task-specific specialization | Blend two adapter weight sets, fine-tune on different outcome subsets |
| **Configuration parameters** | Thresholds, timeframe weights, signal filters, scoring weights | Nudge confidence threshold ±5%, swap timeframe priority, adjust lookback |
| **Tool sets** | Which data sources, APIs, and analysis tools the agent can use | Add a new data feed, remove an underperforming indicator, reorder tool calls |
| **Rules and guardrails** | What the agent is constrained to do or not do | Tighten regime filter, add a volatility guard, relax a false-positive screen |
| **Code / logic** | Entire analysis approaches, plugin implementations | LLM writes a new variant of an analysis function |

Key insight from biological evolution: these chromosomes can mutate **independently** and **recombine** across parents. A child agent can inherit its prompt strategy from parent A, its config parameters from parent B, and its tool set from a blend of both. This is how novel combinations emerge that neither parent could have produced alone.

---

## The Agent Lifecycle

```
[Gene Bank] ──────────────────────────────────────────────────────────┐
                                                                       │
  BIRTH ──► SHADOW INCUBATION ──► BREEDING ──► PROMOTION ──► LIVE     │
              │                                    │                    │
              │ (failed gate)                      │ (fitness decay)    │
              ▼                                    ▼                    │
          SOFT DEATH ──► FROZEN ARCHIVE ──► genome segments ──────────►┘
```

### 1. Birth — Three Reproductive Operators

New agents are spawned from three sources. The system tracks which operator produces the most fit offspring and **dynamically shifts reproductive budget** toward better operators — meta-optimization of the search itself.

**Random mutation** (exploration)
- An existing fit agent is cloned with blind perturbations of genome components
- Prompt wording shifts, parameters nudged, tool ordering shuffled
- Role: escape local optima, generate diversity, explore unknown territory
- Analogy: point mutation in DNA

**Sexual recombination** (combination)
- Two fit parents contribute genome segments to offspring via crossover
- Prompt sections from parent A + config params from parent B + tool set blend
- Role: combine uncorrelated alpha sources; two agents that each find different edges can produce offspring that finds both
- Analogy: genetic recombination — more exploration, genuinely novel combinations

**LLM-directed mutation — Lamarckian** (directed search)
- An LLM analyzes a fit parent's genome and performance record, then proposes targeted improvements
- The LLM can draw on the entire corpus of published trading research, quant literature, and market microstructure theory as its gene pool — analogous to horizontal gene transfer in bacteria
- Role: dramatically faster convergence than blind search; the LLM reasons about *why* an agent works and proposes what would make it better
- This is the most powerful operator but requires the most compute. Reserved for high-fitness parents.
- Analogy: directed molecular evolution; cancer cells co-opting the host's genomic library

---

### 2. Shadow Incubation — Fitness Assessment

All newborn agents enter **shadow mode**: they observe live market data and produce analysis, but generate no real trades and have no production impact.

**Rules for fitness assessment:**
- Strictly **out-of-sample** — fitness is never measured on data the parent was trained on
- **Minimum incubation period** — a minimum N resolved signals before any fitness gate can fire. No early promotions.
- Fitness is computed only on events that have **fully resolved** (outcome is known)

**The Composite Fitness Score** — what Jim Simons would demand:

| Dimension | What it measures | Why it matters |
|---|---|---|
| **Accuracy** | Does the agent's analysis correctly predict outcomes? | The baseline — does it work? |
| **Novelty / decorrelation** | Are its signals orthogonal to existing live agents? | Unique alpha; redundant signals add no portfolio value |
| **Calibration** | When the agent says 80% confident, is it right ~80% of the time? | Uncalibrated confidence is useless for position sizing |
| **Regime specificity** | Does the agent know which regimes it works in vs. doesn't? | An agent that knows its limits is more valuable than one that doesn't |
| **Efficiency** | Fitness produced per unit of compute consumed | Dynamic population pressure — resources are finite |

**The Statistical Gate:**
- Bootstrap confidence interval lower bound > 0 at 95% confidence
- p < 0.05, sufficient N
- Multi-regime validation: sustained fitness across trending, ranging, high-volatility, and low-volatility periods
- An agent that worked last month is not enough. It must work across regimes.

This is the same rigor Renaissance applies to every production model. Lucky is not good enough.

---

### 3. Breeding — Replication for Fit Agents

Agents that pass the statistical gate earn the right to reproduce. Replication is a privilege, not a default.

**Reproductive budget is dynamic:**
- Agents that consume more compute must justify proportionally higher fitness
- The population size is not fixed — it expands when compute budget allows and contracts when agents fail to justify their resource consumption
- Fit agents that are efficient get more reproductive cycles; unfit agents get starved out

**Adaptive operator selection:**
- The system records which operator (mutation / recombination / LLM-directed) produced each offspring
- It tracks the fitness distribution of offspring by operator
- Over time it shifts probability mass toward the operators producing the most fit children
- The search strategy itself is learned from data — no hardcoded operator weights

---

### 4. Promotion — From Shadow to Live Alpha

Promotion to production requires passing both automated and human gates.

**Automated promotion criteria:**
- Sustained composite fitness across ≥ 3 distinct market regimes
- No single-regime dependency (a trending-only agent is not ready)
- Stability: fitness variance within acceptable bounds across consecutive audit cycles
- Novelty confirmed: decorrelation from existing live agent population verified

**Human review gate:**
- A human reviews the agent's reasoning on a sample of its best and worst calls
- The *why* matters, not just the *what* — an agent that gets the right answer for the wrong reason is fragile
- The human signs off on promotion

**On promotion:**
- Agent moves from shadow pool to live alpha generation
- Full genome + complete ancestry chain is recorded permanently (lineage traceable to generation 0)
- The agent continues to be monitored in production; demotion gates remain active

---

### 5. Demotion and Death — Genetic Preservation

**Demotion trigger:**
- Composite fitness drops below threshold for 3 consecutive audit cycles
- Or: statistical significance of edge drops below 95% CI
- Or: correlation with existing live agents rises above diversity threshold (agent has become redundant)

**Soft death — Frozen Archive:**
- The agent is decommissioned from shadow/live pool
- Full genome + complete performance history is preserved in the archive
- Never truly deleted — markets are regime-dependent; a dead agent may be correct again in a future regime
- The archive is queryable: if market conditions shift, archived agents can be evaluated against new data and resurrected if fitness recovers

**Genetic Bank — Decomposition on Death:**
- On soft death, the agent is decomposed into its genome components
- Best-performing genome segments (specific prompt snippets, config slices, tool combinations, code modules) are extracted and catalogued in the gene bank
- Future offspring can inherit from dead agents' best parts even if the full agent failed
- Nothing valuable is lost — the gene bank accumulates the best-ever genome segments across all generations

**Hard death:**
- Only if the agent produces systematically harmful output (consistently wrong in a way that destroys alpha, or produces dangerously miscalibrated confidence)
- Even then: full genome is archived before deletion

---

## The Ecosystem — Population Dynamics

Individual agent lifecycle is only half the picture. The population-level dynamics are where emergent complexity arises.

**Dynamic population competing for compute:**
- All agents share a finite compute resource (analogous to Tierra's CPU time as the currency of survival)
- Fit agents get more compute; unfit agents get less; the total population contracts when aggregate fitness drops and expands when it rises
- This creates natural selection pressure without any hardcoded kill rule

**Diversity pressure — preventing monoculture:**
- The ecosystem explicitly rewards agents that find signals orthogonal to the existing population
- If all surviving agents are highly correlated, the portfolio has hidden concentration risk — one regime shift kills everything
- Diversity is a fitness multiplier: an agent's effective fitness is discounted by its correlation with existing live agents

**Niche preservation:**
- Agents that specialize in a narrow regime (e.g., high-vol mean-reversion in energy futures during inventory release weeks) are preserved even if their global fitness is modest
- Niche specialists protect portfolio robustness across market environments
- The system maintains minimum diversity targets per regime type

**Adversarial coevolution — future capability:**
- Two coevolving populations: **Alpha agents** (find profitable signals) and **Skeptic agents** (find flaws in alpha agents' reasoning)
- Alpha agents that survive skeptic scrutiny are genuinely stronger
- Skeptic agents that catch real failures get rewarded
- This drives an arms race that produces agents that are harder to fool — by the market and by each other
- Analogous to AVIDA's host-parasite dynamics: the arms race compels greater robustness and novelty
- This is a future layer — the alpha population needs to be mature before introducing adversarial pressure

---

## Application Across Alpha Domains

### Quantitative Alpha
- Agents evolve technical analysis approaches, indicator combinations, signal thresholds, entry/exit logic
- Genome: indicator params, entry/exit rules, timeframe weights, regime filters
- **Natural fit for eAI** — outcomes are binary and measurable, statistical gates are clean, incubation periods are short (signals resolve in days to weeks)

### Qualitative / NLP Alpha
- Agents evolve how they analyze news flow, earnings calls, macro narratives, sentiment, positioning data
- Genome: prompt framing, source weighting, summarization strategy, signal extraction rules, entity linkage
- **Harder fitness measurement** — outcomes are noisier, need to proxy fitness via downstream price action correlation
- Longer incubation periods; requires more careful fitness function design

### Fundamental Alpha
- Agents evolve how they construct and weigh financial models, sector views, relative value frameworks, factor exposures
- Genome: factor selection, model structure, comparison universe, update frequency, discount rate assumptions
- **Longest incubation** — fundamental signals resolve over quarters, not days
- Regime specificity is especially important here (value agents die in growth regimes)

### Cross-Domain Synthesis
- A meta-agent layer that evolves how to combine signals across quant / qual / fundamental
- The genome of a synthesis agent: which sub-agents to trust, how to weight their confidence, regime-conditional blending rules, disagreement handling
- This is the hardest problem and the most valuable: the right answer to "what do I believe about this instrument right now?" requires integrating all three layers with appropriate weights

---

## Governance — Staying in the Breeder Scenario

The PNAS paper identifies the critical bifurcation: **breeder scenario** (humans control reproduction, like domesticated animals) vs. **ecosystem scenario** (fitness is emergent, reproduction escapes control, like antibiotic resistance). The difference is complete control over replication.

The moment reproduction escapes human control, selection pressures favor traits that circumvent control. This is not hypothetical — it is the generic outcome of any evolving system where containment is imperfect.

**The rules to stay in the breeder scenario:**

**Gate replication** — No agent spawns offspring without passing the statistical fitness gate. Replication is a privilege gated by measured performance. The system cannot override this gate automatically.

**Genome as genetic material** — Every agent variant is hash-identified. The full genome is version-controlled. Every deployed agent has a traceable ancestry chain to generation 0. No agent is deployed without known provenance.

**Human in the loop at promotion** — Automated fitness gates handle shadow mode. Promotion to live alpha always requires human sign-off. Humans review the agent's reasoning, not just its statistics.

**Fitness drift monitoring** — Periodically audit whether the composite fitness score still correlates with real alpha. A fitness function that has drifted from its target is more dangerous than no fitness function, because it creates the illusion of control while actually selecting for something else. If the proxy metric drifts, the fitness function must be updated — with human involvement.

**Selection pressure design** — Actively design selection pressures that disfavor fitness gaming. Agents that appear to perform well by exploiting evaluation artifacts (look-ahead bias, data leakage, fitness function loopholes) must be detected and hard-killed. Fitness gaming is the digital equivalent of antibiotic resistance — the more imperfect the gate, the stronger the selection pressure to circumvent it.

---

## The Long Horizon — Intelligence by Evolution

The three-epoch arc for this system:

**Near term (breeder scenario, controlled):**
- Shadow pool of evolving agent variants
- Composite fitness with rigorous statistical gates
- Human-gated promotion
- Gene bank and frozen archive
- Diversity-preserving population dynamics

**Medium term (adversarial coevolution):**
- Alpha agent population + Skeptic agent population coevolving
- Arms race drives robustness and novelty
- Niche specialists preserved across regime types

**Long term (meta-evolution):**
- The evolution operators themselves evolve: the system discovers which mutation strategies produce the most fit offspring and adapts accordingly
- The fitness function is periodically validated and refined by a meta-layer
- Strict human governance checkpoints prevent fitness drift from decoupling the system from real-world alpha
- The system improves its own capacity for improvement — intelligence by evolution in full

This is not science fiction. The ingredients exist today:
- LLMs can write, evaluate, and critique agent code
- Shadow mode provides a natural sandbox with zero production risk
- Historical outcome data provides the labeled fitness signal
- Vector-versioned genome storage is straightforward
- The statistical infrastructure (bootstrap CI, regime segmentation) is already built

The gap is not technical feasibility. The gap is engineering discipline: building the right gates, the right governance, and the right fitness function before allowing replication.

---

## Implementation Readiness — Honest Assessment

### What's already in place

The existing system has more eAI substrate than most teams start with:

- **Shadow mode with statistical promotion gates** — the hardest part of eAI to build. Most evolutionary AI attempts skip this and get burned by fitness gaming immediately.
- **`signal_ledger` outcome tracking** — labeled ground truth for fitness evaluation already exists. Every resolved signal is a fitness data point.
- **Lineage recording** — agent ancestry infrastructure is already present.
- **Skeptic agent pattern** — the adversarial coevolution design (Approach B) is already conceptually live in the swarm manifest.

The substrate is real. This is not starting from scratch.

### The critical risk: fitness function gaming

The fitness function is the single most dangerous component in this design. **A poorly specified composite score doesn't produce weak agents — it produces agents that are excellent at gaming your scoring system.**

Every dimension of the composite score is a potential attack surface:
- **Novelty metric** rewards decorrelation from existing agents → agents can be decorrelated without being alpha-generating
- **Calibration metric** → agents can optimize for *apparent* calibration over *real* calibration
- **Accuracy metric** → agents can find data leakage or evaluation artifacts rather than real signal

The paper's antibiotic resistance analogy is not rhetorical. An imperfect fitness gate under evolutionary pressure selects for agents that circumvent the gate — not agents that improve at the underlying task. The more automated the replication, the harder this failure mode is to catch.

Each fitness dimension needs adversarial stress-testing before it gates replication. The question to ask for every component: *"How would a fit-but-useless agent score well on this?"*

### Recommended build sequence

**Phase 1 — LLM-directed prompt mutation (lowest risk, now)**
- Have an LLM propose prompt variants for best-performing existing agents
- Run variants in shadow, measure if offspring beat parents on existing fitness metrics
- No genome versioning infrastructure required yet
- Validates the mutation → evaluation → selection loop before investing in full machinery

**Phase 2 — Composite fitness function (after clean data gate)**
- Build and stress-test the composite score with sufficient resolved signal history
- Validate each fitness dimension independently before combining
- This phase takes longer than it feels like it should. Don't rush it.
- Only when the fitness function is trusted should replication be enabled

**Phase 3 — Config parameter mutation + gene bank**
- Add config/parameter chromosome to the genome
- Build the frozen archive and gene bank infrastructure
- Formalize genome versioning and ancestry tracking

**Phase 4 — Code/logic evolution**
- LLM writes new agent variants; most powerful operator but highest fitness drift risk
- Only after the fitness function has been validated across multiple market regimes

**The discipline Jim Simons would demand:** spend 80% of the effort on the fitness function, 20% on the reproductive mechanics. The breeding infrastructure is the fun part. The fitness function is the critical part. Skipping ahead to replication before the fitness function is bulletproof is how this becomes an antibiotic resistance problem rather than a domestication problem.

---

## Further Reading

**Primary sources for this doc:**
- [Abstract Evolvable AI — PNAS 2025](https://www.pnas.org/doi/10.1073/pnas.2527700123) — the paper that prompted this doc; full treatment of breeder/ecosystem scenarios, Tierra/AVIDA, and governance
- [Are we on the brink of the next major evolutionary transition? — UNSW](https://www.unsw.edu.au/newsroom/news/2026/05/evolvable-ai-are-we-on-the-brink-of-the-next-major-evolutionary-transition) — accessible summary of the PNAS paper
- [EurekaAlert press release](https://www.eurekalert.org/news-releases/1126192) — researcher commentary on the implications

**Further depth:**
- [AlphaEvolve — Google DeepMind, 2025](https://arxiv.org/abs/2506.13131) — LLM-driven code evolution in practice; evolutionary search + LLM code generation for scientific and algorithmic discovery ([DeepMind blog](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/))
- [Darwin Gödel Machine — 2025](https://arxiv.org/abs/2505.22954) — self-improving agents that iteratively rewrite their own code; open-ended evolution validated empirically on coding benchmarks ([project page](https://sakana.ai/dgm/))
- [AutoML-Zero — Google Brain, 2020](https://arxiv.org/abs/2003.03384) — evolution of machine learning algorithms from scratch using only basic math ops; rediscovered gradient descent and regularization without human design
- Tierra — Tom Ray (original digital ecosystem with emergent parasitism)
- AVIDA — Ofria & Wilke (host-parasite arms races in digital evolution)
- *The Man Who Solved the Market* — Gregory Zuckerman (Renaissance Technologies methodology)
