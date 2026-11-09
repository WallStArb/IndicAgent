# Base feature scouting and the research ladder - Idea

**Status:** Idea, 2026-11-09. Not built; the first step (the data adjacency register) is todo 603. The measurement half already exists (todo 601, plan `docs/plans/2026-11-09-regime-conditional-and-incremental-ic.md`).
**Author:** Claude session 1fb77ae9, 2026-11-09, from the owner's direction: a process that looks at the data we hold, and data adjacent to it that we do not save, and proposes new lowest-level features; the same thinking for regimes, families and the combiner.
**Informed by:** glossary (`family`, `predictor`, `feature group`, `primitive`, retired tier taxonomy and the `composition` namespace), `.planning/todos/pending/440-*` (generated_family grammar), todo 601, `docs/ideas/signal-scoped-regime-states.md`, `docs/plans/2026-09-24-evidence-framework.md` (E15-E18), the Massive review of 2026-11-08.

## The problem

The proposer measures every numeric column that exists. Nothing asks what columns should exist. Two blind spots follow: data a vendor already serves that we drop (trade count, VWAP, extended hours), and quantities we could compute from data we hold but have not thought of. This is the lowest level of research, so mistakes here are inherited by everything above it.

Terminology note: the glossary defines `composition = base` as computed from a name's own bars or the timestamp, so features from outside sources (FINRA, FRED, earnings events, dated market cap) fit neither `base` nor `interaction`; widen the `composition` vocabulary (CVR) or add a code for external-source features before todo 603 step 5. The lowest level is a **base feature** (glossary `composition = base`: computed from a name's own bars or the timestamp). "Atomic" was a retired tier name; do not revive it. An `interaction` feature is built from other features and belongs one rung up.

## The ladder

| Rung | Unit | Where discovery happens | What is counted |
|---|---|---|---|
| 0 Data | a field a source serves | scouting the adjacency register | nothing; capture is cheap, no outcome peeked |
| 1 Base feature | one number per (symbol, ts) from declared inputs, causal, declared memory | grammar over primitives plus scouted fields | each admitted column enters the look count `n_looks` |
| 2 Predictor and interaction | registered computation of base features | grammar depth 2 (todo 440), owner ideas | in `n_looks` |
| 3 Family | 3 to 8 members, one pre-registered mechanism | owner and idea docs; never an outcome screen | the family is the tested unit |
| 4 Regime | a conditioning state built from base features or macro | state definitions are hypotheses (number of states, thresholds) | each definition in `n_looks`; interactions only for pre-registered pairs |
| 5 Combiner and book | weights across families, by regime | S7 combiner, construction rule, S8 book test | the book test, once, on its own span |

The same funnel runs at every rung: propose broadly, admit on non-outcome gates, measure in the counted sweep, select with StepM, promote only on positive net expectation.

## Two kinds of gate, kept apart

