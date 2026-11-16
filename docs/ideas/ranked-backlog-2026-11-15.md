# Ranked backlog beyond the published-prior shortlist - Idea

**Status:** Idea, 2026-11-15. Nothing queued, registered or computed. No real-data number exists for any item here; the clean-data rule (E21) holds until the step 7 data gate passes. Each item enters only as a pre-registered family member or disclosure, counted under E18.
**Author:** indicagent-65 for the lead (indicagent-52), 2026-11-15. Docs only; no code and no corpus reads.
**Scope:** every backlog idea that is not one of the ten items of `docs/ideas/signal-published-prior-shortlist.md`, taken from `.planning/IDEAS.md`, `docs/ideas/`, the research ledger (`docs/research/construction-verdict-ledger.md`, sections 1 to 5) and the stage 2 universe docs. Alpha ideas keep their rows in the ledger; this doc adds a ranking and a disposition, and changes no verdict.

## How to read this

- Ranking rule: the shortest path to a counted test. An item ranks high when its design or kernel exists, it runs on 1d data the stage 2 universe provides, it adds few series to the E18 selection universe, and it needs no uncaptured data and no unbuilt construction.
- Looks are series added to the selection universe: members times declared horizons, each measured cell counted. A horizon of 21 or more sessions waits on todo 547 (the horizon-tied HAC lag), so those looks are listed as "later".
- Data facts used (stage 2 preregistration, `docs/plans/2026-11-13-stage2-universe-preregistration.md`, adopted 2026-11-13): 1d for every member from 2003-09-10, about 4,150 members at a typical month-end (2,947 to 6,041), 16,045 securities ever; two panels for every test (point-in-time universe and constant core). The 5m tier is a nested top liquidity tier whose size is set by an amendment that is still a draft (`docs/plans/2026-11-15-stage2-5m-tier-and-intraday-universe.md`). Caveat for every 1d item: the 2003 to 2007 close convention needs a third witness (todo 610) before those years feed a daily test.
- Nothing here retires an owner idea. Where an item is not ranked it is marked waiting or parked with the reason, and the owner can reopen it.

## Ranked top five

| Rank | Item | Ledger row | Data | Looks | Path to a counted test |
|---|---|---|---|---|---|
| 1 | Residual short-term reversal | Family 4, todo 423 | 1d members, S1 residuals | 6 series (R1 to R3 on two panels), already inside the daily residual family's 10 | Already registered as R1 to R3 in `docs/plans/2026-10-27-daily-residual-momentum-reversal-prereg.md`; waits on amendment A1 (universe) and the data gate, no new prereg |
| 2 | 52-week-high anchoring | Family 9 | 1d, `panel.total_return` | 1 member, 2 series at h5 | Draft prereg: `docs/plans/2026-11-15-family9-52week-high-prereg-draft.md` (E26) |
| 3 | Industry momentum and daily sector lead-lag | Family 11 remainder, todo 441 | 1d plus the point-in-time classification | 3 at h5 | Registration beside the residual-momentum prereg; needs classification coverage checked for dead names |
| 4 | Dividend month premium and ex-dividend day pricing | Corporate-action row, todo 428 | Stored dividend events; covered names only | 1 to 2, monthly so later | Needs todo 547 for the monthly form and a coverage-restricted panel |
| 5 | Survivorship measured, not assumed | `.planning/IDEAS.md` (2026-11-09) | Stage 2 membership table | 0 selection looks if it never feeds StepM | Rides on whichever family runs first; a disclosure, not an edge test |

### 1. Residual short-term reversal

- Correction 2026-11-15: this item is already registered. Todo 423 folded into the daily residual family as R1 (5 sessions), R2 (21 sessions) and R3 (5 sessions with a one-session skip) at h5, with the B1 holdout of the screen's names and its disclosure in section 6; B2 size cells have run on the stale S1 vintage (todo 547). The remaining path is A1 (stage 2 universe) and the data gate. The rest of this entry stands as the ledger check.
- Ledger check: design only. A seen-data hint exists: the 2026-09-13 TSMOM screen found a consistently negative `ctf_momentum` IC that is short-term reversal territory (ledger section 5), so the registration must disclose it and exclude that screen's 231 names and window from its evidence, which the ledger row already requires. No recorded null.
- Musk step 1: the requirement is "the cheapest S1 residual member that shows whether the residual cross-section carries a short-horizon edge at all"; it doubles as the control against which residual momentum is read. Keep, and declare overlap with family 11 so one reversal edge is not counted twice.
- Data: 1d for the point-in-time universe and the constant core. Published (as cited in todo 423, not rechecked here): Jegadeesh 1990 and Lehmann 1990. Our inference: the effect is largest in small, illiquid names and turns over fastest, so the costed construction, not the IC, is the binding question; the stage 2 floor of $1M median dollar volume makes that sharper.
- Looks: 3 at h5. The construction carries the highest turnover in this list, so promotion needs the todo 553 spread kernels before any costed claim.

