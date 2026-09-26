---
status: pending
priority: P1
filed: 2026-09-26
source: 2026-09-26 backlog triage, owner direction
---

# Unified research-to-production design: one pipeline from data to a frozen book

This todo is the design brief. The deliverable is one doc in `docs/plans/` marked PROPOSED,
written after a brainstorm with the owner, then adopted (a methodology-change-ledger entry only
if an E15 rule changes). No code until adoption. It must land before todo 435 is planned, so 435
does not harden the split described below.

## 1. The problem

Two ensemble layers overlap with no stated relation:

| | Old layer (v3.0) | New layer (phase 183) |
|---|---|---|
| Input | `feature_vectors` + `feature_ic_scores` | OHLCV only (todo 435 adds features) |
| Combiner | `ensemble_trainer` (IC-weighted, FDR-gated) -> `alpha_ensemble_ic` | S7 walk-forward ridge / equal weight |
| Test | ic_engine per-feature gates, phase 179 sleeve harness | S8 book test (E16/E17), ledger, M = 30 |
| Output | `alpha_publisher` -> `alpha_events` | frozen book, forward confirmation (S9) |

Two combiners, two definitions of the model and two routes toward capital break the DAG
principle. Knowledge is split the same way: ideas in a markdown ledger, features in
`concept_registry`, runs in `research_run`, research parameters in YAML specs outside APR.

## 2. Charter (owner-supplied, refined)

Design as a council of principal systems architects and senior quants under Jim Simons'
oversight: engineering rigor, mathematical purity, extreme simplicity, ruthless elimination of
hidden edge-case failures. Each charter clause is stated below as a testable invariant, because
a rule that is only reviewed, not checked, is how the 243 and 248 lookahead bugs survived.

| # | Invariant | How it is checked |
|---|---|---|
| I1 | **Temporal integrity: T_event <= T_know.** Every stored fact records, or derives by one declared rule, when it became knowable; every read for time t sees only facts with T_know <= t | Generalize the S3 causality probe to stored tables: for sampled dates, recompute a writer's output on data truncated at t and require bit-identity with the stored row. Covers `feature_vectors`, regime columns, factor loadings, IC. Run in CI on fixtures and as a periodic audit on the corpus |
| I2 | **Determinism: bit-exact reruns.** Any output is reproducible from (input snapshot hash, code key, spec or recipe hash) | Extend `repro_frozen.py` from the research layer to every batch writer that feeds a book; CI fails on drift |
| I3 | **One writer per table, one direction, no cycles.** Compute never persists its own output | Existing DAG invariants; add a CI check that each table has exactly one registered writer |
| I4 | **No filled values.** Missing is NaN; warmup is masked by declared memory; no placeholder bar reaches compute | S0 guards (435); coverage floor per feature per span |
| I5 | **Point in time everywhere.** Universe, classification, tags and parameters are read as of t | SCH is already append-only point in time; extend the same to ITR tags and to APR values used by a run |
| I6 | **Lineage.** Every output row traces to its recipe (UCR) and its run | Run ids on every derived row; recipe hash in the run record |
| I7 | **Reusable across asset classes.** Asset class is data, not a code branch | Cross-asset members and factors run through the same S0-S8 path; no `if asset_class ==` in compute |
| I8 | **Typed, functional, vectorized compute.** Pure functions over arrays; state only at the edges | Research layer already does this; applies to feature kernels and the combiner |

The charter's "asynchronous, low-latency execution routing" is kept as a design constraint only:
execution is an isolated, swappable stage behind an interface. Its implementation is deferred until
a book passes forward confirmation (Musk step 4 before step 1 otherwise; Nautilus Trader is the
flagged candidate then).

## 3. Method: the Musk 5 steps, in order, as the doc's structure

1. **Requirement, made less dumb.** The requirement is: a frozen book whose forward returns,
   net of a measured cost model, justify capital. Every stage must serve that sentence.
2. **Delete.** One combiner, one test path, one route to capital. Candidates: the IC-weighted
   combiner (or it becomes one S7 variant), the phase 179 sleeve harness (superseded by the
   research layer), parts of the ic_engine regime x tf grid, `context_writer`, the markdown
   ledger as a source. Delete before adding methods.
3. **Simplify.** The one pipeline, one job per node (section 4).
4. **Accelerate.** Only then: the 426 -> 290 -> 248 -> 411 refresh chain, ic_engine throughput
   (385, 399), combiner speed.
5. **Automate.** Last: feature refresh chained after the nightly OHLCV run (332/411), scheduled
   forward shadow, decay alarms. Nothing automated before a book is confirmed.

## 4. Target pipeline (the starting proposal; the brainstorm tests it)

```
S-ingest   IBKR -> market_data_ohlcv            stateless, idempotent, source recorded (phase 185)
S-feature  regime_writer, backfill_feature_factory -> feature_vectors   (I1, I4 at write time)
S-measure  ic_engine -> feature_ic_scores        side branch: disclosure, proposer, monitoring
S-research S0 Panel (bars + features) -> S1 target -> S2 families -> S3 guards
           -> S7 one combiner -> S8 book test + contribution accounting -> S6 ledger (UCR)
S-book     frozen book (recipe + weights + spec hash)
S-forward  alpha_publisher runs the frozen book forward: shadow, then capital
S-portfolio isolated: sizing, risk limits, cost/impact model
S-exec     interface only until confirmation
```

