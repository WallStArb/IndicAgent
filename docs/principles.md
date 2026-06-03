# Engineering Principles

**Decision frame:** When making any design or architectural decision, think as a council of senior engineers and architects at a fund like Renaissance Technologies. Data integrity is paramount. Every decision compounds — good ones accelerate, bad ones accumulate debt.

---

## The Mindset

Channel Jim Simons: ruthlessly eliminate unnecessary complexity, prioritize clean data flow, and guard against hidden biases or edge-case failures. The system must be correct before it is clever, and simple before it is comprehensive.

- **Rigor over intuition.** Measure, instrument, and verify. Assumptions are liabilities.
- **Compounding quality.** Every refinement makes the next one easier. Shortcuts break that chain.
- **Ruthless simplicity.** Complexity is a cost paid forever. Remove it before it calcifies.
- **Bias awareness.** Hidden assumptions in data pipelines are the most dangerous kind of bug — they produce wrong answers silently.

---

## Architecture Mandates

### 1. Data integrity is non-negotiable
- All timestamps UTC. All DB columns `timestamptz`. No naive datetimes anywhere.
- Data quality over model complexity. A clean signal from a simple model beats a noisy signal from a sophisticated one.
- Shadow mode first. Never promote a component until it has proven itself on live data without consequence.

### 2. Clean DAG topology
- Directed acyclic graphs for all data pipelines. No cycles, no shortcuts that create hidden coupling.
- Each node does one thing. Inputs and outputs are explicit.
- The DAG is the architecture. Violating it means the system is no longer reasoned about correctly.

### 3. Separation of concerns
- Compute is separate from persistence. Analyzers never touch the database.
- Transport is separate from state. Kafka is a sink and a bus, not a state store.
- Coordination is separate from computation. Agents compute; coordinators dispatch; writers persist.

### 4. Async-first, blocking-never
- All I/O is async. Blocking calls in the hot path are architectural defects.
- Backpressure is designed in, not bolted on. Consumer lag is the primary scaling signal.
- asyncio.gather() for fan-out. One await per unit of independent work.

### 5. Instrument everything
- If it isn't measured, it doesn't exist. Latency, throughput, error rates, DLQ depth — all emitted as OTel metrics.
- Liveness signals (watchdog pings, last-message timestamps) are mandatory on every daemon.
- Log events are structured and queryable. Free-text logs are archaeology, not observability.

### 6. Automate the manual
- Any task performed by hand more than once is a candidate for automation.
- Configuration, contract promotion, model registration, health checks — all automated.
- Humans set policy. Systems execute it.

---

## Decision Heuristics

**"Would this survive a 10x data volume?"** If not, it is not architecture — it is a prototype.

**"Where does complexity live?"** Acceptable: business logic in well-named components. Unacceptable: implicit coupling, magic behavior, or load-bearing comments.

**"What fails silently?"** Silent failures (swallowed exceptions, wrong-type defaults, stale cache hits) are worse than loud ones. Design so failures surface.

**"Is this reusable or one-off?"** Prefer patterns that apply across multiple components. Three similar implementations is a signal to extract a shared abstraction.

**"What is the blast radius?"** Scope changes tightly. A data schema change that ripples across 6 services is a design smell.

**"Does the DAG still hold?"** Every new component must fit cleanly into the existing DAG. If it doesn't, the DAG needs to evolve — not be violated.

---

## What These Principles Reject

- Clever code that requires a comment to understand.
- Abstractions added "for future flexibility" that don't serve a current need.
- Manual steps in critical paths (deploys, contract rolls, model promotion).
- Any component that does both compute and persistence.
- Hardcoded values where configuration belongs.
- Operational caution applied to a learning system — fail fast, learn, improve.
