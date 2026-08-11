# Musk's 5-Step Design Process

**Version:** 1.0 (portable)
**Status:** template
**Source:** genericized from IndicAgent `docs/foundation/musk-5-step-process.md` v1.0

## Overview

Developed by Elon Musk at SpaceX to fundamentally rethink how products and systems are built. The framework is not a checklist of independent ideas — the **order is the insight**. Each step exposes waste that the next step would compound. Running them out of sequence produces the illusion of progress while preserving the underlying problem.

These five steps complement your Renaissance principles (what you fight *for*, see [principles.md](principles.md)) by describing the *order in which you think* before touching code.

**The sequence:**
> Make requirements less dumb → Delete → Simplify → Accelerate → Automate

---

## Step 1: Make Requirements Less Dumb

**Core Idea:** Every requirement is wrong until it earns its place.

> *"Your requirements are definitely dumb — it does not matter who gave them to you."*
> — Elon Musk

The greatest risk comes from requirements authored by credible people: executives, lead engineers, domain experts. Teams rarely challenge them because the source is trusted. Intelligence doesn't guarantee correctness. Every requirement must be owned by a specific **person**, not a department — accountability forces examination of why it exists.

**The ABC Model:**
- **Assume Nothing** — Could the system function without this requirement entirely?
- **Be Curious** — What specific problem does this solve? Does it serve the core goal?
- **Confirm the Important** — Does this contribute to core functionality, or is it "just in case"?

**Requirements are not set in stone.** As the product evolves and evidence accumulates, continuously revisit prior assumptions. What made sense last quarter may not survive this one. The cost of carrying a stale requirement is paid every cycle.

**Brutal Truth:** The most dangerous requirements are the ones nobody questions because the author is credible.

**Example Manifestation** (replace with your own before shipping this doc):
- A design-discussion step runs before a planning step — the problem is stated and challenged before the solution is designed.
- Every unit of work inherits prior assumptions and must challenge them explicitly before new work begins.
- A glossary or registry must name a concept before you build it — if you can't define it precisely, the requirement isn't understood.
- A parameter registry's lifecycle (`seed` → `learned` → `override`) is requirements iteration in code — parameters evolve as evidence contradicts prior assumptions.
- Statistical evidence is required before promoting anything to production — "we think this works" is not a requirement.

---

## Step 2: Delete the Part or Process

**Core Idea:** If it doesn't need to exist, remove it before doing anything else.

> *"If you're not adding things back in at least 10% of the time, you're clearly not deleting enough."*
> — Elon Musk

The temptation is to include components "just in case." Every part added defensively becomes permanent: it accumulates tests, documentation, dependencies, and tribal knowledge. The 10% rule is a calibration check — if you've never added something back after deleting it, you're being too conservative. Deletion is a discipline that requires practice.

**The SpaceX grid fins example:** Traditional rocket grid fins folded after launch using elaborate retraction mechanisms. SpaceX simulations revealed that leaving them unfolded had minimal impact and could be managed through other means — eliminating the entire retraction system. The mechanism existed because no one asked whether it needed to exist at all.

**Brutal Truth:** The part that should not exist is the hardest to see — because it took effort to build, it feels like it must be there for a reason.

**Example Manifestation:**
- Archive/delete an old subsystem rather than optimize it — rebuild from first principles when the old design has calcified.
- Drop tables/monoliths entirely rather than migrate them when they've been superseded.
- Auto-demotion for underperforming components — if something can't earn its place, it is removed, not kept "just in case."
- Explicitly exclude data paths known to carry look-ahead bias or other structural defects from the training/decision path, rather than patching around them.

---

## Step 3: Simplify or Optimize the Design

**Core Idea:** Only optimize what has survived deletion.

> *"The most common error of a smart engineer is to optimize a thing that should not exist."*
> — Elon Musk

This step only applies to what remains after steps 1 and 2. Optimizing before deleting is the most expensive mistake in engineering — it creates faster, cleaner versions of things that shouldn't exist. Simplification must also be **holistic**: reducing engine weight while leaving payload weight unaddressed nets zero. Optimizing one component while adding complexity elsewhere is not simplification.

**Brutal Truth:** Clever engineering applied to a wrong requirement produces a beautifully optimized mistake.

**Example Manifestation:**
- Hot/cold path separation simplifies by giving each layer exactly one job — compute, persistence, and transport optimized independently without coupling.
- Vectorize or batch a hot-loop computation only after the algorithm has been validated as necessary.
- A parameter registry replaces magic numbers — but only in modules that survive the deletion check; migrating constants in code that should be deleted is Step 3 before Step 2.
- Simple > clever — readability is the primary optimization target; algorithmic cleverness is secondary.
- Holistic thinking: reducing one dimension's complexity while adding it back elsewhere nets zero — simplify systems together, not component-by-component in isolation.

