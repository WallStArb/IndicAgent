# Naming Conventions

**Version:** 1.2
**Status:** current
**Last Updated:** 2026-09-04 (cross-checked against naming-system.md's same-day refresh: fixed the Mechanical Derivation Table and Systemd Units example, which still showed a `signal_tracker`-owned topic/table/systemd-unit that never existed in code; fixed `BaseSwarmCoordinator` → `BaseGroupCoordinator` in What Does Not Change, the same stale name naming-system.md itself had already flagged and corrected; fixed two stale file-path examples; healed a table-structure break where the v3.0 AlphaEngine Components section had been inserted mid-table, splitting the Python Classes table in two; deduplicated a repeated table row; fixed a Gradient Scale Qualifiers contradiction with naming-system.md's `tight`/`wide` domain-specific-scale exception. Prior: 2026-08-10, added REST API Routes; moved/expanded Functions and Constants into their own sections matching new canonical Surfaces 7-8; renumbered Operational Files 6→9)

Quick-lookup reference for naming on every surface. All claims derive from the canonical spec.
<!-- src: docs/foundation/naming-system.md -->

For the full spec — governing tests, taxonomy governance, ring architecture, abbreviation rationale, rename protocol, model evolution — see `docs/foundation/naming-system.md`.

---

## Python Classes

<!-- src: docs/foundation/naming-system.md §4 Surface 1 -->

| Object type | Pattern | Example |
|------------|---------|---------|
| Ring 2 daemon | `PascalCase(concept)` + category suffix | `SignalTracker`, `BarAggregator` |
| Ring 2 daemon (plain role noun) | `PascalCase(concept)` — no suffix | `IntelligencePipeline`, `AlphaSwarm`, `NarrativeSwarm`, `AlphaEngine`, `PrecedentEngine`, `ICEngine` |
| Ring 1 mathematical object | `PascalCase(concept)` + category suffix | `SkepticEvaluator`, `CorrelationAnalyzer`, `FeatureFactory`, `FeatureCache` |
| Ring 0/1 abstract type | Category suffix alone | `Evaluator`, `Synthesizer` |
| Ring 0 infrastructure base | `Base` + `PascalCase(role)` | `BaseDaemon`, `BaseWriter`, `BaseBatch` |
| Behavioral mixin | `PascalCase(capability)` + `Mixin` | `IncrementalMixin`, `ConfigConsumerMixin` |
| Enumeration | `PascalCase` singular noun — no suffix | `MarketRegime`, `SignalStatus` |
| Component config | `PascalCase(concept)` + `Config` | `EvaluatorConfig`, `PipelineConfig` |
| Plugin | `PascalCase(concept)` + `Plugin` | `ADXPlugin`, `VWAPPlugin` |
| Protocol | `PascalCase(concept)` + `Protocol` | `AIWorkerProtocol` |
| Result / output model | `PascalCase(concept)` + `Result` | `SkepticResult`, `SignalMetricsResult` |
| Context carrier | `PascalCase(concept)` + `Context` | `SignalContext`, `WorkerContext` |
| Repository | `PascalCase(concept)` + `Repository` | `SignalLedgerRepository` |
| Error | `PascalCase(concept)` + `Error` | `ConfigValidationError`, `CircuitOpenError` |

**Taxonomy suffixes — mathematical objects (Ring 0/1):** `Evaluator`, `Analyzer`, `Synthesizer`, `Detector`, `Classifier`, `Aggregator`
<!-- src: docs/foundation/naming-system.md §3 Vocabulary A -->

**Taxonomy suffixes — runtime processes (Ring 2):** `Provider`, `Merger`, `Aggregator`, `Analyzer`, `Writer`, `Tracker`, `Auditor`, `Monitor`, `Orchestrator`, `Trainer`, `Publisher`
<!-- src: docs/foundation/naming-system.md §3 Vocabulary B -->

**Retired — never use:** `ComputeAgent`, `MultiplierAgent`, `GroupService`, `Agent`, and mechanism words `Compute`, `Handler`, `Helper`, `Util`, `Utils`, `Manager`, `Processor`
<!-- src: docs/foundation/naming-system.md §3 taxonomy YAML retired block -->

---

## v3.0 AlphaEngine Components

**Quick reference for v3.0 naming patterns:**

