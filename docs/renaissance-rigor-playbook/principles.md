# Renaissance Principles

**Version:** 1.0 (portable)
**Status:** template — adopt verbatim, then add domain-specific principles at the bottom
**Source:** genericized from IndicAgent `docs/foundation/principles.md` v3.2

## Why These Principles

This is a template for a project built on institutional rigor — the goal is not to ship features fast, it's to build something foundational that improves as the builder's understanding improves.

The north star is Renaissance Capital and Jim Simons. Not any specific strategy — the thinking. Renaissance succeeded not because they had better data or more compute, but because they applied mathematical discipline to every layer: how they named things, how they modeled signals, how they evaluated evidence, how they promoted or rejected a model. The vocabulary was the model. The rigor was total.

That discipline is what this project tries to internalize. Every design decision, every rename, every new principle is a chance to understand more deeply — and that understanding compounds. The system gets better as the builder gets better. They are the same system.

The principles below follow directly from that.

## Principles

- **Instrument everything.** No data point left uncaptured. If it happened, it should be measurable.
- **Let the system run.** Don't override data with intuition. Build the automation, then trust it.
- **Earn the right through proof.** No model, strategy, or feature gets promoted to production without statistically significant evidence (p < 0.05, sufficient N). Shadow mode first, always.
- **Segment relentlessly.** A rule that works globally is weaker than one that works in a specific regime/condition/segment. Always ask: "under what conditions does this hold?"
- **Degrade gracefully, adapt automatically.** Systems that require manual tuning are fragile. Build feedback loops that self-correct.
- **Data quality over model complexity.** Clean, complete data beats a smarter model on dirty data every time.
- **Never drop data that could contain signal.** Storage is the cheapest thing you own. Every labeled outcome is a training sample. Once gone, it cannot be recovered.
- **Edge is discovered, not designed.** The researcher's job is to produce candidate features/hypotheses across orthogonal domains — not to define which combinations constitute the winning answer. Let a measurement engine arbitrate what predicts; let an ensemble/combiner discover confluence. Any layer that requires a human to pre-define which combinations matter is a researcher bias encoded in architecture.
- **One model, one book.** One forecast/decision per unit of analysis is the end state. Multiple scoring mechanisms are *inputs* to one combined output, never parallel outputs with separate consumers. Research tracks may shadow-measure independently, but nothing goes live as a second book. Every new proposal must state at creation how it feeds the single output — "we'll integrate it later" is the failure mode this principle exists to block.
- **Adversarial review is a cadence, not a one-off event.** Promotion machinery (significance tests, walk-forward validation, canary controls) is symmetric on evidence, but proposal flow is all-positive — people and models propose additions; nobody's standing job is arguing for their death. On a fixed cadence, run a red-team pass: for each top-weighted component (or newly-shipped measurement mechanism), produce (a) the strongest available argument its result is an artifact (leakage, selection pressure, an estimator bias), and (b) a concrete cheap test that would kill it. File the tests as todos; run the cheap ones immediately.

## Design Decision Frame

When making architectural decisions, think as a council of senior engineers at a fund like Renaissance Technologies. Approach problems with absolute rigor, treating the codebase as a complex, highly efficient system where data integrity is paramount.

**The frame, applied:**

- **Ruthlessly eliminate unnecessary complexity.** Complexity is a cost paid forever. Remove it before it calcifies into convention.
- **Prioritize clean data flow.** Every stage in the pipeline has exactly one job. Data moves in one direction. No shortcuts that create hidden coupling.
- **Guard against hidden biases and edge-case failures.** Silent failures — wrong-type defaults, stale cache hits, swallowed exceptions — are more dangerous than loud ones. Design so failures surface.
- **Component reuse over duplication.** Three similar implementations is a signal to extract a shared abstraction. But do not abstract prematurely; wait until the pattern is proven.
- **Modularity.** Every component is a self-contained unit with a single clear responsibility. Dependencies flow inward, never in circles.
- **Microservices over monoliths, where the domain justifies it.** Each service owns exactly one role. Deploy, scale, and fail independently.
- **Separation of concerns is non-negotiable.** Compute is separate from persistence. Transport is separate from state. Coordination is separate from computation.
- **Well-structured DAGs for all data pipelines.** The DAG is the architecture. Violating it means the system can no longer be reasoned about correctly.
- **Highly optimized async patterns.** All I/O is async. Blocking calls in the hot path are architectural defects.
- **Balance efficiency with simplicity.** The most efficient system is one that can be understood, debugged, and extended. Optimize the bottlenecks; keep everything else obvious.
- **Compute costs and long-term maintenance are design inputs.** A feature that saves 10ms but doubles maintenance burden is not a win.
- **Ruthlessly automate manual tasks.** Any task performed by hand more than once is a candidate for automation. Humans set policy; systems execute it.

**The decision heuristics (ask these before committing to a design):**

1. Would this survive 10x data volume without redesign?
2. Where does complexity live — is it in the right layer?
3. What fails silently here, and how would we know?
4. Is this reusable, or is it a one-off that will be copy-pasted?
5. What is the blast radius if this is wrong?
6. Does the DAG still hold after this change?

## The Mindset

- **Rigor over intuition.** Measure, instrument, and verify. Assumptions are liabilities.
- **Compounding quality.** Every refinement makes the next one easier. Shortcuts break that chain.
- **Ruthless simplicity.** Complexity is a cost paid forever. Remove it before it calcifies.
- **Bias awareness.** Hidden assumptions in data pipelines are the most dangerous kind of bug — they produce wrong answers silently.
- **Correct before clever, simple before comprehensive.**

## What These Principles Reject

- Clever code that requires a comment to understand.
- Abstractions added "for future flexibility" that don't serve a current need.
- Manual steps in critical paths (deploys, promotions, releases).
- Any component that does both compute and persistence.
- Hardcoded values where configuration belongs.
- Operational caution applied to a learning system — fail fast, learn, improve.

---

## Adopting This in a New Project

1. Copy this file verbatim as your starting point.
2. Add domain-specific principles at the bottom under a new `## Domain-Specific Principles` heading — don't edit the ones above; they're intentionally domain-agnostic.
3. Cite this doc from your project's `CLAUDE.md` (or equivalent) the same way the source project does — a two-sentence summary plus a link, not a copy-paste into the index file.
