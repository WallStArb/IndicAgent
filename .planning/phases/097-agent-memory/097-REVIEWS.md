---
phase: 97
reviewers: [codex]
reviewed_at: 2026-06-02T00:00:00Z
plans_reviewed: [097-01-PLAN.md, 097-02-PLAN.md, 097-03-PLAN.md, 097-04-PLAN.md, 097-05-PLAN.md, 097-06-PLAN.md]
---

# Cross-AI Plan Review — Phase 097

## Gemini Review

Gemini misinterpreted the review prompt as an execution task and attempted to implement the migration.
It was blocked by its own security restrictions and returned an error message, not a review.
Gemini's output is not usable. Only Codex review is included.

---

## Codex Review

### Summary

The plan set is directionally strong: it replaces Zep with a DB-native memory substrate, keeps compute
DB-ignorant on the real-time path, gates rollout behind `AGENT_MEMORY_ENABLED`, and separates read-only
`MemoryClient` from write-only episode capture. The biggest risks are not conceptual but execution-level:
schema idempotency, `MemoryClient.calibration()` depending on data access it does not own, ambiguous
feature-flag wiring for writers, incomplete metrics definitions for F1/F6 in Plan 02, and a very large
statistical batch job in Plan 097-05 that may be too broad to implement correctly in one pass. MEM-01 and
MEM-03 are mostly covered; MEM-02 is covered for episodic recall but naming drift between `setup_type`,
`entry_type`, and `hmm_regime` should be tightened; MEM-04 is only measurable if latency metrics and
timeout attribution are implemented more carefully.

---

### Plan 097-01

**Strengths:**
- Encodes C-01 through C-04 directly in schema, especially `regime_epoch`, `n_eligible`, `sample_n >= 30`, and `memory_assisted`.
- Correctly requires HNSW index on labeled episode embeddings.
- Good structural guarantee for a single open regime period via partial unique index.
- Promoted calibration table is append-only and N-gated at DB level.

**Concerns:**
- **HIGH:** Migration idempotency is overstated. ENUM guards are not enough. `CREATE TABLE`, `CREATE INDEX`, `create_hypertable`, and `add_compression_policy` can fail on second apply unless guarded.
- **HIGH:** `memory_system_state INSERT DEFAULT VALUES` will fail on rerun unless `ON CONFLICT (id) DO NOTHING`.
- **MEDIUM:** `create_hypertable` + compression policy creation inside a single transaction may be sensitive to existing state in some Timescale versions.
- **MEDIUM:** `\dt memory_*` listing "exactly 6 tables" may fail if Timescale creates internal objects matching the pattern.
- **MEDIUM:** Partial unique index on `(symbol, timeframe)` with `ts_end IS NULL` is correct but concurrent transition writes need transaction discipline.
- **LOW:** Plan relies on "verbatim from design doc" without restating D-09 outcome set explicitly, creating executor drift risk.

**Suggestions:**
- Use `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS`, `create_hypertable(..., if_not_exists => TRUE)`.
- Add `INSERT INTO memory_system_state ... ON CONFLICT (id) DO NOTHING`.
- Add verification queries for all four Renaissance columns/checks.
- Add pgvector extension existence check before creating vector columns.

**Risk: MEDIUM-HIGH.** Schema design is sound; migration idempotency and Timescale operational details could block execution.

---

### Plan 097-02

**Strengths:**
- Cleanly separates Ring 0 memory contracts from DB/Ollama implementations.
- Frozen dataclasses are appropriate for read results passed into workers.
- Protocol definitions allow backend/client/testing work to proceed independently.
- `AGENT_MEMORY_ENABLED` defaults false, satisfying MEM-03.
- YAML config captures key tunables.

**Concerns:**
- **HIGH:** `CalibrationStats` does not include `bootstrapped` field, despite F3 requiring `CalibrationStats(bootstrapped=False, sample_n=N)` below the N≥30 gate.
- **HIGH:** Plan says "five OTel instruments" but actually lists six, and still omits `MEMORY_EMBED_STALL_SECONDS` required by F1.
- **HIGH:** Plan 097-05 introduces `memory_promotion_skipped_n_eligible`, `memory_cohorts_promoted_total`, `memory_cohorts_quarantined_total`, and `memory_episodes_labeled_total` — none defined here.
- **MEDIUM:** Protocol docstrings say backends never raise, but the client should also be specified to catch backend exceptions.
- **LOW:** Fields like `hmm_regime`, `entry_type`, `pnl_r` technically violate Ring 0 "no domain vocabulary" — acceptable but worth acknowledging.

