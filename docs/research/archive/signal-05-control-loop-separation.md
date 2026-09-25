# Signal Control Loop Separation

**Version:** 1.0
**Status:** draft
**Priority:** medium
**Milestone:** future (post-v2.8)
**Last Updated:** 2026-05-18
**Tags:** control-loop, signal-generation, learning, shadow-governance, deterministic, auditability

---

## Overview

IndicAgent should treat signal generation and signal learning as two separate control loops:

1. **Deterministic production loop** - the live pipeline turns bars into validated signals using explicit rules, plugin logic, CIS, regime gates, and lifecycle tracking.
2. **Learning / evolution loop** - discovery, ML, swarm, and shadow evaluation mine outcomes, propose better rules or weights, and promote only what survives statistical proof.

The key design rule is that the learning loop does not directly invent live signals in the hot path. It produces candidate rules, weights, or agent variants that must be tested, shadowed, and promoted before they affect live data.

This preserves three things that matter in a trading system:
- deterministic replay
- auditability
- low-latency execution

---

## Why This Matters

The current system already has pieces of both loops, but the boundary is implicit.

The production side already does the right things:
- setup plugins emit executable trade candidates
- CIS arbitrates between competing candidates
- `SignalTrackerComputeAgent` turns candidates into lifecycle outcomes
- `signal_ledger` stores the labeled result

The learning side already exists too:
- `MLDiscoveryComputeAgent` mines feature/outcome correlations
- `CIS` weight learning updates bucket weights from resolved outcomes
- swarm agents learn per-agent multipliers from outcomes
- shadow mode gates prevent premature promotion

What is missing is a crisp model that says:

- this is a signal
- this is a hypothesis
- this is a learned adjustment
- this is the promotion boundary

Without that boundary, AI can drift from "help me find edges" into "decide the edge live", which is the wrong tradeoff for a production pipeline.

---

## Proposed Split

### 1. Deterministic Production Loop

This loop is the current live system.

Input:
- bars
- context
- pattern and structure features
- regime state

Output:
- executable signal candidates
- ranked signal winner
- lifecycle events
- resolved outcomes

Rules:
- deterministic code decides whether a candidate exists
- deterministic code decides framing, TTL, stops, targets, and eligibility
- deterministic code decides what gets written to the ledger
- no LLM call can sit on this path

### 2. Learning / Evolution Loop

This loop reads historical outcomes and proposes improvements.

Input:
- `intelligence_features`
- `signal_ledger`
- `signal_lineage`
- drift metrics
- shadow outcomes

Output:
- new feature correlations
- new bucket weights
- new thresholds
- new candidate setup logic
- new agent variants

Rules:
- learning can propose
- learning cannot self-promote
- every change must prove itself out of sample
- any live impact requires a promotion gate

---

## What Counts As A Signal

A useful split is:

### Hypothesis
An idea that a pattern or relationship might have edge.

Example:
- "RSI divergence is more reliable during trending regimes after high-volume expansion."

### Candidate
A hypothesis turned into executable trade framing.

Example:
- direction
- entry zone
- stop
- target set
- TTL
- setup plugin

### Signal
A candidate that passed publication gates and entered the live ledger.

That means a signal is not just "something the model noticed." It is a validated, executable object with explicit framing and lifecycle semantics.

### Lifecycle
Once published, the signal becomes a tracked object:
- pending
- active
- closed
- outcome-labeled

That lifecycle is what creates training data.

---

## What Can Evolve

The learning loop should be allowed to evolve these artifacts:

- CIS bucket weights
- setup performance multipliers
- regime thresholds
- feature selection
- candidate ranking heuristics
- prompt strategies for research agents
- agent genomes in shadow mode

The learning loop should not directly evolve:

- live execution logic without review
- risk controls
- signal schema contracts
- lifecycle definitions
- hard publication gates

Those should stay explicit and versioned.

---

## Promotion Pipeline

The system should treat every learned change as a staged artifact:

```
observation -> hypothesis -> candidate -> shadow -> evaluation -> promotion -> live
```

Recommended gate sequence:

1. Discovery finds a relationship or candidate rule.
2. A deterministic validator tests it on historical data.
3. Shadow mode runs it without affecting live output.
4. Statistical gates check significance, sample size, and regime stability.
5. Human review confirms the change is sensible.
6. Only then does the change affect live signals.

That applies whether the artifact is:
- a new rule
- a new threshold
- a new weight vector
- a new agent variant

---

## Design Principle

The production engine should answer:

**"What is the signal right now?"**

The learning engine should answer:

**"What should count as a signal next time?"**

That separation gives us a stable live system and a learning system that can improve it without collapsing into an uncontrolled feedback loop.

---

## Open Questions

- Should learned artifacts be stored as versioned rule packs, or as separate model objects?
- Should discovery output only rank relationships, or also synthesize candidate rules?
- Should the promotion unit be a single signal rule, a setup plugin, or a whole bundle of related changes?
- How much of the learning loop should be automated versus human-approved?
