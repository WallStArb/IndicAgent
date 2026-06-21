# Naming System

**Status:** current
**Last Updated:** 2026-05-30
**Design spec:** `docs/plans/2026-05-30-renaissance-naming-system-design.md`

---

## Purpose

This document is the complete vocabulary system for the IndicAgent codebase. It is a portable foundation: when a new project is started, this document and `src/core/` travel with it unchanged.

The naming system is not a style guide. It is a mathematical specification of what kinds of objects exist in this system, how they are named, and how that naming is mechanically derived and enforced. Every name is a claim about what an object IS. Claims must be true.

---

## 1. Philosophy and Governing Tests

### The Core Principle

**The vocabulary IS the model. The model IS the vocabulary.**

When a senior quant reads a list of class names, they are reading the mathematical architecture. When names describe mechanism instead of role, the code has drifted from the model. Naming cleanup is not cosmetic — it restores the identity between model and code.

### The Invariant

> **A name is correct if and only if a domain expert who has never seen the implementation can correctly predict the object's mathematical role, its inputs, and its output contract from the name alone — without reading any code.**

This is the single criterion. The three governing tests are tools for applying it. When they conflict or leave a case unresolved, return to the invariant.

### Three Governing Tests

**The Whiteboard Test**
Write the name on a whiteboard in a mathematics seminar. Would a quant immediately understand what the object IS? `SkepticEvaluator` passes. `SkepticComputeAgent` fails. `context` passes. `ctx` fails.

**The Survival Test**
If you replaced the implementation tomorrow — swap the LLM for a neural net, swap Kafka for a message queue — would the name still be correct? `BarAggregator` survives. `BarAggregator` does not — `Compute` describes mechanism.

**The Portability Test** *(Ring 0 only)*
Could this name be extracted into a shared library and used unchanged in a credit risk system or options pricing engine? `BaseDaemon` passes. `AIContext` fails — it names a trading intelligence construct.

### What Fails All Three Tests

- **Mechanism words:** `Compute`, `Process`, `Handle`, `Manage`, `Execute`
- **Unearned role words:** `Agent` on a component that is called, not autonomous
- **`Base*` on domain objects:** `BaseGroupCoordinator` implies a non-base exists. `Evaluator` (abstract) is simply the type.
- **Code abbreviations:** `ctx`, `cfg`, `msg`, `sig`
- **Three unrelated semantic units:** three related words in a compound (`RegimeCoherenceAnalyzer`) are fine — the smell is *unrelated* concepts. The CI advisory check flags four or more PascalCase segments.

---

## 2. The Four Ring Architecture

Every file, class, and module belongs to exactly one ring.

```
Ring 0  src/core/, src/observability/, src/persistence/, src/monitoring/
        Portable infrastructure. No domain vocabulary.
        Travels to any new project verbatim.

Ring 1  src/intelligence/, src/config/, src/providers/, src/self_healing/, src/validation/
        Domain layer. IndicAgent-specific vocabulary is correct here.

Ring 2  services/
        Runtime processes (daemons). Pure role nouns.
        Location and BaseDaemon inheritance encode "this is a daemon."

Ring 3  src/api/, dashboard/, production/
        External interfaces. Follows surface-specific conventions.
```

**Outer rings depend on inner rings; inner rings must never depend on outer rings:**

```
Ring 0  →  no imports from Ring 1, 2, or 3
Ring 1  →  imports from Ring 0 only
Ring 2  →  imports from Ring 0 and Ring 1
Ring 3  →  imports from any ring
```

**Note on Ring 1 sub-modules:** Files within Ring 1 directories that contain purely generic patterns with no IndicAgent vocabulary may be factored into Ring 0 when they genuinely pass the portability test.

### Rings vs Intelligence Tiers

Rings and the I1–I8 tiers are orthogonal. Rings describe portability. Tiers describe position in the mathematical pipeline.

**File location encodes tier membership; class names do not repeat tier codes.**

`src/intelligence/features/i1_indicators/rsi.py` → `RSIPlugin`, not `I1RSIPlugin`. Tier is structural metadata encoded in the directory. Exception: when tier membership is the concept itself (an object that manages tier boundaries), the tier code may appear in the name.