**Suggestions:**
- Add `bootstrapped: bool` to `CalibrationStats`.
- Define ALL metrics used by later plans: `MEMORY_EMBED_STALL_SECONDS`, `MEMORY_PROMOTION_SKIPPED_N_ELIGIBLE`, `MEMORY_COHORTS_PROMOTED_TOTAL`, `MEMORY_COHORTS_QUARANTINED_TOTAL`, labeled-count gauge.
- Add label/attribute conventions for each metric to prevent inconsistent naming across plans.

**Risk: MEDIUM.** Contract layer is mostly right; missing fields/metrics will cause downstream churn.

---

### Plan 097-03

**Strengths:**
- Correctly uses percentile-based embedding text per D-22.
- Episodic recall uses cohort scoping and Python epoch-decay reranking per D-23.
- Calibration backend reads only promoted table.
- All backends degrade to `[]`/`None` on failure.

**Concerns:**
- **HIGH: CRITICAL MODULE CONFLICT** — Plan 097-02 defines `src/core/memory/backends.py`. Plan 097-03 defines `src/core/memory/backends/__init__.py`. You cannot have both a file `backends.py` and a directory `backends/` with the same module name. This is a Python import error that will break the entire module on import.
- **HIGH:** `MemoryClient.recall()` embeds context before querying — Ollama embedding latency alone can easily exceed 40-50ms. MEM-04's 50ms p95 target is at risk unless embeddings are precomputed or cached.
- **HIGH:** Passing `list[float]` as `::vector` with asyncpg may not work without pgvector codec registration or string serialization. The plan must specify exact parameter format.
- **HIGH:** `asyncio.wait_for(..., 40ms)` around pool acquisition may timeout due to pool contention, not DB latency — metrics should distinguish cause if possible.
- **MEDIUM:** `SET hnsw.ef_search = 100` should be `SET LOCAL hnsw.ef_search = ...` inside a transaction to avoid polluting the connection pool.
- **MEDIUM:** Epoch delta should be clamped: `delta = max(0, current_epoch - row.regime_epoch)` to handle anomalous future-epoch rows.
- **MEDIUM:** `hmm_regime` used as `regime_type`, `entry_type` used as `setup_type` — MEM-02 uses different terminology; should be explicitly aliased.

**Suggestions:**
- Resolve the `backends.py` vs `backends/` conflict before any implementation: delete `backends.py` in Plan 02 and change it to define the Protocols inside `backends/__init__.py` or `backends/base.py`.
- Add embedding cache (LRU or TTL) keyed by serialized text, or explicitly state embedding latency is excluded from recall p95.
- Specify pgvector asyncpg parameter handling: pass as `'[0.1,0.2,...]'::vector` cast or register pgvector codec.
- Use `SET LOCAL` for `hnsw.ef_search`.

**Risk: HIGH.** Module conflict is a hard blocker. 50ms p95 target needs embedding latency resolution.

---

### Plan 097-04

**Strengths:**
- Correct read-only `MemoryClient` / write-only `MemoryEpisodeWriter` separation per D-19.
- Fire-and-forget bounded queue is the right shape for the real-time path.
- Uses `asyncio.to_thread()` for synchronous Mem0 SDK calls.
- WorkerContext typing via `TYPE_CHECKING` is appropriate.

**Concerns:**
- **HIGH:** `MemoryClient.calibration()` is instructed to query `memory_episodes_labeled` for partial stats, but `MemoryClient` has no DB pool and should be a read-only facade over backends. This breaks abstraction unless `CalibrationBackend` exposes a partial-count method.
- **HIGH:** F3 partial `CalibrationStats(bootstrapped=False, sample_n=N)` requires `bootstrapped` field in Plan 097-02, which is currently absent.
- **HIGH:** Timeout attribution is impossible if backends return `[]` for both timeout and no results. Plan notes this but doesn't lock an implementation.
- **HIGH:** `EmbeddingWorker._drain` skips row when vector is `None`, but schema allows `embedding NULL` on raw episodes (back-fill filters `IS NOT NULL`). Skipping loses the episode entirely. Raw row should be inserted with `embedding NULL`.
- **MEDIUM:** `MEMORY_EMBED_STALL_SECONDS` referenced in this plan but not defined in Plan 097-02.
- **MEDIUM:** Writer lifecycle under-specified: who calls `EmbeddingWorker.start()`, how is shutdown handled under systemd?
- **MEDIUM:** Factory does not show config loading from `config/memory.yaml`; defaults may drift from YAML.
- **MEDIUM:** Mem0 LLM extraction disablement needs SDK API verification before assuming it's achievable via config flags.

