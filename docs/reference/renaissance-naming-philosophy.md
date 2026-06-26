# Renaissance Naming System — Design Spec

**Version:** 1.2
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

### The Invariant

Every naming decision in this spec reduces to one falsifiable test:

> **A name is correct if and only if a domain expert who has never seen the implementation can correctly predict the object's mathematical role, its inputs, and its output contract from the name alone — without reading any code.**

This is the single criterion. The three governing tests below are tools for applying it. When they conflict or leave a case unresolved, return to the invariant. If you cannot state what inputs and outputs a reader would predict from the name, the name is wrong.

The invariant is also why naming enforcement belongs in code review, not just CI. Automated checks catch mechanical violations. The invariant requires domain judgment.

### Three Governing Tests

Every name, on every surface, is evaluated against these three tests.

**The Whiteboard Test**
Write the name on a whiteboard in a mathematics seminar. Would a quant immediately understand what the object IS — its role in the mathematical model? `SkepticEvaluator` passes. `SkepticComputeAgent` fails. `context` passes. `ctx` fails.

**The Survival Test**
If you replaced the implementation tomorrow — swap the LLM for a neural net, swap asyncio for threads, swap Kafka for a message queue — would the name still be correct? If yes, it names the role. If no, it names the mechanism. `BarAggregator` survives any implementation change. `BarAggregatorComputeAgent` does not — `Compute` describes mechanism.

**The Portability Test** *(applies to Ring 0 only)*
Could this name be extracted into a shared library and used unchanged in a credit risk system, an options pricing engine, or a macro research platform? If not, it belongs in Ring 1 or Ring 2, not Ring 0. `BaseDaemon` passes — it names the daemon base in any system. `AIContext` fails — it names a trading intelligence construct.

### What Fails All Three Tests

- **Mechanism words:** `Compute`, `Process`, `Handle`, `Manage`, `Execute` — all software does these things. They describe how, not what.
- **Unearned role words:** `Agent` on a component that is called, not autonomous. `Service` on a class that is not a service.
- **The `Base*` pattern on domain objects:** `BaseMultiplierAgent` implies a non-base `MultiplierAgent` exists. `Evaluator` (abstract) is simply the type.
- **Code abbreviations:** `ctx`, `cfg`, `msg`, `sig` — shortcuts that fail the whiteboard test in every field.
- **Three unrelated semantic units:** if a name requires three concepts with no shared mathematical relationship, the object is doing too much or the concept hasn't been named precisely. Note: three related words in a compound concept (`RegimeCoherenceAnalyzer`, `SignalMetricsWriter`) are fine — the smell is *unrelated* concepts, not word count. The CI advisory check (Section 8, Check 5) flags four or more PascalCase segments as a concrete heuristic.

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
        Pure role nouns. Location and BaseDaemon inheritance encode "this is a daemon."

Ring 3  src/api/, dashboard/, production/
        External interfaces. REST, frontend, deployment.
        Follows surface-specific conventions (REST, TypeScript, systemd).
