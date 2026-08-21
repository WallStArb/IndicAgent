# Symbol State Query Layer — Design

**Status:** draft, gradient encoding locked (2026-07-31) — see "Review History" for the full correction trail
**Priority:** medium — real gap (no live query surface exists), useful regardless of live-ingestion status
**Reviewed:** first-principles/Renaissance-lens critique in-session, an independent Opus-model review, a descriptive-vs-predictive correction, and a Kafka-delivery investigation. Not yet Fable-reviewed.
**Tags:** query-api, observability, regime, feature-registry, read-only

---

## The Ask

External processes (and dashboards) need a quick way to query "what's the current state of symbol X" across a few conceptual vectors — volatility, trend, demand/volume, structure — per timeframe, without running bespoke SQL/pandas each time, and without requiring the consumer to already know what every raw field means. Motivating use cases: don't do X if the market is choppy right now; don't do Y in a bear trend; decide whether to hedge an option position earlier or later in the day based on expected market character.

**Scope boundary:** this system computes and exposes state. It does not make gating decisions — external consumers read the data and decide what to do with it. That boundary raises the correctness bar, not lowers it: a consumer with no visibility into how a number was derived has no way to sanity-check it (see "Reliability Metadata").

**On data freshness:** compute doesn't know or care whether an input bar was live-streamed or backfilled — `feature_factory`/`regime_writer` process whatever rows exist in `market_data_ohlcv` identically either way. This query layer inherits that: it reads whatever the latest row currently is. Today that happens to be 2026-07-28 (live ingestion is intentionally paused for the corpus rebuild) — that's a transient property of the current data, not a property of this design. The same code returns fresh reads automatically the moment ingestion resumes, with zero changes. Useful today for research/debugging/backtesting; automatically live-ready later.

**Design principle — one persistence path, source-agnostic (user-stated):** whatever gets persisted (today: `feature_vectors`/`market_regimes`; later, if `ensemble_trainer` ever produces a real composite) must go through the same write path regardless of whether the triggering bar arrived live or via replay/backfill. No "live persistence" branch and a separate "backfill persistence" branch. This query layer doesn't introduce any new persistence, so it inherits this for free today — but it's the binding rule for anything built on top of this design later, and matches this codebase's existing bit-identical-regardless-of-path convention (e.g. Phase 167/168's own backfill-isolation tests assert exactly this).

---

## What Exists (verified live, corrected 2026-07-31 after independent review)

