# Renaissance Naming System — Design Spec

**Version:** 1.0
**Date:** 2026-05-30
**Status:** Active — living document
**Scope:** All naming surfaces across all rings of the IndicAgent codebase and any project built from this foundation

---

## Purpose

This spec establishes the complete vocabulary system for the IndicAgent codebase. It is designed explicitly as a portable foundation: when a new project is started, this document and `src/core/` travel with it unchanged.

The naming system is not a style guide. It is a mathematical specification of what kinds of objects exist in this system, how they are named, and how that naming is mechanically derived and enforced. Every name is a claim about what an object IS. Claims must be true.

---

## 1. Philosophy and Governing Tests

### The Core Principle

**The vocabulary IS the model. The model IS the vocabulary.**

The mathematical model and the codebase are not two things connected by documentation — they are one thing. The names prove it. When a senior quant reads a list of class names, they are reading the mathematical architecture: what the system evaluates, what it synthesizes, what it writes, what it monitors. When names describe mechanism instead of role, the code has drifted from the model. Naming cleanup is not cosmetic — it restores the identity between model and code.

### Three Governing Tests

Every name, on every surface, is evaluated against these three tests. They are the only decision tools needed.

**The Whiteboard Test**
Write the name on a whiteboard in a mathematics seminar. Would a quant immediately understand what the object IS — its role in the mathematical model? `SkepticEvaluator` passes. `SkepticComputeAgent` fails. `context` passes. `ctx` fails.

**The Survival Test**
If you replaced the implementation tomorrow — swap the LLM for a neural net, swap asyncio for threads, swap Kafka for a message queue — would the name still be correct? If yes, it names the role. If no, it names the mechanism. `BarAggregator` survives any implementation change. `BarAggregatorComputeAgent` does not — `Compute` describes mechanism.

**The Portability Test** *(applies to Ring 0 only)*
Could this name be extracted into a shared library and used unchanged in a credit risk system, an options pricing engine, or a macro research platform? If not, it belongs in Ring 1 or Ring 2, not Ring 0. `BaseAgent` passes — it names the daemon base in any system. `AIContext` fails — it names a trading intelligence construct. `SignalContext` also fails Ring 0 — correct in Ring 1, wrong for generic infrastructure.

### What Fails All Three Tests

- **Mechanism words:** `Compute`, `Process`, `Handle`, `Manage`, `Execute` — all software does these things. They describe how, not what.
- **Unearned role words:** `Agent` on a component that is called, not autonomous. `Service` on a class that is not a service.
- **The `Base*` pattern on domain objects:** `BaseMultiplierAgent` implies a non-base `MultiplierAgent` exists. `Evaluator` (abstract) is simply the type.
- **Code abbreviations:** `ctx`, `cfg`, `msg`, `sig` — shortcuts that fail the whiteboard test in every field.
- **Three independent semantic units:** if a name requires three unrelated concepts, the object is doing too much or the concept hasn't been named precisely.

---

## 2. The Four Ring Architecture

Every file, class, and module belongs to exactly one ring. The ring determines how generic or domain-specific names must be, and whether the code travels to other projects unchanged.

```
Ring 0  src/core/, src/observability/, src/persistence/, src/monitoring/
        Portable infrastructure. No domain vocabulary. Passes portability test.
        Travels to any new project verbatim.

Ring 1  src/intelligence/, src/config/, src/providers/, src/self_healing/, src/validation/
        Domain layer. IndicAgent-specific vocabulary is correct here.
        New projects write their own Ring 1 using the same rules.

Ring 2  services/
        Runtime processes (daemons). Always fully specific.
        Pure role nouns. Location and BaseAgent inheritance encode "this is a daemon."

Ring 3  src/api/, dashboard/, production/
        External interfaces. REST, frontend, deployment.
        Follows surface-specific conventions (REST, TypeScript, systemd).
```

**Import direction is strictly outward — never inward:**

```
Ring 0  →  no imports from Ring 1, 2, or 3
Ring 1  →  imports from Ring 0 only
Ring 2  →  imports from Ring 0 and Ring 1
Ring 3  →  imports from any ring
```

