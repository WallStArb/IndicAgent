# Calendar Primitives

**Status:** Research - Fable-reviewed 2026-07-13
**Author:** Claude (Fable 5), dispatched review, 2026-07-13 - todo 104 (quarterly-seasonality/OPEX
rigor pass) plus extraction and expansion of the "Temporal Coordinate Primitives" section of
`docs/research/signal-renaissance-primitives-ohlcv.md` (that section is now a pointer here).
**Canonical term:** `calendar primitive` (glossary entry pending; see "Canonical Term" below).
The filename keeps "temporal" for discoverability from the superseded section's title; prose
uses `calendar primitive` exclusively.
**Companion idea doc:** `docs/ideas/signal-quarterly-seasonality-opex-risk-off.md` - the
hypothesis whose rigor pass produced this doc. Its five open questions are answered in
"Quarterly Seasonality / OPEX Test Design" below.

---

## Canonical Term

A **calendar primitive** is a tier-0 atomic feature computed as a deterministic, stateless,
O(1) function of the bar timestamp alone: no OHLCV input, no cross-bar state, no external
event data. The live schema already uses `group_name='calendar'` in `feature_registry`, and
"calendar effects" is the standard finance term for this anomaly family, so `calendar
primitive` is canonical. Full definition and the retired-synonym list: `docs/foundation/glossary.md`'s
`calendar primitive` entry.

Two sub-forms:

- **Cyclical coordinate** - a `_sin`/`_cos` pair encoding position on a calendar cycle
  (trading week, month, quarter, year, session, hour). Always shipped as a pair: the pair
  spans every phase of the cycle's first harmonic, so no turning point is assumed.
- **Linear position** - a `[0, 1]` fraction with the `_position` suffix (`month_position`,
  `quarter_position`). Monotone within the cycle, discontinuous at the boundary.

Note the timing: `in_ny_session`, `in_london_kz`, `in_overlap`, `power_hour`, and
`opening_range` are calendar primitives whose window boundaries are APR-backed
(`feature.session.*`); they remain pure functions of (timestamp, config) with no state.

---

## Doctrine: No State, No Theory, No Hand-Holding (revised)

This section supersedes the doctrine text formerly in
`signal-renaissance-primitives-ohlcv.md`. The bans stand; their reasoning is sharpened,
because the old text contained two internal inconsistencies (it banned "quarter progress" and
"days to month-end" while the shipped feature set includes `quarter_position` and
`days_to_month_end`, both pure arithmetic) and one argument that is unsound for this system's
actual architecture (the "let the ensemble discover it" claim, below).

### What stays banned, and the precise reason

| Banned | Real reason | Notes |
|---|---|---|
| Stateful counters ("bars since X") | State is complexity: gap handling, reset logic, recovery paths, single-pass compute broken | Ban is about the *implementation class*, not the quantity. A quantity computable statelessly from the timestamp is not covered by this ban even if it could also be built as a counter. |
| HTF-constant-at-LTF via cross-TF joins | Breaks the DAG: features compute from the bar in front of you | Pure timestamp arithmetic that happens to be constant within a day at 5m is fine (see Storage doctrine below). |
| Event flags at tier 0 (`is_opex_day` and kin) | Point selection is a hypothesis. A binary flag asserts that one point in the cycle matters; a coordinate asserts nothing | Flags are not banned from the system; they are banned from the *atomic* tier. See the `is_opex_day` resolution below. |
| Fitted boundaries (e.g. "reflect around quarter_position = 0.885") | In-sample turning points baked into a feature definition are overfit by construction | The companion idea doc's own anti-pattern section; unchanged. |

### The line: coordinates span cycles, flags select points

The old text banned "quarter progress" as theory-laden, yet its own endorsed table motivated
`week_of_month_sin/cos` explicitly "for 3rd Friday OPEX effects". The consistent principle
underneath both is:

**Theory may motivate WHICH cycle to encode. It must not select points within the cycle at
tier 0.**

