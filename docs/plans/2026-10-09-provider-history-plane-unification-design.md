# Provider history plane unification: one fetcher, N leaves, policy at the capture layer

Status: approved design, pre-plan
Author: Claude (session 2026-10-09), discussed and approved by Brandon
Informed by: `docs/plans/2026-10-02-ibkr-history-fetch-consolidation-design.md` (phase 189),
`docs/plans/2026-10-09-alpaca-5m-admission-build.md` (todo 521),
`docs/plans/2026-10-09-alpaca-integration-pilot.md`,
todo 526 (per-TF provider floors and planner root fix)

## Problem

Two market-data vendors are in flight on divergent paths. IBKR history fetching was
consolidated in phase 189 into one timeframe-agnostic fetcher, but the fetcher calls
`IBKRProvider` directly and its planner encodes IBKR-specific semantics (150-day chunk
ceiling, inter-item pause, latency SLA profile). The Alpaca admission build (todo 521)
mandates a Ring 0 leaf writing through the existing capture contract, and without a
deliberate seam it would grow a second fetch path: its own loop, its own ledger
handling, its own retry and no-data semantics. That is the exact fork phase 189
deleted for IBKR alone, now pending at vendor scale.

The unification goal, and the success criterion: adding a vendor (or any third-party
data source) is a new leaf module, policy rows, and APR seeds. Zero new services, zero
new write paths, zero new ledger machinery.

## Design

### Three layers, ring-clean

**Ring 0 leaves (`src/providers/`).** The `DataProvider` protocol
(`src/providers/base.py`) gains a batch history surface alongside the streaming
surface: window-scoped `fetch_ohlcv` requests, page/token-aware, returning the same
normalized `OHLCVBar` observations and a normalized no-data verdict (IBKR "empty
history" and Alpaca 404/no-data must be indistinguishable above the leaf). Each leaf
owns only its API mechanics: credentials isolation (like ib_async today), pagination,
rate-limit budget passed in as a parameter, RTH and adjustment knobs as arguments.
Policy never enters a leaf.

Leaves:

- `src/providers/ibkr.py` (exists, unchanged in role)
- `src/providers/alpaca.py` (new; this is todo 521's loader leaf, not a parallel build)
- `src/providers/economic_source.py` (exists: `EconomicSource` protocol, FRED/NYFed
  leaves; the per-domain precedent this design generalizes, not a surface to merge)

**Ring 1 policy (`src/intelligence/bars/`).** Span ownership and vendor agreement
live here, as data and docs, not code branches:

- `bar_source_policy` per-name-per-TF rows decide which vendor wins a span once both
  hold real data (the Tradier/IBKR precedent, extended to 5m; todo 521 dependency 1).
- D7 vendor-agreement checks extend to a second tape (todo 521 dependency 2).
- RTH-window aggregation and `adjustment=split` remain authoring decisions recorded
  here, per the 2026-10-09 rulings (never Alpaca 1d bars; RTH 5m only).

**Ring 2 service.** One fetcher. `IbkrHistoryFetcher` generalizes: queue items gain a
provider dimension (`(provider, symbol, timeframe, span)`), and per-provider planner
semantics (chunk ceiling, latency profile, inter-item pause, budget) come from
`provider_head` with its per-TF provider floors (todo 526) and `infra.<provider>.*`
APR keys. `BaseBatch`, the `pg_try_advisory_lock` singleton, the `ohlcv_coverage`
ledger written in-transaction, and the `OhlcvObservationWriter` capture contract are
already mechanism-generic and are unchanged by definition.

Proposed name (glossary check owed at plan time): `ohlcv_history_fetcher` /
`OHLCVHistoryFetcher`, matching the `ohlcv_coverage` ledger's mechanism-generic
naming. Leaves stay `src/providers/<vendor>.py`.

### Concurrency is structural

The single advisory-lock singleton makes "never run both drains at once" a property of
the system instead of a procedural rule. Per-vendor rate budgets stay separate APR
keys (`infra.ibkr.*`, `infra.alpaca.*`). The SLA-preemption band gains a provider
column. The nightly picture after unification:

- IBKR 1d update lane preempts the drain inside the same loop, as today.
- Alpaca's nightly T4 leaf verifier (todo 521 item 6: pull the same window after the
  IBKR backfill, run the basis comparison, d2-v3 restates on divergence) is a second
  queue consumer with its own lane, not a second daemon.

### What deliberately does not unify

- **Streaming.** Alpaca live-streaming, when it comes, is a leaf implementing the same
  `DataProvider` protocol against the existing (dormant) streaming DAG. The streaming
  path never touches the database directly; that invariant is untouched.
- **Execution.** The broker client for todo 522 reuses only the leaf pattern
  (credentials isolation, module shape). It is not a data provider and never joins the
  history plane.
- **Economic sources.** `EconomicSource` already IS the per-domain pattern
  (protocol + FRED/NYFed leaves). It is precedent, not a merge target.

### Extensibility contract

New data sources enter through a per-domain protocol, never a bespoke path:

- A market-data vendor implements the OHLCV history surface (and optionally the
  streaming surface) and is immediately available to the unified fetcher's queue,
  ledger, admission, and D7 checks.
- A non-OHLCV source (economic series, dividends) implements its domain's protocol
  (`EconomicSource` exists; others follow the same shape) and its domain's writer.
- The cost of a new vendor is: one leaf module, `bar_source_policy` rows, APR seeds
  under `infra.<vendor>.*`, and a conformance-test fixture set. Nothing else.

## Sequencing (the drain constraint)

The fetcher is a fingerprinted batch writer mid-run on the IBKR 5m drain; editing any
module it imports changes `code_content_key` and discards every completed drain cell
(260 names banked at ~88 req/h). The unification therefore lands in two steps:

1. **Now, inside todo 521's lane (indicagent-87):** the Alpaca leaf and the Ring 1
   policy docs land as new modules, touching no fetcher import. The 521 all-names
   load runs as its own oneshot through the shared leaf, the existing capture
   contract, and basis admission, so it lands canonical from day one. The research
   scratch pull stays scratch.
2. **After the drain completes** (or a deliberate kill-and-resume, owner-ordered):
   fold both providers into `ohlcv_history_fetcher`, retire the temporary Alpaca
   oneshot, and land 526's per-TF provider floors in the same window since the
   planner edit is the same refactor. The end state is one service; the interim is
   two entry points sharing leaves, capture, and policy.

## Enforcement

- A protocol-conformance test both history leaves must pass (normalized no-data,
  observation shape, page boundaries, budget respect). This is the artifact that
  makes "a vendor is a leaf" a checked fact.
- A boundary test in the `test_market_data_ohlcv_boundary.py` pattern: services and
  scripts may import the protocol, never a concrete leaf.
- Ring rule holds: leaves take no imports from `services/` or
  `src/intelligence/`; policy code takes no vendor credentials.

## Non-goals

- No provider plugin registry or dynamic discovery; two-to-three vendors is a config
  mapping, not a framework.
- No unification of the old v2.x remainder (`pipeline/`, `plugins/`, `trading/`);
  todo 509 owns its retirement.
- No change to the write contract (new/changed rows only, old values recorded), the
  ledger, or admission machinery; this design composes them.

## Open items (resolved at plan time)

- Glossary entries for the unified fetcher name and the per-domain protocol pattern;
  pre-commit glossary check must stay clean.
- The exact APR key list per provider, seeded from measured values (IBKR pause,
  Alpaca Basic rate budget, per-provider SLA thresholds) with `[measured]` provenance.