A Ring 0 file importing from `src/intelligence/` or `services/` is a boundary violation. This is checked in CI.

**`Base*` prefix rule:**
- Infrastructure base classes in Ring 0 keep `Base*` — they are shared implementation foundations, not domain objects. `BaseAgent` is this project's equivalent of `abc.ABC`. It does not imply a non-base `Agent` floating around.
- Mathematical abstract types in Ring 0/1 drop `Base*` — the abstract class IS the type. `Evaluator` (not `BaseEvaluator`). `Synthesizer` (not `BaseSynthesizer`).

---

## 3. The Complete Taxonomy

Two vocabularies. Every object in the system belongs to exactly one category in exactly one vocabulary.

### Vocabulary A — Mathematical Objects

Called, not run. No Kafka connection, no systemd unit, no daemon loop. Perform a mathematical operation and return a result. Live in Ring 0 or Ring 1.

Abstract types in this vocabulary are the type itself — no `Base*` prefix.

| Category | Mathematical role | Output contract | Example |
|----------|-----------------|-----------------|---------|
| `Evaluator` | Evaluates from a specific perspective, produces a scored judgment | Score ∈ [0,2] or qualitative judgment | `SkepticEvaluator`, `RegimeCoherenceEvaluator` |
| `Analyzer` | Performs structured analytical computation | Structured typed result | `CorrelationAnalyzer`, `CrossAssetAnalyzer` |
| `Synthesizer` | Combines multiple signals into qualitative synthesis | Narrative or annotation | `NarrativeSynthesizer`, `FundamentalSynthesizer` |
| `Detector` | Detects presence or absence of a pattern or condition | Boolean or classified signal | `BreakoutDetector`, `RegimeDetector` |
| `Classifier` | Assigns inputs to mutually exclusive categories | Enumerated category | `SessionClassifier`, `VolatilityClassifier` |
| `Aggregator` | Combines multiple numerical inputs into a unified measure | Scalar or vector | `ConfluenceAggregator`, `CISAggregator` |

### Vocabulary B — Runtime Processes

Run autonomously. Have a daemon loop, a systemd unit, a Kafka subscription or timer trigger. Live in Ring 2. Class names are pure role nouns — the `services/` location and `BaseAgent` inheritance encode daemon nature; the name encodes role only.

| Category | Role in the data flow | I/O | Example |
|----------|----------------------|-----|---------|
| `Provider` | Ingests from external source → stream | External → Kafka | `IBKRProvider`, `BarReplayProvider` |
| `Merger` | Combines multiple streams into one | Kafka × N → Kafka | `ProviderMerger` |
| `Aggregator` | Aggregates streaming data into higher-level events | Kafka → Kafka | `BarAggregator` |
| `Analyzer` | Computes analytical metrics as a daemon | Kafka / Timer → Kafka | `MacroAnalyzer`, `SignalMetricsAnalyzer` |
| `Writer` | Persists from stream to storage | Kafka → DB | `FeatureWriter`, `SignalWriter`, `LLMWriter` |
| `Tracker` | Manages business object state over time | Kafka → State + Kafka | `SignalTracker` |
| `Auditor` | Validates data integrity, self-heals | DB → Corrections | `SignalAuditor`, `BarAuditor` |
| `Monitor` | Watches conditions, dispatches alerts | Kafka / DB → Alerts | `AlertMonitor` |
| `Orchestrator` | Coordinates multi-step batch workflows | Timer → Jobs | `MLOrchestrator` |
| `Trainer` | Executes model training | Data → Model artifact | `MLTrainer`, `HMMTrainer` |

### Taxonomy Governance

**This taxonomy is a living document.** It grows as new mathematical roles are identified.

When an object does not fit an existing category:
1. Do not force it into the nearest category.
2. Define the new category: name, mathematical role, output contract, example.
3. Add it to the taxonomy and the CI YAML block (Section 7) before naming the object.
4. The taxonomy grows by precision, never by exception.

### Machine-Readable Taxonomy Block

Used by CI lint rules as the single source of truth. Update this block when the taxonomy grows.