Encoding the quarter cycle because quarterly effects plausibly exist is the same move as
encoding day-of-week because weekly effects plausibly exist: the resulting coordinate is
symmetric over the whole cycle and carries no claim about where within it anything happens.
`quarter_position` and `days_to_month_end` are therefore legitimate calendar primitives (both
verified pure arithmetic in `feature_factory.py`; the old ban text was aimed at stateful or
cross-TF implementations that were never built). A binary flag, by contrast, is a delta
function at a chosen point: the choice of point IS the hypothesis, so it belongs where
hypotheses are declared - tier 1.

### Where "let the ensemble discover it" holds, and where it does not

The old text's strongest argument was: "If OPEX causes pin risk, why can't the ensemble
discover that from temporal coordinates + price/volume features?" That argument is
**architecture-dependent**, and for this system as built it fails in two specific places:

1. **Stage 3 combination is linear.** `EnsembleICEngine` produces an IC-weighted linear
   combination of features. Quad-witching Friday is a three-way conjunction: (dow = Friday)
   AND (week_of_month = 3) AND (month mod 3 = 0). No linear functional of the atomic sin/cos
   coordinates expresses a conjunction; that requires a product of indicator regions, which is
   exactly what a nonlinear learner (trees, nets) would form and what this system's linear
   stage cannot.
2. **Per-feature screening is Spearman IC**, a monotone-rank statistic. A pattern that only
   exists at a 4-days-per-year intersection produces essentially zero rank correlation on any
   single coordinate: `dow_sin` is identical on every Friday, expiration or not.

A Renaissance-style nonlinear ensemble genuinely can discover calendar conjunctions from raw
coordinates; the quote is right about that world. This system's sanctioned mechanism for
nonlinearity is the **theory-motivated interaction layer** (Phase 151: at most 50 curated
compounds, each with a stated one-sentence hypothesis, separate BH-FDR pool). Within that
architecture, a hypothesis-bearing conjunction is not a doctrine violation; a declared
hypothesis is the *entrance requirement* of the tier. The doctrine therefore resolves to a
placement rule:

**Tier 0 = coordinates only, theory-free by construction. Tier 1 = conjunctions and flags,
theory mandatory and explicit.** Both halves of the original doctrine survive: the atomic
layer stays clean, and theory enters only where the design forces it to be falsifiable.

### Resolution: `is_opex_day`

- **At tier 0: rejected.** It is a point-selector, not a coordinate. The ROADMAP Phase 151
  entry currently listing it under "Atomic candidates" should be corrected.
- **Statefulness objection: does not apply.** The 3rd Friday is pure calendar arithmetic:
  `(dow == Friday) AND (week_of_month == 3)`, where `week_of_month = (day - 1) // 7 + 1` maps
  days 15-21 to week 3 in every month. No counter, no event table.
- **At tier 1: accepted, reframed as two candidates** (see "Tier-1 Event-Flag Candidates"):
  a monthly `opex_flag` and a quarterly `quad_witching_flag`, registered
  `tier='1_interaction'` with `parent_features` = the calendar atomics they conjoin and the
  dealer-gamma/expiration-mechanics hypothesis in `formula_short`, exactly per Phase 151's
  design rules. "Quad witching" is standard industry vocabulary (glossary naming rule:
  industry-standard terms preferred).

---

## Existing Inventory (22 registered; 21 true calendar primitives)

All rows live in `feature_registry` with `tier='0_atomic'`, `group_name='calendar'`,
`status='active'`. Formulas verified against `src/intelligence/feature_factory.py`
(2026-07-13), not restated from the superseded doc; one formula below corrects the old doc.

