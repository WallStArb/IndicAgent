# Alpha research architecture: one research DAG, one book, breadth over sleeves

**Author:** Claude (Opus 5.5), 2026-09-25, at Brandon's request ("refine how we are finding
alpha ... design this like Renaissance would").
**Informed by:** AGY adversarial review of draft 1, 2026-09-25 (section 9).
**Parents:** `docs/plans/2026-09-24-edge-proof-program.md` (sequence),
`docs/plans/2026-09-24-evidence-framework.md` (draft 3, evidence records, per-vintage budget).
**Status:** ADOPTED 2026-09-25 (draft 2 plus the owner-decision edits of section 9), together
with evidence framework version 4 (methodology-change-ledger E15). The framework owns the
rules; this doc owns the build.

## 1. Diagnosis

The measurement machinery is sound: point-in-time snapshots, whole-panel shift nulls,
stationary bootstrap, pre-registration, a verdict ledger. The problems are in what gets
measured and how the search is organized. Five of them, in order of cost.

**1.1 The research unit contradicts the project's own principles.** `principles.md` says edge
is discovered, not designed, and that there is one model and one book: many weak signals
compete inside one combined forecast. The last month ran the opposite process: one
hand-designed construction at a time, tested standalone, each issued a PASS/FAIL token. Under
that process a real Renaissance-type signal (IC 0.01 to 0.03, individually insignificant,
useful only in combination) fails by construction. 18 verdicts, zero PASS, is what that
process produces whether or not edge exists.

**1.2 Every portfolio-level test ran where statistical resolution is worst.** The two
walk-forward verdicts with real power machinery (TSMOM, phase 179) ran on 13 daily ETFs, n_eff
about 6.3. Section 2 of the evidence framework shows a Sharpe-1 book there takes 4 years of
data to reach t = 2 and a Sharpe-0.5 book 16. `feature_vectors` holds 233 names at 5m, 15m and
1h back to 2006. How much independent breadth that holds after factor residualization is
unmeasured (section 5, step 0), but it is the only place in the project's data where a weak
combined edge could resolve inside one vintage.

**1.3 Tests are spent on ideas instead of on the book.** Each standalone test drew on the
vintage budget. Under the adopted framework the budget is a screen on book versions (M = 30 on
vintage 1, count restarted by owner decision; error control moved to the forward span,
evidence framework sections 3 and 6). What changes is what the budget buys. A standalone test of a
weak signal has almost no power at p < 0.05 / M. A test of a combined book on a broad panel
pools many weak signals into one statistic, so the same bar is reachable. Signal selection
inside the book is handled by walk-forward ridge fitted on past data only, and admission to
the book uses no vintage data at all (section 3.6).

**1.4 The research code is bespoke per idea.** `scripts/analysis/` holds 71 scripts and about
24k lines. Most rebuild their own snapshot, target, null and decision logic. That has already
cost correctness: the 10x spread constant fixed in one script sat unfixed in another for 11
days (ledger, `range_pct_fast` row). The one reusable evaluator (`sleeve_walk_forward/`) is
shaped around the sleeve: `HarnessConfig` hardcodes 13 symbols and 1d, and `SignalSource`
receives only closes, so it cannot express a volume, intraday or feature-based signal.

**1.5 Guards that should be code are review discipline.** Lookahead and null memory are
checked by people reading code. The phase 179 shift-null memory (758 sessions) was derived by
hand, and a leaking wrapped shift was found late (todo 424).

## 2. Design principles for the research layer

- **The unit of research is a signal's contribution to one book,** not a standalone verdict.
  Standalone evaluation is a diagnostic.
- **Breadth before horizon, horizon before cleverness.** Independent bets per year is the
  lever (IR is about IC times the square root of breadth). Measure breadth, then test where it
  is largest.
- **Every guard is a function that fails loudly,** not a checklist item.
- **Research is pure compute over an immutable snapshot.** One node reads the database,
  read-only. Nothing in the research DAG writes production tables. One node writes the ledger.
- **Declarative candidates.** A new idea is a pure function plus a machine-readable spec. It
  adds no new statistics, snapshot, or decision code.

## 3. The research DAG

```
S0  snapshot      (universe, tf, span) -> Panel            read-only DB, content-hashed    [generalize]
S1  target        Panel -> executable fwd return, factor-residualized, causal             [new, reuses factor_math]
S2  signal        Panel -> alpha[t, i]      pure function, declared memory                 [generalize signals.py]
S3  guards        causality probe on S1/S2/S4, memory check, integrity                    [new]
S4  residualize   alpha vs factors (combiner input); vs book signals (diagnostic only)    [new]
S5  measure       evaluate(): arms, session-aligned shift null, bootstrap -> record        [exists, generalize]
S6  ledger        sole writer: concept_registry(domain='construction'), vintage budget     [evidence framework step 2]
S7  combine       walk-forward ridge over every registered signal of admitted families     [new, reuses portfolio]
S8  book test     S5 with S7 as construction: joint shift of signal stack, refit per shift [new, same S5 code]
S9  freeze, forward shadow, confirmation on the pre-dated test day                         [evidence framework 7]
```

