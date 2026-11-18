# Pre-registration drafts: three published-prior hypotheses on the stage 2 universe

**Status:** DRAFT 2026-11-15, unapplied. Nothing here is registered, built or run, and no real-data number exists for any member. Each section becomes a registration only after the owner or lead adopts it, the build requirements in section 6 land, and the data gate in section 5 passes. Values below are the proposed pins; a value changed after a real-data number is a methodology change.
**Author:** Claude (indicagent-c6), 2026-11-15, on the lead's brief.
**Informed by:** `docs/ideas/signal-published-prior-shortlist.md` (items 1 to 3 and the sources table; every published figure there is a prior to count, not an expected result), `docs/plans/2026-10-27-daily-residual-momentum-reversal-prereg.md` (the form and the family H-A joins), `docs/plans/2026-11-13-stage2-universe-preregistration.md` (the universe), the universe IC wiring plan for todo 609 blocker I1 (how a spec reads it; unpushed, lands with L3), `docs/plans/methodology-change-ledger.md` E17, E18 and E21, `docs/research/construction-verdict-ledger.md`.
**Governing rules:** E17 (decision statistic), E18 (every attempt counted, Romano-Wolf StepM selection, net-expectation promotion, one forward confirmation per book), E21 (every measured cell counted).

## Owner adoption list

Everything below is pending an owner decision; the lead recommends adopting each. Nothing is adopted, built or run, and no real-data number exists.

| # | Item | What adopting does | Where it is written | Lead recommendation |
|---|---|---|---|---|
| 1 | 5m tier amendment ($25M entry, $12.5M exit, nested in the membership) | Fixes the 5m tier definition before any tier load; the code already carries the values | `docs/plans/2026-11-15-stage2-5m-tier-and-intraday-universe.md` part 1 | ADOPTED 2026-11-18 |
| 2 | Seen-name holdout | Excludes the screen's 231 names and the TSMOM sleeve (about 5 percent of the membership) from both panels, by a pinned list | section 2 here; build item B-U in the I1 plan | ADOPTED 2026-11-18 |
| 3 | A1, universe amendment | Moves the daily residual family from `daily_unseen` to the membership and core panels | daily residual prereg section 10 (draft) | Adopt |
| 4 | A2, sixth member | Adds the information-discreteness member M3 to the daily residual family | daily residual prereg section 10 (draft) and H-A here | Adopt |
| 5 | E23 ledger entry | Records the counted design choices for the three families (12 series) before any result | section 6 here | Adopt |
| 6 | Family 9 registration (52-week-high anchoring) and ledger entry E26 | Registers one member on both panels (2 series) before any result; E25 is reserved for item 5, E27 stays free | `docs/plans/2026-11-15-family9-52week-high-prereg-draft.md` section 8 | Adopt |
| 7 | Stage 2 amendment: membership after the last Massive list (closed list, rule id `stage2-closed-list`) | Fixes the membership source for month-ends after the plan lapses before anyone builds them; adds no look and no series; moves no counted test on the vintage | `docs/plans/2026-11-15-stage2-membership-after-archive-end-amendment-draft.md` | ADOPTED 2026-11-18 |

Items 3 and 4 depend on 2; none of the seven moves a recorded spec hash.

## 1. Which three, and why

The shortlist's own ranking rule is the filter: data the rebuild already holds, a construction the runner already has, slow turnover, few added series. Applied to the stage 2 world, three items clear it and the rest wait on something that does not exist yet.

| Pick | Path to a counted test | What it waits on beyond the shared gate |
|---|---|---|
| H-C same-calendar-month seasonality | Shortest. A kernel over monthly sums of S1 residuals; no stored column, no feature rerun. | Nothing. |
| H-A information discreteness on residual momentum | One added member in a family that already has its spec, universe code and B2 battery built. | The daily residual family's registration (its section 9: B2 at full size, B3, the spec hash test). |
| H-B low-risk members (MAX, residual volatility, beta) | Three stored columns that exist as candidates from the 584 batch; no new kernel. | The corpus rerun landing those columns for the membership names, and todo 583 for the regime disclosure. |