```yaml
taxonomy:
  mathematical_objects:
    suffixes: [Evaluator, Analyzer, Synthesizer, Detector, Classifier, Aggregator]
    rings: [0, 1]
    no_base_prefix: true
  runtime_processes:
    suffixes: [Provider, Merger, Aggregator, Analyzer, Writer, Tracker, Auditor, Monitor, Orchestrator, Trainer]
    rings: [2]
    inherits: BaseAgent
  infrastructure_bases:
    classes: [BaseAgent, BaseWriterAgent, BaseProviderAgent, BaseAIAgent]
    rings: [0]
    base_prefix: permitted
  retired:
    suffixes: [ComputeAgent, MultiplierAgent, GroupService]
    words: [Compute, Handler, Helper, Util, Utils, Manager, Processor]
```

---

## 4. The Five Surfaces

One concept name mechanically derives all five surface names. No judgment calls, no lookup tables.

### Surface 1 — Python Classes

Derived from the taxonomy directly.

| Object type | Pattern | Example |
|------------|---------|---------|
| Ring 2 daemon | `PascalCase(concept)` | `SignalTracker` |
| Ring 1 mathematical object | `PascalCase(concept) + CategorySuffix` | `SkepticEvaluator` |
| Ring 0/1 abstract math type | `CategorySuffix` alone | `Evaluator`, `Synthesizer` |
| Ring 0 infrastructure base | `Base + PascalCase(role)` | `BaseAgent`, `BaseWriterAgent` |
| Plugin | `PascalCase(concept) + Plugin` | `ADXPlugin`, `VWAPPlugin` |
| Protocol | `PascalCase(concept) + Protocol` | `AgentProtocol` |
| Result / output model | `PascalCase(concept) + Result` | `SkepticResult`, `SignalMetricsResult` |
| Context carrier | `PascalCase(concept) + Context` | `SignalContext`, `AgentContext`, `SMCContext` |
| Repository | `PascalCase(concept) + Repository` | `SignalLedgerRepository` |
| Error | `PascalCase(concept) + Error` | `ConfigValidationError`, `CircuitOpenError` |

### Surface 2 — File Names

The `_agent` suffix in file names is retired alongside the class suffix. File location encodes the ring; file name encodes the concept only.

| Object type | Pattern | Example |
|------------|---------|---------|
| Ring 2 daemon | `services/<concept>.py` | `services/signal_tracker.py` |
| Ring 1 AI evaluator | `src/intelligence/ai/<group>/<concept>.py` | `src/intelligence/ai/alpha/skeptic.py` |
| Ring 1 domain | `src/intelligence/<module>/<concept>.py` | `src/intelligence/context.py` |
| Ring 0 infrastructure | `src/core/<module>/<concept>.py` | `src/core/ai/evaluator.py` |
| Plugin | `src/intelligence/trading/<concept>.py` | `src/intelligence/trading/adx.py` |

### Surface 3 — Kafka Topics

The current pattern is sound. Documented here for completeness.

| Layer | Pattern | Example |
|-------|---------|---------|
| Topic function | `topic_<concept>()` in `stream_keys.py` | `topic_signal_tracker()` |
| Topic string | `<env>.<domain>[.<sublayer>]` — dots only, never colons | `prod.signals.tracker` |
| Consumer group | `<concept>_consumer` | `signal_tracker_consumer` |

Domain abbreviations permitted in topic strings when universally understood in quantitative finance: `htf`, `stf`, `mtf`. No code abbreviations.

### Surface 4 — Database Tables and Columns

| Object | Pattern | Example |
|--------|---------|---------|
| Table | `snake_case` plural noun | `signal_ledger`, `intelligence_features` |
| View | `<source_table>_<qualifier>` | `signal_ledger_full`, `ohlcv_15m` |
| Migration | `NNN_description.sql` | `095_signal_ledger_split.sql` |
| Timestamp column | Always `ts` | `ts` |
| Timeframe column | Always `tf` | `tf` |
| All other columns | Full `snake_case` noun phrase | `exit_reason`, `failure_probability`, `pnl_r` |

Quant domain codes are permitted as column names — see Section 5 Tier 1.

### Surface 5 — Variables, Arguments, and Labels

No code abbreviations. Quant domain codes and CS standards permitted (Section 5).