```

**Note on Ring 1 sub-modules:** Some files within Ring 1 directories may contain purely generic patterns (e.g., a provider reconnect mixin with no IndicAgent vocabulary). Those individual files may be factored into Ring 0 when they genuinely pass the portability test. The Ring 1 assignment describes where domain-specific implementations belong by default, not a blanket prohibition on portable code within those directories.

**Outer rings depend on inner rings; inner rings must never depend on outer rings:**

```
Ring 0  →  no imports from Ring 1, 2, or 3
Ring 1  →  imports from Ring 0 only
Ring 2  →  imports from Ring 0 and Ring 1
Ring 3  →  imports from any ring
```

A Ring 0 file importing from `src/intelligence/` or `services/` is a boundary violation. This is checked in CI.

### Rings vs Intelligence Tiers

Rings and the I1–I8 intelligence tiers are orthogonal systems. Rings describe portability and architectural layer. Tiers describe a class's position in the mathematical pipeline — what transforms what.

**File location encodes tier membership; class names do not repeat tier codes.**

`src/intelligence/features/i1_indicators/rsi.py` contains `RSIPlugin`. The `i1_indicators` directory signals I1 membership. The class name `RSIPlugin` does not need to become `I1RSIPlugin`. Tier is structural metadata; names encode mathematical role.

Exception: when tier membership is the concept itself — an object that explicitly manages tier boundaries or is defined by spanning tiers — the tier code may appear in the name. This should be rare and requires justification.

**`Base*` prefix rule:**
- Infrastructure base classes in Ring 0 keep `Base*` — they are shared implementation foundations. `BaseDaemon` is this project's equivalent of `abc.ABC`. It does not imply a non-base `Daemon` floating around.
- Mathematical abstract types in Ring 0/1 drop `Base*` — the abstract class IS the type. `Evaluator` (not `BaseEvaluator`). `Synthesizer` (not `BaseSynthesizer`).

**`Agent` is fully retired** — including from infrastructure base class names. The word fails the whiteboard test in 2026 (polluted by LLM framework conventions) and the survival test (a `BaseDaemon` is still a daemon if you swap Kafka for Redis Streams; a `BaseAgent` implies framework-specific agent semantics). No exceptions in class or file names.

**`agent_id` operational exception:** The metric label key `agent_id` and the structlog field `agent_id` are preserved as-is for operational compatibility with existing Grafana dashboards, Prometheus alert rules, and OTel pipelines. Renaming these would break production observability across all running services. This is an explicit one-time exception: `agent_id` is a legacy operational field. All new metric labels and log fields introduced after the rename phase use the role-specific identifier (e.g., `daemon_id`, `service_id`, or the specific concept name) unless wiring into an existing metric family.

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

Run autonomously. Have a daemon loop, a systemd unit, a Kafka subscription or timer trigger. Live in Ring 2. Class names are pure role nouns — the `services/` location and `BaseDaemon` inheritance encode daemon nature; the name encodes role only.

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
| `Publisher` | Reads from DB/outbox and emits to stream | DB → Kafka | `OutboxPublisher` |

### Disambiguating Shared Suffixes

`Aggregator` and `Analyzer` appear in both Vocabulary A and Vocabulary B. The disambiguation rule:

- **Ring determines vocabulary.** A class in Ring 0/1 with suffix `Aggregator` or `Analyzer` is a mathematical object — called, stateless, returns a result. A class in Ring 2 with the same suffix is a daemon — runs autonomously, owns a Kafka subscription or timer.
- **Lifecycle determines vocabulary.** Mathematical objects have no `start()`/`stop()` lifecycle. Daemons do.

This is not ambiguous in practice: ring membership is determined by file location, and `BaseDaemon` inheritance is required for Ring 2. A `BarAggregator` in `services/` is a daemon. A `CISAggregator` in `src/intelligence/` is a mathematical object.

### Plain Role Nouns (Ring 2 exemption)

Some Ring 2 daemons are the concept itself — no category suffix adds precision. These are listed explicitly and exempt from the taxonomy suffix requirement (Check 4 in Section 8):

| Name | Reason |
|------|--------|
| `IntelligencePipeline` | IS the pipeline — adding `Analyzer` or `Orchestrator` would misrepresent its role as the unified I1-I7 compute process |
| `AlphaSwarm` | IS the swarm — the swarm is the architectural concept, not a coordinator of a different thing |
| `NarrativeSwarm` | Same pattern as `AlphaSwarm` — the group coordinator IS the swarm |

New plain role nouns require explicit addition to this table before use. The anti-creep rule applies: a concept name is not self-evidently a plain role noun unless the taxonomy has no suffix that fits without distortion.

### The Composability Principle

A composition of mathematical objects or runtime processes earns its own name when it has a **stable mathematical identity that outlives its current members**: if the composition's members can be replaced without changing what the composition IS, the name is correct.

`AlphaSwarm` is stable: replacing `SkepticEvaluator` with `AdversarialEvaluator` does not change what the swarm IS — a group evaluation process that produces a composite alpha multiplier. The name belongs to the role of the composition, not to the enumeration of its parts.

**Rules for naming compositions:**

1. **Name by role, never by members.** `AlphaSwarm` not `SkepticCorrelationCounterfactualEvaluatorGroup`. The members are implementation detail.
2. **A composition that IS its pipeline does not earn a separate name.** If replacing any member changes what the thing IS, it is a pipeline, and the pipeline's stage names apply.
3. **When a composition gains stable identity, it earns a plain role noun** — apply the plain role noun rule above. It does not require a category suffix when the composition IS the thing.
4. **Composites name coordinators separately from members.** `NarrativeSwarm` (coordinator daemon, Ring 2) is distinct from `NarrativeSynthesizer` (individual mathematical object, Ring 1). The coordinator IS the swarm; the synthesizer IS the mathematical operation.

### Taxonomy Governance

**This taxonomy is a living document.** It grows as new mathematical roles are identified.

**Anti-creep rule:** A new category requires at least two distinct existing objects that share the same mathematical role and fit no current category. One object is not a pattern — it is an edge case. Edge cases map to the nearest existing category.

**Governance:** Taxonomy additions require the proposer to demonstrate that the three governing tests pass for the new category name, that the anti-creep rule is satisfied, and that at least one other engineer with domain knowledge reviews the addition against this spec. This is a domain correctness decision, not a majority vote. The spec is the decision framework.

When an object does not fit an existing category:
1. Check the anti-creep rule first.
2. If two or more objects share an unrepresented role, define the new category: name, mathematical role, output contract, example.
3. Add it to the taxonomy YAML block before naming the object.
4. The taxonomy grows by precision and reuse, never by exception.

### Machine-Readable Taxonomy Block

Used by CI lint rules as the single source of truth. Update this block when the taxonomy grows.

```yaml
taxonomy:
  mathematical_objects:
    suffixes: [Evaluator, Analyzer, Synthesizer, Detector, Classifier, Aggregator]
    rings: [0, 1]
    no_base_prefix: true
  runtime_processes:
    suffixes: [Provider, Merger, Aggregator, Analyzer, Writer, Tracker, Auditor, Monitor, Orchestrator, Trainer, Publisher]
    plain_role_nouns: [IntelligencePipeline, AlphaSwarm, NarrativeSwarm]
    rings: [2]
    inherits: BaseDaemon
  infrastructure_bases:
    classes: [BaseDaemon, BaseWriter, BaseProvider, BaseAIWorker, BaseSwarmCoordinator]
    rings: [0]
    base_prefix: permitted
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

