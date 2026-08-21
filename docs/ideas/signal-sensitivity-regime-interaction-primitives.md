# Sensitivity × Regime Interaction Primitives — Idea

**Status:** Idea — not planned. Needs a Fable rigor pass before promotion to `docs/research/`.
**Author:** Claude (Sonnet 5), interactive session, 2026-08-20. Every specific claim below
(row counts, `factor_series` values, reference-symbol overlaps) was verified live against
the running `indicagent` DB and source this session — not extrapolated from docs.
**Origin:** User asked to think through indicagent's regime taxonomy Renaissance-style —
universal/global macro vs. asset-class vs. attribute-sensitivity vs. single-security — and
push past cataloging into a concrete, evidence-based next step, applying Musk's 5-step
mandate (question the requirement → delete → simplify → accelerate → automate) rather than
proposing new infrastructure by default.

---

## The finding: two disconnected pipelines are already measuring the same macro proxies

This is not a proposal to build a new measurement system. It's the opposite: querying the
live DB shows indicagent already computes two continuous, statistically real signals for the
same handful of reference instruments — through code paths that have never been joined.

| Concept | Pipeline A: group-level regime state | Pipeline B: per-instrument sensitivity |
|---|---|---|
| Rates/duration | `market_regimes` `rates` group, `curve_pct` = TLT-SHY log-return spread, rolling z→percentile (`curve_credit.py:89`) | ITR `sensitivity.rate_sensitive`, `factor_series='TLT'`, OLS beta (104 empirical rows) |
| Credit | `market_regimes` `rates` group, `credit_pct` = HYG-LQD spread (`curve_credit.py:90`) | ITR `sensitivity.credit_risk`, `factor_series='HYG-IEF'` |
| Equity vol/beta | `market_regimes` `equity` group, `vix_pct` = SPY realized-vol z-score (`breadth_vol.py`) | ITR `sensitivity.volatility` (`factor_series='SPY_REALIZED_VOL'`) and `sensitivity.equity_beta` (`factor_series='SPY'`) |
| Dollar | `market_regimes` `fx` group, `dollar_z` (UUP-based, `fx_dollar_carry.py`) | ITR `macro_driver.dollar_strength`, `factor_series='UUP'` |

Both `sensitivity` (211 rows) and `macro_driver` (300 rows) are populated with real,
`TagCalibrator`-measured betas — `source='empirical'`, `loading`/`p_value` non-null, verified
by direct query this session (`instrument_tags` JOIN `tag_vocabulary`). Both are current, not
stale placeholders. And per `docs/foundation/instrument-tag-registry.md`'s own "Known Gaps"
section (confirmed still true): **zero live consumers read `sensitivity` or `macro_driver`.**
All three ITR readers (`equity_regime_model.py`, `cross_sectional_regime_model.py`,
`ic_engine.py`) key off `exposure`-prefix tags only, for peer-group routing — none touch the
511 measured sensitivity/driver loadings at all.

So: one pipeline already knows *what state the rates factor is in, right now* (`curve_pct`,
continuous, per-timestamp). Another pipeline already knows *how exposed this specific
instrument is to rates*, with a p-value (`rate_sensitive.loading`, continuous, per-instrument).
Nothing multiplies them together. That product is the interaction primitive this doc proposes
— and it costs zero new measurement infrastructure, because both inputs already exist.

**A third pipeline, found via a parallel SSFI session citing indicagent's own code back at
it:** `feature_vectors.equity_beta_z`/`rate_beta_z` (migration 289, Phase 151,
`tier=0_atomic`) — rolling-OLS beta vs. `SPY`/`TLT`, z-scored, computed per-bar, live in
production — measures functionally the same quantity as ITR's `sensitivity.equity_beta`
(`factor_series='SPY'`) and `sensitivity.rate_sensitive` (`factor_series='TLT'`) tags this
doc already flagged as unconsumed. Same two proxies, same underlying concept (a symbol's
beta to the broad-equity and rates factors), two live indicagent pipelines, neither aware of
the other — a second instance of exactly the pattern this doc's headline finding describes,
this time entirely within indicagent's own codebase rather than between indicagent and
`market_regimes`. Worth reconciling which of `equity_beta_z`/`rate_beta_z` (continuous,
per-bar, unvalidated by a significance test) vs. `sensitivity.equity_beta`/`rate_sensitive`
(periodic, `TagCalibrator`-measured, p-value/FDR-gated) is the one to actually use in the
interaction primitive proposed below — not both, and not a third independent measurement.
Not resolved in this pass; flagged for whoever picks this up next.

---

## Applying the 5-step mandate

