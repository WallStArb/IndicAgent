# Foundational Design Principles

**Version:** 3.0
**Status:** current
**Last Updated:** 2026-06-28

## North Star

The North Star for all development and architectural decisions. When in doubt about a design choice, check it against these principles first.

These principles are timeless. They apply whether we have I1-I7, v3.0 Feature Factory, or whatever architecture comes next. They are not implementation details — they are the discipline that produces institutional-grade systems.

**See also:** `docs/foundation/renaissance-grade-standards.md` — Cleanliness, hygiene, and operational standards

---

## Architectural Principles

### 1. Modular Shell Architecture

The platform is an empty shell; capabilities are composed as modules. If logic isn't modular, it's not extensible. New capabilities are added by writing a module that conforms to a well-defined interface — without changing core infrastructure.

**Why:** Modularity enables parallel development, isolated testing, and hot-swappable components. A monolith cannot evolve at Renaissance speed.

**Anti-pattern:** Tightly-coupled services where changing one component requires touching three others.

---

### 2. Decoupled by Message Bus

No component calls another directly. A durable message fabric is the sole communication layer. Restarting a compute component has zero operational impact on persistence or analytics. Each component resumes from its committed offset — nothing is lost.

**Why:** Direct calls create invisible dependencies, restart cascades, and violate the "restart-from-offset" guarantee. Decoupling means components can fail, restart, and scale independently.

**Anti-pattern:** `service_a.call(service_b)` — if B is down, A cannot function. If B is slow, A blocks.

---

### 3. Hot/Cold Path Separation

The real-time compute path is DB-ignorant. Persistence is strictly asynchronous — decoupled via dedicated writer services. A database outage has zero impact on computation latency.

**Why:** The hot path must be fast. Blocking on I/O or database transactions kills throughput. Async persistence allows compute to run at bus speed while writers handle durability.

**Anti-pattern:** A pipeline daemon that queries the database for each bar. This couples compute to storage health and adds milliseconds per query.

---

### 4. Dependency-Aware Execution

System derives execution order from declared dependencies, not hardcoded sequencing. Circular dependencies are detected at startup. Parallel execution emerges from the dependency graph — no manual config required.

**Why:** Hardcoded sequencing is brittle. Adding a new component shouldn't require updating a choreography file. Declare inputs/outputs; let the system figure out the rest.

**Anti-pattern:** A 200-line orchestration script that lists services in startup order, breaks when a new service is added.

---

### 5. Incremental State Update

Every component maintains state and updates it incrementally per new event — O(1) per update, not recompute from scratch. Warmup is the only exception (convergence period for estimators).

**Why:** Recomputing from history every tick is impossible at scale. Stateful components that update incrementally can process unlimited throughput with constant latency.

**Anti-pattern:** Calculating a 200-period moving average by fetching 200 rows from the database for every bar.

---

### 6. Schema as Contract

Well-defined schemas are the sole API between components. A schema version is the contract. No "we'll pass a dict and hope fields match." If the schema changes, the version bumps.

**Why:** Implicit contracts fail silently. A schema change that isn't versioned causes runtime errors that are impossible to debug. Explicit contracts mean compile-time (or deploy-time) failures on mismatch.

**Anti-pattern:** Publishing events with "dynamic fields" and hoping consumers handle missing keys.

---

### 7. Self-Healing Systems

Drift detection, performance monitoring, and self-adjustment are baked into the live loop. Components validate their own integrity and trigger recovery without human intervention.

**Why:** Systems that require manual tuning fail in production. Humans set policy; systems execute it. If a component is drifting, the system detects it and restarts or reweights automatically.

**Anti-pattern:** A service that slowly degrades over weeks until someone notices "seems slow" and manually restarts it.

---

### 8. Architectural Invariants Are Non-Negotiable

The system has structural invariants. These are not guidelines — violating any one breaks the guarantees that make the rest of the system work.

**Core invariants:**
- **Single Writer Rule:** Each data stream has exactly one writer. Multiple writers corrupt ordering.
- **No Compute-to-DB Direct Calls:** Hot path components never query the database.
- **All Keys via Registry:** No hardcoded topic names, queue names, or table names.
- **All Timestamps UTC:** Mixed timezones corrupt ordering and analytics.
- **Message Bus Only Coupling:** No component-to-component direct calls.

**Why:** These invariants are the foundation. Violate one and the system can no longer be reasoned about correctly.

---

### 9. Complete Emission

Outputs are fully specified when emitted. No "partial results" that require downstream components to finish the job. If an event is emitted, it is complete and actionable.

**Why:** Partial emissions create hidden intermediate state. Downstream components can't validate incomplete data. If emission is gated, the gate is upstream — not a post-processing step.

**Anti-pattern:** Emitting a "raw signal" that another service must enrich with stops and targets before it's usable.

---

## Coding Standards

### 10. Naming Precision Is Thinking Precision

