# Pre-registration: family 2, overnight versus intraday return decomposition

**Author:** Claude (Opus 5.5), 2026-09-25, family 2 of
`docs/plans/2026-09-25-alpha-research-architecture.md` section 4.
**Governing rules:** `docs/plans/2026-09-24-evidence-framework.md` version 4 (E15) with the E16
decision statistic (`docs/plans/methodology-change-ledger.md` E16).
**Status:** REGISTERED 2026-09-25 after two adversarial review rounds (section 8). No real-data
number for any member exists. The first real-data run waits for build requirements B1 to B3
(section 9); the runner's machine spec must reproduce every value pinned here, and a mismatch is
a methodology change.

## 1. Hypothesis and mechanism

Lou, Polk and Skouras (2019, Journal of Financial Economics, "A tug of war: overnight versus
intraday expected returns"): a stock's return splits into an overnight leg (close to open) and an
intraday leg (open to close) that carry different, partly opposite premia, because different
clienteles dominate each (individuals and their orders at the open, institutions through the
day). Each leg's cross-sectional premium persists, and the legs pull against each other: names
with high recent overnight returns earn lower intraday returns.

Berkman, Koch, Tuttle and Zhang (2012, Journal of Financial and Quantitative Analysis, "Paying
attention: overnight returns and the hidden cost of buying at the open") give the same-day form:
attention-driven buying lifts the open, and the stock gives some of it back during the day.
The data-edge thesis's retail-immediacy claim (`docs/research/data-edge-source-thesis.md`) is
the liquidity-provider view of the same reversal.

The test is on residual returns relative to other names, so a market-wide overnight drift is
removed by S1 and is not a member. The mechanism is a US clientele story, so the members'
universe is US-session equities (section 2).

**Scope.** This family tests the intraday-target half of the tug of war. Overnight persistence
(the paper's strongest result) needs a target that enters at the close and exits at the next
open, which the runner does not have; it is a later family version, not tested here and not
failed here.

## 2. Data

- **Source panel:** family 1's (`research/specs/family1_intraday_periodicity.yaml`): 15m bars
  from `market_data_ohlcv_tradeable`, compute_eligible universe, 26 bars per session, start
  2006-01-01, end-exclusive at `alpha.validation.oos_start` (2025-12-24). The same S0 snapshot
  (`panel_81fa9178ca4ad603`) is reused if its content hash still verifies. Opens and closes are
  the first and last trades inside 15m bars, not auction prints.
- **Members' universe (B3):** the S0 snapshot's symbols, intersected with names whose current
  `indicagent_v1` level-1 node is `EQ`, minus names carrying a current (`valid_to IS NULL`)
  `intl_developed` or `intl_em` exposure tag in `instrument_tags` (13 country ETFs, whose
  overnight leg is their home market's session). 187 names on 2026-09-25. The rule keeps the
  asset class the clientele mechanism is about (equity, where individuals and institutions trade
  the same shares at different times of day) and drops fixed income, currencies, commodities,
  crypto, volatility and the alternatives fund, where it is not, and where bond funds' monthly
  ex-dividend gaps would dominate the gap members. Equities whose overnight moves are driven by
  a 24-hour market stay in and are disclosed (section 7). The filter is present-day reference
  data applied to a historical panel; an equity's asset class and home market do not change over
  the span.
- **Session-legs panel (B1):** each session becomes three rows, built from the source panel:

  | Row | open | close | bar return (`panel.bar_returns`) |
  |---|---|---|---|
  | 0, overnight | previous session's final close | bar 0's open | overnight, `ln(open0 / final close of d-1)` |
  | 1, first 15 minutes | bar 0's open | bar 0's close | `ln(close0 / open0)` |
  | 2, rest of session | bar 1's open | final close | `ln(final close / close0)` |

  The final bar is the one `panel.forward_returns`' close exit uses: the session's last row
  with any close, so half days end early. A name with no close on that bar has NaN final close,
  never an earlier one. Any missing input price makes that row's prices NaN. Rows 1 and 2 need
  only bar 0, bar 1 and the final bar, so a name missing a mid-session bar keeps its legs.
  Volume: row 0 takes bar 0's, row 1 bar 0's, row 2 the sum of bars 1 through the final bar.
  Weekend and holiday overnights (up to about 65 hours) are row 0s like any other.
- **Residual returns, per leg:** S1 vintage 1 as merged at run time, run separately on each leg
  as its own one-row-per-session series (`residual_returns(leg, bars_per_session=1)`), so the
  overnight, first-15-minute and rest-of-session legs each get their own market, group and
  principal-component loadings. Pooling the group and PC loadings across unlike legs would leave
  a recurring per-leg exposure gap that could produce O3's effect mechanically (the R3 argument,
  applied to every factor). Each leg's loadings are refit every 21 sessions on a trailing
  window that ends at the refit session, so a residual uses only that leg's data through its own
  session; the residuals are placed back on rows 0, 1 and 2. A session's residual overnight
  return is its row 0 residual; its residual intraday return is the sum of rows 1 and 2 (NaN if
  either is missing).
- **Scored span:** 2010-01-04 through 2025-12-23. Reported sub-periods: 2010-2014, 2015-2019,
  2020-2025-12-23 (reported, not voted on).

## 3. Members

Every member places its alpha for session d on row 1 of session d, formed at bar 0's close
(09:45) from data through it. One signal row for every member is what lets them share a book:
the S7 combiner uses complete cases only.

| Member | statistic for session d | Window (sessions) | Sign |
|---|---|---|---|
| O1 `intraday_persistence_20` | mean residual intraday return over d-20 .. d-1 | 20 | +1 |
| O2 `intraday_persistence_60` | mean over d-60 .. d-1 | 60 | +1 |
| O3 `overnight_to_intraday_20` | mean residual overnight return over d-20 .. d-1 | 20 | -1 |
| O4 `overnight_to_intraday_60` | mean over d-60 .. d-1 | 60 | -1 |
| O5 `gap_fade` | residual overnight return of session d (row 0 of d) | 0 | -1 |
| O6 `gap_fade_z` | O5 over the name's sd of residual overnight returns, d-60 .. d-1 | 60 | -1 |

- Alpha = sign x statistic, then the centred rank `rank / (n_valid - 1) - 0.5` per row with a
  coverage floor of 20 names (family 1's), so the book's construction direction is +1.
- Means and the sd need at least half the window's sessions finite; otherwise NaN. The alpha row
  must itself have a finite residual (a name with no bar 0 has no position).
- O6 is the ledger's gap-size-conditioned variant in a form the complete-case combiner can use:
  scaling by the name's own gap history makes large gaps extreme in rank without making the
  member NaN on small-gap names.
- **Declared memory in rows:** (slot history + 252 + 21 sessions) x 3, family 1's formula
  (`families.common.declared_memory_rows`) at 3 bars per session. Slot history is the window
  for O1 and O2 (their oldest input, row 1 of d - w, is exactly 3w rows back) and window + 1 for
  every member that reads a row 0 (O3, O4, O6: 21, 61, 61; O5: 1), because row 0 of session d - w
  is 3w + 1 rows before the alpha row.
- **Why 20 and 60 sessions and not the paper's month-level and longer formation windows:** E16's
  static tilt is an expanding mean over all prior scored sessions, so a 12-month member is
  testable in principle, but its timing variation has only about 16 independent 12-month
  observations over the scored span, and its permanent per-name component is removed by the
  tilt. It would spend a book's power on the least testable part of the effect. The long windows
  are not tested here and are not failed here.
- **Not members:** (a) the first 15 minutes' residual return (row 1): the strongly negative
  intraday `gap_z` corpus IC (construction-verdict-ledger section 5) most likely measures that
  microstructure, a separate idea seen on this data; its correlation with O5 is reported
  (section 5). (b) A low-liquidity-half gap fade: a member that is NaN on the liquid half would,
  under complete cases, shrink the whole book to that half. The liquidity claim is a diagnostic
  instead.

## 4. Target and construction

- **Target:** `ln(final close / bar 1's open)` of session d, the forward return at row 1 with
  horizon 1 and the session-close exit (`panel.forward_returns(open, 1, session, closes=close)`
  on the legs panel): enter at row 2's open (09:45), exit at the session's final close. It is
  residualized by S1 as its own one-row-per-session series, with loadings from sessions strictly
  before d (lag one session), and placed on row 1; rows 0 and 2 carry no target. So no target
  crosses the overnight gap, none enters another leg's fit, and none shares a price with O5's
  input.
- **Construction (R1, as built):** `rank_vol_neutral`, weights proportional to centred rank over
  each name's trailing volatility of legs-panel residual returns (20 sessions, all three rows,
  half finite), positive side scaled to +0.5 and negative to -0.5. One position per name per
  session. The volatility pools all three legs while the target is the rest-of-session leg; the
  scale is per name, so this changes relative weights only through names whose overnight share
  of variance is unusual.
- **Scoring (R2):** session scoring, one P&L per session, annualized with 252.
- **Costs:** gross (standing directive). Turnover and the 1 and 5 bps per side cost band are
  reported. The book rebalances once per session, against family 1's 13 times.

## 5. Evidence and the test

- **Evidence records** (diagnostic, gate nothing): each member standalone with R1 and R2 through
  `evaluate()`: the E16 HAC timing t, the shift-null diagnostics, per-period estimates, turnover
  and each member's measured autocorrelation time.
- **Diagnostics, reported, decide nothing:**
  - Liquidity split for O5 and O6: each member's session P&L decomposed (not re-constructed) into
    the names above and below the cross-sectional median of trailing 60-session mean daily dollar
    volume (sum over the session's 15m source bars of close x volume), the median taken per
    session.
  - O3 against a per-leg group control: O3's evidence repeated with each name's overnight and
    intraday residuals replaced by their own-group means, so what O3 carries from group-level leg
    exposure is visible.
    The data-edge thesis predicts the fade concentrates in the less liquid half.
  - Correlation of O5's alpha with the row 1 residual (first 15 minutes), per session, averaged.
- **Book version (screen test, one of M = 30 on vintage 1):** all six members combined by the S7
  walk-forward ridge with book_v1's settings (252-session window, 21-session refit, penalty 1.0),
  tested by E16 at one-sided p < 0.00167. No member is dropped after seeing its record. The ridge
  can flip a member's declared sign between windows when the member's true IC is below its
  per-window noise (about 1 / sqrt(252 x 60) = 0.008 per window); the combiner is the adopted
  S7, and the power check prices that loss rather than a constrained combiner being chosen here.
- **Refusal before any real-data number:** S3 guards on every member (integrity, causality probe,
  memory check) and on the legs-panel transform; synthetic power (B2) of at least 50% at a planted
  per-session rank IC of 0.007. At step 0's full-universe breadth of about 60 independent bets
  per session, 0.007 implies an annualized IR near 0.9 (0.007 x sqrt(252 x 60)), the same economic
  size family 1's 0.002 per slot implied across 13 slots. The 187-name universe's breadth is
  measured in B2 and used in the power check; the planted IC stays 0.007 whatever it is. A refused book produces no
  real-data number and is recorded as underpowered.
- **If the book clears the screen,** it is frozen and its confirmation date on the forward span
  is fixed at freeze by the power rule.

## 6. Disclosed prior looks at this data

- **Gap features, 2026-09-25** (construction-verdict-ledger section 5): pooled raw IC of
  `opening_gap_pct` is about 0 at 1d and slightly positive intraday (+0.004 to +0.006,
  continuation; magnitude-conditional +0.008 to +0.011); `overnight_gap_z` and `gap_filled` are
  about 0 everywhere. Raw, not residualized, other targets, full universe; but they bear on O5 and
  O6, whose fade direction was declared in the ledger before that look and is kept. The
  magnitude-conditional continuation bears on O6 in particular, the ledger's size-conditioned
  variant, which is kept in the scaled form above rather than dropped. O5 and O6 are disclosed
  re-specifications on seen data, and on that look the prior for fade is weak.
- **Short-term reversal screen, 2026-09-13** (ledger section 5, corrected 2026-09-24): a 14-period
  RSI against a 2-session forward return on 231 names, mean IC about -0.026 in every split, a
  reversal hint. O1 and O2 average the intraday leg over 20 and 60 sessions with sign +1, and
  the intraday leg is most of a name's total return, so that result bears against O1's sign.
  The members keep the paper's sign: under the tug of war, total-return reversal is consistent
  with intraday persistence plus an opposing overnight leg, which is what O1 to O4 separate.
- **Step 0 breadth and the S1 cluster rule** looked at residual correlation structure only.
- **Family 1's evidence records** (same source panel): same-slot continuation within the session
  is strong (HAC t 13 to 18). O1 and O2 sum all of a past session's intraday slots, so a name's
  same-slot periodicity feeds its intraday mean, so overlap with family 1 is expected. Excess
  over family 1 is not what is tested here; a book combining both would need one panel carrying
  both families' signal rows, which `run_book` does not support today.

## 7. Known risks, stated before the run

- **Dividends (todo 428):** prices are not total-return. An equity's quarterly ex-dividend session
  opens lower by the dividend, which O5 and O6 read as a negative gap and fade (go long). The
  documented ex-day behaviour (price drops by less than the dividend, some intraday recovery)
  could then show up as fade P&L that is a dividend effect, not the clientele mechanism: a
  possible false positive, not only noise. The EQ universe removes the monthly payers (bond
  funds); the remaining exposure is quarterly. No dividend calendar exists to exclude ex-dates;
  the risk is bounded only after todo 428.
- **24-hour drivers inside the equity universe:** three ADRs with a home-market listing (TSM,
  ASML, BHP) whose home session falls inside the US overnight; crypto proxies (COIN, MARA, MSTR,
  RIOT) tied to a market that trades around the clock; and commodity-linked equities (GDX, NEM,
  FCX, CCJ, URA, OIH, XOP and others) whose driver trades overnight. Their overnight leg partly
  measures that market rather than a clientele. They stay in: the rule is asset class, and
  hand-picking names by driver would be a judgment made on seen names. About 14 of 187.
- **Opening prints:** bar 0's open is the first trade in 09:30 to 09:45, which for thin names can
  be late or stale. It enters O3 to O6 only as an input; the executable entry is bar 1's open.
- **Entry at 09:45** skips the first 15 minutes, where part of an opening reversal may happen; the
  test measures what remains after an executable entry.
- **Survivorship (todo 376):** present-day universe, as family 1.
- **Weekend overnights** share the weekday overnight loadings and residual scale; a Monday gap
  covers about 65 hours.
- **Near-duplicate names** count one bet twice; p-values stay valid, breadth is overstated.
- **Slow members and E16 power:** book_v1 (family 1) was refused at 0/51 power, with a suspicion
  under study that the per-(slot, symbol) demean absorbs a persistent plant. O2, O4 and O6 have
  60-session memory. If this book is refused too, the refusal is recorded and the question goes to
  that study, not to a re-specified member.

## 8. Review record

**Round 1** (independent fresh-context Claude review, 2026-09-25; AGY and Codex out of quota).
Adopted: (H1) the power check could not run, the synthetic generator being family 1's HKS plant
with no overnight leg; now B2 with a pinned plant. (H2) the clientele mechanism does not fit bond,
currency, commodity, crypto and foreign-country funds, and bond funds' monthly ex-dividend gaps
would dominate the gap members; now the EQ-minus-international universe (B3), and the dividend
risk restated as a possible false positive. (H3) the reversal-screen disclosure misstated what it
measured, and the size-conditioned gap variant was not accounted for; both corrected. (M1) the
argument for dropping 12-month windows misread E16's tilt (expanding, not trailing); rewritten on
power grounds. (M2) the second-input build was ambiguous; replaced by the session-legs panel, so
members keep one input and the existing guards probe the overnight leg as a bar return. (M3, M4)
requiring all 26 bars dropped thin names and pooled nested close-exit targets; the legs panel
needs three bars and gives one target per session. (L1) the loadings wording; (L2) Berkman et al.
cited, O5's correlation with the first 15 minutes reported; (L3) not auction prints; (L4) the
liquidity diagnostic pinned; (L5) scope stated. Not adopted: (M5) a sign-constrained or
equal-weight combiner; S7 is the adopted combiner and the power check prices its cost.

**Round 2** (independent fresh-context Claude review of revision 2, 2026-09-25). Verified: the
legs' bar returns, the row 1 target, no leak through leave-one-out factors or loadings windows,
and the 187-name universe count. Adopted: (HIGH) members reading a row 0 reach 3w + 1 rows, one
past the declared memory, which would fail the S3 memory check and spend the spec; slot history
is now window + 1 for them. (MEDIUM) S1 pooled group and PC loadings across unlike legs, and the
target's S1 fit included gap-crossing rows; now S1 runs per leg and on the target as separate
session series. (MEDIUM) B2 could not reuse `synthetic.py` and left scale and standardization
open; now pinned. (MEDIUM) legs-panel volume undefined; pinned. (MEDIUM) the universe rationale
conflicted with keeping 24-hour-driven equities, and BNTX is not a home-listed ADR; rationale
restated on asset class and those names disclosed. (LOW) transform causality probe mapping,
pooled volatility, stale breadth figure, the unrunnable combined book, weekend overnights and a
spec field for the transform; all addressed.

## 9. Build requirements before the first real-data run

- **B1, session-legs panel and per-leg S1:** a pure transform from the 15m S0 panel to the
  three-row panel of section 2 (`bars_per_session = 3`), recorded in the run's provenance with the
  source snapshot's hash, selected by a new optional `PanelSpec` field that family 1's spec does
  not set (its spec text and hash are unchanged). S1 runs per leg and on the target as session
  series (section 2 and 4), placed back on the legs rows. Rows 1 and 2 take bar 0's and bar 1's slot starts; row 0 takes bar 0's slot start minus one
  minute, so timestamps stay strictly increasing and row 0 marks the pre-open. Family 1's code
  paths, spec hashes and `repro_frozen.py` stay bit-identical. S3's causality probe and memory
  check run on the transform and on per-leg S1, with at least one probe row forced onto a row 1
  (the signal row) and one onto a row 0. The transform's probe maps each legs row to the latest
  15m source bar it reads (row 0 of d reads d-1's final bar and d's bar 0; row 2 reads through
  the final bar) and perturbs only source bars after it.
- **B2, family 2 plant for the power check:** its own generator (family 1's `synthetic.py` is
  built on two-bar slots and does not apply). Synthetic residuals per leg with the breadth
  structure of `synthetic.py` (covariance I + s Q Q' per leg), each leg and name scaled by the
  measured residual sd of that leg and name on the real legs panel, so the overnight, first-15-
  minute and rest legs keep their real relative sizes. The participation ratio is measured by
  step 0's method on the per-session residual target cross-section of this universe before the
  check (no signal involved). The plant adds `c x z[d, i]` to row 2's residual of session d. z is
  the per-session cross-sectional z-score of the equal-weight sum of three per-session
  cross-sectional z-scores built from the synthetic residuals themselves: O1's statistic (mean
  intraday residual, d-20 .. d-1), minus O3's (mean overnight residual, d-20 .. d-1), minus O5's
  (overnight residual of d); a component that is NaN for a name counts as 0. The plant is
  recursive through O1, as family 1's HKS plant is. c is calibrated so the best linear
  combination of the six members has a per-session rank IC of 0.007 against the target, then the
  book runs through `book_timing` at the bar, R = 100, exact curtailment allowed.
- **B3, members' universe filter:** the section 2 rule, evaluated when the run starts from
  `instrument_classification`, `classification_node` and `instrument_tags` (current rows only),
  with the resulting symbol list and its hash recorded in provenance.
