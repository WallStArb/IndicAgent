# Base feature scouting and the research ladder - Idea

**Status:** Idea, 2026-11-09. Not built; the first step (the data adjacency register) is todo 603. The measurement half already exists (todo 601, plan `docs/plans/2026-11-09-regime-conditional-and-incremental-ic.md`).
**Author:** Claude session 1fb77ae9, 2026-11-09, from the owner's direction: a process that looks at the data we hold, and data adjacent to it that we do not save, and proposes new lowest-level features; the same thinking for regimes, families and the combiner.
**Informed by:** glossary (`family`, `predictor`, `feature group`, `primitive`, retired tier taxonomy and the `composition` namespace), `.planning/todos/pending/440-*` (generated_family grammar), todo 601, `docs/ideas/signal-scoped-regime-states.md`, `docs/plans/2026-09-24-evidence-framework.md` (E15-E18), the Massive review of 2026-11-08.

## The problem

The proposer measures every numeric column that exists. Nothing asks what columns should exist. Two blind spots follow: data a vendor already serves that we drop (trade count, VWAP, extended hours), and quantities we could compute from data we hold but have not thought of. This is the lowest level of research, so mistakes here are inherited by everything above it.

Terminology: the lowest level is a **base feature** (glossary `composition = base`: computed from a name's own bars or the timestamp). "Atomic" was a retired tier name; do not revive it. An `interaction` feature is built from other features and belongs one rung up.

## The ladder

| Rung | Unit | Where discovery happens | What is counted |
|---|---|---|---|
| 0 Data | a field a source serves | scouting the adjacency register | nothing; capture is cheap, no outcome peeked |
| 1 Base feature | one number per (symbol, ts) from declared inputs, causal, declared memory | grammar over primitives plus scouted fields | each admitted column enters the look count `L` |
| 2 Predictor and interaction | registered computation of base features | grammar depth 2 (todo 440), owner ideas | in `L` |
| 3 Family | 3 to 8 members, one pre-registered mechanism | owner and idea docs; never an outcome screen | the family is the tested unit |
| 4 Regime | a conditioning state built from base features or macro | state definitions are hypotheses (number of states, thresholds) | each definition in `L`; interactions only for pre-registered pairs |
| 5 Combiner and book | weights across families, by regime | S7 combiner, construction rule, S8 book test | the book test, once, on its own span |

The same funnel runs at every rung: propose broadly, admit on non-outcome gates, measure in the counted sweep, select with StepM, promote only on positive net expectation.

## Two kinds of gate, kept apart

1. Admission gates (no outcome peeked): causality, declared memory, NaN where undefined (no fill), asset-agnostic, point-in-time inputs, unit-free (no raw price levels as features), coverage above a floor, and uniqueness (feature-to-feature correlation with existing columns; this never touches the target). A proposal that fails is rejected with a recorded reason. A proposal that passes is registered `candidate`, computed, and measured.
2. Selection gates (outcome): the counted sweep with StepM over the declared `L`, then family pre-registration and promotion rules.

Screening proposals on IC before admission is the overfitting path this separation exists to block. Admission may use redundancy, never return.

## Rung 0: the data adjacency register

A table (a doc first, a queryable table later) with one row per field a source serves or could serve: source, field, availability time (point in time), history start, retrieval cost, license note, stored (yes/no/partial), which base features it enables, status (stored, captured-not-used, worth-capturing, rejected with reason). It is generated from vendor schemas where possible (Massive file columns and REST endpoints, Alpaca bar and quote fields, IBKR contract and history fields, FRED and NY Fed catalogs, Yahoo, SEC EDGAR, FINRA) and diffed against `ohlcv_raw` and the stored tables. The diff is the scouting list.

Seed entries (availability and point-in-time quality unverified; verify before capture):

| Field | Source | Enables | Note |
|---|---|---|---|
| trade count `transactions`, `n` | Massive files, Alpaca bars | activity, average trade size, bar-quality witness | free with bars already pulled; nullable raw column (todo 600) |
| VWAP `vw` | Alpaca bars | VWAP deviation without our own estimate | check against `vp_sr` kernels |
| extended-hours bars | Massive files, SIP 23/5 from 2026-12-06 | pre-market range, overnight gap composition | raw only per the owner's 2026-11-09 ruling; summary features later |
| shares outstanding, market cap (dated) | Massive ticker details | size, turnover, float-style ratios | must be a dated table, not an instrument attribute |
| splits, dividends, ticker events | Massive REST | cleaner total return, entity map | also cross-checks Yahoo and the 587 split work |
| short volume, short interest | FINRA direct | crowding, squeeze state | publication date is the availability time, not settlement |
| earnings dates and time of day | to be located (Yahoo, EDGAR 8-K Item 2.02) | event-window atoms, post-announcement drift | announcement time (before open, after close) is the knowable-by time |
| index and volatility series (VIX family, term structure) | Cboe, FRED | regime inputs | macro layer already holds FRED |
| borrow availability | captured (IBKR, 16:30 ET timer) | already stored; check it is a base feature input | |
| index rebalances, option expiry calendar | exchange calendars | calendar primitives | calendar kernel exists |

## Rung 1: proposing base features

Three sources, in order of automation:
1. Schema-driven: every register row marked worth-capturing generates candidate quantities by a fixed template (level, change, dispersion, persistence, extremeness, time since extreme) across the fast/mid/slow gradient scales.
2. Grammar: todo 440 enumerates operators over primitives lazily, never materializing the library. The register feeds it new primitives.
3. Mechanism-driven: owner and idea-doc concepts, each stated with the economic cause before any data is read.

A model may propose; it never admits. Admission is the mechanical gate set above, and status flips go only through `ConceptRegistryService` (UCR rule: no LLM override).

## Rung 4: regimes as hypotheses

A regime definition is itself a choice among many (how many states, which input, what smoothing, what thresholds), so each definition is a look. The discovery question is not "find regimes with high IC", it is "does the conditional IC of a pre-registered family differ across the states of a pre-registered regime". Existing regime groups (volatility, quadrant, rates curve, HMM, fragile divergence) are the register of conditioning variables; new ones enter the way new base features do. Interactions between a regime and a family are tested hierarchically, only for pairs with a stated mechanism or that passed the level 1 and level 2 gates.

## Rung 5: the combiner

Regime-conditional weights are the S7 combiner's job, fit walk-forward. Discovery here is limited on purpose: which families enter a book is pre-registered, weights are fitted, and the book test runs once on its own forward span. More structure than that would spend the evidence budget on the part with the fewest independent observations.

## Cadence and ownership

- Quarterly scouting pass: refresh the register from vendor schemas, list diffs, propose captures. Capture is cheap and carries no outcome, so it needs no look count.
- Each admitted batch is one declared `L` increment recorded in the ledger before measurement.
- A negative-space log records rejected and dead regions (what was tried, reason), so the same region is not rediscovered and recounted unknowingly.

## Open questions for the owner

1. Session definition: RULED by the owner 2026-11-09: extended-hours bars stay raw only (stored, never selected; canonical 5m stays the 78-slot RTH grid). Later, summary features (pre-market return, range, volume share, after-hours return) are computed from raw in a separate kernel and attach to open-time and daily features; no grid, gate or pin change.
2. Earnings dates: which source, and is announcement time reliable enough to be knowable-by?
3. Whether base features may be proposed by a model at all inside the sweep, or only by the grammar and by owner concepts.