Derived from the taxonomy directly.

| Object type | Pattern | Example |
|------------|---------|---------|
| Ring 2 daemon | `PascalCase(concept)` + category suffix | `SignalTracker`, `BarAggregator` |
| Ring 2 daemon (plain role noun) | `PascalCase(concept)` — no suffix | `IntelligencePipeline`, `AlphaSwarm` |
| Ring 1 mathematical object | `PascalCase(concept)` + category suffix | `SkepticEvaluator` |
| Ring 0/1 abstract math type | Category suffix alone | `Evaluator`, `Synthesizer` |
| Ring 0 infrastructure base | `Base` + `PascalCase(role)` | `BaseDaemon`, `BaseWriter` |
| Behavioral mixin | `PascalCase(capability)` + `Mixin` | `IncrementalMixin`, `ConfigConsumerMixin` |
| Enumeration | `PascalCase` singular noun — no suffix | `MarketRegime`, `SignalStatus`, `AssetClass` |
| Component config | `PascalCase(concept)` + `Config` | `EvaluatorConfig`, `PipelineConfig` |
| Plugin | `PascalCase(concept)` + `Plugin` | `ADXPlugin`, `VWAPPlugin` |
| Protocol | `PascalCase(concept)` + `Protocol` | `AIWorkerProtocol` |
| Result / output model | `PascalCase(concept)` + `Result` | `SkepticResult`, `SignalMetricsResult` |
| Context carrier | `PascalCase(concept)` + `Context` | `SignalContext`, `WorkerContext`, `SMCContext` |
| Repository | `PascalCase(concept)` + `Repository` | `SignalLedgerRepository` |
| Error | `PascalCase(concept)` + `Error` | `ConfigValidationError`, `CircuitOpenError` |

**On mixins:** A mixin provides behavioral capability through methods. It must not carry persistent state of its own — if it needs state, the capability belongs in a base class or a composed object, not a mixin. `IncrementalMixin` provides incremental computation methods to plugins. `ConfigConsumerMixin` provides config subscription capability to daemons.

**On enumerations:** Enum members are `UPPER_SNAKE_CASE`. The enum type name is a singular noun — `MarketRegime` not `MarketRegimes`, `SignalStatus` not `SignalStatuses`. The type IS the enumeration; plural implies a collection, not a type. Enums live in the same ring as the domain they describe: `CircuitState` in Ring 0 (`src/observability/`), `MarketRegime` in Ring 1 (`src/intelligence/`).