| Surface | Rule | Example |
|---------|------|---------|
| Function arguments | Full descriptive name | `context`, `signal`, `timeframe` |
| Local variables | Full descriptive name | `signal_context`, `audit_result` |
| Structlog field names | Full descriptive name | `agent_id`, `symbol`, `failure_reason` |
| Metric names | Prometheus convention (verbose) | `signal_tracker_messages_processed_total` |
| Metric labels | Full descriptive name | `agent_id`, `symbol`, `timeframe` |
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
| Structlog `agent_id` value | `signal_tracker` |
| Variable name | `signal_tracker` |

---

## 5. The Abbreviation Policy

### The Principle

An abbreviation is permitted when it is the canonical term in a rigorous field and passes the whiteboard test *in that field*. `PnL` on a finance whiteboard is not abbreviating "profit and loss" — it IS the term. `API` in a CS context is not shorthand — it IS the term. Field codes carry no information loss because every practitioner reads them without decoding.

Code shortcuts fail the whiteboard test in every field. `ctx`, `cfg`, `msg` are laziness dressed as convention.

### Tier 1 — Always Permitted

Canonical field codes in quantitative finance, statistics, mathematics, and computer science.

**Quantitative finance:**
`pnl` `pnl_r` `mae` `mfe` `ts` `tf` `vol` `vix` `poc` `vah` `val` `beta` `alpha` `sharpe` `drawdown` `htf` `stf` `mtf` `ohlcv` `vwap` `twap` `macd` `rsi` `ema` `sma` `wma` `atr` `adx` `obv` `cci` `aroon` `sar` `obb` `stoch`

**Statistics and mathematics:**
`std` `corr` `cov` `mse` `rmse` `aic` `bic` `hmm` `ks` `cusum` `pdf` `cdf`

**Mathematical variables in computation:**
`n` (count/sample size) `x` `y` (generic mathematical variables) `i` `j` `k` (indices) `t` (time) `p` (price or probability) `r` (return)

**Computer science and programming standards:**
`id` `url` `api` `db` `io` `sql` `json` `xml` `http` `https` `tcp` `udp` `uuid` `regex` `sdk` `cli` `sse` `llm` `gpu` `cpu` `otel` `rpc` `jwt` `ssl` `tls` `dns`

### Tier 2 — Permitted in Specific Surfaces Only

| Code | Permitted where | Rationale |
|------|----------------|-----------|
| `i1`–`i8` | DB columns, topic strings, metric labels | Intelligence tier codes — IndicAgent domain vocabulary |
| `smc` | Topic strings, JSONB keys | Smart Money Concepts sub-domain abbreviation |
| Prometheus label conventions | Metric names only | Prometheus has established naming standards |

### Tier 3 — Never Permitted

Code shortcuts. Use the full word or name by role.

`ctx` → `context` | `cfg` → `config` | `msg` → `message` | `evt` → `event`
`sig` → `signal` | `dep`/`deps` → `dependency`/`dependencies` | `impl` → name by role
`obj` → name by type | `res` → `result` | `req` → `request` | `resp` → `response`
`tmp` → name by what it holds | `err` → `error` | `exc` → `exception`
`fn` → name by role | `num` → `count` or `number` | `idx` → `index`
`buf` → `buffer` | `val` → `value` (unless meaning value area low — that is Tier 1)
`e` in `except Exception as e` → `error` or `exception`

### The Test

Would a practitioner write this on a whiteboard in a mathematics, finance, or computer science seminar and have every peer read it without decoding? If yes — field code, permitted. If no — shortcut, not permitted.

---

## 6. The Ring 0 Portability Contract

### What Ring 0 Exports

Ring 0 publishes a stable public API. Every class exported from `src/core/` is a contract. Other projects depend on it without modification.

```
src/core/
  agent/
    BaseAgent           daemon lifecycle, Kafka, systemd, OTel, watchdog
    BaseWriterAgent     writer pattern: DLQ, batch, parse contract
    BaseProviderAgent   ingestion pattern: reconnect, gap detection
  ai/
    BaseAIAgent         LLM generation, audit trail, typed output
    AgentContext        frozen execution context for one agent run
    LLMAdapter          Pydantic AI Model protocol bridge
    Evaluator           abstract: evaluate → scored judgment
    Synthesizer         abstract: synthesize → qualitative output

src/observability/      OTel, metrics, spans, circuit breaker
src/persistence/        generic repository pattern, connection pool
src/monitoring/         CUSUM, KS drift — generic statistical monitors
```

