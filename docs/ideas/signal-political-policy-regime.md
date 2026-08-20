# Political/Policy Regime — Idea

**Status:** Idea — not planned. Needs a Fable rigor pass before promotion to `docs/research/`.
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
- **No FRED integration exists anywhere in the codebase** — a repo-wide check for
  `fred.stlouisfed`/`FRED_API`/`fredapi` returns zero hits. This would be new provider
  plumbing, not a reuse of an existing ingestion path.
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
  `build_cross_asset_series()` in `src/intelligence/features/cross_asset_series.py` and
  joined onto every symbol's row at the same cadence, never routed through
  `market_regimes`/`tag_filter` at all. Policy/EPU belongs in that lane, not in
  `market_regimes`. See the concrete sketch below.

---

## Concrete sketch: broadcast feature columns (not a `market_regimes` group)

Mirrors the existing `vix_z`/`flight_quality`/`yield_slope_z` pattern end to end — new fields
on `FeatureVector`, a new symbol-independent builder, broadcast-join at scoring time. No new
mechanism invented, no touch to `market_regimes`/`ic_engine.py`'s routing/ambiguity code at
all.

1. **New provider plumbing (the one genuinely new piece).** No FRED client exists yet. Add a
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
   (`cross_asset_series.py:303`) — reuse it, don't reinvent it.

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