Questions the doc settles:

1. `ensemble_trainer`: S7 variant or deleted. `alpha_publisher`: the forward runner of a frozen
   book, not an ensemble publisher.
2. Regimes: features (members), one pre-registered combiner-conditioning variant, disclosure.
   Never an admission gate (the Phase 148 failure).
3. ic_engine: disclosure, proposer (method D4), per-member monitoring; whether the regime x tf
   grid shrinks to what those need.
4. Methods portfolio inside the one pipeline, charged to M = 30. Input:
   `docs/plans/2026-09-26-research-methods-portfolio.md` (discovery D1-D5: prior families, whole
   corpus as one family, interactions, IC as proposer, learned members; combiners: equal weight,
   ridge, regime-conditioned, gradient-boosted).
5. Deletions list, with each item's consumer check.

## 5. UCR as the recipe book (owner direction)

UCR becomes the single, queryable record of what the project knows, including failures. The
markdown ledger (`docs/research/construction-verdict-ledger.md`) is the interim home for ideas and
becomes a report rendered from UCR.

- **Recipe card per concept,** domains feature, family, book, combiner, method: what it is and
  why (mechanism, source), code pointer (module:function at commit), inputs and parent concepts,
  parameters (APR keys plus the values pinned at each attempt), vocabulary codes (CVR), universe
  and tags (ITR, SCH), status.
- **Lifecycle starts at `idea`,** before `candidate`, so an idea is a concept from day one.
  Migrate every ledger idea and verdict in.
- **Attempt history per concept:** every run, spec hash, date, result, disclosure. "Have we tried
  this" is one query. Nothing is deleted; a failed idea keeps its record and can return.
- **Registry roles in the pipeline:**
  - APR holds defaults and their history; a spec pins a copy at freeze; S0 records both and
    refuses when a stored input was computed with a different value (closes the two-stores gap).
  - CVR validates every code a spec or recipe uses at load time.
  - ITR tags (measured sensitivities) become usable as members and S1 factor inputs, read point
    in time.
  - SCH stays the classification source for S1 sectors.
  - UCR is written only through `ConceptRegistryService` and the S6 ledger writer.

## 6. Contribution accounting (standard output of every book test)

Two questions, different measures: who earned the return (attribution, additive) and who is
necessary (marginal, counterfactual; catches redundancy). Levels: member, family, method,
combiner.

1. Exact P&L attribution: book timing P&L split into per-member terms (walk-forward weight x
   member P&L); share of mean return and share of risk (Euler: cov with book / book variance).
2. Leave-one-family-out: walk-forward refit without family k; change in the book statistic.
3. Shapley over families: about 2^F closed-form ridge refits (about 1,000 at 10), sampled beyond.
4. Uniqueness and breadth: each member residualized against the others; effective number of
   independent signals from the signal correlation eigenvalues.
5. Standalone vs in-book table: ic_engine IC beside in-book contribution; flags
   strong-but-redundant and weak-but-additive; tells whether IC-as-proposer picks contributors.
6. Stability by sub-period, regime (disclosure), lag (decay); weight sign stability across folds.
7. Turnover and cost share per member.
8. Forward monitoring: per-member realized contribution on a control chart against its in-sample
   expectation; drift out of band is the decay alarm.

Discipline: diagnostics, not tests (no M = 30 spend; per-member t-stats are not significance
claims). They never edit the book they measure: pruning or reweighting on them is a new book
version, recorded as outcome-informed, spending one screen. Counterfactual refits reuse the book's
folds. Compute-only S8 extension; results via S6 into UCR; `alpha_publisher` emits per-member
series in forward shadow.

## 7. Cost and market-impact model

Renaissance treated execution cost as core science. Standing directive unchanged: discovery and
screening stay gross and costs never gate them. But capital sizing needs a measured, per-symbol,
per-time-of-day cost and impact model (spread from data, for example Corwin-Schultz and Roll from
the microstructure row in the ledger; impact scaled by participation). Todo 393 showed the old
proxy was dimensionally wrong, so none exists today. The doc places it in S-portfolio and states
what data it needs.

## 8. Acceptance checks (Renaissance principles, `docs/foundation/principles.md`)

The adopted design passes when each is answered concretely:

- Data quality over model complexity: the data path (185, refresh chain, I1, I4) precedes any new
  combiner.
- Never drop data that could contain signal: no per-feature admission gate; ideas never deleted.
- Earn capital through proof; resist overfitting: every method spends the same budget; one
  forward confirmation; contributions never edit a tested book.
- Segment by regime: as members, one variant, disclosure; never thin gating cells.
- Shadow mode first: forward runner in shadow before capital.
- Instrument everything: run records, coverage, contribution and decay series on every run.
- Automate manual tasks: step 5 list, only after confirmation.
- Empirical over theoretical: methods compete on measured results.
- The eight invariants in section 2 each have a named check.

## 9. Not reopened

E15/E17 evidence rules, M = 30, the forward-span discipline, the standing costs-not-gating
directive.

## Held todos

Serving the IC-as-proposer method: 191, 038, 166, 099, 039, 115. Implementation todos (UCR
recipe book, I1 audit, cost model, deletions) are filed after adoption.
