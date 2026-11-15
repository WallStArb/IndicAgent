# Published-prior shortlist: features, regimes and flow predictors - Idea

**Status:** Idea, 2026-11-15. Nothing queued, registered or computed. No real-data number exists for any hypothesis here; the clean-data rule holds while the step 7 rebuild runs. Each item enters only as a pre-registered family member or S7 variant, counted under E18 and E21.
**Author:** Claude research lane R1, 2026-11-15, from the lead's brief: a ranked shortlist of testable hypotheses grounded in published evidence, checked against the research ledger.
**Informed by:** `docs/research/construction-verdict-ledger.md` (frozen) and `docs/research/research-ledger.md` (generated), `docs/ideas/base-feature-scouting-and-the-research-ladder.md`, `docs/ideas/signal-scoped-regime-states.md`, `docs/ideas/signal-participation-state-style-spreads.md`, `docs/ideas/signal-sensitivity-regime-interaction-primitives.md`, `docs/plans/2026-11-09-regime-conditional-and-incremental-ic.md`, `docs/plans/2026-10-27-daily-residual-momentum-reversal-prereg.md`, the glossary, and a web pass on the papers cited in the sources table.

## How to read this

- Every published number below is a prior to count, never an expected result. Labels: "Published" is what a cited paper reports (abstract level unless stated); "Our inference" is this lane's reasoning and is unverified.
- Three published facts discount every prior here:
  - Published: the average predictor's return decays by about 35% after publication (McLean and Pontiff 2016, as quoted from the authors in coverage of the paper).
  - Published: with microcaps controlled (NYSE breakpoints, value weights), 65% of 452 anomalies fail a t of 1.96, including 96% of the trading-frictions category, and replicated ones are smaller than first reported (Hou, Xue and Zhang 2020).
  - Published: anomalies with monthly turnover below about 50% mostly keep significant net spreads once built to reduce costs; few with higher turnover do (Novy-Marx and Velikov 2016).
- Our inference: the universe is large and mid caps plus ETFs (no microcaps), so the value-weighted replication numbers are the relevant prior, not the original equal-weighted ones. A reasonable working haircut on any published spread is one half before costs.
- Ranking rule (Musk step 1 first): a hypothesis ranks high when it runs on data the rebuild already holds, fits a construction the runner already has (R1, daily clock), turns over slowly enough to clear the measured half-spreads (1.5 to 1.9 bp on the 233-name set, 3.6 to 4.9 bp on the other 201; ledger family 1 row), and adds few series to the selection universe. Anything that needs uncaptured data, the time-series construction (todo 548) or the horizon-tied HAC lag (todo 547) ranks lower in that order.
- Look counts are the series each hypothesis adds to the E18 selection universe: members times declared horizons, each measured cell counted under E21. They are declared before any run.

## Ledger check

Each hypothesis was checked against sections 1 to 5 of the frozen ledger and the generated ledger's idea rows. None re-proposes a recorded null. Where a hypothesis sits next to a verdict or seen-data look, the overlap is stated in its entry and must be disclosed in its pre-registration. Covered and therefore not proposed here: intraday periodicity (family 1), first half hour to last half hour (1b), overnight versus intraday (2), lead-lag (3), short-term reversal (4), period-end marking and flows (5, 6), index reconstitution (7), options expiry (8), 52-week anchoring (9), volume and order-flow corpus members (10), residual and industry momentum (11), the grammar (12), style-spread factor momentum and the participation state, microstructure spread proxies, the dividend event family, PCA residual reversion and the reopened spread family. No owner idea is retired by this doc.

## Ranked shortlist