**On component config:** A component gets its own `*Config` type only when its configuration is meaningfully distinct from global `Settings` and must be passed explicitly — in tests, in parameterized instantiation, or when the component is reused across contexts. Components that read directly from `Settings` at construction do not get a `*Config` type.

### Surface 2 — File Names

The `_agent` suffix in file names is retired alongside the class suffix. File location encodes both the ring and the intelligence tier; file name encodes the concept only.

| Object type | Pattern | Example |
|------------|---------|---------|
| Ring 2 daemon | `services/<concept>.py` | `services/signal_tracker.py` |
| Ring 1 AI evaluator | `src/intelligence/ai/<group>/<concept>.py` | `src/intelligence/ai/alpha/skeptic.py` |
| Ring 1 domain | `src/intelligence/<module>/<concept>.py` | `src/intelligence/context.py` |
| Ring 0 infrastructure | `src/core/<module>/<concept>.py` | `src/core/ai/evaluator.py` |
| Plugin (I1–I5) | `src/intelligence/features/i<N>_<tier_name>/<concept>.py` | `src/intelligence/features/i1_indicators/rsi.py` |

The tier subdirectory (`i1_indicators`, `i3_structure`, etc.) encodes tier membership. The file name does not repeat the tier. `rsi.py` not `i1_rsi.py`.

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
| Table | `snake_case` stable relation name | `signal_ledger`, `intelligence_features` |
| View | `<source_table>_<qualifier>` | `signal_ledger_full`, `ohlcv_15m` |
| Migration | `NNN_description.sql` | `095_signal_ledger_split.sql` |
| Timestamp column | Always `ts` | `ts` |
| Timeframe column | Always `tf` | `tf` |
| All other columns | Full `snake_case` noun phrase | `exit_reason`, `failure_probability`, `pnl_r` |

**On table naming:** The rule is a stable, readable relation name — not strictly grammatical pluralization. Event-store and ledger tables (`signal_ledger`, `llm_calls`) follow the convention already established. Do not rename existing tables for grammatical consistency. New tables should use a name that a quant would write naturally on a whiteboard for that relation.

Quant domain codes are permitted as column names — see Section 6 Tier 1.

### Surface 5 — Variables, Arguments, and Labels

No code abbreviations. Quant domain codes and CS standards permitted (Section 6).

| Surface | Rule | Example |
|---------|------|---------|
| Function arguments | Full descriptive name | `context`, `signal`, `timeframe` |
| Local variables | Full descriptive name | `signal_context`, `audit_result` |
| Structlog field names | Full descriptive name | `daemon_id`, `symbol`, `failure_reason` |
| Metric label: liveness/DLQ/crash | `agent_id` (legacy compatibility — see Section 2) | `agent_id` |
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

This section governs how names behave when the mathematical model changes. It is the most important section for long-term vocabulary integrity.

### Names Encode Role, Not Version

A class name is a claim about mathematical role. It is not a version identifier, a prompt identifier, or an implementation identifier. The corollary: when an evaluator's internal model changes but its mathematical role is unchanged, the name does not change.

`SkepticEvaluator` evaluates a trading signal from an adversarial skeptic perspective and produces a confidence multiplier. That role is stable across LLM provider changes, prompt rewrites, and architectural improvements. The internal evolution is tracked by `prompt_version` (for LLM iteration) and `model_version` attributes. The class name is the invariant.

### The Model Evolution Protocol

Three cases, three responses:

**Case 1 — Implementation changes, role unchanged.**
Prompt rewrite, LLM provider swap, algorithm improvement. The evaluator still does the same thing mathematically.
→ Increment `prompt_version` or equivalent version attribute. Class name unchanged. No shadow period required unless the change is substantial enough to warrant it.

**Case 2 — New mathematical approach to the same role.**
A different analytical technique for the same question (e.g., Bayesian skeptic evaluation replacing heuristic scoring). The role is the same; the math is fundamentally different.
→ New class on a feature branch, starts in shadow mode (`shadow_only = True`). Old class runs in parallel. When graduation criteria are met, the new class is promoted and the old one is deprecated, then deleted in the next cleanup phase. Both classes use the same name for their role; only one can be the canonical non-shadow instance at a time.

**Case 3 — New mathematical role.**
A genuinely different evaluation perspective that produces a different analytical function — not a better version of the same thing, but a different thing.
→ New class with a new name derived from its new role. The old class continues independently under its original name. These are not versions of each other; they are different evaluators.