### Intelligence Tier Code Glossary

When tier codes appear in documentation or code, they map to these descriptive names:

| Code | Name | Purpose |
|------|------|---------|
| I1 | indicators | Technical indicators: RSI, MACD, ATR, ADX, etc. |
| I2 | composite_events | Composite event detectors: momentum acceleration, multi-timeframe signals |
| I3 | structure | Market structure: swing highs/lows, support/resistance levels |
| I4 | context | Context features: GARCH volatility, Kalman filters, VWAP, volume profile, regime |
| I5 | patterns | Chart patterns: head & shoulders, triangles, wedges |
| SMC | smart_money | Smart money concepts: BOS/CHoCH, order blocks, fair value gaps |
| I6 | confluence | Cross-timeframe confluence scoring for signal confidence |
| I7 | signals | Trading signal generation with entry/exit framing |
| I8 | AI_narrative | LLM-driven narrative generation and meta-analysis |

**Usage:** In docs, use first-mention expansion: "indicators (I1)" or "I1 indicators". After first mention, the code alone is sufficient.

### `Base*` Prefix Rule

- Ring 0 infrastructure bases keep `Base*`: `BaseDaemon`, `BaseWriter`, `BaseProvider`. They are shared implementation foundations.
- Mathematical abstract types drop `Base*`: the abstract class IS the type. `Evaluator`, not `BaseEvaluator`.

### `Agent` Retirement Rule

`Agent` is retired as a *mechanism word* — when it describes how something works rather than what it IS. `ComputeAgent`, `DataAgent`, `ProcessAgent`, `HelperAgent` all fail because they describe mechanism, not role.

`Agent` is **correct** when the object genuinely IS an autonomous AI agent: an LLM-driven worker that acts on its own judgment to produce a scored output. `AgentRegistry` (the registry of AI agents), `AgentSpec` (the YAML spec for an AI agent), `self._agents` (the list of AI agents in a group coordinator), and `agent_id` are all correct because the things they name are or directly describe AI agents.

The test: can you replace "agent" with a more specific mathematical role name (`Evaluator`, `Synthesizer`, `Analyzer`) without losing meaning? If yes — use the specific name. If no — the object IS an agent and `agent` is appropriate.

**`agent_id` operational note:** The metric label `agent_id` and structlog field `agent_id` are preserved for compatibility with existing Grafana dashboards and OTel pipelines.

---

## 3. The Complete Taxonomy

Two vocabularies. Every object belongs to exactly one category in exactly one vocabulary.

### Vocabulary A — Mathematical Objects

Called, not run. No Kafka connection, no systemd unit, no daemon loop. Live in Ring 0 or Ring 1. Abstract types are the type itself — no `Base*` prefix.

| Category | Mathematical role | Output contract | Example |
|----------|-----------------|-----------------|---------|
| `Evaluator` | Evaluates from a specific perspective, produces a scored judgment | Score ∈ [0,2] or qualitative judgment | `SkepticEvaluator`, `RegimeCoherenceEvaluator` |
| `Analyzer` | Performs structured analytical computation | Structured typed result | `CorrelationAnalyzer`, `CrossAssetAnalyzer` |
| `Synthesizer` | Combines multiple signals into qualitative synthesis | Narrative or annotation | `NarrativeSynthesizer` |
| `Detector` | Detects presence or absence of a pattern or condition | Boolean or classified signal | `BreakoutDetector`, `RegimeDetector` |
| `Classifier` | Assigns inputs to mutually exclusive categories | Enumerated category | `SessionClassifier`, `VolatilityClassifier` |
| `Aggregator` | Combines multiple numerical inputs into a unified measure | Scalar or vector | `ConfluenceAggregator`, `CISAggregator` |

### Vocabulary B — Runtime Processes

Run autonomously. Have a daemon loop, systemd unit, Kafka subscription or timer trigger. Live in Ring 2. `BaseDaemon` inheritance and `services/` location encode daemon nature; the name encodes role only.