### Domain Objects That Belong in Ring 1

These currently live near Ring 0 but carry domain vocabulary:

| Object | Correct location | Reason |
|--------|-----------------|--------|
| `AIContext` | `src/intelligence/context.py` | Trading intelligence state — fails credit risk portability test |
| `SignalContext` (rename target) | `src/intelligence/context.py` | Same |
| `AIContextCache` | `src/intelligence/context.py` | Domain cache tied to intelligence tiers |

### Boundary Enforcement

Ring 0 has zero dependencies on outer rings. If any file in `src/core/` imports from `src/intelligence/`, `src/config/`, `src/providers/`, `src/self_healing/`, or `services/`, it is a boundary violation caught in CI.

---

## 7. CI Enforcement

The taxonomy is only durable if violations fail the build. Without enforcement, vocabulary drifts back within months.

### Check 1 — Retired Mechanism Words

Fail if any class name contains a retired word.

```bash
grep -rn "class.*ComputeAgent\b\|class.*\bManager\b\|class.*\bHelper\b\|class.*Utils\b\|class.*\bHandler\b\|class.*\bProcessor\b" \
  src/ services/ --include="*.py"
```

Exception: `Handler` in `src/api/` (Ring 3, HTTP handlers). `Manager` for genuine resource managers (connection pool, thread pool) — requires explicit taxonomy note.

### Check 2 — Banned Code Abbreviations in Signatures

Fail if any function definition or assignment contains Tier 3 shortcuts.

```bash
grep -rn "\bctx\b\|\bcfg\b\|\bmsg\b\|\bevt\b\|\bdeps\b\|\btmp\b\|\berr\b\|\bexc\b\|\bres\b\b" \
  src/ services/ --include="*.py" | grep -v "test_\|#"
```

Not applied to single-letter mathematical variables in computation functions.

### Check 3 — Ring 0 Boundary Violation

Fail if any Ring 0 file imports from an outer ring.

```bash
grep -rn "from src\.intelligence\|from src\.config\|from src\.providers\|from src\.self_healing\|from services" \
  src/core/ src/observability/ src/persistence/ src/monitoring/ --include="*.py"
```

### Check 4 — Taxonomy Coverage for New Classes

Every new class in `services/` or `src/intelligence/ai/` must end with a suffix from the taxonomy YAML block. Implemented as a pre-commit Python script that parses new class definitions and validates against the `taxonomy.yaml` block in this document.

### Check 5 — 2-Unit Rule (Advisory)

Flag — not fail — any class name with four or more independent PascalCase segments. Triggers human review.

```python
import re
def word_count(name): return len(re.findall(r'[A-Z][a-z0-9]+', name))
# flag if word_count(class_name) >= 4
```

---

## 8. Pending Renames

The following renames are established by this spec. They represent the delta between the current codebase and the target vocabulary. These are executed in a dedicated rename phase — not incrementally.

### Ring 1 — AI Evaluation Layer (I8)

| Current | Target | Category |
|---------|--------|----------|
| `BaseMultiplierAgent` | `Evaluator` (abstract, Ring 0) | Mathematical object |
| `SkepticComputeAgent` | `SkepticEvaluator` | Mathematical object |
| `CorrelationComputeAgent` | `CorrelationAnalyzer` | Mathematical object |
| `CounterfactualComputeAgent` | `CounterfactualEvaluator` | Mathematical object |
| `RegimeCoherenceComputeAgent` | `RegimeCoherenceAnalyzer` | Mathematical object |
| `MLScorerMultiplierAgent` | `MLEvaluator` | Mathematical object |
| `NarrativeComputeAgent` | `NarrativeSynthesizer` | Mathematical object |
| `NarrativeGroupComputeAgent` | `NarrativeSynthesizer` (group coordinator) | Mathematical object |
| `AIContext` | `SignalContext` | Context carrier (Ring 1) |
| `AIContextCache` | `SignalContextCache` | Context carrier (Ring 1) |

