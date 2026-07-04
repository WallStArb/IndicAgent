# Renaissance Principles

**Version:** 3.1
**Status:** current
**Last Updated:** 2026-07-03

## Why These Principles

This platform is a passion project — built to learn real architecture, apply new ideas, and improve by doing. The goal is not to ship features fast. The goal is to build something foundational: a platform rooted in institutional rigor that can be extended to other domains, other instruments, other forms of intelligence.

The north star is Renaissance Capital and Jim Simons. Not the trading strategies — the thinking. Renaissance succeeded not because they had better data or more compute, but because they applied mathematical discipline to every layer: how they named things, how they modeled signals, how they evaluated evidence, how they promoted or rejected a model. The vocabulary was the model. The rigor was total.

That discipline is what this project tries to internalize. Every design decision, every rename, every new principle is a chance to understand more deeply — and that understanding compounds. The platform gets better as the builder gets better. They are the same system.

The principles below follow directly from that.

## Principles

- **Instrument everything.** No data point left uncaptured. If it happened, it should be measurable.
- **Let the system run.** Don't override data with intuition. Build the automation, then trust it.
- **Earn the right through proof.** No model, strategy, or feature gets promoted to production without statistically significant evidence (p < 0.05, sufficient N). Shadow mode first, always.
- **Segment relentlessly.** A rule that works globally is weaker than one that works in a specific regime. Always ask: "under what conditions does this hold?"
- **Degrade gracefully, adapt automatically.** Systems that require manual tuning are fragile. Build feedback loops that self-correct.
- **Data quality over model complexity.** Clean, complete data beats a smarter model on dirty data every time.
- **Never drop data that could contain signal.** Storage is the cheapest thing we own. Every signal outcome, feature vector, and LLM call is a labeled training sample. Once gone, it cannot be recovered.
- **Edge is discovered, not designed.** The researcher's job is to produce candidate features across orthogonal domains — not to define what combinations constitute a tradeable edge. The IC engine arbitrates what predicts. The ensemble discovers confluence. Any layer that requires a human to define which feature combinations matter is a researcher bias encoded in architecture. Renaissance found thousands of features with IC 0.02-0.06 each and let the ensemble combine them — no individual feature was the insight. The aggregate was.
- **One model, one book.** One forecast per (symbol, tf, bar) is the end state. AnalogEngine scores, confluence predictors, ensemble scores — all are *inputs* to one combined forecast, never parallel forecasts with separate consumers. Research tracks may shadow-measure independently, but nothing goes live as a second book; discrete events and portfolio positions ultimately settle into the same accounting. Every new forecasting proposal must state at creation how it feeds the single forecast and the single P&L — "we'll integrate it later" is the failure mode this principle exists to block. Medallion's under-appreciated property was the opposite of proliferation: a single integrated model, everything competing inside one framework. (Promoted 2026-07-03 from `docs/ideas/intel-11-dual-system-discrete-vs-portfolio.md`, per `.planning/research/2026-07-03-intel10-11-fable-review.md` R3.)

## Design Decision Frame

When making architectural decisions, think as a council of senior engineers at a fund like Renaissance Technologies. Approach problems with absolute rigor, treating the codebase as a complex, highly efficient system where data integrity is paramount.

**The frame, applied:**

- **Ruthlessly eliminate unnecessary complexity.** Complexity is a cost paid forever. Remove it before it calcifies into convention.
- **Prioritize clean data flow.** Every stage in the pipeline has exactly one job. Data moves in one direction. No shortcuts that create hidden coupling.
- **Guard against hidden biases and edge-case failures.** Silent failures — wrong-type defaults, stale cache hits, swallowed exceptions — are more dangerous than loud ones. Design so failures surface.
- **Component reuse over duplication.** Three similar implementations is a signal to extract a shared abstraction. But do not abstract prematurely; wait until the pattern is proven.
- **Modularity.** Every component is a self-contained unit with a single clear responsibility. Dependencies flow inward, never in circles.
- **Microservices over monoliths.** Each service owns exactly one role. Deploy, scale, and fail independently.
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

**See also:** `docs/ideas/renaissance-01-simons-principles.md` for the full Jim Simons research and distilled trading-system principles.

## The Mindset

- **Rigor over intuition.** Measure, instrument, and verify. Assumptions are liabilities.
- **Compounding quality.** Every refinement makes the next one easier. Shortcuts break that chain.
- **Ruthless simplicity.** Complexity is a cost paid forever. Remove it before it calcifies.
- **Bias awareness.** Hidden assumptions in data pipelines are the most dangerous kind of bug — they produce wrong answers silently.
- **Correct before clever, simple before comprehensive.**

## What These Principles Reject

- Clever code that requires a comment to understand.
- Abstractions added "for future flexibility" that don't serve a current need.
- Manual steps in critical paths (deploys, contract rolls, model promotion).
- Any component that does both compute and persistence.
- Hardcoded values where configuration belongs.
- Operational caution applied to a learning system — fail fast, learn, improve.
