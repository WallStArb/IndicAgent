# Political/Policy Regime — Idea

**Status:** Idea — not planned. Needs a Fable rigor pass before promotion to `docs/research/`.
Refreshed 2026-10-01: FRED plumbing now exists, a presidential-cycle section was added, and the
family this belongs to is mapped in `docs/ideas/signal-macro-context-layer.md`.
**Author:** Claude (Sonnet 5), interactive session, 2026-08-19. Data-source specifics (FRED
series IDs, current control-of-government facts) verified live via web search this session;
not independently backtested.
**Origin:** User idea, stated directly in conversation while discussing whether multiple
regime dimensions (rate, volatility, political) can be in effect concurrently rather than
one exclusive regime — asked specifically for a "business-friendly vs. non-business-friendly
government" concept that doesn't require an NLP/sentiment pipeline to measure.

---

## The hypothesis

Government policy posture (fiscal/regulatory direction, and the degree of uncertainty around
it) is a real, priceable macro regime dimension, separate from — and concurrent with — rate
regime and volatility regime. Two sub-concepts, deliberately kept apart rather than merged
into one composite label:

1. **Policy uncertainty** — how unpredictable near-term policy is, independent of direction.
   Elevated uncertainty (trade war escalation, government shutdown brinkmanship, contested
   election) has a documented dampening effect on investment/output and shows up in equity
   vol and risk-premia behavior even when nobody can say which direction policy will move.
2. **Policy direction / gridlock** — whether the current configuration of government
   (unified vs. divided control of White House/House/Senate) tends to produce more or less
   legislative output, and whether the party in power skews toward regulation-heavy or
   deregulation-heavy policy. This is a directional, structural fact, not a sentiment score.

Both are measurable today from existing, free, non-NLP data sources — no LLM/text pipeline
required, matching this project's "data quality over model complexity" principle.

---

## Data sources (verified 2026-08-19)

### 1. Economic Policy Uncertainty (EPU) Index — Baker, Bloom, Davis

- **General EPU, daily:** FRED series `USEPUINDXD` — news-based index over US newspapers,
  daily frequency, not seasonally adjusted, history back to 1985-01-01, current through
  2026-08-09 at time of check. Free, public domain (citation requested).
  https://fred.stlouisfed.org/series/USEPUINDXD
- **Categorical sub-indices, monthly:** e.g. `EPUTRADE` (Trade Policy Uncertainty) — same
  Baker/Bloom/Davis methodology, normalized to mean 100 over 1985-2010, derived from
  Access World News corpus of 2,000+ US newspapers. Multiple categories exist (fiscal policy,
  monetary policy, healthcare, national security, financial regulation, trade policy) —
  trade policy is the most directly tradeable given 2018-era and current tariff regimes.
  https://fred.stlouisfed.org/series/EPUTRADE ·
  https://www.policyuncertainty.com/categorical_epu.html
- **Global variant:** `GEPUCURRENT` (GDP-weighted global EPU) if a cross-market uncertainty
  read is ever wanted alongside the US-specific one.
- Origin paper: Baker, Bloom, Davis (2012/2016), "Measuring Economic Policy Uncertainty."

### 2. Partisan Conflict Index — Federal Reserve Bank of Philadelphia

- Monthly, news-search-based measure of the frequency of reported political disagreement
  among federal lawmakers (Washington Post, NYT, LA Times, Chicago Tribune, WSJ). History
  from 1981 (extended back to 1891 in the academic construction). Distinct from EPU — this
  measures *conflict/gridlock*, not uncertainty about outcomes.
  https://www.philadelphiafed.org/surveys-and-data/macroeconomic-data/partisan-conflict-index
- As of the most recent data point found this session (2025-07), the index was at its
  highest level since January 2019 — useful as a sanity check that the series is live and
  currently moving, not stale.

### 3. Divided vs. unified government — pure calendar lookup, zero judgment

- A lookup table keyed by date: which party controls the White House, Senate, House. This is
  a historical fact, not an estimate — changes only at inauguration (Jan 20) and when a new
  Congress convenes (Jan 3 in odd years) following an election.
- **Current state (verified 2026-08-19, pre-November-2026-midterm):** unified Republican
  government — House (~220-215 R), Senate (53-47 R, with 2 independents caucusing D), and
  the White House. This will change if either chamber flips in the November 2026 midterms;
  the lookup table needs a maintenance step after each election, not a live feed.
- No FRED/API dependency needed for this one — it's small enough to hand-maintain as a
  static table (a handful of rows per Congress/administration), unlike the two series above.