### Ring 2 — Daemon Processes

| Current | Target | Category |
|---------|--------|----------|
| `IntelligencePipelineComputeAgent` | `IntelligencePipeline` | Daemon (no category suffix — IS the pipeline) |
| `AlphaSwarmComputeAgent` | `AlphaSwarm` | Daemon (IS the swarm) |
| `BarAggregatorComputeAgent` | `BarAggregator` | Aggregator |
| `ProviderMergerComputeAgent` | `ProviderMerger` | Merger |
| `CrossAssetComputeAgent` | `CrossAssetAnalyzer` | Analyzer |
| `MacroComputeAgent` | `MacroAnalyzer` | Analyzer |
| `SignalMetricsComputeAgent` | `SignalMetricsAnalyzer` | Analyzer |
| `GraduationComputeAgent` | `SignalGraduator` | *(new category candidate — see governance)* |
| `SignalTrackerComputeAgent` | `SignalTracker` | Tracker |
| `AlertingComputeAgent` | `AlertMonitor` | Monitor |
| `MLOrchestratorComputeAgent` | `MLOrchestrator` | Orchestrator |
| `MLDiscoveryComputeAgent` | `MLDiscovery` | Analyzer |
| `MLDataQualityAuditorAgent` | `DataQualityAuditor` | Auditor |
| `MLTrainingComputeAgent` | `MLTrainer` | Trainer |
| `HMMTrainingComputeAgent` | `HMMTrainer` | Trainer |
| `IBKRProviderAgent` | `IBKRProvider` | Provider |
| `BarReplayProviderAgent` | `BarReplayProvider` | Provider |
| `BarWriterAgent` | `BarWriter` | Writer |
| `FeatureWriterAgent` | `FeatureWriter` | Writer |
| `SignalWriterAgent` | `SignalWriter` | Writer |
| `LifecycleWriterAgent` | `LifecycleWriter` | Writer |
| `LineageWriterAgent` | `LineageWriter` | Writer |
| `LLMWriterAgent` | `LLMWriter` | Writer |
| `CtxWriterAgent` | `ContextWriter` | Writer |
| `SwarmLedgerWriterAgent` | `SwarmLedgerWriter` | Writer |
| `SignalMetricsWriterAgent` | `SignalMetricsWriter` | Writer |
| `GraduationWriterAgent` | `GraduationWriter` | Writer |
| `BarAuditorAgent` | `BarAuditor` | Auditor |
| `SignalAuditorAgent` | `SignalAuditor` | Auditor |
| `SignalReplayAuditorAgent` | `SignalReplayAuditor` | Auditor |
| `ServiceAuditorAgent` | `ServiceAuditor` | Auditor |
| `OutboxDispatcherAgent` | `OutboxDispatcher` | *(dispatcher — new category candidate)* |

### File Names (alongside class renames)

File names follow the class rename. `bar_aggregator_agent.py` → `bar_aggregator.py`. The `_agent` suffix is retired from file names in Ring 2.

### Documentation

`docs/foundation/naming-conventions.md` is superseded by this spec for all prescriptive guidance. It will be updated to reference this document as the canonical source in the rename phase.

---

## 9. What Does Not Change

- **Kafka topic strings** — the current pattern is correct.
- **DB table names** — correct. `signal_ledger`, `intelligence_features` stay.
- **DB column quant codes** — `ts`, `tf`, `pnl_r`, `mae`, `mfe` stay.
- **Plugin naming** — `PascalCasePlugin` convention stays.
- **Intelligence tier codes** — `I1`–`I8` stay in code, docs, and metrics.
- **`BaseAgent`, `BaseWriterAgent`, `BaseProviderAgent`, `BaseAIAgent`** — Ring 0 infrastructure bases keep `Base*`.
- **Systemd unit names** — updated mechanically when class/file names change, no independent changes.

---

*This document is the authoritative vocabulary spec for IndicAgent and any project built from this foundation. When the taxonomy grows, update Section 3 and the YAML block. When a new surface is added, add it to Section 4. The spec grows; the principle does not.*
