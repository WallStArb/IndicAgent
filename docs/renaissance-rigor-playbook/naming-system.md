# Naming System

**Status:** template — pattern only, all concrete class/table/directory names are illustrative placeholders
**Source:** genericized from IndicAgent `docs/foundation/naming-system.md`

---

## Purpose

This document is a portable naming-system *method*, not a finished vocabulary. It travels with a new project the same way a shared infrastructure library would: the governing tests, the ring/layer architecture, the taxonomy method, and the surface-derivation table are domain-agnostic. The actual class names, table names, and taxonomy categories are NOT — those must be built fresh for each project, following the method below, not copied from the source project.

The naming system is not a style guide. It is a mathematical specification of what kinds of objects exist in your system, how they are named, and how that naming is mechanically derived and enforced. Every name is a claim about what an object IS. Claims must be true.

---

## 1. Philosophy and Governing Tests

### The Core Principle

**The vocabulary IS the model. The model IS the vocabulary.**

When a domain expert reads a list of class names, they are reading the mathematical architecture. When names describe mechanism instead of role, the code has drifted from the model. Naming cleanup is not cosmetic — it restores the identity between model and code.

### The Invariant

> **A name is correct if and only if a domain expert who has never seen the implementation can correctly predict the object's mathematical role, its inputs, and its output contract from the name alone — without reading any code.**

This is the single criterion. The three governing tests are tools for applying it. When they conflict or leave a case unresolved, return to the invariant.

### Three Governing Tests

**The Whiteboard Test**
Write the name on a whiteboard in front of a domain expert. Would they immediately understand what the object IS? A name like `RiskEvaluator` passes. `RiskComputeAgent` fails. `context` passes. `ctx` fails.

**The Survival Test**
If you replaced the implementation tomorrow — swap the LLM for a neural net, swap the message bus for a different one — would the name still be correct? A name describing role (`BarAggregator`) survives. A name describing mechanism (`BarComputeWorker`) does not.

**The Portability Test** *(Ring 0 only — see §2)*
Could this name be extracted into a shared library and used unchanged in a completely different domain? `BaseDaemon` passes. A name like `TradingContext` fails — it names a domain-specific construct, not an infrastructure one.

### What Fails All Three Tests

- **Mechanism words:** `Compute`, `Process`, `Handle`, `Manage`, `Execute`
- **Unearned role words:** `Agent` on a component that is called, not autonomous
- **`Base*` on domain objects:** `BaseGroupCoordinator` implies a non-base exists. `Evaluator` (abstract) is simply the type.
- **Code abbreviations:** `ctx`, `cfg`, `msg`, `sig`
- **Three unrelated semantic units:** three related words in a compound are fine — the smell is *unrelated* concepts. A CI advisory check should flag four or more PascalCase segments.

---

## 2. The Four Ring Architecture

Every file, class, and module belongs to exactly one ring. Directory names below are illustrative — pick your own, but keep the ring *concept* and the dependency-direction rule.

```
Ring 0  <core infra dirs, e.g. src/core/, src/observability/>
        Portable infrastructure. No domain vocabulary.
        Travels to any new project verbatim.

Ring 1  <domain dirs, e.g. src/domain/, src/config/, src/providers/>
        Domain layer. Project-specific vocabulary is correct here.

Ring 2  <runtime process dir, e.g. services/>
        Runtime processes (daemons). Pure role nouns.
        Location and a shared BaseDaemon inheritance encode "this is a daemon."

Ring 3  <external interface dirs, e.g. src/api/, frontend/>
        External interfaces. Follows surface-specific conventions (REST, GraphQL, etc.)
```

**Outer rings depend on inner rings; inner rings must never depend on outer rings:**

```
Ring 0  →  no imports from Ring 1, 2, or 3
Ring 1  →  imports from Ring 0 only
Ring 2  →  imports from Ring 0 and Ring 1
Ring 3  →  imports from any ring
```

**Note on Ring 1 sub-modules:** Files within Ring 1 directories that contain purely generic patterns with no project-specific vocabulary may be factored into Ring 0 when they genuinely pass the portability test.

### Rings vs. Pipeline Tiers

If your system has a multi-stage processing pipeline (tiers/stages that data flows through), rings and pipeline tiers are orthogonal. Rings describe portability. Tiers describe position in the pipeline.