| Category | Role | I/O | Example |
|----------|------|-----|---------|
| `Provider` | Ingests from external source → stream | External → Kafka | `IBKRProvider`, `BarReplayProvider` |
| `Merger` | Combines multiple streams into one | Kafka × N → Kafka | `ProviderMerger` |
| `Aggregator` | Aggregates streaming data into higher-level events | Kafka → Kafka | `BarAggregator` |
| `Analyzer` | Computes analytical metrics as a daemon | Kafka / Timer → Kafka | `MacroAnalyzer`, `SignalMetricsAnalyzer` |
| `Writer` | Persists from stream to storage | Kafka → DB | `FeatureWriter`, `SignalWriter` |
| `Tracker` | Manages business object state over time | Kafka → State + Kafka | `SignalTracker` |
| `Auditor` | Validates data integrity, self-heals | DB → Corrections | `SignalAuditor`, `BarAuditor` |
| `Monitor` | Watches conditions, dispatches alerts | Kafka / DB → Alerts | `AlertMonitor` |
| `Orchestrator` | Coordinates multi-step batch workflows | Timer → Jobs | `MLOrchestrator` |
| `Trainer` | Executes model training | Data → Model artifact | `MLTrainer`, `HMMTrainer` |
| `Publisher` | Reads from DB/outbox and emits to stream | DB → Kafka | `OutboxPublisher` |

### Disambiguating Shared Suffixes

`Aggregator` and `Analyzer` appear in both vocabularies. **Ring determines vocabulary.** A class in Ring 0/1 is a mathematical object — called, stateless. A class in Ring 2 is a daemon — autonomous, owns a lifecycle. `BaseDaemon` inheritance is the mechanical boundary.

### Plain Role Nouns (Ring 2 exemption)

Some Ring 2 daemons are the concept itself — no category suffix adds precision. Listed explicitly and exempt from the taxonomy suffix requirement:

| Name | Reason |
|------|--------|
| `IntelligencePipeline` | IS the pipeline — any suffix would misrepresent the unified I1-I7 compute process |
| `AlphaSwarm` | IS the swarm — the swarm is the architectural concept |
| `NarrativeSwarm` | Same pattern — group coordinator IS the swarm |
| `AlphaEngine` | IS the system — the IC measurement + ensemble alpha generation system (System 1, v3.0) |
| `AnalogEngine` | IS the system — the pgvector k-NN historical retrieval substrate (System 2, v3.0) |

New plain role nouns require explicit addition to this table. The anti-creep rule applies.

### The Composability Principle

A composition earns its own name when it has a **stable mathematical identity that outlives its current members**: if members can be replaced without changing what the composition IS, the name is correct.

Rules:
1. **Name by role, never by members.** `AlphaSwarm` not `SkepticCorrelationCounterfactualGroup`.
2. **A composition that IS its pipeline does not earn a separate name.**
3. **Coordinators name separately from members.** `NarrativeSwarm` (Ring 2 daemon) is distinct from `NarrativeSynthesizer` (Ring 1 mathematical object).

### Taxonomy Governance

**Anti-creep rule:** A new category requires at least two distinct existing objects that share the same mathematical role and fit no current category. One object maps to the nearest existing category.

**Governance:** Taxonomy additions require the proposer to demonstrate the three governing tests pass and the anti-creep rule is satisfied, reviewed by at least one engineer with domain knowledge. The spec is the decision framework — not a vote.

### Machine-Readable Taxonomy Block

