# Concepts Library Rebuild — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `docs/concepts/` into a 13-doc Renaissance-grade knowledge library — reusable intellectual artifacts at the concept level, usable as recipe cards for new system design.

**Architecture:** Two sequential parts. Part A (rescue pass) migrates implementation detail from concepts/ into domain docs so nothing is lost before files are rewritten. Part B rebuilds the library: 8 rewrites and 5 new docs, each following a strict recipe-card structure. Parts A and B must not be interleaved — complete all Part A commits before starting Part B.

**Tech Stack:** Markdown, git. No code changes. All writes are documentation only.

**Spec:** `docs/plans/2026-05-29-concepts-library-design.md`

---

## Recipe-Card Template

Every concept doc in Part B follows this exact structure. Refer back here for each task.

```markdown
# [Concept Name]
> [One sentence: the irreducible definition]

## The Problem It Solves
[What goes wrong without this concept. Concrete failure mode, 2-4 sentences.]

## The Principle
[Abstract definition. Mathematical or systems rationale where applicable.
No IndicAgent-specific code — system-agnostic.]

## How IndicAgent Applies It
[Specific design choices. Links to domain docs for implementation detail.
What's shipped vs. what's roadmap if applicable.]

## Invariants
[Hard rules derived from this concept. Minimum 2.
Format: "X must never Y." or "Every Z must W."]

## Recipe
[Decision checklist for someone building a new system.
Not IndicAgent instructions — transferable design questions.
Format: bulleted questions or a decision table.]

## See Also
[Links to domain docs, ideas/, related concepts in this library.]
```

---

## File Map

### Part A — Domain doc modifications (rescue)

| File | Change |
|------|--------|
| `docs/intelligence/intelligence-foundation.md` | Append adaptive weights + calibration chain detail to CIS section |
| `docs/intelligence/intelligence-plugins.md` | Append reliability/error handling + performance characteristics |
| `docs/intelligence/intelligence-operations.md` | Append performance characteristics (if better fit than plugins.md) |
| `docs/intelligence/intelligence-ai.md` | Append eAI substrate inventory section |
| `docs/foundation/naming-conventions.md` | Append tier naming system content |

### Part B — Concepts library

| File | Status |
|------|--------|
| `docs/concepts/hot-path-isolation.md` | New |
| `docs/concepts/event-driven-fabric.md` | New |
| `docs/concepts/temporal-data-architecture.md` | New |
| `docs/concepts/observability-and-traceability.md` | New |
| `docs/concepts/autonomous-resilience.md` | New |
| `docs/concepts/dag-execution.md` | Rewrite in place |
| `docs/concepts/incremental-computation.md` | Rewrite in place |
| `docs/concepts/progressive-intelligence-extraction.md` | New (replaces intelligence-tiers.md) |
| `docs/concepts/plugin-composability.md` | New (replaces plugin-architecture.md) |
| `docs/concepts/regime-awareness.md` | New (replaces regime-classification.md) |
| `docs/concepts/evidence-graded-signals.md` | New (replaces cis-scoring.md) |
| `docs/concepts/adaptive-intelligence.md` | New (replaces evolvable-ai.md) |
| `docs/concepts/swarm-intelligence.md` | Rewrite in place |
| `docs/concepts/README.md` | Rewrite |
| `docs/concepts/intelligence-tiers.md` | Delete (after progressive-intelligence-extraction.md committed) |
| `docs/concepts/plugin-architecture.md` | Delete (after plugin-composability.md committed) |
| `docs/concepts/regime-classification.md` | Delete (after regime-awareness.md committed) |
| `docs/concepts/cis-scoring.md` | Delete (after evidence-graded-signals.md committed) |
| `docs/concepts/evolvable-ai.md` | Delete (after adaptive-intelligence.md committed) |
| `docs/concepts/tier-naming-system.md` | Delete (after naming-conventions.md updated) |

---

## PART A — Rescue Pass

### Task 1: Rescue cis-scoring.md → intelligence-foundation.md

**Files:**
- Modify: `docs/intelligence/intelligence-foundation.md` (after line 291 — end of CIS section, before Renaissance Checklist)
- Source: `docs/concepts/cis-scoring.md` sections: Adaptive Weights, Signal Confidence Calibration Chain, 5 Plugins That Feed CIS

- [ ] **Step 1: Read the source material**

Read `docs/concepts/cis-scoring.md` lines 148-241 (Adaptive Weights section through end of file). Understand the two-system composition before writing.

- [ ] **Step 2: Append adaptive weights detail to intelligence-foundation.md**

Add the following after the Six-Layer Self-Correction block (before `## Renaissance Checklist`):

```markdown
### Adaptive Weight Systems

Two independent weight systems govern signal scoring. Do not conflate them.

**1. CIS Bucket Weights** — governs which *direction* to trust

Bootstrap weights (version 0) are manually tuned. The architecture supports learned weights loaded from `cis_weights` DB table. When `version > 0` exists, the scorer loads it at startup. Every `CISResult` carries `weights_version` — all signals in `signal_ledger` are traceable to the exact weight set that produced them.

```
signal fires (weight version N)
  → signal_tracker_compute_agent tracks outcome (stop / target / TTL)
  → outcome written to signal_ledger
  → weight-learning job reads outcomes, fits logistic regression per bucket
  → new weights written to cis_weights (version N+1)
  → scorer loads version N+1 at next restart
```

**2. Setup Performance Weights** — governs which *setup plugin* to prefer

Independent of CIS scoring. Applied as a Sharpe-normalized performance multiplier on setup ranking.

```
signal_metrics table (rolling 30-day):
  setup_plugin, tf, symbol, regime_type, track, window_days, n, sharpe

perf_multiplier = 0.5 + ((n - 1 - rank) / n)   range [0.5, 1.5]
  rank = ascending Sharpe rank (best Sharpe → rank n-1 → highest multiplier)

Promotion gate: n >= 30 required — below threshold multiplier = 1.0 (neutral)
Regime conditioning: weights loaded per current HMM regime_type
  symbol-specific weights take precedence; '*' wildcard is fallback
```

`IntelligencePipelineComputeAgent` loads weights at startup and refreshes every hour. No Redis — weights flow: `signal_metrics` table → in-memory `_perf_weights` dict.

**Composition:** CIS governs which *direction* has cross-tier confirmation. Performance weights govern which *setup plugin* to prefer within the eligible pool. Neither overwrites the other.

### Signal Confidence Calibration Chain (Detail)

Full six-layer pipeline with implementation notes:

1. **Isotonic Calibration** — raw confidence values are systematically biased. Isotonic regression maps them to empirically calibrated values. Raw value stored as `pre_calibration_confidence`; output as `calibrated_confidence`.

2. **Time-of-Day (TOD) Multiplier** — 120 cells: `(regime_type, timeframe, hour_et)`. Computed from rolling historical win rates. A trend setup at RTH open behaves differently than the same setup at 2pm.

3. **Performance Multiplier** (`perf_multiplier`) — rolling 30-day Sharpe and win rate per setup per regime. Gate: N < 30 → `perf_multiplier = 1.0`.

4. **KS Drift Monitor** — Kolmogorov-Smirnov test compares current feature distributions against historical baseline. Feature drift → proportional CIS bucket weight penalty.

5. **CUSUM Monitor** — cumulative sum control charts track win rate per setup. Degradation reduces performance weight automatically; recovery restores it.

6. **Shadow Mode Gate** — `shadow_registry` auto-enrollment at startup. Promotion: `n >= 100` AND `bootstrap_ci_lower(pnl_r) > 0.0`. Demotion: `EV[R] < -0.05` for 3 consecutive cycles.

Swarm overlay applies after calibration: `adjusted_confidence = calibrated_confidence × swarm_multiplier` (MoA composite from 5 alpha swarm agents).
```

