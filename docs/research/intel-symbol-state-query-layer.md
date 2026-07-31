# Symbol State Query Layer — Design

**Status:** draft, refined after independent Opus review + a descriptive-vs-predictive correction (2026-07-31) — see "Review History"
**Priority:** medium — real gap (no live query surface exists), useful regardless of live-ingestion status
**Reviewed:** first-principles/Renaissance-lens critique in-session, an independent Opus-model review, and a further in-session correction on what "composite" actually means. Not yet Fable-reviewed.
**Tags:** query-api, observability, regime, feature-registry, read-only

---

## The Ask

External processes (and dashboards) need a quick way to query "what's the current state of symbol X" across a few conceptual vectors — volatility, trend, demand/volume, structure — per timeframe, without running bespoke SQL/pandas each time, and without requiring the consumer to already know what every raw field means. Motivating use cases: don't do X if the market is choppy right now; don't do Y in a bear trend; decide whether to hedge an option position earlier or later in the day based on expected market character.

**Scope boundary:** this system computes and exposes state. It does not make gating decisions — external consumers read the data and decide what to do with it. That boundary raises the correctness bar, not lowers it: a consumer with no visibility into how a number was derived has no way to sanity-check it (see "Reliability Metadata").

**On data freshness:** compute doesn't know or care whether an input bar was live-streamed or backfilled — `feature_factory`/`regime_writer` process whatever rows exist in `market_data_ohlcv` identically either way. This query layer inherits that: it reads whatever the latest row currently is. Today that happens to be 2026-07-28 (live ingestion is intentionally paused for the corpus rebuild) — that's a transient property of the current data, not a property of this design. The same code returns fresh reads automatically the moment ingestion resumes, with zero changes. Useful today for research/debugging/backtesting; automatically live-ready later.

**Design principle — one persistence path, source-agnostic (user-stated):** whatever gets persisted (today: `feature_vectors`/`market_regimes`; later, if `ensemble_trainer` ever produces a real composite) must go through the same write path regardless of whether the triggering bar arrived live or via replay/backfill. No "live persistence" branch and a separate "backfill persistence" branch. This query layer doesn't introduce any new persistence, so it inherits this for free today — but it's the binding rule for anything built on top of this design later, and matches this codebase's existing bit-identical-regardless-of-path convention (e.g. Phase 167/168's own backfill-isolation tests assert exactly this).

---

## What Exists (verified live, corrected 2026-07-31 after independent review)

- **`market_regimes`** — cross-sectional regime state, keyed on `(regime_group, tf, ts)` where `regime_group ∈ {equity, rates}`. **No per-symbol dimension** — this table answers "what regime is the equity/rates complex in," not "what regime is AAPL in."
- **Per-symbol HMM regime lives in `feature_vectors.regime`** instead — K=5, migration 176. **NULL on ~27% of rows** (29% at 5m); any consumer-facing read needs an explicit `regime_available: false` rather than silently omitting the field.
- **`feature_vectors`** — the Feature Factory's output. **263 columns**, 249 of which are registry-tracked features. 36.8M rows, 80 symbols × 4 tfs, already point-in-time correct, per-feature z-scored.
- **`feature_registry.group_name`** — populated categorical taxonomy: `structure` (64), `session` (62), `volatility` (31), `volume` (30), `calendar` (21), `momentum` (14), `regime` (10), `oscillator` (6), `cross_tf`/`macro` (3 each), **`control` (5)**.
- **`feature_registry.control` group is 5 canary features, all `is_control = true`**, including `canary_acausal_placebo` — a *deliberately* look-ahead-contaminated positive control. Any consumer-facing query **must filter `is_control = false AND status = 'active'`**, or a placebo feature leaks out as if it were real.
- **`feature_ic_scores`** — real, current, per-feature IC data: **972,594 rows, computed 2026-07-30**, 310K with non-null `ic_sharpe`, stratified by symbol × tf × regime × lookahead, plus `passes_walkforward`, `sign_hit_rate`, `n_independent`.
- **`passes_fdr` is TRUE on zero rows, corpus-wide, right now.** Nothing has cleared the multiple-testing-corrected significance bar on the in-flight rebuild yet — the real, checkable blocker on any *predictive* use of IC data.
- **`alpha_events`/`alpha_ensemble_ic`** — the real, promotion-gated ensemble path (IC-weighted, regime-conditioned, effective-N-corrected). Currently 0 rows — dormant, Gate 2 pending re-test (see [[project_phase148_review_and_migration_collision]]).
- **No live query API exists for any of this.** `src/api/routes/features.py` is the only features-related route in the codebase, and it exclusively queries `intelligence_features` — the dead v2.x table (ARCHIVED, no live consumer since 2026-07-02). This is the concrete gap this doc scopes a fix for.

---

## The Core Distinction: Descriptive vs. Predictive

Earlier passes on this doc rejected "group composite scores" wholesale. That was too blunt — it conflated two different questions with two different validation bars:

