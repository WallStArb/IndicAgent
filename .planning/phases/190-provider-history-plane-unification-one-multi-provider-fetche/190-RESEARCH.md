# Phase 190: Provider history plane unification - Research

**Researched:** 2026-10-09
**Domain:** Multi-provider market-data history fetching (Python, BaseBatch oneshot, psycopg/TimescaleDB, systemd)
**Confidence:** HIGH (nearly all findings verified by direct read of the live code this session; Alpaca vendor facts cited from the measured pilot doc)

## User Constraints (from CONTEXT.md)

### Locked Decisions

**Layering**
- Ring 1 leaves (`src/providers/<vendor>.py`): `ibkr.py` unchanged in role, `alpaca.py` from todo 521's lane. Leaves own credentials isolation, pagination, their native rate-limit model, RTH/adjustment knobs as declared request parameters. Policy never enters a leaf.
- Leaf interface contract: caller-driven window-scoped pagination (cursors are never long-lived state; resumability comes from coverage, not tokens); leaf owns its native rate-limit model behind a common budget interface (planner passes deadline + request budget); queue items keyed by registry instrument/symbol with leaf-resolved vendor symbology (resolution failures are item-level errors, never silent skips); adjustment and window conventions declared in the request and recorded in lineage.

**Two-tier ledger (the AGY correction)**
- Per-provider tier: todo 526's provider heads (per-TF proven-days, floors) are the planning source of record; `consecutive_failures` and quarantine state are per-provider. One vendor's outage can never rank or exclude the other vendor's items.
- Canonical tier: `ohlcv_coverage` stays the stored-state ledger written in-transaction with the bars, provider-labeled; its rebuild path's IBKR-specific request filter (`route = 'SMART' AND what_to_show = 'TRADES'`) generalizes into per-provider rebuild inputs.
- The planner reads the per-provider tier only; it never derives a vendor's gap from another vendor's coverage.

**Policy vs write arbitration**
- `bar_source_policy` per-name-per-TF rows decide which vendor's queue items are created for a span and which source may issue a revision; a revision corrects only its own source's rows.
- The grid's `UNIQUE (timestamp, symbol, timeframe)` with first-writer-stays stays the sole write gate. No span re-arbitration, no cross-source restatement. Divergence surfaces through D7 vendor-agreement checks and d2-v3 restate of the authoring source's own rows. D7 extends to a second tape (todo 521 dependency 2).

**Empty-history verdicts**
- A normalized no-data verdict is a verdict object: status plus vendor evidence (IBKR confirming-chunk count; Alpaca single authoritative empty response). The planner may weight evidence per vendor. `ohlcv_empty_history` keeps its confidence semantics per vendor (provider dimension owed).

**Service and concurrency**
- One fetcher process, one queue, one writer connection, one advisory-lock singleton. Lanes (IBKR 1d nightly update, 5m drain, Alpaca all-names load, todo 521 nightly T4 verifier) are priorities inside the same loop, never lock contenders. The IBKR socket constraint lives inside the IBKR leaf and its budget.
- Proposed name `ohlcv_history_fetcher` / `OHLCVHistoryFetcher` (glossary check at plan time; `IbkrHistoryFetcher` is live precedent, this is a `BaseBatch` batch job, not a Ring 2 daemon).

**Sequencing**
- Step 1 (not this phase): Alpaca leaf + policy docs + conformance tests land via todo 521's lane as new modules touching no fetcher import; pilot/verification against scratch only, no canonical write.
- Step 2 (this phase): generalize the fetcher and land the two-tier ledger as one refactor (shared planner edit with todo 526); the drain kill-and-resumes under the unified fetcher and continues from coverage (resume state is the coverage ledger and permanent bars; the fetcher has no `code_content_key` cell cache).
- Step 3 (this phase, gated on the drain): canonical Alpaca load runs as queue lanes in the unified fetcher through leaf, capture contract, and basis admission. No interim separate Alpaca oneshot.

**Enforcement**
- Protocol-conformance test both history leaves must pass (normalized verdicts and evidence fields, observation shape, page boundaries, budget interface).
- Boundary test in the `test_market_data_ohlcv_boundary.py` pattern: services and scripts import the protocol, never a concrete leaf.
- APR keys per provider under `infra.<provider>.*`, seeded from measured values with `[measured]` provenance.

### Claude's Discretion
Task decomposition, wave structure, exact migration numbering, conformance-test fixture mechanism, per-provider head schema details within todo 526's scope.

### Deferred Ideas (OUT OF SCOPE)
- Alpaca live-streaming leaf (same `DataProvider` protocol, dormant streaming DAG)
- Third-vendor onboarding
- Wiring ingestion lag alerts (alerting deliberately unwired for UAT)

## Phase Requirements

No requirement IDs were mapped for this phase (planning/REQUIREMENTS.md does not exist). The phase scope is defined by the approved design `docs/plans/2026-10-09-provider-history-plane-unification-design.md` (rev 2) and 190-CONTEXT.md; the planner should derive plan-level requirement IDs from the design's Enforcement and Sequencing sections.

## Summary