---

## What already exists in indicagent (verified live this session)

- **The regime architecture this would plug into is real and already built for exactly this
  shape of addition.** `market_regimes` (migration 171, renamed via migration 222) is keyed
  `(regime_group, tf, ts)` with `regime_label`/`regime_prob_vector` — one row per regime
  dimension per timestamp, computed independently. `services/cross_sectional_regime_model.py`
  iterates every enabled group in APR key `alpha.regime.groups` (a JSON array of
  `{name, tag_filter}` dicts) and writes group-scoped labels. Six groups currently defined
  (`equity`, `rates`, three commodity sub-groups, `fx`); adding a `policy` group is an APR
  config change plus a new module under `src/intelligence/regime_signals/` (see
  `commodity_momentum_ts.py`/`fx_dollar_carry.py` for the pattern) — **no schema migration
  required.**
- **FRED integration:** none existed when this was written (2026-08-19). It does since
  2026-10-01: `src/providers/fred.py` and `services/economic_series_writer.py` store FRED series in
  `economic_series_observation` (todo 480), and `USEPUINDXD` is a one-entry addition to the APR list
  `infra.economic_series.sources`, not new plumbing. The Partisan Conflict Index (a CSV from the
  Philadelphia Fed) is not FRED and still needs its own fetch.
- **A political/policy regime_group does NOT fit the existing `tag_filter`-based symbol
  routing model — confirmed by reading the actual routing code, not just inferred.**
  `tag_filter` does double duty in this codebase: it selects the peer set a group's label is
  *computed from* (cross-sectional breadth/dispersion across matched symbols' price data),
  and — via `ic_engine.py`'s `_resolve_symbol_routing` / `AmbiguousRegimeGroupError` (line
  275+) — it enforces that every symbol routes to **exactly one** `regime_group` for IC
  stratification; a symbol matching more than one enabled group is a hard failure by design,
  not an edge case. A `tag_filter: ["*"]` "ALL" group would make every symbol match both its
  own asset-class group *and* `ALL`, triggering that ambiguity error universe-wide. And even
  bypassing the check wouldn't fix the deeper mismatch: policy regime isn't computed from any
  symbol's price behavior — it's an exogenous macro series applied identically to everyone.
  **This is not a novel problem.** `FeatureVector` already has an established mechanism for
  exactly this shape of value — see `vix_z` (`schemas.py:482`, `"broadcast to every symbol
  on a given date"`, comment at `schemas.py:1467`) — computed once by
  `build_cross_asset_series()` in `src/intelligence/features/kernels/macro.py` and
  joined onto every symbol's row at the same cadence, never routed through
  `market_regimes`/`tag_filter` at all. Policy/EPU belongs in that lane, not in
  `market_regimes`. See the concrete sketch below.

---

## Concrete sketch: broadcast feature columns (not a `market_regimes` group)

Mirrors the existing `vix_z`/`flight_quality`/`yield_slope_z` pattern end to end — new fields
on `FeatureVector`, a new symbol-independent builder, broadcast-join at scoring time. No new
mechanism invented, no touch to `market_regimes`/`ic_engine.py`'s routing/ambiguity code at
all.

