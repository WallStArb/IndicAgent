# Musk's 5-Step Design Process

**Version:** 1.1
**Status:** current
**Last Updated:** 2026-09-04

## Overview

Developed by Elon Musk at SpaceX to fundamentally rethink how products and systems are built. The framework is not a checklist of independent ideas — the **order is the insight**. Each step exposes waste that the next step would compound. Running them out of sequence produces the illusion of progress while preserving the underlying problem.

These five steps complement our Renaissance principles (what we fight *for*) and product laws (what we fight *against*) by describing the *order in which we think* before touching code.

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

**Requirements are not set in stone.** As the product evolves and evidence accumulates, continuously revisit prior assumptions. What made sense in Phase 137 may not survive Phase 141. The cost of carrying a stale requirement is paid every phase.

**Brutal Truth:** The most dangerous requirements are the ones nobody questions because the author is credible.

**IndicAgent Manifestation:**
- `discuss-phase` runs before `plan-phase` — the problem is stated and challenged before the solution is designed
- Every phase inherits prior assumptions and must challenge them explicitly before new work begins
- The glossary must name a concept before we build it — if you can't define it precisely, the requirement isn't understood
- The APR parameter lifecycle (`[initial_estimate]` → `ml_learned` → `user_override`) is requirements iteration in code — parameters evolve as evidence contradicts prior assumptions
- IC evidence is required before promoting a signal to active — "we think this works" is not a requirement

---

## Step 2: Delete the Part or Process

**Core Idea:** If it doesn't need to exist, remove it before doing anything else.

> *"If you're not adding things back in at least 10% of the time, you're clearly not deleting enough."*
> — Elon Musk

The temptation is to include components "just in case." Every part added defensively becomes permanent: it accumulates tests, documentation, dependencies, and tribal knowledge. The 10% rule is a calibration check — if you've never added something back after deleting it, you're being too conservative. Deletion is a discipline that requires practice.

**The SpaceX grid fins example:** Traditional rocket grid fins folded after launch using elaborate retraction mechanisms. SpaceX simulations revealed that leaving them unfolded had minimal impact and could be managed through other means — eliminating the entire retraction system. The mechanism existed because no one asked whether it needed to exist at all.

**Brutal Truth:** The part that should not exist is the hardest to see — because it took effort to build, it feels like it must be there for a reason.

**IndicAgent Manifestation:**
- I5-I7 were archived in v3.0 rather than optimized — the entire intelligence pipeline layer was deleted and rebuilt from first principles
- `signal_ledger` monolith dropped in Phase 130; `signal_outcomes` dropped entirely rather than migrated
- Shadow governance auto-demotes underperforming plugins — if a signal can't earn its place, it is removed
- `intelligence_features` is not used as training corpus (look-ahead bias) — deleted from the v3.0 data path entirely rather than patched

---

## Step 3: Simplify or Optimize the Design

**Core Idea:** Only optimize what has survived deletion.

> *"The most common error of a smart engineer is to optimize a thing that should not exist."*
> — Elon Musk

This step only applies to what remains after steps 1 and 2. Optimizing before deleting is the most expensive mistake in engineering — it creates faster, cleaner versions of things that shouldn't exist. Simplification must also be **holistic**: reducing engine weight while leaving payload weight unaddressed nets zero. Optimizing one component while adding complexity elsewhere is not simplification.

**Brutal Truth:** Clever engineering applied to a wrong requirement produces a beautifully optimized mistake.

**IndicAgent Manifestation:**
- Hot/cold path separation simplifies by giving each layer exactly one job — compute, persistence, and transport optimized independently without coupling
- `_alpha_pass` (`services/regime_writer.py`, formerly `_causal_decode`) was vectorized — `_compute_log_emit` batch-precomputes log emissions before the alpha-pass loop — only after the HMM algorithm was validated as necessary
- APR replaces magic numbers — but only in modules that survive the deletion check; migrating constants in code that should be deleted is Step 3 before Step 2
- Simple > Clever (design-principles.md §12) — readability is the primary optimization target; algorithmic cleverness is secondary
- Holistic thinking: reducing signal count while adding model complexity nets zero — the ensemble must be simplified together

