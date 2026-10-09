# Phase 190: Provider history plane unification - Context

**Gathered:** 2026-10-09
**Status:** Ready for planning
**Source:** PRD Express Path (docs/plans/2026-10-09-provider-history-plane-unification-design.md, rev 2, owner-approved; AGY-reviewed)

<domain>
## Phase Boundary

Unify all market-data vendor history fetching into one multi-provider fetcher process.
The IBKR fetcher (phase 189) generalizes: queue items gain a provider dimension,
per-provider heads (todo 526) become the planning source of record, vendor API mechanics
retreat into leaves under the shared `DataProvider` protocol, and span-ownership policy
stays at the capture layer. The IBKR 5m drain kill-and-resumes under the unified fetcher;
the canonical Alpaca load (todo 521) runs as lanes in the same loop. Success criterion:
adding a vendor is a new leaf module, policy rows, and APR seeds; zero new services, zero
new write paths, zero new ledger machinery.

Out of scope: streaming (dormant DAG unchanged; Alpaca live-streaming is a later leaf),
execution (todo 522 reuses only the leaf pattern), economic sources (`EconomicSource` is
precedent, not a merge target), the v2.x remainder (todo 509), and the Alpaca leaf module
itself plus its policy docs (todo 521's lane, indicagent-87, lands first as step 1).

</domain>

<decisions>
## Implementation Decisions

### Layering
- Ring 1 leaves (`src/providers/<vendor>.py`): `ibkr.py` unchanged in role, `alpaca.py`
  from todo 521's lane. Leaves own credentials isolation, pagination, their native
  rate-limit model, RTH/adjustment knobs as declared request parameters. Policy never
  enters a leaf.
- Leaf interface contract: caller-driven window-scoped pagination (cursors are never
  long-lived state; resumability comes from coverage, not tokens); leaf owns its native
  rate-limit model behind a common budget interface (planner passes deadline + request
  budget); queue items keyed by registry instrument/symbol with leaf-resolved vendor
  symbology (resolution failures are item-level errors, never silent skips); adjustment
  and window conventions declared in the request and recorded in lineage.

### Two-tier ledger (the AGY correction)
- Per-provider tier: todo 526's provider heads (per-TF proven-days, floors) are the
  planning source of record; `consecutive_failures` and quarantine state are
  per-provider. One vendor's outage can never rank or exclude the other vendor's items.
- Canonical tier: `ohlcv_coverage` stays the stored-state ledger written
  in-transaction with the bars, provider-labeled; its rebuild path's IBKR-specific
  request filter (`route = 'SMART' AND what_to_show = 'TRADES'`) generalizes into
  per-provider rebuild inputs.
- The planner reads the per-provider tier only; it never derives a vendor's gap from
  another vendor's coverage.

### Policy vs write arbitration
- `bar_source_policy` per-name-per-TF rows decide which vendor's queue items are
  created for a span and which source may issue a revision; a revision corrects only
  its own source's rows.
- The grid's `UNIQUE (timestamp, symbol, timeframe)` with first-writer-stays stays the
  sole write gate. No span re-arbitration, no cross-source restatement. Divergence
  surfaces through D7 vendor-agreement checks and d2-v3 restate of the authoring
  source's own rows. D7 extends to a second tape (todo 521 dependency 2).

### Empty-history verdicts
- A normalized no-data verdict is a verdict object: status plus vendor evidence (IBKR
  confirming-chunk count; Alpaca single authoritative empty response). The planner may
  weight evidence per vendor. `ohlcv_empty_history` keeps its confidence semantics
  per vendor (provider dimension owed).

### Service and concurrency
- One fetcher process, one queue, one writer connection, one advisory-lock singleton.
  Lanes (IBKR 1d nightly update, 5m drain, Alpaca all-names load, todo 521 nightly T4
  verifier) are priorities inside the same loop, never lock contenders. The IBKR socket
  constraint lives inside the IBKR leaf and its budget.
- Proposed name `ohlcv_history_fetcher` / `OHLCVHistoryFetcher` (glossary check at plan
  time; `IbkrHistoryFetcher` is live precedent, this is a `BaseBatch` batch job, not a
  Ring 2 daemon).

### Sequencing
- Step 1 (not this phase): Alpaca leaf + policy docs + conformance tests land via todo
  521's lane as new modules touching no fetcher import; pilot/verification against
  scratch only, no canonical write.
- Step 2 (this phase): generalize the fetcher and land the two-tier ledger as one
  refactor (shared planner edit with todo 526); the drain kill-and-resumes under the
  unified fetcher and continues from coverage (resume state is the coverage ledger and
  permanent bars; the fetcher has no `code_content_key` cell cache).
- Step 3 (this phase, gated on the drain): canonical Alpaca load runs as queue lanes
  in the unified fetcher through leaf, capture contract, and basis admission. No
  interim separate Alpaca oneshot (it would be a second hypertable writer and a second
  fetch path).

### Enforcement
- Protocol-conformance test both history leaves must pass (normalized verdicts and
  evidence fields, observation shape, page boundaries, budget interface).
- Boundary test in the `test_market_data_ohlcv_boundary.py` pattern: services and
  scripts import the protocol, never a concrete leaf.
- APR keys per provider under `infra.<provider>.*`, seeded from measured values with
  `[measured]` provenance.

### Claude's Discretion
- Task decomposition, wave structure, exact migration numbering, conformance-test
  fixture mechanism, per-provider head schema details within todo 526's scope.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design and prior art
- `docs/plans/2026-10-09-provider-history-plane-unification-design.md` — this phase's
  design (rev 2; owner-approved, AGY-reviewed; the AGY findings are folded in)
- `docs/plans/2026-10-02-ibkr-history-fetch-consolidation-design.md` — phase 189 design;
  the fetcher, queue, ledger, and lock this phase generalizes
- `docs/plans/2026-10-09-alpaca-5m-admission-build.md` — todo 521; the leaf, policy docs,
  admission machinery, and the two pre-write dependencies this phase consumes
- `docs/plans/2026-10-09-alpaca-integration-pilot.md` — measured Alpaca facts
  (adjustment=split, RTH aggregates, pagination, rate limits, T1-T9 findings)

### Foundation
- `docs/foundation/naming-system.md` — ring classification (src/providers is Ring 1),
  suffix taxonomy, portability test
- `docs/foundation/adaptive-parameter-registry.md` — APR seeding rules for
  `infra.<provider>.*` keys
- `docs/foundation/principles.md` — project principles
- `docs/reference/gotchas.md` — kill-and-resume procedure, shared-checkout rules

</canonical_refs>

<specifics>
## Specific Ideas

- `scripts/infrastructure/backfill/ibkr_history_fetcher.py` is the code to generalize;
  `scripts/infrastructure/backfill/_fetcher_lock.py`, `_fetch_queue.py`,
  `services/ohlcv_coverage_writer.py`, `src/intelligence/bars/sources.py`
  (`bar_source_policy`) are the adjacent surfaces.
- The live drain (~260+/1,529 names at ~88 req/h) must not lose banked work: the
  kill-and-resume happens deliberately, with the code-diff check first
  (memory: restart-batch-job check-code-diff-first).
- `provider_head` does not exist yet; todo 526 is P3 pending and lands with this phase's
  refactor (shared planner edit).

</specifics>

<deferred>
## Deferred Ideas

- Alpaca live-streaming leaf (same `DataProvider` protocol, dormant streaming DAG)
- Third-vendor onboarding (the phase's own conformance tests are the proof it is cheap)
- Wiring ingestion lag alerts (alerting deliberately unwired for UAT; the council's
  common-mode objection says wire before this fetcher becomes the only door)

</deferred>

---

*Phase: 190-provider-history-plane-unification-one-multi-provider-fetche*
*Context gathered: 2026-10-09 via PRD Express Path from the approved design*