| Feature | Formula (live code) | Cycle / note |
|---|---|---|
| `dow_sin`, `dow_cos` | `sin/cos(2π · min(weekday, 4) / 5)` | **Trading week, period 5** - not period 7 as the superseded doc's table claimed; weekends clamp to Friday. Doc/code discrepancy resolved in favor of code. |
| `hour_of_day_sin`, `hour_of_day_cos` | `sin/cos(2π · (hour + minute/60) / 24)` | Intraday clock, period 24h |
| `week_of_month_sin`, `week_of_month_cos` | `week = (day-1)//7 + 1`; `sin/cos(2π · week / 5)` | Week within month, period 5 |
| `day_of_month_sin`, `day_of_month_cos` | `sin/cos(2π · day / 31)` | Calendar day within month, fixed period 31 |
| `week_of_year_sin`, `week_of_year_cos` | ISO week; `sin/cos(2π · week / 52)` | Annual, week resolution |
| `month_sin`, `month_cos` | `sin/cos(2π · month / 12)` | Annual, month resolution |
| `month_position` | `day / days_in_month` | Linear month position, (0, 1] |
| `quarter_position` | `min(1.0, (month_in_quarter · 30 + day) / 91.25)` | Linear quarter position; approximate month lengths, monotone, stateless |
| `days_to_month_end` | `(days_in_month - day) / days_in_month` | **Exactly `1 - month_position`. Redundant; removal recommended below.** |
| `session_time_pos` | `clamp((minutes - session_open) / session_length, 0, 1)` | Continuous NY-session position; boundaries APR-backed |
| `in_ny_session`, `in_london_kz`, `in_overlap` | indicator of APR-configured UTC windows | Session membership |
| `power_hour`, `opening_range` | indicator of APR-configured UTC windows (`feature.session.*`) | Sub-session windows |
| `above_wk_vwap` | price vs weekly VWAP | **Not a calendar primitive.** Price-dependent and stateful (FeatureCache, per `feature_factory.py:21`); grouped `calendar` in the registry for legacy reasons. Recommend regrouping in a follow-up migration; no compute change. |

### Redundancy finding: remove `days_to_month_end`

`_days_to_month_end_fraction = (days_in_month - day) / days_in_month = 1 - _month_position`,
exactly, for every timestamp (both read the same `calendar.monthrange`). An exact affine
complement: Pearson correlation -1, Spearman |IC| identical with flipped sign, perfectly
collinear in any linear stage. This is the same class of mathematical redundancy as the
migration-211 removal of `new_high_flag`/`new_low_flag` (redundant with
`dist_from_high`/`dist_from_low`), and the same remedy applies: drop `days_to_month_end`,
keep `month_position` (the simpler, positively-oriented one). Calendar set 22 to 21;
`FeatureVector` 150 to 149 fields. This also quietly settles the old doctrine's "no days to
month-end" line: the feature should go, though for redundancy, not for the statefulness the
old text imagined.

---

## New Atomic Candidates

Disciplined by design: three sin/cos pairs proposed, seven candidates rejected. Every
proposal is pure timestamp arithmetic, O(1), stateless, parameter-free (no APR keys), bounded
[-1, 1], and must pass partial-IC control against the named nearest neighbors before
promotion (todo 037 methodology).

### Proposed

| Candidate | Formula | Why the existing 22 do not cover it | Redundancy risk and required control |
|---|---|---|---|
| `quarter_cycle_sin`, `quarter_cycle_cos` | `sin/cos(2π · quarter_position)` | First circular harmonic of the quarter. Spearman IC on linear `quarter_position` is blind to any non-monotone within-quarter shape (a mid-quarter dip scores ~0); the sin/cos pair makes a single-harmonic seasonal shape of ANY phase linearly detectable, and wraps the quarter boundary (quarter-end flows into new-quarter, which the linear coordinate breaks). As the 4th harmonic of the annual cycle it is NOT in the linear span of `month_sin/cos` or `week_of_year_sin/cos` (higher harmonics are nonlinear in the fundamental). | Control against `quarter_position` and `month_sin/cos`. This is the primary instrument for the quarterly-seasonality hypothesis below. |
| `tdom_sin`, `tdom_cos` (trading-day-of-month) | `t` = count of weekdays (Mon-Fri) from the 1st through the bar date; `W` = weekday count in the month; `sin/cos(2π · t / W)` | Turn-of-month, the best-documented monthly anomaly (returns concentrate in the last and first few TRADING days), is defined in trading days; `day_of_month_sin/cos` smears the boundary by up to 2 weekend days exactly where the effect concentrates. Weekday counting is closed-form arithmetic; deliberately ignores holidays (a holiday table is nonstationary institutional data, see rejections) at a cost of at most 1 day of jitter ~9 times a year. | High rank-correlation with `day_of_month_sin/cos` away from month boundaries; keep only if partial IC survives controlling for that pair plus `month_position`. Honest expectation: modest incremental IC, concentrated at month turns. |
| `minute_of_hour_sin`, `minute_of_hour_cos` | `sin/cos(2π · minute / 60)` | Sub-hour cycle: round-time execution clustering (TWAP/VWAP schedules, option-hedge rebalancing at :00/:30). A period-1h cycle is a high harmonic of the day, not linear in `hour_of_day_sin/cos`, and `session_time_pos` is linear across the whole session. | Constant at 1h/1d (fine per Storage doctrine; varies at 5m/15m where the corpus has the most rows and this family has the most power). Control against `hour_of_day_sin/cos`. |