The phase generalizes a fetcher that phase 189 already built well: `IbkrHistoryFetcher` (scripts/infrastructure/backfill/ibkr_history_fetcher.py, 1,309 lines) is a `BaseBatch` oneshot with a deterministic ledger-ranked queue, an advisory-lock singleton, atomic chunk+ledger writes, dry-run mode, and kill-and-resume from coverage. Its IBKR-specificity is concentrated and enumerable: a `PROVIDER = "ibkr"` constant and per-provider SQL in `_fetch_queue.py`, module-global APR overlays loaded at run start (`_load_provider_overlays`), IBKR socket/gateway semantics in the loop, and an IBKR-only request filter in the coverage rebuild. The ledger tables split cleanly: `ohlcv_empty_history` already has `provider` in its PK (migration 354), `ohlcv_provider_head` has provider but no timeframe (migration 355, todo 526's migration), and `ohlcv_coverage` has no provider dimension at all (migration 432).

Two findings materially shape the plan. First, todo 526's original premise was withdrawn by its own 2026-10-09 correction: the planner already computes gap as `min(depth_days, proven_days, floor) - actual` and plans head gaps correctly; what survives is only the per-TF `ohlcv_provider_head` PK migration, floor seeding, and a floor-lookup edit, with a before/after dry-run parity bar. Second, the Alpaca leaf (`src/providers/alpaca.py`) does not exist yet on main and todo 521 is deferred behind a plan-doc gate, so this phase's step 2 (the refactor) must be executable with IBKR-only leaves parameterized, and step 3 (canonical Alpaca load) is genuinely blocked until 521's lane lands.

The rename surface (`ibkr_history_fetcher` to `ohlcv_history_fetcher`) is wider than the code: a checked-in pair of systemd unit files plus root-owned copies in /etc/systemd/system, `_DAG_ORDER` and the oneshot list in services/service_auditor.py, the advisory-lock name (whose sha256 key the manual ops tools share), the status-file path the D7 audit reads, metric job labels, and the structlog-derived log file name. All are enumerable and listed below.

**Primary recommendation:** Plan step 2 as a queue-and-ledger refactor that is provider-parameterized but ships with exactly one leaf (IBKR), gated by a dry-run parity check against today's planner output; treat the migration set as one numbered family (coverage provider labeling, provider_head per-TF PK, per-provider failure state, APR seeds); keep every externally parsed string (`fetch_run_id:` line, LOCK_HELD_MESSAGE, status-file schema) byte-identical or update all consumers in the same commit.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Vendor API mechanics (pagination, rate limits, symbology, adjustment knobs) | Ring 1 leaf (`src/providers/<vendor>.py`) | - | Design decision; policy never enters a leaf |
| Queue ranking, lanes, budget, planning | Batch script tier (`scripts/infrastructure/backfill/`) | reads per-provider ledger tier | The fetcher is the only history-plane planner |
| Per-provider planning state (heads, floors, failures, quarantine) | Database (ledger tables) | written by fetcher path | Single-writer tables; planner reads only |
| Canonical stored-state coverage | Database (`ohlcv_coverage`) | written in-transaction with bars | Design: canonical tier stays |
| Span ownership / which vendor's items exist | Database (`bar_source_policy` rows) | CLI writer `ops_source_policy.py` | Policy at capture layer, never in leaf |
| Persistence of bars + requests + coverage | `services/ohlcv_observation_writer.py` + `services/ohlcv_coverage_writer.py` | - | Already mechanism-generic (design confirms unchanged) |
| Process singleton + liveness | systemd (Type=exec unit, WatchdogSec) + `FetcherLock` advisory lock | - | Structural concurrency guarantee |
| Policy rows authoring | `scripts/ops/bars/ops_source_policy.py` (sole writer per single-writer registry) | - | Not this phase's write path; the fetcher becomes a reader |

## Standard Stack

No new external packages are required for this phase. The stack is entirely in-repo:

| Component | Version/Location | Purpose | Why Standard |
|-----------|------------------|---------|--------------|
| Python venv | `.venv/` (3.12+, has `datetime.UTC`) | runtime | existing |
| psycopg | in venv | sync conn for lock/writer, async pool for queue reads | existing |
| asyncpg | in venv | BaseBatch pooled reads | existing |
| httpx | 0.28.1 (verified: `.venv/bin/python -c "import httpx"`) | Alpaca REST when the leaf lands (the scratch pull already uses it; no alpaca-py needed) | measured precedent in `scripts/research/alpaca_depth_scratch_pull.py` |
| pytest | 9.0.3 | tests | existing |
| structlog, OTel SDK | in venv | logging/metrics | existing (never prometheus_client) |

If todo 521's lane instead introduces `alpaca-py`, that is 521's package decision, not this phase's; this phase consumes the leaf through the protocol and needs only the protocol types.

## Package Legitimacy Audit

No new external packages are installed by this phase. `httpx` (0.28.1) is already present in the project venv and is the measured precedent for Alpaca REST calls (`scripts/research/alpaca_depth_scratch_pull.py:26`). The Alpaca leaf module itself is step 1 (todo 521's lane), outside this phase's install surface. slopcheck was therefore not run: the audit table is empty by construction, and no checkpoint gates are owed.

## Architecture Patterns

### System Architecture Diagram

```
                       systemd timer (15-min OnUnitInactiveSec)
                                      |
                                      v
                      OHLCVHistoryFetcher (BaseBatch oneshot)
                       [FetcherLock advisory singleton]--fail fast--> exit 0, lock_held
                                      |
        +-----------------------------+-------------------------------+
        |  prepare (reads only)       |  locked run                   |
        v                             v                               v
  APR config_state              PriorityQueue.load()            per-provider leaves
  (infra.<provider>.*)          per-provider tier reads         src/providers/ibkr.py
  scopes, lanes, parity         (heads/floors, failures,        (alpaca.py when landed)
  per-provider budgets          empty ranges, coverage)              |
        |                             |                              | pages, budget,
        |                             v                              | native rate limit
        |                       rank (pure tuple)  <--- item_lane   |
        |                       lanes: update/gap_fill/              |
        |                       backfill/parity/<alpaca-load>        |
        |                             |                              v
        |                             v                    normalized OHLCVBar +
        |                       fetch_item_with_retries <--+  no-data verdict object
        |                       (stall bound, retries)       |
        |                             |                       |
        v                             v                       v
  coverage ledger writes (one transaction per chunk):
    ohlcv_request -> bars (grid or archive) -> ohlcv_coverage   [canonical tier]
  per-provider outcome writes:
    heads / floors / consecutive_failures                        [per-provider tier]
        |
        v
  run end: overlap judge -> escalation re-fetch -> daily stage -> grid stage
           -> SLA gauge -> status file (D7 audit reads it) -> run summary
```

Primary use case trace: timer fire -> lock -> queue.next() reads per-provider tier -> item dispatched to its provider's leaf -> bars land through the observation sink with the coverage upsert in the same transaction -> outcome recorded per-provider -> derivation stages promote.

### Recommended Project Structure

```
scripts/infrastructure/backfill/
├── ohlcv_history_fetcher.py     # renamed/generalized fetcher (BaseBatch)
├── _fetch_queue.py              # queue gains provider dimension; per-provider config
├── _fetcher_lock.py             # lock name decision (keep or rename, one commit)
├── _history_fetch_item.py       # IBKR item mechanics; leaf-facing seam here
├── _history_fetch.py            # helper library; module-global APR overlays
└── _empty_history.py            # already provider-keyed; stays

src/providers/
├── base.py                      # protocol gains batch history surface + verdict object
├── ibkr.py                      # leaf, unchanged in role
└── alpaca.py                    # step 1 lane (may not exist yet at execution time)

services/
├── ohlcv_coverage_writer.py     # provider-labeled canonical tier; per-provider rebuild inputs
└── ohlcv_observation_writer.py  # unchanged (already mechanism-generic)

tests/unit/scripts/              # fetcher/queue/item tests, provider-parameterized
tests/unit/                      # boundary + migration-contract tests
```

### Pattern 1: Provider-parameterized queue config

**What:** `QueueConfig` (scripts/infrastructure/backfill/_fetch_queue.py:123) becomes per-provider or gains per-provider fields; the pure rank tuple stays pure.
**When to use:** every place the queue currently reads `infra.ibkr.*` (`_KEY_REQUEST_TIMEOUT` :100, `_KEY_REQUEST_RETRIES` :101, `_KEY_RATE_LIMIT_WINDOW` :102, `_KEY_CONFIRMATION_CHUNKS` :103) or the module constant `PROVIDER = "ibkr"` (:90).
**Example shape:**

```python
@dataclass(frozen=True)
class ProviderPlan:
    """Per-provider planner inputs: budget interface + native semantics."""
    name: str                      # "ibkr", "alpaca"
    request_timeout_s: float       # infra.<p>.history_request_timeout
    request_retries: int
    confirmation_chunks: int       # no-data evidence threshold (IBKR n-chunk; Alpaca 1)
    inter_item_pause_s: float      # infra.<p>.inter_item_pause_s
```

The existing validation in `load_queue_config` (:212-219, stall bound must exceed rate-limit window) generalizes to a per-provider check, not a global one.

### Pattern 2: Item-level leaf resolution and verdict objects

**What:** each queue item resolves its leaf at item start; the leaf returns observations plus a structured no-data verdict. `EmptyHistory` (src/providers/base.py:176-190) is the IBKR precedent; the protocol gains a normalized verdict type with per-vendor evidence fields.
**Why:** the design's empty-history decision; `_EMPTY_SQL` (scripts/infrastructure/backfill/_fetch_queue.py:517-521) already filters `ohlcv_empty_history` by provider and `n_confirming_chunks`, so the ledger side needs no migration, only the leaf-side verdict object and per-provider weighting in the queue's floor computation.

### Anti-Patterns to Avoid

- **A second fetch path for Alpaca:** the exact fork this design exists to prevent. Any Alpaca fetching outside the unified loop (a oneshot script with its own ledger handling) is a violation, per the design's deleted interim oneshot.
- **Cross-provider gap derivation:** the planner must never read vendor B's coverage/head to compute vendor A's gap (silent gap erasure: Alpaca's 2016-forward head would erase IBKR's 2006-2016 plan).
- **Shared consecutive_failures:** one vendor's outage quarantining the other vendor's symbols.
- **Policy inside a leaf:** leaves take no imports from `services/` or `src/intelligence/`; no policy branches on vendor inside the loop either (vendor semantics come from per-provider data).
- **Editing fetched-module imports while a run is live:** the fetcher itself carries no `code_content_key` cache (kill-and-resume safe), but the rule still means: stop the timer/service, check the code diff, then deploy (memory: restart-batch-job check-code-diff-first).

## Research Findings (the nine questions)

### 1. IBKR-specific inventory in the fetcher (must become per-provider data)

All file:line verified by read this session.

**scripts/infrastructure/backfill/ibkr_history_fetcher.py**
- `:139` imports `IBKRProvider` directly; `:570-573` `_default_provider()` constructs it with `settings.ib_host/ib_port` and `args.client_id` (an IBKR-only CLI flag, `:243-245`).
- `:143` `JOB = "ibkr-history-fetcher"` (metric job label, log identity, status file payload).
- `:150` `_INTRADAY_UPDATE_TF = "5m"`; `:152` `_PARITY_TFS = ("15m", "1h")` (archive-bound, `_history_fetch._ARCHIVE_TFS` at _history_fetch.py:86).
- `:154` `_SEAM_KEYS` (threshold.seam.*); `:161` `_KEY_INTER_ITEM_PAUSE = "infra.ibkr.inter_item_pause_s"`.
- `:822-823` `"IBKR gateway unreachable at startup"` raise; gateway-loss semantics throughout `_loop` (:886-889) and `_escalate` (:997-999) are IBKR socket facts.
- `:1166-1176` `_load_provider_overlays()` calls eight module-global APR overlay loaders in `_history_fetch.py` (`_load_ibkr_chunk_days_config` :421, `_load_ibkr_hist_timeout_config` :446, `_load_ibkr_retry_config` :485, `_load_ibkr_venue_fallback_config` :526, `_load_ibkr_rate_limit_config` :560, plus `_load_ohlcv_insert_batch_size_config` :789 and `_load_gap_cluster_max_days_config` :928 which are provider-neutral). This module-global overlay pattern is the documented APR migrate-as-you-go pattern (docs/reference/gotchas.md); it must become leaf-owned or per-provider-plan-owned.
- `:67` (`_history_fetch.py`) `_EMPTY_HISTORY_PROVIDER = "ibkr"` used in `_default_context` (:578-582).
- `_history_fetch_item.py` IBKR mechanics: `_ensure_qualified` (:371, IBKR conId qualification), `_head_floor` (:386, with a futures branch :399), FX/crypto 1m derive (`:696` asset-class branch, `_fx_derive` :731), venue fallback routing, `what_to_show`/`route` on every RequestRecord. These stay inside the IBKR leaf's fetch path; the fetch loop should not see them.

**scripts/infrastructure/backfill/_fetch_queue.py**
- `:90` `PROVIDER = "ibkr"`; `:100-103` four `infra.ibkr.*` APR keys; `:95-99` provider-neutral `infra.backfill.*` keys (max_consecutive_failures, staleness, priority_tf_order, default_scopes, run_budget).
- `:513-516` `_HEADS_SQL`: `ohlcv_provider_head WHERE provider = $1` (no timeframe column; todo 526's migration).
- `:517-521` `_EMPTY_SQL`: provider-filtered, `n_confirming_chunks >= $4`.
- `:525-530` `_LATEST_DAILY_ANSWER_SQL`: `source = $1 AND timeframe='1d' AND route='SMART' AND what_to_show='TRADES'` — the 1d due rule is doubly IBKR-specific (request-shape filter AND the fact that only IBKR answers 1d; todo 521 decision 3 rules out Alpaca 1d bars, so the 1d session-calendar due rule is per-provider planner data: IBKR yes, Alpaca no 1d lane at all).
- `:464` rank element 1 reads `consecutive_failures` (currently shared across what is only IBKR; becomes per-provider).
- Depth days (`_DEPTH_PREFIX` :104, fallbacks :120) are currently provider-uniform (7300/1m:90); Alpaca's 2016-forward 5m scope means depth_days may need a provider dimension (or policy rows carry it; planner's call within discretion).
- `:212-219` the timeout > rate-limit-window coupling check is an IBKR-limiter invariant; generalizes per provider.

**services/ohlcv_coverage_writer.py**
- `:245-248` `_REQUEST_FILTER = "route = 'SMART' AND what_to_show = 'TRADES' AND outcome IN (...)"` inside `_REBUILD_SQL` (:176-244) — the rebuild's IBKR-only request shape. This is the "per-provider rebuild inputs" generalization the design names.
- `:41-44` `DESTINATION_TABLES` (grid vs archive) is mechanism-generic, unchanged.

**Queue item shape:** items are `(symbol, timeframe)` pairs today (`Candidates.pairs` :396, `PriorityQueue.candidates` :555, `visited: set[tuple[str, str]]` :867). The provider dimension must thread through: `RankedItem`, `CoverageRow` (or CoverageRow gains a provider field), `item_lane`, `parity_sample` keys, the dry-run TSV columns (`:171-188`, add a provider column; ops_head_rerun and any TSV consumers must be checked), and the escalation targets list (`:969-979`).

### 2. ohlcv_coverage read paths and migration shape

**Writers (single-writer registry, tests/unit/test_single_writer_registry.py:77):** `services/ohlcv_coverage_writer.py` only, under `SET LOCAL ROLE bar_derivation_writer`, from `upsert_coverage` (in `persist_chunk_atomically`'s transaction), `record_fetch_outcome`, `refresh_1d_bounds`, `rebuild_from_stored_state`, `reset_failures`. Boundary fence: tests/unit/test_ohlcv_coverage_writer_boundary.py.

**Readers found (grep-verified, complete list):**
- Planner/queue: `_fetch_queue.py:508-511` `_COVERAGE_SQL` (bounds, status, failures, last_fetched_at) — the planning read.
- D7 audit: `services/bar_reconciliation_audit.py:1266-1268` `_COVERAGE_ROWS_SQL` (bounds + status, for display/completeness context). Not a planning read; unaffected by per-provider heads as long as canonical row semantics stay.
- Onboarding: `src/config/instrument_onboarding.py:12` docstring mention only (new active names are picked up by re-running; no direct read).
- Metric: `src/observability/metrics.py:414` the SLA gauge name only.
- Migration/contract tests and integration tests (see section 7).

**What breaks if the planner moves to per-provider heads:** nothing external. The planner's only ledger inputs are `_COVERAGE_SQL`, `_HEADS_SQL`, `_EMPTY_SQL`, and the daily-answer SQL; all four become per-provider. The D7 audit read stays on the canonical tier and keeps working.

**Migration shape (planner decides numbering; substance):**
1. `ohlcv_coverage` gains a `provider` label. Schema today: plain table (NOT a hypertable; ~2.5k rows; migration 432 header states this explicitly, so the compressed-hypertable decompress/VACUUM rule does NOT apply), PK `(symbol, timeframe)` at 432_ohlcv_coverage.sql:50, CHECK constraints at :51-57.
2. `ohlcv_provider_head` PK `(symbol, provider)` -> `(symbol, provider, timeframe)` with per-TF floor rows seeded from measured vendor floors (todo 526's surviving item, verbatim).
3. Per-provider quarantine/failure state: either a provider column on the same failure columns (widening the PK to include provider) or a small per-provider companion table. The design says "provider-labeled" canonical tier plus per-provider failure state; the simplest faithful shape is `ohlcv_coverage` PK `(symbol, timeframe, provider)` with `consecutive_failures` moving per-row, existing rows backfilled to their authoring source.
4. APR seeds: per-provider budget keys under `infra.<provider>.*` with `[measured]` provenance (design Enforcement), plus per-provider `max_consecutive_failures` (or promote the existing `infra.backfill.max_consecutive_failures` to per-provider keys).

**Backfill hazard for step 3 (flag for the planner):** existing `ohlcv_coverage` rows are a rollup of stored bars whose 1d content mixes IBKR and pre-D Tradier rows, and the 449 vendor lane wrote bars without ledger coverage for a window (writer docstring :253-258). Labeling every existing row `provider='ibkr'` is defensible only because the ledger's fetch bookkeeping (last_fetch_status from SMART TRADES requests) is IBKR-only today; the planner should state the labeling rule explicitly in the migration and note that pre-swap Tradier-era 1d bounds ride under the IBKR label as stored-state, not as vendor claims. This is exactly the canonical-vs-per-provider-tier distinction the design draws.

### 3. consecutive_failures / quarantine today

- Lives in `ohlcv_coverage.consecutive_failures` (migration 432:49; writer `record_fetch_outcome` services/ohlcv_coverage_writer.py:129-141, only 'error' increments; 'ok'/'no_data' reset).
- Consumers (complete): the rank tuple's first element (`_fetch_queue.py:464` vs `infra.backfill.max_consecutive_failures`, seeded 432:119-124), the dry-run "excluded" band (`ibkr_history_fetcher.py:1263-1276` via `held_snapshot`), and `--reset-failures` (`ibkr_history_fetcher.py:298-303, 751-767` -> `reset_failures` writer :282-298). No other readers. Moving it per-provider is a contained change.

### 4. DataProvider protocol consumers (what the batch surface must not disturb)

- `src/providers/base.py`: `DataProvider` (streaming protocol, :51-108: connect/disconnect/is_connected/resolve_instrument/stream_ticks/stream_real_time_bars/fetch_historical_bars) and `DataProviderAdapter` (:113-165, the Phase 54 bar-level adapter). Both `runtime_checkable`.
- Streaming consumers (dormant units, verified `systemctl list-unit-files`: `indicagent-ibkr-provider`, `indicagent-provider-merger`, `indicagent-bar-writer`, `indicagent-bar-aggregator` all disabled): `services/ibkr_provider.py:15,37` uses `DataProviderAdapter`; `bar_writer.py:396-405` and `bar_aggregator.py:621-632` reference only the legacy "DataProviderAgent" wire format in comments, not the protocol. `bar_replay_provider.py` has no protocol reference.
- Batch consumers of `IBKRProvider` today (grep-complete list): the fetcher family (`ibkr_history_fetcher.py`, `_history_fetch.py`, `_history_fetch_item.py`), manual ops tools under the lock (`ops_d1_bootstrap.py`, `ops_venue_study.py`, `ops_intraday_venue_recovery.py`), onboarding/classification sourcing, `infrastructure_ibkr_chunk_and_rate_limit_probe.py`, `services/backfill_feature_factory.py`, `src/api/routes/sse.py`, `src/providers/ibkr_adapter.py`.
- **Must-not-disturb:** the existing streaming method set on `DataProvider` (the protocol the dormant DAG expects), `DataProviderAdapter`, and `IBKRProvider`'s current method signatures. The design's answer is additive: the protocol gains a batch history surface alongside the streaming surface. Implementation options for the planner: extend `DataProvider` itself, or define a separate `HistoryProvider` protocol that leaves also satisfy (runtime_checkable protocols compose; `IBKRProvider` would satisfy both). Either satisfies the locked decision; the conformance test pins whichever is chosen. Note `fetch_historical_bars` already exists on the protocol (:101-108) with a too-narrow signature (no adjustment/window/verdict); the new surface supersedes or wraps it, and the streaming path's use of it (if any) must be checked before changing it.

### 5. todo 526 current state and exact scope

Status: pending, P3, corrected 2026-10-09 (.planning/todos/pending/526-per-tf-provider-floors-and-planner-root-fix.md). The original "planner root fix" premise is withdrawn: a dry run of the ten short names proved the planner already computes gap = `min(depth_days, proven_days, floor) - actual` (verified in code: `coverage_gap_days`, `_fetch_queue.py:423-438`, floor = max of fresh head and fresh confirmed empty_through, :587-593). Surviving scope, verbatim from the todo:
- Migrate `ohlcv_provider_head` PK to `(symbol, provider, timeframe)`.
- Seed per-TF floor rows from measured vendor floors (1d floor 2000-01-03, IBKR 5m floor 2006-07 measured).
- The queue's floor lookup (`floor()` closure, `_fetch_queue.py:587-593` fed by `_HEADS_SQL` :513-516) reads the per-timeframe row.
- Correctness bar: a before-and-after dry run shows identical planned work (no planned-span change, only fewer no-data discovery trips).

This phase's planner edit composes with (not duplicates) 526: the per-TF head migration and the provider-parameterized planner are the same refactor per the design's Sequencing section, and 526's "Done when" becomes a verification task inside this phase.

### 6. Kill-and-resume and the rename surface

**Kill-and-resume (documented safe):** resume state is the coverage ledger plus permanent bars; the fetcher has no `code_content_key` cell cache (design Sequencing section). Procedure for this phase: `sudo systemctl stop indicagent-ibkr-history-fetcher.timer indicagent-ibkr-history-fetcher.service` (check a run is not mid-item via logs/ibkr_history_fetcher_status.json and the journal), check the code diff (memory rule: restart-batch-job check-code-diff-first), deploy, restart the timer; the next fire resumes from coverage. The advisory lock dies with the process (session-level, _fetcher_lock.py docstring). The gotchas kill procedure's pg_stat_activity check (docs/reference/gotchas.md:31, :191) applies if a kill leaves a backend.

**Live drain state at research time (verified live 2026-10-09 ~16:00 UTC):** fetcher active and succeeding (status file: run 14:10-15:37 UTC, 22 items, 0 errors, 81,497 bars, lanes backfill 13 / gap_fill 4 / update 5). 5m coverage: 260 of 279 rows hold bars. `ohlcv_provider_head`: 703 ibkr rows; `ohlcv_empty_history`: 574 ibkr rows. Timer fires every 15 min (OnUnitInactiveSec).

**Everything the rename `ibkr_history_fetcher` -> `ohlcv_history_fetcher` touches (complete, verified):**
- `production/systemd/indicagent-ibkr-history-fetcher.service` and `.timer` (checked in) plus the root-owned live copies in `/etc/systemd/system/` (sudo cp + daemon-reload). Unit facts to preserve: Type=exec, WatchdogSec=1200, RuntimeMaxSec=18000, NotifyAccess=main, WATCHDOG=1 pings, Restart=no.
- `services/service_auditor.py:101` `_DAG_ORDER["indicagent-ibkr-history-fetcher"] = 8` and `:173` the oneshot list entry.
- No `alert.lag.*` key exists for the fetcher (grep-verified): it is a oneshot with `job_completed_total` only, so nothing to migrate there. (CLAUDE.md's "new service seeds alert.lag.*" applies to lag-emitting daemons; phase 189 established the oneshot precedent at priority 8.)
- `_fetcher_lock.py:31` `FETCHER_LOCK_NAME = "ibkr_history_fetcher"` — the advisory key is sha256 of the name (:40-43). Manual tools share it: ops_d1_bootstrap, ops_venue_study, ops_intraday_venue_recovery, the rate-limit probe, classification sourcing, onboard manifest (grep list in section 4). Rename the lock name only in the same commit as every tool, or keep the lock name and rename only code identifiers (safer; the lock name is operator-visible in pg_stat_activity as `lock:<name>:<holder>`).
- `services/bar_reconciliation_audit.py:736` `NIGHTLY_STATUS_FILE = logs/ibkr_history_fetcher_status.json` and the audit's `check_nightly_skipped` (:431-443) reads `status` from that file's payload — the audit does NOT match the job name, only `status == "success"`, so a renamed fetcher writing the same path keeps the audit working; renaming the path must move both writer and reader in one commit.
- Metric job label `job="ibkr-history-fetcher"` on `job_completed_total` and `OHLCV_COVERAGE_SLA_BREACHED_SERIES` (ibkr_history_fetcher.py:1151) — a rename starts a new label series (continuity break in dashboards; grep found no Grafana dashboard referencing it, so impact is nil today; note it anyway).
- Log file: `setup_service_logging` derives `logs/<snake_case_class>.log` -> `logs/ibkr_history_fetcher.log` becomes `logs/ohlcv_history_fetcher.log` (logrotate config `production/indicagent-logrotate.conf` may reference the old name; checked-in unit files and logrotate should be reviewed in the same task).
- Parsed strings: `ops_head_rerun.py:73` regex `fetch_run_id:\s*([0-9a-f-]{36})` and `:316` exact `LOCK_HELD_MESSAGE` match; `:44` imports LOCK_HELD_MESSAGE (so renaming the constant's value is the only risk, not its symbol).
- `ops_split_detect.py` and `services/split_detection.py` reference the fetcher (recorded_by / caller strings, :1038 `recorded_by=JOB`); a JOB rename changes the `recorded_by`/caller values written to corporate_action/integrity facts — check for string-matching consumers before renaming JOB.
- Tests: `test_ibkr_history_fetcher.py`, `test_fetcher_lock.py`, `test_ibkr_history_lock_boundary.py`, `test_head_rerun.py`, `test_ops_split_detect.py`, `test_bar_hold.py` all reference the name.

Recommendation for the planner: separate "code identifier rename" (mechanical, low risk) from "external identity rename" (systemd units, lock name, JOB label, status/log paths). The external identity rename is optional value; the design proposes the name but the glossary check is owed. Keeping `JOB`/lock/unit names stable and renaming only the class/module is the lower-risk cut and still satisfies the design's naming intent if the glossary check passes on the concept level.

### 7. Test surface (provider-parameterization and where new tests belong)

Existing, with sizes (lines):
- `tests/unit/scripts/test_ibkr_history_fetcher.py` (1,089) — fetcher orchestration; will need provider-parameterized fixtures or a leaf-fake.
- `tests/unit/scripts/test_fetch_queue.py` (679) — ranking, floors, lanes, parity; gains per-provider cases.
- `tests/unit/scripts/test_history_fetch_item.py` (1,283) and `test_history_fetch.py` (1,267) — IBKR item and helper mechanics; stay IBKR-scoped behind the leaf seam.
- `tests/unit/scripts/test_fetcher_lock.py`, `test_empty_history.py`, `test_empty_history_from_d1.py` — lock and empty-history ledger.
- `tests/unit/test_ohlcv_coverage_writer_boundary.py` (50), `test_ohlcv_coverage_migration_contract.py` (87), `test_backfill_status_retirement_migration_contract.py`, `test_fetcher_reconcile_parity_migration_contract.py`, `test_single_writer_registry.py` (entries :77 ohlcv_coverage, :105 ohlcv_empty_history, :111 ohlcv_provider_head — new/changed writers must update this registry or CI fails).
- `tests/integration/test_ohlcv_coverage_atomic_write.py`, `test_ingress_write_contract.py` — the in-transaction coverage write.
- Boundary pattern to extend: `tests/unit/test_market_data_ohlcv_boundary.py` (filesystem-grep allow-list style, CI-clean, no DB).

New tests this phase owes (design Enforcement): the protocol-conformance test (fixture mechanism is Claude's discretion; parameterize over leaf fakes now, real Alpaca leaf when 521 lands), the import-boundary test (services/scripts import the protocol, never a concrete leaf; same grep style), migration-contract tests for each migration in the family, and dry-run parity for 526's before/after bar.

### 8. Alpaca leaf landing state (todo 521 / indicagent-87)

Verified: `src/providers/` contains base.py, economic_source.py, fred.py, ibkr.py, ibkr_adapter.py, nyfed.py, yahoo.py — no alpaca.py on main and no branch carrying it (git branch -a). Todo 521 is pending/deferred behind a gate: the depth-build plan doc written first, then owner green-light. The lane's delivered artifacts so far are measured facts and scratch tooling, not the leaf:
- Measured REST mechanics: `scripts/research/alpaca_depth_scratch_pull.py` (pagination via `next_page_token`, `limit=10000`, `feed=sip`, `adjustment=split`, Basic rate 190 req/min vs documented 200, 429 with `retry-after`), full detail in `docs/plans/2026-10-09-alpaca-integration-pilot.md` (T1-T9 findings).
- Locked rulings the leaf implements: adjustment=split, RTH-window aggregates only, never Alpaca 1d bars, spinoff-class admission (MMM/PFE/TMUS/HON/LEN/IBM/O), 1m out of scope.
- APR: `threshold`-side `alpaca_basis` tolerance row landed (migration 463, commit e7ec5a7b4) as the T2 gate.

Plan consequence: step 2 (the refactor) must not import `alpaca.py`; the conformance test runs over a fixture set with IBKR as the only real leaf until the lane lands. Step 3 (canonical Alpaca load) keeps an explicit dependency on todo 521's leaf + policy docs (its dependency 1: the 5m multi-source policy doc must exist before the first canonical write).

### 9. Validation architecture

See the dedicated section below (nyquist_validation enabled).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Deterministic queue order | ad-hoc sorting per provider | the existing rank tuple + `queue_items` (`_fetch_queue.py:476-505`) with a provider field added | total order, dry-run/real parity already proven |
| Process singleton | lockfile, flock, or per-provider locks | `FetcherLock` (pg advisory, fail-fast) | crash-safe, operator-visible, shared by all history tools |
| Atomic bar+ledger writes | separate ledger updates | `persist_chunk_atomically` path + `upsert_coverage` in the same transaction | the ledger-can-never-describe-unwritten-bars invariant |
| No-data suppression | boolean emptiness | `ohlcv_empty_history` evidence rows + verdict object | already provider-keyed (migration 354) |
| Vendor rate limiting in the loop | loop sleeps per vendor | leaf-owned budget behind a common interface | IBKR pacing and Alpaca leaky-bucket are incommensurable; the loop must stay vendor-blind |
| Policy rows authoring | fetcher writing policy | existing `ops_source_policy.py` sole-writer (single-writer registry) | the fetcher becomes a policy reader only |

**Key insight:** phase 189 already solved the hard problems (single writer, atomic writes, deterministic ranking, kill-and-resume, lock singleton). This phase's risk is not mechanism; it is threading one new dimension (provider) through a working machine without disturbing the external strings other tools parse.

## Runtime State Inventory

Included because this phase renames a live service and re-keys ledger tables.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `ohlcv_coverage`: ~2.5k rows, PK (symbol,timeframe), no provider (migration 432); `ohlcv_provider_head`: 703 ibkr rows, PK (symbol,provider) (355); `ohlcv_empty_history`: 574 ibkr rows, already provider-keyed (354); live drain in progress (5m: 260/279 rows with bars) | migrations with explicit backfill labeling rules; provider_head PK migration + per-TF floor seeds; drain kill-and-resume under the new fetcher |
| Live service config | systemd unit+timer live at 15-min cadence (root-owned copies in /etc/systemd/system; checked-in twins in production/systemd/); logrotate config; D7 audit reads logs/ibkr_history_fetcher_status.json | rename tasks must edit checked-in files, sudo-install, daemon-reload, and keep writer+reader of the status file in step |
| OS-registered state | FetcherLock advisory key = sha256("ibkr_history_fetcher"), shared by 6+ manual tools; pg_stat_activity shows lock:<name>:<holder> | decide keep-vs-rename; if renamed, every tool in the same commit |
| Secrets/env vars | none new; IBKR gateway settings via `src/config/Settings` (never os.environ); Alpaca keys live in `.env` read by the scratch pull and later the leaf (521's isolation job) | none this phase |
| Build artifacts | none (pure-Python repo, no compiled artifacts); logs/ibkr_history_fetcher.log* rotates | new log file name on rename; logrotate review |

## Common Pitfalls

### Pitfall 1: Breaking dry-run/real-run parity while parameterizing
**What goes wrong:** the queue's value is that `--dry-run` (reads only, no lock, no provider connection) predicts the real run's order exactly (`prepare()` is shared, ibkr_history_fetcher.py:625-687). Per-provider config threaded partially (e.g. floors per-provider but budgets global) silently diverges them.
**Why it happens:** provider data lands in some read paths and not others.
**How to avoid:** 526's before/after dry-run parity bar extended to the whole refactor: identical planned spans (plus the new provider column) across the cutover dry run.
**Warning signs:** dry-run TSV rows whose lane/gap columns shift without a policy or data change.

### Pitfall 2: Renaming external identity strings piecemeal
**What goes wrong:** the advisory lock key is sha256 of the name; a fetcher renamed in one commit and a manual ops tool in another can both hold "the" lock simultaneously — the one-writer invariant dies silently.
**How to avoid:** one commit for the whole external-identity set, or don't rename the lock/JOB at all (recommended cut above).
**Warning signs:** `lock_held` statuses with no visible holder, or two pg_stat_activity `lock:` rows with different names doing history work.

### Pitfall 3: The coverage backfill mislabeling pre-swap 1d history
**What goes wrong:** stamping all existing rows `provider='ibkr'` reads as an IBKR vendor claim over Tradier-era 1d bounds and 449-lane bars.
**How to avoid:** state the labeling rule in the migration comments (stored-state rollup under the canonical tier, not a per-vendor provenance claim); the per-provider vendor claims live in the per-provider tier and `ohlcv_load.source`.
**Warning signs:** D7 vendor-agreement checks suddenly attributing 2006-2015 Tradier-era bars to IBKR.

### Pitfall 4: Letting the 1d due rule leak into providers without 1d
**What goes wrong:** `_LATEST_DAILY_ANSWER_SQL` assumes every provider answers SMART TRADES 1d; an Alpaca lane would either plan 1d items (violating "never Alpaca 1d bars") or error on missing request shapes.
**How to avoid:** the daily session-calendar due rule is per-provider planner data; the Alpaca lane simply has no 1d items (policy rows never create them).
**Warning signs:** queue items with provider=alpaca, timeframe=1d.

### Pitfall 5: Editing imported modules under a live run
**What goes wrong:** the fetcher runs every 15 minutes; a deploy during an item aborts it mid-chunk. (Not a code_content_key loss — the fetcher has no cell cache — but an interrupted item.)
**How to avoid:** stop timer+service first, verify via status file + journal, then deploy; the gotchas kill procedure covers orphaned backends.
**Warning signs:** a status file with an old started_at while the code on disk is newer.

## Code Examples

### The rank tuple to generalize (verified current)
```python
# Source: scripts/infrastructure/backfill/_fetch_queue.py:463-473
key = (
    row.consecutive_failures > config.max_consecutive_failures,  # per-provider
    row.timeframe != DAILY_TF,                                   # per-provider (IBKR-only 1d)
    not sla_breach,
    tf_class,
    -gap,
    -effective_stale,
    row.symbol,
    row.timeframe,                                               # + provider, or key by (provider, ...)
)
```

### The rebuild filter to generalize
```python
# Source: services/ohlcv_coverage_writer.py:245-248
_REQUEST_FILTER = (
    "WHERE route = 'SMART' AND what_to_show = 'TRADES' "
    "AND outcome IN ('bars', 'no_data', 'timeout', 'failed')"
)
```
Per-provider rebuild inputs: IBKR keeps this shape; Alpaca's shape (endpoint + adjustment + feed recorded on its ohlcv_request/observation rows) becomes its own filter constant supplied by the leaf's planner data.

### The leaf seam that already exists
```python
# Source: scripts/infrastructure/backfill/ibkr_history_fetcher.py:519-528
def __init__(self, ..., provider_factory: Callable[[], Any] | None = None, ...):
    self._provider_factory = provider_factory or self._default_provider
```
The constructor seam pattern (one dependency per seam, documented :507-514) is the established extension style; a provider registry/config mapping slots in here without a framework (design Non-goals: no plugin registry).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Nightly backfill + lane scripts + ResourceLease | Single IBKR fetcher + FetcherLock | phase 189 (2026-10-06 cutover) | this phase generalizes it |
| Todo 526 "planner root fix" (expected-domain rework) | Withdrawn; only per-TF provider_head PK survives | 2026-10-09 dry-run correction | phase scope shrank; planner edit is shared, not a rework |
| Interim separate Alpaca oneshot (design rev 1) | Deleted in rev 2; Alpaca load = lanes in the unified fetcher | 2026-10-09 | no second writer, ever |
| provider_head per symbol | per (symbol, provider, timeframe) | todo 526, this phase | fewer no-data discovery trips |

**Deprecated/outdated:** the two-tier history ResourceLease (retired 189-08, `_fetcher_lock.py:15-16`); Tradier as 1d primary (owner 2026-10-07; loader deleted 185-48, identifiers kept in sources.py:38-39 for stored history).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | No Grafana dashboard or alertmanager rule references the `ibkr-history-fetcher` job label (grep of production/ found none) | 6. rename surface | a dashboard silently loses its series after a JOB rename; low impact, alerting deliberately unwired |
| A2 | Alpaca lane item creation can be driven purely by policy rows + scopes without new candidate-source machinery | 1, pitfalls | if 521's policy doc needs per-provider scope keys (default_scopes is provider-neutral today), the planner adds an `infra.<provider>.default_scopes` or equivalent; discoverable at plan time |
| A3 | `setup_service_logging` derives the log filename from the class name, so renaming the class changes the log path | 6 | wrong only if the helper takes an explicit override; verified pattern from CLAUDE.md ("structlog -> logs/<snake_case_class_name>.log"), not re-read this session |
| A4 | depth_days may need a provider dimension for Alpaca's 2016-forward scope | 1 | alternative: policy rows or a per-provider depth key; either satisfies the design; planner picks |

## Open Questions

All three resolved at plan time (2026-10-09 revision); pointers to the adopting plans inline.

1. **External identity rename: full or code-only?** — RESOLVED: code-only, adopted in plan 190-05 (code identifiers rename; FETCHER_LOCK_NAME, JOB, status path, unit filenames frozen with decision comments).
   - What we know: the design proposes the name; the rename surface (section 6) is wide but enumerable; the lock-name rename is the one genuinely risky piece.
2. **Coverage provider labeling rule for pre-existing rows.** — RESOLVED: stored-state labeling under the ibkr label, adopted in plan 190-02 Task 1 (migration 464 header + COMMENT ON COLUMN restate the rule; vendor claims stay in ohlcv_load.source and the per-provider tier).
   - What we know: existing rows are IBKR-era stored-state rollups (section 2 backfill hazard).
3. **Where the batch history surface lives: extend `DataProvider` or a sibling `HistoryProvider` protocol.** — RESOLVED: sibling runtime_checkable protocol, adopted in plan 190-01 Task 1 (DataProvider byte-identical; conformance suite pins the new surface; 190-04 dispatches through it).
   - What we know: `DataProvider` already carries `fetch_historical_bars` with a too-narrow signature (:101-108); the dormant streaming DAG expects the current method set.
   - Recommendation adopted as stated; the conformance test pins it (plan 190-01).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL (indicagent) | all ledger work | Yes (verified live queries) | TimescaleDB, live | - |
| ib-gateway container | IBKR leaf fetches | per CLAUDE.md at 127.0.0.1:7497; drain succeeding | - | - |
| systemd (root via sudo) | unit rename/relaunch | Yes (units listed) | - | - |
| pytest venv | validation | Yes (9.0.3) | - | - |
| httpx | Alpaca leaf (521) | Yes (0.28.1) | - | - |
| Alpaca keys | step 3 | present in .env (scratch pull ran) | - | - |

Missing dependencies with no fallback: none.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 (`.venv/bin/pytest`) |
| Config file | repo-level pytest config; unit tests are CI-clean (no DB, no network) |
| Quick run command | `.venv/bin/pytest tests/unit/scripts/test_fetch_queue.py -q` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| P190-queue | per-provider ranking, floors, exclusion | unit | `.venv/bin/pytest tests/unit/scripts/test_fetch_queue.py -q` | yes, extend |
| P190-fetcher | provider-parameterized orchestration, lanes incl. new provider lane | unit | `.venv/bin/pytest tests/unit/scripts/test_ibkr_history_fetcher.py -q` | yes, extend |
| P190-ledger | provider-labeled canonical writes; per-provider failures; per-provider rebuild inputs | unit (writer contract) | `.venv/bin/pytest tests/unit/test_ohlcv_coverage_writer_boundary.py tests/unit/test_ohlcv_coverage_migration_contract.py -q` | yes, extend + new migration contract |
| P190-writers | single-writer registry stays complete | unit | `.venv/bin/pytest tests/unit/test_single_writer_registry.py -q` | yes, update entries |
| P190-conformance | both leaves pass protocol conformance (verdict object, page boundaries, budget) | unit | new `tests/unit/providers/test_history_conformance.py` | no, Wave 0/plan task |
| P190-boundary | services/scripts import protocol, never a concrete leaf | unit (grep style) | new test in `tests/unit/test_market_data_ohlcv_boundary.py` pattern | no, plan task |
| P190-parity | 526 bar: dry-run before/after identical planned spans | measured dry-run | `.venv/bin/python scripts/infrastructure/backfill/ohlcv_history_fetcher.py --dry-run` (old vs new, diff TSVs) | manual step, scripted diff |
| P190-migration | migration family applies via psql -f, backfills label correctly | integration | `tests/integration/test_ohlcv_coverage_atomic_write.py` + live psql -f apply committed same-breath | partial, extend |
| P190-lock | lock singleton intact across the rename decision | unit | `.venv/bin/pytest tests/unit/scripts/test_fetcher_lock.py tests/unit/test_ibkr_history_lock_boundary.py -q` | yes |

### Sampling Rate
- Per task commit: the touched module's quick command above.
- Per wave merge: `.venv/bin/pytest tests/unit/ -q`.
- Phase gate: full suite green; the dry-run parity diff attached before the drain kill-and-resume; no edits under `src/intelligence/research/` or `statistics/` are expected (if any sneak in, `repro_frozen` must report bit-identical).

### Wave 0 Gaps
- [ ] Conformance test skeleton + leaf fixture mechanism (parameterized over a fake leaf first)
- [ ] Provider import-boundary test file (grep-style, allow-list seeded with today's legitimate IBKRProvider importers: the fetcher family and the ops tools that must keep concrete access until migrated)
- [ ] Migration-contract test files for the new migration family (pattern: tests/unit/test_ohlcv_coverage_migration_contract.py)

## Security Domain

security_enforcement is not set in .planning/config.json, so it is enabled by default. This phase is internal infrastructure with no new network exposure; the applicable controls:

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|------------------|
| V2 Authentication | no | - (no user auth surface) |
| V3 Session Management | no | - |
| V4 Access Control | yes | Postgres roles: coverage writes only under `SET LOCAL ROLE bar_derivation_writer` (migration 432 grants); preserve for the new per-provider writes |
| V5 Input Validation | yes | APR-sourced numerics validated at load (`load_queue_config` raises on the timeout/window coupling); verdict/status CHECK constraints in DDL |
| V6 Cryptography / Secrets | yes | Credentials stay leaf-isolated: IBKR gateway is localhost-only; Alpaca keys in `.env`, read only inside the leaf, never logged (the scratch pull's pattern); no secrets in APR/config_state |

### Known Threat Patterns for this stack
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Silent gap erasure (vendor A's head hides vendor B's gap) | Tampering (data) | two-tier ledger; planner reads per-provider tier only (design) |
| Concurrent hypertable writers deadlock | DoS | one fetcher process, one writer connection, lanes not lock contenders |
| Lock-name drift letting two fetchers run | Tampering | single-commit rename discipline or keep the lock name |
| Credential leakage via logs | Information disclosure | leaf-owned credentials, structlog discipline, never log request headers |

## Sources

### Primary (HIGH confidence)
- Direct reads this session: scripts/infrastructure/backfill/ibkr_history_fetcher.py, _fetch_queue.py, _fetcher_lock.py, _history_fetch.py/_history_fetch_item.py (structure), services/ohlcv_coverage_writer.py, services/service_auditor.py, services/bar_reconciliation_audit.py (status-file read), src/providers/base.py, src/providers/__init__.py, src/providers/CLAUDE.md, src/intelligence/bars/sources.py, scripts/research/alpaca_depth_scratch_pull.py, scripts/ops/bars/ops_head_rerun.py (parse points), production/migrations/432, 354, 355, 463, tests/unit/ surfaces, tests/unit/test_single_writer_registry.py, tests/unit/test_market_data_ohlcv_boundary.py, .planning/todos/pending/526 and 521, 190-CONTEXT.md, docs/plans/2026-10-09-provider-history-plane-unification-design.md
- Live system: `systemctl list-units/list-unit-files/cat`, `logs/ibkr_history_fetcher_status.json`, live psql counts (ohlcv_coverage/provider_head/empty_history), `git branch -a`, venv imports (httpx 0.28.1, pytest 9.0.3)

### Secondary (MEDIUM confidence)
- docs/plans/2026-10-09-alpaca-integration-pilot.md and 521 doc for Alpaca vendor facts (adjustment=split, 200 req/min Basic, RTH convention) — cited, not re-measured this session

### Tertiary (LOW confidence)
- None material; A1-A4 in the assumptions log are the only non-re-verified claims.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; all components verified present.
- Architecture: HIGH — the design is owner-approved and every claimed code surface was read this session with file:line.
- Pitfalls: HIGH — derived from verified code paths and documented operational memory (drain, shared checkout, lock keying).

**Research date:** 2026-10-09
**Valid until:** 2026-11-08 (stable; re-check drain progress and 521 lane status at plan time, both move fast)