Every domain term has exactly one definition. The glossary is law. `snake_case` concept names derive all layer names:

```
signal_tracker → SignalTracker (class) → signal_tracker (table)
              → signal_tracker() (topic) → signal-trackers (service)
```

**Why:** Ambiguous names hide bugs. "Ticker" and "symbol" in the same codebase mean someone didn't check the glossary. Inconsistent naming across layers creates confusion and bugs.

**Anti-pattern:** Using `userId`, `user_id`, `User_ID`, and `uid` in the same codebase.

---

### 11. No Magic Numbers

All tunable numeric values live in a registry (APR), accessed via `ConfigService.get(key, default)`. Hard-coded thresholds, weights, periods in code are architecture violations.

**Why:** Magic numbers cannot be tuned without code changes. They hide what's tunable vs. mathematical constant. A value that affects algorithm output belongs in configuration, not in source.

**Anti-pattern:** `if confidence > 0.7:` — what is 0.7? Why 0.7? Can it be tuned?

**Exception:** Statistical concept definitions (the `5` in `momentum_z_5`) and mathematical constants (π) are immutable.

---

### 12. Simple > Clever

Readability beats cleverness. Code is read far more often than it's written. Future you (or a teammate) will thank present you for writing obvious code.

**Why:** Clever one-liners that save 3 characters but require 5 minutes to understand are technical debt. Obvious code is maintainable code.

**Anti-pattern:**
```python
# Clever but opaque
data = filter(lambda x: x and items.get(x), processed)

# Simple and clear
active_items = [item for item in processed if item is not None]
```

---

### 13. Comments Explain WHY, Not WHAT

Code shows what. Comments explain why this approach, why not the alternative, what this guards against.

**Why:** Comments that repeat code are noise at best, misleading at best when code changes. Comments that explain *reasoning* survive code changes and provide context.

**Anti-pattern:**
```python
# BAD: Repeats code
# Increment counter by 1
counter += 1

# GOOD: Explains why
# Hysteresis prevents rapid toggle when signal hovers at threshold
counter += 1
```

---

### 14. Function Length: One Responsibility

If a function is doing two things, split it. Long functions hide bugs, are hard to test, and resist refactoring.

**Why:** Single-responsibility functions are easier to test, easier to understand, and easier to reuse. A 200-line function is a bug farm.

**Rule:** If you need to scroll to see the whole function, it's too long.

---

### 15. Variable Names Are Documentation

`data`, `items`, `values`, `temp` are banned. Variable names convey what the thing IS, not its type.

**Why:** Generic names hide meaning. Six months from now, `active_contracts` tells you what it is. `items` requires reading the whole function.

**Anti-pattern:**
```python
# BAD: Generic names
for item in items:
    process(item)

# GOOD: Specific names
for contract in active_contracts:
    enrich_contract_with_prices(contract)
```

---

### 16. Scripts Are Executable and Self-Documenting

All scripts have shebang, are executable (`chmod +x`), and include usage comments. A teammate should be able to run `./script.py --help` and understand what it does.

**Why:** Scripts that aren't executable are forgotten. Scripts without usage comments require reading source to understand.

**Pattern:**
```python
#!/usr/bin/env python3
"""
Backfill feature vectors from historical OHLCV.

Usage:
    production/scripts/backfill_features.py --symbols SPY TLT --depth 5y

Args:
    --symbols: List of symbols to backfill
    --depth: Historical depth (1y, 5y, 10y)
"""
```

---

### 17. Documentation Is Living

Docs are verified against the codebase. Stale docs are worse than no docs. If the code changed and the doc didn't, the doc is lying.

**Why:** Documentation that doesn't match reality misleads. A missing doc is obvious; a stale doc is dangerous.

**Rule:** When code changes, update the doc in the same commit. When reviewing a PR that changes behavior, check if docs need updating.

---

## Decision Heuristics

When making architectural decisions, ask these questions. If the answer is "no" to any, reconsider.

1. **Survivability:** Would this survive 10x data volume without redesign?
2. **Failure Mode:** What fails silently or introduces hidden bias?
3. **DAG Integrity:** Does the DAG still hold? (No cycles, clear direction)
4. **Elimination:** What manual task does this eliminate?
5. **Complexity Cost:** Is the simplicity gained worth the complexity added?

If you can't answer these clearly, the design isn't ready.

---

## References

- **Renaissance Standards:** `docs/foundation/renaissance-grade-standards.md` — Cleanliness, hygiene, anti-patterns
- **Glossary:** `docs/foundation/glossary.md` — Canonical vocabulary
- **Naming System:** `docs/foundation/naming-system.md` — Full naming convention spec
- **APR:** `docs/foundation/adaptive-parameter-registry.md` — Parameter management
- **Ship or Sink:** `docs/foundation/ship-or-sink-rules.md` — Development workflow
- **DAG Topology:** `docs/architecture/architecture-dag-topology.md` — System map