| Component | Ring | Pattern | Location | Naming Rationale |
|----------|------|---------|----------|-------------------|
| `FeatureFactory` | 1 | `PascalCase(concept)` — no suffix | `src/intelligence/feature_factory.py` | Pure function library, no daemon loop |
| `FeatureCache` | 1 | `PascalCase(concept)` | `src/intelligence/feature_cache.py` | State container, not autonomous |
| `ICEngine` | 2 | `PascalCase(concept)` + `Engine` | `services/ic_engine.py` | Batch compute service, autonomous |
| `AlphaEngine` | 2 (plain role noun) | `PascalCase(concept)` | Architecture concept (not a class) | The overall IC + ensemble system, entirety of v3.0 Layer 1 (Prediction) |
| `BaseBatch` | 0 | `Base` + `PascalCase(role)` | `src/core/agent/base_batch.py` | Infrastructure base for batch services |
| `AlphaEventEmitter` | 2 | `PascalCase(concept)` + `Emitter` | `services/alpha_event_emitter.py` | Future Phase C daemon — not yet built |

**v3.0 naming philosophy:** No "plugins" (v2.x term), no "signals" (v2.x term). Features are mathematical functions, services are autonomous daemons.

---

## File Names

<!-- src: docs/foundation/naming-system.md §4 Surface 2 -->

| Object type | Pattern | Example |
|------------|---------|---------|
| Ring 2 daemon | `services/<concept>.py` | `services/signal_tracker.py` |
| Ring 1 AI evaluator | `src/intelligence/ai/<group>/<concept>.py` | `src/intelligence/ai/alpha/skeptic_agent.py` |
| Ring 1 domain | `src/intelligence/<module>/<concept>.py` | `src/intelligence/ai/context.py` |
| Ring 0 infrastructure | `src/core/<module>/<concept>.py` | `src/core/ai/evaluator.py` |
| Plugin (I1–I5) | `src/intelligence/features/i<N>_<tier_name>/<concept>.py` | `src/intelligence/features/i1_indicators/rsi.py` |

The `_agent` file suffix is retired alongside `Agent` class names.

---

## Kafka Topics

<!-- src: docs/foundation/naming-system.md §4 Surface 3 -->

Topics use **dots only** — never colons.

| Layer | Pattern | Example |
|-------|---------|---------|
| Topic function | `topic_<concept>()` in `stream_keys.py` | `topic_signal_tracker()` |
| Topic string | `<env>.<domain>[.<sublayer>]` | `prod.signals.tracker` |
| Consumer group | `<concept>_consumer` | `signal_tracker_consumer` |

Always constructed via `src/core/stream_keys.py` — never inline f-strings.
<!-- src: src/core/stream_keys.py -->

---

## Database

<!-- src: docs/foundation/naming-system.md §4 Surface 4 -->

| Object | Pattern | Example |
|--------|---------|---------|
| Table | `snake_case` stable relation name | `signal_ledger`, `intelligence_features` |
| View | `<source_table>_<qualifier>` | `signal_ledger_full`, `ohlcv_15m` |
| Migration | `NNN_description.sql` | `095_signal_ledger_split.sql` |
| Timestamp column | Always `ts` | `ts` |
| Timeframe column | Always `tf` | `tf` |
| All other columns | Full `snake_case` noun phrase | `exit_reason`, `pnl_r`, `failure_probability` |
| Index | `idx_<table>_<cols>` | `idx_signal_ledger_symbol_ts` |

---

## REST API Routes

<!-- src: docs/foundation/naming-system.md §4 Surface 6 -->

| Element | Pattern | Example |
|---------|---------|---------|
| Collection path | Plural noun, no verb | `/instruments`, `/signals` |
| Instance path | `/<collection>/{<snake_case_id>}` | `/instruments/{symbol}` |
| Multi-word path segment | `kebab-case` | `/market-data/{symbol}`, `/signals/edge-series` |
| Router file | `src/api/routes/<resource_plural>.py`, one `APIRouter()` per file | `signals.py` |
| Handler function | `<crud_verb>_<resource>`: `list_`/`get_`/`create_`/`update_`/`delete_` | `list_instruments`, `get_instrument` |
| Query parameter | `snake_case`; `alias=` only for external-spec or reserved-word collisions | `alias="lastEventId"`, `alias="from"` |
| Request/response model | `<Concept>Request` / `<Concept>Response` | `NarrativeResponse` |

HTTP method IS the verb (`GET`/`POST`/`PUT`/`DELETE`) — never repeat it in the path. Every router
mounts under `/api` except `health.router`, which mounts bare at `/health`.

---

## Functions and Methods

<!-- src: docs/foundation/naming-system.md §4 Surface 7 -->