One direction, no cycles. S0 is the only node with I/O besides S6. S1 to S5 and S7 are
compute-only and run in `ProcessPoolExecutor` workers under the existing rule (workers return
arrays, never write).

### 3.1 Where it lives

Promote `scripts/analysis/sleeve_walk_forward/` to `src/intelligence/research/` (Ring 1).
Statistics primitives stay in `src/intelligence/statistics/` (`panel_null`, `ic_math`,
`factor_math`), imported, never copied. The promotion is a move plus generalization, verified
by re-running TSMOM and phase 179 from their snapshots and matching the recorded numbers
exactly; their frozen commits stay the reference. New one-off scripts under
`scripts/analysis/` that re-implement S0, S1, S3 or S5 stop.

### 3.2 S0 and S1: panel and target

`Panel` generalizes `Snapshot`: open, close, volume, selected `feature_vectors` columns, and
causal factor exposures, as `[t, i]` arrays for any `(universe, tf, span)`, plus a session
index and a time-of-day index for intraday tfs. Prices come from `market_data_ohlcv_tradeable`;
a missing bar is NaN, never filled. The universe is a pinned query stored in the manifest
with its survivorship status stated. `end_exclusive` stays capped at
`alpha.validation.oos_start`, checked before any fetch.

S1 defines one target for every candidate: the executable open-to-open forward return
(Invariant 1), entering at the open of the bar after the signal bar, residualized against
market and sector or asset-class factors, plus k principal components estimated on a trailing
window, all with loadings estimated on data before t; k and the window are fixed in the
vintage's S1 spec, not per candidate (step 0 found 51 to 66 bets after market and sector
removal, 95 to 120 after 10 in-sample PCs). A
candidate that predicts the raw return mostly predicts beta (`range_pct_fast`,
`alpha_score_residual`); that is enforced once here instead of relearned per construction.
Entering at the next open also skips the close-to-open bid-ask bounce that a close-based
reversal statistic would otherwise harvest (section 4).

### 3.3 S2 and S3: signals with mechanical guards

A signal is `compute(panel) -> alpha[t, i]` plus a spec (3.4) that declares its memory
analytically: the lookback for finite windows, and for recursive filters (EMA, Wilder RSI,
GARCH) the lag at which the impulse response falls below 1e-4 of its peak. S3 runs before S5
sees anything:

- **Causality probe on S1, S2 and S4.** For every date in a deterministic set (month ends,
  session boundaries, holiday-shortened sessions, each name's first and last valid bar) plus a
  random sample, recompute on the panel truncated at t and assert the outputs at t are
  bit-identical. For S1 the assertion is the mirror image: the target at t must change when
  prices after t change and must not depend on the signal bar's own close. The probe covers
  reads inside the pipeline; it does not prove the economic interface is right, which is why
  S1's entry convention is fixed in one place and not per candidate.
- **Memory check.** At a sample of dates, perturb inputs by several standard deviations and
  record the furthest row where alpha moves by more than a tolerance. The run fails if that
  exceeds the declared memory. Perturbation is a check against the declaration, not a
  replacement for it: a threshold signal can hide memory from a small perturbation, and a
  recursive filter never reaches exactly zero.
- **Integrity.** Coverage per date and per name (reported, and a pre-declared minimum per
  cross-section), no input from synthetic or zero-volume bars, NaN in gives no position out.

A failed guard records the failure in the ledger and produces no evidence.

### 3.4 The candidate spec is the pre-registration

Each candidate is a small frozen dataclass or YAML file: signal function, direction, declared
memory, universe, tf, horizon, family, and the prior source (paper or mechanism). The runner
hashes the spec and refuses to run on real data unless the spec is committed and no result
exists for that hash. The result records the spec hash, snapshot hash and code commit. "No
real-data number before the pre-registration commit" becomes a property of the runner, and
constants such as cost figures live in one reviewed place.

Prose pre-registration stays for what a spec cannot say: rationale and disclosed in-sample
hints.

### 3.5 S5: one evaluator, two readouts

`evaluate()` stays the single statistics path, generalized on three points:

- **Any `(universe, tf)`.** The sleeve list and 1d constants become Panel properties.
- **Session-aligned null for intraday.** `shift_panel` rolls rows; on an intraday panel a
  shift that is not a whole number of sessions puts the open's volatility and the overnight
  gap on midday bars, which tests "returns have no intraday seasonality", not "the signal has
  no timing". Intraday shifts are whole sessions only, so every bar keeps its time of day, and
  `memory` is rounded up to whole sessions. Daily panels are unchanged.
- **A cross-sectional readout** beside the portfolio excess Sharpe: the rank-IC time series of
  factor-residualized alpha against the residualized target, with the same null and bootstrap.

The output is the evidence framework's record (estimate, standard error, permutation p,
per-period estimates, provenance). No tokens.