```yaml
taxonomy:
  mathematical_objects:
    suffixes: [Evaluator, Analyzer, Synthesizer, Detector, Classifier, Aggregator]
    rings: [0, 1]
    no_base_prefix: true
  runtime_processes:
    suffixes: [Provider, Merger, Aggregator, Analyzer, Writer, Tracker, Auditor, Monitor, Orchestrator, Trainer, Publisher]
    plain_role_nouns: [IntelligencePipeline, AlphaSwarm, NarrativeSwarm, AlphaEngine, AnalogEngine, ICEngine, OutcomeLabeler, RegimeLabeler]
    rings: [2]
    inherits: BaseDaemon
  infrastructure_bases:
    classes: [BaseDaemon, BaseWriter, BaseProvider, BaseAIWorker, BaseGroupCoordinator]
    rings: [0, 1]
    base_prefix: permitted
    note: >
      BaseGroupCoordinator lives in Ring 1 (src/intelligence/ai/group_coordinator.py) because
      it carries domain-specific shadow_registry and LLM chain wiring. All others are Ring 0.
  behavioral_mixins:
    suffix: Mixin
    rings: [0, 1]
    rule: provides methods only — no persistent state of its own
  enumerations:
    suffix: none — PascalCase singular noun
    rings: [0, 1, 2]
    members: UPPER_SNAKE_CASE
  configuration_objects:
    suffix: Config
    rings: [0, 1]
    rule: component-scoped only — global singleton is Settings
  retired:
    suffixes: [ComputeAgent, MultiplierAgent, GroupService, Agent]
    words: [Compute, Handler, Helper, Util, Utils, Manager, Processor, Agent]
    note: >
      Agent is fully retired — including from infrastructure base class names.
      Exception: agent_id metric label and structlog field preserved for operational compatibility.
```

---

## 4. The Five Surfaces

One concept name mechanically derives all surface names. No judgment calls, no lookup tables.

### Surface 1 — Python Classes

| Object type | Pattern | Example |
|------------|---------|---------|
| Ring 2 daemon | `PascalCase(concept)` + category suffix | `SignalTracker`, `BarAggregator` |
| Ring 2 daemon (plain role noun) | `PascalCase(concept)` — no suffix | `IntelligencePipeline`, `AlphaSwarm` |
| Ring 1 mathematical object | `PascalCase(concept)` + category suffix | `SkepticEvaluator` |
| Ring 0/1 abstract math type | Category suffix alone | `Evaluator`, `Synthesizer` |
| Ring 0 infrastructure base | `Base` + `PascalCase(role)` | `BaseDaemon`, `BaseWriter` |
| Behavioral mixin | `PascalCase(capability)` + `Mixin` | `IncrementalMixin`, `ConfigConsumerMixin` |
| Enumeration | `PascalCase` singular noun | `MarketRegime`, `SignalStatus`, `AssetClass` |
| Component config | `PascalCase(concept)` + `Config` | `EvaluatorConfig`, `PipelineConfig` |
| Plugin | `PascalCase(concept)` + `Plugin` | `ADXPlugin`, `VWAPPlugin` |
| Protocol | `PascalCase(concept)` + `Protocol` | `AIWorkerProtocol` |
| Result / output model | `PascalCase(concept)` + `Result` | `SkepticResult`, `SignalMetricsResult` |
| Context carrier | `PascalCase(concept)` + `Context` | `SignalContext`, `WorkerContext`, `SMCContext` |
| Repository | `PascalCase(concept)` + `Repository` | `SignalLedgerRepository` |
| Error | `PascalCase(concept)` + `Error` | `ConfigValidationError`, `CircuitOpenError` |

**Mixins:** Provide behavioral capability through methods. No persistent state of their own — if state is needed, the capability belongs in a base class, not a mixin. Same ring as the domain they serve.

**Enumerations:** Members are `UPPER_SNAKE_CASE`. Type name is singular — `MarketRegime` not `MarketRegimes`. Same ring as the domain they describe.

**Component config:** A component gets its own `*Config` only when configuration is meaningfully distinct from global `Settings` and must be passed explicitly (tests, parameterized instantiation, reuse across contexts). Components that read directly from `Settings` at construction do not get a `*Config`.

### Surface 2 — File Names

File location encodes both ring and intelligence tier. File name encodes the concept only. The `_agent` suffix is retired.

| Object type | Pattern | Example |
|------------|---------|---------|
| Ring 2 daemon | `services/<concept>.py` | `services/signal_tracker.py` |
| Ring 1 AI evaluator | `src/intelligence/ai/<group>/<concept>.py` | `src/intelligence/ai/alpha/skeptic.py` |
| Ring 1 domain | `src/intelligence/<module>/<concept>.py` | `src/intelligence/context.py` |
| Ring 0 infrastructure | `src/core/<module>/<concept>.py` | `src/core/ai/evaluator.py` |
| Plugin (I1–I5) | `src/intelligence/features/i<N>_<tier_name>/<concept>.py` | `src/intelligence/features/i1_indicators/rsi.py` |