1. **Provider plumbing: done for FRED (see above).** The paragraph below is the original sketch,
   kept for the parts still open (the Partisan Conflict Index fetch). Original text: no FRED client
   existed; add a
   small fetch module — not a real-time `ib_async`-style stream, since FRED series update at
   most daily and this project's provider convention (`src/providers/ibkr.py`) is specific to
   IBKR — most naturally a `src/providers/fred.py` doing periodic pulls (a plain HTTP GET per
   series, FRED's API is free/keyed, low volume) of `USEPUINDXD`, `EPUTRADE`, and the
   Philadelphia Fed's Partisan Conflict Index CSV. Divided-government doesn't need a fetch at
   all — it's the static hand-maintained table from the Data Sources section above.

2. **New symbol-independent builder**, e.g. `src/intelligence/features/policy_regime_series.py`,
   structured like `build_cross_asset_series()`: iterate dates, look up (or forward-fill) each
   external series' latest value, z-score it over a rolling window, emit one record per date —
   never per symbol. This is where the frequency-mismatch problem (daily `USEPUINDXD` vs.
   monthly `EPUTRADE`/Partisan Conflict Index) actually gets resolved, in one place: forward-
   fill the monthly value forward day-by-day, but cap it — an APR-backed
   `feature.policy_regime.max_staleness_days` — beyond which the field goes `None` rather than
   silently carrying a months-stale number forward forever. Same "daily grain, broadcast to
   all timeframes by date" cadence contract `build_symbol_beta_series()` already documents
   (`kernels/macro.py` (`build_symbol_beta_series`)) — reuse it, don't reinvent it.

3. **New `FeatureVector` fields**, immediately adjacent to `vix_z`/`vix_level`
   (`schemas.py:482`), each carrying the same `"# broadcast to every symbol on a given date,
   like vix_z above"` comment convention already established at `schemas.py:1467`:
   - `policy_epu_z: float | None` — general uncertainty (`USEPUINDXD`)
   - `policy_trade_epu_z: float | None` — trade-policy-specific uncertainty (`EPUTRADE`)
   - `policy_partisan_conflict_z: float | None` — gridlock/conflict (Philadelphia Fed)
   - `policy_government_control: str | None` — categorical, not z-scored: `unified_r` /
     `unified_d` / `divided`. Because this is a fixed symbolic code (not a falsifiable
     numeric claim), it's a **CVR** touch point, not APR — register the 3 valid codes as a
     `controlled_vocabulary` group (`regime_hmm`-style) so `VocabularyDriftAuditor` catches
     any typo/drift, per the CVR spec in `docs/foundation/controlled-vocabulary-registry.md`.
   Adding these fields auto-registers under `concept_registry`'s `domain='feature'` lifecycle
   via `ic_engine.py`'s existing post-run hook — no new registration code needed, same as any
   other feature addition (per CLAUDE.md's UCR section).

4. **Nothing in `market_regimes`, `cross_sectional_regime_model.py`, or `ic_engine.py`'s
   routing/`AmbiguousRegimeGroupError` path needs to change.** These fields join into
   `feature_vectors` the same way `vix_z` already does today, and become ordinary interaction-
   primitive inputs (`policy_trade_epu_z × <existing signal>`) gated through the normal
   partial-IC significance test — same discipline as any other candidate feature, no special
   casing for "this one's political."

---

## Presidential-cycle seasonal (post-midterm window)

A third sub-hypothesis, kept apart from the two above: equity returns follow the four-year
election cycle, with the strongest stretch starting at the midterm election. It is a calendar
coordinate (years since the last presidential election), not a policy measurement, and needs
no external feed.

### Mechanism and confounds

The usual story is that the midterm resolves policy uncertainty (sub-concept 1), after a
weak midterm-year spring and summer. That makes three explanations that a raw "post-midterm
returns are high" comparison cannot separate:

1. A cycle effect proper (phase of the four-year cycle matters).
2. Uncertainty resolution (the same bounce follows any resolved shock, election or not).
3. Rebound after the midterm-year drawdown (plain short-horizon reversal, no politics).

Only (1) is a seasonal. Explanations (2) and (3) are already testable with existing features
(EPU, trailing drawdown), so the pre-registered spec conditions on the midterm-year drawdown
depth and reports the cycle term net of it.

### Descriptive look, 2026-10-01 (SPY daily, 2006-06 to 2026-09; one look at the vintage)

Five midterms: 2006, 2010, 2014, 2018, 2022. Election day to +6 months: +9.0, +14.0, +5.1,
+6.4, +8.0 percent (mean +8.5), all positive. Election day to +12 months: mean +8.2 against
an unconditional +10.2, so the effect is a 6-month one here, not a 12-month one.

The right comparison is the same calendar window in the other cycle years, not the
unconditional mean, because 2006-2026 is a strong-drift sample. Starting every year on 5
November: midterm years +7.4% (n=5), other years +4.2% (n=15, sd 9.7%). The difference of
3.2 points has a standard error near 5 points (t about 0.6). Unconditionally SPY is positive
over 6 months about 73% of the time, so "five of five" is roughly a 20% event by chance.

### Power

The sd of a 6-month SPY return is about 11 points. With the roughly 18 midterms since 1950
against 3 other-phase years each (SE of the difference near 3.1 points), the minimum
detectable excess at 80% power is about 8.7 points. A cycle effect of the size usually
quoted (3 to 4 points) is below that even on the full history, and adding names does not
help: the cycle is a time-series broadcast with one observation per four years. The test can
reject a large effect; it cannot confirm a small one. Treat the cycle as a conditioning
variable or risk flag for a combiner, never as a standalone book.

### Forward event

The 3 November 2026 midterm falls inside the unsearched forward span. A spec committed
(hash recorded) before that date turns the 2026-27 window into one clean forward
observation under the evidence framework. One event confirms nothing statistically, but
committing the spec costs almost nothing and the window cannot be recovered later.

### Pre-registered look, 2026-10-01 (written and committed before the run)

Owner-requested descriptive look on stored data. Not a research-runner verdict; counted as look 2 at
this hypothesis (look 1: SPY 2006+, above).

- **Data:** `YAHOO_GSPC_CLOSE` (S&P 500 price index, Yahoo, from 1927-12-30), price-only. Dividends are
  similar across years and cancel in the excess.
- **Event date:** election day E_y = the Tuesday after the first Monday in November, every year y from
  1928 to 2025 (a calendar rule; the market was closed on some election days, so the entry is the last
  close at or before E_y). Midterm years: even, not divisible by 4 (1930 to 2022, 24 years).
- **Window:** last close at or before E_y to the last close at or before E_y + 6 calendar months.
  Windows of different years never overlap.
- **Statistic:** mean 6-month log return over midterm years minus the mean over all other years
  (presidential and odd years), same calendar window.
- **Test:** one-sided permutation p-value, 100,000 random draws of 24 "midterm" years from all years
  (the year is the exchangeable unit). Also a bootstrap 95% interval over years for the difference.
- **Pass criterion, fixed now:** p < 0.05 and the difference > 0, and the same sign in both halves of
  the sample (1928-1976 and 1977-2025). Anything else is "not shown".
- **Reported, not tested:** the 12-month window and the four cycle-phase means (descriptive only).
- **Power, stated before the run:** with 24 midterm years against about 74 others and a 6-month return
  sd near 11 points, the smallest difference detectable at 80% power is roughly 7 points; the
  commonly quoted effect (3 to 4 points) would most likely read "not shown" even if real.

### Result of the pre-registered look (run 2026-10-01, after the spec above was committed)

| | Midterm years (24) | Other years (74) |
|---|---|---|
| Mean 6-month log return from election day | +10.0% | +1.9% |
| Windows positive | 21 of 24 | 65% |

Difference +8.1 points; permutation one-sided p = 0.0008 (100,000 draws, seed 20261001); bootstrap 95%
interval +3.0 to +12.9 points; halves 1928-1976 +9.6 and 1977-2025 +6.6. **The pass criterion is met.**
Descriptive only: 12-month +11.2% against +3.7%; 6-month means by cycle phase: midterm +10.0,
presidential +3.5, pre-election +1.7, post-election +0.6.

What the pass does and does not mean:
- **Literature selection.** This effect was chosen because it is famous (the presidential cycle was
  popularized from the late 1960s). Of the many calendar effects people have tried, the surviving ones
  get published, and a pre-registration cannot remove that selection. The p-value is conditional on
  having picked this hypothesis; treat it as much weaker than 0.0008.
- **After publication.** The 1977-2025 half is mostly after the effect became widely known and is still
  +6.6 points, which argues against pure data mining; it was not separately tested.
- **One event every four years.** As a strategy it is about 24 trades in 98 years; it is a conditioning
  input (for example, a cycle coordinate or a midterm-window flag in a combiner), not a book.
- **Not a verdict.** A research-runner attempt is still required before any use, counted against the
  vintage, with the forward window below as its unsearched confirmation.

**Forward observation.** The rule dates the next midterm 2026-11-03, so the committed spec already
defines the 2026 window (close at or before 2026-11-03 to close at or before 2027-05-03). Its result is
recorded here in May 2027, unchanged by anything learned before then.

### Window scan, look 3 (exploratory, run 2026-10-01 after the result above)

Looks 2 and 3 and the robustness rows reproduce exactly from `scripts/research/midterm_cycle_looks.py`
(`look2`, `look3`, `robust`; seeds fixed in the script).

Owner-requested, not pre-registered, and no evidence beyond look 2: it asks only where in the cycle the
excess sits. Same data and event rule; 24 cells (entry 3, 2, 1 months before election day, on it, 1 and
2 months after; horizon 3, 6, 9, 12 months). Each cell is the midterm-minus-other-years difference in
log return over that cell's own horizon. Family-wise p compares each cell's permutation z against the
maximum z over all 24 cells (20,000 draws, seed 20261002).

| Entry | 3 months | 6 months | 9 months | 12 months |
|---|---|---|---|---|
| 2 months before | +3.2 | +8.1 (0.044) | +10.2 (0.059) | +10.8 (0.029) |
| 1 month before | +3.8 | +9.3 (0.008) | +12.7 (0.007) | +11.0 (0.054) |
| Election day | +4.0 | +8.1 (0.015) | +8.3 (0.047) | +7.4 |
| 1 month after | +4.9 (0.014) | +7.0 (0.065) | +7.6 (0.051) | +6.4 |

Points of log return over the cell's horizon; family-wise p shown where below 0.07. Rows for 3 months
before and 2 months after are omitted.

Monthly increments (midterm minus other years, points): negative through the midterm summer (-3.3 five
months out, -1.6 three months out), +2.7 in the month before the election, positive in each of months 1
to 6 after it (about +8 in total), +2.4 in month 8, flat to negative in months 9 to 12.

Robustness (seed 20261003):

| Cell | Mean excess | Median excess | Leave-one-out range | Drop top 3 midterms |
|---|---|---|---|---|
| Election day, 6 months (committed) | +8.1 | +8.6 | +7.6 to +9.3 (worst: drop 1942, p 0.002) | +6.5 |
| 1 month before, 9 months (best) | +12.7 | +11.8 | +11.6 to +14.5 (worst: drop 1974, p 0.002) | +9.9 |
| 1 month before, 6 months | +9.3 | +8.9 | +8.6 to +10.6 | +7.2 |
| 2 months before, 12 months | +10.8 | +12.2 | +9.8 to +13.4 | +8.1 |

No single cycle carries the result, and the median matches the mean, so it is not a few outlier years.

Reading:
- The excess sits from about a month before the election through roughly six to nine months after,
  following a weak midterm summer. The breadth across cells is expected rather than confirming: adjacent
  cells share most of the same 24 return paths. The evidence is look 2's p and the robustness rows.
- The best cell (1 month before, 9 months) is the maximum of 24 searched cells and must not replace the
  committed definition. The election-day 6-month window stays the definition, and the 2026 forward
  window above is unchanged.
- For use as an input, encode the cycle as a `_sin`/`_cos` pair on the four-year cycle (the calendar
  primitive form) rather than a hand-picked window, and let the combiner fit the shape walk-forward
  inside a counted attempt. Our own panel covers about six cycles, so that fit has little to learn from;
  this is a slow prior, low priority under build first.

### Spec to pre-register

- Outcome: SPY (and one broad equal-weight ETF, RSP) total return, election day to +6
  months, minus the same-window return in the other three cycle years.
- Control: midterm-year drawdown depth (peak to the 30 September close) as a covariate.
- Null: block bootstrap over years, never one draw per event.
- Data: pre-2006 index history as owner-approved reference data (todo 428 precedent);
  without it the spec is refused as underpowered.
- Feature, if the test survives: `presidential_cycle_sin`, `presidential_cycle_cos`
  (period four years) beside the other cyclical coordinates in
  `docs/research/signal-temporal-atomic-primitives.md`. The coordinate spans the cycle and
  does not select the post-midterm point.

---

## Open questions / cautions before promotion to `docs/research/`

1. ~~Does this become a `market_regimes` group or a plain feature?~~ **Resolved above** — plain
   broadcast feature column, following the `vix_z` precedent. Not a `market_regimes` group.
2. **Frequency mismatch / staleness cap.** Resolved in *design* above (forward-fill the monthly
   series with an APR-backed max-staleness cutoff), but the actual cutoff value is unset and
   unvalidated — this is exactly the kind of design choice that has burned this project before
   (see `regime_writer.py` HMM parameter-lookahead history) if the cap is picked carelessly or
   skipped.
3. **Don't cross with other regime dimensions into one joint label.** Per the earlier
   discussion in this session: keep policy/uncertainty features independent and let each
   interaction with existing signals get tested individually for incremental value, rather
   than pre-combining into a sparse multi-way bucket.
4. **Divided-government lookup needs an explicit maintenance trigger**, not a "set once and
   forget" table — flag it to get updated after the November 2026 midterms regardless of
   what else is in flight then.
5. **Null-arm control applies here too.** Per the 2026-08-08 standing rule (any future HMM/
   regime candidate must clear a scrambled-data null-arm control before its numbers are
   trusted), this candidate is not exempt just because the inputs are simple/interpretable —
   and as a broadcast feature it should also clear the existing "broadcast-feature
   significance-test gap" concern already open in todo 204 before being trusted at face value.
6. **This has not been scoped against a specific target (IC on which return horizon, which
   instruments) or run through Stage 1 mechanism validation.** It is a data-source survey,
   not a tested candidate.
