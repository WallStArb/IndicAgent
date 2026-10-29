# Pre-registration: daily residual momentum and short-term reversal

**Author:** Claude (Opus 5.5, indicagent-5b research lane), 2026-10-27. Ledger families 11
(residual momentum, todo 441) and 4 (short-term reversal, todo 423), registered together as one
daily family because they share the panel, S1 target and construction, and because each must
declare its overlap with the other.
**Informed by:** todos 441 and 423; `docs/research/construction-verdict-ledger.md` families 4,
9 and 11 and the TSMOM row; `docs/plans/2026-09-25-family2-overnight-intraday-prereg.md` for
form.
**Governing rules:** unified design (`docs/plans/2026-09-26-unified-research-to-production-
design.md`) with E17 (decision statistic) and E18 (counted attempts, StepM selection) in
`docs/plans/methodology-change-ledger.md`. Build-first lifts for this family at phase 191 plan
20's 1d re-derive (owner amendment 2026-10-27).
**Status:** DRAFT 2026-10-27, before any real-data number for any member. Registered after the
cross-AI review (section 8) and the build requirements (section 9). The runner's machine spec
must reproduce every value pinned here; a mismatch is a methodology change.

## 1. Hypotheses and mechanisms

**Residual momentum** (Blitz, Huij and Martens 2011, Journal of Empirical Finance, "Residual
momentum"; Gutierrez and Pirinsky 2007). A name's return over the past year, net of its factor
exposures, predicts its residual return over the following month. Total-return momentum loads
on time-varying factor exposures and crashes when factors reverse; residual momentum keeps the
firm-specific part, which the authors find roughly doubles the risk-adjusted premium and removes
most of the crash exposure. Mechanism: slow diffusion of firm-specific news (underreaction).
The most recent month is skipped, because it carries the opposite effect below.

**Short-term reversal** (Jegadeesh 1990; Lehmann 1990; Da, Liu and Schaumburg 2014, Management
Science, "A closer look at the short-term return reversal"). A name's residual return over the
past week or month reverses over the following week or month. Da, Liu and Schaumburg show the
reversal is concentrated in the residual, non-news component, consistent with liquidity
provision: the market maker who absorbs an order imbalance earns a reversal premium. Executable
open-to-open targets (CLAUDE.md, executable returns only) remove most bid-ask bounce from the
measured effect; the residual is stated in section 7.

The two pull against each other over the skipped month: a name up strongly last month is a
reversal short and, over the year, a momentum long. That is the point of testing them together
on one target (section 3, overlap).

**Not in this family** (stated so nothing here is read as a failure of them):
- Industry momentum (Moskowitz and Grinblatt 1999), todo 441's other daily branch, deferred and
  kept open there. The reason is data: industry portfolios need SCH industry labels as of each
  date, and SCH history before its 2026 records is present-day labels, which S1 rejected as
  look-ahead. (S1's statistical groups are price clusters, not industries; they absorb part of
  industry co-movement but do not make industry momentum absent from the residual.) Its family
  pins point-in-time industry portfolios and its own target (market-only or separately
  specified residuals).
- Sector-ETF lead-lag (todo 441 item 2) is intraday (5m or 15m): a later family.
- Price anchoring and slow reversal (ledger family 9): daily, overlapping in mechanism; its
  pre-registration must position against this one (section 7).

## 2. Data

- **Panel:** S0 daily snapshot, `tf: 1d`, one row per session, universe `compute_eligible_1d`
  (1,502 of 1,529 active names on 2026-10-27; the todos' 931 is stale). The universe is point in
  time on entry (a name has no row before its first bar) but not on exit: delisted names are
  absent, in S1's factor inputs as well as in positions. That is the survivorship limitation the
  owner accepted when retiring the survivorship bound (todo 514, 2026-10-09); the run reports
  position and S1 universe membership by date, and the verdict carries the disclosure. Panel span 2000-01-03
  to 2025-12-24 exclusive: about a quarter of names have daily bars from 2000, half from 2006.
- **Prices:** total-return (`panel.total_return: {suspect_yield: 0.10}`, todo 428). A daily
  target held across sessions carries every ex-dividend drop as a loss otherwise, which would
  manufacture reversal on high-yield names.
- **S1:** `vintage_1` on the members' universe of the daily panel (market, statistical group, 5
  principal components; 252-session window, 21-session refit). Members and target both read S1
  residuals.
- **Members' universe:** `daily_unseen` (build requirement B1): `compute_eligible_1d` names whose
  `instruments.created_at` is on or after 2026-09-13, minus the 13-symbol sleeve the TSMOM look
  read. On 2026-10-27 that is 1,269 of the 1,502 daily names. The excluded set is the union of
  every disclosed prior look's names (section 6): the 231 active instruments that existed on
  2026-09-13 (the screen's universe exactly, and the names the daily corpus IC looks read) and
  the sleeve (two of whose symbols, EMLC and VIXY, were created after the cutoff). The rule
  narrows the S0 panel before S1, as family 2's members universe does, so this is a data
  holdout, not only a position holdout: the excluded names' returns enter neither the members,
  the target nor S1's factors. The exact list is mandatory: if the rule cannot reproduce the
  screen's 231 names, the run refuses.
- **Scored span:** alpha rows from 2003-01-02 (`trading_start`) whose 5-session target completes
  inside the panel. The panel ends at 2025-12-24 exclusive, so the forward span is not in it at
  all; an alpha row whose exit open would fall on or after 2025-12-24 has a NaN target
  (`forward_returns` returns NaN past the panel's end), which makes the last scored alpha row
  about 2025-12-15. M1 and M2 need
  S1 loadings (252-session window, at least 126 finite) and then 252 sessions of residuals, about
  525 sessions after a name's first bar, so three years precede the scored start for names with
  bars from 2000; later-listing names enter when their own members first turn finite. The run
  reports each member's first non-NaN row and effective span per name and in total, and the S3
  memory guard refuses any output earlier than the declared memory allows. Sub-periods are
  reported, not voted: 2003-2008, 2009-2016, 2017-2025-12-23. The forward span (from `alpha.validation.oos_start`,
  2025-12-24) is never read.
- **Data quality:** the D0 labels (todo 501) are pinned in the snapshot manifest and disclosed;
  names whose daily history shortens in the 191-20 re-derive are listed from 3a's first-bar TSV
  in the run record.

## 3. Members

All members read S1 residual daily returns `e[s, i]` (close to close, known at s's close) for
sessions up to and including the signal row d, and place alpha on row d, formed at d's close;
the target enters at d+1's open, so no member reads a return inside the target's window. Sums
need at least half the window's sessions finite (the standardized member also at least 2 and a
positive sd), else NaN. Signs are applied inside each member; the construction direction is +1.

| Member | statistic for row d | sessions read | Sign | slot_history_sessions |
|---|---|---|---|---|
| M1 residual_momentum_12_1 | sum of e over d-251 .. d-21 | 231 | +1 | 252 |
| M2 residual_momentum_12_1_z | mean(e) / sd(e, ddof 1) over the same sessions as M1 (the volatility-standardized form of Blitz et al., who scale formation-period residual returns by their own residual sd) | 231 | +1 | 252 |
| R1 reversal_5 | sum of e over d-4 .. d | 5 | -1 | 5 |
| R2 reversal_21 | sum of e over d-20 .. d | 21 | -1 | 21 |
| R3 reversal_5_skip1 | sum of e over d-5 .. d-1 (one-session skip, todo 423) | 5 | -1 | 6 |

None of these is a canonical form of its paper. M2 is closest to Blitz, Huij and Martens (their
12-1 residual return over formation-period residual volatility), adapted to S1's 252-session
model in place of a 36-month three-factor regression and to a one-week target in place of a
monthly holding period; M1 is its unstandardized variant. R1-R3 are S1-residual reversal
proxies: Da, Liu and Schaumburg remove expected returns and analyst-forecast cash-flow news and
sort within industry, which S1's price clusters do not replicate. A point-in-time
within-industry reversal is a later diagnostic, outside this attempt.

Declared memory per member is `declared_memory_rows(slot_history_sessions, 1, vintage_1)`:
slot history plus S1's 252 + 21 sessions (M1, M2: 525 rows; R1: 278; R2: 294; R3: 279).

**Overlap, declared.** R2's window (the last month) is exactly the month M1 and M2 skip, so the
members are built not to share sessions. Within a book they enter the S7 combiner as separate
members with their stated signs; the combiner, not this pre-registration, weighs them. Family 9's
members (`rsi_slow`, `price_percentile_slow` and others) read the same daily prices over similar
windows; family 9 registers after this one and states its correlation with R1-R3.

## 4. Target and construction

- **Target recipe:** the panel kernel's executable return `ln(open[d+h+1] / open[d+1])` on row
  d, residualized by S1 with the forward-horizon lag (`residual_returns(..., horizon=h)` through
  the runner's `transform.s1_target(panel, h, vintage_1)`): the loadings applied at row d are fit
  only on rows whose own forward windows end before d+1, so no target-window return enters a
  loading. The S3 causality probe perturbs bars inside the target window and must leave alpha and
  the loadings in force at d unchanged.
- **One spec, h = 5:** `daily_residual_h5`. Five member evidence runs, each a counted attempt
  that joins the vintage-1 StepM universe (E18); nothing else is charged by this registration.
- **E17 on a multi-session target (methodology-change-ledger E17 amendment 2026-10-27).** E17's
  L, the window fbar_L excludes, was each signal's memory in sessions, which keeps fbar_L clear
  of the signal's inputs only when the target ends inside its entry session (every target
  before this family). A daily target at row r runs open[r+1] .. open[r+1+h], so L is now the
  memory plus h (`timing.e17_memory`; the last session is the overnight move into the exit
  session); with L equal to the memory, the B2 battery's 5-session reversal member had mean H0 t
  +0.55 and rejected 15% at 0.05 (60 simulations), and with the amended L, on a battery panel
  with overnight gaps, its mean t is about 0. Intraday L is unchanged, so no recorded run moves.
- **HAC lag at h = 5, open.** A 5-session target overlaps the next 4 rows', and the Bartlett
  weights of E17's Newey-West lag (floor(4 (n/100)^(2/9)), about 9 at n 5,800) do not fully
  cover that overlap: in the same 60 simulations the reversal members' H0 t had sd 1.07 to 1.14
  and rejected about 8% at 0.05. B2 must hold at full size (1,000 simulations per cell); if it
  does not, the run waits for a second E17 amendment tying the HAC lag to the horizon, the same
  one h = 21 needs.
- **Not run: h = 21**, the canonical momentum holding period. Its targets overlap for 20
  sessions, more than the Newey-West lag, so E17 as adopted would overstate its t. It waits for
  a methodology-change-ledger amendment that ties the HAC lag to the horizon (lag at least h - 1)
  and a battery cell at h = 21; it is then a new spec and its own counted attempts.
- **No book here, and no promotion from this registration.** It creates five member evidence
  attempts only. A book that combines these members (with family 9 or others) is its own
  registration: it pins the combiner, standardization, missing-member rule, construction,
  horizon rule and book memory (member memory plus the combiner's training reach).
- **Construction:** R1 rank-vol-neutral (direction +1, coverage floor 20, trailing residual vol
  over 60 sessions with at least half finite). Daily rebalancing of an h-session target overlaps
  positions; the E17 statistic's HAC lag covers the overlap.
- **Costs:** disclosed, never in the statistic: 1-5 bps per side as family 2; reversal at h = 5
  turns over most, and its promotion needs positive net expectation (E18).

## 5. Evidence and the test

E17: one-sided HAC t on the per-session D_s series of each member's R1 book, memory per member
as declared above; the static-size precondition must pass at the measured static sizes of the
daily panel before any real-data run (build requirement B2). The shift null is reported as a
diagnostic. Each member run writes its D_s series through S6 and joins the vintage-1 StepM
selection universe (E18); no member has a bar of its own. A book combining these members with
other families is a separate attempt.

## 6. Disclosed prior looks at this data

- **2026-09-13 screen** (`ctf_momentum`, which at 1d is a 14-period RSI, against the 2-session
  forward return, as a per-symbol time-series IC): pooled IC -0.0261, single names -0.0280, ETFs
  -0.0239, on the 231 then-active symbols (128 single names, 103 ETFs) over their full history.
  That is a reversal hint seen in-sample. Its names are excluded from the
  members' universe (B1); its window cannot be excluded (it covered the full history), so the
  hint is disclosed as having shaped R1-R3's existence, not their parameters, which are the
  literature's (one week, one month, one-session skip).
- **TSMOM on the 13-symbol sleeve** (FAIL 2026-09-24, p 0.22, positive in 3 of 3 sub-periods):
  time-series momentum of total returns on ETFs, a different signal on different names. M1 and M2
  are the ledger's named reopen of that failure as cross-sectional residual momentum.
- **Daily corpus IC looks** (ledger family 9 and section 5): the feature corpus's IC term
  structure for slow daily price features (`rsi_slow`, `price_percentile_slow`, `stoch_k_slow`,
  `dist_from_high_slow` and others) was read on raw, not residual, forward returns on the
  intraday-scope names, and found predictability not decayed by the longest horizon measured.
  These are price-anchoring and oscillator features, not residual returns, and they shaped the
  family 9 and family 4 boundary; R1-R3's existence and parameters come from the literature, not
  from those results, and the 231 names they were read on are outside the members' universe.
- Families 1 and 2 ran on 15m data of the intraday-scope names; nothing daily-residual was
  measured.
- The forward span has not been read for any daily-residual quantity.

## 7. Known risks, stated before the run

- **Bid-ask bounce residual:** open-to-open targets remove the close-quote bounce; the opening
  auction's own spread is not removed. R3 (one-session skip) is the stated control: a reversal
  that lives only in R1, not R3, is mostly microstructure.
- **Survivorship:** the universe is today's active names (the owner retired the survivorship
  bound 2026-10-09, todo 514). It inflates reversal on losers most; disclosed, with the D0
  labels.
- **Power at h = 5 for slow members:** M1 and M2 change slowly, so their weekly books carry
  few independent bets a year; B3 states each member's minimum detectable IC before the run, and
  a member below the bar still runs, is counted and discloses its power.
- **Dividends:** price-only daily data would manufacture reversal at ex-dates; the total-return
  panel removes it, and the family 9 guard test shows the mechanism.
- **Delisting returns:** names that delisted are mostly absent; the sensitivity requested in
  todo 441 is reported from the D0 labels where a delisting date is known.

## 8. Review record

Round 1 (2026-10-27, Codex gpt-5.6-terra, read-only; AGY was out of quota until about
2026-11-03): 5 HIGH, 4 MEDIUM, 1 LOW, verdict "register after fixes". Taken:
- HIGH, h = 21 overlap exceeds E17's Newey-West lag: h = 21 removed until an E17 horizon-lag
  amendment; h = 5 kept with an overlapping-target battery cell (sections 4, 9).
- HIGH, power check underspecified: B3 now pins generator, persistence, IC grid, R and the
  statistic, as a disclosure.
- HIGH, the seen-name fallback: removed; the exact 231 names come from `created_at`, and the run
  refuses if the rule cannot reproduce them; the position-versus-data holdout is stated.
- HIGH, target residualization not pinned: section 4's target recipe and its S3 probe.
- HIGH, universe not point in time on exit: stated as the owner-accepted survivorship limit,
  reported by date (section 2).
- MEDIUM: industry momentum's deferral reason corrected; attempt count enumerated (five) and
  books moved to their own registration; scored start moved to 2003 with per-member spans;
  daily corpus IC looks disclosed. LOW: canonical forms versus variants labelled, M2's formula
  written out.
Round 2 (2026-10-27, Codex): 2 HIGH, 5 MEDIUM, 1 LOW, verdict "register after fixes". Taken:
- HIGH, scored end: stated in target terms (the panel ends before the forward span; late alpha
  rows have NaN targets).
- MEDIUM: literature labels corrected (no member is canonical); no-promotion stated; the seen
  set is now the union of every disclosed look's names, the sleeve included (EMLC and VIXY were
  not excluded by the cutoff alone), and S1 is fit on the members' universe, so the holdout is a
  data holdout; B2 enumerates the five members at their own memories with the spec's
  construction; B3 at 1,000 replicates.
- HIGH, construction vol in E17 memory: not taken as a memory change. E17 as adopted takes L
  from the signal, and the family 1 and 2 batteries held with R1's trailing vol in the loop; B2
  runs the 60-session vol exactly as the spec does, so if vol in the weights biases D_s the
  battery fails and the run waits.
Found while building B2, outside the review: E17's L did not cover a multi-session target
(amended, section 4), and the HAC lag at h = 5 is open (section 4).

## 9. Build requirements before the first real-data run

- **B1** `members_universe: daily_unseen` in S0: `compute_eligible_1d` names with
  `instruments.created_at >= 2026-09-13`. The screen (`scripts/analysis/tsmom_per_symbol_ic_
  screen.py` at 9adf3f2d4) ran on the 231 symbols then active, all of them instruments created
  before that date; on 2026-10-27, 231 active and 253 total instruments predate it, so the rule
  excludes the screen's names exactly (and 22 inactive ones it never saw). The list and its hash
  are pinned in the snapshot manifest, as `us_session_equity` is.
- **B2** an E17 H0 battery module for this family (`null_battery_daily_residual`) scoring each
  of the five members at its own amended memory through the spec's construction (R1, 60-session
  trailing vol) on the h = 5 overlapping target, plus their equal-weight book, in gaussian,
  static-mean, late-listing, hostile and S1 cells, with size holding at 0.05, 0.01 and 0.00167
  over 1,000 simulations per cell; and the static-size precondition passing on the real
  1,269-name panel.
- **B3** synthetic power, disclosed before the run, not a gate (member runs have no power bar
  under E18). Generator: the residual-space synthetic (`synthetic.py`) on the real daily panel's
  availability mask, plant persistence AR(1) phi 0.0 (reversal, turns over in days, todo 423) and
  0.98 (momentum), planted rank IC 0.005, 0.01 and 0.02, R = 1,000 replicates per cell, each
  scored by the real E17 statistic through R1 at h = 5 with each member's declared memory and
  the production HAC lag. Reported: power at one-sided 0.05 and each member's minimum detectable
  IC at 80% power.
- **B4** phase 191 plan 20's 1d re-derive has landed (3a's notice); its first-bar TSV is
  attached to the run record.
- **B5** the spec `research/specs/daily_residual_h5.yaml` reproduces every value above and is
  added to the pinned spec-hash test before its first run.

## 10. Amendments before the first real-data number

**2026-10-29, panel start.** Section 2 pins the panel at 2000-01-03 and the scored span from
2003-01-02. The snapshot builder cannot build a daily panel before 2005: `get_market_calendar`
covers 2005-01-01 onward (`_PMC_RANGE_START` in `src/core/market_calendar.py`, in the 186-26
fingerprinted closure, so not edited between stages), and `build_grid` rejects bars on days the
calendar does not know (the first attempt failed on 1,256 dates from 2000-01-03). No real-data
number for any member exists, so this is a registration correction, not a response to a result:
the panel starts 2005-01-03, the scored span 2007-03-01 (the first row with M1 and M2's 525-session
memory for a name listed at the panel start) through 2025-12-23, and the sub-periods are 2007-03-01
to 2011-12-31, 2012 to 2018 and 2019 to 2025-12-23 (the first holds the 2008 crisis). Everything
else in sections 1 to 9 stands. Extending the calendar to 2000 is todo 564's rebuild batch; a later
spec on the longer panel would be a new spec with its own counted attempts.