---

## Step 4: Accelerate Cycle Time

**Core Idea:** Move faster, but only in the correct direction.

> *"If you're digging your grave, don't dig faster."*
> — Elon Musk

Acceleration is a multiplier — it amplifies whatever direction you're already moving. Applied after steps 1-3, it delivers value faster. Applied before them, it compounds waste faster. Rapid iteration is only valuable when you've confirmed you're iterating on something that should exist, can't be deleted, and has been simplified.

**Brutal Truth:** Speed is not progress. Speed in the wrong direction is the fastest way to build something that must be entirely thrown away.

**Example Manifestation:**
- Shadow mode first — never accelerate promotion of a new component before direction is confirmed by evidence (p<0.05, sufficient N).
- A shared base class accelerates iteration on new services — but only after the pattern was validated through multiple manual implementations.
- Parallelism (worker pools, batching) added only after the underlying algorithm is proven correct.
- Atomic-commit execution accelerates delivery, but only after a discussion/plan step confirms the right work is being done.
- A resume/checkpoint flag accelerates re-runs but only re-runs validated steps.

---

## Step 5: Automate

**Core Idea:** Automate last, after every prior step has been satisfied.

Automation is the final force multiplier — it makes a validated, simplified process run without human intervention. Applied too early, it permanently enshrines waste. The cost of automating the wrong thing is not just the automation work — it's all future work that runs on top of it.

**The Tesla battery mat example:** Massive resources were invested in automating a robotic process for installing battery mats. Only after the automation was complete did someone ask whether the mat was still needed. It turned out the mat existed only to reduce sound, was no longer required, and the entire automated system was scrapped. The automation was built perfectly. The requirement was never challenged.

**Brutal Truth:** Automating an unvalidated process doesn't eliminate the problem — it scales it and makes it invisible.

**Example Manifestation:**
- A pipeline-runner script was built after each manual step was verified to produce correct output — automation followed validation, not the reverse.
- Scheduled services + lag/health monitoring — automation layered on services that were proven correct in manual operation first.
- ML learning targets in a parameter registry — tuning is automated only after manual calibration proves the parameter matters and the range is sensible.
- Nightly/periodic batch automation — the process was manually executed and verified before being scheduled.
- Dead-letter-queue error isolation — automated, but only because the error taxonomy was understood through manual debugging first.

---

## The Sequencing Mandate

The five steps are only valuable in order. Violations are predictable:

| Skipping to... | Before completing... | Result |
|---|---|---|
| Step 3 (Optimize) | Step 2 (Delete) | Highly optimized component that shouldn't exist |
| Step 4 (Accelerate) | Step 3 (Simplify) | Faster iteration on an overcomplicated system |
| Step 5 (Automate) | Step 1 (Requirements) | Permanently automated waste (Tesla battery mat) |
| Step 2 (Delete) | Step 1 (Requirements) | Deleting the wrong things because the goal wasn't clear |

**The 10% calibration:** Deletion is a skill. If you've never added something back after deleting it, you're under-deleting. The right calibration produces occasional add-backs — proof that the deletion pass was aggressive enough to find the boundary.

---

## Synthesis

| Step | Core Question | Enforce via |
|---|---|---|
| 1. Requirements Less Dumb | Does this need to exist, and who owns it? | Discuss-before-plan workflow; glossary; evidence gate |
| 2. Delete | What can be removed entirely? | Archive-over-optimize bias; auto-demotion; rebuild-from-scratch willingness |
| 3. Simplify | Are we optimizing the right things holistically? | Hot/cold separation; parameter registry; simple > clever |
| 4. Accelerate | Are we moving in the right direction faster? | Shadow mode first; shared base classes; atomic commits |
| 5. Automate | Has this been validated enough to run without human oversight? | Pipeline runners; scheduled services; ML learning targets |

## See Also

- [Renaissance Principles](principles.md) — What you fight for
- [Renaissance-Grade Standards](renaissance-grade-standards.md) — How you keep the workspace clean
- [Ship or Sink Rules](ship-or-sink-rules.md) — Development workflow

---

## Adopting This in a New Project

Copy this file verbatim — the framework itself doesn't change. Replace every "Example Manifestation" bullet list with your own project's real examples once you have three or four instances of each step actually happening in your codebase. Don't invent hypothetical examples; wait until the step has actually occurred and cite the real instance.