**Version numbers in class names are prohibited in all three cases.** `SkepticEvaluatorV2` implies `SkepticEvaluatorV1` exists simultaneously, which means either they serve different mathematical roles (give them different names) or one should be in shadow mode (use `shadow_only`, not a version suffix).

### Shadow Mode Is Runtime State, Not Mathematical Identity

`shadow_only = True` does not create a different type of evaluator. A `SkepticEvaluator` in shadow mode and a `SkepticEvaluator` in production are the same mathematical object in different operational states. The graduation system (`shadow_registry`) manages the boundary. This has two consequences for naming:

1. **No shadow-suffixed class names.** Never `SkepticEvaluatorShadow`. The class was always `SkepticEvaluator`.
2. **Promotion requires no renaming.** When a shadow evaluator is promoted to production, zero code changes to names occur. The `shadow_only` attribute flips; nothing else changes.

The research/production boundary in this system is entirely runtime-governed, not name-governed. This is by design: the mathematical claim encoded in the name — what the evaluator IS — is the same in research and production. Encoding environment in the name would imply the math changes between environments. It does not.

### Retirement Protocol

When a class is replaced and its role is no longer needed:

1. Add a deprecation note at the class level citing the replacement and the target removal date.
2. Run in parallel for one deployment cycle to confirm replacement is stable.
3. Delete the class. No zombie classes, no `_deprecated` suffixes.

If deletion requires updating many callers, that is a sign the class had too many direct dependencies — a modularity problem to fix, not a reason to keep the zombie class.

---

## 6. The Abbreviation Policy

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
| `agent_id` | Metric labels, structlog fields (legacy family) | Operational compatibility — see Section 2 |

### Tier 3 — Never Permitted

Code shortcuts. Use the full word or name by role.

`ctx` → `context` | `cfg` → `config` | `msg` → `message` | `evt` → `event`
`sig` → `signal` | `dep`/`deps` → `dependency`/`dependencies` | `impl` → name by role
`obj` → name by type | `res` → `result` | `req` → `request` | `resp` → `response`
`tmp` → name by what it holds | `err` → `error` | `exc` → `exception`
`fn` → name by role | `num` → `count` or `number` | `idx` → `index`
`buf` → `buffer` | `e` in `except Exception as e` → `error` or `exception`

**Note on `val`:** `val` is Tier 3 when it means "value" (a shortcut). It is Tier 1 when it means value area low (a quant domain code). The distinction is semantic, not syntactic — enforcement is by code review, not grep.

### The Test

Would a practitioner write this on a whiteboard in a mathematics, finance, or computer science seminar and have every peer read it without decoding? If yes — field code, permitted. If no — shortcut, not permitted.

---

## 7. The Ring 0 Portability Contract

### What Ring 0 Exports

Ring 0 publishes a stable public API. Every class exported from `src/core/` is a contract. Other projects depend on it without modification.

```
src/core/
  agent/
    BaseDaemon          daemon lifecycle, Kafka, systemd, OTel, watchdog
    BaseWriter          writer pattern: DLQ, batch, parse contract
    BaseProvider        ingestion pattern: reconnect, gap detection
  ai/
    BaseAIWorker        LLM generation, audit trail, typed output
    BaseSwarmCoordinator  group coordinator for parallel evaluator dispatch
    WorkerContext       frozen execution context for one evaluator run
    LLMAdapter          Pydantic AI Model protocol bridge
    AIWorkerProtocol    protocol interface for AI workers
    Evaluator           abstract: evaluate → scored judgment
    Synthesizer         abstract: synthesize → qualitative output

src/observability/      OTel, metrics, spans, circuit breaker
src/persistence/        generic repository pattern, connection pool
src/monitoring/         CUSUM, KS drift — generic statistical monitors
```

**On `WorkerContext`:** This is the frozen context passed to each evaluator run — holds execution inputs (signal data, LLM chain, DB pool, memory client). `Worker` passes the portability test: any system with worker-pattern execution needs a frozen context object. The former name `AgentContext` is retired with `Agent`.

**On `BaseAIWorker`:** Interim name. The architectural concern — that Ring 1 mathematical objects (`SkepticEvaluator`, `CorrelationAnalyzer`) currently inherit from a daemon base — is real. Separating the evaluator class hierarchy from the daemon hierarchy is Phase 2 architectural work, required before the evaluator pattern is reused in a new project.