| Rank | Hypothesis | Data on hand | Construction ready | Turnover | Series added |
|---|---|---|---|---|---|
| 1 | Information discreteness modifies residual momentum | yes, 1d | yes (R1, daily residual family) | monthly | 1 to 2 |
| 2 | Low-risk members: MAX, residual volatility, beta | yes, 1d | yes | monthly | 3 to 6 |
| 3 | Same-calendar-month return seasonality | yes, 1d from 2003 | yes | monthly | 2 |
| 4 | High-volume return premium | yes, 1d volume | yes | weekly to monthly | 2 to 4 |
| 5 | Realized skewness and signed jump variation from 5m bars | yes, 5m from 2016 | yes | weekly | 2 |
| 6 | Volatility scaling of the momentum member (then market-state conditioning) | yes | S7 variant; needs a base book | n/a | 1, later 2 |
| 7 | Stock-bond rebalancing pressure on the index | yes, 1d | no (time series, todo 548) | daily, sparse | 2 |
| 8 | Treasury auction cycle in Treasury ETFs | no (auction calendar uncaptured) | no (todo 548) | event | 1 to 2 |
| 9 | Earnings announcement premium | no (earnings dates uncaptured) | yes once dates exist | event | 1 to 2 |
| 10 | Aggregate short interest as a world state | no (FINRA uncaptured) | S7 variant | monthly | 1 |

Declined on published decay or prior closure, with reasons in the last section: pre-FOMC drift, post-earnings drift, macro-series market timing, market-level intraday momentum.

## 1. Information discreteness modifies residual momentum

- Statement: Among names with similar 12-1 residual momentum, those whose formation return arrived as many small same-sign days (continuous information) continue more than those whose return came in a few large days (discrete information).
- Published: Momentum falls monotonically from 5.94% for continuous-information stocks to -2.07% for discrete-information stocks with similar formation returns; media coverage goes with discrete information (Da, Gurun and Warachka 2014). The measure is `ID = sign(PRET) x (%negative days - %positive days)` over the formation window.
- Data: 1d bars only (Massive from 2003-09-10, then Alpaca), with `panel.total_return`. Cannot use: news counts (no source), so the media channel is untested.
- Construction: One member added to the daily residual family before it registers: M1 (12-1 residual momentum) multiplied by a centered cross-sectional rank of ID computed on S1 residual daily returns. Our inference: computing ID on residual rather than raw returns is the natural transfer to S1, but it is not what the paper tested; state it.
- Horizon: h = 5 now; h = 21, the paper's holding scale, after todo 547.
- Regime segmentation: `regime_volatility` disclosure only.
- Looks: 1 series (h = 5), 2 with h = 21.
- Cheapest first test: Add the member to `docs/plans/2026-10-27-daily-residual-momentum-reversal-prereg.md` while that family is held for registration; the S1 rebuild it already waits on covers it, and the null battery needs only the new member's cells. No new kernel beyond a rolling count of signed days.
- Decay and crowding: Our inference: the construct is published and practitioner summaries of it circulate widely, so expect the McLean-Pontiff decay over our span. Turnover is that of monthly momentum, inside the Novy-Marx-Velikov survivable band.
- Overlap: It is a modifier of M1, so its series is highly correlated with M1's; StepM's joint bootstrap prices that.

## 2. Low-risk members on the residual target

