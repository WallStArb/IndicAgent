# Unified research-to-production design: one pipeline from data to a frozen book

**Author:** Claude (Opus 5.5), 2026-09-26, from a section-by-section brainstorm with Brandon
(todo 436). Every decision in section 2 was approved by the owner in that session.
**Informed by:** the owner's charter (design as a council of senior engineers and quants under
Jim Simons' mandate: rigor, radical simplicity, data integrity, no lookahead, modular reuse, a
strict DAG, async I/O). External reviewers (AGY, Codex) are out of quota until about 2026-10-01
and 2026-10-15. An independent adversarial review by Fable 5.1 (file paths only, 2026-09-26)
raised 19 findings; each was checked against the code and database before acceptance, the two
that reversed approved decisions were put to the owner and accepted, and the dispositions are in
section 20.
**Status:** ADOPTED 2026-09-26 by the owner, with methodology-change-ledger E18 (section 7.4):
this design replaces E15's hard M = 30 screen budget, moves the forward span per book, and adds a
net-expectation condition at promotion. Implementation is tracked by roadmap phases 186-188 and
the todos filed at adoption (section 19).
**Parents:** `docs/plans/2026-09-24-evidence-framework.md` (E15),
`docs/plans/2026-09-25-alpha-research-architecture.md` (adopted),
`docs/plans/methodology-change-ledger.md` E16 and E17.
**Absorbs:** `docs/plans/2026-09-26-research-methods-portfolio.md` (working input, section 6
here). **Supersedes on adoption:** `docs/plans/2026-09-24-edge-proof-program.md` (status line
only; its verdicts stand).

## 1. Requirement and problem

**The requirement (Musk step 1):** a frozen book whose forward returns, net of a measured cost
model, justify capital. Every stage below exists to serve that sentence, or it is deleted.

**The problem.** Two ensemble layers overlap with no stated relation:

| | Old layer (v3.0) | New layer (phase 183) |
|---|---|---|
| Input | `feature_vectors` + `feature_ic_scores` | OHLCV only (todo 435 adds features) |
| Admission | Per-feature gate per (tf, regime) cell: BH-FDR, `ic_ci_lower > 0`, walk-forward | Pre-registered families, no per-member gate |
| Combiner | `ensemble_trainer`: IC-Sharpe weights, Ledoit-Wolf cluster deflation | S7 walk-forward ridge; equal weight is the E17 default |
| Test | Hundreds of per-feature cells; the combined output is never tested as one book | S8 book test, one statistic |
| Output | `alpha_publisher` -> `alpha_events` | frozen book, forward confirmation |

Both layers share the Renaissance premise, many weak signals combined into one forecast. The old
layer contradicts it in practice: a feature with IC 0.02 in a regime cell of a few thousand
effective observations cannot clear its per-feature gate, so the weak signals are removed before
the ensemble sees them (the Phase 148 failure; E15 removed per-feature admission for this
reason). This design keeps one layer, carries the old layer's good ideas into it, and names every
stage from data to capital.

## 2. Decision register

Owner-approved 2026-09-26. Section numbers point to the detail.

| # | Decision | Section |
|---|---|---|
| UD-01 | One pipeline, one job per node; stages named, not numbered, above the research layer | 3 |
| UD-02 | Two distinct weightings: member weights (S7, signals -> book forecast) and position weights (construction rule, forecast -> holdings). A book freezes both | 4 |
| UD-03 | Combiners: equal weight, walk-forward ridge (lambda chosen in-fold), IC-Sharpe weighting; all behind the `Combiner` protocol | 4.2 |
| UD-04 | Construction rules R1, `vol_normalized`, `ic_proportional`, `mean_variance`, `fixed_sign` behind a `ConstructionRule` protocol; R1 fixed during discovery | 4.3 |
| UD-05 | Horizon rule: partial adjustment toward target, kappa derived from the cost model and the signal's own autocorrelation, pinned before the attempt | 4.4 |
| UD-06 | Nonlinearity enters as members first; one regime-conditioning variant; capped gradient-boosted combiner only after the `temporal_integrity` audit passes | 5 |
| UD-07 | Regimes: fixed per-regime disclosure plus regime-explained share on every book test, never gating; conditioning only through continuous state variables | 5.2 |
| UD-08 | Discovery methods named; `ic_proposal` split into in-fold selection (honest) and human reading of corpus IC (outcome-informed) | 6 |
| UD-09 | Iteration uncapped; every real-vintage series a person can see recorded; selection by a step-down multiple test (Romano-Wolf StepM) over everything tried on the vintage; promotion within that set by net expectation; one forward confirmation on a span that starts after the book's freeze where the span was already looked at; sealed shadow for every book in the set | 7 |
| UD-10 | Post-deployment: frozen recalibration rule; structural change as a challenger version with a capital ramp; decay alarms trigger review | 8 |
| UD-11 | Cost policy: discovery and every test statistic gross; promotion requires positive net expectation at a conservative quantile; capital sized on measured net | 9 |
| UD-12 | Cost model staged: first cut (commission, spread) now; impact, borrow constraint, capacity curve at the capital tier; implementation shortfall and cost distributions throughout; borrow snapshots start now; todo 393 folded in | 9 |
| UD-13 | UCR as the recipe book: typed domains, append-only versioned recipes, attempts with typed results, derived research stage, generated ledger | 10 |
| UD-14 | ic_engine shrinks to proposer, IC term structure and member monitoring; feature lifecycle moves from IC gates to data-quality gates | 11 |
| UD-15 | Eight named invariants, each with a check; five bias guards | 12 |
| UD-16 | Contribution accounting, full list, two-level attribution | 13 |
| UD-17 | Delete the old chain; summarize then drop its tables (amended 2026-09-26: raw data permanent, derived data is cache, conclusions are records); re-scope dependent phases and todos | 14 |
| UD-18 | Vocabulary: rename only misleading or colliding names; retired and new terms; todo 430 enforces | 15 |
| UD-19 | Build order: price-only daily families on the 931 names and single-family books run first while the feature infrastructure is built; then delete, data path, research core, features into books, forward, capital | 16 |
| UD-20 | Forward span per book: feature and ctf-like books confirm only on data after their freeze (2026-08-08 at the earliest); price-only families 1 and 2 keep 2025-12-24, disclosed | 7.3 |
| UD-21 | Review resolutions (Fable, 19 findings) | 20 |
| UD-22 | Preconception-free discovery: `generated_family`, a registered grammar that enumerates candidate predictors from primitives, selected and weighted only inside training folds | 6.1 |
| UD-23 | Accounting groups inside large families: by feature origin (primary) and by in-fold correlation cluster (beside it); for reading contributions only | 13 |
| UD-24 | Refactor map: refactor only surviving code the design touches, parity-checked; delete the rest (14.6) | 14.6 |

## 3. Target pipeline

### 3.1 Stages

| Stage | One job | Writes | Change from today |
|---|---|---|---|
| ingest | IBKR -> bars, source recorded | `market_data_ohlcv` via phase 185's derivation | Phase 185 |
| feature | Compute features and regime columns | `feature_vectors`, `market_regimes` | Refresh chain 426 -> 290 -> 248 -> 411 |
| measure | Standalone IC for proposal, IC term structure, member monitoring | `feature_ic_scores` | Shrunk (section 11) |
| research | S0 panel -> S1 target -> S2 families -> S3 guards -> S7 combiner -> construction -> S8 book test + contribution accounting | nothing except through S6 | Construction named; 435 wires features into S0 |
| ledger (S6) | Sole writer of attempts and recipe versions | `research_run`, `concept_recipe` | Section 10 |
| book | Frozen book record | UCR `book` concept + recipe | New |
| forward | Runs frozen books forward with the research code | `book_position` | `alpha_publisher` replaced by `BookTracker` + `BookPositionWriter` |
| capital | Sizing from the cost model, risk limits, kill switch | `portfolio_state` | Phases 156-157 re-scoped |
| execution | Interface only until a book passes confirmation | none | Phase 158 deferred |

S0-S9 remain the research layer's internal step codes (already in code). The retired AlphaEngine
"Stage 0-4" numbering is not used.

### 3.2 DAG manifest