- [ ] **Step 3: Verify the section lands correctly**

```bash
grep -n "Adaptive Weight\|perf_multiplier\|Isotonic\|CUSUM" docs/intelligence/intelligence-foundation.md
```

Expected: lines present, no duplication of existing content.

- [ ] **Step 4: Commit**

```bash
git add docs/intelligence/intelligence-foundation.md
git commit -m "docs(rescue): migrate CIS adaptive weights + calibration chain from concepts/ to intelligence-foundation"
```

---

### Task 2: Rescue plugin-architecture.md → intelligence docs

**Files:**
- Modify: `docs/intelligence/intelligence-plugins.md` (append reliability/error handling section)
- Modify: `docs/intelligence/intelligence-operations.md` (append performance characteristics)
- Source: `docs/concepts/plugin-architecture.md` sections: Reliability & Error Handling (line 401), Performance Characteristics (line 441)

- [ ] **Step 1: Read source sections**

Read `docs/concepts/plugin-architecture.md` lines 401-452 (Reliability & Error Handling and Performance Characteristics).

- [ ] **Step 2: Append to intelligence-plugins.md**

Add before the `## See Also` section of `docs/intelligence/intelligence-plugins.md`:

```markdown
## Reliability & Error Handling

### Plugin Failure Isolation

Each plugin runs inside try/except in the pipeline executor. A plugin that raises an exception is skipped for that bar — the pipeline continues with other plugins. Error is logged with plugin name and bar context.

**Contract:** A plugin must never raise on bad input data. Validate inputs and return `None` outputs if data is insufficient (e.g., warmup not complete, NaN inputs).

### Plugin Validation at Startup

`PluginValidator` checks all registered plugins at pipeline startup:
- Output field names declared in plugin's schema match `IntelligenceEvent` fields
- No circular dependencies in the DAG
- Warmup requirements are positive integers
- `supports_incremental` flag is consistent with `compute_next()` implementation

Startup fails fast if validation fails — prevents silent bad-data propagation.

### Error State Persistence

Plugin state is checkpointed to disk (`cache/plugin_states.json`) every N bars. On restart, state is restored so warmup periods are not replayed from scratch. If a checkpoint is corrupt or missing, the plugin reinitializes from scratch (warmup period replays).
```

- [ ] **Step 3: Append to intelligence-operations.md**

Add to `## Performance` section of `docs/intelligence/intelligence-operations.md`:

```markdown
### Plugin Performance Characteristics

| Metric | Value |
|--------|-------|
| Sequential bar processing | `await _process_bar` — one bar at a time |
| Per-bar latency (production) | Measured by `intelligence_pipeline_pipeline_latency_ms` gauge at `:8000/metrics` |
| Plugin count | 132 plugins + 2 aggregation components across I1-I7 |
| Thread-pool workers | 12 (GIL cap for CPU-bound plugins) |
| Backfill replay throttle | 10 bars/sec (`BAR_REPLAY_BARS_PER_SEC`) — not representative of pipeline ceiling |

**Bottleneck:** The sequential `_process_bar` await is the primary throughput limit. Each bar must complete all 132 plugins before the next bar begins. I1-I4 run in waves; I5-I7 run after I4 completes.

**GIL note:** Python GIL limits true parallelism for CPU-bound plugins. The 12 thread-pool workers help I/O-bound operations but CPU-bound indicator math is effectively single-threaded per bar.
```

- [ ] **Step 4: Verify**

```bash
grep -n "Plugin Failure\|Plugin Validation\|Plugin Performance\|GIL cap" docs/intelligence/intelligence-plugins.md docs/intelligence/intelligence-operations.md
```

Expected: lines present in both files.

- [ ] **Step 5: Commit**

```bash
git add docs/intelligence/intelligence-plugins.md docs/intelligence/intelligence-operations.md
git commit -m "docs(rescue): migrate plugin reliability + performance detail from concepts/ to intelligence docs"
```

---

### Task 3: Rescue evolvable-ai.md → intelligence-ai.md

**Files:**
- Modify: `docs/intelligence/intelligence-ai.md` (append eAI substrate section after Shadow Governance)
- Source: `docs/concepts/evolvable-ai.md` section: Existing Infrastructure (line 86)

- [ ] **Step 1: Read source section**

Read `docs/concepts/evolvable-ai.md` lines 86-121 (Existing Infrastructure and Implementation Phases sections).

- [ ] **Step 2: Append eAI substrate to intelligence-ai.md**

Add after `## Shadow Governance` section (before `## Lineage Recording`):

```markdown
## eAI Substrate (v2.8)

The infrastructure for evolvable AI agents is operational. eAI agents (v2.8 roadmap) build on this existing substrate — no new infrastructure needed.

| Component | Status | Purpose |
|-----------|--------|---------|
| `shadow_registry` table | Live | Auto-enrolls all I7 plugins and swarm agents at startup |
| Signal ledger outcome tracking | Live | Fitness evaluation data accumulates per signal |
| `LineageRecorder` | Live | Full ancestry tracking per agent call |
| Skeptic agent | Live | Adversarial coevolution — challenges other swarm agents |
| `BaseAIAgent` framework | Live | Agent parameter variations implement genome mutations |
| `llm_calls` audit trail | Live | Every LLM call persisted with prompt version; outcome back-filled |
| `bootstrap_ci_lower()` | Live | Statistical gate in `src/core/stats_utils.py` |
| `ShadowTransitionEvent` | Live | Promotion/demotion published to `topic_shadow_transitions` |

**Design principle:** eAI agents are `BaseAIAgent` subclasses with an additional `genome` parameter dict. Reproductive operators (mutation, crossover, selection) are applied to the genome dict between evaluation cycles. The shadow governance lifecycle handles statistical gating before any mutant agent affects production scoring.

See `docs/ideas/ai-03-evolvable-ai-agents.md` for the full research vision and `docs/ideas/eai-phase-recommendations.md` for the v2.8 implementation roadmap.
```

- [ ] **Step 3: Verify**

```bash
grep -n "eAI Substrate\|shadow_registry\|genome" docs/intelligence/intelligence-ai.md | head -10
```

Expected: new section present.

- [ ] **Step 4: Commit**

```bash
git add docs/intelligence/intelligence-ai.md
git commit -m "docs(rescue): migrate eAI substrate inventory from concepts/ to intelligence-ai"
```

---

### Task 4: Move tier-naming-system.md → foundation/naming-conventions.md

**Files:**
- Modify: `docs/foundation/naming-conventions.md` (append content)
- Delete: `docs/concepts/tier-naming-system.md`
- Source: `docs/concepts/tier-naming-system.md` (full file, 204 lines)

- [ ] **Step 1: Read both files**

Read `docs/foundation/naming-conventions.md` (56 lines) and `docs/concepts/tier-naming-system.md` (204 lines) to understand existing content and avoid duplication.