### 2. 52-week-high anchoring

- Ledger check: design only. Adjacent seen data to disclose: the pooled corpus IC look (section 5) found `high_52w_dist` at -0.058 at 1d h10 with 0 or 1 of 227 names FDR-passing, the opposite sign to George and Hwang (2004), and the cross-sectional `bars_since_high_fast_xs_ls_h5` verdict is DEAD (net-negative, 2026-09-11). The registration states the expected sign before any run.
- Musk step 1: the requirement is one test of whether price position inside its 52-week range predicts beyond residual momentum; the seven pending members collapse to one (the George and Hwang ratio over 252 sessions) because the corpus shows they are one mechanism, and the stored columns are not read (price-only, partial-window warmup).
- Data: 1d with `panel.total_return`; a price-only high manufactures a false signal on high-yield names (the guard in `tests/unit/research/test_dividends.py`).
- Looks: 1 member, 2 series (primary and core panels) at h5. Overlap with item 1 and shortlist item 1 is high; StepM's joint bootstrap prices it.

### 3. Industry momentum and daily sector lead-lag

- Ledger check: design only (todo 441, corrected 2026-11-15: the panel is the stage 2 universe, not 931 names; its sector lead-lag leg is the 5m or 15m family 3, while ledger family 11 names a daily sector lead-lag). Residual momentum is the section 2 reopen of the TSMOM FAIL and is the base of shortlist item 1; the pairs-based forms are DEAD and closed, which this item does not touch.
- Musk step 1: the requirement is "does industry membership carry information the S1 sector residual removes"; delete the lead-lag leg first if the classification does not cover dead names, since a lead-lag between 11 sectors adds 1 to 2 series and no breadth.
- Data: 1d plus `ClassificationService`. Open check before registration: the stage 2 docs do not state that dead-name securities get a point-in-time classification, so industry momentum may be limited to classified names.
- Looks: 3 at h5.

### 4. Dividend month premium and ex-dividend day pricing