The tier subdirectory (`i1_indicators`, `i3_structure`, etc.) encodes tier membership. File names do not repeat the tier: `rsi.py` not `i1_rsi.py`.

### Surface 3 — Kafka Topics

| Layer | Pattern | Example |
|-------|---------|---------|
| Topic function | `topic_<concept>()` in `stream_keys.py` | `topic_signal_tracker()` |
| Topic string | `<env>.<domain>[.<sublayer>]` — dots only, never colons | `prod.signals.tracker` |
| Consumer group | `<concept>_consumer` | `signal_tracker_consumer` |

Domain abbreviations permitted in topic strings when universally understood in quantitative finance: `htf`, `stf`, `mtf`.

### Surface 4 — Database Tables and Columns

| Object | Pattern | Example |
|--------|---------|---------|
| Table | `snake_case` stable relation name | `signal_ledger`, `intelligence_features` |
| View | `<source_table>_<qualifier>` | `signal_ledger_full`, `ohlcv_15m` |
| Migration | `NNN_description.sql` | `095_signal_ledger_split.sql` |
| Timestamp column | Always `ts` | `ts` |
| Timeframe column | Always `tf` | `tf` |
| All other columns | Full `snake_case` noun phrase | `exit_reason`, `pnl_r` |

Table naming uses stable relation names, not strictly grammatical pluralization. Event-store and ledger tables (`signal_ledger`, `llm_calls`) follow conventions already established.

### Surface 5 — Variables, Arguments, and Labels

| Surface | Rule | Example |
|---------|------|---------|
| Function arguments | Full descriptive name | `context`, `signal`, `timeframe` |
| Local variables | Full descriptive name | `signal_context`, `audit_result` |
| Structlog field names | Full descriptive name | `daemon_id`, `symbol`, `failure_reason` |
| Metric label: liveness/DLQ/crash | `agent_id` (legacy compatibility) | `agent_id` |
| All other new metric labels | Full descriptive name | `symbol`, `timeframe`, `job` |
| Enum members | `UPPER_SNAKE_CASE` | `REGIME_TRENDING`, `PENDING` |
| Mathematical variables in formulas | Single-letter mathematical convention | `n`, `x`, `y`, `i`, `j`, `t`, `p`, `r` |

### The Mechanical Derivation Table

Given concept `signal_tracker`:

| Surface | Result |
|---------|--------|
| Daemon class | `SignalTracker` |
| File name | `services/signal_tracker.py` |
| Systemd unit | `indicagent-signal-tracker.service` |
| Topic function | `topic_signal_tracker()` |
| Topic string | `prod.signals.tracker` |
| DB table | `signal_trackers` |
| Log file | `logs/signal_tracker.log` |
| Metric prefix | `signal_tracker_` |
| Structlog `daemon_id` value | `signal_tracker` |
| Variable name | `signal_tracker` |

---

## 5. Model Identity and Evolution

### Names Encode Role, Not Version

A class name is a claim about mathematical role. When an evaluator's internal model changes but its role is unchanged, the name does not change. `SkepticEvaluator` evaluates from an adversarial skeptic perspective and produces a confidence multiplier — that role is stable across LLM provider changes, prompt rewrites, and algorithmic improvements. Internal evolution is tracked by `prompt_version` and equivalent version attributes.

### The Model Evolution Protocol

| Case | Description | Response |
|------|-------------|----------|
| Implementation changes, role unchanged | Prompt rewrite, provider swap, algorithm improvement | Increment `prompt_version`. Class name unchanged. |
| New mathematical approach to the same role | Different technique, same analytical question | New class starts in shadow mode. Old class runs in parallel. When graduation criteria met, new class promoted, old deprecated then deleted. |
| New mathematical role | Genuinely different evaluation perspective, different output contract | New class with a new name derived from its new role. Old class continues independently. |

