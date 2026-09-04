# Product Laws

**Version:** 1.1
**Status:** current
**Last Updated:** 2026-09-04

## Overview

Six philosophical and economic principles that govern product reality. These complement our Renaissance principles — they describe what we fight **against**; Renaissance principles describe what we fight **for**.

Originally sourced from an infographic on modern tech product challenges, particularly relevant in the AI era.

## The Laws

### 1. Pareto's Law (The 80/20 Rule)

**Core Idea:** 80% of your results come from 20% of your efforts or features.

**Product Context:** A handful of core features actually carry the value of your product and drive user engagement. The rest is often "noise" that adds technical debt and maintenance overhead.

**Brutal Truth:** Find the 20% that matters. Cut the rest before it cuts you.

**IndicAgent Manifestation:**
- "Instrument everything" — we can see which signals drive 80% of alpha
- `setup_performance` table gates on `sample_size >= 30` to promote only signals with proven impact
- Bootstrap aggregation promotes only features meeting statistical thresholds
- Shadow governance auto-enrolls at n>=100, demotes on performance decay

---

### 2. Goodhart's Law

**Core Idea:** When a measure becomes a target, it ceases to be a good measure.

**Product Context:** If you incentivize a team based on arbitrary metrics — like "number of story points completed," "features shipped," or "AI adoption rates" — the team will optimize for those exact numbers rather than making the product actually better.

**Brutal Truth:** Measure what changed for the user, not what left the factory.

**IndicAgent Manifestation:**
- "Earn promotion through proof (p<0.05, sufficient N)" — we track **outcome metrics** (pnl_r, mfe, mae), not **output metrics** (signals fired, features shipped)
- `signal_ledger` (v2.x Signal Ledger Architecture) captures full lifecycle outcomes, not just signal generation — archived, no live consumer as of 2026-07-02; the outcome-over-output discipline itself carries forward into v3.0's `alpha_events`/IC-engine path
- `setup_performance` tracks 30-day rolling stats, not point-in-time flashes
- LLM audit trail (`llm_calls` table) measures agent quality, not call volume

---

### 3. Sturgeon's Law

**Core Idea:** "90% of everything is crap."

**Product Context:** Originally coined by sci-fi author Theodore Sturgeon regarding literature, in product management it means most feature ideas are inherently bad or useless. AI makes generating this 90% cheaper to produce, making the noise even louder.

**Brutal Truth:** AI reduced the cost of building, not the cost of being wrong. The hardest part of product management is still figuring out what not to build.

**IndicAgent Manifestation:**
- "Resist overfitting" — simpler models that generalize beat complex models that memorize
- Shadow governance with promotion/demotion based on `bootstrap_ci_lower(pnl_r) > 0.0` (v2.x I1-I7 plugin-tier mechanism — archived, no live consumer as of 2026-07-02; the principle carries forward, the mechanism doesn't currently run)
- Every plugin starts in shadow mode; must earn promotion
- "Data quality over model complexity" — we bias toward clean data over fancy algorithms
- 132 plugins existed at v2.x's final inventory, only a fraction ever active at once — the whole tier is now archived rather than pruned live

---

### 4. Conway's Law

**Core Idea:** "You ship your org chart."

**Product Context:** Organizations tend to design systems that copy their own communication structures. If you have three disconnected engineering teams working on a single app, your users will likely experience a fragmented, disjointed user interface.

**Brutal Truth:** Fix the org chart before you fix the roadmap.

**IndicAgent Manifestation:**
- "Deterministic DAG topology" — every node does one thing, data flows one direction, no cycles
- "Modular microservices" — each service owns exactly one responsibility
- Separation of concerns: compute ≠ persistence ≠ transport
- Compute stages run DB-ignorant; dedicated Writers manage persistence (the v2.x I1-I7 tier that originated this pattern is now archived — the pattern lives on in v3.0's `FeatureVectorPipeline` → `FeatureVectorWriter` split)
- `_DAG_ORDER` in `services/service_auditor.py` is the single source of truth for service dependencies
- All stream keys via `stream_keys.py` — no hardcoded topic strings

---

### 5. Kidlin's Law

**Core Idea:** If you can write a problem down clearly, you're halfway to solving it.

**Product Context:** Many product teams rush to build solutions before they even understand the core user pain point or who they are building for.

**Brutal Truth:** Write the problem before the solution. Clarity beats smartness.

**IndicAgent Manifestation:**
- "Shadow mode first" — state the hypothesis, collect evidence, then ship
- "Empirical over theoretical" — if data says it works, it works; don't require a narrative
- Phase planning with `discuss-phase` before `plan-phase` — understand the problem before designing the solution
- `docs/plans/` capture the "why" before touching code
- `docs/foundation/glossary.md` — every domain term has exactly one definition; clarity through shared vocabulary

---

### 6. Brooks's Law

**Core Idea:** Adding manpower to a late software project makes it later (due to communication overhead and onboarding time).

**Product Context:** The infographic modernizes this by replacing "more people" with "AI." Throwing automated tools or AI assistance at a fundamentally broken, messy product process will not save it.

**Brutal Truth:** AI amplifies your operating system; it doesn't replace it.

**IndicAgent Manifestation:**
- "Let the system run" — automation over manual labor, but the process must be sound first
- "Automate manual tasks" — we identify and eliminate toil, but only after the underlying workflow is correct
- AI agents (I8 narrative) are designed to layer on top of the deterministic pipeline without replacing the DAG — but I8 itself is dormant-pending-design (zero commits since the v3.0 rebuild started, `alpha-swarm`/`narrative-compute` services `disabled`/`inactive`), so this is design intent, not current running behavior
- `BaseAIWorker` protocol enforces structure on AI output — real code, part of the same dormant I8 stack
- LLM audit trail (`llm_calls` table, `services/llm_writer.py`) — we measure AI quality, we don't assume it

---

## Synthesis

These six laws form a philosophical boundary around the codebase:

| Law | Guardrail | Violation Symptom |
|-----|-----------|-------------------|
| Pareto | Focus on proven 20% | Bloating with unused features |
| Goodhart | Track outcomes, not outputs | Gaming metrics, shipping without impact |
| Sturgeon | Earn promotion through proof | Auto-promoting everything AI generates |
| Conway | Single responsibility, DAG flow | Spaghetti code, circular dependencies |
| Kidlin | Write problem first | Building solutions to unclear problems |
| Brooks | Fix process before automating | Accelerating mess with AI |

## See Also

- [Renaissance Principles](principles.md) — What we fight for
- [Architecture DAG Topology](../architecture/architecture-dag-topology.md) — Conway in practice
- [Plugin System](../intelligence/CLAUDE.md) — Pareto and Sturgeon in signal selection