`quarter_cycle_sin/cos` **supersedes** the ROADMAP's current "month-of-quarter sin/cos"
candidate: month-of-quarter (period 3 in months) is a step-quantization of the same
quarter-period coordinate at coarser resolution; the continuous version carries strictly more
information at identical cost. It also supersedes the idea doc's "squared distance from
quarter midpoint" option, which fixes the effect's phase at mid-quarter by assumption; the
sin/cos pair spans all phases and assumes no turning point, which is precisely the
anti-pattern boundary the idea doc worried about.

### Rejected

| Rejected candidate | Reason |
|---|---|
| `month_of_quarter_sin/cos` | Superseded by `quarter_cycle_sin/cos` (above): same fundamental period, coarser quantization. |
| `day_of_year_sin/cos` | Same fundamental harmonic as `week_of_year_sin/cos` to within ±3.5 days of phase; redundant for any first-harmonic effect. |
| `days_to_quarter_end` | Affine in `quarter_position`; exactly the `days_to_month_end` mistake again. |
| `week_of_quarter_sin/cos` | Week-quantized `quarter_cycle`; redundant with the continuous version. |
| Presidential/4-year cycle `sin/cos` | Pure arithmetic, but the deepest corpus (1d, 20y) holds 5 independent cycles. Unpowered at any honest effect size; filing it would be data-mining theater. |
| `is_pre_holiday_session` | Technically derivable from timestamp arithmetic (even Good Friday, via the Easter computus), but the holiday set is institution-specific and nonstationary (Juneteenth added 2022): a maintained event table in disguise, violating the "different researcher computes the identical number forever" property. Permissible as ONE tier-1 curated candidate if someone writes the hypothesis; not recommended, and never tier 0. |
| Any FOMC-adjacent feature | FOMC dates are scheduled by the Fed, not derivable from the timestamp. Requires an events feed: alternative-data territory (Phase 155), out of scope for this family. This is the bright line: OPEX is calendar arithmetic; FOMC is not. |
| `quarter_cycle` second harmonic (`sin/cos(4π · quarter_position)`) | Deferred, not rejected. Add only if the first harmonic shows real IC but a shape misfit (dip narrower than a half-cycle). Adding harmonics preemptively is Fourier sprawl, the calendar version of the rejected 30K-candidate factory. |

---

## Tier-1 Event-Flag Candidates (Phase 151 interaction pool)

These enter Phase 151's at-most-50 theory-motivated pool, never the atomic pool. Each is a
conjunction of shipped calendar atomics, registered `tier='1_interaction'` with
`parent_features` and hypothesis text per the phase's design rules.

| Candidate | Definition | Parents | Hypothesis (one sentence, as required) |
|---|---|---|---|
| `opex_flag` | `(dow == Friday) AND (week_of_month == 3)` - monthly options expiration, 12x/year | `dow_sin/cos`, `week_of_month_sin/cos` | Monthly option expiration forces dealer gamma-hedging unwind and pinning flows into and off the expiration date. |
| `quad_witching_flag` | `opex_flag AND (month mod 3 == 0)` - quarterly expiration of index futures, index options, stock options, single-stock futures, 4x/year | `opex_flag`, `month_sin/cos` | Quarterly ("quad-witching") expiration concentrates the same mechanics at 3x monthly open interest, plus index-rebalance flows on the same date. |
| `quarter_position × <atomic>` | per ROADMAP Phase 151 entry (e.g. × `vol_z`, × regime label) | `quarter_position` + partner | Quarter phase modulates the partner signal's predictiveness (window dressing, earnings-season drift). Unchanged from the ROADMAP; runs through todo 037's partial-IC machinery as-is. |

Splitting monthly from quarterly is not cosmetic; it is the test design (next section).

---

## Quarterly Seasonality / OPEX Test Design