**Suggestions:**
- Add `get_partial_count(agent_id, symbol, hmm_regime, entry_type, regime_epoch) -> int` to `CalibrationBackend` Protocol; use this in `MemoryClient.calibration()` for cold-start path instead of direct DB.
- Define a `RecallResult` internal type or use `None` as sentinel to distinguish miss vs error vs timeout.
- In `EmbeddingWorker._drain`: insert raw row with `embedding=NULL` when vector generation fails, rather than skipping.
- Specify full writer lifecycle: where constructed, `start()` called, and shutdown ordering.
- Load `config/memory.yaml` once in factory and pass values into all components.

**Risk: HIGH.** Architecturally central; unresolved interface mismatches will cause significant churn.

---

### Plan 097-05

**Strengths:**
- Correct strict ordering: Epoch → RegimeTransition → Backfill → Promotion.
- Step failure aborts downstream steps, preventing promotion on incomplete state.
- Backfill is idempotent via `ON CONFLICT DO NOTHING`.
- Enforces N≥30 at application and DB layers.
- F2, F4, and F6 correctly incorporated.

**Concerns:**
- **HIGH:** PromotionJob statistics are underspecified: Brier decomposition requires binning definition; IC requires exact prediction/outcome variable definition; correction-factor stability requires sub-window specification.
- **HIGH:** Circular block bootstrap needs number of resamples, statistic, random seed policy, and block wrapping behavior.
- **HIGH:** BH-FDR "across all cohorts this run" needs clear family definition — mixing agents/symbols/regimes/statistics may be statistically incoherent.
- **HIGH:** `n_eligible` backfill "counting eligible bars from market_data_ohlcv + signal_ledger" is vague — can introduce lookahead or inconsistent denominators.
- **HIGH:** EpochJob checks "last 3 rows ordered by `run_ts`" but SPC schema uses `ts` as the time column — column name mismatch.
- **MEDIUM:** `memory_regime_transitions` concurrent close/open writes can violate `mem_reg_open` unique index unless done transactionally with row-level locks.
- **MEDIUM:** Dry-run semantics broad — should compute but not insert/update; requires explicit write guards.
- **MEDIUM:** Batch metrics (`memory_episodes_labeled_total`, promotion counters, etc.) not defined in Plan 097-02.
- **LOW:** `TimeoutStartSec=600` may be too short as episode volume grows.

**Suggestions:**
- Consider splitting into two plans: orchestration/backfill/regime (simpler) + promotion/statistics (statistically dense).
- Add a statistical spec appendix: prediction column, binary outcome definition, Brier binning, IC method, bootstrap resamples count (e.g., 10000), random seed, BH family, stability window definition.
- Define `n_eligible` exactly: eligibility predicate, time window, denominator.
- Fix: `run_ts` → `ts` in EpochJob consecutive-alarm query.
- Add explicit transaction boundaries and row locks for RegimeTransitionJob close/open.

**Risk: HIGH.** Batch pipeline is essential and statistically sensitive. Without tighter math, it risks producing confident but invalid calibration.

---

### Plan 097-06

**Strengths:**
- Uses fakes for DB/Ollama — CI-safe.
- Tests graceful degradation, read-only invariant, queue full behavior, percentile serialization.

**Concerns:**
- **HIGH:** `test_drain_skips_null_embedding` conflicts with the correct behavior of inserting raw episodes with `embedding=NULL`. Once Plan 097-04 is corrected, this test needs updating.
- **MEDIUM:** No tests for epoch-weighted reranking in `PgvectorEpisodicBackend`.
- **MEDIUM:** No tests for `build_memory_client()` returning `None` when disabled.
- **MEDIUM:** No tests for timeout-vs-miss metric distinction.
- **MEDIUM:** No tests for `WorkerContext.memory_client` propagation into worker setup paths.