| Role | Prefix | Example |
|------|--------|---------|
| Boolean predicate | `is_`, `has_`, `should_` | `is_connected`, `should_skip_plugin` |
| Factory | `make_` or `create_` (both in use, no preference between them) | `make_signal_id`, `create_pool` |
| Simple accessor | `get_` | `get_active_contracts` |
| Computed/derived value | `compute_` or `calculate_` | `compute_quality_weight` |
| Module-private helper | `_` + full descriptive `snake_case` | `_build_obs_matrix` |
| Test function | `test_<unit>_<expected_behavior>` | `test_compute_next_returns_macd_when_warmed_up` |

Single/double-letter function names are prohibited (`_f`, `_s`, `_i` are violations, not a
pattern) — same abbreviation floor as everywhere else in the spec.

---

## Module-Level Constants

<!-- src: docs/foundation/naming-system.md §4 Surface 8 -->

| Visibility | Pattern | Example |
|-----------|---------|---------|
| Public (imported elsewhere) | `UPPER_SNAKE_CASE` | `REGIME_WRITER_OWNED_COLUMN_NAMES` |
| Private (module-internal) | `_UPPER_SNAKE_CASE` | `_JOB`, `_DEFAULT_TFS` |

A hardcoded numeric constant here is presumptively an APR violation (see CLAUDE.md §APR) before
it's a naming question — this section only governs the identifier once the constant is confirmed
to legitimately live outside APR.

---

## Gradient Scale Qualifiers

<!-- src: docs/foundation/naming-system.md §7 -->

Only these terms may appear as scale qualifiers in column names, APR keys, and variable names:

| Scale | Approved terms | Example |
|-------|---------------|---------|
| Speed / horizon (2-level) | `fast`, `slow` | `aroon_fast`, `aroon_slow` |
| Speed / horizon (3-level) | `fast`, `mid`, `slow` | `rsi_fast`, `rsi_mid`, `rsi_slow` |
| Speed / horizon (4-level) | `fast`, `mid`, `slow`, `extended` | `return_extended` |
| Magnitude / intensity | `low`, `mid`, `high` | threshold tiers, confidence bands |
| Rank / quality | `primary`, `secondary` | signal tiers, confirmation layers |

Numbers in names are valid **only** when the number defines the statistical concept (`rsi_14` = 14-period RSI — changing it to 9 or 21 is a different statistic, not a recalibrated version of the same one). For tunable calibration parameters, use a gradient term: `return_fast` column + `alpha.ic.lookahead.{tf}.fast` APR key.