Answers to the five open questions in
`docs/ideas/signal-quarterly-seasonality-opex-risk-off.md`.

### Q1 - Primitive design: both routes, precisely scoped

- **Atomic route:** `quarter_cycle_sin/cos` (above). Answers "does unconditional
  within-quarter seasonality exist" with the pair's phase-free first-harmonic basis. Not the
  squared-distance transform (assumes a turning point) and not month-of-quarter (coarser
  quantization of the same coordinate).
- **Interaction route:** `quarter_position × <atomic>` through todo 037's already-validated
  partial-IC pipeline, zero new measurement code. Answers a different question: "does quarter
  phase modulate other signals' predictiveness". Run both; they are complements, not
  alternatives.

### Q2 - OPEX test: separate, and split monthly from quarterly

Test the flags independently of the broad seasonal hypothesis, and split them:

- `opex_flag` (monthly) is the **clean mechanical probe**. It fires every month, so it is
  orthogonal to quarter phase; any effect it shows is expiration mechanics, not quarter-end
  seasonality. It also has 3x the episodes.
- `quad_witching_flag` tests the **amplification** claim (quarterly open interest is much
  larger). Quad-witching alone can never separate hypothesis 2 from hypothesis 1, because it
  always co-occurs with late-quarter; the monthly flag is what breaks that confound.
- Interpretation matrix, pre-registered: quarter_cycle shows the dip but flags show nothing
  means quarter-phase seasonality, not expiration mechanics; monthly flag fires means
  mechanics; only the quarterly flag fires (monthly null) means either amplification-only or
  residual quarter-phase confound, and the quarter_cycle coefficient adjudicates.

### Q3 - Power: the flags are marginal-to-underpowered; the coordinate is not

Episodes are **distinct dates**, not rows: the corpus's ~80 symbols co-move within a date
(the retracted check measured exactly this: 18,694 rows collapsing to 54 episodes, an ~18.6x
t-stat inflation). Intraday TFs add within-episode resolution, not episodes. At the 1d/20y
corpus depth:

- `quad_witching_flag`: ~80 episodes. Detecting at alpha 0.05 / power 0.8 needs an effect of
  roughly `2.8 / sqrt(80) ≈ 0.31` daily SDs, ~35-40 bps/day at ~1.2% daily vol. Documented
  expiration effects are an order of 5-20 bps: **underpowered by roughly 2-5x** for realistic
  effect sizes.
- `opex_flag`: ~240 episodes, needs ~0.18 SD (~20 bps/day). **Marginal** - detectable only if
  the effect is at the top of the documented range.
- `quarter_cycle_sin/cos`: NOT a rare-event flag. Every bar contributes within-quarter
  contrast inside each of ~80 quarter-episodes, so the test is a first-harmonic fit with 80
  clusters and full within-cluster design spread: **substantially better powered** than the
  flags. This is the primary instrument; the flags are secondary.