### 3.6 S7 and S8: the book is what gets tested

This is the main change to the evidence framework.

- **Families are admitted on prior alone.** A family is a pre-declared group of signals with a
  shared, published or mechanistic rationale (section 4). Admission reads no vintage data:
  the spec, the prior source and clean S3 guards are the whole gate. A data-driven screen
  would spend vintage data to choose what enters the book, and ridge fitted afterwards cannot
  remove that selection.
- **Every registered signal of an admitted family enters the combiner,** including the ones
  that later look weak. Members are fixed before any real-data number.
- **Ridge on factor-residualized signals, not on signals orthogonalized against each other.**
  Sequential orthogonalization shrinks later signals' variance, and a uniform ridge penalty
  then weights them by registration order. Signals are standardized inside each walk-forward
  fold and ridge handles their collinearity. Residualizing a candidate against the book
  (evidence framework section 5) stays as a diagnostic readout of what it adds.
- **The book null refits.** S8 shifts the stacked signal panel `[t, i, k]` jointly by one
  whole-session shift, reruns S7 on the shifted stack and scores it, the pattern S5 already uses
  for phase 179's calibration. Shifting the combined alpha after fitting would leave the fit's
  own capacity out of the null. Ridge is closed form, so refits per shift are cheap.
- **Budget.** Each book version tested on the vintage is one screen test at 0.05 / M, M = 30,
  bar p < 0.00167, with a null of at least 600 admissible shifts and synthetic power of at least
  50% checked before the run. The gain is power, not a looser bar: a book over hundreds of names
  pools many weak signals into one statistic. The book that clears the screen is frozen and
  confirmed on the forward span (evidence framework section 7).
- **Standalone and residual records** are still written for every signal, for diagnosis and
  for "have we tried this"; they gate nothing.

## 4. Where to search first

Ordered by prior, cleanliness of the evidence available, and power:

1. **Intraday return periodicity and momentum, cross-sectional.** Heston, Korajczyk and
   Sadka (2010): a name's return in a half-hour slot predicts its return in the same slot on
   following days, relative to other names. Plus a residual first-half-hour to last-half-hour
   variant. The market-level form (Gao, Han, Li and Zhou 2018, SPY) is one time-series bet that
   market residualization removes by construction, so it is not a member. No hint has been seen
   on this data. Needs 15m bars, the session-aligned null, and S1's session-close exit for the
   last slot: exit at the final bar's close (a market-on-close order), NaN when the name has no
   final-slot bar. Breadth is priced at the 1d figure (one bet per name per slot-day).
2. **Overnight versus intraday return decomposition** (the two legs carry different, partly
   opposite premia; Lou, Polk and Skouras 2019). Also unseen; needs only opens and closes.
3. **ETF-to-constituent and cross-asset lead-lag** at 5m to 1h. The universe mixes sector ETFs
   with their large constituents, the setup this family needs.
4. **Short-term reversal** (todo 423). The best-documented prior, but the 2026-09-13 screen
   already looked at a reversal-like statistic on 231 of these names over the whole in-sample
   window, so the in-sample panel is not clean evidence for it. Its daily form runs on symbols
   added since that screen or on phase 180 onboarding, never on the holdout: the forward span is
   reserved for one confirmation of a frozen book, and a standalone look spends it. An intraday
   reversal family on the in-sample panel is admissible only as a disclosed re-specification
   on seen data, counted like any other test, and its members pre-declare a one-bar skip
   variant so bounce and genuine reversal separate.

Each is a family of 3 to 8 pre-declared variants. Families from the existing feature corpus
(SMC structure, volatility state) can be admitted the same way on prior, with the corpus IC
table recorded as prior context and disclosed, not used as the gate.

Costs: discovery stays gross (standing directive), and every S5 and S8 record reports
turnover and the cost band as diagnostics. Bid-ask bounce is a different thing: it is a
measurement artifact, not a cost, and S1's next-open entry plus the one-bar skip variants are
how it is controlled.

## 5. Build order, shortest path to the next verdict

