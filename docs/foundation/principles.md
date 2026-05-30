# Renaissance Principles

**Version:** 2.9
**Status:** current
**Last Updated:** 2026-05-30

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