**Flagged stale 2026-08-21, not re-verified as part of this pass:** this section's
`feature_registry.*` references (group taxonomy, `is_control`) are now wrong as written --
`feature_registry` was DROPped by migration 311 (Phase 170, 2026-08-10); the live
successor is `concept_registry` (`group_name`/`is_control` both ported, see migration 283).
Not fixed inline here because the *numbers* in this section (36.8M `feature_vectors` rows,
80 symbols, the specific per-group counts) are equally stale -- the corpus has since grown
to 231 symbols and ~106M rows (see `.planning/STATE.md`'s Strategic Plan section) -- and
partially correcting just the table name while leaving every count wrong would look like a
full refresh when it isn't one. **Before this design doc is picked up for planning, this
whole section needs a fresh live-verification pass, not a piecemeal string fix.**

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

A read-only query API over what's already measured and already persisted. The primary, default output per stratum is a numeric gradient, not raw fields or text — raw member-level access stays available as an optional deeper tier for anyone who wants it, but it's not what a consumer sees by default.

1. **Regime state** — cross-sectional regime from `market_regimes` (resolved by the symbol's asset class → `regime_group`), plus per-symbol HMM regime from `feature_vectors.regime` with explicit `regime_available: false` on NULL.
2. **Per-stratum gradient (primary, default output)** — see "Gradient Encoding" below. One number for magnitude-type strata, two for directional-type strata. Fully numeric, no text, no expertise required to consume.
3. **Raw feature reads (optional, secondary tier)** — current `feature_vectors` values for a symbol/tf, filtered to `is_control = false AND status = 'active'`, organized by `concept_registry.group_name` (corrected 2026-08-21 -- `feature_registry` was DROPped by migration 311; `is_control`/`status`/`group_name` all ported to `concept_registry`, migration 283). Available for a consumer who wants to see what's behind a gradient, not the default response.
4. **No cross-stratum composite.** Each consumer combines strata for their own decision; a single "comprehensive" number is rejected on coherence grounds (see above), not deferred pending validation.

### Gradient Encoding (locked, 2026-07-31)

**Magnitude-type strata (volatility is the worked example): one number, `gradient ∈ [-1, +1]`.**

Defined as *signed deviation from typical*: take the stratum's current reading (e.g. average z-score across its member features), rank it against its own trailing history, map that percentile onto `[-1, +1]` (`0` = typical/50th percentile, `+1` = extreme-high edge of its own history, `-1` = extreme-low edge). Safe as a single number because there's a real, coherent "above vs. below normal" axis for a magnitude reading with nothing to cancel against.

**Directional-type strata (structure, momentum: two numbers, never one.**

- `direction ∈ [-1, +1]` — net lean (e.g. `long_fraction − short_fraction` among the group's directional features), same percentile-vs-history mapping as above.
- `conviction ∈ [0, 1]` — how strong/reliable the current reading is (e.g. percentile-scaled average `|z|` across the same features), independent of which way it leans.

A single blended number for a directional stratum was tried and rejected twice already in this doc (once as a raw average, once as a threshold count) — both times because `direction ≈ 0` is ambiguous between "genuinely quiet" and "strong opposing signals canceling out." The `direction`/`conviction` pair is the numeric-only way to keep that distinguishable: low conviction means the reading is quiet or unreliable regardless of what direction says; high conviction with `direction ≈ 0` means real signals are actively conflicting — a materially different, and more decision-relevant, state than quiet.

**This is a normalization/encoding choice, not a validation claim** — mapping an already-computed percentile onto a bounded range doesn't assert predictive value, so it doesn't reopen the IC/FDR issue. Same category of decision as choosing to z-score a feature in the first place.

**Categorical/state strata** (`session`, `calendar`, `regime`) don't fit the gradient shape at all — they're flags or labels, not continuous readings (`in_ny_session: true`, not a percentile). These stay as direct state reads, not gradients.

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

- `infra.symbol_state.lookback_days` — the time-bound default for raw-read queries
- `feature.symbol_state.group_map` (JSON) — if groupings ever diverge from `concept_registry.group_name` (corrected 2026-08-21, see note above)
- `feature.symbol_state.percentile_window_days` — the trailing-history window the gradient's percentile ranking is computed against
- `feature.symbol_state.summary_statistic` — mean vs. median for the pre-percentile magnitude/direction aggregation, if this ever needs to be configurable rather than fixed

### Response Contract

```
{
  "envelope": { "contract_version": "...", "taxonomy_version": "...", "pipeline_version": "...",
                "bar_ts": "...", "coverage_flags": [...] },
  "regime": { "cross_sectional": "...", "symbol_hmm": "...", "regime_available": true },
  "strata": {
    "volatility":  { "kind": "magnitude",   "gradient": 0.62 },
    "structure":   { "kind": "directional", "direction": -0.15, "conviction": 0.71 },
    "session":     { "kind": "state",       "value": "in_ny_session" }
  },
  "raw": {
    "volatility": [ {name, value, formula_short}, ... ],
    "structure":  [ {name, value, formula_short}, ... ]
  }
}
```

`strata` is the primary, default-consumed field — pure numbers, `kind` tells a consumer which shape to expect without needing to understand the underlying features. `raw` is present but optional/secondary — a consumer who wants to see what's behind a gradient can look, but it's not what's returned by default. `kind` also protects against a future implementer accidentally averaging a directional stratum's raw members the naive way. If group membership or gradient methodology changes, that's a `taxonomy_version` bump, not a silent redefinition under an unchanged field name.

### Extendibility

The compute logic is generic, parameterized by two things per stratum: which features belong to it, and its `kind` (`magnitude` / `directional` / `state`). It is not hardcoded per-stratum, which makes most future extension a config change, not new code:

- **Adding a new stratum** (e.g. volume/demand) means defining its feature membership and classifying its `kind` — a `magnitude`-type addition reuses the existing percentile-vs-history gradient formula unchanged; a `directional`-type addition reuses the existing `direction`/`conviction` pair unchanged. Zero new compute logic in either case.
- **Regrouping features, or diverging from `concept_registry.group_name`'s taxonomy**, is a config/APR change (`feature.symbol_state.group_map`, with a `taxonomy_version` bump) in the common case, not a schema migration — this is exactly why groupings were deliberately decoupled from `group_name`'s value set earlier in this doc. **Corrected 2026-08-21:** the "fixed DB check-constraint" premise this paragraph was written against is stale in a substantive way, not just a table-name swap — `feature_registry.group_name` (dropped, migration 311) *was* an 11-value CHECK constraint, but `concept_registry.group_name` (migration 283) is deliberately UNCONSTRAINED TEXT, policed by the controlled-vocabulary system (`vocabulary_drift.py`, Phase 161) instead of a table CHECK. A new category no longer needs a migration at all under the live schema, even in the "rarer case" this paragraph describes -- worth re-deriving whether this changes the `taxonomy_version`/`group_map` design's own reasoning before this doc is planned.
- **The response contract's `taxonomy_version`/`kind` fields exist specifically to make this evolution safe** — a consumer reads `kind` to know how to interpret a stratum rather than assuming, and a `taxonomy_version` bump signals when membership or methodology changed, rather than a field silently meaning something different under an unchanged name.
- **What is *not* free:** a fundamentally new `kind` beyond magnitude/directional/state (nothing has come up requiring one yet) would need real new compute logic, not just config — extendibility applies to adding more strata of the existing kinds, not to inventing new kinds of summary.

---

## Delivery: API and Kafka

**Raw feature vectors already have a live push mechanism — no new work needed for that piece.** `topic_feature_vectors` exists today; `FeatureVectorPipeline` (a `BaseDaemon`) publishes every computed bar to it, and `feature_vector_writer` is just one of potentially many independent consumer groups reading it. An external system can subscribe to this exact topic today (its own consumer group) and receive the same real-time stream, the same way v2's `topic_intelligence` let consumers subscribe to I1-I6. Verified live: the writer (`indicagent-feature-vector-writer.service`) is running; the publisher (`indicagent-feature-vector-pipeline.service`) is currently `failed`, consistent with live ingestion being paused — nothing is flowing right now, but the mechanism is real and resumes automatically once the pipeline is back up, no new code required.

`market_regimes` has no equivalent topic — its writers (`cross_sectional_regime_model.py`, `equity_regime_model.py`) are batch jobs (`ProcessPoolExecutor` + one serial batch `INSERT`, not `BaseDaemon`), which is the correct, established pattern for periodic bulk recomputation in this codebase, not an oversight. Kafka is reserved for the live per-bar hot path; a regime refit over a large historical window is not that, and routing it through a low-retention transport bus would misuse it as an ETL pipe.

**The strata gradients are new — they don't exist as raw output anywhere, so delivery mode is a real choice:**
- **On-demand (pull):** compute the gradient at request time from `feature_vectors`, no new persistence, no new compute stage. Cheapest, ships fastest.
- **Live (push):** a new `BaseDaemon` subclass subscribing to the *existing* `topic_feature_vectors`, computing the gradient per bar as vectors arrive, publishing to a new topic (e.g. `topic_symbol_state_gradient`), consumed by a new writer into a new table if durable/queryable history is also wanted. This reuses `BaseDaemon`, an existing Ring 0 class (`src/core/agent/base.py:108`) every compute daemon in this codebase already extends — it is not new daemon infrastructure, it's one more subclass of infrastructure that already exists and is already proven.

**Observability/guardrails are bundled in, not bolted on, by extending `BaseDaemon`:**
- The 5 mandatory OTel health signals (`agent_last_message_timestamp_seconds`, `agent_crash_total`, `agent_dlq_total`, `watchdog_notify_total`, `watchdog_notify_suppressed_total`) are auto-inherited — zero per-service code, per CLAUDE.md's OTel Health Contract.
- `observed_span()` (`src/observability/spans.py`) for tracing, `setup_service_logging()` for structured logs to `logs/<name>.log`, and the standard DLQ pattern (`BaseWriter._parse_payload`'s `None`-vs-`[]` contract) if a persistence writer is added — all existing, reused conventions, not new ones invented for this service.
- The only genuinely new registration work: one `stream_keys.py` topic entry, one `_DAG_ORDER`/`_AGENT_ID_TO_UNIT` registration, one `alert.lag.*` APR key seeded for the new topic's lag threshold — each a small, mechanical addition following an existing pattern, not new mechanism design.

**Recommended sequencing:**
1. Raw feature/regime read API (repoint `src/api/routes/features.py` off the dead `intelligence_features` table) — useful immediately, ships fastest, needed regardless of what follows.
2. Strata gradients, on-demand via the same API — the actual distilled output this doc is about.
3. Live gradient push via Kafka, only once a real consumer needs sub-request-latency delivery rather than polling — build the `BaseDaemon` + new topic at that point, reusing the existing `topic_feature_vectors` subscription.

---

## Deferred / Rejected

- **Predictive composite scores (whole-symbol or per-group)** — rejected, not deferred. Needs `ensemble_trainer`/`alpha_events` clearing its own gates (Gate 2 re-test, `passes_fdr` populating); not a query-layer feature.
- **A single cross-stratum "comprehensive" number** — rejected on coherence grounds (blends non-comparable concepts), independent of validation status.
- **Threshold-count summaries** (`|z| > 1.5` style) — rejected; a hidden, worse-governed weight than CIS's own, discards direction entirely. Superseded by the magnitude/direction-pair design above.
- **Forward-looking forecasts** (hedge-timing predictions) — a new predictive claim needing full IC/statistical rigor, structurally different from distilling current state.
- **Dashboard/UI** — explicitly out of scope; this doc scopes the query/delivery layer only.
- **Live Kafka push for the strata gradients** — not rejected (corrected from an earlier pass in this doc that called this scope creep); genuinely useful, genuinely real work, sequenced after the on-demand version has a real consumer needing push delivery. Raw feature vectors already have a working push mechanism (`topic_feature_vectors`) and need no new work at all.
- **API-first coverage for the rest of the platform** — agreed as a good general principle, explicitly a separate, larger initiative.

---

## Review History

1. **First-principles/Renaissance-lens critique (in-session):** killed a whole-symbol group-averaged composite score and a materialized-view persistence design (right conclusion on persistence, wrong initial reasoning).
2. **Independent Opus-model review** (given only the doc + codebase, not the conversation): verified all live-data claims against the DB directly. Corrected: `feature_ic_scores` existed and was missed; `market_regimes` has no symbol dimension; `feature_vectors` is 263 not ~344 columns; the `control`/canary group was missed entirely (real leak risk); the "cheap point lookups" persistence argument didn't hold for the actual use case (measured 14s, fixed via time-bounding); the threshold-counting idea was a hidden, worse-governed weight than CIS's.
3. **User correction (source-agnostic design):** compute and persistence don't distinguish live vs. replay input — the "3-days-stale blocks this" framing conflated a transient operational state with a design flaw.
4. **User correction (descriptive vs. predictive):** the blanket "no composites" conclusion conflated a forecasting claim (needs IC/FDR validation) with a descriptive current-state summary (doesn't). Corrected to: descriptive per-stratum summaries are in scope, with magnitude-type and directional-type strata requiring different (and for directional strata, split) treatment; predictive composites and a cross-stratum "comprehensive" number remain rejected, for validation and coherence reasons respectively.
5. **User correction (delivery mechanism):** questioned why Kafka wasn't integrated, prompting a direct check of the actual codebase rather than assumption — found `topic_feature_vectors` already exists and already supports independent subscribers (verified: writer running, publisher currently `failed` consistent with paused ingestion); found `market_regimes`'s batch writers correctly don't use Kafka (live-per-bar vs. periodic-bulk is the real architectural line, not an oversight). This reversed an earlier "Kafka is scope creep, cut" conclusion in this doc — it's scope creep for the *strata gradients* only if built before a real consumer needs push delivery, not scope creep in general, and raw feature vectors need no new Kafka work at all.
6. **Gradient encoding locked-in:** requested a distilled numeric encoding (`-1` to `+1`) instead of text descriptions. Landed on: one number (`gradient`) for magnitude-type strata (percentile-vs-history, signed by above/below typical); two numbers (`direction`, `conviction`) for directional-type strata, specifically to preserve the quiet-vs-conflicting distinction the doc's cancellation objection depends on — a single blended number for a directional stratum reintroduces that exact ambiguity in numeric form.

*Drafted in a Claude Code session, verified live against the running database. Not yet Fable-reviewed.*