- [ ] **Step 2: Append tier naming content to naming-conventions.md**

Add a new section at the end of `docs/foundation/naming-conventions.md`:

```markdown
---

## Intelligence Tier Naming System

Tiers have both a code (`I1`–`I8`) and a functional name. Both are valid in documentation and code; use whichever aids clarity.

### Tier Mapping

| Code | Functional Name | `snake_case` | Usage |
|------|----------------|--------------|-------|
| I1 | Technical Indicators | `technical_indicators` | Plugin tier key, log tags |
| I2 | Composite Events | `composite_events` | |
| I3 | Market Structure | `market_structure` | |
| I4 | Regime Classification | `regime_classification` | |
| I5 | Pattern Detection | `pattern_detection` | |
| I6 | Smart Money Concepts | `smart_money_concepts` | Also: `smc` shorthand in event keys |
| I7 | Trading Signals | `trading_signals` | |
| I8 | AI Narrative | `ai_narrative` | |

### Usage Guidelines

- **In code:** Use `snake_case` functional names as dict keys and topic suffixes (e.g., `i1/technical_indicators`)
- **In docs:** Tier codes (`I1`–`I8`) for brevity; functional names when clarity matters
- **In logs:** Tier codes preferred for width constraints
- **In metrics:** `snake_case` functional name as label value

### Conversion API

`src/core/stream_keys.py` contains `tier_to_functional_name(tier_code)` and `functional_name_to_tier(name)` for programmatic conversion.

See `src/intelligence/register_plugins.py` `TIER_I1`..`TIER_I7` for the canonical tier lists.
```

- [ ] **Step 3: Delete tier-naming-system.md**

```bash
git rm docs/concepts/tier-naming-system.md
```

- [ ] **Step 4: Verify naming-conventions.md is coherent**

```bash
wc -l docs/foundation/naming-conventions.md
grep -n "^## " docs/foundation/naming-conventions.md
```

Expected: file has grown by ~60 lines, new section present.

- [ ] **Step 5: Commit**

```bash
git add docs/foundation/naming-conventions.md
git commit -m "docs(rescue): move tier naming system from concepts/ to foundation/naming-conventions"
```

---

## PART B — Concepts Library Rebuild

**Before starting Part B:** Verify all Part A commits are done.

```bash
git log --oneline -4
```

Expected: 4 rescue commits visible.

---

### Task 5: Write hot-path-isolation.md (Layer 1 — new)

**Files:**
- Create: `docs/concepts/hot-path-isolation.md`
- Source material: `docs/architecture/overview.md`, `docs/intelligence/intelligence-foundation.md` (Data Flow section), CLAUDE.md (Hot/Warm/Cold data flow, "Real-time pipeline never touches the database directly")

- [ ] **Step 1: Read source material**

Read `docs/intelligence/intelligence-foundation.md` lines 121-170 (Data Flow section). Read CLAUDE.md data flow block.

- [ ] **Step 2: Write the doc**

```markdown
# Hot-Path Isolation
> Real-time compute is strictly isolated from storage and I/O — the hot path never blocks on a database or network call.

## The Problem It Solves

A naively built trading system puts database writes on the critical path: a bar arrives, the system queries historical data, writes features, reads signals, and only then generates a decision. Under load, I/O latency compounds — a 5ms DB round-trip repeated 132 times per bar produces 660ms of unavoidable latency, and any DB outage stops signal generation entirely.

## The Principle

Separate the system into three latency tiers with strict rules about what each tier can do:

- **Hot path** (sub-millisecond): Stateless compute only. Reads from in-memory state. Writes to nothing. Cannot block.
- **Warm path** (<10ms): Stream routing, topic fan-out. Reads topic offsets. Cannot touch the database.
- **Cold path** (async, batch): Persistence workers consume from topics and write to storage. Completely decoupled from hot-path timing.

The invariant: **no component on the hot path may call I/O.** Hot-path state is loaded once at startup and updated incrementally per bar. If the database goes down, signal generation continues uninterrupted.

## How IndicAgent Applies It

```
Hot:  IBKR TWS → Redpanda Streams → IntelligencePipelineComputeAgent   (sub-ms)
Warm: Streams → I1-I7 plugin DAG → ranked signals + feature vectors    (<10ms)
Cold: FeatureWriterAgent + SignalWriterAgent → TimescaleDB              (async batch)
```

The intelligence pipeline (I1-I7) is fully DB-ignorant. It reads from in-memory plugin state (loaded at startup, updated per bar) and publishes results to Kafka topics. Dedicated WriterAgents (`FeatureWriterAgent`, `SignalWriterAgent`, `LifecycleWriterAgent`) consume those topics and handle persistence asynchronously.

Performance weights, CIS weights, and regime state are loaded at startup and refreshed on a timer (not per-bar). Plugin state is checkpointed to local disk — not to the database.

## Invariants

- The real-time pipeline (`IntelligencePipelineComputeAgent`) must never import or call `database_manager`.
- Plugin `compute()` and `compute_next()` methods must be pure functions of their input + internal state.
- WriterAgents consume from topics — they never receive direct calls from compute agents.
- A `TimescaleDB` outage must have zero impact on signal generation latency or throughput.

## Recipe

When designing a new real-time intelligence system:

1. **Classify every operation** — is this hot (compute), warm (routing), or cold (persistence)?
2. **Forbid cross-tier calls** — hot path cannot call warm or cold. Enforce at code review.
3. **Load state at startup** — weights, thresholds, reference data. Refresh on a timer, never per-event.
4. **Design for DB outage** — if the DB goes down for 10 minutes, what breaks? That list is your hot-path violations.
5. **Instrument the boundary** — measure hot-path latency separately from cold-path write latency. They should be uncorrelated.

## See Also

- Implementation: `docs/intelligence/intelligence-foundation.md` — Data Flow section
- Related concept: `docs/concepts/event-driven-fabric.md` — why Kafka is the decoupling mechanism
- Related concept: `docs/concepts/incremental-computation.md` — how hot-path state is maintained O(1)
- Operations: `docs/intelligence/intelligence-operations.md` — latency breakdown and tuning
```

- [ ] **Step 3: Verify structure**

```bash
grep -n "^## " docs/concepts/hot-path-isolation.md
```

Expected: The Problem It Solves, The Principle, How IndicAgent Applies It, Invariants, Recipe, See Also.

- [ ] **Step 4: Commit**

```bash
git add docs/concepts/hot-path-isolation.md
git commit -m "docs(concepts): add hot-path-isolation concept doc (Layer 1)"
```

---

### Task 6: Write event-driven-fabric.md (Layer 1 — new)

**Files:**
- Create: `docs/concepts/event-driven-fabric.md`
- Source material: `docs/data/data-streaming.md`, `docs/agents/agents-foundation.md`, CLAUDE.md Kafka rules

- [ ] **Step 1: Read source material**

Read `docs/data/data-streaming.md` — focus on ADRs and design principles sections. Read CLAUDE.md rules: "Kafka is transport, not state store", "No agent calls another directly", stream key rules.

- [ ] **Step 2: Write the doc**