A quantity may also use standard field-specific vocabulary instead of a generic scale when the terms are universally recognized, whiteboard-testable finance terminology (naming-system.md §7's domain-specific scales table) — e.g. `tight`/`wide` for credit spread state, `contango`/`neutral`/`backwardation` for term structure, `calm`/`elevated`/`turbulent` for idiosyncratic volatility state. See naming-system.md §7 for the full domain-specific table before using one of these.

**Prohibited:** `near`, `ultra`, `short`, `long`, or any term not in the generic or domain-specific tables. `tight`/`wide` are permitted *only* within the credit spread state domain-specific scale — never as a generic magnitude qualifier elsewhere. Adding a new term requires updating `docs/foundation/naming-system.md §7` first.

---

## Systemd Units

<!-- src: docs/foundation/naming-system.md §4 Surface 4; production/systemd/ -->

```
indicagent-<concept>.service
```

`concept` is the daemon's `snake_case` concept name. Examples: `indicagent-bar-aggregator.service`, `indicagent-feature-vector-pipeline.service`

Not every unit is a bare `<concept>` — e.g. `signal_tracker`'s live unit is `indicagent-signal-tracker-compute.service` (a `-compute` qualifier appended, not the pure pattern above). Check `production/systemd/` for the live name rather than assuming the mechanical derivation when precision matters.

Unit names update alongside class/file renames — never independently.

---

## Variables, Arguments, Labels

<!-- src: docs/foundation/naming-system.md §4 Surface 5 -->

| Surface | Rule | Example |
|---------|------|---------|
| Function arguments | Full descriptive name | `context`, `signal`, `timeframe` |
| Local variables | Full descriptive name | `signal_context`, `audit_result` |
| Structlog fields | Full descriptive name | `daemon_id`, `symbol`, `failure_reason` |
| Metric label: liveness/DLQ/crash | `agent_id` (legacy compatibility) | `agent_id` |
| All other new metric labels | Full descriptive name | `symbol`, `timeframe`, `job` |
| Enum members | `UPPER_SNAKE_CASE` | `REGIME_TRENDING`, `PENDING` |
| Mathematical variables | Single-letter convention | `n`, `x`, `y`, `i`, `j`, `t`, `p`, `r` |

---

## Tests

```
tests/unit/test_<module>.py
tests/unit/<domain>_tests/test_<thing>.py
tests/integration/test_<thing>.py
```

Test functions: `test_<what>_<condition>` — e.g. `test_compute_next_returns_macd_when_warmed_up`

---

## TypeScript / Dashboard (Ring 3)

| Thing | Convention | Example |
|-------|-----------|---------|
| Components | `PascalCase.tsx` | `SignalCard.tsx`, `SkeletonCard.tsx` |
| Hooks | `use-kebab-case.ts` | `use-market-stream.ts` |
| Utilities | `kebab-case.ts` | `format.ts`, `symbol-config.ts` |
| CSS variables | `--kebab-case` | `--amber`, `--signal-green` |

---

## Abbreviations

<!-- src: docs/foundation/naming-system.md §6 -->

**Always permitted** — canonical field codes in quant finance, statistics, and CS:

`pnl` `pnl_r` `mae` `mfe` `ts` `tf` `vol` `vix` `poc` `vah` `val` `beta` `alpha` `sharpe` `ohlcv` `vwap` `twap` `macd` `rsi` `ema` `sma` `atr` `adx` `std` `corr` `hmm` `id` `url` `api` `db` `sql` `json` `uuid` `llm` `gpu` `cpu` `otel` `sse`

**Specific surfaces only:** `i1`–`i8` (DB columns, topic strings, metric labels), `smc` (topic strings, JSONB keys), `agent_id` (legacy metric labels and structlog only)

**Never permitted** — code shortcuts:

`ctx` → `context` | `cfg` → `config` | `msg` → `message` | `evt` → `event` | `sig` → `signal` | `err` → `error` | `exc` → `exception` | `res` → `result` | `req` → `request` | `resp` → `response` | `tmp` → name by what it holds | `fn` → name by role | `idx` → `index` | `buf` → `buffer` | `obj` → name by type | `num` → `count` or `number`

---

## The Mechanical Derivation Table

<!-- src: docs/foundation/naming-system.md §4 -->

Given concept `signal_tracker` — this is a worked *exception* case, not the clean mechanical
example: `signal_tracker` doesn't own a dedicated input topic or output table, so those two rows
are N/A rather than an invented value. See `docs/foundation/naming-system.md §4` for a full
explanation of why, and for the general pattern (topic string `<env>.<domain>.<concept>` via
`topic_<concept>()`, table `<concept>s`) that still applies to concepts that do own their own
topic/table.

| Surface | Result |
|---------|--------|
| Daemon class | `SignalTracker` |
| File name | `services/signal_tracker.py` |
| Systemd unit | `indicagent-signal-tracker-compute.service` |
| Topic function | N/A — consumes shared upstream topics; publishes `topic_lifecycle_transitions()` |
| Topic string | N/A (no single owned topic) |
| DB table | N/A — persisted into the shared SLA schema (`signal_events`/`trade_frames`/`trade_executions`) by `LifecycleWriter`, not a `signal_trackers` table |
| Log file | `logs/signal_tracker.log` |
| Metric prefix | `signal_tracker_` |
| Structlog `daemon_id` value | `signal_tracker` |
| Variable name | `signal_tracker` |

---

## Operational Files (Surface 9)

<!-- src: docs/foundation/naming-system.md §11 -->

| Location | Purpose | Rule |
|----------|---------|------|
| `production/migrations/NNN_description.sql` | Canonical migrations, all phases | Sequential, applied once, never modified |
| `tools/<concept>_<verb>.py` | Permanent operational utilities | Only if run repeatedly; one-offs deleted on completion |
| `scripts/<layer>/<concept>.py` | Operational scripts by layer | Organized: `ops/`, `infrastructure/`, `debug/` |

**Deletion rule:** A file with no permanent operational use is deleted the day its job is complete. Git history is the archive. No `archive/` subdirectories.

---

## What Does Not Change

<!-- src: docs/foundation/naming-system.md §10 -->

- Kafka topic strings — current pattern is correct
- DB table names — `signal_ledger`, `intelligence_features`, `llm_calls` stay
- DB column quant codes — `ts`, `tf`, `pnl_r`, `mae`, `mfe` stay
- Plugin naming — `PascalCasePlugin` stays
- Intelligence tier codes — `I1`–`I8` stay in code, docs, metrics, directory names
- Ring 0/1 `Base*` prefix — `BaseDaemon`, `BaseWriter`, `BaseProvider`, `BaseAIWorker`, `BaseGroupCoordinator`
- `agent_id` metric label and structlog field — stays for operational compatibility