Consequences, pre-registered: (1) do NOT regime-stratify the flags (9-way stratification of
80 episodes is ~9 per cell, hopeless; pool across regimes); (2) "insufficient evidence, keep
accruing" is an acceptable and expected outcome for `quad_witching_flag`; (3) the
project-native way to keep accruing without alpha-spending is an **e-process**
(143.1-06's anytime-valid e-values pattern): rare calendar events that arrive 4-12x/year are
the ideal client for sequential testing, since evidence accumulates across future episodes
with no repeated-look penalty. Do not re-run fixed-alpha tests annually; that is silent
p-hacking on a timer.

### Q4 - Methodology: split by candidate type

- **Smooth coordinates** (`quarter_cycle`, `tdom`, `minute_of_hour`) and the
  `quarter_position × atomic` interactions: the standard `ic_engine` pipeline plus todo 037's
  partial-IC control, with **one mandatory check first**: the 143.1-01 circular-block
  bootstrap's block length must be at least the feature's cycle period at that TF (a
  quarter-period feature at 1d needs blocks of ~63 trading days or longer). The block length
  was sized for forward-return overlap, not for feature-cycle dependence; if it is shorter
  than the cycle, the CI is anticonservative for exactly the naive-N reason the idea doc
  documents. If lengthening blocks is impractical, aggregate to per-episode (per-quarter)
  means before the CI, which is the same fix SHADOW-REVIEW applies to frames. Decide once;
  the rule then covers any future long-period calendar candidate.
- **Sparse event flags** (`opex_flag`, `quad_witching_flag`): Spearman IC is the wrong
  instrument outright. A 4-5% sparse binary is constant on ~96% of bars; rank IC on it is
  noise-dominated and the eligibility gates would discard it before it was ever fairly
  tested. Use the SHADOW-REVIEW criterion-2 pattern instead: per-episode mean forward return
  on flag days versus **matched control days** (same day-of-week, weeks 2 and 4 of the same
  month, pre-registered), day/episode-clustered BCa bootstrap on the difference, pass iff the
  clustered CI excludes zero. This is a small `scripts/analysis/` or `scripts/ops/` script in
  the existing pattern, not new pipeline infrastructure, and it does not need the IC engine
  to grow episode-clustering support for the general case.
- **Pre-registration is mandatory for both** (E6 lesson, and the retracted check's
  moved-goalposts error): windows, controls, directions, and the interpretation matrix in Q2
  are fixed in this doc before measurement.

### Q5 - Scope

Resolved before this review: inside Phase 151, per todo 104's scope decision of 2026-07-13
(the idea doc's "Phase 150" wording is the stale pre-renumbering name for the same phase).
Nothing here changes that. The one ROADMAP correction this review does require: move
`is_opex_day` out of Phase 151's "Atomic candidates" line and into the interaction-candidate
list as `opex_flag`/`quad_witching_flag` (doctrine resolution above).

---

## Storage and Pre-Optimization: Don't

Ported doctrine, unchanged in substance. At 5m, a month-period feature is constant for ~1,600
bars; a float64 column costs ~1.6 MB/year/symbol, ~130 MB/year across 80 symbols. Storage is
cheap; signal is expensive. Do not pull calendar values from an HTF table at analysis time -
that breaks the DAG (features compute from the bar in front of you) and adds join state for
zero benefit. Redundancy is handled downstream: feature clustering (todo 009) groups
correlated calendar coordinates, IC prunes non-performers, and exact mathematical redundancy
gets removed by migration when found (`days_to_month_end`, this doc; `new_high_flag`,
migration 211).

---

## Recommended Vocabulary Additions

Summarized here; exact insert blocks are delivered with the review. `docs/foundation/glossary.md`
gains a `calendar primitive` entry (canonical term, banned synonyms as above, code surface
`feature_registry` `tier='0_atomic'` + `group_name='calendar'`). `docs/foundation/naming-system.md`
gains a calendar-primitive naming table: `<cycle>_sin`/`<cycle>_cos` pairs, `<cycle>_position`
fractions, `in_<session>` membership indicators, and `<event>_flag` names permitted at tier 1
only. Cycle names state the period in words, never numbers (`quarter_cycle`, not `cycle_63`);
the number-free rule is the same one that governs gradient columns (naming-system section 7).

Known adjacent gap, out of this doc's scope: the glossary's existing `primitive` entry
defines only the tag-system sense (beta/hurst measurements feeding tags), while
`feature_registry` and the primitives docs use "primitive" pervasively in the atomic-feature
sense. That collision predates this review and deserves its own reconciliation pass.

---

## References

- `docs/research/signal-renaissance-primitives-ohlcv.md` - parent doc; its "Temporal
  Coordinate Primitives" section now points here
- `docs/ideas/signal-quarterly-seasonality-opex-risk-off.md` - the hypothesis under review,
  including the retracted worked example of the naive-N trap
- `.planning/todos/pending/104-quarterly-seasonality-opex-fable-review.md` - the review gate
  this doc closes
- `.planning/todos/completed/037-interaction-primitives-pilot-ic-test.md` - partial-IC
  methodology precedent (192/864 cells passed BH-FDR, 2026-07-10)
- `docs/plans/SHADOW-REVIEW.md` criterion 2 - day-clustered BCa bootstrap pattern reused for
  the event-flag tests
- `docs/plans/methodology-change-ledger.md` E6 - the overlapping-observation fix whose logic
  extends to feature-cycle block lengths here
- `src/intelligence/feature_factory.py` - live implementations verified for every formula in
  the inventory table (2026-07-13)