```markdown
# Event-Driven Fabric
> Agents communicate exclusively through named topics — no agent ever calls another directly.

## The Problem It Solves

Direct inter-agent calls create invisible coupling: agent A's latency affects agent B, a crash in A blocks B, deploying a new version of A requires coordinating with every caller. In a system with 20+ agents, point-to-point coupling produces a dependency web that cannot be reasoned about or restarted safely.

## The Principle

Every agent publishes events to topics and subscribes to topics. No agent holds a reference to another agent. The fabric (Kafka/Redpanda) is the only shared resource between agents. An agent can be restarted, replaced, or scaled independently without affecting any other agent — each resumes from its committed offset with no data loss.

This makes the system topology a first-class artifact: the full data flow is visible by examining topic subscriptions, not by tracing call graphs through code.

## How IndicAgent Applies It

All inter-agent communication flows through Redpanda (Kafka-compatible). Topic names are constructed via `src/core/stream_keys.py` — never hardcoded. The `env_prefix` from `Settings` namespaces all topics, preventing cross-environment contamination.

Key design decisions:
- **Kafka is transport, not state store.** Retention is minimal — topics are not replayed for state reconstruction. Hot state lives in local file checkpoints; historical data lives in TimescaleDB.
- **Topics use dots not colons** (Redpanda convention). `stream_keys.py` enforces this.
- **Consumer groups are service-scoped** — each service has its own group ID, so restarts resume from committed offsets automatically.
- **The `KafkaProducerClient.publish()` kwarg is `msg=`** (not `value=`). Wrong kwarg silently fails at flush.

```
Bar arrives → intelligence_pipeline → topic_intelligence_features
                                    → topic_signal_ledger
                                    → topic_shadow_transitions

topic_intelligence_features → feature_writer_service → TimescaleDB
topic_signal_ledger         → signal_writer_service  → TimescaleDB
topic_shadow_transitions    → swarm_ledger_writer    → TimescaleDB
```

## Invariants

- No agent may import or instantiate another agent class directly.
- All topic names must be constructed via `stream_keys.py`. No hardcoded topic strings.
- `INDICAGENT_ENV` must be consistent across all services — mixed env prefixes cause services to subscribe to different topics, producing zero data flow with no error.
- `KafkaProducerClient.publish()` calls must `await` the result — fire-and-forget silently drops messages.

## Recipe

When designing an event-driven agent system:

1. **Define topics before agents** — the topic schema is the API contract between agents.
2. **Name topics after the event, not the producer** — `topic_intelligence_features` not `topic_pipeline_output`.
3. **Namespace by environment** — prevents dev/prod data mixing.
4. **Consumer groups per service** — enables independent restart and scaling.
5. **Treat Kafka as transport** — if you need Kafka for state reconstruction, your agents have no local state management and will be slow on restart.
6. **Audit every `publish()` call** — confirm it is awaited and the kwarg name matches the client's API.

## See Also

- Implementation: `docs/data/data-streaming.md` — full topic catalog, ADRs, stream key conventions
- Related concept: `docs/concepts/hot-path-isolation.md` — why isolation is possible given this fabric
- Code: `src/core/stream_keys.py` — canonical topic construction
```

- [ ] **Step 3: Verify structure**

```bash
grep -n "^## " docs/concepts/event-driven-fabric.md
```

- [ ] **Step 4: Commit**

```bash
git add docs/concepts/event-driven-fabric.md
git commit -m "docs(concepts): add event-driven-fabric concept doc (Layer 1)"
```

---

### Task 7: Write temporal-data-architecture.md (Layer 1 — new)

**Files:**
- Create: `docs/concepts/temporal-data-architecture.md`
- Source material: `docs/operations/timescaledb-gotchas.md`, `docs/data/data-foundation.md`, CLAUDE.md table definitions, principles "Never Drop Data That Could Contain Signal"

- [ ] **Step 1: Read source material**

Read `docs/operations/timescaledb-gotchas.md` fully. Read CLAUDE.md TimescaleDB table section and principle 9 (Never Drop Data).

- [ ] **Step 2: Write the doc**

```markdown
# Temporal Data Architecture
> Every market event is a timestamped, immutable record — nothing is dropped, everything is queryable by time.

## The Problem It Solves

Generic relational databases treat time as just another column. This leads to: slow range queries requiring full-table scans, no native compression for time-series data, schema designs that mix mutable state with immutable events, and lost history when records are updated in-place. For a quantitative system where every historical signal is a labeled training sample, these are fatal flaws.

## The Principle

Time-series data has a natural append-only structure — events happen, are recorded, and never change. A temporal data architecture exploits this:

1. **Hypertables** — partition data automatically by time. Range queries hit only the relevant partitions.
2. **Compression** — time-ordered data compresses at 10-20x versus row-store. Old data costs nearly nothing.
3. **Immutable events** — never UPDATE a row that represents something that happened. Corrections are new rows.
4. **No retention policies** — storage is the cheapest resource. Every data point is a potential training sample.

## How IndicAgent Applies It

TimescaleDB (PostgreSQL extension) is used for all time-series tables. Three primary hypertables:

| Table | Time column | Purpose |
|-------|-------------|---------|
| `market_data_ohlcv` | `timestamp` | Raw OHLCV bars |
| `intelligence_features` | `ts` | Full feature vectors per bar (I1-I7 outputs) |
| `signal_ledger` | `timestamp` | All signals + lifecycle outcomes, forever |

**`signal_ledger` is the crown jewel.** Every I7 signal ever fired is stored with its full feature context, entry/exit prices, PnL-R, MAE, MFE, and outcome. This is the labeled training dataset for every future model. It has no retention policy and never will.

**Volume Profile columns:** `poc_price`/`vah`/`val` = session VP (1m/5m); `poc_price_rolling`/`vah_rolling`/`val_rolling` = rolling VP (15m/1h). Different names for semantically different calculations — do not conflate.

**Connection pattern:** All DB access via `asyncpg` through `src/core/database_manager.py`. JSONB columns return `dict` directly — never call `json.loads()` on asyncpg results. Timestamps return `datetime` objects. Always `str()` UUID values before JSON serialization.

**Connection safety:** `conn.fetch()` results must be consumed inside the `async with get_connection()` block. Assigning outside risks `NameError` if `fetch()` raises.

## Invariants

- No table that records a market event may have rows deleted or updated in place.
- `intelligence_features`, `signal_ledger`, and `llm_calls` have no retention policies — ever.
- All timestamps stored as `timestamptz` (UTC). `datetime.now(UTC)` only — never `datetime.now()` or `datetime.utcnow()`.
- DB queries use `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent`. Plain `psql -U postgres` fails (no socket auth).

## Recipe

When designing time-series storage for a new system:

1. **Choose a time-series native DB** — TimescaleDB, InfluxDB, QuestDB. Generic SQL is a poor fit.
2. **Identify immutable event tables vs. mutable state tables** — different retention and access patterns.
3. **Never drop historical signal data** — today's noise is tomorrow's training sample.
4. **Design the schema around queries** — time-range queries and point lookups have different optimal layouts.
5. **Separate hot state from cold storage** — real-time systems should not query the DB on the hot path (see `hot-path-isolation.md`).
6. **Timestamp discipline from day one** — all timestamps UTC, stored as `timestamptz`, ISO-8601 with Z suffix in JSON.

## See Also

- Operations: `docs/operations/timescaledb-gotchas.md` — asyncpg patterns, connection gotchas
- Related concept: `docs/concepts/hot-path-isolation.md` — why DB is on the cold path only
- Data layer: `docs/data/data-foundation.md` — table schemas, hypertable configuration
```

