# Service Separation Design

**Date:** 2026-02-20
**Status:** Approved — pending implementation
**Author:** Engineering session (Claude Code + Brandon)

---

## Context

IndicAgent runs a multi-stage intelligence pipeline over Redis Streams. As of v4.8.0 the platform
has eight or more Python processes, but their responsibilities had grown organically and were not
clearly documented. The question driving this session: are the service boundaries engineered
correctly, or do they reflect historical accident?

The goal was not to change the fundamental architecture — Redis Streams as the communication bus,
independent processes per concern — but to audit the boundaries, name things clearly, and fix the
identified design smells before they compound.

---

## Problem Statement

Three concrete issues were found:

**1. I1 computed three times per bar**
- `indicators_processor_service.py` runs I1 and publishes to `indicators:SYMBOL:TF`
- `indicators_enhanced_service.py` runs I1 again (incremental variant)
- `intelligence_processor_service.py` runs I1 a third time *inline*, because consuming the
  indicators stream would require waiting for 23 separate indicator messages per bar — a
  coordination problem it sidesteps by recomputing

**2. Signal lifecycle bundled with signal execution**
`signal_orchestrator_service.py` runs I7 setup plugins, aggregates results, inserts new signals
to the ledger, *and* evaluates open signal lifecycle (stop/target/TTL) — two concerns with
different data dependencies, different failure modes, and different cadences.

**3. Service names require internal domain knowledge**
Names like `intelligence_processor_service` and the tier numbers (I1, I3, I7) are opaque to
anyone unfamiliar with the intelligence tier taxonomy. Service names should be self-describing.

---

## Options Considered

### Option A — Tier-per-process
One process per intelligence tier (I1, I3, I4, I5, I6, I7, I8). Maximum fault isolation.

**Rejected:** Adds 10+ process coordination points. Each tier hop adds ~1ms Redis latency.
I3–I6 run sequentially on the same bar's data — separating them adds latency and complexity
without meaningful fault isolation benefit (they share context and fail together anyway).

### Option B — Natural grouping (chosen)
Group tiers that are tightly coupled by data dependency; separate concerns that are genuinely
independent. Fixes the I1 duplication. Extracts signal lifecycle as a distinct concern.

**Chosen:** Eliminates design smells, keeps latency low, reduces process count, uses clear names.

### Option C — Document and fix smells only
Keep the current process structure, fix I1 duplication, retire the duplicate indicator services,
write the separation-of-duties doc.

**Rejected:** Leaves `intelligence_processor_service` as a multi-concern monolith. Defers the
signal lifecycle split. Technical debt compounds as more I7 plugins are added.

---

## Decision: Option B — Natural Grouping

### Service Map (Target Architecture)

| Service | Single Responsibility | Publishes To |
|---------|----------------------|--------------|
| `market_data_daemon` | IBKR connection, tick ingest, bar formation | `market:SYMBOL:1m`, `ticks:SYMBOL:live`, `price:SYMBOL:latest` |
| `indicator_service` | All 23 I1 plugins (incremental), one combined message per bar | `indicators:SYMBOL:TF` |
| `bar_aggregator_service` | Resample 1m bars into 5m/15m/1h/4h/1d | `market:SYMBOL:TF` |
| `market_analysis_service` | I3 structure → I4 context → I5 patterns → SMC → I6 confluence | `intelligence:SYMBOL:TF` |
| `signal_generator_service` | I7 setup plugins, aggregation, initial signal_ledger insert | `signals:SYMBOL:TF:aggregated` |
| `signal_tracker_service` | Lifecycle evaluation of open signals (stop/target/TTL) | DB updates (signal_ledger) |
| `narrative_service` | I8 LLM synthesis from aggregated signals | `narratives:SYMBOL:TF` |
| `api_service` | FastAPI REST + SSE for dashboard | Dashboard |

### Key Design Decisions

**I1 publishes one combined message per bar**
The original I1 coordination problem (waiting for 23 separate indicator messages) is solved by
having `indicator_service` publish a single message containing OHLCV + all I1 fields as flat
key-value pairs — the same format `intelligence_processor_service` currently uses internally.
`market_analysis_service` sees one message per bar, has all I1 features, and runs I3–I6
immediately. One extra Redis hop (~0.5ms) is the only latency cost.

**`signal_tracker_service` subscribes to `market:SYMBOL:1m`, not `intelligence:SYMBOL:TF`**
Lifecycle evaluation only needs OHLCV (did price cross the stop or target?). This means
tracking continues even if the intelligence pipeline is stopped for maintenance — open positions
remain monitored.

**Stream key names are unchanged**
`indicators:SYMBOL:TF` and `intelligence:SYMBOL:TF` keep their current names. The semantic
meaning of each stream becomes clearer, but no downstream consumers need to change.

**`coordination_parallel_service` to be audited**
Redis Streams consumer groups already provide self-coordination. This service may be redundant
and is a candidate for retirement during implementation.

### Services Retired

- `indicators_processor_service.py` — superseded by `indicator_service`
- `indicators_enhanced_service.py` — merged into `indicator_service` (incremental state preserved)

---

## Migration Path

Sequentially, each step independently verifiable:

1. **Consolidate I1** — create `indicator_service.py` combining incremental I1 state from
   `indicators_enhanced_service`. Publish combined OHLCV+I1 message to `indicators:SYMBOL:TF`.
   Run alongside existing services to verify output parity. Retire old services.

2. **Update market_analysis_service** — remove inline I1 computation from
   `intelligence_processor_service.py`. Change consumer to read from `indicators:SYMBOL:TF`
   instead of `market:SYMBOL:1m`. Rename file to `market_analysis_service.py`.

3. **Extract signal_tracker_service** — move lifecycle evaluation (`evaluate_signal` calls) out
   of `signal_orchestrator_service.py` into `signal_tracker_service.py`. The orchestrator stops
   calling `evaluate_signal`; the tracker handles it by subscribing to `market:SYMBOL:1m`.
   Rename orchestrator file to `signal_generator_service.py`.

4. **Audit coordination_parallel_service** — determine if it is still needed. Retire if not.

5. **Update config, systemd units, docs** — rename configs, update `services/README.md`,
   root `README.md`, `CLAUDE.md` service table, and systemd unit files.

Each step keeps unit tests passing. No plugin code changes required at any step.

---

## Reference

- Architecture reference: `docs/architecture/service-separation.md`
- Stream schemas: `docs/architecture/stream-schemas.md`
- Implementation plan: `docs/plans/2026-02-20-service-separation.md` (to be created)