**1. Question the requirement.** The real question isn't "do we need a 5th regime layer for
single-security macro-reactivity" (the framing that started this discussion) — a security's
reaction to a macro regime is not itself a new kind of regime. It's the interaction of two
things this project already measures independently. Reframing the requirement from "build a
new classification layer" to "multiply two existing measurements" is itself the main
contribution of this doc.

**2. Delete.** `factor_regime` (the 6th ITR category — `defensive`/`growth`/`momentum`/
`risk_on`/`risk_off`/`value`) looked, before checking, like an oversight — 0 empirical rows
against 211/300 for its siblings. It isn't one: all 6 rows have `measurement_type='definitional'`
and `factor_series` explicitly empty, confirmed via `tag_vocabulary` query — this was seeded
deliberately as a static human prior, not left half-built. **Do not "fix" this by wiring
`factor_regime` into `TagCalibrator`.** If growth/value/momentum exposure is wanted as a real
measured quantity, it already has a home: a new `sensitivity` tag with a real `factor_series`
proxy (e.g. `growth_value_tilt` → `IWF-IWD`, `equity_momentum` → `MTUM`) — same mechanism as
`rate_sensitive`/`credit_risk`, not a reason to resurrect a second measurement path for
`factor_regime`. That's a separate, smaller, lower-priority idea, not part of this proposal.