- [ ] **Step 3: Commit**

```bash
git add docs/concepts/temporal-data-architecture.md
git commit -m "docs(concepts): add temporal-data-architecture concept doc (Layer 1)"
```

---

### Task 8: Write observability-and-traceability.md (Layer 4 — new)

**Files:**
- Create: `docs/concepts/observability-and-traceability.md`
- Source material: `docs/platform/platform-observability.md`, CLAUDE.md OTel health contract (D-04, D-06, D-27), `llm_calls` audit trail

- [ ] **Step 1: Read source material**

Read `docs/platform/platform-observability.md` fully. Read CLAUDE.md OTel Health Contract section (D-04, D-06, D-27 SLO alerts).

- [ ] **Step 2: Write the doc**

```markdown
# Observability and Traceability
> Every decision the system makes is measurable, attributable, and auditable — from a raw bar to a fired signal to an LLM call to a position outcome.

## The Problem It Solves

A quantitative system that cannot explain its own decisions is not a quantitative system — it is a black box that happens to trade. Without observability: bugs are found by traders, not engineers; latency regressions are invisible until they matter; signal quality degrades silently; and post-mortems are guesswork. Traceability adds the dimension of time: not just "what is happening now" but "what happened at 14:32:07 on Tuesday and why."

## The Principle

Observability is infrastructure, not afterthought. Three pillars:

1. **Metrics** — quantitative measurements over time (counters, histograms, gauges). Answer: "is the system healthy?"
2. **Traces** — causal chains linking events across services. Answer: "why did this signal fire?"
3. **Audit logs** — immutable records of every decision with full context. Answer: "what exactly happened?"

These three are complementary. Metrics tell you something is wrong. Traces tell you where. Audit logs tell you what the system was thinking.

## How IndicAgent Applies It

**Metrics** are emitted via OTel SDK (`src/observability/metrics.py`). Every `BaseAgent` subclass automatically emits five mandatory signals:

| Signal | Type | Purpose |
|--------|------|---------|
| `agent_last_message_timestamp_seconds` | gauge | Liveness — updated every processed message |
| `agent_crash_total` | counter | Uncaught exceptions in `_run()` |
| `agent_dlq_total` | counter | Dead-letter queue routing events |
| `watchdog_notify_total` | counter | Successful systemd `WATCHDOG=1` pings |
| `watchdog_notify_suppressed_total` | counter | Agent alive but idle/stalled |

Scrape endpoint: `:8000/metrics`. Grafana at `:3001`.

**Traces** use OTel spans via `observed_span()` from `src/observability/spans.py`. Auto-records ERROR status and exception on raise. `ATTR_*` constants from the same module — no raw strings.

**Audit logs** — every LLM call is persisted to `llm_calls` table with full context: `call_id`, `agent_id`, `prompt_version`, `symbol`, `signal_id`, `regime`. Outcome is back-filled by `llm_writer_service` when the signal resolves. This enables prompt A/B testing, per-agent performance scoring, and full decision archaeology.

**D-27 SLO alerts** (Grafana):
- `agent_last_message_timestamp_seconds` stale > 120s → page
- `watchdog_notify_suppressed_total` rate > 0 → warning
- Any oneshot `job_completed_total{status="failure"}` → warning

**Oneshot contract (D-06):** Timer-triggered scripts emit `job_completed_total{job, status}` at exit. `job` label must match systemd unit `%n` suffix exactly (kebab-case).

## Invariants

- Every new `BaseAgent` subclass inherits the 5 mandatory OTel signals — no per-service instrumentation code needed.
- `prometheus_client` must never be imported — OTel SDK only.
- Counters: `.add(1, {"label": val})`. Histograms: `.record(val, {"label": val})`. Point gauges: `.set(value, {"label": val})`. Wrong call pattern silently fails.
- The `llm_calls` composite PK is `(call_id, called_at)` — ON CONFLICT must include both columns.
- `prompt_version` class attribute is mandatory on every `BaseAIAgent` subclass — enables prompt A/B testing in `llm_calls`.

## Recipe

When designing observability for a new system:

1. **Define the five baseline signals for every agent** — liveness, crashes, DLQ, watchdog. These are non-negotiable.
2. **Audit logs are not logs** — structured records in a queryable store, not text files. Design the schema before the agent.
3. **Trace the decision chain** — from input event to output decision, every intermediate step should be attributable.
4. **Version everything that affects decisions** — model versions, prompt versions, weight versions. Store them with the decision.
5. **SLO alerts before features** — define what "healthy" looks like before building. Alerts at deployment, not after incidents.
6. **Separate operational metrics from business metrics** — `agent_crash_total` is operational; `signal_win_rate` is business. Both matter; they live in different dashboards.

## See Also

- Implementation: `docs/platform/platform-observability.md` — OTel instruments, Grafana setup, D-27 SLO alerts
- Agent contract: `docs/agents/agents-foundation.md` — BaseAgent mandatory OTel signals
- Audit trail: `docs/intelligence/intelligence-ai.md` — `llm_calls` schema and back-fill pattern
```

- [ ] **Step 3: Commit**

```bash
git add docs/concepts/observability-and-traceability.md
git commit -m "docs(concepts): add observability-and-traceability concept doc (Layer 4)"
```

---

### Task 9: Write autonomous-resilience.md (Layer 4 — new)

**Files:**
- Create: `docs/concepts/autonomous-resilience.md`
- Source material: `docs/architecture/self-healing.md`, `docs/agents/agents-operations.md`, CLAUDE.md Phase 108 SOP (HEAL-01/03/04), `src/observability/circuit_breaker.py`

- [ ] **Step 1: Read source material**

Read `docs/architecture/self-healing.md` fully. Read CLAUDE.md Phase 108 SOP section and `CircuitBreaker` manual-tracking rule.

- [ ] **Step 2: Write the doc**