**File location encodes tier membership; class names do not repeat tier codes.** E.g. `src/domain/features/tier1_indicators/rsi.py` → `RSIPlugin`, not `Tier1RSIPlugin`. Tier is structural metadata encoded in the directory. Exception: when tier membership is the concept itself (an object that manages tier boundaries), the tier code may appear in the name.

If you adopt numbered/coded tiers, maintain a small glossary mapping code → descriptive name → purpose, same shape as this table (illustrative):

| Code | Name | Purpose |
|------|------|---------|
| `T1` | `<tier_1_name>` | `<what this tier computes>` |
| `T2` | `<tier_2_name>` | `<what this tier computes>` |

Delete this table's placeholder rows and fill in your real tiers once they exist — don't leave the source project's tier list in a new project's doc.

### `Base*` Prefix Rule

- Ring 0 infrastructure bases keep `Base*`: e.g. `BaseDaemon`, `BaseWriter`, `BaseProvider`. They are shared implementation foundations.
- Mathematical/domain abstract types drop `Base*`: the abstract class IS the type. `Evaluator`, not `BaseEvaluator`.

### `Agent` Retirement Rule (if your domain uses AI agents)

`Agent` should be retired as a *mechanism word* — when it describes how something works rather than what it IS. `ComputeAgent`, `DataAgent`, `ProcessAgent`, `HelperAgent` all fail because they describe mechanism, not role.

`Agent` is **correct** when the object genuinely IS an autonomous AI agent: an LLM-driven worker that acts on its own judgment to produce a scored output. The test: can you replace "agent" with a more specific mathematical role name (`Evaluator`, `Synthesizer`, `Analyzer`) without losing meaning? If yes — use the specific name. If no — the object IS an agent and `agent` is appropriate.

Drop this section entirely if your project has no AI-agent layer.

---

## 3. The Complete Taxonomy (Method, Not Content)

Two vocabularies is the recommended split. Every object belongs to exactly one category in exactly one vocabulary. **The category names and suffixes below are illustrative starting points from the source project — build your own taxonomy from your own codebase's actual recurring roles, don't copy this list wholesale.**

### Vocabulary A — Mathematical/Domain Objects

Called, not run. No message-bus connection, no daemon loop. Live in Ring 0 or Ring 1. Abstract types are the type itself — no `Base*` prefix.

| Category | Mathematical role | Output contract | Example (illustrative) |
|----------|-----------------|-----------------|---------|
| `Evaluator` | Evaluates from a specific perspective, produces a scored judgment | Score or qualitative judgment | `RiskEvaluator` |
| `Analyzer` | Performs structured analytical computation | Structured typed result | `CorrelationAnalyzer` |
| `Synthesizer` | Combines multiple signals into qualitative synthesis | Narrative or annotation | `SummarySynthesizer` |
| `Detector` | Detects presence or absence of a pattern or condition | Boolean or classified signal | `AnomalyDetector` |
| `Classifier` | Assigns inputs to mutually exclusive categories | Enumerated category | `SessionClassifier` |
| `Aggregator` | Combines multiple numerical inputs into a unified measure | Scalar or vector | `ScoreAggregator` |

### Vocabulary B — Runtime Processes

Run autonomously. Have a daemon loop, process-manager unit, message-bus subscription, or timer trigger. Live in Ring 2. A shared `BaseDaemon` inheritance and the `services/`-style location encode daemon nature; the name encodes role only.

| Category | Role | I/O | Example (illustrative) |
|----------|------|-----|---------|
| `Provider` | Ingests from external source → stream | External → message bus | `MarketDataProvider` |
| `Merger` | Combines multiple streams into one | bus × N → bus | `SourceMerger` |
| `Aggregator` | Aggregates streaming data into higher-level events | bus → bus | `EventAggregator` |
| `Analyzer` | Computes analytical metrics as a daemon | bus / timer → bus | `MetricsAnalyzer` |
| `Writer` | Persists from stream to storage | bus → DB | `RecordWriter` |
| `Tracker` | Manages business object state over time | bus → state + bus | `SessionTracker` |
| `Auditor` | Validates data integrity, self-heals | DB → corrections | `DataAuditor` |
| `Monitor` | Watches conditions, dispatches alerts | bus / DB → alerts | `AlertMonitor` |
| `Orchestrator` | Coordinates multi-step batch workflows | timer → jobs | `BatchOrchestrator` |
| `Trainer` | Executes model training | data → model artifact | `ModelTrainer` |
| `Publisher` | Reads from DB/outbox and emits to stream | DB → bus | `OutboxPublisher` |

