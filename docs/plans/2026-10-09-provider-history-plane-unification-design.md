# Provider history plane unification: one fetcher, N leaves, policy at the capture layer

Status: approved design, pre-plan (rev 2 after AGY design critique)
Author: Claude (session 2026-10-09), discussed and approved by Brandon
Informed by: `docs/plans/2026-10-02-ibkr-history-fetch-consolidation-design.md` (phase 189),
`docs/plans/2026-10-09-alpaca-5m-admission-build.md` (todo 521),
`docs/plans/2026-10-09-alpaca-integration-pilot.md`,
todo 526 (per-TF provider floors and planner root fix),
AGY design critique (2026-10-09; findings verified against code before adoption)

## Problem

Two market-data vendors are in flight on divergent paths. IBKR history fetching was
consolidated in phase 189 into one timeframe-agnostic fetcher, but the fetcher calls
`IBKRProvider` directly and its planner encodes IBKR-specific semantics (150-day chunk
ceiling, inter-item pause, latency SLA profile). The Alpaca admission build (todo 521)
mandates a leaf writing through the existing capture contract, and without a deliberate
seam it would grow a second fetch path: its own loop, its own ledger handling, its own
retry and no-data semantics. That is the exact fork phase 189 deleted for IBKR alone,
now pending at vendor scale.

The unification goal, and the success criterion: adding a vendor (or any third-party
data source) is a new leaf module, policy rows, and APR seeds. Zero new services, zero
new write paths, zero new ledger machinery.

Relation to the 189 design: that design excluded a provider abstraction as YAGNI,
conditioned on "there is no second OHLCV provider today, and IBKR's single-connection
constraints are not representative of a REST vendor". The condition is now false:
Alpaca is admitted, is REST, and has materially different rate-limit and no-data
semantics. The exclusion's rationale is preserved here by keeping everything
IBKR-specific inside the IBKR leaf and per-provider planner data, never in the loop.

## Design

### Three layers

**Ring 1 leaves (`src/providers/`).** The `DataProvider` protocol
(`src/providers/base.py`) gains a batch history surface alongside the streaming
surface: window-scoped `fetch_ohlcv` requests, returning normalized `OHLCVBar`
observations and a normalized no-data verdict. Leaves own only their API mechanics:
credentials isolation, pagination, their native rate-limit model, RTH and adjustment
knobs as declared request parameters. Policy never enters a leaf.

Each leaf interface point, so the plan has no undefined seams:

- *Pagination:* caller-driven and window-scoped. A leaf yields pages within one
  request's span; the queue item re-drives from the coverage ledger on resume.
  Cursors are never long-lived state; resumability comes from coverage, not tokens.
- *Rate limits:* the leaf owns its native model (IBKR pacing pauses and socket stalls;
  Alpaca leaky-bucket 429s with reset headers) behind a common budget interface: the
  planner passes a deadline and a request budget, the leaf enforces its own model
  inside it. APR keys (`infra.<provider>.*`) seed the budgets.
- *Symbology:* queue items are keyed by instrument/symbol from the registry. Each
  leaf resolves its own vendor symbology (IBKR conId and trading class from
  `contract_details`; REST tickers with share-class delimiter handling) at item
  start; resolution failures are item-level errors, never silent skips.
- *Adjustment:* adjustment and window conventions (RTH, `adjustment=split`) are
  declared in the request and recorded in lineage, so a bar's provenance states both
  the vendor and the transform.

Leaves:

- `src/providers/ibkr.py` (exists, unchanged in role)
- `src/providers/alpaca.py` (new; this is todo 521's loader leaf, not a parallel build)
- `src/providers/economic_source.py` (exists: `EconomicSource` protocol, FRED/NYFed
  leaves; the per-domain precedent this design generalizes, not a surface to merge)

**Ring 1 policy (`src/intelligence/bars/`).** Two distinct mechanisms that must not
be conflated:

- *Planning/authoring assignment:* `bar_source_policy` per-name-per-TF rows decide
  which vendor's queue items are created for a span, and which source may issue a
  revision. A revision corrects only its own source's rows.
- *Write arbitration:* the grid's `UNIQUE (timestamp, symbol, timeframe)` with
  first-writer-stays stays the sole write gate. There is no span re-arbitration and
  no cross-source restatement machinery; once a span is written, the other vendor's
  bars for it are evidence for D7 agreement checks, not competitors. Divergence
  beyond tolerance surfaces through the existing d2-v3 restate of the authoring
  source's own rows.

D7 vendor-agreement checks extend to a second tape (todo 521 dependency 2). RTH and
`adjustment=split` decisions are recorded here, per the 2026-10-09 rulings (never
Alpaca 1d bars; RTH 5m only).

**The service.** One fetcher process, one queue, one writer connection. Queue items
become `(provider, symbol, timeframe, span)`, and per-provider planner semantics
(chunk ceiling, latency profile, inter-item pause, budget) come from per-provider
heads with their per-TF floors (todo 526) and `infra.<provider>.*` APR keys.
`BaseBatch` and the `OhlcvObservationWriter` capture contract are already
mechanism-generic and are unchanged.

Proposed name (glossary check owed at plan time): `ohlcv_history_fetcher` /
`OHLCVHistoryFetcher`, matching the `ohlcv_coverage` ledger's mechanism-generic
naming. Note for that check: the taxonomy's daemon suffix list has no `Fetcher`, but
this is a `BaseBatch` batch job in `scripts/infrastructure/backfill/`, not a Ring 2
daemon, and `IbkrHistoryFetcher` is the live precedent. Leaves stay
`src/providers/<vendor>.py`.

### Two-tier ledger (the correction)

`ohlcv_coverage`'s key is `(symbol, timeframe)` with no provider dimension. Keeping
it cross-provider would let one vendor's writes clobber the other's coverage state
(silent gap erasure: Alpaca's 2016-forward head would make IBKR's planner compute
zero gap for 2006-2016) and one vendor's outage quarantine the other's symbols
(shared `consecutive_failures`). The ledger architecture is therefore two-tier:

- **Per-provider tier:** todo 526's provider heads (per-TF proven-days, floors) are
  the planning source of record. Each vendor's head moves only from its own fetches,
  and `consecutive_failures` and quarantine state are per-provider. One vendor's
  outage can never rank or exclude the other vendor's items.
- **Canonical tier:** `ohlcv_coverage` remains the stored-state ledger written
  in-transaction with the bars, but its writer becomes provider-aware: rows record
  the authoring source, and the rebuild path's IBKR-specific request filter
  (`route = 'SMART' AND what_to_show = 'TRADES'`) generalizes into per-provider
  rebuild inputs.

The planner reads the per-provider tier only. It never derives a vendor's gap from
another vendor's coverage.

### Empty-history verdicts carry their evidence

A normalized no-data verdict is a verdict object, not a boolean: status plus vendor
evidence (IBKR's confirming-chunk count; Alpaca's single authoritative empty
response), so `ohlcv_empty_history` keeps its `verified_from` / `empty_through` /
`n_confirming_chunks` confidence semantics per vendor. The planner may weight
evidence differently per vendor (Alpaca's 404 is one observation; IBKR's
n-chunk emptiness is n observations) without either collapsing into the other.

### Concurrency is structural

One fetcher process, one queue, one advisory-lock singleton. "Never run both drains
at once" is a property of the system. Lanes (IBKR 1d nightly update, the 5m drain,
Alpaca's all-names load, and todo 521's nightly T4 verifier with its basis
comparison) are priorities inside the same loop, so the single writer connection on
the hypertable is preserved and the concurrent-writer deadlock class never arises.
The `lock_held` fail-fast path exists for stray invocations of the same service, not
for lanes; lanes cannot be starved because they are not lock contenders.

The IBKR socket constraint (`FetcherLock`'s origin) lives inside the IBKR leaf and
its budget; the process-level singleton guards the one-writer invariant, which is
provider-independent.

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
  per-provider heads, admission, and D7 checks.
- A non-OHLCV source (economic series, dividends) implements its domain's protocol
  (`EconomicSource` exists; others follow the same shape) and its domain's writer.
- The cost of a new vendor is: one leaf module, `bar_source_policy` rows, per-provider
  head seeds, APR keys under `infra.<vendor>.*`, and a conformance-test fixture set.
  Nothing else.

## Sequencing

Resume state for the fetcher is the coverage ledger and permanent bars; the fetcher
carries no `code_content_key` cell cache. Kill-and-resume is documented safe, so the
unification does not need to wait out the drain:

1. **Leaf first (todo 521's lane, indicagent-87):** `alpaca.py`, the policy docs, and
   the conformance tests land as new modules touching no fetcher import. The leaf's
   pilot and basis verification proceed against scratch; no canonical write.
2. **Unify (one phase, with 526):** generalize the fetcher and land the two-tier
   ledger as the same refactor, since the planner edit is shared. The drain
   kill-and-resumes under the unified fetcher and continues from coverage.
3. **Canonical Alpaca load:** runs as queue lanes in the unified fetcher, after the
   drain or interleaved by the planner's priorities, through leaf, capture contract,
   and basis admission. The interim separate Alpaca oneshot that an earlier revision
   of this design proposed is deleted: it would have been a second writer on the
   hypertable and a second fetch path, the two things this design exists to prevent.

## Enforcement

- A protocol-conformance test both history leaves must pass (normalized verdicts and
  evidence fields, observation shape, page boundaries, budget interface). This is the
  artifact that makes "a vendor is a leaf" a checked fact.
- A boundary test in the `test_market_data_ohlcv_boundary.py` pattern: services and
  scripts may import the protocol, never a concrete leaf.
- Ring rule holds: leaves take no imports from `services/` or
  `src/intelligence/`; policy code takes no vendor credentials. (`src/providers/`
  is Ring 1 per `naming-system.md` §2; purely generic leaf-adjacent helpers may
  graduate to Ring 0 only by passing the portability test.)

## Non-goals

- No provider plugin registry or dynamic discovery; two-to-three vendors is a config
  mapping, not a framework.
- No unification of the old v2.x remainder (`pipeline/`, `plugins/`, `trading/`);
  todo 509 owns its retirement.
- No change to the write contract (new/changed rows only, old values recorded), the
  admission machinery, or first-writer-stays; this design composes them.

## Open items (resolved at plan time)

- Glossary entries for the unified fetcher name, the two-tier ledger vocabulary, and
  the per-domain protocol pattern; pre-commit glossary check must stay clean.
- The per-provider ledger migration: provider labeling on `ohlcv_coverage` rows and
  per-provider quarantine/failure state alongside 526's provider heads.
- The exact APR key list per provider, seeded from measured values (IBKR pause,
  Alpaca Basic rate budget, per-provider SLA thresholds) with `[measured]` provenance.
- `ohlcv_empty_history` gaining a provider dimension (per-vendor verdict rows).