```markdown
# Autonomous Resilience
> The system detects failures, routes around them, and recovers without human intervention.

## The Problem It Solves

A system that requires manual intervention to recover from failures is not a 24/7 trading system — it is a system that trades during business hours. Overnight crashes, stalled consumers, DB timeouts, and LLM provider failures all require the same human response: someone wakes up, diagnoses, and restarts. At scale, this is operationally untenable. The system must be its own first responder.

## The Principle

Resilience is layered: detect failure early (watchdogs), isolate it (circuit breakers), route around it (DLQ), and recover automatically (service auditor). Each layer handles a different failure mode:

1. **Watchdogs** — detect agent death or stall (no heartbeat within N seconds)
2. **Circuit breakers** — detect cascading failures and open the circuit before they compound
3. **Dead-letter queues (DLQ)** — route unparseable or consistently-failing messages out of the hot path
4. **Service auditor** — monitors all services, restarts failed ones, enforces the DAG restart order

## How IndicAgent Applies It

**Watchdogs (systemd + OTel):** Every `BaseAgent` emits `WATCHDOG=1` to systemd via sd_notify on each processed message. If the watchdog interval elapses without a ping, systemd restarts the service. `watchdog_notify_suppressed_total` distinguishes a stalled (alive but idle) agent from a crashed one.

**Circuit breakers** (`src/observability/circuit_breaker.py`): States are `CLOSED` (normal) → `OPEN` (failing) → `HALF_OPEN` (testing recovery). For manual tracking outside `call()`: use `allow_request()` (time-based OPEN→HALF_OPEN check) and `record_success()` (closes from HALF_OPEN). Do not call `record_failure()` and expect automatic recovery without one of these.

**DLQ:** `BaseWriterAgent._parse_payload` returns `None` (route whole payload to DLQ) or `[]` (valid parse, no signals — do not DLQ). Every DLQ event increments `agent_dlq_total`. DLQ messages are quarantined for investigation, not silently dropped.

**Service Auditor (`ServiceAuditorAgent`):** Monitors all services via systemd unit state. `_DAG_ORDER` in `services/service_auditor_agent.py` defines restart sequence — services earlier in the DAG restart before services that depend on them. `_LAG_THRESHOLDS` defines consumer lag thresholds per service.

**Parity Auditor:** `ParityAuditorAgent` certifies feature writes after 60 consecutive clean parity cycles. If parity fails, the auditor flags the write path for investigation before corruption compounds.

## Invariants

- Every daemon service must emit `WATCHDOG=1` on each processed message — inherited from `BaseAgent`.
- `_parse_payload` returning `None` routes the whole payload to DLQ. Return `[]` for valid-but-empty to prevent double-DLQ.
- The `_DAG_ORDER` in `service_auditor_agent.py` is the single source of truth for restart order — never maintain a parallel list.
- Circuit breaker `OPEN→HALF_OPEN` recovery only fires inside `call()` — manual tracking requires explicit `allow_request()` calls.

## Recipe

When designing autonomous resilience for a new system:

1. **Define failure modes first** — agent crash, agent stall, message parse failure, DB timeout, external API failure. Each needs a different mechanism.
2. **Watchdogs on every daemon** — systemd `WatchdogSec=` + sd_notify is the simplest reliable approach.
3. **DLQ before alerting** — bad messages should be quarantined, not cause service crashes. Alerts fire on DLQ growth, not on parse errors.
4. **Circuit breakers on external dependencies** — DB, LLM APIs, external data providers. Internal agent failures use watchdogs instead.
5. **Service auditor is a meta-service** — one agent that knows the full DAG restart order and acts on it. Simpler and more reliable than distributed health checks.
6. **Distinguish dead from stalled** — a crashed agent and a stalled-but-alive agent need different responses. Separate metrics for each.

## See Also

- Implementation: `docs/agents/agents-operations.md` — service auditor DAG, watchdog config
- Implementation: `docs/architecture/self-healing.md` — detailed self-healing patterns
- Code: `src/observability/circuit_breaker.py` — CircuitBreaker with manual tracking API
- Phase 108 SOP in `CLAUDE.md` — mandatory OTel signals, D-04 contract
```

- [ ] **Step 3: Commit**

```bash
git add docs/concepts/autonomous-resilience.md
git commit -m "docs(concepts): add autonomous-resilience concept doc (Layer 4)"
```

---

### Task 10: Rewrite dag-execution.md (Layer 2)

**Files:**
- Modify: `docs/concepts/dag-execution.md` (rewrite in place)
- Source: current file + `docs/intelligence/intelligence-plugins.md` DAG Execution Model section

- [ ] **Step 1: Read source material**

Read current `docs/concepts/dag-execution.md` (169 lines). Note what's conceptual (Kahn's algorithm rationale, why DAGs for market intelligence, cycle prevention) vs. implementation detail (code snippets of the DAG data structure — already in intelligence-plugins.md).

- [ ] **Step 2: Rewrite the file**

Strip: the service-level DAG table (belongs in `docs/agents/agents-foundation.md`), any Python code showing the DAG data structure (already in `intelligence-plugins.md`). Keep: the graph theory rationale, the "why DAGs" section.