**Suggestions:**
- Update writer drain tests after resolving NULL-embedding insert decision.
- Add reranking unit tests with mocked rows at current, prior, and future epochs.
- Add factory gating tests for both enabled and disabled paths.
- Add metric spy tests for recall latency and hit/miss/timeout labels.

**Risk: MEDIUM.** Good foundation; incomplete around highest-risk behaviors.

---

## Cross-Plan Dependency Issues (Blockers)

| Issue | Plans Affected | Severity |
|-------|---------------|----------|
| `backends.py` (Plan 02) vs `backends/` package (Plan 03) — Python import conflict | 02, 03 | **BLOCKER** |
| `CalibrationStats` missing `bootstrapped` field | 02, 03, 04, 06 | **BLOCKER** |
| `MEMORY_EMBED_STALL_SECONDS` and batch metrics not defined in Plan 02 | 02, 04, 05 | HIGH |
| `MemoryClient.calibration()` cold-start path queries DB directly (no backend method) | 03, 04 | HIGH |
| EmbeddingWorker skips NULL-vector rows — should insert with `embedding=NULL` | 04, 06 | HIGH |
| SPC column name `run_ts` vs `ts` in EpochJob consecutive-alarm query | 01, 05 | HIGH |

---

## Council Fixes F1-F6 Re-Assessment

| Finding | Status After This Review |
|---------|--------------------------|
| F1: Queue depth + stall observability | Partially applied — `MEMORY_EMBED_STALL_SECONDS` not defined in Plan 02 |
| F2: Auto epoch increment | Applied in Plan 05, but `run_ts` vs `ts` column mismatch needs fix |
| F3: Cold-start calibration | Partially applied — `bootstrapped` field missing from `CalibrationStats` |
| F4: Bootstrap block length formula | Correctly applied |
| F5: Mem0 LLM extraction disabled | Applied, pending SDK verification |
| F6: n_eligible skip counter | Applied conceptually, but metric not defined in Plan 02 and n_eligible computation underspecified |

---

## Consensus Summary

### Key Strengths
- Architecture correctly separates read/write paths, gates behind feature flag, and encodes Renaissance constraints structurally in schema.
- Fire-and-forget queue + background EmbeddingWorker is the right async pattern for keeping memory writes off the signal pipeline.
- Offline promotion with N≥30 gate and append-only calibration table is statistically disciplined.
- Council fixes F2, F4, and F5 are correctly incorporated.

### Blocking Issues (Fix Before Execution)

1. **`backends.py` vs `backends/` module conflict** — Plan 02 defines `backends.py`, Plan 03 creates a `backends/` package. Python can't have both. Resolve by moving Protocols into `backends/__init__.py` or `backends/base.py` and removing the flat `backends.py`.
2. **`CalibrationStats` missing `bootstrapped: bool`** — Add to Plan 02. Without it, F3 cold-start path is unimplementable.
3. **Missing metrics in Plan 02** — `MEMORY_EMBED_STALL_SECONDS`, `memory_promotion_skipped_n_eligible`, `memory_cohorts_promoted_total`, `memory_cohorts_quarantined_total`, `memory_episodes_labeled_total` all used by Plans 04/05 but not defined in Plan 02.
4. **EmbeddingWorker NULL-vector skip** — Should insert raw row with `embedding=NULL` rather than dropping the episode. Fix Plan 04 + Plan 06 test.
5. **SPC column `run_ts` vs `ts`** — EpochJob queries `run_ts` for consecutive alarm detection; SPC table uses `ts`. Fix Plan 05.
6. **Migration idempotency** — `CREATE TABLE IF NOT EXISTS`, `create_hypertable(if_not_exists=>TRUE)`, `ON CONFLICT DO NOTHING` for state row seed. Fix Plan 01.

### Divergent Views
- **MEM-04 achievability:** Codex flags that 50ms p95 recall is at risk if Ollama embedding is in the live recall hot path. The design intends embeddings to be precomputed at write time and stored; recall queries by stored vector, not re-embeds. This should be made explicit in Plan 03 so executors don't embed at recall time.
- **Plan 097-05 granularity:** Codex recommends splitting into two plans. Given the statistical density of the PromotionJob, this is worth considering but not mandatory if the statistical appendix is added.