### Disambiguating Shared Suffixes

`Aggregator` and `Analyzer` appear in both vocabularies. **Ring determines vocabulary.** A class in Ring 0/1 is a mathematical object — called, stateless. A class in Ring 2 is a daemon — autonomous, owns a lifecycle. Shared `BaseDaemon` inheritance is the mechanical boundary.

### Plain Role Nouns (Ring 2 exemption)

Some Ring 2 daemons are the concept itself — no category suffix adds precision. List these explicitly and exempt them from the taxonomy suffix requirement as your project discovers them. Don't pre-populate this table with the source project's names (`AlphaEngine`, `AlphaSwarm`, etc.) — start empty and add only when a real daemon in your codebase earns a plain-noun exemption.

New plain role nouns require explicit addition to this table. The anti-creep rule applies (see Taxonomy Governance below).

### The Composability Principle

A composition earns its own name when it has a **stable mathematical identity that outlives its current members**: if members can be replaced without changing what the composition IS, the name is correct.

Rules:
1. **Name by role, never by members.** A group of evaluators is named for what the group does, not by concatenating the members' names.
2. **A composition that IS its pipeline does not earn a separate name.**
3. **Coordinators name separately from members.** A Ring 2 daemon that coordinates a group is distinct from the Ring 1 mathematical objects it coordinates.

### Taxonomy Governance

**Anti-creep rule:** A new category requires at least two distinct existing objects that share the same mathematical role and fit no current category. One object maps to the nearest existing category.

**Governance:** Taxonomy additions require the proposer to demonstrate the three governing tests pass and the anti-creep rule is satisfied, reviewed by at least one engineer with domain knowledge. The spec is the decision framework — not a vote.

### Machine-Readable Taxonomy Block (Template)

```yaml
taxonomy:
  mathematical_objects:
    suffixes: []   # fill in as your project defines its Vocabulary A categories
    rings: [0, 1]
    no_base_prefix: true
  runtime_processes:
    suffixes: []   # fill in as your project defines its Vocabulary B categories
    plain_role_nouns: []   # fill in as plain-noun exemptions are earned
    rings: [2]
    inherits: BaseDaemon
  infrastructure_bases:
    classes: []   # e.g. BaseDaemon, BaseWriter, BaseProvider
    rings: [0, 1]
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
    words: [Compute, Handler, Helper, Util, Utils, Manager, Processor]
    note: >
      Start this list empty and add words as you catch yourself reaching for a
      mechanism word instead of a role word. Don't pre-populate with the source
      project's retirement list — your project's temptations will differ.
```

---

## 4. The Surfaces — Mechanical Derivation