Replace with the recipe-card template. Sections to write:
- **The Problem It Solves:** Manual plugin sequencing requires the developer to know all transitive dependencies. Adding a new plugin that sits between two existing ones requires editing sequencing code. This is fragile and doesn't scale to 132 plugins.
- **The Principle:** Declare inputs and outputs for each node. A topological sort (Kahn's algorithm) derives execution order automatically. Parallelism emerges from the graph — nodes with no unsatisfied dependencies run concurrently without any explicit scheduling.
- **How IndicAgent Applies It:** Two-level DAG — plugin DAG (within a bar, I1-I7) and service DAG (across services, L1-L10). Plugin DAG computed at startup from `inputs`/`outputs` declarations. Cycle detection runs at startup and fails fast. Parallel waves execute plugins with no inter-dependencies simultaneously.
- **Invariants:** No plugin may declare a circular dependency. Execution order must be deterministic given the same dependency graph. The DAG is computed once at startup — not per-bar. A plugin's `inputs` list is its contract; it may not read from tier outputs not listed there.
- **Recipe:** When designing a DAG-executed system: (1) Define node interface before implementation — what does each node consume and produce? (2) Choose cycle detection strategy — startup-fail-fast is preferable to runtime detection. (3) Decide granularity — too-fine nodes create overhead; too-coarse nodes prevent parallelism. (4) Consider optional vs. required inputs — nodes that can run with partial inputs need explicit fallback behavior.

- [ ] **Step 3: Verify no implementation code remains**

```bash
grep -n "def \|class \|import " docs/concepts/dag-execution.md
```

Expected: no code — only markdown prose and diagrams.

- [ ] **Step 4: Commit**

```bash
git add docs/concepts/dag-execution.md
git commit -m "docs(concepts): rewrite dag-execution to concept level (Layer 2)"
```

---

### Task 11: Rewrite incremental-computation.md (Layer 2)

**Files:**
- Modify: `docs/concepts/incremental-computation.md` (rewrite in place)

- [ ] **Step 1: Read the current file** (153 lines)

Note what's conceptual (the problem with full recomputation, O(1) vs O(N) tradeoff, warmup as the exception) vs. implementation (Python state classes, specific `compute_next()` signatures — already in intelligence-plugins.md).

- [ ] **Step 2: Rewrite**

Strip: Python code showing specific state classes (already in `intelligence-plugins.md`). Keep: deque pattern description as prose, warmup rationale, fallback behavior rationale.

Replace with recipe-card template. Sections:
- **The Problem It Solves:** 132 plugins × full recomputation per bar = O(N×bars) work per tick. At 12 bars/min across 6 instruments, this is untenable. A naive implementation recomputes RSI from the last 14 bars, ATR from the last 14 bars, etc. — redundant work that scales with history length.
- **The Principle:** Each plugin maintains bounded internal state (e.g., a fixed-length deque). On each new bar, the plugin calls `compute_next(bar)` which updates state O(1) — add the new value, drop the oldest. The full history is never reprocessed after warmup.
- **How IndicAgent Applies It:** `supports_incremental` flag per plugin. Plugins without it (`supports_incremental = False`) receive a rolling window of bars on each call. Plugins with it receive only the new bar and maintain state internally. Warmup period (~50 bars for GARCH/Kalman/HMM to converge) is the only exception. State is checkpointed to disk so warmup does not replay on restart.
- **Invariants:** `compute_next()` may only read from internal state and the current bar — never from a full history lookup. Warmup is the only legitimate O(N) operation. State must be serializable to JSON for checkpointing.
- **Recipe:** (1) Identify which computations are truly incremental vs. window-based. (2) For incremental: define the minimal state representation. (3) Set warmup length to the convergence window of the slowest state variable. (4) Checkpoint state to local disk — not to a database — to survive restarts without warmup replay.

- [ ] **Step 3: Commit**

```bash
git add docs/concepts/incremental-computation.md
git commit -m "docs(concepts): rewrite incremental-computation to concept level (Layer 2)"
```

---

### Task 12: Write progressive-intelligence-extraction.md, delete intelligence-tiers.md (Layer 2)

**Files:**
- Create: `docs/concepts/progressive-intelligence-extraction.md`
- Delete: `docs/concepts/intelligence-tiers.md`
- Source: current `intelligence-tiers.md` (conceptual sections only) + `docs/intelligence/intelligence-foundation.md`

- [ ] **Step 1: Read source**

Read `docs/concepts/intelligence-tiers.md`. Note: the I1-I8 overview is conceptual; the stream key catalog, code organization, and development status tables are implementation detail already in intelligence-foundation.md.

- [ ] **Step 2: Write progressive-intelligence-extraction.md**

Structure:
- **Problem:** raw market data (price/volume) contains no signal — it must be transformed through progressive layers before patterns emerge
- **Principle:** each tier consumes the outputs of previous tiers and produces a richer abstraction. Mathematical foundation → composite events → structure → regime → patterns → confluence → signals → narrative. No tier can skip its predecessors.
- **How IndicAgent applies it:** I1-I8 with clear tier responsibilities, the `IntelligenceEvent` as the carrier, why sequential ordering is necessary
- **Invariants:** I7 must consume I1-I6 outputs; no tier may bypass a prerequisite tier; every tier output is typed in `IntelligenceEvent`
- **Recipe:** how to design a progressive extraction pipeline for any domain (not just market data)

- [ ] **Step 3: Delete old file and commit**

```bash
git rm docs/concepts/intelligence-tiers.md
git add docs/concepts/progressive-intelligence-extraction.md
git commit -m "docs(concepts): add progressive-intelligence-extraction, remove intelligence-tiers (Layer 2)"
```

---

### Task 13: Write plugin-composability.md, delete plugin-architecture.md (Layer 2)

**Files:**
- Create: `docs/concepts/plugin-composability.md`
- Delete: `docs/concepts/plugin-architecture.md`
- Source: current `plugin-architecture.md` (conceptual sections only — the 132-plugin registry and DAG implementation detail already in intelligence-plugins.md)

- [ ] **Step 1: Read source**

Read `docs/concepts/plugin-architecture.md`. Executive Summary and Framework Objectives are conceptual. Plugin Architecture section has the contract (conceptual) plus the full 132-plugin registry (already in intelligence-plugins.md — strip it).

- [ ] **Step 2: Write plugin-composability.md**

Structure:
- **Problem:** hardcoded intelligence logic cannot be extended without modifying core pipeline code
- **Principle:** the shell is empty — intelligence is composed entirely of plugins. Each plugin declares its inputs, outputs, and dependencies. The system derives execution order, detects cycles, and computes in parallel where possible.
- **How IndicAgent applies it:** plugin protocol (`compute()` / `compute_next()`), tier registration in `register_plugins.py`, the shell-plugin separation
- **Invariants:** no intelligence logic in the pipeline itself; all plugins are independently testable; plugin registration is the only coupling point
- **Recipe:** how to design a plugin system (interface definition, registration pattern, dependency declaration, versioning)

- [ ] **Step 3: Delete old file and commit**

```bash
git rm docs/concepts/plugin-architecture.md
git add docs/concepts/plugin-composability.md
git commit -m "docs(concepts): add plugin-composability, remove plugin-architecture (Layer 2)"
```

---

### Task 14: Write regime-awareness.md, delete regime-classification.md (Layer 2)

**Files:**
- Create: `docs/concepts/regime-awareness.md`
- Delete: `docs/concepts/regime-classification.md`

- [ ] **Step 1: Read source** (`docs/concepts/regime-classification.md`, 152 lines)

Note: per-plugin implementation detail (VolatilityRegime, KalmanTrend specific implementations) is implementation detail. The concept is: market behavior is non-stationary — rules that work in trending markets fail in ranging markets.

- [ ] **Step 2: Write regime-awareness.md**

Structure:
- **Problem:** a signal that works globally is weaker than one that works in a specific regime; non-stationarity makes global rules unreliable
- **Principle:** classify regime continuously; condition all signals on current regime; never apply a rule learned in one regime to another
- **How IndicAgent applies it:** I4 regime classifiers (HMM, BOCPD, Kalman, GARCH, volatility), regime gate in I7, per-regime weight tables in `signal_metrics`
- **Invariants:** every I7 signal must declare which regimes it is valid in; performance weights are regime-conditioned; a signal cannot override a regime suppression gate
- **Recipe:** regime segmentation design (how many regimes, how to detect transitions, how to handle regime uncertainty)

- [ ] **Step 3: Delete old file and commit**

```bash
git rm docs/concepts/regime-classification.md
git add docs/concepts/regime-awareness.md
git commit -m "docs(concepts): add regime-awareness, remove regime-classification (Layer 2)"
```

---

### Task 15: Write evidence-graded-signals.md, delete cis-scoring.md (Layer 3)

**Files:**
- Create: `docs/concepts/evidence-graded-signals.md`
- Delete: `docs/concepts/cis-scoring.md`
- Note: implementation detail already rescued to `intelligence-foundation.md` in Task 1

- [ ] **Step 1: Read source** (`docs/concepts/cis-scoring.md`, 241 lines)

The problem statement and architecture overview are conceptual. The formula detail and calibration chain were rescued in Task 1 — do not repeat them here.

- [ ] **Step 2: Write evidence-graded-signals.md**

Structure:
- **Problem:** a single indicator firing is noise — any individual signal has a non-trivial false positive rate; the naive approach (if RSI < 30, buy) cannot survive real markets
- **Principle:** require agreement from multiple independent evidence sources before acting. Independence is critical — correlated sources provide no additional information.
- **How IndicAgent applies it:** 6 independent CIS buckets (trend, momentum, structure, pattern, institutional, regime), gate requires `|score| > 0.35` AND 3+ buckets agree; adaptive weights that learn from outcomes
- **Invariants:** no signal may fire from a single indicator; CIS buckets must be statistically independent; `active` always derived from `all_ranked` never from raw `signals`
- **Recipe:** how to design a multi-source confirmation system (bucket independence test, gate threshold calibration, adaptive weight learning)

- [ ] **Step 3: Delete old file and commit**

```bash
git rm docs/concepts/cis-scoring.md
git add docs/concepts/evidence-graded-signals.md
git commit -m "docs(concepts): add evidence-graded-signals, remove cis-scoring (Layer 3)"
```

---

### Task 16: Write adaptive-intelligence.md, delete evolvable-ai.md (Layer 3)

**Files:**
- Create: `docs/concepts/adaptive-intelligence.md`
- Delete: `docs/concepts/evolvable-ai.md`
- Note: eAI substrate inventory rescued to `intelligence-ai.md` in Task 3

- [ ] **Step 1: Read source material**

Read `docs/concepts/evolvable-ai.md`. Read `docs/intelligence/intelligence-ai.md` Shadow Governance and eAI Substrate sections (added in Task 3). Read `docs/ideas/ai-03-evolvable-ai-agents.md` — the research vision for broader context.

- [ ] **Step 2: Write adaptive-intelligence.md**

Structure:
- **Problem:** a system with fixed weights and hardcoded thresholds degrades as market regimes shift — it was tuned for the past, not the present
- **Principle:** every component that influences a decision must earn that influence through statistical proof, and must lose it when evidence degrades. This applies at three levels: (1) individual signals — shadow → statistical gate → production; (2) CIS weights — bootstrap → learned from outcomes; (3) agents — shadow mode → graduation → live → demotion
- **How IndicAgent applies it:** `shadow_registry` auto-enrollment, `bootstrap_ci_lower(pnl_r) > 0.0` promotion gate, `EV[R] < -0.05` demotion, `signal_ledger` as the continuous fitness dataset, eAI genome mutations (v2.8 roadmap)
- **Invariants:** nothing goes to production without `n >= 100` resolved signals and positive bootstrap CI; demotion is automatic — it cannot be overridden by configuration; the fitness dataset (`signal_ledger`) is never dropped
- **Recipe:** designing an adaptive system (fitness metric selection, gate threshold calibration, demotion sensitivity, data accumulation requirements before any adaptation fires)

- [ ] **Step 3: Delete old file and commit**

```bash
git rm docs/concepts/evolvable-ai.md
git add docs/concepts/adaptive-intelligence.md
git commit -m "docs(concepts): add adaptive-intelligence, remove evolvable-ai (Layer 3)"
```

---

### Task 17: Rewrite swarm-intelligence.md (Layer 3)

**Files:**
- Modify: `docs/concepts/swarm-intelligence.md` (rewrite in place)
- Note: BaseAIAgent/BaseGroupCoordinator API detail is already in `intelligence-ai.md` — do not repeat

- [ ] **Step 1: Read source** (`docs/concepts/swarm-intelligence.md`, 142 lines)

Agent Framework section (BaseAIAgent, BaseGroupCoordinator, LineageRecorder) is implementation detail — strip. The Alpha Swarm section, MoA composition, and shadow governance rationale are conceptual.

- [ ] **Step 2: Rewrite**

Structure:
- **Problem:** a single LLM call cannot reliably synthesize multi-dimensional market intelligence — it lacks specialization, has no adversarial check, and produces uncalibrated confidence
- **Principle:** Mixture of Agents (MoA) — specialized agents each assess one dimension, their outputs are composed into a calibrated multiplier. No single agent makes a decision.
- **How IndicAgent applies it:** 5 alpha swarm agents (correlation, regime_coherence, counterfactual, skeptic, ml_scorer), shadow governance gates each agent, MoA composite multiplier applied after CIS calibration
- **Invariants:** swarm agents are discount-only until sufficient outcome data proves positive edge; the skeptic agent must always be live (adversarial coevolution); `swarm_multiplier` is applied after all other calibration
- **Recipe:** designing a swarm (specialization criteria, adversarial agent inclusion, composition function, calibration approach)

- [ ] **Step 3: Commit**

```bash
git add docs/concepts/swarm-intelligence.md
git commit -m "docs(concepts): rewrite swarm-intelligence to concept level (Layer 3)"
```

---

### Task 18: Rewrite docs/concepts/README.md

**Files:**
- Modify: `docs/concepts/README.md`

- [ ] **Step 1: Rewrite as library index**

Replace the entire file with:

```markdown
# Concepts Library

Reusable intellectual artifacts — the architectural DNA of IndicAgent. Each doc captures the *why* behind a design decision at a level of abstraction that transfers to new systems.

**How to read this library:**
- New engineer onboarding: read Layer 1 first, then Layer 2
- Designing a new system: use the Recipe section of any relevant doc
- Understanding a domain doc: the concept doc is its intellectual foundation

---

## Layer 1 — System Architecture

Foundations that everything else rests on.

| Doc | Core idea |
|-----|-----------|
| [Hot-Path Isolation](hot-path-isolation.md) | Real-time compute never touches storage — decouples latency from I/O |
| [Event-Driven Fabric](event-driven-fabric.md) | Agents decouple through topics, never direct calls |
| [Incremental Computation](incremental-computation.md) | O(1) per-bar updates via stateful plugins |
| [Temporal Data Architecture](temporal-data-architecture.md) | Time-series native; every event timestamped, nothing dropped |

## Layer 2 — Intelligence Design

How you build a smart system on that foundation.

| Doc | Core idea |
|-----|-----------|
| [Progressive Intelligence Extraction](progressive-intelligence-extraction.md) | Raw data → actionable intelligence through 8 tiers (I1-I8) |
| [Plugin Composability](plugin-composability.md) | Intelligence as independently-testable units with declared dependencies |
| [DAG Execution](dag-execution.md) | Topological ordering derives parallelism from the dependency graph |
| [Regime Awareness](regime-awareness.md) | Signals conditioned on regime, not absolute thresholds |

## Layer 3 — Trust and Quality

How you know the system is right.

| Doc | Core idea |
|-----|-----------|
| [Evidence-Graded Signals](evidence-graded-signals.md) | Multi-dimensional confirmation before any signal fires |
| [Adaptive Intelligence](adaptive-intelligence.md) | The system earns the right to act through statistical proof |
| [Swarm Intelligence](swarm-intelligence.md) | Mixture of expert agents — no single model makes a decision |

## Layer 4 — Operational Excellence

How you run it reliably at scale.

| Doc | Core idea |
|-----|-----------|
| [Observability and Traceability](observability-and-traceability.md) | Every decision auditable end-to-end |
| [Autonomous Resilience](autonomous-resilience.md) | The system detects and corrects its own failures |
```

- [ ] **Step 2: Commit**

```bash
git add docs/concepts/README.md
git commit -m "docs(concepts): rewrite README as four-layer library index"
```

---

### Task 19: Final verification

- [ ] **Step 1: Verify no old filenames remain**

```bash
ls docs/concepts/
```

Expected: only the 13 concept docs + README.md. No `intelligence-tiers.md`, `plugin-architecture.md`, `regime-classification.md`, `cis-scoring.md`, `evolvable-ai.md`, `tier-naming-system.md`.

- [ ] **Step 2: Verify all 13 concept docs have the required sections**

```bash
for f in docs/concepts/*.md; do
  [ "$f" = "docs/concepts/README.md" ] && continue
  echo "=== $(basename $f) ==="
  grep "^## " "$f"
done
```

Expected: every doc has The Problem It Solves, The Principle, How IndicAgent Applies It, Invariants, Recipe, See Also.

- [ ] **Step 3: Verify Part A rescues are present**

```bash
grep -l "perf_multiplier\|Isotonic\|eAI Substrate\|Plugin Failure Isolation\|Tier Mapping" \
  docs/intelligence/intelligence-foundation.md \
  docs/intelligence/intelligence-plugins.md \
  docs/intelligence/intelligence-ai.md \
  docs/foundation/naming-conventions.md
```

Expected: all four files listed.

- [ ] **Step 4: Verify README layer structure**

```bash
grep "^## Layer" docs/concepts/README.md
```

Expected: Layer 1, Layer 2, Layer 3, Layer 4.

- [ ] **Step 5: Final commit**

```bash
git add docs/concepts/
git commit -m "docs(concepts): concepts library rebuild complete — 13 recipe-card docs in 4 layers"
```