Why not the others:
- Item 4 (high-volume premium): its family 10 pre-registration is unwritten, it sits under the volume basis guard (todos 555, 560, 563), and the vendor seam falls in the forward span. Next in line.
- Item 5 (realized skewness and semivariances): the only item that needs 5m, so it waits on the tier load and the measured cost estimate; weekly full turnover means it most likely fails promotion on costs. It is the first user of the 5m tier and stays the next registration after these.
- Items 6 to 10: need todo 548 (time-series construction), uncaptured data (auction calendar, earnings dates, FINRA short interest), or a base book.

Order of first tests: H-C, then H-A, then H-B. H-C needs the least of the build; H-B needs the corpus rerun to have landed its columns, so it is last by dependency, not by merit.

Universe note. The lead's brief says "universe from the stage 2 tier". These three read the **1d membership** (`universe_membership`, the $1M / $0.5M rule), not the 5m tier: the tier is the 5m subset, and none of the three needs 5m bars. The tier enters only for item 5.

## 2. The shared frame (applies to H-A, H-B and H-C)

**Universe.**
- Primary panel: `universe: universe_membership`. Session d is a member of the latest built as_of strictly before d; prices stay unmasked (warmup and returns need them), and the target and member cells of non-members are NaN (wiring plan design items 1 to 4). The ledger rule id (`stage2-2026-11-15` or later) is inside the snapshot hash.
- Core panel: `universe_membership_core`, names that are members at 90 percent or more of the month-ends of the span. The stage 2 preregistration requires every family on both panels. Each panel is its own counted series (section 4).
- Seen-name holdout (ADOPTED 2026-11-18 (owner decision taken through the lead); counted in E23): the 231 names the 2026-09-13 screen and the corpus IC looks read, plus the TSMOM sleeve, are excluded from both panels by the pinned list the daily residual family already defines (B1). It is 5 percent or less of the membership, and it keeps these tests unseen on their data without a second disclosure cell. This needs the membership universe to accept an exclusion list (build requirement B-U). If the owner prefers no holdout, drop B-U and each family discloses the seen names as a prior look touching about 5 percent of the panel.
- The `daily_unseen` universe of the daily residual prereg (section 2, 1,269 names of `compute_eligible_1d`) is superseded for H-A by the rule above; that supersession is draft amendment A1 in section 3.

**Target.** `panel.forward_returns`, `ln(open[d+h+1] / open[d+1])`, residualized by S1 vintage 1 with the forward-horizon lag (`transform.s1_target(panel, h, vintage_1)`), exactly the family's recipe. Total-return prices (`panel.total_return: {suspect_yield: 0.10}`); outside `dividend_event_coverage` dividends are unknown, never zero. Horizon h = 5 only. The h = 21 versions wait for todo 547 and are new specs with their own counted attempts. S1 is regenerated from the rebuilt tables on the membership panel before any run; a vintage fit on the old universe is not reused.

