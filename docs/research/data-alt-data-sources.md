# AlphaEngine — Alternative Data Extension

**Date:** 2026-06-23
**Status:** idea - adopted into ROADMAP as **Phase 154 "Alternative Data Vectors"** (Deferred / Independently-Gated section)
**Milestone:** Phase 154, independently-gated; not blocking v4.0 *(corrected 2026-07-06, Fable 5 - was "post-v3.0 Phase A/B," stale: Phase A/B completed 2026-06-30/2026-07-01 and the 2026-07-04 renumbering placed this work at Phase 154)*
**Last Updated:** 2026-07-06 (Fable 5 review pass against live schema, `ic_engine.py`, and ROADMAP)

**Review pass (2026-07-06, Fable 5):** first review of this doc; verified against live code and
psql, not just design-read. Four findings, corrected inline below with *(Fable's revision)* markers:

1. **The proposed `alt_feature_vectors` table is superseded by a precedent this doc predates.**
   Phase 140.5 P5 (completed 2026-06-26, three days after this doc was written) built
   `context_features` - a live, populated long/narrow table keyed `(feature_date, feature_name,
   symbol)` with a `source` check constraint, which `ic_engine.py` already joins (line ~845) with
   its own cadence-calibrated N gate (`alpha.ic.min_obs_daily_features`, APR value 1000). The
   codebase already solved "slower-cadence non-OHLCV features measured by the same IC engine,"
   and the answer was narrow-and-keyed, not wide-and-nullable. The Architectural Implication
   section below is rewritten around that precedent.
2. **The "separate IC gate per data source" idea was named but not designed** - and the doc's own
   N math (5,000 daily rows vs 20,000-bar gate) conceals a worse problem it walked past:
   fill-forwarded quarterly values give ~80 *independent* observations per symbol per 20 years,
   not 5,000. Rows are not observations. Concrete gate design now specified in Key Risk below.
3. **Qualitative timestamp risk was named, not mitigated.** "Timestamp discipline" is a wish;
   the section now specifies the mechanism (immutable event table with `published_at` +
   `received_at`, materialized `effective_ts` = first bar open strictly after both).
4. **All three `docs/research/` See Also links were broken** (docs moved to `docs/research/archive/`);
   fixed. `catalog.md`'s entry for this doc also pointed at the pre-rename filename; fixed in the
   same pass.

**Follow-up owed to ROADMAP (not applied 2026-07-06 because ROADMAP.md has uncommitted edits from
a concurrent session):** Phase 154's ALTDATA-01 requirement still specifies the single
`alt_feature_vectors` table inherited from this doc's original text. When Phase 154 is planned,
ALTDATA-01 should be updated to the two-shape design below.

---

## Core Insight

AlphaEngine is data-agnostic by design. The IC methodology has one requirement: a numeric feature value at time T with a causally-known forward return at T+N. The measurement apparatus - Spearman IC, IC Sharpe, FDR correction, regime conditioning, effective-N - operates on a matrix of `(symbol, tf, ts, feature_value)` rows. The source is irrelevant.

The question per data type is not "can AlphaEngine handle it" but "what are the ingestion and alignment constraints."

*(Fable's revision, 2026-07-06:)* One precision the original overstated: "effective-N handles
redundancy between price-derived and alt-data features automatically" is wrong as written.
Effective-N (stride subsampling, `alpha.ic.subsample_min_stride`) corrects for *serial*
dependence within one feature's observations. *Cross-feature* redundancy is handled by a
different mechanism: Phase 140's collinearity clustering plus EnsembleBuilder's Ledoit-Wolf
covariance. Both apply to alt-data features once they enter measurement, but neither is
automatic for a new source - a flows feature that is 0.95-correlated with `rel_volume` must
enter the same collinearity clustering pass, or the ensemble double-counts it.

---

## Data Types

### Flows

Options net delta, dark pool %, institutional order imbalance. Already intraday numeric values. IC measured at 5m/15m TF same as existing features. Lowest-friction extension and almost certainly has measurable IC on rate-sensitive ETFs.

*(Fable's revision, 2026-07-06:)* the original said "slot directly into `feature_vectors` as new
columns." That breaks a DAG invariant: `FeatureVectorWriter` is the sole writer of
`feature_vectors`, and flows arrive from a different provider on a different ingestion path. Two
writers updating the same rows means races and silently partial rows. Correct shape: a dense
sibling table `flow_vectors (symbol, tf, bar_ts, ...)` with its own `BaseWriter`, joined by
`ic_engine` on the bar key - same cadence, same key, one writer per table. See Architectural
Implication.

### Fundamentals

EPS surprises, P/B, earnings revision ratios. IC framework is exactly how Barra and Axioma measure factor quality - this is the canonical use case. Constraint: fundamentals update quarterly, so IC is only meaningful at daily TF with fill-forward "as-of" values. Requires a `fundamental_snapshots` table keyed on `(symbol, report_date)` and a fill-forward join at daily resolution.

*(Fable's revision, 2026-07-06:)* two corrections the Barra citation actually implies but the
original missed. First, **per-symbol time-series IC on quarterly data is statistically dead on
arrival**: 20 years of quarters is ~80 independent observations per symbol; no gate calibration
rescues that. Barra factor IC is *cross-sectional* - rank correlation across the universe at each
rebalance date. That is the correct measurement here too: cross-sectional rank IC across the
80-symbol universe per report season, ~80 quarters × 80 symbols of pooled observations. The
POOLED-strata machinery `ensemble_trainer` already trains on (cross-sectional `is_pooled=true`
strata in `feature_ic_scores`) is the existing home for this - fundamentals should *only* be
measured in cross-sectional strata, never per-symbol. Second, **point-in-time discipline**:
vendor fundamentals are routinely restated. Store as-reported values keyed on the public release
timestamp, never the fiscal period end, or the corpus quietly trains on data that did not exist
at the bar. This is the same causality bug as the Qualitative section's, at quarterly cadence.

### Qualitative

News sentiment, transcript tone, analyst language. Requires a conversion step first: NLP pipeline produces a numeric score per event (VADER, FinBERT, or LLM-graded tone score). Once numeric, IC measurement is identical. Hard problem: look-ahead in timestamps - news published after-hours must not bleed into the bar it followed. Timestamp discipline is more important than the NLP choice.

*(Fable's revision, 2026-07-06:)* "timestamp discipline" is a named risk, not a mechanism. The
concrete design, mirroring `ic_engine`'s purge/embargo logic on the forward-return side:

1. **Immutable raw event table** `alt_events (event_id, symbol, published_at, received_at,
   payload, score, scored_at)`. `published_at` is the provider's claim; `received_at` is when our
   ingestion first saw it. Providers restate timestamps and backfill "history" with corrected
   metadata - `received_at` is the only timestamp we can prove, and for any event ingested from a
   historical dump (not live), the causal timestamp is unknowable and the event is
   **training-ineligible for the bars near it** rather than trusted.
2. **Materialized effective timestamp:** `effective_ts` = first bar open strictly *after*
   `max(published_at, received_at)`. The event's score attaches to bars at `effective_ts` and
   later, never earlier. After-hours news attaches to the next session's first bar by
   construction, not by convention.
3. **The join direction is the contract:** feature value at bar T may only use events with
   `effective_ts <= T`. Note that today's `ic_engine` context-features join is same-day
   (`DATE(fv.bar_ts) = cf.feature_date`) and its causality rests on an unstated ingestion
   convention that daily values are knowable before the open; the alt-data extension must make
   that convention an explicit effective-date contract at the materialization step, because news
   violates it by default where FRED series mostly do not.

With that mechanism the NLP choice really is secondary, as the original claimed.

### Kalshi

Prediction market probabilities. Already bounded [0,1] and update continuously. Two uses:

1. **Direct IC** - measure IC between Kalshi event probability and corresponding ETF forward returns (e.g., "Fed +50bps" probability vs. TLT 5d return).
2. **Regime conditioning** - Kalshi probability defines a regime stratum; compute IC per stratum separately. "Momentum IC in low-Fed-risk regimes vs. high-Fed-risk regimes" is a testable stratification that price-only features cannot provide. Arguably more powerful than direct IC use.

*(Fable's revision, 2026-07-06:)* use 2 now has a designated architectural home this doc
predates: the `StratificationDimension` contract (`docs/research/regime-multi-regime-layer.md`,
v3.15 Phases 144-145). A Kalshi probability bucket is precisely a new conditioning dimension -
it should be implemented as a `StratificationDimension`, not as bespoke stratification logic
inside `ic_engine`. This also sharpens the sequencing: Kalshi-as-conditioning should wait for
v3.15 to land the contract, which is consistent with its position behind Flows in the build
order. Direct IC (use 1) additionally needs the resolution-cycle N-gate caveat below - a market
that resolves in 3 months contributes one independent macro observation per cycle, not one per
tick.

---

## Architectural Implication

*(Rewritten 2026-07-06, Fable 5. Original proposed "a second table `alt_feature_vectors` (or
additional nullable columns) keyed on `(symbol, ts, data_source)`." Both options are wrong, for
different reasons, and the codebase has since built the pattern that replaces them.)*

**Rejected: nullable columns on `feature_vectors`.** Quarterly values duplicated across ~78
5m bars/day is exactly the artificial-autocorrelation disease Phase 140.5 P5 excised from
`feature_vectors` by *removing* daily-cadence macro columns into `context_features`. Re-adding
slower-cadence data as wide columns reintroduces it, plus a NULL-semantics trap: a NULL flows
column cannot distinguish "source not yet ingested" from "no data exists for this bar," which is
a silent-wrong-answer generator. And every new source becomes an `ALTER TABLE` on a 10M-row
hypertable.

**Rejected: one grab-bag `alt_feature_vectors`.** A single table spanning 5m flows, quarterly
fundamentals, continuous Kalshi snapshots, and event-driven news scores has no honest primary
key: bar-keyed rows are dense for flows and 99% absent for fundamentals; event-keyed rows are
wrong for flows. One table pretending these cadences are one thing is the wide-table mistake with
an extra join.

**Adopted: two shapes, chosen by cadence, both already precedented in the codebase.**

1. **Bar-cadence sources (flows):** dense sibling table per source family, keyed
   `(symbol, tf, bar_ts)` - e.g. `flow_vectors` - written by its own dedicated `BaseWriter`
   (one writer per table, DAG invariant 3 preserved), joined by `ic_engine` on the bar key
   exactly as `forward_returns` is today. Adding a source = new table + new join; no ALTER, no
   NULLs, no second writer on `feature_vectors`.
2. **Sub-bar-cadence sources (fundamentals snapshots, Kalshi snapshots, materialized qualitative
   scores):** extend the existing `context_features` pattern - long/narrow,
   `(feature_date, feature_name, symbol)` key (per-symbol support already exists; market-wide
   rows use `symbol = ''`, which fits Kalshi macro probabilities as-is), `source` check
   constraint extended (`'kalshi'`, `'fundamental'`, `'news'`), plus the effective-date contract
   from the Qualitative section formalized at materialization. Event-driven sources keep their
   immutable raw event table upstream and materialize into this layer; the raw table is the audit
   trail, the narrow table is the measurement surface. `ic_engine` already reads this shape with
   one-observation-per-day extraction (`DISTINCT ON (DATE(bar_ts))`) - the mechanism generalizes
   to one-observation-per-update-event.

**4-question gate (CLAUDE.md):**
1. *10x volume?* Yes - per-source tables scale by addition; the narrow table grows linearly in
   (sources × update events), which is small by construction for sub-bar cadences.
2. *What fails silently?* The three leak vectors are all timestamp bugs: fill-forward rows
   counted as observations, restated fundamentals, news attached to the preceding bar. Each has
   an explicit mechanism above; the effective-date contract is the single load-bearing invariant
   and should be enforced at write (check constraint or materializer assertion), not by reviewer
   vigilance.
3. *DAG holds?* Yes - each source family gets provider → ingestion daemon → Kafka →
   dedicated writer → its table; `ic_engine` only ever joins (reads). The rejected
   new-columns-on-`feature_vectors` option is the one that breaks it.
4. *What manual step does this eliminate?* None - this is signal-surface expansion, not
   automation, and it *adds* operational surface (new providers, new failure modes). That is why
   its Phase 154 independently-gated placement is correct: Phase 150's primitives/interaction
   expansion mines already-ingested OHLCV at zero new ingestion cost and should exhaust first.

---

## Key Risk

*(Restated and resolved 2026-07-06, Fable 5. Original correctly flagged short history and said
"this requires a separate IC gate per data source calibrated to its available N" - but left the
gate undesigned, and its own arithmetic showed the problem without noticing: 5,000 fill-forward
daily rows of quarterly data contain ~80 independent observations per symbol.)*

Alternative data has shorter history than price, and worse, **its rows overstate its
observations**. The gate design:

1. **N counts update events, not rows.** Quarters for fundamentals, resolution cycles for a
   Kalshi market, events for news, bars only for genuinely bar-cadence flows. This is the same
   principle behind `alpha.ic.min_obs_daily_features` existing separately from the 20,000-bar
   intraday gate - one more level down.
2. **Per-source APR gate keys**, following the existing precedent exactly:
   `alpha.ic.min_obs.flows`, `alpha.ic.min_obs.kalshi`, `alpha.ic.min_obs.fundamental`,
   `alpha.ic.min_obs.news`, each `[initial_estimate]`, alongside the live keys
   (`alpha.ic.min_obs_daily_features = 1000`, `alpha.ic.min_obs_per_regime = 3000`).
3. **Sources whose per-symbol event count can never clear a sane gate are measured
   cross-sectionally only** (fundamentals; likely news). The gate then applies to pooled
   cross-sectional N, which the POOLED-strata pipeline already supports.
4. **No blending before independent validation** (unchanged from original): each source enters
   at weight 0 and earns weight through its own gate; alt-data IC estimates are never averaged
   into price IC estimates. Phase 154's per-vector gating already encodes this.

---

## Recommended Order

1. **Flows** - highest signal, same cadence as price, lowest infrastructure delta
2. **Kalshi as regime conditioning** - not return prediction; stratifies existing price IC estimates by macro event probability *(2026-07-06: now additionally gated on v3.15's `StratificationDimension` contract landing first - see Kalshi section)*
3. **Fundamentals** - after corpus depth is established; needs fill-forward infrastructure *(and cross-sectional-only measurement, per revision above)*
4. **Qualitative** - infrastructure is right but timestamp discipline in news ingestion is a meaningful operational risk worth isolating last

*(Fable's note, 2026-07-06:)* the order survives review unchanged - it independently matches the
edge-source and effort/evidence logic that later produced Phase 154's ALTDATA-02/03/04 ordering.
The one addition: all four rank behind Phase 150 (primitives + interaction expansion on existing
OHLCV), which buys signal diversity with zero new ingestion surface. Alt-data is what you build
when the existing corpus is mined out, and it is not yet.

---

## See Also

*(Links repaired 2026-07-06, Fable 5 - the three `docs/research/` targets had moved to
`docs/research/archive/` unnoticed; `catalog.md`'s entry for this doc fixed in the same pass.)*

- `docs/intelligence/intelligence-alphaengine.md` - AlphaEngine concept doc
- `docs/research/archive/vision-06-flowagent.md` - FlowAgent vision (flows ingestion)
- `docs/research/archive/vision-07-fundagent.md` - FundAgent vision (fundamentals ingestion)
- `docs/research/archive/ai-10-qualitative-intelligence-layer.md` - qualitative layer design
- `docs/research/regime-multi-regime-layer.md` - `StratificationDimension` contract (home for Kalshi-as-conditioning)
- `docs/research/data-edge-source-thesis.md` - counterparty/edge framing that any new data source must answer to
- `.planning/ROADMAP.md` § Phase 154 "Alternative Data Vectors" - where this idea now lives as a phase (ALTDATA-01 pending update to the two-shape design above)
