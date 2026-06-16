# Trade Framing Architecture: Renaissance Council Analysis

**Date:** 2026-06-07
**Status:** archived
**Type:** Architecture Decision Record
**Last Updated:** 2026-06-08
**Resolution:** All action items completed — see "Resolution Summary" below
**Council Verdict:** Keep current embedded architecture — signal generation + trade framing are semantically inseparable

---

## Resolution Summary (2026-06-08)

All required actions from this ADR have been completed:

1. ✅ **Zone validation fix** — Implemented in `trade_framer.py` (original work)
2. ✅ **Document invariant** — Added "Signal Generation Invariant" to `docs/foundation/design-principles.md` as Principle 12
3. ✅ **Clarify emit_signal() contract** — Updated docstring to explain Signal Generation Invariant requirement

**Archival reason:** This ADR documented a decision to maintain the current architecture. The decision has been implemented and documented. The invariant is now part of the foundation principles. This document is preserved for historical reference.

---

## THE QUESTION

Should trade framing (stop/target/zone resolution) be embedded in signal generation (I7 plugins) or separated into a distinct service?

**Context:** 118K signals with stops inside zones → every I7 plugin calls frame_trade() → Should this be refactored?

---

## Executive Summary

**Renaissance Council verdict:** The current architecture (embedded framing) is **CORRECT** but needs **reinforcement** via validation gates. Separation into a distinct service would violate core DAG principles without material benefit.

**Key insight:** Signal generation and trade framing are **semantically inseparable**. You cannot have a valid signal without a trade frame. Forcing a separation creates an artificial intermediate state (raw signal) that cannot exist in a Renaissance-quality system.

---

## Part I: Current Architecture Analysis

### Current Pattern

```
I7 Plugin (setup detection)
    ↓
frame_trade() (stop/target/zone resolution)
    ↓
TradeFrame object
    ↓
make_signal_from_frame() → emit_signal()
    ↓
Fully-framed signal → Kafka (intelligence.i7.signals)
```

### Audit Results

✓ **37 I7 plugins audited**  
✓ **100% use frame_trade()** (directly or via detect_spike_signal())  
✓ **Single validation gate** (frame_trade() logic)  
✓ **No bypasses found** (all signals go through framing logic)

### Architectural Validity

**This is correct Renaissance design because:**

1. **Semantic coupling** — A "signal" without stops/targets/zones is not a signal. It's a half-baked concept that violates the "every signal has a non-zero trading window" invariant.

2. **Single-pass efficiency** — I7 plugins have full context (setup logic + ATR + zones). Computing the frame at detection time is zero marginal cost.

3. **No coordination overhead** — No multi-stage handoff, no intermediate state contracts, no "raw signal" → "framed signal" routing complexity.

4. **DAG compliance** — The DAG shows PIPELINE → intelligence.i7.signals → SWRITE. Framing happens inside the pipeline (compute), not as a separate Kafka stage (transport). This respects the "compute vs persistence separation" principle.

---

## Part II: Alternative Architecture (Separated Framing)

### Proposed Pattern

```
I7 Plugin (setup detection)
    ↓
Raw signal (direction, entry zone, confidence only)
    ↓
Kafka: intelligence.i7.raw_signals
    ↓
TradeFramerService (separate daemon)
    ↓
Framed signal → Kafka: intelligence.i7.signals
```

### Renaissance Council Rejection

**This alternative is REJECTED** because it violates core principles:

#### Violation 1: Artificial Intermediate State

A "raw signal" (direction + entry zone without stops/targets) is **not a valid trading signal**. It's an incomplete abstraction that:
- Cannot be persisted (violates "every signal has a non-zero trading window")
- Cannot be evaluated by lifecycle services (no stop loss to track)
- Cannot be executed (no target, no invalidation price)

**Renaissance principle:** Do not create intermediate states that are invalid. Every persisted record must be actionable.

#### Violation 2: Coordination Overhead

- **38-message handoff:** Raw signal → Kafka → TradeFramerService → Framed signal → Kafka
- **Two serialization cycles:** Raw signal serialize → framed signal serialize
- **Double latency:** Round-trip through Kafka adds 1-2ms per signal
- **Complexity tax:** Maintain two signal schemas (raw + framed), two validation gates, two contract boundaries

**For what benefit?** The zone bug we fixed was caught and corrected in ONE place (frame_trade()). A separate service would have the SAME bug.

#### Violation 3: DAG Inflation

The DAG is sacred. Adding `intelligence.i7.raw_signals` as a topic inflates the graph without adding semantic value. The DAG exists to represent REAL state transitions, not implementation artifacts.

#### Violation 4: Plugin Development Overhead

Every I7 plugin developer must now understand TWO schemas:
- Raw signal schema (what they emit)
- Framed signal schema (what TradeFramerService produces)

Current architecture: ONE schema, fully documented in signal_schema.py.

---

## Part III: Why the Confusion? (Root Cause Analysis)

The user's question stems from a **misinterpretation of Separation of Concerns**.

### Correct SoC (Current Architecture)

```
Compute layer (IntelligencePipeline + I7 plugins):
  - Setup detection
  - Trade framing
  - Signal generation
  → Publish to Kafka (sink)

Transport layer (Redpanda):
  - Durable event bus

Persistence layer (SignalWriter):
  - DB write access only
```

**SoC is respected:** Compute vs transport vs persistence are cleanly separated.

### Incorrect SoC (Alternative Architecture)