- **Predictive: "does this combination forecast future returns?"** A forecasting claim. Needs IC/FDR validation, because an unvalidated forecast presented as validated is a real, costly failure mode (this is what `alpha_score`/CIS/the ensemble exist for).
- **Descriptive: "what is this stratum doing right now?"** A statement about current state, no forecasting claim attached. "Volatility is elevated — the group's average z-score is +1.8, 90th percentile of the trailing 60 days" doesn't predict anything; it just accurately reports where the numbers already sit. This needs **no** IC/FDR validation, because there's no forecast being made to validate.

**This changes the recommendation:** descriptive per-stratum summaries are in scope and buildable today. Predictive composites (whole-symbol or per-group) are still rejected, for the same reasons as before.

### Why volatility is the easy case, and structure isn't

Not every stratum aggregates the same way, even descriptively:

- **Magnitude-type strata (volatility is the clean example):** these measure *how much* — ATR, realized vol, GARCH vol — with no opposing direction to cancel against. High-ATR and high-realized-vol both just mean "more volatile." Averaging (or taking a percentile-vs-history) is safe: there's no hidden-cancellation failure mode, because there's nothing to cancel.
- **Directional strata (`structure`, `momentum`, `trend`-adjacent features):** these can point either way — bullish order blocks vs. bearish ones, BOS up vs. BOS down. A single blended average genuinely can hide a strong bullish read canceling a strong bearish one into a misleading "0." For these, **magnitude and direction must be reported as two separate numbers**, not blended into one:
  - *Conviction strength* — e.g. average `|z|` across the group's directional features. Safe to average, same logic as volatility magnitude.
  - *Direction* — e.g. fraction of directional features currently long vs. short, or net sign count. Reported separately so "strongly bullish," "strongly bearish," and "genuinely quiet" stay distinguishable, which they cannot under a single blended average.

Classifying every one of the ~11 groups into magnitude / directional / categorical (`session`, `calendar`, `regime` are mostly state flags, not magnitude-or-direction readings, and likely need their own summary shape — e.g. "currently in NY session: true," not an averaged z-score) is implementation work, not a design blocker; volatility and structure are the two worked examples that establish the pattern.

### Why a single cross-stratum "comprehensive" number is still rejected

Even under the descriptive framing, blending *volatility* + *trend* + *volume* into one overall number doesn't have a clean interpretation, for a different reason than the predictive-validation one: these aren't the same concept. "How volatile" and "which way is trend" aren't comparable quantities the way 31 different volatility indicators are (they're all estimating the same underlying thing — current volatility — just via different formulas, so averaging them is combining independent estimates of one quantity). A cross-stratum blend combines *different* quantities into a number with no natural unit or meaning. This is a coherence objection, not a validation objection, and it holds regardless of whether IC data ever clears FDR. **Per-stratum descriptive summaries: yes. One number across all strata: no**, not because it's unvalidated, but because there's no honest interpretation of what it would mean.

---

## Recommended Scope

A read-only query API over what's already measured and already persisted:

1. **Regime state** — cross-sectional regime from `market_regimes` (resolved by the symbol's asset class → `regime_group`), plus per-symbol HMM regime from `feature_vectors.regime` with explicit `regime_available: false` on NULL.
2. **Raw feature reads** — current `feature_vectors` values for a symbol/tf, filtered to `is_control = false AND status = 'active'`, organized by `feature_registry.group_name`.
3. **Descriptive per-stratum summaries** — a mean/percentile-vs-history read for magnitude-type strata (volatility first); a conviction-strength + direction pair for directional strata (structure first). Explicitly labeled as descriptive, never as a predictive/tradeable signal.
4. **No cross-stratum composite.** Each consumer combines strata for their own decision; a single "comprehensive" number is rejected on coherence grounds (see above), not deferred pending validation.

### No New Persistence — Query the Existing Tables Directly, Time-Bounded

The data is already computed and already persisted by the pipeline that's already running (`feature_factory`, `regime_writer`) — no new writer, no materialized view, no scheduled refresh job. Descriptive summaries are computed at request time from these same tables, not pre-materialized.

**Correction from independent review:** the original argument for this ("point lookups on the PK are cheap regardless of table size") was measured and found misleading. A true point lookup with an explicit `bar_ts` is 15ms. But the actual use case — "current state for all 80 symbols × 4 tfs" — measured **14 seconds** against the same hypertable the nightly corpus pipeline writes to: a real, trivially-reachable self-DoS risk from an unauthenticated read endpoint.

**The fix is a bounded time predicate, not persistence:** adding `WHERE bar_ts > now() - interval '<N> days'` took the same query from 14,061ms → 118ms (119×) — chunk exclusion, zero new compute. Server-enforced default, not optional; the lookback window is an APR key, not a hardcoded constant.

### Reliability Metadata

Every read must carry, alongside the data:
- **Freshness** — `bar_ts` of the underlying row, `pipeline_version` (exists on the table, currently unused by any consumer).
- **Coverage/degradation flag** — a real signal, not just a timestamp check: a mid-rebuild read can have a recent-looking `bar_ts` on a partially-rebuilt row. Needs a `backfill_status`-derived flag (same class of trap as [[feedback_backfill_status_seed]]).

Not optional — since the derivation logic is a black box to the consumer by design, metadata is the only signal they have that a read might be untrustworthy.

### Explicit Separation from `alpha_score`

Must not share a name, table, or API surface with `alpha_events`/`alpha_ensemble_ic` — those are the real, promotion-gated predictive path, currently dormant. A descriptive summary must never be labeled or structured in a way that lets a consumer mistake it for a validated tradeable signal.

### APR Keys Required

- `infra.symbol_state.lookback_days` — the time-bound default
- `feature.symbol_state.group_map` (JSON) — if groupings ever diverge from `feature_registry.group_name`
- `feature.symbol_state.percentile_window_days` — the trailing-history window for percentile-vs-history framing (this is a tunable calibration choice, same category as any other lookback window elsewhere in this codebase)
- `feature.symbol_state.summary_statistic` — mean vs. median for magnitude-type rollups, if this ever needs to be configurable rather than fixed

### Response Contract

```
{
  "envelope": { "contract_version": "...", "taxonomy_version": "...", "pipeline_version": "...",
                "bar_ts": "...", "coverage_flags": [...] },
  "regime": { "cross_sectional": "...", "symbol_hmm": "...", "regime_available": true },
  "strata": [
    { "id": "volatility", "kind": "magnitude",
      "summary": { "avg_z": 1.8, "percentile_60d": 90 },
      "members": [ {name, value, formula_short}, ... ] },
    { "id": "structure", "kind": "directional",
      "summary": { "conviction_avg_abs_z": 1.2, "direction": {"long_frac": 0.7, "short_frac": 0.3} },
      "members": [ {name, value, formula_short}, ... ] }
  ]
}
```

`kind` makes the magnitude/directional distinction explicit in the contract itself, so a consumer (or a future implementer) can't accidentally average a directional stratum's raw members the naive way. If group membership or summary methodology changes, that's a `taxonomy_version` bump, not a silent redefinition under an unchanged field name.

---

## Smallest Useful First Slice (recommended starting point)

Repoint `src/api/routes/features.py` from the dead `intelligence_features` table to `feature_vectors` + `market_regimes`, with:
- Time-bounded queries (`infra.symbol_state.lookback_days`)
- Control/status filtering (`is_control = false AND status = 'active'`)
- Freshness + coverage metadata on every response
- Raw member reads only — no strata summaries yet

This is unambiguously useful today (dashboards, debugging, research) regardless of live-ingestion state and ships in a fraction of the effort of the full design. Descriptive strata summaries (the magnitude/directional split above) are the natural second slice once the raw-read layer is in place and the magnitude-vs-directional classification has been worked out per group.

---

## Deferred / Rejected

- **Predictive composite scores (whole-symbol or per-group)** — rejected, not deferred. Needs `ensemble_trainer`/`alpha_events` clearing its own gates (Gate 2 re-test, `passes_fdr` populating); not a query-layer feature.
- **A single cross-stratum "comprehensive" number** — rejected on coherence grounds (blends non-comparable concepts), independent of validation status.
- **Threshold-count summaries** (`|z| > 1.5` style) — rejected; a hidden, worse-governed weight than CIS's own, discards direction entirely. Superseded by the magnitude/direction-pair design above.
- **Forward-looking forecasts** (hedge-timing predictions) — a new predictive claim needing full IC/statistical rigor, structurally different from distilling current state.
- **Dashboard/UI** — explicitly out of scope; this doc scopes the query API only.
- **Kafka/Redpanda publishing** — considered and cut; no live bar stream to publish today, and adding one is a full compute-stage build contradicting this doc's thin/read-only scope.
- **API-first coverage for the rest of the platform** — agreed as a good general principle, explicitly a separate, larger initiative.

---

## Review History

1. **First-principles/Renaissance-lens critique (in-session):** killed a whole-symbol group-averaged composite score and a materialized-view persistence design (right conclusion on persistence, wrong initial reasoning).
2. **Independent Opus-model review** (given only the doc + codebase, not the conversation): verified all live-data claims against the DB directly. Corrected: `feature_ic_scores` existed and was missed; `market_regimes` has no symbol dimension; `feature_vectors` is 263 not ~344 columns; the `control`/canary group was missed entirely (real leak risk); the "cheap point lookups" persistence argument didn't hold for the actual use case (measured 14s, fixed via time-bounding); the threshold-counting idea was a hidden, worse-governed weight than CIS's.
3. **User correction (source-agnostic design):** compute and persistence don't distinguish live vs. replay input — the "3-days-stale blocks this" framing conflated a transient operational state with a design flaw.
4. **User correction (descriptive vs. predictive, this pass):** the blanket "no composites" conclusion conflated a forecasting claim (needs IC/FDR validation) with a descriptive current-state summary (doesn't). Corrected to: descriptive per-stratum summaries are in scope, with magnitude-type and directional-type strata requiring different (and for directional strata, split) treatment; predictive composites and a cross-stratum "comprehensive" number remain rejected, for validation and coherence reasons respectively.

*Drafted in a Claude Code session, verified live against the running database. Not yet Fable-reviewed.*