- Statement: Names with high recent maximum daily return, high residual volatility or high market beta earn lower subsequent residual returns.
- Published: The lowest minus highest MAX decile earns over 1% a month, and adding MAX reverses the negative idiosyncratic volatility relation (Bali, Cakici and Whitelaw 2011). High idiosyncratic volatility names earn very low returns (Ang, Hodrick, Xing and Zhang 2006). Low-beta assets earn positive risk-adjusted returns across asset classes, and the factor does poorly when funding tightens (Frazzini and Pedersen 2014); part of the supporting evidence comes from the non-standard beta estimator (Novy-Marx and Velikov 2022).
- Against: Published: 96% of the trading-frictions category fails under value weights (Hou, Xue and Zhang 2020). Our inference: volatility and MAX predictors sit in that category, so in a large-cap universe expect a small effect; the case for testing is that it is cheap and low turnover, not that the prior is strong.
- Data: 1d bars; S1's trailing market and PC factors for residual volatility; SCH industry groups if an industry-neutral form is declared up front (it would add its own series). Cannot use: book leverage or funding-liquidity data beyond the stored FRED funding rates.
- Construction: One pre-registered family, three members sharing a lottery-demand and leverage-constraint mechanism: MAX over 21 sessions, residual volatility over 21 sessions from S1 residuals, and an OLS market beta over 252 sessions (a standard estimator, declared, to avoid the estimator dependence the 2022 critique found). Our inference: S1 removes factor return variation but keeps a name's mean residual, so a CAPM-style alpha on beta or volatility survives residualization; the PCs may partly span a low-risk factor, which the pre-registration must check through the book's PC loadings.
- Horizon: h = 5 and, after todo 547, h = 21.
- Regime segmentation: `regime_volatility` disclosure. One pre-registered S7 variant later: the funding state from the stored credit and funding series (Frazzini and Pedersen's tightening result), counted separately.
- Looks: 3 series at h = 5, 6 with h = 21.
- Cheapest first test: Three pure kernels on the 1d panel through the existing daily construction.
- Decay and crowding: Our inference: low-risk investing is a widely sold product, so crowding is likely, mostly on the long side; a residual book holds both sides.
- Overlap: Corpus features `downside_deviation` and the volatility columns have seen corpus IC; disclose. Volatility-rank features in the ledger's never-tested cross-sectional relative-value row are related; this family supersedes the volatility part of that row rather than counting it twice.

## 3. Same-calendar-month return seasonality

- Statement: A name's average return in the same calendar month over prior years predicts its return in that month this year.
- Published: Same-month returns persist across up to 20 annual lags, independent of size, industry, earnings and dividends (Heston and Sadka 2008). A same-month strategy earned about 13% a year in sample, with similar seasonalities in anomalies, commodities and country indices, and different seasonality strategies are only modestly correlated (Keloharju, Linnainmaa and Nyberg 2016). The same authors find seasonal effects offset by reversals over the rest of the year, pointing to temporary mispricing (Keloharju, Linnainmaa and Nyberg 2021).
- Data: 1d bars from 2003-09-10 with `panel.total_return`; dividends from `dividend_event_coverage` only (outside it dividends are unknown, never zero). Our inference: with a 10-year lookback the first usable signal is late 2013, so vintage 1 holds about 12 years (about 144 monthly cross-sections); a 5-year lookback starts in 2008 with noisier estimates. Declare one lookback, never sweep it.
- Construction: Two members: the same-month mean over lags 1 to 10 years, and the other-months mean over the same lags (the paper's control, which tends to reverse). Constant within the month, scored on the daily clock.
- Horizon: h = 5 inside the month now; h = 21 after todo 547.
- Regime segmentation: None beyond disclosure; the effect is a calendar mechanism.
- Looks: 2 series at h = 5.
- Cheapest first test: A kernel on monthly aggregated returns from the 1d panel; no new data.
- Decay and crowding: Our inference: moderate; the strategy is published and replicated, but its monthly rebalance keeps turnover in the survivable band.
- Overlap: January and quarter-end months overlap families 5 and 6 (period-end marking, tax-loss selling); the pre-registration must report the result with those months excluded as a disclosure. It is not family 1: that family is the intraday same-slot pattern.

## 4. High-volume return premium

- Statement: A name whose volume over the last day or week is unusually high relative to its own recent history rises over the following month; unusually low volume precedes declines.
- Published: The effect is not explained by return autocorrelation, announcements, market risk or liquidity, and the authors attribute it to a visibility shock (Gervais, Kaniel and Mingelgrin 2001); the working-paper version reports it stronger when the volume shock comes without an extreme return.
- Data: 1d volume, under the volume basis guard (todos 555, 560, 563): a volume shock defined on a mixed-vendor or mixed-basis series is an artifact. Trade count would sharpen it (IDEAS bullet 2026-11-09), but it is not stored; do not wait for it.
- Construction: Two members: last-session volume rank inside its trailing 50-session window, and the 5-session version, each orthogonalized to the same-window return (the paper's non-extreme-return condition).
- Horizon: h = 5; h = 21 after todo 547.
- Regime segmentation: `regime_volatility` disclosure.
- Looks: 2 series at h = 5, 4 with h = 21.
- Cheapest first test: Members of family 10 (volume and order flow), whose pre-registration has not been written.
- Decay and crowding: Our inference: unknown; no replication was verified in this pass. Turnover is weekly at worst.
- Overlap: H-A `extreme_volume_divergence` FAILED (15m, within-symbol, light volume at fresh price extremes); that is a different clock and mechanism, but it is a seen look on volume and must be disclosed. Corpus `volume_z` and `rel_volume` have seen corpus IC; disclose.

## 5. Realized skewness and signed jump variation from 5m bars

- Statement: Names with negative realized skewness of intraday returns over the past week earn higher returns the next week; names whose positive-increment variance dominates earn lower returns.
- Published: Buying the lowest and selling the highest realized-skewness decile earns 19 bp a week (t 3.70), not captured by Fama-French and Carhart factors; realized volatility shows no strong relation (Amaya, Christoffersen, Jacobs and Vasquez 2015; the working paper reports 24 bp). Sorting on normalized good-minus-bad volatility gives large, significant return differences (Bollerslev, Li and Zhao 2020).
- Data: Canonical 5m RTH bars (from 2016-01-04 per the provider matrix in `docs/foundation/canonical-truth-registry.md`; check the post-rebuild start). In-session returns only, so the overnight gap never enters the statistic. Cannot use: tick data or quotes.
- Construction: Two members on the daily clock: RSkew from 5m log returns over the past 5 sessions, and the signed jump variation (positive minus negative semivariance over total). Both are pure kernels over the 5m panel aligned to the daily clock through S2b.
- Horizon: h = 5. This is the one item where costs bind: weekly full turnover against 1.5 to 4.9 bp half-spreads. Our inference: in large caps the gross spread is likely well under the published 19 bp, so expect a detection that fails promotion unless a buy-hold band cuts turnover (the Novy-Marx-Velikov mitigation).
- Regime segmentation: `regime_volatility` disclosure.
- Looks: 2 series.
- Decay and crowding: Our inference: moderate; the data needed (intraday bars on a broad panel) limits who trades it.
- Overlap: `jump_diffusion_decomposition` is DEAD (jump ratio added no partial IC beyond `garch_ratio` and `hurst` on a SPY 15m pilot), a per-symbol time-series test, not a cross-sectional weekly one; disclose it. Corpus `ret_skew_z` (rolling bar-return skewness) has seen corpus IC; disclose.

## 6. Volatility scaling of the momentum member, then market-state conditioning

- Statement: Scaling the residual momentum member by the inverse of its own recent realized variance improves its risk-adjusted payoff; separately, momentum pays less after market declines and in high-variance rebounds.
- Published: Scaling momentum by its trailing realized variance largely removes its crashes and roughly doubles its Sharpe ratio (Barroso and Santa-Clara 2015). Crashes occur in panic states, after market declines with high volatility, when the loser leg behaves like a written call on the market (Daniel and Moskowitz 2016). Momentum profits are concentrated after positive lagged three-year market returns (Cooper, Gutierrez and Hameed 2004). Against: across 103 strategies, volatility-managed versions beat their unmanaged forms in direct comparisons only rarely, and real-time mean-variance combinations do worse for 72 of 103, though momentum is one of the cases where it helped (Cederburg, O'Doherty, Wang and Yan 2020).
- Against, locally: The ledger's regime-conditional prior is poor (0 of 270 persistence cells, earnings season 0 of 249). The registered residual momentum member already removes most crash exposure by construction, per the Blitz, Huij and Martens result cited in its pre-registration, so the conditioning has less to fix. Our inference: 2003 to 2025 holds about three bear-and-rebound episodes (2008-09, 2020, 2022), far too few for the market-state variants to have power.
- Data: 1d bars of panel SPY and the family's own member series.
- Construction: The scaling variant is a construction-rule change inside one book, not a regime; it needs no episodes, only a base book. The market-state variants are S7 regime-slot variants (todo 548), each one counted.
- Looks: 1 for the scaling variant; 2 more for the market-state pair, only after an episode count shows power.
- Cheapest first test: A synthetic power check of the market-state variants at three episodes; expect a refusal and record it.
- Overlap: The participation-state doc cites Cooper et al. and Daniel and Moskowitz as its prior; these are the specific states that prior names, entering through the same regime-conditioned combiner row in ledger section 3, not a new row.

## 7. Stock-bond rebalancing pressure on the index

- Statement: When equities have drifted overweight in a 60/40-style mix, the index falls the next day as rule-based rebalancers sell equities (threshold rule); month-end calendar rebalancing produces a slower version.
- Published: Harvey, Mazzoleni and Melone (2025, working paper) separate a threshold signal (faster, intra-month) from a calendar signal (month-end) built from portfolio drift; the authors' summary reports a 17 bp next-day decline when equities are overweight and say the effect has strengthened over time.
- Data: 1d bars of panel SPY and a long-history Treasury ETF; nothing new. Our inference: the paper's next-day return is probably close to close; the executable open-to-open target (`panel.forward_returns`) may lose part of it, and the pre-registration must say which window the effect needs.
- Construction: A market-level time series, outside the R1 cross-section; it waits for todo 548's time-series construction.
- Horizon: One session.
- Looks: 2 series (threshold, calendar).
- Decay and crowding: Our inference: high. The paper is new and its point is that others already trade ahead of the flow.
- Overlap: Families 5 and 6 (period-end marking and flows): the calendar member overlaps them directly and must declare it.

## 8. Treasury auction cycle in Treasury ETFs

- Statement: Treasury prices fall in the days before an auction and recover after it, though timing and size are announced in advance.
- Published: Lou, Yan and Zhang (2013) document the pattern and tie it to dealers' limited risk-bearing capacity and imperfect investor capital mobility.
- Data: Treasury ETF 1d bars (TLT, IEF and SHY appear as factor series in the sensitivity doc; confirm onboarding at spec time). The auction calendar is not captured: it would be a schedule series in the economic series layer (announcement date as availability time), a small public capture.
- Construction: Event-time series on a few ETFs; waits for todo 548 and the schedule capture.
- Horizon: 1 to 5 sessions around each auction.
- Looks: 1 to 2 series.
- Decay and crowding: Our inference: moderate; the mechanism is capacity-bound and ETF spreads are tiny, but ETF prices track futures that arbitrageurs already trade on this cycle.

## 9. Earnings announcement premium

- Statement: Names expected to announce earnings in the next window earn a premium over the window.
- Published: The premium is large, robust and tied to the volume surge around announcements; names with high past announcement volume earn the most (Frazzini and Lamont 2007).
- Data: Not stored. Earnings dates need EDGAR 8-K Item 2.02 acceptance timestamps (scouting doc, rung 0) or a vendor feed; predicted dates must be built from prior announcement dates only, since a projected date with no stored history is not point in time.
- Looks: 1 to 2 series. Ranked low only because the data does not exist yet.
- Overlap: Earnings-season conditioning was NOT_SHARPENED (0 of 249); that was a conditioning flag, not a name-level announcement premium, but it is a seen look; disclose.

## 10. Aggregate short interest as a world state

- Statement: High aggregate short interest predicts low market returns, so it may condition members as a world state.
- Published: Aggregate short interest beat many popular predictors in and out of sample, with annual R-squared of about 13% (Rapach, Ringgenberg and Zhou 2016).
- Data: Not captured; this is the published prior for the existing "short interest and short volume families" IDEAS bullet (FINRA direct, publication date as availability time). It needs shares outstanding by date too.
- Construction: One S7 state variant after a base book exists.
- Looks: 1.

## Declined, with reasons (Musk step 2)

- Pre-FOMC drift: Published: large pre-announcement equity returns from 1994 to 2011 (Lucca and Moench 2015), which essentially disappeared after 2015 (Kurov, Wolfe and Gilbert 2021). Our inference: the forward span would test a dead effect; do not spend a look. The calendar entry stays in the macro context layer as a schedule series for disclosure.
- Post-earnings announcement drift: Published: it began disappearing from non-microcap stocks in 2001 and was gone by 2006 (Martineau 2022), though later work disputes the full demise. Our inference: in a universe without microcaps the prior is close to zero; keep only item 9.
- Market timing from the stored macro series: Published: the standard equity premium predictors did poorly in sample and out of sample and were unstable (Welch and Goyal 2008); in a 2024 re-test more than a third of newer variables lost even in-sample significance (Goyal, Welch and Zafirov 2024). Our inference: credit, rate and funding series stay conditioning states (scoped regime states, macro context layer), never direct market-return predictors.
- Market-level intraday momentum: Published: the first half hour predicts the last half hour on the index (Gao, Han, Li and Zhou 2018). Already covered: `retail_immediacy_provision` found ordinary intraday momentum everywhere, and family 1b holds the residual form. Not re-proposed.

## Gates for any of these before a run

- The clean-data rule lifts and the S1 vintage is regenerated from the rebuilt tables.
- Each family's pre-registration states its universe as of t, the seen-data disclosures listed above, its look count, its costed construction for promotion, and a synthetic power check against StepM at the selection universe's size.
- Executable targets only, `ln(open[T+N+1] / open[T+1])` from `panel.forward_returns`; no hyper-traded clocks (nothing here trades faster than daily).

## Sources

| Source | Venue | URL | Used for |
|---|---|---|---|
| Amaya, Christoffersen, Jacobs, Vasquez (2015), Does realized skewness predict the cross-section of equity returns? | Journal of Financial Economics 118(1) | https://econpapers.repec.org/RePEc:eee:jfinec:v:118:y:2015:i:1:p:135-167 | item 5 |
| Ang, Hodrick, Xing, Zhang (2006), The cross-section of volatility and expected returns | Journal of Finance 61(1) | https://econpapers.repec.org/RePEc:bla:jfinan:v:61:y:2006:i:1:p:259-299 | item 2 |
| Bali, Cakici, Whitelaw (2011), Maxing out: stocks as lotteries and the cross-section of expected returns | Journal of Financial Economics 99(2) | https://econpapers.repec.org/RePEc:eee:jfinec:v:99:y:2011:i:2:p:427-446 | item 2 |
| Barroso, Santa-Clara (2015), Momentum has its moments | Journal of Financial Economics 116(1) | https://econpapers.repec.org/RePEc:eee:jfinec:v:116:y:2015:i:1:p:111-120 | item 6 |
| Bollerslev, Li, Zhao (2020), Good volatility, bad volatility, and the cross section of stock returns | Journal of Financial and Quantitative Analysis 55(3) | https://ideas.repec.org/a/cup/jfinqa/v55y2020i3p751-781_2.html | item 5 |
| Cederburg, O'Doherty, Wang, Yan (2020), On the performance of volatility-managed portfolios | Journal of Financial Economics 138(1) | https://econpapers.repec.org/RePEc:eee:jfinec:v:138:y:2020:i:1:p:95-117 | item 6 |
| Cooper, Gutierrez, Hameed (2004), Market states and momentum | Journal of Finance 59(3) | https://academicnewsletter.sufe.edu.cn/info/361185 | item 6 |
| Da, Gurun, Warachka (2014), Frog in the pan: continuous information and momentum | Review of Financial Studies 27(7) | https://econpapers.repec.org/RePEc:oup:rfinst:v:27:y:2014:i:7:p:2171-2218. | item 1 |
| Daniel, Moskowitz (2016), Momentum crashes | Journal of Financial Economics 122(2) | https://econpapers.repec.org/RePEc:eee:jfinec:v:122:y:2016:i:2:p:221-247 | item 6 |
| Frazzini, Lamont (2007), The earnings announcement premium and trading volume | NBER Working Paper 13090 | https://www.nber.org/papers/w13090 | item 9 |
| Frazzini, Pedersen (2014), Betting against beta | Journal of Financial Economics 111(1) | https://econpapers.repec.org/RePEc:eee:jfinec:v:111:y:2014:i:1:p:1-25 | item 2 |
| Gao, Han, Li, Zhou (2018), Market intraday momentum | Journal of Financial Economics 129(2) | https://econpapers.repec.org/RePEc:eee:jfinec:v:129:y:2018:i:2:p:394-414 | declined |
| Gervais, Kaniel, Mingelgrin (2001), The high-volume return premium | Journal of Finance 56(3) | https://ideas.repec.org/a/bla/jfinan/v56y2001i3p877-919.html | item 4 |
| Goyal, Welch, Zafirov (2024), A comprehensive 2022 look at the empirical performance of equity premium prediction | Review of Financial Studies 37(11) | https://econpapers.repec.org/RePEc:oup:rfinst:v:37:y:2024:i:11:p:3490-3557. | declined |
| Harvey, Mazzoleni, Melone (2025), The unintended consequences of rebalancing | SSRN working paper 5122748 | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5122748 | item 7 |
| Heston, Sadka (2008), Seasonality in the cross-section of stock returns | Journal of Financial Economics 87(2) | https://academicnewsletter.sufe.edu.cn/info/357254 | item 3 |
| Hou, Xue, Zhang (2020), Replicating anomalies | Review of Financial Studies 33(5) | https://econpapers.repec.org/RePEc:oup:rfinst:v:33:y:2020:i:5:p:2019-2133. | discount |
| Keloharju, Linnainmaa, Nyberg (2016), Return seasonalities | Journal of Finance 71(4) | https://econpapers.repec.org/RePEc:bla:jfinan:v:71:y:2016:i:4:p:1557-1590 | item 3 |
| Keloharju, Linnainmaa, Nyberg (2021), Are return seasonalities due to risk or mispricing? | Journal of Financial Economics 139(1) | https://econpapers.repec.org/RePEc:eee:jfinec:v:139:y:2021:i:1:p:138-161 | item 3 |
| Kurov, Wolfe, Gilbert (2021), The disappearing pre-FOMC announcement drift | Finance Research Letters 40 | https://ideas.repec.org/a/eee/finlet/v40y2021ics1544612320315956.html | declined |
| Lou, Yan, Zhang (2013), Anticipated and repeated shocks in liquid markets | Review of Financial Studies 26(8) | https://econpapers.repec.org/RePEc:oup:rfinst:v:26:y:2013:i:8:p:1891-1912 | item 8 |
| Lucca, Moench (2015), The pre-FOMC announcement drift | Journal of Finance 70(1) | https://econpapers.repec.org/RePEc:bla:jfinan:v:70:y:2015:i:1:p:329-371 | declined |
| Martineau (2022), Rest in peace post-earnings announcement drift | Critical Finance Review 11(3-4) | https://nowpublishers.com/article/Details/CFR-0122 | declined |
| McLean, Pontiff (2016), Does academic research destroy stock return predictability? | Journal of Finance 71(1) | https://ivey.uwo.ca/media/3775549/pontiff.pdf | discount |
| Novy-Marx, Velikov (2016), A taxonomy of anomalies and their trading costs | Review of Financial Studies 29(1) | https://www.nber.org/papers/w20721 | discount, item 5 |
| Novy-Marx, Velikov (2022), Betting against betting against beta | Journal of Financial Economics 143(1) | https://pure.psu.edu/en/publications/betting-against-betting-against-beta/ | item 2 |
| Rapach, Ringgenberg, Zhou (2016), Short interest and aggregate stock returns | Journal of Financial Economics 121(1) | https://econpapers.repec.org/RePEc:eee:jfinec:v:121:y:2016:i:1:p:46-65 | item 10 |
| Welch, Goyal (2008), A comprehensive look at the empirical performance of equity premium prediction | Review of Financial Studies 21(4) | https://econpapers.repec.org/RePEc:oup:rfinst:v:21:y:2008:i:4:p:1455-1508 | declined |

Verification note: every source was confirmed through search results (bibliographic record and abstract); full texts were not read. Figures quoted are abstract-level, except the Harvey-Mazzoleni-Melone 17 bp figure and the McLean-Pontiff 35% figure, which come from the authors' own summaries in secondary coverage, and the Gervais-Kaniel-Mingelgrin non-extreme-return point, which is from the working-paper version. Recheck each against the paper before it enters a pre-registration.
