# Product Laws

**Version:** 1.0 (portable)
**Status:** template
**Source:** genericized from IndicAgent `docs/foundation/product-laws.md`

## Overview

Six philosophical and economic principles that govern product reality. These complement [Renaissance Principles](principles.md) — they describe what you fight **against**; Renaissance principles describe what you fight **for**.

Originally sourced from an infographic on modern tech product challenges, particularly relevant in the AI era.

## The Laws

### 1. Pareto's Law (The 80/20 Rule)

**Core Idea:** 80% of your results come from 20% of your efforts or features.

**Product Context:** A handful of core features actually carry the value of your product and drive user engagement. The rest is often "noise" that adds technical debt and maintenance overhead.

**Brutal Truth:** Find the 20% that matters. Cut the rest before it cuts you.

**Example Manifestation** (replace with your own before shipping this doc):
- "Instrument everything" — measure enough to actually see which components drive most of the value.
- A gating rule that requires a minimum sample size before promoting anything to production.
- Bootstrap aggregation or similar statistical gating promotes only components meeting a proven threshold.
- Auto-enrollment into a shadow/trial state at a minimum sample size, with auto-demotion on decay.

---

### 2. Goodhart's Law

**Core Idea:** When a measure becomes a target, it ceases to be a good measure.

**Product Context:** If you incentivize a team based on arbitrary metrics — like "number of story points completed," "features shipped," or "AI adoption rates" — the team will optimize for those exact numbers rather than making the product actually better.

**Brutal Truth:** Measure what changed for the user, not what left the factory.

**Example Manifestation:**
- "Earn promotion through proof (p<0.05, sufficient N)" — track **outcome metrics**, not **output metrics** (things shipped).
- A full-lifecycle ledger capturing outcomes, not just generation events.
- Rolling-window performance stats, not point-in-time flashes.
- An audit trail that measures quality, not call/event volume.

---

### 3. Sturgeon's Law

**Core Idea:** "90% of everything is crap."

**Product Context:** Originally coined by sci-fi author Theodore Sturgeon regarding literature, in product management it means most feature ideas are inherently bad or useless. AI makes generating this 90% cheaper to produce, making the noise even louder.

**Brutal Truth:** AI reduced the cost of building, not the cost of being wrong. The hardest part of product management is still figuring out what not to build.

**Example Manifestation:**
- "Resist overfitting" — simpler models that generalize beat complex models that memorize.
- Shadow governance with promotion/demotion based on a statistically-defensible metric, not intuition.
- Every new candidate starts in shadow mode; must earn promotion. See [unified-concept-registry.md](unified-concept-registry.md).
- "Data quality over model complexity" — bias toward clean data over fancy algorithms.
- Many candidates may exist in the registry, but only a fraction are active at any time.

---

### 4. Conway's Law

**Core Idea:** "You ship your org chart."

**Product Context:** Organizations tend to design systems that copy their own communication structures. If you have three disconnected engineering teams working on a single app, your users will likely experience a fragmented, disjointed user interface.

**Brutal Truth:** Fix the org chart before you fix the roadmap.

**Example Manifestation:**
- "Deterministic DAG topology" — every node does one thing, data flows one direction, no cycles.
- "Modular microservices" — each service owns exactly one responsibility.
- Separation of concerns: compute ≠ persistence ≠ transport.
- Compute runs DB-ignorant; writers manage persistence. See [design-principles.md](design-principles.md) §2-3.
- A single canonical service-dependency registry as the source of truth.
- All topic/key strings via a central module — no hardcoded strings.

---

### 5. Kidlin's Law

**Core Idea:** If you can write a problem down clearly, you're halfway to solving it.

**Product Context:** Many product teams rush to build solutions before they even understand the core user pain point or who they are building for.

**Brutal Truth:** Write the problem before the solution. Clarity beats smartness.

**Example Manifestation:**
- "Shadow mode first" — state the hypothesis, collect evidence, then ship.
- "Empirical over theoretical" — if data says it works, it works; don't require a narrative.
- A discuss-the-problem step before a design/plan step — understand the problem before designing the solution.
- Planning docs capture the "why" before touching code.
- A glossary where every domain term has exactly one definition; clarity through shared vocabulary.

---

### 6. Brooks's Law

**Core Idea:** Adding manpower to a late software project makes it later (due to communication overhead and onboarding time).

**Product Context:** The infographic modernizes this by replacing "more people" with "AI." Throwing automated tools or AI assistance at a fundamentally broken, messy product process will not save it.

**Brutal Truth:** AI amplifies your operating system; it doesn't replace it.

**Example Manifestation:**
- "Let the system run" — automation over manual labor, but the process must be sound first.
- "Automate manual tasks" — identify and eliminate toil, but only after the underlying workflow is correct.
- AI agents are layered on top of a deterministic pipeline — they don't replace the DAG.
- A structured-output protocol enforces structure on AI output — AI amplifies intelligence within guardrails.
- An audit trail measures AI quality; quality is never assumed.

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

- [Renaissance Principles](principles.md) — What you fight for
- [Design Principles](design-principles.md) — Conway in practice
- [Unified Concept Registry](unified-concept-registry.md) — Pareto and Sturgeon in candidate selection

---

## Adopting This in a New Project

Copy the six laws and the synthesis table verbatim — they're fully domain-agnostic as framing. Replace every "Example Manifestation" bullet list with your own project's real examples once you have them, the same way [musk-5-step-process.md](musk-5-step-process.md) recommends. Don't invent hypothetical manifestations.