**Span.** Panel start 2005-01-03 (the NYSE calendar floor, daily residual prereg section 10; todo 564's calendar extension would be a new spec). End exclusive `alpha.validation.oos_start`, 2025-12-24; the forward span is never read. Scored start and sub-periods are per family below; sub-periods are reported, never voted.

**Family and guard config.** One `kind: family` spec per family with the recipe of `research/specs/daily_residual_h5.yaml`: construction R1 `rank_vol_neutral` (direction +1, coverage floor 20, 60-session residual vol, at least half finite), `timing_statistic: e17` with L equal to the member's memory plus h, `session_scoring: true`, `min_shift: 63`, `bootstrap_mean_block: 21`, `bootstrap_reps: 2000`, `seed: 183`, guard seed 183, S3 causality probe (perturbing bars inside the target window must leave alpha and S1 loadings unchanged), S3 memory guard (no output earlier than the declared memory allows). Member signs are applied inside each member and the construction direction is +1.

**Selection and counting.** Every member on every panel is one counted attempt in the vintage-1 selection universe (E18, E21); no member has a bar of its own. Selection is Romano-Wolf StepM at 0.05 over the whole universe of everything seen on the vintage. The look count of each family is declared in section 4 before any run and is bookkeeping, never a cap. A dropped or refused cell still counts.

**Pass and fail, declared before any run.**
- Detection (the only statistical pass): the member's E17 statistic, one-sided in the published direction, is in the StepM rejection set at 0.05. A significant result in the opposite direction is recorded as an opposite-sign finding: counted, not promoted, not turned into a reversed hypothesis.
- Fail: not in the rejection set. A fail is recorded as a null in the research ledger with its look count and stays in the universe forever.
- Pre-run gates (properties of the machinery, not results): B2 size at 0.05, 0.01 and 0.00167 over 1,000 simulations per cell, including the new members, plus the static-size precondition on the real membership panel; the S3 probes pass; each member's first finite row is reported per name and the memory guard holds. A failed gate postpones the run; it is never a verdict on the hypothesis.
- Disclosures that carry no threshold and never gate: sub-period signs, B3 minimum detectable IC at 80 percent power, the `regime_volatility` split (only after todo 583 is fixed; until then no regime split is reported over a partial panel), published-versus-measured spread against the half-haircut prior (a detection whose gross spread is under a quarter of the published value-weighted figure is labelled "detected, economically small" and costed first).
- No promotion from these registrations. They create member evidence attempts only. Promotion needs a book registration (combiner, missing-member rule, construction, horizon rule, book memory), positive net expectation, and one forward confirmation on a span that opens after the book's freeze.

**Costs.** Never in the statistic (E18). At promotion only, with the half-spreads measured through the todo 553 kernels (Corwin-Schultz, Roll) on the membership names; the only measured spreads today are for the 434 intraday names and say nothing about the wider membership. Monthly-turnover members (all three here) sit inside the Novy-Marx and Velikov survivable band, so no buy-hold band is pre-declared; one would be a new counted construction.

**Forward-span rule.** The span from 2025-12-24 is read by no member run and no disclosure. A frozen book gets one confirmation on its own unsearched forward span, sealed shadow for every book in the set, per E18.

## 3. The three drafts

### H-A. Information discreteness modifies residual momentum

**Hypothesis.** Among names with similar 12-1 residual momentum, those whose formation return arrived as many small same-sign days continue more than those whose return arrived in a few large days (Da, Gurun and Warachka 2014, Review of Financial Studies 27(7): 5.94 percent for continuous names to -2.07 percent for discrete names). The published sort is within momentum groups on raw returns; the product on S1 residuals below is this registration's transfer to the R1 construction, labelled as such.

**Member (one, added to the daily residual family).** `residual_momentum_12_1_continuity`, row d, over the same 231 sessions as M1 (d-251 to d-21) of S1 residual daily returns e:
- PRET = sum of e over the window (this is M1).
- ID = sign(PRET) x (share of window sessions with e < 0 minus share with e > 0). Zero residuals count in neither share; the denominator is the finite sessions. NaN when PRET is zero or fewer than half the window is finite.
- Continuity c = centered cross-sectional rank of -ID on row d, over the finite names (range -0.5 to +0.5, ties by average rank).
- Member value = M1 x c, sign +1. Direction check: continuous winners are long, continuous losers short; discrete winners are short and discrete losers long, which is the published monotone pattern (the paper reports continuation at the continuous end and reversal at the discrete end). Declared memory 525 rows (slot history 252 plus S1's 252 plus 21), as M1.

**Draft amendments to `docs/plans/2026-10-27-daily-residual-momentum-reversal-prereg.md` section 10, recorded before any real-data number:**
- A1 (universe): section 2's members universe and `daily_unseen` are replaced by the section 2 rule here (membership and core panels, with the B1 seen-name list as the holdout). The family's attempts become five members times two panels.
- A2 (sixth member): add the member above. Attempts become six members times two panels. B2 reruns with the sixth member and the equal-weight book at full size; B3 states its minimum detectable IC; the spec `daily_residual_h5.yaml` gains the member and is added to the pinned spec-hash test.
- A3 (scored span): unchanged (2007-03-01 to 2025-12-23, sub-periods 2007-03-01 to 2011-12-31, 2012 to 2018, 2019 to 2025-12-23).

**Pass and fail.** Detection as in section 2, direction as published (positive). The family's other members keep their own pre-declared directions.

**Disclosures (prior looks).** It is a modifier of M1, so its series is highly correlated with M1's; StepM's joint draw prices that. Corpus daily IC looks and the 2026-09-13 TSMOM screen are seen data, handled by the holdout.

**Specific data gate.** The news-coverage channel of the paper cannot be tested (no source); the registration says so.

### H-B. Low-risk members: MAX, residual volatility, beta

**Hypothesis.** Names with high recent maximum daily return, high residual volatility or high market beta earn lower subsequent residual returns (Bali, Cakici and Whitelaw 2011; Ang, Hodrick, Xing and Zhang 2006; Frazzini and Pedersen 2014; Novy-Marx and Velikov 2022 on the beta estimator). The case for testing is that it is cheap and slow, not that the prior is strong: 96 percent of the trading-frictions category fails a t of 1.96 under value weights (Hou, Xue and Zhang 2020), and volatility predictors sit in that category.

**Members (three, stored columns read as they are).**

| Member | Column | Window | Sign |
|---|---|---|---|
| H-B1 | `max_daily_return` | `feature.max_daily_return.window`, APR default 21, copied into the spec at registration | -1 |
| H-B2 | `idiosyncratic_volatility` | `feature.idiosyncratic_volatility.window`, APR default 21 (residual std against the fixed market series, not S1's factors) | -1 |
| H-B3 | `equity_beta_z` | the one rolling OLS estimator under `feature.factor_beta.window`; no second beta definition | -1 |

Values are pinned from the APR at registration and recorded in the spec; the row each member scores on is the stored column on session d (known at d's close). Declared memory per member is the column's own memory from the 584 batch plus S1's 273 sessions, read from the feature contract, not retyped here. An S1-residual variant of volatility is a separate counted member and is not run in this registration. SCH industry-neutral forms are not run: neutralization would add its own series.

**Checks before the first run.**
- S1 removes factor return variation but keeps a name's mean residual, so a CAPM-style alpha on beta or volatility survives residualization; the principal components may partly span a low-risk factor. The registration reports the book's PC loadings on each member as a disclosure.
- The three members share a lottery-demand and leverage-constraint mechanism and are one family for counting.

**Pass and fail.** Detection as in section 2, per member, direction negative as published (a high-risk name earns less). A detection on beta alone is flagged against the estimator caveat above and costed first.

**Disclosures (prior looks).** The three columns are 584-batch candidates. Any IC they show in the post-rebuild level 1 sweep (todo 601) is a counted E21 cell that joins the same selection universe; the registration lists those cells by run id, or states that the sweep had not read them. Corpus `downside_deviation` and the volatility columns have seen corpus IC; the ledger's never-tested relative-value volatility-rank row is superseded by this family, not counted twice.

**Specific data gate.** The three columns exist for every membership name over the scored span after the corpus rerun (todo 584 manifest), with todo 564's check that none is constant or all-null; todo 583 fixed before any regime disclosure. A name or year with the column NaN is masked, never filled (`no_fill`).

### H-C. Same-calendar-month return seasonality

**Hypothesis.** A name's average return in the same calendar month over prior years predicts its return in that month this year (Heston and Sadka 2008, Journal of Financial Economics 87(2); Keloharju, Linnainmaa and Nyberg 2016, Journal of Finance 71(4)). The 2021 follow-up finds seasonal effects offset by reversals over the rest of the year, which the second member tests directly.

**Members (two, a research-layer kernel over monthly sums of S1 residuals).** For row d, the label month m is the calendar month of session d+1, the session the target enters in; only months before m are read, and a month is read only when complete at d's close, so no target-window return enters a member.
- H-C1 `seasonal_same_month_5`: mean over lags k = 1 to 5 of the name's S1 residual return summed over calendar month m - 12k. Needs at least 3 of the 5 lags finite. Sign +1.
- H-C2 `seasonal_other_months_5`: mean of the monthly residual sums over the 60 months before m, excluding every month whose calendar month equals m. Needs at least half finite. Sign -1 (the published control reverses). Constant within the month.
- Residual, not raw, monthly sums: the target is S1 residual, so a raw-return seasonality would be mostly market and factor seasonality the target cannot reward. This is a transfer from the paper's raw form, labelled as such; the lag range 1 to 5 is pinned and never swept.
- Declared memory in rows per member: slot history `seasonality.slot_history_sessions(60)` = 1,403 sessions (an upper bound; the measured reach is 1,324 for H-C1 and 1,297 for H-C2) plus S1's 273, so 1,676, as pinned in `research/specs/seasonality_h5.yaml`. The earlier estimate of about 1,260 is superseded.

**Scored span.** With S1 residuals starting in 2005 and three finite lags required, the first finite signal is about March 2009 (a name with bars from the panel start), and `trading_start` is 2009-03-02. E17 tests a session only after 60 scored sessions older than s - L, and L is the slot history plus the horizon, 1,408 sessions here, so the first tested session is 2014-12-29: the effective tested span is about 11 years, not 17, and the draft's first sub-period (2009 to 2014) would have held three tested sessions. Amended 2026-11-18, before any real-data number: the sub-periods are 2015-01-02 to 2018-12-31, 2019-01-01 to 2022-12-31 and 2023-01-01 to 2025-12-23, reported not voted (the last two hold the 2020 and 2022 episodes). `trading_start` is kept so history accrues; a test requires every declared sub-period of every registered daily spec to hold tested sessions under the spec's own L. A different date is a further amendment before any real-data number. H-C does not register or run until the E17 battery (`null_battery_seasonality`, todo 635) shows SIZE HOLDS in the seven non-S1 cells (held, 1,000 simulations each) and in the S1 cell (running); both results are recorded with the E23 entry, and `runner.static_gate` refuses a real run without a recorded pass for the family's inputs and the battery's current code.

**Pass and fail.** Detection as in section 2: H-C1 positive, H-C2 negative.

**Disclosures (prior looks).** January and quarter-end target months overlap ledger families 5 and 6 (period-end marking, tax-loss selling): the verdict is also reported with those target months masked, recomputed from the stored D_s series, never a new attempt, and the selection uses the full-sample series only. This is not family 1 (intraday same-slot periodicity). There is no prior real-data look at this statistic.

**Specific data gate.** Monthly sums need the dividend-adjusted series with `dividend_event_coverage` declared; a month with a missing session count above a pinned fraction of the calendar is masked, never filled. S1 vintage regenerated on the membership panel.

## 4. Look counts, declared before any run

Looks per family are members times declared horizons times panels (primary and core).

| Family | Members | Horizons | Panels | Series added |
|---|---|---|---|---|
| H-A | 1 | 1 (h = 5) | 2 | 2 |
| H-B | 3 | 1 (h = 5) | 2 | 6 |
| H-C | 2 | 1 (h = 5) | 2 | 4 |
| Total | 6 | | | 12 |

The daily residual family's own five members add 10 more when it registers, so H-A is the sixth member of a family of 12 series. Counting the core panel as its own series is the conservative reading of the stage 2 rule; correlated series cost little under StepM's joint draw. At h = 21 each count doubles, as separate registrations after todo 547. The cells of E21 sweeps that touch the same columns join the same universe under their own `n_looks` declaration.

## 5. What must pass before any run (data gate)

In order, none optional:
1. Step 7 D1 proven (canonical is Massive then Alpaca) and the clean-data rule lifted by the owner for these families (owner 2026-10-30; no real-data hypothesis test runs while the rebuild is in progress).
2. Stage 2 gates 1 to 5 of the universe preregistration: dead-name instrument rows, the map rebuilt on the pit snapshots, the all-ticker 1d load compared per year, `universe_membership` built by one writer with the member count by year shown to the owner.
3. The corpus rerun's data gate (`services/corpus_rerun_data_gate.py`) passes for 1d on the membership names, and H-B's three columns exist and pass the constant or all-null check (todo 564); todo 583 fixed.
4. Universe IC wiring (blocker I1) landed: the `universe_membership` Literal in the panel spec, the mask in the snapshot hash, `repro_frozen` bit-identical, and its methodology-change entry written.
5. S1 vintage 1 regenerated on the membership panel.
6. Daily residual B2 at full size with the sixth member (H-A) and the static-size precondition on the real membership panel; B2-style cells for the H-B and H-C kernels (H0 size over 1,000 simulations per cell); B3 power statements for all six members.
7. Specs written, added to the pinned spec-hash test, and each registration section here adopted with its look count entered in the ledger before the run.

## 6. Build requirements and ledger text (drafts)

- **B-U:** exclusion-list support for `universe_membership` (pinned symbol list, hash in the snapshot manifest), so the B1 seen-name list holds on the new universe. Optional if the owner drops the holdout.
- **B-H:** H-C kernels (`seasonal_same_month`, `seasonal_other_months`) and H-A's continuity kernel under `src/intelligence/research/families/`, pure functions over S1 residual arrays, with unit tests for the lag arithmetic, month labelling at month boundaries and the causality probe.
- **B-S:** three spec files (`daily_residual_h5.yaml` amended for H-A, plus two new) with their spec-hash pins.

**Draft entry for `docs/plans/methodology-change-ledger.md` (E23, written before any real-data result):** "Registration of three published-prior families on the stage 2 universe. Counted design choices: the `universe_membership` and core panels as the family universe (two series per member), the seen-name holdout, h = 5 only, the S1-residual transfers of H-A and H-C, the pinned directions, StepM detection at 0.05 as the only pass. Looks declared: 12 series (section 4). Pre-registered by construction: no real-data number exists. Moves no recorded spec hash; `repro_frozen` bit-identical. Further counted design choices recorded 2026-11-18 (build items I1, B-U, B-H): S1 is fitted on the names seen as members on or before each date (first membership onward), membership gates alpha and target only, and non-member same-day returns of already-seen names enter S1's market and group means (point in time); an entrant's residual history starts at its first membership, and the share of member-days not yet warm because of entry is measured per year and disclosed at the membership build; `universe_membership_core` is defined over the span's month-ends, so a name's core status at t depends on months after t: core is a fixed robustness panel and never a selection basis for a counted family, and a family registered on core alone needs a separate counted amendment; M3's continuity rank is taken over every name with a finite ID on row d, including a name whose residual is NaN on d or that is not a member that day (masked afterwards); the H-C pinned values are max_missing_fraction 0.25, lags 5, min_lags 3, window_months 60, with declared memory read from `seasonality.slot_history_sessions(60)` (1,403 sessions) plus S1's 273, so the "about 1,260 plus 273" estimate above is superseded by the measured reach (1,324 and 1,297 sessions); the effective tested span is about 11 years, not 17, because E17's memory L = 1,408 sessions delays the first tested session to 2014-12-29, and the H-C sub-periods are 2015-01-02 to 2018-12-31, 2019 to 2022 and 2023-01-01 to 2025-12-23."

**Draft rows for `docs/research/construction-verdict-ledger.md` section 3:** row 13, low-risk members (MAX, residual volatility, beta), design only, H-B above, pending pre-registration and the post-rebuild columns; row 14, same-calendar-month return seasonality, design only, H-C above, pending pre-registration. H-A is a member of row 11, recorded in the family's section 10, not a new row.

## 7. Open points for the owner or lead

- Seen-name holdout (B-U): lead ruled adopt, pending the owner (adoption list, item 2).
- Core panel counted as its own series: lead ruled yes (doubles each count).
- H-B's regime disclosure stays off until todo 583 is fixed; H-A and H-C carry no regime claim.