**Version numbers in class names are prohibited in all three cases.** `SkepticEvaluatorV2` implies `V1` exists simultaneously — either they serve different roles (give them different names) or one is in shadow mode (use `shadow_only`, not a version suffix).

### Shadow Mode Is Runtime State, Not Mathematical Identity

`shadow_only = True` does not create a different type of evaluator. A `SkepticEvaluator` in shadow mode and one in production are the same mathematical object in different operational states. The graduation system (`shadow_registry`) manages the boundary.

Consequences:
- No shadow-suffixed class names — never `SkepticEvaluatorShadow`
- Promotion requires no renaming — `shadow_only` flips, nothing else changes

### Retirement Protocol

When a class is replaced:
1. Add a deprecation note citing the replacement and target removal date.
2. Run in parallel for one deployment cycle to confirm stability.
3. Delete the class. No zombie classes, no `_deprecated` suffixes.

---

## 6. The Abbreviation Policy

### Tier 1 — Always Permitted

**Quantitative finance:**
`pnl` `pnl_r` `mae` `mfe` `ts` `tf` `vol` `vix` `poc` `vah` `val` `beta` `alpha` `sharpe` `drawdown` `htf` `stf` `mtf` `ohlcv` `vwap` `twap` `macd` `rsi` `ema` `sma` `wma` `atr` `adx` `obv` `cci` `aroon` `sar` `obb` `stoch`

**Statistics and mathematics:**
`std` `corr` `cov` `mse` `rmse` `aic` `bic` `hmm` `ks` `cusum` `pdf` `cdf`

**Mathematical variables in computation:**
`n` `x` `y` `i` `j` `k` `t` `p` `r`

**Computer science:**
`id` `url` `api` `db` `io` `sql` `json` `xml` `http` `https` `tcp` `udp` `uuid` `regex` `sdk` `cli` `sse` `llm` `gpu` `cpu` `otel` `rpc` `jwt` `ssl` `tls` `dns`

### Tier 2 — Specific Surfaces Only

| Code | Permitted where |
|------|----------------|
| `i1`–`i8` | Topic strings, metric labels |
| `smc` | Topic strings, JSONB keys |
| `agent_id` | Metric labels, structlog fields (legacy family only) |

### Tier 3 — Never Permitted

`ctx` → `context` | `cfg` → `config` | `msg` → `message` | `evt` → `event`
`sig` → `signal` | `dep`/`deps` → `dependency`/`dependencies` | `impl` → name by role
`obj` → name by type | `res` → `result` | `req` → `request` | `resp` → `response`
`tmp` → name by what it holds | `err` → `error` | `exc` → `exception`
`fn` → name by role | `num` → `count` or `number` | `idx` → `index`
`buf` → `buffer` | `e` in `except Exception as e` → `error` or `exception`

**`val`:** Tier 3 when meaning "value". Tier 1 when meaning value area low. Enforcement is by code review, not grep.

### The Test

Would a practitioner write this on a whiteboard in a mathematics, finance, or CS seminar and have every peer read it without decoding? If yes — permitted. If no — not permitted.

---

## 7. The Ring 0 Portability Contract

### What Ring 0 Exports

```
src/core/
  agent/
    BaseDaemon             daemon lifecycle, Kafka, systemd, OTel, watchdog
    BaseWriter             writer pattern: DLQ, batch, parse contract
    BaseProvider           ingestion pattern: reconnect, gap detection
  ai/
    BaseAIWorker           LLM generation, audit trail, typed output
    BaseGroupCoordinator   group coordinator for parallel evaluator dispatch
    AgentDependencies      typed DI container for AI agent construction
    WorkerContext          frozen execution context for one evaluator run
    LLMAdapter             Pydantic AI Model protocol bridge
    AIWorkerProtocol       protocol interface for AI workers
    Evaluator              abstract: evaluate → scored judgment
    Synthesizer            abstract: synthesize → qualitative output

src/observability/         OTel, metrics, spans, circuit breaker
src/persistence/           generic repository pattern, connection pool
src/monitoring/            CUSUM, KS drift — statistical monitors
```