**3. Simplify.** Don't build a joined-label lookup table, and don't bucket either input first.
`_bucket()`'s categorical tiers exist so `market_regimes` has a compact, human-readable
`regime_label` — but `_assign_labels()` already writes the *continuous* underlying values into
`regime_prob_vector` (JSONB, keyed by each module's `PROB_KEYS`: `curve_pct`/`credit_pct`,
`vix_pct`/`breadth_pct`, `dollar_z`/`carry_z`, `momentum_z`/`ts_proxy`). Use those, not the
bucketed label. The interaction feature is a plain product of two already-continuous numbers
— `symbol_sensitivity_loading × group_regime_prob_vector[key]` — computed once per (symbol,
timestamp), no categorical cross-tab, no sparsity risk. This is exactly the existing
`vix_reversion_product = vix_z * momentum_reversal_z`-style pattern already in `FeatureVector`
(`schemas.py:1524-1533`, Phase 151 Plan 06's 10 "Theory-Motivated Interactions") — reuse that
established shape, don't invent a new one.

**4. Accelerate — cheapest, highest-conviction first test.** `rate_sensitive` × `rates` group:
- `rate_sensitive` sensitivity already has 104 empirically-measured symbols with real
  `loading`/`p_value`/`passes_fdr` — no new calibration run needed.
- `rates` regime_group is **enabled** and running (unlike `commodity`/`fx`, gated off by
  todo 041) — `curve_pct`/`credit_pct` are live in `market_regimes.regime_prob_vector` today.
- Candidate feature: `rate_sensitive_curve_product = symbol's rate_sensitive.loading ×
  market_regimes[rates, tf, ts].regime_prob_vector['curve_pct']`, tested as a new interaction
  primitive against an existing base signal (e.g. momentum) via `ic_engine.py`'s standard
  partial-IC significance test — same discipline as every other interaction primitive, no
  special-casing because the inputs happen to come from two different subsystems.
- This requires: (a) a join from `feature_vectors`/`ic_engine.py`'s symbol universe to
  `instrument_tags` for the `rate_sensitive` loading (per-symbol, rarely-changing — cacheable,
  same shape as the existing `_watermark_market_regimes_instrument_tags` peer-set cache), and
  (b) a join to `market_regimes.regime_prob_vector` for `curve_pct` at matching `(tf, ts)`. No
  new backfill, no new provider, no new table.

**5. Automate — only after step 4 proves out.** If `rate_sensitive × curve_pct` clears the
partial-IC gate, generalize into a small declarative mapping (sensitivity/macro_driver tag →
matching `regime_group` + `PROB_KEYS` entry) that a single interaction-builder function sweeps,
rather than hand-writing one product feature per pair forever. Do not build this generalized
sweep before the first pair is proven — per "earn promotion through proof," automating an
unproven mechanism is out of order.

---

## What this is NOT proposing

- **Not** a new regime table, a new `regime_group`, or a new tag category.
- **Not** a fix to `factor_regime` — that category's unmeasured state is by design.
- **Not** a claim that `rate_sensitive_curve_product` (or any specific pairing) has been
  tested yet. This is a data-source/mechanism survey plus a fully-specified first test, not a
  validated candidate. Stage 1 mechanism validation and the null-arm control (per the
  2026-08-08 standing rule) both still apply before any number here is trusted.
- **Not** urgent relative to the project's actual current blockers (`forward_returns`
  staleness gating other in-flight candidates, todo 335's downstream recompute). This is
  backlog-track work.

---

## The universal concept: sensitivity loadings need the same shrinkage IC already gets

**Added 2026-08-20, prompted by comparing notes with a parallel SSFI session** working an
independently-arrived-at version of the same underlying problem (SSFI's
`signal-event-catalog-and-impact-system.md` §7: per-security sensitivity to a sparse event
class, with peer-class pooling proposed as a fallback when an individual security's own
event history is too thin to trust alone).

**The general shape, stated once:** any per-entity point estimate computed from that
entity's own limited history should be shrunk toward a leave-one-out peer-group prior,
weighted by effective sample size — and the shrinkage's benefit must be empirically proven
(an out-of-fold test showing shrunk error is strictly less than raw error), never assumed
just because it's theoretically sound. indicagent already has a live, production-gated
reference implementation of exactly this: `shrink_ic()` / `leave_one_out_group_prior()`
(`src/intelligence/ensemble/shrinkage.py`, consumed by `ops_ic_shrinkage.py`, corpus
pipeline step 6). Read closely, `shrink_ic(ic_raw, n_eff, ic_prior, k)` has zero IC-specific
logic — `w = n_eff / (n_eff + k)` blending a raw estimate with a leave-one-out peer-group
mean is fully generic empirical-Bayes shrinkage, misleadingly scoped by name/location to one
consumer. The out-of-fold gate it clears (D-05: shrunk error strictly less than mean raw
error, re-derived fresh per training window, not reused from the full-corpus fit) is the
part worth taking seriously — it's the difference between "this should help" and "this was
shown to help."

**Direct gap in this doc's own proposal:** §4's first test uses `rate_sensitive.loading`
raw, gated only by `TagCalibrator`'s flat p-value/FDR pass — no peer-pooling for a
low-`sample_n` symbol. `instrument_tags.sample_n` is already sitting there as the exact
`n_eff` this mechanism wants, and the natural peer group is other symbols sharing the same
`exposure` tag (or `tag_category`). Before wiring `rate_sensitive_curve_product` into
production, the loading itself should go through the same shrink-and-validate discipline the
IC side of this codebase already requires — not because it's theoretically nicer, but
because this project doesn't get to skip the gate it already built for the identical
statistical shape just because the consumer is different.

**Architectural note, not yet actioned:** `shrink_ic`/`leave_one_out_group_prior` currently
live under `src/intelligence/ensemble/` (Ring 1, IC-scoped) despite carrying zero domain
vocabulary — pure statistics, Ring-0-shaped by the project's own naming rules. Promoting them
to something like `src/core/statistics/shrinkage.py` (generic `shrink_estimate`/
`leave_one_out_prior` names) before a second consumer (ITR loadings here, or any future one)
imports from an `ensemble`-named module is worth doing deliberately rather than accreting a
second copy or an awkward cross-Ring import. Not done in this pass — this doc stays a survey,
not an implementation.

**For SSFI:** the flat N-threshold fallback proposed in §7 (use class average below an
n-threshold, individual estimate above it) works, but creates a step-function discontinuity
at the threshold that continuous empirical-Bayes shrinkage avoids — and indicagent's version
is already built, already proven via a real out-of-fold gate, not just theoretically argued
for. Worth relaying back: reuse the `w = n_eff/(n_eff+k)` / leave-one-out-prior construction
(even reimplemented in SSFI's own stack) rather than the simpler threshold rule, given the
harder version is already sitting there proven.

---

## Open questions

1. Should the interaction-builder read `regime_prob_vector` live per row (a DB round-trip
   per symbol×timestamp) or precompute a broadcast-style per-`(regime_group, tf, ts)` lookup
   once and join in-memory, mirroring `cross_asset_series.py`'s broadcast pattern? Given
   CLAUDE.md's standing warning against per-row hot-loop DB calls, the latter is almost
   certainly right — needs sizing against real row counts before committing to a design.
2. `instrument_tags.loading` has a `valid_from`/`valid_to` window and `half_life_days` decay
   (per `tag_vocabulary`) — the interaction feature must respect that window (no lookahead:
   only use a loading whose `valid_from <= ts`), not just join on `symbol` blindly.
3. Which other pairs are worth testing after `rate_sensitive`×`curve_pct` — `credit_risk`×
   `credit_pct` is the next-cheapest (same enabled `rates` group, different `PROB_KEYS` slot).
   `equity_beta`/`volatility`×`vix_pct` needs the `equity` group (also enabled). `dollar_strength`
   ×`dollar_z` needs the `fx` group, which is currently disabled (todo 041) — lower priority
   until that's revisited.