### Domain Objects That Belong in Ring 1

These currently live near Ring 0 but carry domain vocabulary:

| Object | Correct location | Reason |
|--------|-----------------|--------|
| `AIContext` | `src/intelligence/context.py` | Trading intelligence state — fails portability test |
| `SignalContext` (rename target) | `src/intelligence/context.py` | Same |
| `AIContextCache` | `src/intelligence/context.py` | Domain cache tied to intelligence tiers |

### Boundary Enforcement

Ring 0 has zero dependencies on outer rings. If any file in `src/core/` imports from `src/intelligence/`, `src/config/`, `src/providers/`, `src/self_healing/`, or `services/`, it is a boundary violation caught in CI.

---

## 8. CI Enforcement

The taxonomy is only durable if violations fail the build. Without enforcement, vocabulary drifts back within months.

**Implementation note:** The grep checks below are advisory pre-checks useful for fast feedback. For durable enforcement, implement an AST-based Python linter using the `ast` module for class name checks and an import graph checker for boundary violations. Grep misses multiline class definitions, dynamically generated classes, and aliased imports. Extract the YAML block in Section 3 into a standalone `taxonomy.yaml` file as the single source of truth for both the AST linter and documentation.

### Check 1 — Retired Mechanism Words

Fail if any class definition contains a retired suffix or word.

```bash
grep -rn "class.*ComputeAgent\b\|class.*\bManager\b\|class.*\bHelper\b\|class.*Utils\b\|class.*\bHandler\b\|class.*\bProcessor\b\|class.*\bAgent\b" \
  src/ services/ --include="*.py"
```

Permitted exceptions:
- `Handler` in `src/api/` (Ring 3, HTTP handlers)
- `Manager` for genuine resource managers (connection pool, thread pool) — requires explicit taxonomy note in the file
- Test files (`test_*.py`) are excluded

### Check 2 — Banned Code Abbreviations in Signatures

Fail if any function definition or variable assignment uses Tier 3 shortcuts.

```bash
grep -rn "\bctx\b\|\bcfg\b\|\bmsg\b\|\bevt\b\|\bdeps\b\|\btmp\b\|\berr\b\|\bexc\b\|\bres\b\|\bsig\b\|\breq\b\|\bresp\b\|\bidx\b\|\bbuf\b\|\bfn\b\|\bobj\b\|\bnum\b" \
  src/ services/ --include="*.py" | grep -v "test_\|#\|\".*\"\|'.*'"
```

Not applied to single-letter mathematical variables in computation functions. The `val` ambiguity requires human review — Check 2 does not flag `val`.

### Check 3 — Ring 0 Boundary Violation

Fail if any Ring 0 file imports from an outer ring.

```bash
grep -rn "from src\.intelligence\|from src\.config\|from src\.providers\|from src\.self_healing\|from services" \
  src/core/ src/observability/ src/persistence/ src/monitoring/ --include="*.py"
```

### Check 4 — Taxonomy Coverage for New Classes

Every new class in `services/` or `src/intelligence/ai/` must either:
- End with a suffix from the `runtime_processes.suffixes` or `mathematical_objects.suffixes` list, or
- Be listed in `runtime_processes.plain_role_nouns`

Implemented as a pre-commit Python script that parses new class definitions, validates against the taxonomy YAML, and checks the plain role noun exemption list before failing.

### Check 5 — Segment Count (Advisory)

Flag — not fail — any class name with four or more independent PascalCase segments. Triggers human review.

```python
import re
def segment_count(name): return len(re.findall(r'[A-Z][a-z0-9]+', name))
# flag if segment_count(class_name) >= 4
```

This is a heuristic for the "three unrelated semantic units" smell. `RegimeCoherenceAnalyzer` has three segments and is fine. Four or more segments is a strong signal that the concept hasn't been named precisely or the object has too many responsibilities.

---

## 9. Pending Renames

The following renames are established by this spec. They represent the delta between the current codebase and the target vocabulary. These are executed in a dedicated rename phase — not incrementally.

### Ring 0 — Infrastructure Base Classes