**`BaseAIWorker` is interim.** Ring 1 mathematical objects (`SkepticEvaluator`, `CorrelationAnalyzer`) currently inherit from a daemon base. Separating the evaluator class hierarchy from the daemon hierarchy is Phase 2 architectural work — required before the evaluator pattern is reused in a new project.

### Domain Objects That Belong in Ring 1

| Object | Correct location | Reason |
|--------|-----------------|--------|
| `AIContext` | `src/intelligence/context.py` | Trading intelligence state — fails portability test |
| `SignalContext` (rename target) | `src/intelligence/context.py` | Same |
| `AIContextCache` | `src/intelligence/context.py` | Domain cache tied to intelligence tiers |

### Boundary Enforcement

Ring 0 has zero dependencies on outer rings. Any file in `src/core/` importing from `src/intelligence/`, `src/config/`, `src/providers/`, `src/self_healing/`, or `services/` is a boundary violation caught in CI.

---

## 8. CI Enforcement

The taxonomy is only durable if violations fail the build.

**Implementation:** The grep checks below are advisory pre-checks. For durable enforcement, implement an AST-based Python linter using the `ast` module for class name checks and an import graph checker for boundary violations. Extract the taxonomy YAML block in Section 3 into a standalone `taxonomy.yaml` as the single source of truth for both.

### Check 1 — Retired Mechanism Words

```bash
grep -rn "class.*ComputeAgent\b\|class.*\bManager\b\|class.*\bHelper\b\|class.*Utils\b\|class.*\bHandler\b\|class.*\bProcessor\b\|class.*\bAgent\b" \
  src/ services/ --include="*.py"
```

Exceptions: `Handler` in `src/api/` (HTTP handlers). `Manager` for genuine resource managers — requires explicit taxonomy note. Test files excluded.

### Check 2 — Banned Code Abbreviations

```bash
grep -rn "\bctx\b\|\bcfg\b\|\bmsg\b\|\bevt\b\|\bdeps\b\|\btmp\b\|\berr\b\|\bexc\b\|\bres\b\|\bsig\b\|\breq\b\|\bresp\b\|\bidx\b\|\bbuf\b\|\bfn\b\|\bobj\b\|\bnum\b" \
  src/ services/ --include="*.py" | grep -v "test_\|#\|\".*\"\|'.*'"
```

Not applied to single-letter mathematical variables. `val` ambiguity requires human review.

### Check 3 — Ring 0 Boundary Violation

```bash
grep -rn "from src\.intelligence\|from src\.config\|from src\.providers\|from src\.self_healing\|from services" \
  src/core/ src/observability/ src/persistence/ src/monitoring/ --include="*.py"
```

### Check 4 — Taxonomy Coverage for New Classes

Every new class in `services/` or `src/intelligence/ai/` must end with a suffix from `runtime_processes.suffixes` or `mathematical_objects.suffixes`, or be listed in `runtime_processes.plain_role_nouns`. Implemented as a pre-commit Python script.

### Check 5 — Segment Count (Advisory)

```python
import re
def segment_count(name): return len(re.findall(r'[A-Z][a-z0-9]+', name))
# flag if segment_count(class_name) >= 4
```

Four or more segments is a strong signal the concept hasn't been named precisely or the object has too many responsibilities.

---

## 9. Stable Conventions

These do not change as part of any rename or refactor:

- **Kafka topic strings** — current pattern is correct
- **DB table names** — `signal_ledger`, `intelligence_features`, `llm_calls` stay
- **DB column quant codes** — `ts`, `tf`, `pnl_r`, `mae`, `mfe` stay
- **Plugin naming** — `PascalCasePlugin` stays
- **Intelligence tier codes** — `i1`–`i8` stay in topic strings, metric labels, and directory names; not permitted as DB column names
- **Ring 0/1 `Base*` prefix** — `BaseDaemon`, `BaseWriter`, `BaseProvider`, `BaseAIWorker`, `BaseGroupCoordinator` keep `Base*`
- **`agent_id` metric label and structlog field** — stays for operational compatibility
- **Systemd unit names** — updated mechanically when class/file names change, never independently

