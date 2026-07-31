# Symbol State Query Layer — Design

**Status:** draft, rewritten after independent Opus review (2026-07-31) — see "Review History" for the trail
**Priority:** medium — real gap (no live query surface exists), useful regardless of live-ingestion status
**Reviewed:** first-principles/Renaissance-lens critique in-session, then an independent Opus-model review that corrected several factual claims and one design conclusion. Not yet Fable-reviewed.
**Tags:** query-api, observability, regime, feature-registry, read-only

---

## The Ask

External processes (and dashboards) need a quick way to query "what's the current state of symbol X" across a few conceptual vectors — volatility, trend, demand/volume, structure — per timeframe, without running bespoke SQL/pandas each time. Motivating use cases: don't do X if the market is choppy right now; don't do Y in a bear trend; decide whether to hedge an option position earlier or later in the day based on expected market character.

**Scope boundary:** this system computes and exposes state. It does not make gating decisions — external consumers read the data and decide what to do with it. That boundary raises the correctness bar, not lowers it: a consumer with no visibility into how a number was derived has no way to sanity-check it (see "Reliability Metadata").

**On data freshness:** compute doesn't know or care whether an input bar was live-streamed or backfilled — `feature_factory`/`regime_writer` process whatever rows exist in `market_data_ohlcv` identically either way. This query layer inherits that: it reads whatever the latest row currently is. Today that happens to be 2026-07-28 (live ingestion is intentionally paused for the corpus rebuild) — that's a transient property of the current data, not a property of this design. The same code returns fresh reads automatically the moment ingestion resumes, with zero changes. Useful today for research/debugging/backtesting; automatically live-ready later.

**Design principle — one persistence path, source-agnostic (user-stated):** whatever gets persisted (today: `feature_vectors`/`market_regimes`; later, if `ensemble_trainer` ever produces a real composite) must go through the same write path regardless of whether the triggering bar arrived live or via replay/backfill. No "live persistence" branch and a separate "backfill persistence" branch. This query layer doesn't introduce any new persistence, so it inherits this for free today — but it's the binding rule for anything built on top of this design later (e.g. a future validated composite score), and matches this codebase's existing bit-identical-regardless-of-path convention (e.g. Phase 167/168's own backfill-isolation tests assert exactly this).

---

## What Exists (verified live, corrected 2026-07-31 after independent review)

- **`market_regimes`** — cross-sectional regime state, keyed on `(regime_group, tf, ts)` where `regime_group ∈ {equity, rates}`. **No per-symbol dimension** — this table answers "what regime is the equity/rates complex in," not "what regime is AAPL in."
- **Per-symbol HMM regime lives in `feature_vectors.regime`** instead — K=5, migration 176. **NULL on ~27% of rows** (29% at 5m); any consumer-facing read needs an explicit `regime_available: false` rather than silently omitting the field.
- **`feature_vectors`** — the Feature Factory's output. **263 columns**, 249 of which are registry-tracked features (not ~344 — corrected). 36.8M rows, 80 symbols × 4 tfs, already point-in-time correct, per-feature z-scored.
- **`feature_registry.group_name`** — populated categorical taxonomy: `structure` (64), `session` (62), `volatility` (31), `volume` (30), `calendar` (21), `momentum` (14), `regime` (10), `oscillator` (6), `cross_tf`/`macro` (3 each), **`control` (5, initially missed)**.
- **`feature_registry.control` group is 5 canary features, all `is_control = true`**, including `canary_acausal_placebo` — a *deliberately* look-ahead-contaminated positive control, currently anomalous per an open todo. Any consumer-facing query **must filter `is_control = false AND status = 'active'`**, or a placebo feature leaks out as if it were real.
- **`feature_ic_scores`** — real, current, per-feature IC data: **972,594 rows, computed 2026-07-30**, 310K with non-null `ic_sharpe`, stratified by symbol × tf × regime × lookahead, plus `passes_walkforward`, `sign_hit_rate`, `n_independent`. (First draft of this doc missed this table entirely — see "Review History.")
- **`passes_fdr` is TRUE on zero rows, corpus-wide, right now.** Nothing has cleared the multiple-testing-corrected significance bar on the in-flight rebuild yet. This is the real, checkable blocker on using IC data for anything — not "no IC data exists."
- **`alpha_events`/`alpha_ensemble_ic`** — the real, promotion-gated ensemble path (IC-weighted, regime-conditioned, effective-N-corrected). Currently 0 rows — dormant, Gate 2 pending re-test (see [[project_phase148_review_and_migration_collision]]).
- **No live query API exists for any of this.** `src/api/routes/features.py` is the only features-related route in the codebase, and it exclusively queries `intelligence_features` — the dead v2.x table (ARCHIVED, no live consumer since 2026-07-02). This is the concrete gap this doc scopes a fix for.