---

## Step 4: Accelerate Cycle Time

**Core Idea:** Move faster, but only in the correct direction.

> *"If you're digging your grave, don't dig faster."*
> — Elon Musk

Acceleration is a multiplier — it amplifies whatever direction you're already moving. Applied after steps 1-3, it delivers value faster. Applied before them, it compounds waste faster. Rapid iteration is only valuable when you've confirmed you're iterating on something that should exist, can't be deleted, and has been simplified.

**Brutal Truth:** Speed is not progress. Speed in the wrong direction is the fastest way to build something that must be entirely thrown away.

**IndicAgent Manifestation:**
- Shadow mode first — never accelerate signal promotion before direction is confirmed by evidence (p<0.05, sufficient N)
- `BaseBatch` Ring 0 base class accelerates iteration on new batch services — but only after the batch pattern was validated through multiple manual implementations
- `ProcessPoolExecutor` added to `regime_writer` and `ic_engine` for parallelism — only after the underlying algorithms were proven correct
- `gsd-executor` atomic commits per task — cadence accelerates delivery, but only after `discuss-phase` + `plan-phase` confirm the right work is being done
- Corpus pipeline `--from-step N` resume flag — accelerates re-runs but only runs validated steps

---

## Step 5: Automate

**Core Idea:** Automate last, after every prior step has been satisfied.

Automation is the final force multiplier — it makes a validated, simplified process run without human intervention. Applied too early, it permanently enshrines waste. The cost of automating the wrong thing is not just the automation work — it's all future work that runs on top of it.

**The Tesla battery mat example:** Massive resources were invested in automating a robotic process for installing battery mats. Only after the automation was complete did someone ask whether the mat was still needed. It turned out the mat existed only to reduce sound, was no longer required, and the entire automated system was scrapped. The automation was built perfectly. The requirement was never challenged.

**Brutal Truth:** Automating an unvalidated process doesn't eliminate the problem — it scales it and makes it invisible.

**IndicAgent Manifestation:**
- `scripts/ops/corpus/ops_corpus_pipeline_run.sh` was built after each of the 6 pipeline steps was manually verified to produce correct output — automation followed validation, not the reverse
- systemd services + Prometheus lag monitoring — automation layered on services that were proven correct in manual operation first
- APR ML learning targets — parameter tuning is automated only after manual calibration proves the parameter matters and the range is sensible
- `roll-batch` (`scripts/ops/roll/ops_roll_batch.py`) — the roll process was manually executed and verified before being scheduled as a nightly timer; the timer is currently disabled (verify with `systemctl list-timers` before assuming it fires), a reminder that automation status must be re-checked live, not assumed from this doc
- `BaseWriter` DLQ — automated error isolation, but only because the error taxonomy was understood through manual debugging first

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

| Step | Core Question | IndicAgent Enforcement |
|---|---|---|
| 1. Requirements Less Dumb | Does this need to exist, and who owns it? | `discuss-phase`; glossary; IC evidence gate |
| 2. Delete | What can be removed entirely? | Archive over optimize; shadow demotion; v3.0 rebuild |
| 3. Simplify | Are we optimizing the right things holistically? | Hot/cold separation; APR; Simple > Clever |
| 4. Accelerate | Are we moving in the right direction faster? | Shadow mode first; `BaseBatch`; atomic commits |
| 5. Automate | Has this been validated enough to run without human oversight? | Corpus pipeline; systemd; APR ML targets |

## See Also

- [Renaissance Principles](principles.md) — What we fight for
- [Product Laws](product-laws.md) — What we fight against
- [Design Principles](design-principles.md) — How we build (includes 5-Step Pre-Flight)
- [Ship or Sink Rules](ship-or-sink-rules.md) — Development workflow