---

## 10. Operational Files — Surface 6

These are the non-code file categories that appear at the project root and in supporting directories. Each has a single canonical location and a deletion rule.

### The Renaissance Deletion Principle

> **A file with no permanent operational use is deleted the day its job is complete. Git history is the archive. There are no archive folders.**

An `archive/` subdirectory signals uncertainty about whether work is truly finished. That uncertainty is noise. Delete the file; the commit that removed it records what it was and why.

### Migration Files

| Location | Rule |
|----------|------|
| `db/migrations/NNN_description.sql` | Canonical home for all migrations Phase 104+. Numbered sequentially. Applied once; never modified after apply. |
| `production/migrations/` | Legacy home, frozen. Migrations 001–103 live here. No new files. |

One canonical home. The split exists because `db/migrations/` was established in Phase 104 as the correct Ring 3 location. `production/migrations/` is preserved for history only.

**Naming:** `NNN_description.sql` where `NNN` is globally unique across both directories. Duplicate numbers are a violation — they are the artifact of parallel development without coordination and must be resolved.

### Operational Tools — `tools/`

Permanent utilities used on a recurring basis to operate, validate, or analyze the live system.

| Pattern | Example | Rule |
|---------|---------|------|
| `<concept>_<verb>.py` | `validate_skeptic.py` | Validates a live component against a baseline |
| `<concept>_<noun>.py` | `feature_selection.py` | Applies a quantitative decision rule |
| `backtest_<concept>.py` | `backtest_i6_plugin.py` | Replays historical data against a plugin |
| `check_<concept>.py` | `check_duplicate_tests.py` | Diagnostic or integrity check |
| `compute_<concept>.py` | `compute_skeptic_baseline.py` | Computes a baseline or reference value |
| `scan_<concept>.py` | `scan_binary_patterns.py` | Pattern sweep across data or code |

A tool belongs in `tools/` only if it will be run again. If it answers a one-time question, it is deleted after use — not committed. If it was already committed, delete it in the next cleanup pass.

`tools/` has no subdirectories. A `tools/backtest/` or `tools/archive/` is a signal that the directory is being used as a graveyard.

### Operational Scripts — `production/scripts/`

Long-running or periodic operational scripts that are part of the deployed system — backfills, replays, batch jobs. These are not tools; they are part of the production workflow.

| Pattern | Example |
|---------|---------|
| `<verb>_<concept>.py` | `run_historical_pipeline.py`, `lifecycle_replay.py` |
| `<concept>_<verb>.sh` | `db_setup.sh`, `ensure_topics.sh` |

One-off scripts used during a phase (data migrations, schema repairs, investigation queries) are deleted when the phase closes. They are not committed unless they are part of a repeatable production operation. If already committed and the job is done, delete on next cleanup pass.

`production/scripts/archive/` is prohibited. Delete, don't archive.

### Schema Reference Files — `production/schemas/`

Monolithic schema snapshots (`create_schema.sql`, `signal_ledger_migration.sql`) are an anti-pattern once a migration sequence exists. The migrations ARE the schema. A snapshot that is not continuously maintained diverges from reality and becomes noise.

**Rule:** No schema snapshot files. The current schema is reconstructed by applying all migrations in sequence. If a snapshot is needed for onboarding, generate it from the live database — do not commit a hand-maintained copy.

### Systemd Unit Files — `production/systemd/`

Every `.service` and `.timer` file in `production/systemd/` corresponds to a deployed or deployment-ready service. A unit file for a service that has been permanently abandoned is deleted immediately — not commented out, not renamed with `.disabled`.

A unit file for a service that is implemented but not yet installed is legitimate — it is the deployment artifact waiting for the install step. The distinction: **planned vs abandoned**. Planned services have a live Python implementation in `services/`. Abandoned services have neither a live implementation nor a phase that will deploy them.

---

*When the taxonomy grows, update Section 3 and the YAML block. When a new surface is added, update Section 4. The spec grows; the principle does not.*