---

## Rejected: Group-Averaged / Composite "Strength Scores"

The initial framing of this idea was per-group sub-scores (a "volatility score," a "trend score") rolled into a composite. Rejected, for reasons that got sharper across two review passes:

1. **Duplicates already-validated infrastructure.** "Choppy"/"bear trend" are what the Dual Regime System already answers, with real measurement behind it. A second, unvalidated continuous approximation alongside a validated categorical one is worse, not better.

2. **A real, non-arbitrary weighting source exists (`feature_ic_scores.ic_sharpe`) — but it already has a home.** The first draft of this doc claimed no principled weighting was possible; that was wrong. The correct reason not to build a composite here: an IC-weighted, regime-conditioned, effective-N-corrected composite already exists by design as `ensemble_trainer` → `alpha_events`. Building a second one in this query layer duplicates *the ensemble*, not the regime system. And the live blocker is real and checkable: `passes_fdr` is TRUE on zero rows corpus-wide — nothing has cleared significance yet, so weighting by today's `ic_sharpe` would mean weighting by noise with a rigorous-sounding name.

3. **Group averaging has a real hidden-bias failure mode.** `structure` alone has 64 directional features; a naive average can silently cancel a strong bullish read against a strong bearish one and report "0" — indistinguishable from "nothing happening."

4. **A "mechanical, weight-free" alternative (threshold-counting) was proposed and then also rejected.** `|z| > 1.5`-style filtering looks weight-free but isn't: it's a hidden step-function weight (1.0 above the cut, 0.0 below), arguably worse-governed than CIS's own weights (which were at least visible and versioned). Concretely: it lets `structure`'s 64 features structurally dominate `macro`'s 3; ~83 features (`session`+`calendar`) are binary/cyclical and can't meaningfully cross a z-score threshold in a way that means anything; and it discards direction entirely, making maximally-bullish and maximally-bearish indistinguishable — strictly worse than the averaging failure mode it was meant to fix.

**Conclusion, same as before, better-grounded now:** no new blended score, no composite, no threshold-count summary. If a validated composite is ever wanted, that's `ensemble_trainer`/`alpha_events` clearing its own gates (Gate 2 re-test, `passes_fdr` populating) — not a byproduct of this query layer.

---

## Recommended Scope: Expose, Don't Blend

A read-only query API over what's already measured and already persisted, unaggregated:

1. **Regime state** — cross-sectional regime from `market_regimes` (resolved by the symbol's asset class → `regime_group`), plus per-symbol HMM regime from `feature_vectors.regime` with explicit `regime_available: false` on NULL.
2. **Raw feature reads** — current `feature_vectors` values for a symbol/tf, filtered to `is_control = false AND status = 'active'`, organized by `feature_registry.group_name` for readability, never blended.
3. **No synthesis layer.** Each consumer combines what they need for their own decision.

### No New Persistence — Query the Existing Tables Directly, Time-Bounded

The data is already computed and already persisted by the pipeline that's already running (`feature_factory`, `regime_writer`) — no new writer, no materialized view, no scheduled refresh job.

**Correction from independent review:** the original argument for this ("point lookups on the PK are cheap regardless of table size") was measured and found misleading. A true point lookup with an explicit `bar_ts` is 15ms. But the actual use case — "current state for all 80 symbols × 4 tfs" — measured **14 seconds** against the same hypertable the nightly corpus pipeline writes to: a real, trivially-reachable self-DoS risk from an unauthenticated read endpoint, not a hypothetical concern.

**The fix is a bounded time predicate, not persistence:** adding `WHERE bar_ts > now() - interval '<N> days'` took the same query from 14,061ms → 118ms (119×) — chunk exclusion, zero new compute, zero new pipeline stage. This must be a server-enforced default, not optional, and the lookback window is an APR key (see below), not a hardcoded constant.

### Reliability Metadata

Every read must carry, alongside the data:
- **Freshness** — `bar_ts` of the underlying row, `pipeline_version` (exists on the table, currently unused by any consumer), so a reader can tell if two reads came from different compute.
- **Coverage/degradation flag** — a real signal, not just a timestamp check: a mid-rebuild read can have a recent-looking `bar_ts` on a partially-rebuilt row (the corpus pipeline truncates and refills `feature_vectors`). Freshness alone can't catch this; needs a `backfill_status`-derived flag (same class of trap as [[feedback_backfill_status_seed]]).

This isn't optional — since the derivation logic is a black box to the consumer by design, metadata is the only signal they have that a read might be untrustworthy.

### Explicit Separation from `alpha_score`

Must not share a name, table, or API surface with `alpha_events`/`alpha_ensemble_ic` — those are the real, promotion-gated path, currently dormant. Conflating "raw informational read" with "validated tradeable signal" would let a consumer accidentally trust an unvalidated number as if it cleared the same bar `alpha_score` is held to.

### APR Keys Required

Per this project's Adaptive Parameter Registry mandate, at minimum:
- `infra.symbol_state.lookback_days` — the time-bound default (`[initial_estimate]`)
- `feature.symbol_state.group_map` (JSON) — if groupings ever diverge from `feature_registry.group_name` (see below)
- Any notability/threshold value, if a filtered tier is ever built (not in v1 scope — see "Deferred")

### Response Contract (resolves the tiering/evolvability question)

To let internal grouping/filtering logic evolve without silently changing what a stable field name means, the response should carry its own versioning rather than bake taxonomy into field names:

```
{
  "envelope": { "contract_version": "...", "taxonomy_version": "...", "pipeline_version": "...",
                "bar_ts": "...", "coverage_flags": [...] },
  "groups": [ { "id": "volatility", "taxonomy_version": "...", "members": [ {name, value, formula_short}, ... ] }, ... ],
  "regime": { "cross_sectional": "...", "symbol_hmm": "...", "regime_available": true }
}
```

If group membership changes (e.g. splitting `structure` into trend/SMC subsets), that's a `taxonomy_version` bump, not a silent redefinition of what "structure" means under an unchanged name.

---

## Smallest Useful First Slice (recommended starting point)

Repoint `src/api/routes/features.py` from the dead `intelligence_features` table to `feature_vectors` + `market_regimes`, with:
- Time-bounded queries (`infra.symbol_state.lookback_days`)
- Control/status filtering (`is_control = false AND status = 'active'`)
- Freshness + coverage metadata on every response
- No taxonomy, no thresholds, no tiers

This is unambiguously useful today (dashboards, debugging, research) regardless of live-ingestion state, ships in a fraction of the effort of the full design above, and defers every contested decision (grouping strategy, whether a filtered tier is ever built, dual transport) until there's a real consumer to shape them around.

---

## Deferred

- **Per-group weighted composite / threshold-count summaries** — rejected twice now (see "Rejected" above), not just deferred. Would need its own validation gate as an `ensemble_trainer`/`alpha_events` extension, not a query-layer feature.
- **Forward-looking forecasts** (hedge-timing predictions) — a new predictive claim needing full IC/statistical rigor, structurally different from distilling current state.
- **Dashboard/UI** — explicitly out of scope; this doc scopes the query API only.
- **Kafka/Redpanda publishing** — considered and cut. There's no live bar stream to publish today, and adding one is a full compute-stage build (stream key, `BaseDaemon`, OTel signals, DAG registration) that contradicts this doc's own "thin, stateless, read-only" scope. Revisit only if a genuine push/real-time consumer shows up.
- **API-first coverage for the rest of the platform** — agreed as a good general principle, explicitly a separate, larger initiative.

---

## Review History

1. **First-principles/Renaissance-lens critique (in-session):** killed a group-averaged composite score (correctly) and a materialized-view persistence design (correct conclusion, wrong initial reasoning — see below).
2. **Independent Opus-model review** (given only the doc + codebase, not the conversation): verified all live-data claims against the DB directly. Found and corrected: `feature_ic_scores` existed and was missed (the "no IC data" claim was wrong); `market_regimes` has no symbol dimension (the doc's original design was unimplementable as written); `feature_vectors` is 263 not ~344 columns; the `control`/canary group was entirely missed (real leak risk); the "cheap point lookups" persistence argument didn't hold for the actual use case (measured 14s, fixed via time-bounding, not persistence); the "mechanical" threshold-counting idea was actually a hidden, worse-governed weight than CIS's.
3. **User correction (in-session):** compute doesn't distinguish live vs. backfilled input — the "3 days stale, can't answer live questions" framing conflated a transient operational state (ingestion paused for the corpus rebuild) with a design flaw. The design is valid and useful now; it becomes live-fresh automatically once ingestion resumes, with no changes needed.

*Drafted in a Claude Code session, verified live against the running database. Not yet Fable-reviewed.*