- Ledger check: idea, not queued (added 2026-10-12). Overlaps families 5 and 6 on calendar structure and must say so.
- Musk step 1: the requirement is one monthly indicator (expected dividend month from the name's own past payments) against the S1 residual; ex-dividend day pricing is a day-level pricing effect with too few series and too much cost sensitivity to rank here, so it stays a disclosure item.
- Data: `dividend_events_reconciled` and the split history. Outside `dividend_event_coverage` dividends are unknown, never zero, so the panel is the covered names, which is a survivor-leaning subset; the registration discloses that. Monthly horizon waits on todo 547.
- Looks: 1 to 2, later.

### 5. Survivorship measured, not assumed

- Ledger check: not a ledger family. The stage 2 design already separates a universe effect from a feature effect with its two panels; this adds a third panel, current names only, on one family.
- Musk step 1: the requirement is a number for how much survivors-only inflates or deflates an IC, so the survivorship caveat becomes a measurement. It adds no hypothesis, so it is a disclosure that never selects anything.
- Data: the stage 2 membership table (`universe_membership`, held landing) and the current-name set. No new compute kernel; the same member cells are read on a subset of the IC panel.
- Looks: counts no selection look as long as it never feeds StepM or a promotion; the registration of the family it rides on must say so.

## Not ranked

Each row is checked against the ledger. "Waiting" means the item stands and has a named blocker; "parked" means no near path, with the reason; no row is retired.

| Item | Ledger check | Musk step 1 on the requirement | Data on the stage 2 tiers | Disposition |
|---|---|---|---|---|
| Period-end marking (family 5) and period-end flows (family 6), both owner-proposed | Design only | Is there enough power in a few dozen period ends per year to test anything? A power check decides | 1d, calendar events | Waiting on the power check |
| Index reconstitution (family 7) | Held | Requires a point-in-time event history | No source | Parked: no event history |
| Options expiry flows (family 8) and quarterly seasonality with OPEX risk-off | `dealer_hedging_flow` is DEAD (2026-08-07/08); open-interest capture declined by the owner 2026-09-25 | The calendar form is already tested and dead | No open interest | Parked: prior verdict plus no data |
| Intraday volume and order-flow members (family 10, `up_vol_ratio_fast`, `ofi_z`, `obv_z`, `mfi_slow`) | Design only; weak per-feature support | Needs its own step 0 (residual n_eff at 5m and 15m); the daily volume-shock part is shortlist item 4 | 5m tier only | Waiting on the 5m tier |
| `generated_family` grammar (family 12, todo 440) | Design only | Every grammar expansion is a counted look, so run it after the named families set the baseline | 1d, in-fold selection | Waiting on family 11 S1 target |
| ETF-to-constituent lead-lag (family 3) | Design only; never run | Needs a constituent map and 5m to 1h clock; conflicts with the no hyper-trading rule at fast horizons | 5m tier | Parked: heavy build for a fast clock |
| Extended-hours tape family (owner suggestion 2026-10-10) | Untested; must position against family 2's overnight leg | Kernels read the archived extended bars; no canonical grid | Raw extended bars, 5m tier names | Waiting on the tier and a raw-bar kernel path |
| Trade count and average trade size features | Never stored (`ohlcv_raw` holds OHLCV only) | Capture is a schema change before any test | Needs capture first | Parked: no stored data |
| Overnight versus intraday (family 2) | Evidence run 2026-10-29 recorded no member significant in the preregistered direction; the owner ruled it not evidence (incomplete data) and testing restarts from scratch | Re-register on the rebuilt table; it is a rerun, not a new idea | 1d and 5m | Waiting on the data gate |
| Style-spread factor momentum and the participation state | Overlaps the S7 combiner; needs the time-series construction (todo 548) | Few series, but a different construction | ETFs on 1d | Waiting on todo 548 |
| Equity stat arb: PCA residual reversion, Kalman and OU spreads | `statistical_factor_residual` and `cointegrated_pairs_residual` are DEAD; the owner reopened the spread form 2026-10-28 | Residual reversion on a daily clock is item 1 in its simplest form | 1d | Folded into item 1; spread forms wait on todo 559 |
| Fundamental factor residuals | No fundamentals source stored | Needs the as-reported source first | None | Parked: no data |
| Short interest and short volume (FINRA) | Uncaptured; the aggregate form is shortlist item 10 | Capture first, with publication dates | None yet | Waiting on a capture decision |
| SEC filing text features | Not queued | New data class and a text model | None yet | Parked: new data class |
| Microstructure spreads and Amihud illiquidity as features | Spread kernels landed (todo 553); the frictions category fails most replications under value weights | The kernels serve costs first; a feature test adds series in the weakest published category | 1d, 5m tier | Parked as a feature; used for costs |
| Cross-sectional relative-value features (`momentum_rank_z`, `volatility_rank_z`, `volume_rank_z`) | Never computed | A cross-sectional rank is a transform the S1 panel already applies, so the stored column adds no series | 1d | Parked: likely redundant; confirm in todo 558 |
| Small additions (permutation entropy, sub-bar path summaries, dollar bars) | Never computed; dollar bars change the sampling | Each is a candidate base feature for the scouting process (todo 603) | 5m tier | Waiting on the scouting process |
| Rolling volume profile at 1d | Suppressed for 1d, never reviewed | Needs the 1d columns first | 1d | Waiting on columns |
| Regime-conditioned combiner variants and scoped regime states (owner ideas) | Not queued, unreviewed | Needs a base book and a rigor pass | 1d | Waiting on a base book |
| Macro context layer and the political and policy regime (post-midterm seasonal) | One preregistered look on S&P 500 1928 to 2025 (24 midterms) exists; macro point in time is todo 482 | Few independent events limit power | Macro series | Waiting on todo 482 |
| Convolutional raw-window model, TimesFM features, ML on residuals, nonlinear combiner N1 | N1 inconclusive; others untested and flagged skeptical | Model classes, not hypotheses; they enter as S7 variants after a baseline | 1d | Parked until a baseline book exists |
| Sequential confirmation of a book, book-stage VaR and ES, equal-risk-contribution variant | Governance and construction, not edge | They matter only once a book exists | Forward span | Waiting on the first book |
| Evolutionary APR optimization, agentic research loop, self-evolving harness | Gated or parked in their docs | Not an edge source | None | Parked per their own docs |
| Futures, roll features, continuous contracts | Tabled by the owner | Conditions in `docs/ideas/futures-in-the-research-universe-tabled.md` | None | Parked by the owner |
| Orderflow setups, news sentiment, DerivAgent, options-derived ideas (implied borrow, put ladder) | Need tick, news or options data none of which exists | No data | None | Parked: no data |
| v2.x era product ideas in `.planning/IDEAS.md` (TradeAgent, QualAgent, SaaS, agent patterns) | Written against the removed I1 to I8 tier | Not research hypotheses | None | History, not backlog |

## Gates before any of these runs

- The data gate passes (step 7 D1 verified) and the stage 2 membership table is shown to the owner.
- Each registration states its universe as of t, the seen-data disclosures above, its look count and a synthetic power check against StepM at the selection universe's size.
- Executable targets only (`panel.forward_returns`), daily clock or slower.