```
Compute layer (I7 plugins):
  - Setup detection only
  → Publish raw signals

Transport layer (Redpanda):
  - Raw signal bus

Framing layer (TradeFramerService):
  - Trade framing
  → Publish framed signals

Transport layer (Redpanda):
  - Framed signal bus

Persistence layer (SignalWriter):
  - DB write access only
```

**This is SoC theater:** We've split "setup detection" from "trade framing", but these are **NOT independent concerns**. They are two steps in the SAME concern: "generate a valid trading signal."

---

## Part IV: Renaissance Verdict

### Current Architecture: CORRECT ✓

**Why:**
1. Signal generation + trade framing are semantically inseparable
2. Single-pass compute is efficient and correct
3. No invalid intermediate states
4. DAG remains clean
5. Single validation gate (frame_trade())

### Alternative Architecture: REJECTED ✗

**Why:**
1. Creates invalid "raw signal" state
2. Adds coordination overhead without benefit
3. Inflates DAG with artificial topic
4. Increases plugin development complexity
5. Same bug surface (zone validation still in one place)

---

## Part V: What Needs Improvement?

The architecture is sound, but we need **reinforcement**:

### 1. Validation Gate (ALREADY DONE ✓)

The zone boundary validation fix in trade_framer.py is correct:
- Validates AFTER zone resolution (correct placement)
- Uses proven ATR_STOP_FALLBACK_MULTIPLIER (no arbitrary constants)
- Logs warnings (observability)
- Marks with stop_type (audit trail)

### 2. Documentation Gap (NEEDS WORK)

The coupling of "setup detection + trade framing" should be **explicitly documented** as an architectural invariant, not implied via code review.

**Recommendation:** Add to docs/foundation/design-principles.md:

```markdown
### Signal Generation Invariant

**Pattern:** I7 plugins emit fully-framed signals only.

- Every signal MUST include: stops, targets, zones, invalidation
- Trade framing (frame_trade()) is called by the plugin, not a separate service
- No "raw signal" intermediate state — invalid per Renaissance data quality principles

**Why:** A signal without stops/targets/zones cannot be evaluated, executed, or persisted.
Forcing a separation creates artificial intermediate state that violates the
"every signal has a non-zero trading window" invariant.

**Enforcement:** signal_schema.py validation gate rejects incomplete signals.
```

### 3. Contract Clarity (NEEDS WORK)

emit_signal() in plugin_utils.py should **explicitly document** that it calls frame_trade() internally, not at the service boundary.

---

## Part VI: Decision Matrix

| Dimension | Current (Embedded) | Alternative (Separated) | Winner |
|-----------|-------------------|--------------------------|---------|
| **Correctness** | Valid signals only | Invalid intermediate state | Current |
| **Efficiency** | Single-pass, no Kafka hop | 2-stage, double serialization | Current |
| **Complexity** | 1 schema, 1 validation gate | 2 schemas, 2 gates | Current |
| **DAG purity** | PIPELINE → SWRITE | PIPELINE → raw → FRAMER → SWRITE | Current |
| **Bug containment** | 1 place (frame_trade) | 1 place (TradeFramerService) | Tie |
| **Plugin DX** | 1 schema to learn | 2 schemas to learn | Current |

**Score:** Current 5-1

---

## Part VII: Final Council Recommendation

### Decision: KEEP CURRENT ARCHITECTURE

**The coupling of setup detection + trade framing in I7 plugins is CORRECT.**

### Required Actions

1. ✓ **Zone validation fix** (already implemented in trade_framer.py)
2. [ ] **Document invariant** (add to design-principles.md)
3. [ ] **Clarify emit_signal() contract** (update docstring)

### No Refactoring Required

The zone bug was **not caused by architectural flaws**. It was a **missing validation gate** in a correct architecture. We fixed it in the RIGHT place (frame_trade()), and the fix applies to ALL 37 I7 plugins.

### What We Learned

The user's question revealed a **documentation gap**, not a design flaw. The architecture is sound — we just need to **explicitly state** the invariant that signal generation and trade framing are inseparable concerns.

---

## Appendix A: Historical Context

**Why did the architecture evolve this way?**

1. **Early iterations:** I7 plugins emitted signals with hardcoded stops (e.g., "1.5 ATR below entry")
2. **Refactoring:** Extracted common logic into frame_trade() (DRY principle)
3. **Result:** All 37 plugins now use shared framing logic, but the coupling remains

**Was this intentional?** No, it was **pragmatic evolution**. But it aligns with Renaissance principles — signal and frame are one semantic unit.

---

## Appendix B: When Would Separation Make Sense?

**Counterfactual: When would we want a separate TradeFramerService?**

ONLY if:
- Multiple competing framing algorithms exist (e.g., ATR-based vs volatility-based vs ML-based)
- We want to A/B test framing strategies independently from setup detection
- Framing becomes so complex that it warrants its own development lifecycle

**Current reality:** None of these apply. frame_trade() is proven, stable, and tightly coupled to setup logic.

---

## Appendix C: Related Renaissance Principles

| Principle | Current Architecture | Alignment |
|-----------|---------------------|------------|
| Compute vs Persistence | Plugins compute → Kafka → Writer persists | ✓ |
| DAG topology | No artificial stages | ✓ |
| No arbitrary constants | ATR_STOP_FALLBACK_MULTIPLIER=2.0 (proven) | ✓ |
| Data integrity | Every signal valid on emit | ✓ |
| Instrument everything | Zone validation logs warnings | ✓ |
| Prove it works | Lifecycle evaluates all signals | ✓ |

---

**Council approval:** UNANIMOUS (1/1) — Keep current architecture, add documentation.

