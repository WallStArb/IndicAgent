# ITR Extension Opportunities -- Idea

**Status:** Idea -- survey, not designed to implementation-readiness. None of these have had
a rigor pass (Fable or otherwise) yet, unlike the sibling doc this survey grew out of.
**Author:** Claude (Sonnet 5), interactive session, 2026-09-18. Item #6 added same day,
surfaced during Phase 175's D-07 cross-AI review while explaining why the sign-stability gate
exists.
**Origin:** Follow-on to `docs/ideas/signal-sensitivity-regime-interaction-primitives.md`
(that doc's Fable rigor pass, same session). User asked, after that review landed: are there
ways to extend the ITR *concept* itself, beyond one interaction-feature idea, at
Renaissance/Simons-grade rigor? This doc is the answer -- a ranked survey of candidate
extensions, cross-checked against what's already documented so it doesn't duplicate existing
design work.

---

## Why this doc exists, and what it isn't

The interaction-primitive doc answers one question: how do we use the sensitivity loadings
ITR already measures. This doc asks a different, prior question: is ITR itself measuring,
storing, and validating instrument classification claims as rigorously as it could -- the
same "why is this a permanent guess when it's measurable" reframe ITR already applies to
instrument classification, applied recursively to ITR's own machinery.

Six candidates are catalogued here. Two (regime-conditioned betas, mutual-information
measurement) already have real design work behind them and just need scheduling or
narrow-vs-broad scoping. Four (point-in-time history, walk-forward re-validation,
cross-tag collinearity, instrument-level structural break detection) are genuinely new --
flagged at most as a one-line gap, if flagged at all -- and get a real design sketch here
rather than a one-paragraph pitch.

This is not a plan doc. Nothing here has a task breakdown, an APR key list, or a migration
number. Per this project's own graduation discipline, that comes after a rigor pass and a
decision to build, not before.

---

## Ranked candidates

### 1. Point-in-time history for `instrument_tags` -- highest leverage, least documented

**Current state:** flagged as one bullet in `docs/foundation/instrument-tag-registry.md`'s
"Known Gaps" section ("No dedicated audit-log table... A `git log`-style 'show me this tag's
full history' query isn't directly supported"). No design doc, no todo, no schema sketch.

**Why this ranks first.** Every `TagCalibrator` run overwrites `loading`/`p_value`/
`sample_n`/`estimated_at` on the current `instrument_tags` row in place
(`_UPSERT_EMPIRICAL_SQL`, `tag_calibrator.py:599-617`). Only `valid_from` is set once, on
first insert, and never touched again. There is exactly one `loading` value per `(symbol,
tag)` at any moment: today's. This produces two distinct, independently serious problems:

- **Scientific-integrity gap.** No way to reconstruct "what did TagCalibrator believe about
  TLT's rate sensitivity six months ago" -- the evidence trail for a past decision is gone the
  moment a newer measurement overwrites it. APR solved the identical problem for numeric
  parameters with `config_history`; ITR has no equivalent for classification claims.
- **Structural lookahead blocker, confirmed live 2026-09-18.** Fable's rigor pass on the
  interaction-primitive doc found this independently: any full-corpus historical IC test
  that joins a `sensitivity` loading against `market_regimes` state would silently use
  *today's* loading for every historical timestamp back to the start of the corpus, because
  no historical loading exists to join against instead. This isn't a query-filtering bug
  fixable by respecting `valid_from <= ts` -- the row that would need to exist at an earlier
  `ts` was never kept.

**What a fix looks like, sketched (not designed):** an append-only `instrument_tags_history`
table, one row per `(symbol, tag, measured_at)`, written alongside (not instead of) the
current-state upsert in `TagCalibrator`'s Pass 3 -- same shape as APR's `config_history`
recording every write with `changed_by`/`reason`. The current `instrument_tags` row stays
the fast-path read for every live consumer; the history table exists purely so a backtest or
an audit query can ask "what was true as of timestamp X" instead of "what's true now."

**Unlocks:** both a real audit trail (small win, done for its own sake) and a hard
prerequisite for #4 below and for the interaction-primitive doc's own historical-IC test
(large win, blocks other work today).

---

### 2. Regime-conditioned betas -- already designed, just unscheduled

**Current state:** fully designed. `docs/research/tag-calibrator-phase2-regime-conditioning.md`
(TAG-02) -- primary key extends `(symbol, tag)` to `(symbol, tag, regime)`, explicitly cites
Renaissance's own stated practice ("everything was regime-conditional"), gives the canonical
example (TLT's `rate_sensitive` beta differs materially between flight-to-quality and calm
regimes, and Phase 1's single blended average cannot represent that). Status: design-only,
not scheduled into any phase, gated on a stated ship condition (read the doc for the exact
condition before scoping this).

**Why it's listed here at all:** it's the most directly "Simons-grade" of the five --
Renaissance's stated methodology is cited by name in the existing design doc, not inferred by
this survey -- and it structurally subsumes the interaction-primitive idea rather than sitting
alongside it. Instead of measuring one unconditional loading and multiplying it by regime
state as a downstream feature (the interaction-primitive doc's approach), TAG-02 measures the
loading *as a function of* regime directly. Anyone picking up the interaction-primitive doc's
first test should read TAG-02 first and decide whether the interaction-feature approach is
still worth building as an interim step, or whether it's better to go straight to
regime-conditioned measurement.

**Nothing to design here.** The open question is sequencing/scheduling, not architecture.

---

### 3. Unimplemented measurement types -- partially designed, narrower than it first looks

**Current state:** `tag_vocabulary.measurement_type` schema already allows `'correlation'`,
`'cross_correlation'`, and `'mutual_information'` alongside the only implemented type,
`'beta_regression'` -- unimplemented types are logged once and silently skipped (by design,
defense-in-depth, per `docs/foundation/instrument-tag-registry.md`'s Known Gaps).

**The narrower part:** `mutual_information` is not just a schema placeholder -- it's already
scoped in the original design doc, but for one specific purpose: a `regime_classifier`
`signal_role` tag measuring "how much does regime state explain this instrument's price
action" (`docs/research/stratification-instrument-tag-calibrator.md:59,105,176,219,395` --
"MI against HMM regime state"). That's a real, narrow, already-designed use case, distinct
from the broader use this survey's earlier conversation gestured at: using MI generally to
catch *any* nonlinear factor-sensitivity relationship an OLS beta would miss (zero linear
correlation, real dependence). The narrow version has a design; the broad version doesn't.

**What's actually open:** whether the broad version (MI as a general-purpose sensitivity
measurement type, not just a regime-classifier detector) is worth designing at all, or
whether `beta_regression`'s known blind spot (linear-only) is better addressed some other
way. Not resolved here -- flagged as genuinely open, not pre-decided.

---

### 4. Walk-forward re-validation over a tag's whole life -- new, and distinct from an existing mechanism

**Current state:** not documented anywhere as its own idea. Easy to conflate with something
that *is* documented -- don't.

**What already exists:** F5 in the original design doc (`stratification-instrument-tag-
calibrator.md`, "'Tests on next run' is not out-of-sample confirmation") specifies a
one-time discovery-to-confirmed gate: a newly discovered tag sits `pending_oos` until
`alpha.tag_auditor.discovery_oos_days` (63 days) of *post-discovery* data confirms it,
explicitly modeled on `ic_engine`'s walk-forward embargo discipline. Phase 175 is actively
enforcing this (todo 125 fold-in) as part of its materiality filter.

**What's missing:** F5 gates promotion once, at discovery. It says nothing about a tag that
has already been `source='empirical'`/confirmed for a year -- does its predictive power (not
just its current-window significance) still hold? A tag currently only needs to keep
clearing `passes_fdr` on each successive `lookback_days` window to avoid the hysteresis
expiry counter; nothing checks whether a *previously* measured loading actually predicted
its own next-period continuation. That's a different, stronger claim than "still
statistically significant this quarter" -- it's closer to "this relationship has genuine
walk-forward predictive value," the same distinction `ic_engine.py`'s own IC-measurement
discipline draws between in-sample fit and out-of-sample forward-return prediction.

**What a fix looks like, sketched:** for each confirmed empirical tag, periodically check
whether the loading measured at time T actually predicted the sign/magnitude of the
relationship observed in [T, T+discovery_oos_days] -- not just whether a fresh regression at
T+N still clears FDR independently. This needs #1 (point-in-time history) to be buildable at
all, since it requires comparing a past loading against what actually happened after it was
measured, not just the current row.

---

### 5. Cross-tag collinearity audit -- new, and distinct from an existing, deliberately-deferred concern

**Current state:** not documented as its own idea. Also easy to conflate with something
that exists and was explicitly scoped *out*.

**What already exists:** the design doc flags factor-*series proxy* collinearity -- TLT/IEF/
SHY all measuring overlapping duration exposure, VUG/VTV/MTUM all overlapping on growth/
value/momentum -- as a concern for BH-FDR validity (positive regression dependence), and
explicitly defers it: "If factor-series collinearity... ever proves material, `ic_engine`'s
cluster-representative refinement... is the established in-house pattern to borrow. Not
needed for v1" (`stratification-instrument-tag-calibrator.md:441-444`). That's about the
*regressors* being correlated with each other.

**What's different here:** a single symbol's measured loadings *across different tags* can
be collinear even when their proxies aren't identical -- `rate_sensitive` (proxy `TLT`) and
`credit_risk` (proxy `HYG-IEF`) both riding the same underlying flight-to-quality factor for
a given instrument, say, without either proxy being the other's regressor. Nothing in ITR
today measures or flags this. It matters specifically because of Phase 175 and the
interaction-primitive doc: once multiple sensitivity loadings start feeding into features or
gates (materiality filters, interaction products), two nominally-different tags that are
secretly measuring almost the same thing on a given symbol create redundant, correlated
inputs downstream -- the same failure class Phase 175's own materiality filter is designed to
catch for a single tag against a control set, generalized here to tag-vs-tag instead of
tag-vs-control.

**What a fix looks like, sketched:** a periodic pairwise-correlation audit across each
symbol's own set of measured `sensitivity`/`macro_driver` loadings (not the proxies -- the
measured `loading` values themselves, across the symbol's tag set), flagging pairs whose
correlation across the active universe exceeds some threshold as candidates for either
merging (same rule that already retired `credit_cycle` into `credit_risk`) or explicit
downstream de-duplication before they're both allowed into the same feature/gate.

---

### 6. Instrument-level structural break detection -- new, distinct from TAG-02's regime-conditioning

**Current state:** not documented anywhere. Surfaced 2026-09-18 during Phase 175's D-07
cross-AI review, discussing why Pass 4's sign-stability gate exists at all.

**Why this is a different problem from TAG-02 (#2 above), not a restatement of it.** TAG-02
conditions the SAME instrument's SAME business on a market-wide state variable -- TLT's
`rate_sensitive` beta legitimately differs between a flight-to-quality regime and a calm one,
but TLT is still a Treasury bond ETF the whole time. This candidate is about a different axis
entirely: the instrument's own underlying business or asset composition changing, independent
of any market regime. The canonical example: MSTR was an enterprise software company through
roughly 2020, then became functionally a leveraged Bitcoin-treasury vehicle -- a company-level
structural break, not a shift in market conditions. Nothing about the market changed; MSTR
did.

**Why this matters for Phase 175 specifically.** R-07 (see `175-03-PLAN.md`) chose full
available history for Pass 4's regression, specifically so the 4x252-day sign-stability
windows and the 756-observation floor have room to exist. This is the right call for the
gate's stated purpose (distrust a short track record), but it has a real, undocumented-until-
now cost: a symbol whose business genuinely changed can take years to accumulate enough
sign-stable windows even when its CURRENT sensitivity is completely real, because pre-change
history (when the relationship legitimately did not exist, or pointed a different direction)
dilutes the aggregate statistic and can fail the sign-stability gate outright. The gate is
correctly skeptical of a short record; it just cannot currently tell "short record because
the relationship is new and unproven" apart from "short record because the company's own
identity changed and the old history is genuinely irrelevant now."

**What a fix looks like, sketched (not designed):** changepoint-aware history truncation --
detect a structural break in the instrument's own return-generating process (a formal
changepoint test, e.g. on rolling volatility/correlation structure against a broad-market
proxy, is the natural starting point rather than inventing a bespoke method) and, once
detected, treat data before the break as a different "instrument-era" for materiality
purposes -- not silently discarded, but not diluting a real current relationship either. This
is a narrower, more surgical tool than TAG-02: TAG-02 conditions an ongoing relationship on
recurring regimes; this candidate identifies a ONE-TIME break in a specific instrument's
own history and stops treating pre-break data as informative about the post-break relationship.

**Not urgent, not common:** MSTR-style total business-model pivots are rare in this project's
231-symbol equity-heavy universe (most candidates are ETFs, whose mandates rarely change this
drastically). Worth documenting now because it was found via direct reasoning about why the
sign-stability gate exists, not because a live symbol has hit this failure mode yet -- flag it
for whoever eventually re-calibrates the materiality thresholds against real corpus data (the
`docs/foundation/apr-calibration-backlog.md` follow-up Phase 175's own APR keys are routed to)
to check whether any live symbol's measured loading looks suppressed by this effect before
treating a "fails materiality" result as ground truth.

---

## Recommendation, unchanged from the conversation this doc consolidates

Do #1 first, deliberately, before the others. It's the cheapest of the genuinely new
ideas, it's been surfaced independently twice now (the spec's own known-gaps bullet, and
Fable's review), and #4 is not buildable without it. #2 needs a scheduling decision, not new
design work -- read TAG-02 before treating the interaction-primitive doc's first test as the
only path forward. Hold #3's broad-MI question, #5, and #6 until a concrete candidate
actually needs them, per this project's own "earn promotion through proof" discipline --
don't build general infrastructure speculatively. #6 specifically has no known live trigger
yet (see its own section) -- it's here so the cost of R-07's full-history choice is on
record, not because anything needs building now.

---

## Related docs

- `docs/foundation/instrument-tag-registry.md` -- canonical ITR spec, source of the #1 and #3
  "Known Gaps" bullets this doc expands on.
- `docs/research/tag-calibrator-phase2-regime-conditioning.md` (TAG-02) -- full design for #2.
- `docs/research/stratification-instrument-tag-calibrator.md` -- original Phase 146 design
  doc; source of F5 (discussed under #4) and the factor-series-proxy collinearity note
  (discussed under #5), and the narrow MI scoping (discussed under #3).
- `docs/ideas/signal-sensitivity-regime-interaction-primitives.md` -- the sibling doc this
  survey grew out of; Fable-reviewed 2026-09-18, revision-required, not yet promoted.
- `.planning/todos/pending/380-itr-materiality-filtered-empirical-tags-and-eq-prefix-naming-
  collision.md` and Phase 175 -- the active work this doc's #1 and #5 both connect to
  (materiality filtering needs #5's discipline generalized; the shadow-mode diagnostic Phase
  175 builds would be a natural place to also surface #1's history, once it exists). #6's
  R-07 caveat lives directly in `175-03-PLAN.md`, not just here.
- `docs/foundation/apr-calibration-backlog.md` -- where #6 suggests checking, once Phase
  175's materiality thresholds are re-calibrated against real corpus data, whether any live
  symbol's measured loading looks suppressed by an undetected structural break.