0. **Measure residual breadth.** Done 2026-09-25 (`724e4af29`,
   `docs/research/measurement-residual-breadth.md`). After market and sector removal the
   233-name panel carries 51 to 66 independent bets per daily cross-section (63 to 83 at 1h,
   partly the Epps effect), stable across 2007-2012, 2013-2018 and 2019-2025; the sleeve carries
   8.4. The premise holds. Two consequences: (a) a family's breadth is set by its bets per
   name per period, not the bar size it reads, so intraday momentum (one bet per name per day)
   is priced at the 1d figure; (b) the top-10-PC tail (95 to 120) shows shared variance beyond
   market and sector, so S1's factor set adds statistical factors (section 3.2).
1. **Generalize S0/S2/S5** (Panel over `(universe, tf)`, session-aligned null, sleeve
   constants removed). Verify by reproducing TSMOM and phase 179 bit-identically. First
   consumer: the intraday momentum family.
2. **S3 guards** (causality probe on S1/S2/S4, memory check). Run on the momentum family
   before its real-data run; backfill against TSMOM and 179 as a check on the hand-derived 758.
3. **S1 residual target**, shared by every candidate from here on.
4. **Spec-as-pre-registration runner** with the commit and hash check.
5. **S6 ledger writer** (evidence framework step 2, unchanged).
6. **S7 combiner and S8 book test** once two families are registered.
7. Families 2 to 4 of section 4 in parallel with 5 and 6 (alpha-first rule: no verdict waits
   on infrastructure that is not on its path).

## 6. What changes in the parent plans, if accepted

- Evidence framework: done, version 4 (book-version screen at M = 30 with the count restarted,
  admission by prior only, confirmation on the forward span dated by power, capital sized net
  after confirmation).
- Edge-proof program: phase 181's queue becomes families on the 233-name panel in section 4's
  order. Phase 180 (sleeve breadth expansion) drops in priority, pending the step 0 breadth
  measurement. Phase 177 is not on this path for in-sample work: the vintage ends 2025-12-24
  and recent staleness does not touch it. It is on the path for the holdout read, the forward
  shadow run, and survivorship (todo 376).
- `scripts/analysis/`: frozen for new S0/S1/S3/S5 logic. Existing scripts stay as the record of
  their verdicts.

## 7. What this deliberately does not do

- **No async in the compute path.** The research DAG is CPU-bound numpy over memory-mapped
  arrays; async buys nothing there and would complicate the worker model. Async stays where
  the waiting is: S0's concurrent asyncpg fetches and the production daemons.
- **No new service or table** beyond the ledger writer the evidence framework already
  specifies. The research layer is a library plus a runner, not a daemon.
- **No re-scoring of frozen verdicts.** Every ledger row stands.

## 8. Risks

- **Book versions become the new forking path.** Mitigated by declaring the number of versions
  with M and recording every version tested.
- **Thin cross-sections.** Intraday bars for less liquid names have gaps. S3's coverage floor
  applies per cross-section; a date below it gives no position, and coverage is reported with
  every record.
- **Survivorship on a present-day universe.** Short-horizon residual signals are less exposed
  than drift signals, not immune; reversal on losers is the most exposed. Stated in every
  manifest until todo 376 lands.
- **Breadth may be smaller than hoped.** If step 0 finds residual n_eff near the sleeve's, the
  breadth argument fails and this plan's priority order has to be revisited before families
  run, not after.

## 9. Review record

Owner decisions and council edits, 2026-09-25, on adoption. The owner set M = 30 on vintage 1
with the count restarted; this reverses draft 2's "M includes the 18", and it is sound only
because the evidence framework now puts error control on the forward span, not the screen
(framework section 3). Added: the book null refits the combiner per shift. Changed: daily
reversal no longer runs on the holdout, which is reserved for confirmation.

AGY, 2026-09-25, on draft 1. Adopted: family admission by a data screen launders selection
into the book, and the 18 prior tests must stay in M (now: admission on prior only, M includes
the 18); measured memory by perturbation fails on threshold and recursive signals (now:
declared memory, perturbation checks it); a bar-level circular shift destroys intraday
structure (now: whole-session shifts); the causality probe covered only S2 and random dates
(now: S1, S2, S4, deterministic boundary dates); ridge after sequential orthogonalization
weights by registration order (now: factor-residualized signals into ridge, book
residualization diagnostic only); the 09-13 screen leaves no clean in-sample evidence for
reversal on these names (now: reversal moved to fourth, daily form on the holdout per todo
423). Partly adopted: bid-ask bounce is a real bias at short horizons, controlled by
next-open entry and one-bar skip variants rather than a cost gate, which the standing
directive rules out for discovery. Not adopted: holding in-sample family work until phase
177 exits. Its concerns are data after the vintage (freshness) and survivorship; the first
does not touch in-sample data, the second is stated per manifest. The review's "82% synthetic"
figure is the raw table; research reads the tradeable view.