1. Admission gates (no outcome peeked): causality, declared memory, NaN where undefined (no fill), asset-agnostic, point-in-time inputs, unit-free (no raw price levels as features), coverage above a floor, and uniqueness (feature-to-feature correlation with existing columns; this never touches the target; reuse `research/contribution.py`'s `uniqueness`, `effective_breadth` and `correlation_clusters`). A proposal that fails is rejected with a recorded reason. A proposal that passes is registered `candidate`, computed, and measured.
2. Selection gates (outcome): the counted sweep with StepM over the declared `n_looks`, then family pre-registration and promotion rules.

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
| earnings dates and time of day | EDGAR 8-K Item 2.02 (acceptance timestamp, free, actual release only); Massive Benzinga partner feed (from 2010-04-30: `date`, `time` EST, `date_status` projected or confirmed, estimates and actuals, `last_updated`; select Benzinga expansion plans; no revision history stated) | event-window features, post-announcement drift | acceptance timestamp or `time` is the knowable-by time; the projected date is not point in time without a stored history of the estimate |
| dividend declaration, record and pay dates | Massive dividends (all plans; all four dates plus `historical_adjustment_factor`) | declaration-announcement features; our `dividend_events` holds only `ex_date` and `amount` | check Yahoo for the same dates before buying anything |
| filing index with accession numbers | Massive EDGAR index (filing dates), EDGAR directly | event timing, filing-based features | Massive's income-statement `filing_date` is the latest filing containing the period, not the original, so use EDGAR's own index for original dates |
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

## Discovering features from the data itself

Proposals (above) start from ideas. Discovery methods start from data. They differ in what they may see, so they differ in what they cost in evidence:

| Class | Method | Sees outcomes? | Output | Counting |
|---|---|---|---|---|
| A. Mechanism | owner concepts, blind model proposals | no | base feature spec | each admitted column in `n_looks` |
| B. Combinatorial | registered grammar over primitives (todo 440) | no (selection in-fold) | many candidate predictors | whole grammar plus selector is one attempt |
| C. Target-free structure | PCA or ICA of the feature panel, clustering of names or features, autoencoder embeddings, HMM-style states, residual factor models | no | latent features, factor loadings, regimes | admission is safe; each kept output enters `n_looks` |
| D. Target-aware learning | supervised importance (lasso, boosted trees), symbolic regression, convolutional models on raw windows (`docs/ideas/signal-convolutional-raw-window-representation.md`, framed skeptically) | yes, inside training folds only | a fitted book member (a `predictor` has no fitted parameters), not a base feature | the frozen fitted object is one attempt, tested once on a later span |
| E. Error analysis | where do existing books lose or leave residual (by regime, event, name class, time of day)? | yes, on a discovery span | new hypotheses for class A | the discovery span is spent; confirmation uses a separate, unsearched span |

Order of use: C first (cheap, no outcome peeked, and it also finds redundancy and the true dimensionality of the 306 columns), then B, then D inside folds, then E under strict span discipline. Class E is the most dangerous because it reads outcomes to write hypotheses: it reads the searched vintage only, every series it produces joins the selection universe under E18 (counted), and confirmation is each book's own unsearched forward span, spent once. Nothing found there is reported as evidence, only as a hypothesis for class A to register and test.

What none of them can do is invent data. A new quantity from a source we do not hold comes from rung 0 scouting.

Status of the counting mechanism for the feature sweep: E21 (drafted 2026-11-09, awaiting owner adoption) defines it — the measured cell is the unit, its per-session pooled IC is the attempt series, storage is `research_run`/`research_run_series` through S6 (sole writer), every measured cell joins the E18 selection universe, and `informed_by` chains a family to the prompting cell's run. Until the owner adopts E21 and todo 601 builds it, the interim rule holds: sweep cells are evidence records, E18's StepM runs over the family's book attempts, and the forward span is the control. `n_looks` is the bookkeeping count of measured features and nothing more. No real-data sweep runs before adoption (todos 601, 603).

## What does the suggesting and discovering (components, simplified after review)

Review verdict (2026-11-09): the first draft was an eight-stage job with its own ledger, which is the over-engineering the owner warned against. By the five steps: delete the daemon and the new ledger, keep four small artifacts, build the rest only when the first counted test is done.

Nothing suggests features today: `ic_measure` only measures columns that exist. Four artifacts, no new service and no new table:

1. The data adjacency register (a doc under `docs/reference/`, plus a small script that diffs vendor schemas and endpoint lists against stored columns). Rung 0.
2. The admission gate: one pure function in the research layer, called on the registration path. Rung 1. Rejections and their reasons are recorded as `concept_registry` rows with status `deprecated` and a reason code in metadata (the live check allows only candidate, shadow_only, active, deprecated; a new `rejected` status would need a migration, and `UNIQUE (domain, name)` means a rejected name is blocked until renamed); a proposal is a `candidate` row with a proposal timestamp and a mechanism statement. The registry is the proposals ledger; do not build another.
3. The look count `n_looks`: recorded in the existing research ledger (S6 is the sole writer of `research_run`), declared before each measurement run.
4. The discovery methods as research-runner jobs, not as a daemon: grammar (todo 440), structure learner (class C), learned predictors (class D), error analysis (class E). Each is a pure kernel with the runner owning I/O, built only when a counted test needs it.

Who proposes: the owner, the blind model proposer (rule above), and the grammar. All three write the same kind of `candidate` row. Flow: proposal row -> admission gate -> compute in the rebuild -> `ic_measure` sweep -> counted verdict.

Build order: register (no code beyond a diff script), admission gate spec, then everything else only after the first counted test. Stages that need data or outcomes wait.

## Corrections after review

1. Counting. The first draft said every proposal counts in `n_looks` whether or not computed. That over-counts: StepM corrects for tests actually performed. The rule is: log every proposal (timestamp, spec, mechanism) so blindness is auditable; `n_looks` counts every feature that is measured, and a feature measured and then dropped after seeing a result still counts. A proposal never measured costs nothing in the correction.
2. Admission statistics need a span. The uniqueness gate (feature-to-feature correlation) uses no target, but computing it on the whole history uses future feature values to decide admission and weakens the claim that the forward span is unsearched. Compute every admission statistic on the discovery span only (before the write-once `alpha.validation.oos_start`), with the thresholds as APR keys.
3. Learned latent features obey temporal integrity. A PCA, ICA, clustering or embedding fit on the full sample leaks the future into its loadings. Fit walk-forward (expanding or rolling windows inside the vintage), freeze each fit with a content hash, and apply it only to rows after its fit window (a read for t sees only loadings knowable by t); a single fit over the whole vintage applied to earlier rows is lookahead. Pre-register the refit schedule, as the HMM walk-forward did (todo 248). Class C is target-free but not time-free.
4. Hindsight in model proposals is reduced, not removed: a model has read the literature and the market's history. Disclose it, require a stated mechanism, and confirm only on each book's own unsearched forward span.
5. Priority. The first counted test is the critical path (`PRIORITIES.md`). This whole lane waits behind it except the register and the gate spec, which are cheap and unblock the Massive capture decisions.

## Counting is a price, not a cap (E18 is already this)

Methodology ledger E18 (adopted 2026-09-26) replaced E15's M = 30 budget and per-screen Bonferroni bar. The rule in force: iteration is uncapped; every real-vintage series a person can see is recorded with its full return series and joins the selection universe (including `exploration` mode runs, diagnostic refits, and a run that computed a statistic and then failed); there is no bar per attempt; at selection, Romano-Wolf StepM runs over the whole universe at family-wise 0.05 with one joint stationary-bootstrap draw, so correlated attempts cost far fewer than independent ones; the book that spends a forward span is chosen by positive net expectation at a conservative quantile; each forward span is spent once, per book.

So the look count never limits how many ideas are generated, logged or computed. It is the size of the selection universe StepM controls over. Consequences for this lane:
1. There is no free, uncorrected exploration on real vintage data: whatever a person sees joins the universe. Exploration that must stay free uses synthetic data or the null battery; real-data exploration is counted, cheaply, because StepM is joint.
2. Dependence lowers the price automatically. Class C (structure analysis) shows the effective number of dimensions; test one representative per correlated cluster, and test a group or family before its members, so fewer series enter the universe.
3. The scarce resource is the forward span (spent once per book). The practical cap on ideation is how many books the spans can confirm, not how many features are tried.

Superseded and withdrawn: the "exploration span versus confirmation span" lever and the "capacity-based screen bar" option I drafted earlier. E18 already uncapped the screen, and the vintage-versus-forward split is E15's section 3, still in force.

Possible refinement worth a research note (not a change now): sequential confirmation. A fixed power-dated test date (E18 refuses a date more than 3 years out) wastes calendar time when evidence is strong early or hopeless early. Group-sequential or always-valid (e-value) confirmation on book P&L would allow early stopping in both directions without spending extra alpha. The difficulty is autocorrelated P&L under the E17 HAC statistic; it needs a study, a synthetic power check and a ledger entry before use. This attacks the real bottleneck (forward-span time), which the screen's price does not.

## Cadence and ownership

- Quarterly scouting pass: refresh the register from vendor schemas, list diffs, propose captures. Capture is cheap and carries no outcome, so it needs no look count.
- Each admitted batch is one declared `n_looks` increment recorded in the ledger before measurement.
- Rejected and dead regions are recorded as registry rows with a reason code (what was tried and why it failed), so the same region is not rediscovered and recounted unknowingly; no separate log.

## Open questions for the owner

1. Session definition: RULED by the owner 2026-11-09: extended-hours bars stay raw only (stored, never selected; canonical 5m stays the 78-slot RTH grid). Later, summary features (pre-market return, range, volume share, after-hours return) are computed from raw in a separate kernel and attach to open-time and daily features; no grid, gate or pin change.
2. Earnings dates: which source, and is announcement time reliable enough to be knowable-by?
3. Model proposals: RULED by the owner 2026-11-09, allowed as a blind proposer. (1) It sees schemas, the register, existing features, the glossary and the rejected-proposals log, never IC, verdicts or returns. (2) Every proposal is a spec with a mechanism statement, timestamped in the concept registry before any measurement; it counts toward `n_looks` once measured (refined 2026-11-09: a proposal never measured costs nothing in the correction). (3) Admission is mechanical; only `ConceptRegistryService` flips a status. (4) Refining a result into neighbours is a separate step under pre-registered rules and its own count, never the model's judgement.
