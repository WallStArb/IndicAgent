# Symbol State Query Layer — Design

**Status:** draft, scope-corrected same session (not yet built)
**Priority:** medium — real gap (no live query surface exists), but not blocking anything else
**Reviewed:** first-principles/Renaissance-lens critique in-session (2026-07-31), not yet Fable-reviewed — see "Rejected Approach" below for what the critique found and killed
**Tags:** query-api, observability, regime, feature-registry, read-only

---

## The Ask

External processes (and dashboards) need a quick way to query "what's the current state of symbol X" across a few conceptual vectors — volatility, trend, demand/volume, structure — per timeframe, without running bespoke SQL/pandas each time. Motivating use cases (user's own examples): don't do X if the market is choppy right now; don't do Y in a bear trend; decide whether to hedge an option position earlier or later in the day based on expected market character.

**Explicit scope boundary:** this system computes and exposes state. It does not make gating decisions — external consumers read the data and decide what to do with it. That boundary doesn't lower the bar on correctness; it raises it, because a consumer with no visibility into how a number was derived has no way to sanity-check it. See "Reliability Metadata" below.

---

## What Already Exists (verified live, 2026-07-31)

- **`market_regimes`** — the Dual Regime System's output table. Per-symbol HMM regime (K=5, migration 176) and cross-sectional VIX×breadth market regime, both empirically validated, both live. This directly answers "are we choppy / trending" with real statistical backing — see MEMORY.md's "Dual Regime System" entry for the full mechanism.
- **`feature_vectors`** — the Feature Factory's output. ~344 columns/symbol as of this session (249 base + ~100 new primitives from an in-flight corpus rebuild), already point-in-time correct, already z-scored/normalized per feature (`normalization = 'z_scored'` in `feature_registry`), already per-timeframe.
- **`feature_registry.group_name`** — a fixed, populated categorical taxonomy already tagging every active feature: `momentum` (14), `volume` (30), `volatility` (31), `structure` (64), `session` (62), `oscillator` (6), `regime` (10), `calendar` (21), `cross_tf`/`macro` (3 each). No separate "trend" or "demand" tag — `structure` is the closest analog to trend, `volume` to demand.
- **No live query API exists for any of this.** `src/api/routes/features.py` is the only features-related route in the codebase, and it exclusively queries `intelligence_features` — the **dead v2.x table** (CLAUDE.md: ARCHIVED, no live consumer since 2026-07-02). There is currently zero API/dashboard exposure of `feature_vectors`, `feature_registry`, `market_regimes`, `alpha_events`, or `alpha_ensemble_ic`. This is the actual, concrete gap this doc is scoping a fix for.

## What Doesn't Exist (also verified live, 2026-07-31)

- **`feature_registry.last_ic_sharpe` is 0% populated across every group** — not sparse, completely empty, checked group-by-group. The per-feature IC-tracking mechanism a "weight blended reads by measured predictive power" design would depend on isn't running at all right now.
- **`alpha_events` and `alpha_ensemble_ic` are both 0 rows.** The ensemble/publisher pipeline that would produce a validated composite `alpha_score` is dormant (consistent with the intentionally-paused live ingestion chain and Phase 148's Gate 2 status — see [[project_phase148_review_and_migration_collision]] for why that verdict is currently pending re-test, not settled).

---

## Rejected Approach: Group-Averaged / Composite "Strength Scores"

The initial framing of this idea (this session) was: per-group sub-scores (a "volatility score," a "trend score," etc.) rolled up into a comprehensive composite. Applying real scrutiny to that killed it, for three independent reasons:

1. **It duplicates already-validated infrastructure.** The two concrete motivating examples ("choppy," "bear trend") are exactly what `market_regimes` already answers, with real measurement behind it. Building a second, unvalidated continuous approximation of the same concept alongside a validated categorical one is worse, not better — Simons wouldn't fund a weaker parallel signal when a proven one already exists; the actual gap is exposure, not measurement.

2. **Group averaging has a real hidden-bias failure mode.** `structure` alone has 64 features spanning order blocks, FVG, BOS/CHoCH, swing/fib — many of them directional. A naive average can silently cancel a strong bullish read against a strong bearish one and report "0," which is indistinguishable from "nothing happening." Since the logic is a black box to external consumers by design, they'd have no way to tell "quiet" from "conflicting" apart. This is a genuine silent-wrong-answer risk, not a hypothetical one.

3. **There is no principled way to weight a blend today.** The one non-subjective candidate — weight by each feature's own measured `last_ic_sharpe` — is unavailable; that field is 0% populated. Any blend built today would necessarily use hand-assigned weights, which is the exact mechanism `docs/plans/archive/2026-02-27-composite-intelligence-score-design.md` (Composite Intelligence Score, CIS) shipped with and was explicitly killed for in the v3.0 rebuild:

   > "CIS / ICC scoring — *Why it was wrong:* Weighted by researcher-assigned bucket weights. Weights change slowly via logistic regression on biased sample. → *v3.0 replacement:* IC Sharpe: weights derived entirely from forward return correlation." (`docs/intelligence/intelligence-alphaengine.md`)

   Reviving that pattern under a new name because the consumer is now "informational" rather than "tradeable" doesn't change the mechanism that was rejected — it changes who's exposed to the mistake.

**Conclusion:** no new blended score, no composite, no per-group weighted average. Not now, and not until `last_ic_sharpe` (or an equivalent measured-not-assigned weight) actually exists in enough coverage to make weighting non-arbitrary — at which point that's its own measurement question requiring its own validation, not a byproduct of this query layer.

---

## Recommended Scope: Expose, Don't Blend

A read-only query API surfacing what's already measured, unaggregated:

1. **Regime state** — current `market_regimes` row(s) for a symbol: per-symbol HMM regime, cross-sectional market regime. This is the validated answer to "what kind of market are we in."
2. **Raw feature reads** — current `feature_vectors` values for a symbol/tf, organized (not blended) by `feature_registry.group_name` so a consumer can see "here are the 31 volatility-tagged readings" without averaging them into one ambiguous number.
3. **No synthesis layer.** Each consumer combines what they need for their specific decision — hedge timing and chop-avoidance need different combinations of the same primitives, and a one-size-fits-all blend would be wrong for both in different, invisible ways.

### Reliability Metadata

Every read must carry, alongside the data:
- **Freshness** — timestamp of the underlying `bar_ts`/`ts`, so a consumer can tell if they're looking at a stale read.
- **Coverage/degradation flag** — whether the query landed mid-corpus-rebuild or against a symbol/tf with known gaps (e.g., BIL's thin-cell IC instability, [[project_todo218... bil-thin-cell]]).

This isn't optional. Since the derivation logic is a black box to the consumer by design, the *only* signal they have that a number might be untrustworthy is metadata traveling with it — matching this project's existing fail-loud discipline (OTel health contract, DLQ handling) rather than the one place that discipline quietly doesn't apply.

### Explicit Separation from `alpha_score`

This query layer must not share a name, table, or API surface with `alpha_events`/`alpha_ensemble_ic`. Those are the real, promotion-gated ensemble path — currently dormant, Gate 2 status pending re-test on the in-flight corpus rebuild. Conflating "here's a raw informational read" with "here's the validated tradeable signal" would let an external consumer accidentally trust an unvalidated number as if it had cleared the same bar `alpha_score` is held to.

### No New Persistence — Query the Existing Tables Directly

**Correction (2026-07-31, user-flagged):** an earlier draft of this doc proposed a materialized view or a new dedicated writer, refreshed on a schedule, sitting between the API and `feature_vectors`/`market_regimes`. That's wrong — it re-computes/re-copies data that is *already* computed and *already* persisted by the pipeline that's already running (`feature_factory`, `regime_writer`). There is no new compute to do. The API queries `feature_vectors` and `market_regimes` directly, at request time, full stop.

The operational-isolation concern that motivated the materialized-view idea (external polling contending with `ic_engine`/`feature_factory`'s write load on the same table — a real, previously-documented near-miss on this exact table) is legitimate but doesn't justify a new compute step to solve it. Point lookups keyed on `(symbol, tf, bar_ts)` — the table's actual primary key — are cheap regardless of table size. If polling volume ever becomes a real, measured problem, the fix is an infrastructure-level one (connection pooling, a read replica, rate limiting) applied to a proven load pattern — not a speculative new pipeline stage built ahead of any evidence it's needed.

**Broader "API-first" principle (user's framing):** this project should generally have API coverage for its data, not just this one surface. That's a real, separate initiative and explicitly out of scope here — this doc stays narrow: one thin, stateless, read-only endpoint over data that already exists.

---

## Deferred

- **Per-group weighted composite scores** — blocked on `last_ic_sharpe` (or equivalent) actually being populated at real coverage. Its own future measurement question with its own validation gate once the corpus rebuild + IC re-scoring lands.
- **Forward-looking forecasts** ("likely weak market today," hedge-timing predictions) — this is a new predictive claim, not a distillation of current state. Needs the same IC/statistical rigor as any new alpha candidate before anything gates a real decision on it. Explicitly out of scope for this doc; a candidate for its own thesis on `docs/research/data-edge-source-thesis.md`-style falsification treatment if pursued.
- **Dashboard/UI** — user explicitly deferred this; this doc scopes the query API only.
- **API-first coverage for the rest of the platform** — user's stated broader principle (this project should have API surfaces for its data generally, not just this one table pair) is agreed but explicitly out of scope for this doc; a separate, larger initiative to scope later.

---

*Drafted in a Claude Code session (2026-07-31), all schema/coverage claims verified live against the running database (`\d`, `SELECT count/group by`) rather than assumed from memory. Not yet Fable-reviewed.*