| Current | Target | Note |
|---------|--------|------|
| `BaseAgent` | `BaseDaemon` | Timeless, portable, passes all three tests |
| `BaseWriterAgent` | `BaseWriter` | Role suffix complete without `Agent` |
| `BaseProviderAgent` | `BaseProvider` | Same |
| `BaseAIAgent` | `BaseAIWorker` | Interim — see Section 7 architectural note |
| `BaseGroupCoordinator` | `BaseSwarmCoordinator` | Names the actual coordination role |
| `AgentContext` | `WorkerContext` | `Agent` retired; `Worker` passes portability test |
| `AgentProtocol` | `AIWorkerProtocol` | Consistent with `BaseAIWorker` prefix |

### Ring 1 — AI Evaluation Layer (I8)

| Current | Target | Category |
|---------|--------|----------|
| `BaseMultiplierAgent` | `Evaluator` (abstract, Ring 0) | Mathematical object |
| `SkepticComputeAgent` | `SkepticEvaluator` | Mathematical object |
| `CorrelationComputeAgent` | `CorrelationAnalyzer` | Mathematical object |
| `CounterfactualComputeAgent` | `CounterfactualEvaluator` | Mathematical object |
| `RegimeCoherenceComputeAgent` | `RegimeCoherenceAnalyzer` | Mathematical object |
| `MLScorerMultiplierAgent` | `MLEvaluator` | Mathematical object |
| `NarrativeComputeAgent` | `NarrativeSynthesizer` | Mathematical object (individual) |
| `AIContext` | `SignalContext` | Context carrier (Ring 1) |
| `AIContextCache` | `SignalContextCache` | Context carrier (Ring 1) |

### Ring 2 — Daemon Processes

| Current | Target | Category |
|---------|--------|----------|
| `IntelligencePipelineComputeAgent` | `IntelligencePipeline` | Plain role noun |
| `AlphaSwarmComputeAgent` | `AlphaSwarm` | Plain role noun |
| `NarrativeGroupComputeAgent` | `NarrativeSwarm` | Plain role noun — group coordinator IS the swarm; distinct from individual `NarrativeSynthesizer` |
| `BarAggregatorComputeAgent` | `BarAggregator` | Aggregator |
| `ProviderMergerComputeAgent` | `ProviderMerger` | Merger |
| `CrossAssetComputeAgent` | `CrossAssetAnalyzer` | Analyzer |
| `MacroComputeAgent` | `MacroAnalyzer` | Analyzer |
| `SignalMetricsComputeAgent` | `SignalMetricsAnalyzer` | Analyzer |
| `GraduationComputeAgent` | `GraduationAnalyzer` | Analyzer |
| `MLDiscoveryComputeAgent` | `MLDiscoveryAnalyzer` | Analyzer — `Discovery` alone fails Check 4; `Analyzer` names the role |
| `SignalTrackerComputeAgent` | `SignalTracker` | Tracker |
| `AlertingComputeAgent` | `AlertMonitor` | Monitor |
| `MLOrchestratorComputeAgent` | `MLOrchestrator` | Orchestrator |
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
| `LLMWriterAgent` | `LLMWriter` | Writer — `llm` is Tier 1 permitted; role is writing LLM call audit records to `llm_calls` |
| `CtxWriterAgent` | `ContextWriter` | Writer — `ctx` is Tier 3; full word required |
| `SwarmLedgerWriterAgent` | `SwarmLedgerWriter` | Writer |
| `SignalMetricsWriterAgent` | `SignalMetricsWriter` | Writer |
| `GraduationWriterAgent` | `GraduationWriter` | Writer |
| `BarAuditorAgent` | `BarAuditor` | Auditor |
| `SignalAuditorAgent` | `SignalAuditor` | Auditor |
| `SignalReplayAuditorAgent` | `SignalReplayAuditor` | Auditor |
| `ServiceAuditorAgent` | `ServiceAuditor` | Auditor |
| `OutboxDispatcherAgent` | `OutboxPublisher` | Publisher — reads DB outbox, emits to Kafka |

### File Names (alongside class renames)

File names follow the class rename. `bar_aggregator_agent.py` → `bar_aggregator.py`. The `_agent` suffix is retired from Ring 2 file names.

### Ring 3 — API and Dashboard

Ring 3 follows surface-specific conventions (REST, TypeScript, systemd) and is not subject to the taxonomy suffix rules. However it must be updated in Wave 4 to reflect Ring 1/2 renames and to fix Tier 3 abbreviations in Python.

**Dashboard — display string updates (`dashboard/src/hooks/use-observability-stream.ts`):**

