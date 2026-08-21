# Factor Sensitivity / Cross-Asset Regime Levels — Idea

> **Copied from SSFI** (`docs/research/signal-factor-sensitivity-cross-asset.md`,
> 2026-08-20) for cross-reference — unmodified below. **Surfaced a real indicagent
> finding on re-import:** this doc cites `migration 289`'s `equity_beta_z`/
> `rate_beta_z` (rolling-OLS beta vs. SPY/TLT, per-bar, live in `feature_vectors`)
> as its precedent — a *third*, previously-uncross-checked indicagent pipeline
> measuring the same underlying quantity (a symbol's beta to SPY/TLT) as ITR's
> `sensitivity.equity_beta`/`sensitivity.rate_sensitive` tags found in
> `docs/ideas/signal-sensitivity-regime-interaction-primitives.md` — two live,
> disconnected indicagent mechanisms computing near-identical betas against the
> same two proxies, neither aware of the other. Worth reconciling before adding a
> third (the interaction-primitive proposal in that doc) rather than picking one
> arbitrarily.

**Status:** Idea — not planned, not a `primitive-catalog.md` row yet. Captured per direct
user request (2026-08-20), explicitly not being acted on now.
**Origin:** user-proposed hierarchy (universal/global macro vs. asset-class vs. attribute
sensitivity vs. single-security), confirmed by the user to map onto indicagent's real
"cross-asset" work. Verified directly against indicagent's actual code/migrations, not
assumed from the concept name — per `CLAUDE.md`'s indicagent-verification rule. No code or
infrastructure shared; SSFI's own batch architecture below is independently designed
against the same underlying math, matching the project's standing "borrow patterns, never
code or runtime" constraint.

---

## The hierarchy

Four levels, by how broadly a signal applies before it says anything about one security:

1. **Universal/global macro** — identical for every security, every asset class (VIX
   level, policy uncertainty, general risk-on/risk-off appetite). SSFI already has doctrine
   here: never a standalone primitive (`vix_z`/`flight_quality` rejected in
   `primitive-catalog.md`), only enters as a broadcast series.
2. **Asset-class/market factor** — how a Level-0 shock transmits into equities
   specifically vs. bonds/commodities. Real, verified indicagent examples that are daily-
   batch-sourceable (no streaming needed): yield-curve slope/regime, `sb_corr_z`
   (stock-bond correlation regime — historically-stable relationships flipping sign are
   regime-transition events), `tip_tlt_ret_z` (TIPS/nominal Treasury spread, a real-yield
   proxy), `hyg_lqd_ret_z` (HYG/LQD credit spread), VX term structure (contango/
   backwardation). All computable from daily closes of liquid ETFs/series SSFI could
   already reach via Alpaca/FRED — none of this requires indicagent's Kafka/streaming
   plumbing, which is real-time-futures-specific and doesn't transfer.
3. **Attribute/factor sensitivity — the layer with a real, verified precedent, not a
   novel construction.** Not a signal about current conditions; a **per-security loading
   onto a Level-0/1 factor**, verified live against indicagent's migration `289_cross_
   asset_spread_beta_atomics.sql` (Phase 151, `tier='0_atomic'`, currently `status='active'`):
   `equity_beta_z` (rolling OLS slope of the symbol's own daily log-return regressed on
   SPY's daily log-return, z-scored) and `rate_beta_z` (same construction against TLT).
   Real design details worth carrying forward exactly: NULL for the factor-proxy symbol
   itself (self-regression is degenerate — beta identically 1 — emitting a constant would
   be a silently-wrong feature, the same "explicit absence, never a fabricated value"
   principle `DATA-18` already states for SSFI); daily-grain, broadcast-to-all-timeframes-
   by-date cadence, same contract as the Level-0/1 series it's computed against; treated as
   a `tier=0_atomic` primitive despite needing cross-symbol data for its computation — the
   *output* is one measured quantity per symbol per day, same shape as any other atomic,
   even though the *computation* needs a second series.
4. **Single-security/idiosyncratic** — SSFI's seven themes live almost entirely here:
   company-specific fundamentals, own short interest, own IV, own event calendar.

## Why this generalizes, not a one-off pattern

Once a per-security beta onto a given factor exists, it's the multiplier for *any*
Level-0/1 interaction involving that factor — not a hand-picked pairing invented per
candidate. This directly fixes a real weakness already sitting in `primitive-catalog.md`:
**`iv_dispersion_rate_interaction`** (Volatility section, added 2026-08-19) currently
justifies its mechanism with an assumed proxy — "index-heavy long-duration names are
disproportionately discount-rate-sensitive" — rather than a measured quantity. A real
`rate_beta_z`-equivalent primitive (SSFI's own rolling OLS slope of a symbol's return
against a rate-proxy series — `TLT` or the `real_rate` DTB3/DTB4WK series itself) would
replace that assumption with the actual measured sensitivity, and the same primitive
becomes the multiplier for the political/policy-EPU interaction candidate too
(`docs/research/signal-political-policy-regime.md`) — one mechanism serving multiple
Level-0/1 factors, not a new beta invented per macro series.

## Architecturally, not an 8th theme — same shape as Velocity

Matches the reasoning already applied to Velocity (`intelligence-vector-taxonomy.md` §5:
"applies as an operator to any of the seven [themes]... it's a transform, not a concept")
and to the political-regime candidate's own conclusion: a per-security factor-loading is a
**cross-cutting construction mechanism**, not a vector with its own UCR row. It doesn't
answer "what does this company's own condition look like right now" — it answers "how
strongly should a given Level-0/1 shock move this specific security's score," which is an
input to interaction primitives, never a competing theme diluting `SCORE-04`'s
theme-independence/Grinold's-Law discipline.

## What doesn't transfer from indicagent, stated explicitly so it isn't assumed later

`cross_asset_analyzer.py` and its sibling services are real-time Kafka-topic-subscribing
`BaseDaemon` processes, maintaining live rolling windows over streaming futures bars (ES/
NQ/RTY/YM) — architecturally coupled to indicagent's own continuous-market-data
infrastructure, which SSFI deliberately does not have (DAG Invariant 6, no general-purpose
hot tier). **The math transfers, the service architecture does not.** SSFI's equivalent
would be an ordinary daily-cadence Calc-layer `BaseBatch` job: pull the prior N days' closes
for the factor-proxy series (already landed by the Gateway) and every in-universe symbol,
run the rolling OLS, write one row per symbol per day — no streaming, no Kafka, matching
every other Calc-layer batch job SSFI already has designed.

## Extension: event-class sensitivity, not just continuous-factor sensitivity

**This doc's mechanism (rolling OLS beta) is for continuous macro series — it doesn't
directly work for discrete, sparse event classes** (FOMC decisions, sector-wide regulatory
shocks), where there isn't enough occurrence density for a meaningful regression.
`docs/research/signal-event-catalog-and-impact-system.md` §7 proposes the event-shaped
analog: average a security's own historical event-impact readings (its §6 event-study
mechanism) across occurrences of an event type, with class/sector-level pooling as the
fallback when individual history is too thin — same four-level hierarchy (universal →
asset-class → sensitivity → single-security), same "loading" concept, different
estimation mechanism because the input is sparse/discrete rather than continuous.

## Open questions, not resolved here

1. **Which factor proxies SSFI would actually use.** Indicagent's `SPY`/`TLT` choices are
   futures-trading-context defaults; SSFI's real-rate factor might use the `DTB3`/`DTB4WK`
   series directly (already sourced, `data-sources-candidates.md`) rather than a bond-ETF
   proxy — not decided, needs its own falsifiable-mechanism statement before it's a real
   catalog row, same bar every other candidate here has to clear.
2. **Rolling-window length and re-estimation cadence** — an APR-governed parameter,
   unset, unvalidated, same category as the policy-regime doc's staleness-cap open question.
3. **Not scoped against any specific target or interaction pair yet.** A construction
   mechanism plus a verified precedent, not a tested candidate — same status as every other
   `novel_candidate` in `primitive-catalog.md` until a specific pair (factor × existing
   atomic) clears that catalog's own bar, the way `iv_dispersion_rate_interaction` did.

## Cross-refs

- `docs/research/primitive-catalog.md` — `iv_dispersion_rate_interaction` (the interaction
  this would strengthen with a measured beta instead of an assumed proxy), the `vix_z`
  rejection this hierarchy's Level-0 treatment already matches
- `docs/research/signal-political-policy-regime.md` — the companion candidate this
  factor-sensitivity mechanism would generalize to (EPU-beta, not just rate-beta)
- `docs/research/data-sources-candidates.md` — FRED's existing Gateway scope
  (`DTB3`/`DTB4WK`), where yield-curve/credit-spread/real-yield series would land as
  additional series on the same module if this is ever promoted
- `/home/bg/dev/indicagent/production/migrations/289_cross_asset_spread_beta_atomics.sql` —
  the verified real precedent (`equity_beta_z`/`rate_beta_z`), read directly, not
  paraphrased, per this project's own verification standard