One checked-in YAML manifest declares every node, its input tables and its output table. The
orchestrator reads it for run order, `services/service_auditor.py` reads it in place of the
hand-kept `_DAG_ORDER`, and CI reads it to check that every table has exactly one writer and the
graph has no cycle. No code generation. Today the run order is kept twice by hand
(`_DAG_ORDER` and `scripts/ops/corpus/ops_corpus_pipeline_run.sh`); the manifest removes both.
Systemd timers are a third copy of scheduling; CI validates them against the manifest.

### 3.3 Idempotency

Every node is idempotent, keyed by its provenance batch record (section 12.1, `lineage`): writer,
per-kernel code key, APR snapshot, an input content digest per (symbol, tf, time range), and the
range covered. A rerun with the same key is a no-op; a resume is safe.

The key is a content digest, not a time watermark: a high-water mark does not change when old
bars are revised (todo 433's venue-history recovery, IBKR revisions, dividend reconciliation), so
a watermark key would no-op over stale inputs, a silent wrong answer. A revision counter bumped by
the ingest writer per (symbol, tf, range) is an acceptable cheaper equivalent. The code key is per
kernel, not ic_engine's all-imports key, so a refactor elsewhere does not force a full recompute.

### 3.4 Async

"Async-first" applies to I/O: asyncpg fetches overlapped with compute, Kafka publishes. Numeric
kernels are synchronous, pure and vectorized, parallelized with process pools whose workers
return rows to one serial writer per table (the existing CLAUDE.md rule). Forcing async into
kernels adds complexity and buys nothing.

## 4. The book: forecast, construction, horizon

### 4.1 Definition

A book is four frozen parts plus a spec hash:

1. members: the registered families and their pinned members;
2. combiner (member weights), refit walk-forward by a frozen rule;
3. construction rule (position weights from the book forecast);
4. horizon rule.

S8 tests the construction that will trade. A change to any part is a new book version and a new
attempt (section 7). Refit schedules are anchored to calendar dates, not to the panel's first row
(`combiner.py` `refit_positions` anchors to row 0 today), so a forward run starting on a
different row refits on the same dates and position parity holds.

A book combines families that share one panel, horizon and factor spec
(`spec.py` `_check_book` enforces this). Families on different clocks, such as family 1 (15m,
horizon 2) and family 2 (session legs, horizon 1), combine only at the P&L level as a **pod
book**: its series is the session-level sum of the member books' E17 D_s series, and it is its own
book type with its own attempt.

### 4.2 Combiners (member weights)

All produce `book_forecast[t, i] = sum over k of v_k * s_k[t, i]`; they differ in how `v` is
chosen, always from training folds only.

| Combiner | Weights | Notes |
|---|---|---|
| Equal weight | `1 / N`, sign from the family prior; for a family with no prior (`corpus_family`), sign of the expanding training-fold IC, which makes it an in-fold combiner | E17 default |
| Ridge | `(X'X + lambda I)^-1 X'y`, lambda chosen inside the training folds | Handles correlated members in the fit |
| IC-Sharpe | Mean IC over its time variation, peer shrinkage, Ledoit-Wolf cluster deflation | The old `ensemble_trainer` estimator, rebuilt as a pure function on the same folds, clusters included (never `feature_ic_scores.cluster_id`, which is computed over the whole vintage); rewards consistency over time, which ridge does not. No admission cut |

As lambda grows, ridge tends to weights proportional to each member's covariance with the target,
so the three sit on one spectrum from no information (equal) to a joint fit (ridge). One
`Combiner` protocol (exists in `src/intelligence/research/combiner.py`), one implementation per
estimator, no second pipeline.

**Missing members.** `EqualWeight.combine` is complete-case across members today, so with many
members of uneven coverage most (row, name) cells go NaN and the cross-section shrinks silently.
Every combiner averages over the available standardized members, with a pinned minimum member
count below which the cell is NaN. This is a combining rule, not input filling, so `no_fill`
holds. Per-row member coverage is recorded in the evidence record.

### 4.3 Construction rules (position weights)

| Rule | Form | Use |
|---|---|---|
| R1 | Rank of forecast, inverse-vol scaled, market-neutral | Fixed during discovery (robust to outliers) |
| `vol_normalized` | Linear in forecast, inverse vol | Candidate; exact P&L attribution |
| `ic_proportional` | `mu = IC * sigma * z` | Candidate; with `vol_normalized` the project's one positive portfolio result (13-ETF diagnostic) |
| `mean_variance` | `w proportional to Sigma^-1 mu`, Ledoit-Wolf covariance | Capital tier; the cost-aware form is tested as its own attempt before promotion, so the promoted book is the traded book |
| `fixed_sign` | Pre-registered direction, inverse vol | Families with a stated direction (momentum) |

All sit behind a `ConstructionRule` protocol wrapping the existing functions in
`src/intelligence/research/portfolio.py`. During discovery only members or combiner vary (one
axis per attempt is recommended practice, not a rule); the construction changes once, at
capital readiness, as its own attempt.

### 4.4 Horizon rule

Each bar the book trades part of the way to its target:
`w_t = w_(t-1) + kappa * (w*_t - w_(t-1))` (Garleanu and Pedersen 2013). In that model partial
trading exists because of costs: with zero cost the optimal kappa is 1, and signal decay enters
the aim portfolio, not the trading rate. Kappa is therefore a cost device, derived from the
first-cut cost model (section 9) and the signal's own autocorrelation (which uses no returns),
pinned in the spec before the attempt, never tuned on outcomes. It is not derived from the IC
term structure: `feature_ic_scores` is computed over the whole vintage, so a kappa taken from it
would be a hyperparameter fitted on outcomes.

Discovery attempts may run gross with kappa = 1, stated in the spec. The candidate for promotion
runs with its costed kappa as its own attempt (section 7.3), so the confirmed book is the traded
book.

### 4.5 E17 memory for fitted books

E17's timing statistic compares weights against a cell mean lagged by the book's memory L. The
runner sets `memory_sessions = max(slot_histories)` for books (`runner.py` S8 call), which covers
members only. A ridge weight at s is fitted on targets inside its training window, which overlaps
the lagged mean's inputs; so do `in_fold_selection`, IC-Sharpe, the gradient-boosted combiner and
kappa below 1 (geometric, unbounded memory). That reintroduces the coupling E17 removed. Rule:
L = member memory + combiner training reach + horizon-rule reach (the lag where the kappa weight
falls below 1e-3). E17's H0 battery gains ridge and kappa cells before any attempt uses them.

## 5. Aggregation, nonlinearity, regimes

### 5.1 Nonlinearity

Every combiner that has fed a book so far is linear. The record on nonlinear aggregation:

- N1 (LightGBM over `feature_vectors`): the headline 1h uplift was 90.6% a cross-timeframe join
  leak (todos 243/245); the corrected residual test flipped significance between adjacent
  hyperparameter values and reproduced bit-identically. Inconclusive. No per-feature gain cap.
- Interaction terms (phase 151 tier 1) entered a linear combiner: 33% gate-clear against 60-67%
  for atomic families; pilot 22.2% at BH-FDR.
- Per-regime linear models (piecewise linear): 234 cells, nothing survived out-of-sample (T2).

Policy, in order:

1. Nonlinearity enters as members first (interaction terms, `s x z_t` state interactions); the
   aggregation stays linear and attributable.
2. One pre-registered regime-conditioning variant.
3. A gradient-boosted combiner with a per-feature gain cap, only after the `temporal_integrity`
   audit passes on every input table. A flexible model finds a leak before it finds a weak real
   signal; this project's first nonlinear "edge" was a leak.

Reasons: at IC 0.01 to 0.03 a nonlinear model needs far more observations per fitted degree of
freedom, and exact P&L attribution needs linearity (section 13).

### 5.2 Regimes

`market_regimes` holds four macro groups: equity (SPY realized-vol percentile x breadth, 9
labels, 2006-), rates (TLT-SHY curve x HYG-LQD credit, 6, 2017-), fx (UUP trend x HYG carry, 4,
2007-), commodity (trend x term structure, 12, 2005-). All are built from rolling z-scores and
causal expanding ranks, so they are causal by construction (unlike the per-symbol HMM, todo 248),
to be confirmed by the audit. Known defects: equity breadth uses today's tag set
(`point_in_time` fixes it); bucket thresholds are APR values chosen after seeing the history;
stale since 2026-08-10 (todo 411).

Rules:

1. **Disclosure on every book test,** a fixed pre-declared table for all four groups: per regime
   the share of P&L, mean, HAC t, IC, hit rate and effective observations; per member and family
   by regime; and the **regime-explained share** (the part of book return explained by regime
   dummies alone), which exposes a disguised static bet such as earning only in `low_bull`.
2. **Never gating.** A t of 3 in one of 31 cells is not a finding; no cell refuses a book.
3. **Conditioning only in one pre-registered S7 variant, through continuous state variables**
   (vol z, breadth, curve z, dollar z) as `s` and `s x z_t` members, never through the buckets,
   which discard information and carry post-hoc thresholds.
4. Per-symbol HMM columns stay out of every family until todo 248's walk-forward refit is
   deployed (435's rule).

## 6. Discovery methods

The fixed evidence path is section 7. Methods compete inside it:

| Method | Proposes | Status of the screen |
|---|---|---|
| `prior_family` | 3-8 variants of one published or reasoned mechanism (ledger families 1-10) | Seen-data looks disclosed per family |
| `corpus_family` | Every `feature_vectors` column that passes guards, no per-member prior | Corpus IC table disclosed as context |
| `interaction_family` | Theory-motivated pairwise terms (Interaction Factory v2) | Pilot's 22.2% disclosed |
| `in_fold_selection` | Members selected by IC computed inside each training fold, then combined | A combiner variant; the screen is not biased by it |
| `ic_proposal` | A human reads the corpus IC table and proposes a family | Outcome-informed: recorded with `informed_by`, disclosed |
| `learned_member` | ML-derived members (later) | Declared memory and guards like any member |
| `generated_family` | Candidates enumerated by a registered grammar over primitives, no idea behind any single one (6.1) | Selection and weighting inside training folds only; one attempt per grammar configuration |

The `alpha_score_residual_single_security_15m` idea reopened in the ledger used the old
ensemble's score as its signal. It is re-expressed as `corpus_family` with the IC-Sharpe
combiner, not read from the frozen `ensemble_alpha` table.

### 6.1 Discovery without preconceptions

Prior-driven families test ideas someone already had, and `corpus_family` only reaches the
features someone already designed. Renaissance's reported practice (Laufer's intraday
periodicities, Berlekamp-era pattern searches) included searching the data for non-random
structure with no story attached, then demanding the evidence hold. `generated_family` is that
process under this design's controls.

1. **Grammar, registered before any run.** The only preconception is the grammar, never an idea:
   - primitives: returns at each clock, volume, range, gaps (overnight, intraday legs),
     time-of-day and calendar position, cross-sectional and sector (SCH) aggregates;
   - operators, all causal by construction: lag, difference, time-series mean, z-score and rank
     over trailing windows, cross-sectional demean and rank, products of two terms;
   - windows from a fixed menu; a maximum expression depth (2 to start).
   The enumerated library holds thousands of candidates.
2. **No admission.** Every generated candidate is a member. Selection happens only inside each
   training fold (`in_fold_selection`, by in-fold IC), followed by ridge, so the out-of-fold
   series is honest however many candidates exist.
3. **Counting.** One grammar configuration plus its selector is one attempt in the selection
   universe (7.1). Changing the grammar after seeing results is a new, outcome-informed attempt.
4. **Guards.** Causality holds by grammar construction; the S3 causality probe still runs on a
   sample of generated members, and `temporal_integrity` covers their inputs. Generated members
   also pass the missing-member rule and the E17 memory rule (4.5); a generated expression's memory
   is derived from its windows.
5. **Compute.** A library of about 5,000 candidates over 931 names and about 5,000 sessions is
   about 93 GB in float32, so candidates are never materialized together. In-fold IC uses per-fold
   sufficient statistics (prefix moments, as `combiner.py` already does for ridge), computed one
   candidate block at a time.
6. **Interpretation after the fact.** A selected generated member with lasting contribution earns a
   recipe card and, where one is found, a mechanism; lacking a mechanism never removes it.

The first run is daily OHLCV primitives on the 931 names (attempt 3b), which needs no feature
pipeline.

**Planned order** (an order, not a cap). The shortest path to a tradeable verdict comes first:
books that need no feature infrastructure run while tracks A-C are built. `feature_vectors`
covers only the 233 `compute_eligible` names; the 931-name daily universe has OHLCV only.

| Attempt | Book | Waits on |
|---|---|---|
| 1a, 1b | Family 1 and family 2 as single-family books, equal weight, R1 | E17 H0 battery (phase 183 session) |
| 1c | Pod book of 1a + 1b (P&L-level sum of their D_s series, section 4.1) | 1a, 1b |
| 2 | Low-turnover forms of family 1 (costed kappa; extreme slots only; trade only when the predicted move clears cost) | First-cut cost model (track Now) |
| 3 | Price-only daily cross-sectional families on the 931 names: residual short-term reversal (todo 423, on the names the 2026-09-13 screen never saw), residual and industry momentum | S1 residual target on the 931 names; 185 D0 survivorship bound |
| 3b | `generated_family` over daily OHLCV primitives on the 931 names, in-fold selection plus ridge | 3's S1 target; grammar registered; E17 H0 battery ridge cells |
| 4 | Sector-ETF-leads-constituent lead-lag at 5m or 15m (ledger family 3), sectors from SCH | Intraday bars for the constituents in the book's universe |
| 5 | + `corpus_family`, equal weight with in-fold signs | 435; 184 B3 alignment; full feature recompute under provenance batches (section 12.1); `temporal_integrity`, `no_fill`, `point_in_time` checks on the feature columns |
| 6 | `corpus_family`, ridge; then `corpus_family`, `in_fold_selection` | 5; E17 H0 battery ridge cells (4.5) |
| 7 | Best of 5-6 + one regime-conditioning variant | 6 |
| 8 | Capped gradient-boosted combiner | `temporal_integrity` clean on every input table |
| 9 | Cost-aware construction of the book headed for promotion | Cost model (section 9) |

Attempts 5-6 answer the three open questions: do features add to price-only families, does the
combiner matter, does selection help. Attempts 3-4 are the high-breadth, low-infrastructure
families a Simons-style shop runs first, and they sit lower in E15's section 2 power table
because breadth is the lever.

## 7. Evidence: iterate, count, select, confirm

### 7.1 What is counted

Everything a person can see on the real vintage joins the selection universe: every book
attempt in any runner mode, member evidence runs (real-vintage single-signal books that inform
pruning; family 1's members carry t 13 to 19), and the diagnostic subset refits of section 13
(leave-one-family-out, Shapley). A step-down test prices correlated and weak series cheaply, so
including them costs little and closes the gap where a person inspects K variants and one is
counted. A run that computed a statistic and then ended `failed` still counts.

Not counted: synthetic runs, anything computed inside training folds that no person sees, and
runs refused or guard-failed before any statistic existed.

### 7.2 Iteration and exploration

Iteration is uncapped. The runner gains an `exploration` mode: cheap, recorded as an attempt, and
any return series it produces joins the selection universe. Exploration stays free to do and is
always counted. Every attempt stores its full return series in UCR (section 10), not only its
statistic.

### 7.3 Selection, promotion and confirmation

1. **No bar per attempt.** The ledger shows each attempt's raw statistic.
2. **Selection set.** Romano-Wolf StepM runs over the whole selection universe on the vintage at
   family-wise 0.05 (comparable to E15's 30 x 0.00167) and returns the set of books whose
   statistic beats zero given everything tried. It resamples all series jointly with one
   stationary-bootstrap index draw.
   - Series: each attempt's E17 D_s per session.
   - Calendar: one common session calendar; each series is studentized on its own sample, so
     differing warmup, spans (2006 vs 2010 starts), universes and floors do not bias it.
   - Mean block length exceeds the longest holding horizon in the universe.
   - Ten tweaks of one book cost about one trial; ten unrelated books about ten.
   - Known gap, disclosed: step-down tests assume a fixed model set, while `informed_by` chains are
     adaptive. The forward confirmation covers it.
3. **Promotion (capital decision, not a verdict).** Within the selection set, the book that
   spends a forward span is chosen by pre-declared net expectation from the cost model at a
   conservative quantile. A book whose net expectation is at or below zero is not promoted,
   however strong its gross statistic. The promoted construction (costed kappa, cost-aware
   construction where used) must itself be an attempt in the selection set, so the confirmed
   book is the traded book.
4. **Forward span per book.** The span that confirms a book must be data no one looked at while
   shaping it. `.planning/gate_look_log.jsonl` records 7 scored looks at data after
   `alpha.validation.oos_start` (2025-12-24): Phase 148's `alpha_score`, the gate166 candidates,
   and the `ctf_momentum` decile long-short (gates 1 and 2, twice), the last on 2026-08-07; and
   until 2026-07-02 every IC and ensemble computation included it. So:
   - books with `feature_vectors` members or `ctf_momentum`-like members confirm only on data after
     the book's freeze date, and never before 2026-08-08;
   - price-only families 1 and 2 keep the 2025-12-24 start, disclosed as adjacent to the
     `ctf_momentum` looks.
5. **One confirmation** of the promoted book, named before its span is read, on the
   pre-registered statistic (E16/E17 unchanged). A power-dated test date more than 3 years out
   refuses promotion: a book that needs longer cannot be confirmed in useful time.
6. **Sealed shadow.** Every book in the selection set runs forward in shadow automatically.
   `book_position` output is readable only for loss-limit monitoring until each book's power-dated
   test date, so later promotion choices cannot peek at confirmation data. Shadow books make no
   claims; after their dates they show whether selection picks winners.
7. **Capital** follows the confirmed book, starts small and scales on realized net results (E15).

The Bonferroni bar rises about as sqrt(2 ln M) (t 2.94 at 30 one-sided tries, 3.29 at 100, 3.59
at 300); step-down tests price correlated tries more cheaply still. Counting is cheap; an
uncounted look is what this section exists to prevent.

### 7.4 Methodology-change-ledger entry E18

Adoption records E18:

1. E15's hard M = 30 budget and per-screen Bonferroni bar are replaced by uncapped, recorded
   attempts and Romano-Wolf StepM at selection, over everything a person saw (7.1).
2. Promotion requires positive net expectation at a conservative quantile. Test statistics stay
   gross (the costs-not-gating directive holds for discovery and every statistic).
3. The forward span is per book, with the contamination record of 7.3.4.
4. Unchanged: the single use of each forward span, E16/E17's statistic. Frozen verdicts are not
   re-scored.

## 8. Refining after capital

The deployed book is never edited in place.

| Change | Example | Path |
|---|---|---|
| Recalibration | Scheduled walk-forward weight refit | Part of the frozen recipe; not a change |
| Structural | Add a family, swap combiner or construction | Version N+1: in the selection set on updated data, then a sealed forward shadow challenger beside N. Capital moves on a pre-declared ramp only after a pre-declared paired test (difference of D_s, HAC t) passes at a test date fixed at the challenger's freeze |
| Retirement | A member's contribution leaves its control band | Decay alarm triggers review; removal is a new version on the same path |

The kill switch and risk limits are independent of all three. When data after a forward span
extends the vintage, every prior attempt is re-evaluated on the extended vintage (recipes are
reproducible) and stays in the selection universe; the count does not reset, since the new
vintage is mostly the old data.

## 9. Costs

### 9.1 Policy

| Tier | Costs | Turnover |
|---|---|---|
| Members and families (discovery) | None, gross (standing directive) | Reported only |
| Book (frozen from its first attempt) | Not in the objective; statistic gross | Kappa = 1 in discovery; costed kappa (4.4) for the promotion candidate |
| Promotion (choosing the book that spends a span) | Net expectation at a conservative quantile must be positive | Costed construction tested as its own attempt |
| Capital (after confirmation) | Measured model decides size | Cost-aware `mean_variance` |

Costs never enter a test statistic and never decide whether an attempt passed. They decide which
book is worth a forward span, and how large it trades. A book that cannot be traded at a profit
is not promoted: family 1's members carry gross Sharpe 3.8 to 5.3 at about 26x gross turnover per
session (15m slots re-ranked every slot), where 1 bp per side costs about 65% a year against about
4.7% gross. Netting happens at book level, so costs are never charged per
signal: a weak member's trades mostly net against others'.

### 9.2 Model

A pure function `cost(symbol, t, Q, side, clock)` behind one interface, used by kappa,
promotion, construction, sizing and the diagnostic band. It is staged: the **first cut**
(commission plus spread) is built now, because promotion and kappa need it; impact, the borrow
constraint and the capacity curve are added at the capital tier. Today the only real input is a flat
`alpha.construction.cost_hurdle_bps_round_trip = [1, 3, 5, 10]`; `alpha.quant.cost_hurdle.*`
are emission thresholds, not costs (todo 393, folded into this model and deleted with the old
chain).

| Component | Estimator | Data |
|---|---|---|
| Commission | IBKR tiered schedule | Published schedule |
| Spread | Quoted spread where IBKR serves historical BID_ASK; otherwise Abdi-Ranaldo (2017) from high, low, close, validated against quotes on the overlap first | IBKR BID_ASK bars (depth to be measured), OHLC |
| Fill timing | Daily books: opening auction slippage. Intraday: cross the spread at the next bar open | Same |
| Impact | `k * sigma_daily * sqrt(Q / ADV)`; `k` from the literature, tagged `[conventional]` until fill calibration (phase 159) | Volume, volatility |
| Short borrow | Fee plus availability as a hard construction constraint | IBKR shortable shares, live only |

Also: implementation shortfall against the decision price is the one cost metric, recorded by
the forward runner from day one; every component carries an uncertainty band and sizing uses a
conservative quantile; each book at the capital tier reports a capacity curve (net return against
capital), which matters most for the 195 small caps.

### 9.3 Borrow is a feasibility bias

A market-neutral book that shorts unborrowable names is not the object that will trade. Borrow
history cannot be bought from IBKR, so: a daily borrow snapshot for the full universe starts now
(same pattern as 185 D8's holdings snapshots), and every book test discloses the share of short
P&L from names outside a liquidity floor (market cap, ADV).

## 10. UCR as the recipe book

### 10.1 Today (live, 2026-09-26)

`concept_registry`: 302 features, 11 construction rows (families and members distinguished by
`metadata->>'kind'`), 5 `ensemble_strategy`. `research_run`: 5 rows, append-only.
`concept_evaluation`: 590 rows. `concept_parent`, `concept_annotation` exist. The markdown ledger
(208 lines) is the only record for most ideas and all 18 legacy verdicts.

### 10.2 Design

1. **Identity.** One `concept_registry` row per concept, typed domains: `feature`, `family`,
   `member`, `combiner`, `construction_rule`, `book`, `method`. `ensemble_strategy` retires with
   `ensemble_trainer`. An idea is a row with no recipe yet, written the day it is logged; nothing
   is ever deleted.
2. **Recipes.** New append-only `concept_recipe`, versioned per concept, UPDATE and DELETE refused
   by trigger (the SCH pattern, migrations 367/368): `recipe_hash`, code pointer
   (`module:function`) and commit, pinned params, APR keys with their values at pin time, inputs
   (feature columns; parents through `concept_parent`), universe selector (ITR/SCH predicate read
   point in time), CVR codes validated on insert, mechanism, sources, author, created date.
3. **Attempts.** `research_run` is the attempt table. It gains `recipe_hash`, `informed_by`
   (the attempt whose result prompted this one), and typed headline columns: decision statistic,
   gross Sharpe, mean return, turnover, effective N, span, and the section 13 headline numbers.
   Full series are stored for the selection test and the decay alarm.
   **Built clean, not migrated wholesale** (amendment 2026-09-26). The new schema carries over only
   live concepts (features that exist after the `feature_vectors` rebuild, families 1 and 2 and
   their members) and live attempts (the phase 183 `research_run` rows). Every old verdict and dead
   process becomes a **summary card**: a `kind = 'legacy_verdict'` attempt with the idea, recipe
   pointer (spec or pre-registration path, git commit), result numbers, known defects, spans
   looked at, and why it is closed or reopened; flagged not reproducible from stored rows, never
   re-scored. About 20-25 cards: the 18 ledger verdicts plus the old ensemble chain (Phase 148
   gates, gate166, the `ctf_momentum` gates, phase 179). Dropped, not migrated: the 5
   `ensemble_strategy` rows, the IC-gate `concept_evaluation` rows, genesis-seed transitions and
   `concept_gate` counters, all belonging to the removed lifecycle.
4. **Two axes.** `status` keeps its meaning, the production lifecycle, changed only by
   `ConceptRegistryService`. The research stage (idea -> specified -> registered -> tested ->
   refused, frozen or confirmed) is derived by a view from recipes and attempts, never stored, so
   it cannot drift. "Have we tried this" is one query on that view.
5. **Writers.** `ConceptRegistryService` (identity, status, new ideas through a CLI); the S6
   ledger writer (recipe versions at spec registration, attempts); `feature_lifecycle`
   (feature-domain evaluations).
6. **Generated ledger.** `docs/research/construction-verdict-ledger.md` becomes a generated
   `research-ledger.md` with a do-not-edit header, rendered by the nightly job (unit CI has no
   database, and a pre-commit hook should not need one).
7. **Registry roles.** APR holds defaults and history; a spec pins values at freeze and S0 refuses
   a stored input computed with a different value. CVR validates codes at load. ITR tags are
   usable as members and S1 inputs, read point in time. SCH stays the S1 sector source.

## 11. ic_engine and feature lifecycle

`feature_ic_scores` holds 10.6M rows (300 features, 99 regime codes, 4 timeframes, per symbol
and pooled). A full recompute takes 6-7 hours at 233 names and about 10 days at the 931
`compute_eligible_1d` names (todo 385). Under this design ic_engine has three jobs, none of which
needs the per-symbol x regime grid:

1. proposer: pooled cross-sectional IC per feature x timeframe x horizon;
2. IC term structure: the same cells across horizons (disclosure and horizon choice for new
   families; not kappa, section 4.4);
3. monitoring: per-member IC over time for members of frozen books.

Regime-stratified IC is kept as disclosure for `regime_volatility` only. The per-symbol x regime
grid is deleted, which makes todos 385 and 399 moot. Todo 412 (watermark) stays.

IC rows whose target window ends at or after `alpha.validation.oos_start` are purged. Today the
bound is `bar_ts <= training_window_end` (`services/ic_engine.py`), so the forward returns of the
last bars reach past the vintage end by up to the horizon: a small leak into the forward span.

Feature `status` changes meaning: computed, valid, coverage above the floor, decided by
data-quality checks. Weak standalone IC is not a reason to stop computing a feature; under E15
that would drop data that could contain signal.

## 12. Invariants and bias guards

### 12.1 Invariants

| Name | Rule | Check |
|---|---|---|
| `temporal_integrity` | Every stored fact records or derives when it became knowable; every read for t sees only facts known by t | Stored-table audit: for sampled (symbol, t), recompute the writer's output on inputs truncated at t and compare with the stored row (about 1k points a night). Details below the table. CI on fixture panels; nightly after the refresh on the corpus, to an audit table, failing loud. Covers `feature_vectors`, regime columns, `market_regimes`, factor loadings, IC |
| `determinism` | Any output reproduces bit-exactly from (input snapshot hash, code key, recipe or spec hash) | `scripts/analysis/sleeve_walk_forward/repro_frozen.py` generalized into one tool, lands with the first frozen book |
| `single_writer` | One writer per table, one direction, no cycles | DAG manifest (3.2) plus a CI scan of SQL write statements; enforced by the database through per-writer roles and grants generated from the manifest (14.5) |
| `no_fill` | Missing is NaN; warmup masked by declared memory; no placeholder reaches compute | S0 warmup mask and coverage floor (435) now; writers emit NULL during warmup at the next planned recompute |
| `point_in_time` | Universe, classification, tags and parameters read as of t | APR values: the value pinned at the book's freeze, and every stored row records which values computed it (via `lineage`). "APR as of a 2012 bar" is not meaningful: `config_history` starts 2026-06-13 and 255 of 847 keys have no history row. ITR tags and universe flags as of t (universe via 185 D8); equity breadth made point in time |
| `lineage` | Every output traces to its recipe and run | Research rows carry a run id; bulk tables get a provenance batch record (writer, per-kernel code key, APR snapshot, input content digest, symbol x tf x time range), no per-row column on compressed hypertables (the 768 GB disk-full class). The same record is the idempotency key (3.3) |
| `asset_agnostic` | Asset class is data, not a code branch | CI scan for asset-class branches in compute paths |
| `pure_compute` | Pure functions over arrays; state only at the edges | Enforced by `temporal_integrity`: its audit needs a pure `compute(inputs up to t)` entry point per writer, so an impure writer cannot be audited and fails |

**`temporal_integrity` audit details.**

- `feature_vectors` stores `real` (float32) columns, so the recompute is cast to float32 and
  compared exactly (or within 1 ulp). A float64 relative tolerance would fail every row.
- Truncation uses availability time (bar end plus any publication lag), not the stored timestamp.
  Higher-timeframe bars stamped at bar start are the N1 cross-timeframe join leak class, and a
  timestamp-truncated audit would pass them.
- Cross-sectional features (breadth, cross-timeframe broadcast) truncate every symbol's inputs,
  not only the sampled one.
- The audit records the input content digest, so a mismatch caused by a later input revision is
  told apart from lookahead.
- The pure entry point is `backfill_feature_factory`'s batch path, not a new implementation.

**Existing rows carry no provenance.** The 89 GB of `feature_vectors` has no record of the APR
values or code that computed it, so 435's "S0 refuses a stored input computed with a different
value" cannot be verified for any current row. The first feature book (attempt 5) therefore needs
a full feature recompute under provenance batches. It is budgeted in track B: todo 426's disk
guard first, and space for about 4x the table at 931 names against 496 GB free.

**Expected first findings,** stated before the first run so it measures known debt: HMM regime
columns fail `temporal_integrity` until todo 248's refit is deployed; universe flags and equity
breadth fail `point_in_time`; features written with since-changed APR values fail 435's pin
check.

Order: `temporal_integrity`, `no_fill` and `point_in_time` precede any new combiner work (data
quality first); `single_writer` and `asset_agnostic` are cheap CI checks, landing any time;
`determinism` lands with the first frozen book.

### 12.2 Bias guards

| Guard | Rule |
|---|---|
| Uncounted backtests | Research reads of `feature_vectors` and `forward_returns` go through the runner (exploration mode included), which records every attempt. A CI boundary test (the `market_data_ohlcv` pattern) fences committed code that bypasses it; the 63 existing scripts go on an allow-list with reasons. Ad hoc queries cannot be fenced; the forward span remains the backstop |
| Forward-span leakage | `snapshot.py` already refuses `end_exclusive` past `alpha.validation.oos_start`. That key becomes write-once (DB trigger refusing updates), so one config write cannot silently reopen the span |
| Survivorship | The 932-name universe is today's S&P 500 plus names alive today, and both research universes read current state (`snapshot.py` reads `valid_to IS NULL` tags and classification; `universe_symbols` reads current flags). Every attempt states its universe as of t and carries phase 185 D0's survivorship bound; daily cross-sectional books also report a delisting-return sensitivity (a fixed delisting return applied at a Shumway-style hazard), since reversal books are the most exposed; books on long-lived ETFs are disclosed separately. 185 D8 (keep every name, record delistings) must be live before a forward span starts |
| Parameter hindsight | A structured APR provenance column; values tuned on outcomes (`[rca_analysis]`, `ml_learned`, anything tuned on IC or returns) are disclosed for every book that uses them. `[conventional]` values are not hindsight |
| Second implementation | The forward runner executes the same S0-S7 code on new rows and reads nightly batch features only. Positions for overlapping rows are bit-identical between research and forward (parity test); 184 B2's kernel parity test covers features |
| Forward runner edge cases | Forward mode is the only sanctioned read past `oos_start`, keyed to a frozen book id. It fails loudly when a member's coverage falls below its in-sample band or a member stops being computed. Emitted `book_position` rows are append-only; a later recompute that differs raises a data-revision alarm instead of overwriting |

### 12.3 Protocols

Extension surface is three protocols: `PredictorSource` (today `SignalSource`), `Combiner`
(exists), `ConstructionRule` (new, wraps the existing arms). Families are data (spec YAML) plus
pure functions. The forward runner uses the same three.

## 13. Contribution accounting

A standard output of every book test. Two questions with different measures: who earned the
return (attribution, additive) and who is necessary (marginal, counterfactual).

1. **Attribution at two levels.**
   - Forecast level, exact for any construction:
     `cov(book_forecast, r) = sum over k of v_k * cov(s_k, r)`; each member's term is its share of
     the forecast's predictive content. The primary table.
   - P&L level: exact per-member split (walk-forward weight x member P&L, plus Euler risk shares)
     for linear constructions (`vol_normalized`, `mean_variance`). R1 ranks the forecast, so
     member terms do not add up to book P&L; under R1 the P&L split is by family Shapley values
     (item 3), which sum to the total by construction.
2. Leave-one-family-out: walk-forward refit without family k; change in the book statistic.
3. Shapley over families, when a book has 4 or more families (below that, leave-one-family-out
   plus weight-sign stability says the same): subset refits with the book's own combiner (ridge
   closed form, or equal-weight subsets under the default) on the book's own folds, exact up to
   about 12 families, sampled beyond. Catches what leave-one-out misses: two redundant families
   each look unnecessary when removed alone.
4. Uniqueness (each member residualized on the others) and effective breadth (eigenvalues of the
   signal correlation matrix).
5. Standalone vs in-book table: ic_engine IC beside in-book contribution; flags
   strong-but-redundant and weak-but-additive members; tests whether `ic_proposal` picks
   contributors.
6. Stability by sub-period, regime (the 5.2 disclosure table) and lag; weight-sign stability
   across folds (a cheap overfitting tell).
7. Turnover and cost share per member.
8. Forward monitoring: per-member realized contribution on a control chart against its in-sample
   expectation; leaving the band is the decay alarm (section 8).

**Accounting groups inside large families.** Items 1-3 need groups to split. A prior-driven
family is small enough to read member by member, but `corpus_family` (about 300 members) and
`generated_family` (thousands) are one family each, so leave-one-family-out and Shapley have
nothing to split. Inside them, contributions are read by:

- **feature origin (primary):** the feature phase or grammar branch that built each member (SMC,
  VP/SR, calendar, momentum, volatility, ...; for generated members, primitive and operator).
  Readable and fixed in advance.
- **in-fold correlation clusters (beside it):** clusters computed inside each training fold,
  never from full-vintage data.

Accounting groups exist only for reading contributions. They never decide admission or weights,
so they cannot bias the test.

Discipline: diagnostics, not tests; per-member t-stats are not significance claims. They never
edit the book they measure: a pruned book is a new version, outcome-informed, and a counted
attempt. Compute-only S8 extension; headline numbers are typed columns on the attempt; series
stored; `BookTracker` emits per-member series in forward shadow.

## 14. Deletions, fencing and re-scoping

### 14.1 Delete (git history is the archive)

| Component | Role today |
|---|---|
| `services/ensemble_trainer.py` | IC-weighted combiner (estimator reborn as the IC-Sharpe `Combiner`) |
| `services/ensemble_ic_engine.py` | IC of the ensemble output -> `alpha_ensemble_ic` |
| `services/alpha_frame_writer.py` | `alpha_events` -> hypothetical trade frames |
| `services/counterfactual_tracker.py` | FRAME-04 exit gate on those frames |
| `scripts/ops/alpha/ops_ensemble_*`, `ops_emission_threshold_sweep.py`, `ops_ensemble_ic_gate.py`, `scripts/ops/corpus/ops_oos_gate1_signal_eval.py` | Operating the old chain |
| `scripts/analysis/sleeve_walk_forward/` plumbing | Phase 179 harness, superseded by the research layer (check `research/portfolio.py` imports first; the construction arms survive in `ConstructionRule`) |
| Orchestrator steps after `ic_engine` and `feature_lifecycle` | Chain wiring (`ops_pipeline_monitor.sh`) |

`services/alpha_publisher.py` is replaced by `BookTracker` and `BookPositionWriter`.
Checked at plan time: `services/cross_sectional_spread_tracker.py` (phase 167's long-short
primitives; deleted if R1 covers it); `services/context_writer.py`, whose unit
`indicagent-ctx-writer.service` is the one component here currently active, needs a consumer
check before any decision; whether `feature_lifecycle` reads `alpha_ensemble_ic` beyond the
removed gates.

### 14.2 Summarize, then drop (amended 2026-09-26)

Rule: **raw data is permanent, derived data is cache, conclusions are records.** Market data
(bars, dividends, IBKR raw observations) is the only thing that cannot be regenerated and is kept
forever; it is what "never drop data that could contain signal" protects. Anything computed by
code can be rebuilt from git history plus raw data; once the process that made it is dead, the
cache has no reader. What was learned lives on as summary cards in UCR (10.2 item 3). This
replaces the earlier keep-and-fence decision.

Measured 2026-09-26 (database 174 GB):

| Data | Size | Decision |
|---|---|---|
| `market_data_ohlcv`, `dividend_events`, IBKR raw observations (phase 185) | 10 GB | Keep forever |
| `alpha_events`, `ensemble_alpha`, `ensemble_weights`, `alpha_ensemble_ic`, `alpha_frames`, `context_features` | 9.7 GB | Summarize, then drop |
| `feature_ic_scores_history` | 38 GB, uncompressed | Drop: an archive of superseded IC rows on each fingerprint invalidation; no decision reads it and the grid it archives is deleted |
| `feature_ic_scores` | 0.7 GB | Keep (live: proposal, term structure, monitoring). Old-grid rows go with the ic_engine shrink; current rows stay until the shrunk engine writes fresh ones on rebuilt features |
| `forward_returns` | 14 GB | Keep (live, rebuildable) |
| `feature_vectors` | 89 GB (491 GB uncompressed) | Live input: replaced by a rebuild (below), old table dropped only after the rebuild is validated |
| `.planning/gate_look_log.jsonl` | small | Keep: the forward-span contamination record is a conclusion, not a cache |

**`feature_vectors` rebuild, not refresh.** The first feature book needs a full recompute under
provenance batches anyway (12.1). Updating the compressed table in place is the pattern behind the
2026-08-13 disk-full incident and todos 149, 161 and 426 (426: decompression would need 491 GB
against 414 GB free). Instead: a new table written append-only in time order, each chunk
compressed when complete, provenance from the first row, and a cleaner schema (never-computed
columns such as todo 421's rank_z features and exact duplicates such as todo 115 removed); a
sampled drift report against the old table; swap names; drop the old table. This replaces the
in-place refresh chain (426 step 2, 411) with one build.

**Timeframes in the rebuild: open, decide before specifying it.** 5m holds 75M of the 109M
`feature_vectors` rows (about 69%), so it is most of the rebuild's cost. No active family reads 5m
features (families 1 and 2 run on the 15m grid); ledger family 3 (sector ETF leads constituents)
is written "5m or 15m". The 2026-09-13 per-timeframe cost check found 5m signal real but economic
only at about half-day holds, a horizon 15m also covers. Untested: whether 5m features add IC
over 15m at matched horizons. Run that test first; if they add nothing, the rebuild covers 15m,
1h and 1d, and raw 5m bars keep ingesting either way (raw data is permanent, features are cache).

**Safeguards.**

1. Summary cards are written and checked before anything is dropped.
2. Every drop is a migration committed in the same breath as it is applied, after a repo-wide
   consumer grep.
3. Nothing is dropped while another session's run reads it.
4. Performance-investigation SOP for every operation on a compressed hypertable.

Expected result: about 174 GB to about 60 GB after the drops, about 100 GB once the rebuilt
`feature_vectors` lands.

### 14.3 Re-scope

| Item | New scope |
|---|---|
| Phase 170, plans 07-08 | Gate (`alpha_ensemble_ic` rows) never clears; rewritten to finish the `feature_registry` retirement without an ensemble rehearsal, since feature status is data-quality based |
| Phases 156-157 | `portfolio_state` and sizing on top of construction and the forward runner |
| Phases 158-159 | Interface only, then fill-calibrated costs, after a book passes confirmation |
| Phases 149-150, todo 275, glossary `PrecedentEngine` | Precedent predictors enter as family members, not "weighted by AlphaEngine's ensemble" |
| Phase 184 | Revised per 435 (reads `feature_vectors`); B4 feeds kappa |
| `docs/plans/2026-09-24-edge-proof-program.md` | Status: superseded by this design |
| Todo 423 | Retitled as a family 4 member |

### 14.4 Todo dispositions

- Closed as moot, with a pointer here: 214, 385, 399, 337, 419, 166, 009 item 4, the
  `alpha_publisher`/ensemble parts of 352 and 228, 393 (folded into section 9).
- Folded under `ic_proposal` and `in_fold_selection`: 191, 038, 099, 039, 115.
- Folded into the deletion work: 355.
- Kept: 412; the refresh chain (426, 290, 248, 411, 421); 390 before `illiq` enters a family.

### 14.5 Database hygiene (best-practices audit, 2026-09-26)

Read-only audit of the live database against the Postgres best-practices rules. Checked clean: no
timestamp-without-time-zone columns, no `json` columns, no uppercase identifiers, no significant
dead tuples, 4 of 200 connections in use, `pg_stat_statements` installed, `random_page_cost` tuned
for SSD.

| Finding | Action | Where |
|---|---|---|
| `postgres-exporter`'s per-table scrape over every chunk table is the top consumer by total time (305 min in 3 days) | Exclude chunk tables or slow those collectors | Todo 443 |
| `idle_in_transaction_session_timeout` is 1 hour | 5-10 minutes | Todo 443 |
| Row-at-a-time inserts (`ensemble_alpha` 107M calls, `alpha_events` 66M, `feature_ic_scores` 18M) | New writers load with `COPY` in chunk order | Phase 186 |
| Duplicate 400 MB indexes on `market_regimes` (PK unused) and on `construction_spreads` | Drop the non-PK duplicate | Phase 186 |
| 11 tables without a primary key, mostly v2.x or monitoring | Dropped in the dead-table sweep or given a PK | Phase 186 |
| `shared_buffers` 3 GB on a 29 GB host; `work_mem` 8 MB | Measure, then tune (about 25% for `shared_buffers`; `work_mem` per batch session) | Phase 186 |
| Every service connects as the `postgres` superuser | One role per writer with grants only on its own tables, read-only roles for readers, generated from the DAG manifest: `single_writer` enforced by the database | Phase 187 |
| Foreign keys without indexes | Indexed in the clean UCR schema | Phase 187 |
| Integrity services: most check archived v2.x tables and are disabled; none checks historical price correctness; `regime_coverage_auditor` fails every night on 5 known symbols | Auditor inventory in the DAG manifest (live with an owner and an action, or archived); price integrity is phase 185 D2a/D7; todo 341 resolves the nightly alarm | Phases 185, 187; todo 341 |

### 14.6 Refactor map

Refactor only code that survives and that this design already touches; delete the rest; leave
the v2.x tree (archived under the dual intelligence-path decision), `src/providers/ibkr.py`
(phase 185) and the dormant streaming daemons alone. Sizes measured 2026-09-26.

| # | Code (lines) | Refactor | Phase |
|---|---|---|---|
| 1 | `src/intelligence/feature_factory.py` (8,733) | One module per feature origin (price dynamics, volume and flow, SMC, VP/SR, calendar, macro, regime) behind one kernel registry: declared inputs, memory and dtype, pure `compute(inputs up to t)`. The entry point the rebuild, the `temporal_integrity` audit, the forward runner and 184's kernel table all need; the module split is also the feature-origin accounting grouping (UD-23) | 186, before the rebuild |
| 2 | `services/ic_engine.py` (6,755) | Not refactored: the shrunk engine is written fresh as three small pure jobs (proposer, term structure, monitoring) over `ic_math.py` plus one writer, run beside the old engine to parity on pooled cells, then the old engine is deleted (strangler) | 186 |
| 3 | `services/_batch_utils.py` (1,369) | One bulk-load primitive: `COPY` in chunk order, compress each chunk when complete, provenance batch record, content-digest idempotency key; every writer uses it. Absorbs todos 301, 343 and 352 and the audit's row-at-a-time finding | 186 |
| 4 | `services/backfill_feature_factory.py` (1,815), `feature_vector_persistence.py` (927) | The single batch feature path (the rebuild writer) on #1 and #3. The dormant `feature_vector_pipeline.py` (1,749) only imports the same kernel registry | 186 |
| 5 | `services/regime_writer.py` (2,640) | Walk-forward as the only mode (full-history path deleted once todo 248 deploys); todo 290's memory and query fixes; todo 291's duplication. Fixed once, before the rebuild consumes its columns | 186 |
| 6 | `services/feature_lifecycle.py` (924), `ConceptRegistryService` | Lifecycle shrinks to data-quality checks; the registry service is rebuilt on the clean UCR schema | 186, 187 |
| 7 | `services/service_auditor.py` (891), `ops_corpus_pipeline_run.sh` | Both read the DAG manifest; `_DAG_ORDER` deleted | 187 |
| 8 | Research package (`runner.py` 934, `portfolio.py`, `signals.py`) | The three protocols; construction arms become rules; `runner.py` split into spec loading, execution and recording; renames with todo 430. Waits for phase 183 plan 10 | 187 |

**Delete, not refactor:** the old chain (`ensemble_trainer`, `ensemble_ic_engine`,
`alpha_frame_writer`, `counterfactual_tracker`, `alpha_publisher`, about 5,500 lines);
`cross_sectional_spread_tracker.py` (1,942) if R1 covers it; `scripts/analysis/` (71 scripts,
26.8k lines) once summary cards exist, after promoting reusable helpers (`_date_panel.py`, the
cost-band helpers) into the research package. Git history keeps every deleted file.

**Rules for every refactor.**

1. Parity before and after: a refactor commit changes no output (byte-identical float32 on a
   feature sample, identical IC on pooled cells); behavior changes are separate commits.
2. No edits to modules `ic_engine` imports while a corpus run is live or resumable.
3. APR migrate-as-you-go applies to touched code.
4. Refactor behind tests; add tests first where a module has none.

Net effect: the three largest modules become small single-purpose modules and about 34k lines of
dead chain and analysis scripts go, roughly a third of the live codebase.

## 15. Vocabulary

Rule: rename only where a name misstates the role or collides; everything else keeps its name.
Todo 430 enforces (curated bans, full-tree ratchet, YAML/SQL/dashboard coverage); this section is
its input.

### 15.1 Collisions

| Collision | Resolution |
|---|---|
| Brief's invariants I1-I8 vs intelligence tiers "I1 price dynamics" ... "I4 regime state" | Invariants named by concept (12.1) |
| Methods D1-D5 vs phase 185 stages D0-D8 and phase 183 requirements D-01 | Methods named (section 6) |
| Research S0-S9 vs AlphaEngine "Stage 0-4" vs pipeline labels | Pipeline stages by name (3.1); S0-S9 research sub-steps only; AlphaEngine stages retired |
| "signal" (archived v2.x trade hypothesis) vs `research/signals.py`, `SignalSource` | `predictors.py`, `PredictorSource` (todo 430 step 4) |
| Two meanings of "weight" | `member weight` (S7) vs `position weight` (construction); S7's output is the `book forecast` |
| `book`, `book version`, `screen` glossary entries (ridge only; spends one of M) | Redefined per sections 4.1 and 7 |
| UCR `domain = 'construction'` holds families | Split into typed domains (10.2) |

### 15.2 Retired terms

Legacy entries kept with a pointer to the replacement, banned in new code and docs:
`AlphaEngine` as a system, `ensemble alpha`, `alpha score`, `alpha emitter`, `ensemble optimizer`,
`alpha scorer`, `weight_version`, `sleeve`, `IC discovery` as an admission step.

### 15.3 New terms

`construction rule`, `horizon rule`, `frozen book`, `forward runner`, `champion`/`challenger`
(reused, now for books), `recipe`, `recipe version`, `attempt`, `research stage`,
`selection test`, `decay alarm`, `contribution` (attribution vs marginal), `state variable`,
`regime disclosure`, `provenance batch`, `summary card`.

### 15.4 Names in code

`BookTracker` (compute) and `BookPositionWriter` (persistence), checked against
`docs/foundation/naming-system.md`'s suffix taxonomy at plan time ("Publisher" means DB -> Kafka,
which is no longer the job). Kept: `ic_engine`, `feature_lifecycle`, `ConceptRegistryService`,
`regime_writer`. New tables: `concept_recipe`, `write_provenance`, `book_position`.

Renames land with the implementation of each piece. Research-package renames wait for phase
183 plan 10 and family 2 to finish, together with todo 430 step 4.

## 16. Build order

Research attempts keep running in parallel with the build and never queue behind
infrastructure (owner directive, alpha first).

| Track | Work | Waits on |
|---|---|---|
| Now | First-cut cost model (IBKR commission, Abdi-Ranaldo spread, validated on a quoted overlap); borrow snapshot capture; `oos_start` write-once; 185 D8 holdings snapshots | nothing |
| Alpha, continuous | 183-10 and E17's H0 battery (with ridge and kappa cells) -> attempts 1a-1c; attempt 2 with the first-cut cost model; attempts 3-4 (price-only daily families on the 931 names, sector lead-lag) | running; S1 residual target on 931 names |
| A: delete | Remove the old chain; summarize then drop its tables and `feature_ic_scores_history`; shrink ic_engine; feature lifecycle to data-quality gates; close moot todos | Phase 183 not touching those modules; no live or resumable ic_engine run (the import rule) |
| B: data path | 426 -> 290 -> 248 -> 411 (+412, 421); `temporal_integrity`, `no_fill`, `point_in_time` audits; phase 185 | A's ic_engine shrink (smaller recompute) |
| C: research core | UCR recipe book and migration; StepM selection and E18; `ConstructionRule`, pod books and horizon rule; missing-member combining rule; contribution accounting; DAG manifest; vocabulary renames with 430 | 183-10 finished |
| D: features into books | Full feature recompute under provenance batches; 435 S0 wiring; revised 184 (B3 alignment) -> attempts 5-8 | B, C |
| E: forward | `BookTracker` and sealed shadow for every book in the selection set; full cost model; attempt 9; 156-157 re-scoped | A candidate from the alpha track or D |
| F: capital | Promotion by net expectation, forward confirmation on the book's own span, capital ramp; 158; 159 | E; 185 D8 live before the span |

After adoption, A, C and E become new roadmap phases (about 186-188); B maps onto existing todos
and phase 185; D is 435 plus revised 184; F keeps 158-159, re-scoped. Critical path: attempts 1-4
need only E17, the first-cut cost model and the S1 target on the 931 names, so a tradeable verdict
can come from the alpha track before any feature book; the first feature book needs A -> B -> C ->
full recompute -> 435. Freezing a book early matters: a forward span only accrues for frozen books.

## 17. Acceptance checks (`docs/foundation/principles.md`)

| Principle | Answer in this design |
|---|---|
| Data quality over model complexity | Data path and three integrity audits precede any new combiner (16, 12.1) |
| Never drop data that could contain signal | No per-feature admission gate; feature status by data quality, not IC; raw market data kept forever; ideas never deleted, dead-process output kept as summary cards (11, 10, 14.2) |
| Earn capital through proof; resist overfitting | Everything a person saw on the vintage counted; StepM over all of it; promotion only with positive net expectation; one confirmation on a span no one looked at; contributions never edit a tested book (7, 13) |
| Segment by regime | Disclosure on every book, one conditioning variant through continuous states, never gating thin cells (5.2) |
| Shadow mode first | Every book in the selection set in sealed forward shadow before capital (7.3) |
| Instrument everything | Attempts, recipes, provenance batches, audits, contribution and decay series (10, 12, 13) |
| Automate manual tasks | DAG manifest replaces two hand-kept orders; generated ledger replaces a hand-edited one; nightly audits (3.2, 10.2, 12.1) |
| Empirical over theoretical | Combiners and constructions compete on the same test (4, 6) |
| Deterministic DAG, one writer, compute separate from persistence | Manifest-checked; `BookTracker` vs `BookPositionWriter`; kernels pure (3, 12) |
| No silent wrong answers | Dead tables dropped, not left queryable; write-once span boundary; audits fail loud; expected findings stated first (12, 14.2) |

## 18. Deferred ideas

Recorded as `idea` concepts in UCR once it exists, not lost:

- **Execution-measurement program:** trade the forward runner's shadow orders at a capped
  minimal notional before any book is confirmed, to measure real auction slippage, spread capture
  and fill rates a year before phase 159. Owner: good concept, deferred 2026-09-26.
- **Execution routing** (low-latency, Nautilus Trader as the flagged candidate): interface only
  until a book passes confirmation.

## 19. Adoption actions

All done 2026-09-26:

1. Independent review (Fable 5.1, file paths only, adversarial prompt); findings folded in
   (section 20).
2. Owner adoption; status line ADOPTED.
3. Methodology-change-ledger E18.
4. Glossary (retired terms marked legacy, new vocabulary added, `book`, `book version`,
   `screen`, `confirmation`, `vintage` redefined) and naming-system (`AlphaEngine` retired,
   `PrecedentEngine` repointed). Bans are left to todo 430's curation.
5. ROADMAP: phases 186 (track A), 187 (track C), 188 (track E); re-scope notes on 149, 150, 156,
   170 and 184; v4.0 parking note revised.
6. Todos: 214, 385, 399, 337, 419, 166 closed as moot, 393 folded into 437, 436 closed; notes on
   009, 038, 039, 099, 115, 191, 228, 352, 355, 423 (retitled), 435; new 437-442 with
   PRIORITIES.md rows.
7. STATE.md strategic plan updated; `docs/plans/2026-09-24-edge-proof-program.md` marked
   superseded.

## 20. Review resolutions

Independent adversarial review by Fable 5.1, 2026-09-26, file paths only. Each finding was checked
against the code or database before disposition. Items 1 and 2 reversed decisions approved in
the brainstorm and were accepted by the owner the same day.

| # | Finding (severity) | Verified | Disposition |
|---|---|---|---|
| 1 | Forward span already looked at for feature books (blocker) | `.planning/gate_look_log.jsonl`, 7 looks, last 2026-08-07 | Accepted (owner): per-book span, 7.3.4, E18 |
| 2 | Gross selection promotes an untradeable book; kappa is a cost device in Garleanu-Pedersen (blocker) | Family 1: 26x turnover per session, 1 bp/side costs ~65%/yr vs ~4.7% gross | Accepted (owner): net-expectation promotion, costed kappa, first-cut cost model now (4.4, 7.3.3, 9) |
| 3 | Attempt 1 refused by code: families 1 and 2 differ in horizon and panel (major) | `spec.py` `_check_book` | Accepted: single-family books plus a pod book (4.1, 6) |
| 4 | SPA underspecified; selects poorly (major) | design text | Accepted: Romano-Wolf StepM at 0.05 now, series, calendar, block length, adaptivity gap (7.3.2) |
| 5 | Counting excluded looks that steer selection (major) | design text | Accepted: everything a person sees joins the selection universe (7.1) |
| 6 | E17 memory ignores combiner and kappa reach (major) | `runner.py` passes `max(slot_histories)` | Accepted: L rule and H0 battery cells (4.5) |
| 7 | `corpus_family` equal weight has no signs and collapses on NaN (major) | `combiner.py` `EqualWeight.combine` complete-case | Accepted: in-fold signs, missing-member rule (4.2) |
| 8 | Kappa and IC-Sharpe clusters from full-vintage IC are outcome-informed; IC targets cross `oos_start` (major) | `feature_ic_scores` single `training_window_end` | Accepted (4.2, 4.4, 11) |
| 9 | Shadow books and challenger ramps read the confirmation span (major) | design text | Accepted: sealed shadow, eligibility = selection set, paired challenger test (7.3.6, 8) |
| 10 | REVOKE does not bind a superuser (major) | `pg_roles`: `postgres` only, superuser | Accepted: raising triggers (14.2) |
| 11 | Watermark idempotency key misses revisions; all-imports code key over-triggers (major) | design text, todo 433 | Accepted: content digest, per-kernel code key (3.3) |
| 12 | Audit tolerance wrong for float32; truncate by availability time; cross-sectional truncation; revision vs lookahead (major) | `feature_vectors` `real` columns | Accepted (12.1) |
| 13 | APR as of bar time meaningless; existing rows unpinnable (major) | `config_history` from 2026-06-13; 255 of 847 keys without history | Accepted: pin at freeze, full recompute before attempt 5 (12.1) |
| 14 | Attempt order not the shortest path to a tradeable verdict (major) | features cover 233 of 931 names | Accepted: price-only daily families and single-family books first (6, 16) |
| 15 | Survivorship: both universes read current state (minor) | `snapshot.py` | Accepted: delisting-return sensitivity (12.2) |
| 16 | Forward runner edge cases (minor) | `combiner.py` `refit_positions` anchors to row 0 | Accepted: calendar-anchored refits, coverage alarms, sanctioned bypass, append-only positions, failed-after-statistic counts (4.1, 7.1, 12.2) |
| 17 | Vintage roll should not reset the count (minor) | design text | Accepted: re-evaluate prior attempts, no reset (8) |
| 18 | Bonferroni wording; maximum test horizon (suggestion) | arithmetic | Accepted: sqrt(2 ln M); 3-year maximum (7.3) |
| 19 | Over-engineering (suggestion) | design text | Partly: Shapley only at 4+ families with the book's own combiner; ledger rendered nightly only; cost model staged; timers validated against the manifest. Kept: the `asset_agnostic` CI scan (a cheap grep) and the vocabulary rule (already limited to collisions) |