| Current string | Target string |
|----------------|---------------|
| `"SignalTrackerComputeAgent"` | `"SignalTracker"` |
| `"AlphaSwarmComputeAgent"` | `"AlphaSwarm"` |
| `"CrossAssetComputeAgent"` | `"CrossAssetAnalyzer"` |
| `"GraduationComputeAgent"` | `"GraduationAnalyzer"` |

Also update `agentAge["AlphaSwarmComputeAgent"]` key reference on line 213.

**API — import updates (flow from Ring 1/2 renames):**

| File | Change |
|------|--------|
| `src/api/routes/narrative.py` | Import `NarrativeSynthesizer` (was `NarrativeComputeAgent`) |

**API — Tier 3 abbreviation fixes:**

| File | Current | Target |
|------|---------|--------|
| `src/api/routes/narrative.py:96` | `bar_ctx` | `bar_context` |
| `src/api/routes/narrative.py:107` | `i7_ctx` | `i7_context` |
| `src/api/routes/health.py:94-95` | `resp` | `response` |
| `src/api/routes/drift.py`, `ai_stats.py`, `narrative.py`, `signals.py` | `except Exception as exc:` | `except Exception as error:` |

**TypeScript note:** `SymbolConfigManager` in `dashboard/src/lib/symbol-config.ts` uses `Manager` which is idiomatic TypeScript for this pattern. Ring 3 follows surface-specific conventions — leave unchanged.

### Documentation

`docs/foundation/naming-conventions.md` is superseded by this spec. It will be replaced with a redirect to this document in the rename phase.

---

## 10. What Does Not Change

- **Kafka topic strings** — the current pattern is correct.
- **DB table names** — `signal_ledger`, `intelligence_features`, `llm_calls` stay.
- **DB column quant codes** — `ts`, `tf`, `pnl_r`, `mae`, `mfe` stay.
- **Plugin naming** — `PascalCasePlugin` convention stays.
- **Intelligence tier codes** — `I1`–`I8` stay in code, docs, metrics, and directory names.
- **Ring 0 infrastructure base `Base*` prefix** — `BaseDaemon`, `BaseWriter`, `BaseProvider`, `BaseAIWorker`, `BaseSwarmCoordinator` keep `Base*`; `Agent` is retired from all names.
- **`agent_id` metric label and structlog field** — stays for operational compatibility. See Section 2.
- **Systemd unit names** — updated mechanically when class/file names change, no independent changes.

---

## 11. Migration Guidelines

The rename phase touches every service file, class name, and import in the codebase simultaneously.

**Sequencing decision (2026-05-30):** The rename executes before Phase 095 (Pydantic AI Agent Execution Layer). Phase 095 directly touches the Ring 0 infrastructure being renamed — `BaseAIAgent`, `BaseGroupCoordinator`, `AgentContext` — and introduces new evaluators that must be named correctly from day one. Writing 095 code against old names would compound the debt. The foundation must be correct before anything built on top of it can be trusted.

**Atomic rename:** All renames in Section 9 execute in a single phase on a feature branch. Incremental rename across multiple PRs creates a window where CI checks fail and vocabulary is contradictory. The branch merges only when all checks pass.

**Wave structure within the branch:** Four commits, each verified before the next:
1. Ring 0 base classes (7 renames) — highest leverage; everything inherits from these
2. Ring 1 math objects (9 renames) — self-contained, no service restarts
3. Ring 2 class names (~30 renames) — class names only, no file moves yet
4. File renames + systemd units + import cleanup

**Clean break:** No compatibility aliases, no systemd stub files. All callers are updated in the same branch. This is not a production system with external dependents — a clean atomic rename is correct.

**Metrics and dashboards:** The `agent_id` label exception in Section 2 means no Grafana dashboard changes are required for the core liveness/DLQ/crash metrics. Metric prefixes derived from old class names (e.g., `bar_aggregator_compute_agent_messages_total`) update alongside the class rename in Wave 3.

**Ring boundary violations:** During the rename phase, the Ring 0 boundary check (Check 3) may temporarily fail if `BaseAIAgent`/`BaseAgent` references are being removed from Ring 0. Mark these `# noqa: ring0-boundary` with a tracking comment; remove as part of the phase completion checklist.

---

*This document is the authoritative vocabulary spec for IndicAgent and any project built from this foundation. When the taxonomy grows, update Section 3 and the YAML block. When a new surface is added, add it to Section 4. The spec grows; the principle does not.*