One concept name should mechanically derive all surface names. No judgment calls, no lookup tables. The surfaces below are the ones the source project needed; add or drop surfaces to match your own stack (e.g. drop "Kafka Topics" if you don't use a message bus; add "GraphQL Resolvers" if you use GraphQL instead of REST).

### Surface 1 — Classes

| Object type | Pattern | Example (illustrative) |
|------------|---------|---------|
| Ring 2 daemon | `PascalCase(concept)` + category suffix | `SessionTracker`, `EventAggregator` |
| Ring 2 daemon (plain role noun) | `PascalCase(concept)` — no suffix | (project-specific, earned not assumed) |
| Ring 1 mathematical object | `PascalCase(concept)` + category suffix | `RiskEvaluator` |
| Ring 0/1 abstract math type | Category suffix alone | `Evaluator`, `Synthesizer` |
| Ring 0 infrastructure base | `Base` + `PascalCase(role)` | `BaseDaemon`, `BaseWriter` |
| Behavioral mixin | `PascalCase(capability)` + `Mixin` | `RetryMixin` |
| Enumeration | `PascalCase` singular noun | `SessionStatus` |
| Component config | `PascalCase(concept)` + `Config` | `EvaluatorConfig` |
| Plugin | `PascalCase(concept)` + `Plugin` | `RSIPlugin` |
| Protocol/interface | `PascalCase(concept)` + `Protocol` | `WorkerProtocol` |
| Result / output model | `PascalCase(concept)` + `Result` | `EvaluationResult` |
| Context carrier | `PascalCase(concept)` + `Context` | `RequestContext` |
| Repository | `PascalCase(concept)` + `Repository` | `SessionRepository` |
| Error | `PascalCase(concept)` + `Error` | `ValidationError` |

**Mixins:** Provide behavioral capability through methods. No persistent state of their own — if state is needed, the capability belongs in a base class, not a mixin. Same ring as the domain they serve.

**Enumerations:** Members are `UPPER_SNAKE_CASE`. Type name is singular. Same ring as the domain they describe.

**Component config:** A component gets its own `*Config` only when configuration is meaningfully distinct from a global settings object and must be passed explicitly (tests, parameterized instantiation, reuse across contexts). Components that read directly from global settings at construction do not get a `*Config`.

### Surface 2 — File Names

File location encodes both ring and pipeline tier (if you have tiers). File name encodes the concept only.

| Object type | Pattern | Example (illustrative) |
|------------|---------|---------|
| Ring 2 daemon | `services/<concept>.py` | `services/session_tracker.py` |
| Ring 1 domain | `src/domain/<module>/<concept>.py` | `src/domain/context.py` |
| Ring 0 infrastructure | `src/core/<module>/<concept>.py` | `src/core/ai/evaluator.py` |
| Plugin (tiered) | `src/domain/features/tier<N>_<tier_name>/<concept>.py` | `src/domain/features/tier1_indicators/rsi.py` |

The tier subdirectory (if any) encodes tier membership. File names do not repeat the tier.

### Surface 3 — Message Bus Topics (if applicable)

| Layer | Pattern | Example (illustrative) |
|-------|---------|---------|
| Topic function | `topic_<concept>()` in a central stream-keys module | `topic_session_tracker()` |
| Topic string | `<env>.<domain>[.<sublayer>]` — dots only, never colons | `prod.sessions.tracker` |
| Consumer group | `<concept>_consumer` | `session_tracker_consumer` |

### Surface 4 — Database Tables and Columns

| Object | Pattern | Example (illustrative) |
|--------|---------|---------|
| Table | `snake_case` stable relation name | `session_ledger` |
| View | `<source_table>_<qualifier>` | `session_ledger_full` |
| Migration | `NNN_description.sql` | `095_session_ledger_split.sql` |
| Timestamp column | Pick one convention and hold it everywhere | `ts` or `timestamp` — decide once, project-wide |
| All other columns | Full `snake_case` noun phrase | `exit_reason`, `pnl_r` |

Table naming uses stable relation names, not strictly grammatical pluralization. Once an event-store or ledger table convention is established, keep it — don't rename mid-project.

### Surface 5 — Variables, Arguments, and Labels

| Surface | Rule | Example |
|---------|------|---------|
| Function arguments | Full descriptive name | `context`, `session_id` |
| Local variables | Full descriptive name | `session_context`, `audit_result` |
| Log field names | Full descriptive name | `daemon_id`, `symbol`, `failure_reason` |
| Metric labels | Full descriptive name (pick a convention and keep it stable — renaming a label breaks existing dashboards) | `symbol`, `job` |
| Enum members | `UPPER_SNAKE_CASE` | `PENDING`, `ACTIVE` |
| Mathematical variables in formulas | Single-letter mathematical convention | `n`, `x`, `y`, `i`, `j`, `t`, `p`, `r` |

### The Mechanical Derivation Table (Template)

Given a concept, e.g. `session_tracker`:

| Surface | Result |
|---------|--------|
| Daemon class | `SessionTracker` |
| File name | `services/session_tracker.py` |
| Process-manager unit | `<project>-session-tracker.service` |
| Topic function | `topic_session_tracker()` |
| Topic string | `prod.sessions.tracker` |
| DB table | `session_trackers` |
| Log file | `logs/session_tracker.log` |
| Metric prefix | `session_tracker_` |
| Variable name | `session_tracker` |

### Surface 6 — REST API Routes (Ring 3)

Endpoint naming follows REST resource conventions (Microsoft REST API Guidelines / Google API Design Guide) — the path names a resource, the HTTP method supplies the verb.

| Element | Pattern | Example |
|---------|---------|---------|
| Collection resource path | Plural noun, no verb | `/sessions`, `/instruments` |
| Instance resource path | `/<collection>/{<snake_case_id>}` | `/sessions/{session_id}` |
| Multi-word path segment | `kebab-case` | `/market-data/{symbol}` |
| Router file | `src/api/routes/<resource_plural_snake_case>.py`, one router per file | `sessions.py` |
| Route handler function | `<crud_verb>_<resource>`: `list_`, `get_`, `create_`, `update_`, `delete_` | `list_sessions`, `get_session` |
| Query parameter | `snake_case`; alias only for an external-spec-mandated name or a reserved-keyword collision | `symbol`, `timeframe` |
| Request/response model | `<Concept>Request` / `<Concept>Response` | `SessionResponse` |

**HTTP method → action mapping (no exceptions):** `GET` reads, `POST` creates, `PUT` replaces, `DELETE` removes. A verb never appears in the path itself.

### Surface 7 — Functions and Methods

PEP 8 / your language's style guide baseline (verb or verb phrase), sharpened with a role-prefix vocabulary.

| Role | Prefix | Example |
|------|--------|---------|
| Boolean predicate | `is_`, `has_`, `should_` | `is_connected`, `has_alpha` |
| Factory / constructor function | `make_` or `create_` — pick one convention project-wide, don't mix arbitrarily | `make_worker_pool` |
| Simple accessor (no meaningful computation) | `get_` | `get_active_contracts` |
| Derived / computed value (real computation, may be expensive) | `compute_` or `calculate_` | `compute_quality_weight` |
| Module-private helper | leading `_` + full descriptive name | `_build_obs_matrix` |
| Public function | no leading underscore | `format_iso_ts` |
| Test function | `test_<unit_under_test>_<expected_behavior>` | `test_label_map_assigns_active_to_highest_score` |

**The `get_`/`compute_` distinction matters:** a `get_` function's cost and behavior must survive any internal reimplementation unnoticed by the caller — the same contract as a plain attribute access. A `compute_`/`calculate_` function is allowed to be expensive, and its name is a signal to the caller not to invoke it in a hot loop.

**Abbreviation floor:** single- or double-letter function names are prohibited outside the mathematical-variable exception in Surface 5.

### Surface 8 — Module-Level Constants

| Visibility | Pattern | Example |
|-----------|---------|---------|
| Public (imported by other modules) | `UPPER_SNAKE_CASE`, no leading underscore | `DEFAULT_TIMEFRAMES` |
| Private (module-internal only) | `_UPPER_SNAKE_CASE`, leading underscore | `_JOB`, `_MIN_OBS_FACTOR_DEFAULT` |
| Enum members | `UPPER_SNAKE_CASE` (Surface 5, unchanged) | `PENDING` |

**A hardcoded numeric constant on this surface is presumptively an APR violation, not a naming question.** See [adaptive-parameter-registry.md](adaptive-parameter-registry.md) for what may legitimately stay a constant (structural values, label strings, statistical-definition numbers per §7's rule below).

---

## 5. Model Identity and Evolution

### Names Encode Role, Not Version

A class name is a claim about mathematical role. When an evaluator's internal model changes but its role is unchanged, the name does not change. Internal evolution is tracked by a version attribute (e.g. `prompt_version`), not by a suffix on the class name.

### The Model Evolution Protocol

| Case | Description | Response |
|------|-------------|----------|
| Implementation changes, role unchanged | Prompt rewrite, provider swap, algorithm improvement | Increment the version attribute. Class name unchanged. |
| New mathematical approach to the same role | Different technique, same analytical question | New class starts in shadow mode. Old class runs in parallel. When graduation criteria are met, new class promoted, old deprecated then deleted. |
| New mathematical role | Genuinely different evaluation perspective, different output contract | New class with a new name derived from its new role. Old class continues independently. |

**Version numbers in class names are prohibited in all three cases.** `EvaluatorV2` implies `V1` exists simultaneously — either they serve different roles (give them different names) or one is in shadow mode (use a `shadow_only` flag, not a version suffix).

### Shadow Mode Is Runtime State, Not Mathematical Identity

A `shadow_only = True` flag does not create a different type of object. An evaluator in shadow mode and one in production are the same mathematical object in different operational states.

Consequences:
- No shadow-suffixed class names — never `RiskEvaluatorShadow`
- Promotion requires no renaming — the flag flips, nothing else changes

### Retirement Protocol

When a class is replaced:
1. Add a deprecation note citing the replacement and target removal date.
2. Run in parallel for one deployment cycle to confirm stability.
3. Delete the class. No zombie classes, no `_deprecated` suffixes.

---

## 6. The Abbreviation Policy

### Tier 1 — Always Permitted

Standard abbreviations for your domain's field(s), computer science, and mathematics. The source project's list (quantitative finance + stats + CS) is below as an example of the *shape* this list should take — build your own from your own domain.

**Example — quantitative finance:**
`pnl` `ts` `tf` `vol` `vix` `beta` `alpha` `sharpe` `drawdown` `ohlcv` `vwap` `rsi` `ema` `sma` `atr`

**Example — statistics and mathematics:**
`std` `corr` `cov` `mse` `rmse` `aic` `bic` `hmm` `pdf` `cdf`

**Mathematical variables in computation (always permitted, any domain):**
`n` `x` `y` `i` `j` `k` `t` `p` `r`

**Computer science (always permitted, any domain):**
`id` `url` `api` `db` `io` `sql` `json` `xml` `http` `https` `uuid` `cli` `llm` `gpu` `cpu` `rpc` `jwt` `ssl` `tls` `dns`

### Tier 2 — Specific Surfaces Only

Domain codes that are fine in topic strings/metric labels but shouldn't leak into class names — build your own table as these arise.

### Tier 3 — Never Permitted

`ctx` → `context` | `cfg` → `config` | `msg` → `message` | `evt` → `event`
`sig` → `signal` | `dep`/`deps` → `dependency`/`dependencies` | `impl` → name by role
`obj` → name by type | `res` → `result` | `req` → `request` | `resp` → `response`
`tmp` → name by what it holds | `err` → `error` | `exc` → `exception`
`fn` → name by role | `num` → `count` or `number` | `idx` → `index`
`buf` → `buffer` | `e` in `except Exception as e` → `error` or `exception`

### The Test

Would a practitioner write this on a whiteboard in a seminar for your domain and have every peer read it without decoding? If yes — permitted. If no — not permitted.

---

## 7. Gradient Scale Vocabulary

When a column name, APR key, or variable name contains a scale qualifier — a word describing where on a spectrum the value falls — only terms from a canonical table are permitted. Adding a new gradient term requires updating that table first.

### Canonical Terms — Generic Scales (adopt as-is; domain-agnostic)

| Scale | Approved terms | Typical use |
|-------|---------------|-------------|
| Speed / horizon (2-level) | `fast`, `slow` | Two-tier lookback windows |
| Speed / horizon (3-level) | `fast`, `mid`, `slow` | Three-tier lookback windows |
| Speed / horizon (4-level) | `fast`, `mid`, `slow`, `extended` | Four-tier lookback windows |
| Magnitude / intensity | `low`, `mid`, `high` | Threshold tiers, confidence bands |
| Rank / quality | `primary`, `secondary` | Tiers, confirmation layers |

### Canonical Terms — Domain-Specific Scales (build your own table)

A quantity being tiered may use its own field-standard vocabulary instead of a generic scale when the terms meet the **same bar as the Abbreviation Policy**: universally recognized, whiteboard-testable terminology for your field — not frequency of reuse within this codebase. A term used exactly once still qualifies if it is standard field vocabulary a domain practitioner would recognize unprompted. Each domain-specific scale requires its own row, added deliberately — never invented ad hoc inside a single module docstring.

Example row shape (illustrative, from the source project's finance domain):

| Scale | Approved terms | Typical use | Why domain-specific, not generic |
|-------|---------------|-------------|-----------------------------------|
| Volatility state | `calm`, `elevated`, `turbulent` | Vol-regime tiers | Standard vol-desk terminology; the field already has established language for this exact tiering rather than a generic magnitude label |

A quantity that is structurally a magnitude tier (a continuous score threshold-bucketed) but has **no established field-specific naming convention** must use the generic Magnitude/Intensity scale (`low`/`mid`/`high`), not an invented term. Domain-specific status is earned by the term already being standard usage in the field.

### Rule

Only terms from your canonical tables may appear as scale qualifiers in column names, APR keys, and variable names. Numbers in names are valid **only** when the number defines the statistical concept — e.g. `momentum_z_5` means "5-period z-score"; changing it to 7 produces a different statistic, not a recalibrated version of the same one. When the number is a tunable calibration parameter, use a gradient term instead: a `return_fast` column paired with an APR key like `feature.lookahead.fast = 1`. See [adaptive-parameter-registry.md](adaptive-parameter-registry.md) for the full pattern.

**Prohibited:** inventing terms outside your canonical tables. If a new gradient term is genuinely needed — generic or domain-specific — update the table first; it is the single source of truth.

---

## 8. The Ring 0 Portability Contract

### What Ring 0 Exports (Template)

```
src/core/
  agent/
    BaseDaemon             daemon lifecycle, message-bus wiring, process-manager integration, health signals
    BaseWriter              writer pattern: DLQ, batch, parse contract
    BaseProvider             ingestion pattern: reconnect, gap detection
  <other Ring 0 infra as your project needs it>

src/observability/         metrics, spans, tracing
src/persistence/           generic repository pattern, connection pool
src/monitoring/            statistical drift monitors, if applicable
```

Fill this in with your own real Ring 0 exports as they're built — don't copy the source project's list of class names, since they name IndicAgent-specific infrastructure.

### Boundary Enforcement

Ring 0 has zero dependencies on outer rings. Any file in a Ring 0 directory importing from a Ring 1, 2, or 3 module is a boundary violation, caught in CI.

---

## 9. CI Enforcement

The taxonomy is only durable if violations fail the build.

**Implementation approach:** grep checks are advisory pre-checks, cheap to add on day one. For durable enforcement, implement an AST-based linter for class-name checks and an import-graph checker for boundary violations. Extract your taxonomy into a standalone `taxonomy.yaml` as the single source of truth for both — don't let the doc and the enforcement script drift.

### Check 1 — Retired Mechanism Words

```bash
grep -rn "class.*\bManager\b\|class.*\bHelper\b\|class.*Utils\b\|class.*\bHandler\b\|class.*\bProcessor\b" \
  src/ services/ --include="*.py"
```

Adjust the retired-word list to match your own project's Section 3 YAML block.

### Check 2 — Banned Code Abbreviations

```bash
grep -rn "\bctx\b\|\bcfg\b\|\bmsg\b\|\bevt\b\|\bdeps\b\|\btmp\b\|\berr\b\|\bexc\b\|\bres\b\|\bsig\b\|\breq\b\|\bresp\b\|\bidx\b\|\bbuf\b\|\bfn\b\|\bobj\b\|\bnum\b" \
  src/ services/ --include="*.py" | grep -v "test_\|#\|\".*\"\|'.*'"
```

Not applied to single-letter mathematical variables.

### Check 3 — Ring 0 Boundary Violation

```bash
grep -rn "from src\.<ring1_module>\|from services" \
  src/core/ src/observability/ src/persistence/ --include="*.py"
```

### Check 4 — Taxonomy Coverage for New Classes

Every new class in `services/` or your domain-object directories must end with a suffix from your taxonomy's category list, or be explicitly listed as a plain role noun. Implement as a pre-commit script once your taxonomy is populated.

### Check 5 — Segment Count (Advisory)

```python
import re
def segment_count(name): return len(re.findall(r'[A-Z][a-z0-9]+', name))
# flag if segment_count(class_name) >= 4
```

Four or more segments is a strong signal the concept hasn't been named precisely or the object has too many responsibilities.

---

## 10. Stable Conventions

These do not change as part of any rename or refactor, once established. Fill in your own project's list here as conventions get established — don't leave this section pointing at the source project's specific choices.

- **Message bus topic strings** — once a pattern is chosen, it stays
- **DB table names** — established event-store/ledger tables stay
- **DB column codes** — once a shorthand (`ts`, `tf`, etc.) is adopted project-wide, it stays
- **Plugin naming** — once established, stays
- **Ring 0/1 `Base*` prefix** — established infrastructure base classes keep `Base*`
- **Process-manager unit names** — updated mechanically when class/file names change, never independently

---

## 11. Operational Files — Non-Code File Categories

These are the non-code file categories that appear at the project root and in supporting directories. Each should have a single canonical location and a deletion rule.

### The Renaissance Deletion Principle

> **A file with no permanent operational use is deleted the day its job is complete. Git history is the archive. There are no archive folders.**

An `archive/` subdirectory signals uncertainty about whether work is truly finished. That uncertainty is noise. Delete the file; the commit that removed it records what it was and why.

### Migration Files

| Location | Rule |
|----------|------|
| `<migrations_dir>/NNN_description.sql` | Canonical home for all migrations. Numbered sequentially. Applied once; never modified after apply. |

**Naming:** `NNN_description.sql` where `NNN` is globally unique. Duplicate numbers are a violation — they are the artifact of parallel development without coordination and must be resolved.

### Operational Tools — `tools/`

Permanent utilities used on a recurring basis to operate, validate, or analyze the live system.

| Pattern | Rule |
|---------|------|
| `<concept>_<verb>.py` | Validates a live component against a baseline |
| `<concept>_<noun>.py` | Applies a quantitative decision rule |
| `check_<concept>.py` | Diagnostic or integrity check |
| `compute_<concept>.py` | Computes a baseline or reference value |

A tool belongs in `tools/` only if it will be run again. If it answers a one-time question, it is deleted after use — not committed. If it was already committed, delete it in the next cleanup pass.

`tools/` has no subdirectories. A `tools/archive/` is a signal that the directory is being used as a graveyard.

### Operational Scripts — `scripts/`

Long-running or periodic operational scripts that are part of the deployed system — backfills, replays, batch jobs. These are not tools; they are part of the production workflow.

| Pattern | Example shape |
|---------|--------|
| `<verb>_<concept>.py` | `run_historical_pipeline.py` |
| `<concept>_<verb>.sh` | `db_setup.sh` |

One-off scripts used during a phase (data migrations, schema repairs, investigation queries) are deleted when the phase closes. They are not committed unless they are part of a repeatable production operation.

`scripts/archive/` is prohibited. Delete, don't archive.

### Schema Reference Files

Monolithic schema snapshots are an anti-pattern once a migration sequence exists. The migrations ARE the schema. A snapshot that is not continuously maintained diverges from reality and becomes noise.

**Rule:** No schema snapshot files. The current schema is reconstructed by applying all migrations in sequence. If a snapshot is needed for onboarding, generate it from the live database — do not commit a hand-maintained copy.

### Process-Manager Unit Files

Every service/timer unit file corresponds to a deployed or deployment-ready service. A unit file for a service that has been permanently abandoned is deleted immediately — not commented out, not renamed with `.disabled`.

A unit file for a service that is implemented but not yet installed is legitimate — it is the deployment artifact waiting for the install step. The distinction: **planned vs. abandoned**. Planned services have a live implementation in `services/`. Abandoned services have neither a live implementation nor a plan that will deploy them.

---

## Adopting This in a New Project

1. **Copy the method sections verbatim:** §1 (governing tests), §5 (model identity/evolution protocol), §6's Tier 3 list and "the test," §7's rule and generic-scale table, §9's enforcement approach, §11's deletion principle and operational-file rules. These are fully domain-agnostic.
2. **Rebuild the content sections from scratch, following the method:** §2's ring directory names, §3's taxonomy categories and suffixes, §4's concrete examples, §6's Tier 1/2 domain abbreviation lists, §7's domain-specific scale table, §8's Ring 0 export list, §10's stable-conventions list. Populate these only as real classes/tables/conventions accumulate in your actual codebase — an empty table with "fill in as you go" is more honest than a copy-pasted IndicAgent example dressed up as a placeholder.
3. Do this genuinely early — the source project's own naming-system doc describes a 2026-05/06 rename phase that happened *after* the codebase had drifted; a new project that adopts this method from commit one never needs that painful pass.

*When the taxonomy grows, update Section 3 and its YAML block. When a new surface is added, update Section 4. The spec grows; the principle does not.*
