# Phase 175: ITR materiality-filtered empirical tags for breadth/peer-grouping - Context

**Gathered:** 2026-09-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Todo 379 shipped a `source='human'`-only stopgap for `equity_regime_model.py`'s successor
`breadth_vol.py` (equity breadth universe) and `cross_sectional_regime_model.py`'s peer-group
resolution (all 4 regime groups). That stopgap discards real empirical sensitivity signal
entirely. This phase designs and implements a materiality filter so a `source='empirical'`
`instrument_tags` row can be safely re-admitted into these two identity-adjacent, behavioral-
similarity consumers when the underlying statistical evidence clears a real bar — not just
`passes_fdr` (already proven insufficient by the `ic_engine.py` routing bug this stopgap
followed: significance and materiality are different questions at n=250+ observations).

</domain>

<decisions>
## Implementation Decisions

### Where the computation lives
- **D-01:** Extend `TagCalibrator` (`services/tag_calibrator.py`) with a 4th pass computing
  an orthogonalized/incremental factor loading, persisted as new evidence columns on
  `instrument_tags` for every `source='empirical'` row (unconditionally — this is a
  measurement, not an admission decision). Rejected building this inside
  `breadth_vol.py`/`cross_sectional_regime_model.py` directly: consumers are dumb readers
  of already-decided state everywhere else in this codebase (ConfigService, VocabularyService,
  every `market_regimes` reader) — computing statistics inside a consumer breaks that pattern
  uniquely here and guarantees the two consumers' copies of the same math drift apart over
  time. TagCalibrator already owns the BH-FDR correction, HAC p-values, hysteresis, and
  `discovery_oos_days` state machine (todo 125, folded in below) this computation needs to
  reuse.
- **D-02:** Each consumer applies its *own* admission threshold as a `WHERE` clause at read
  time against the persisted statistic — this is what "reuse one implementation, calibrate
  per consumer" (all three reviewers' consensus) actually means: one measurement engine, N
  independent read-time cutoffs. Do not build N copies of the orthogonalization math.
- **New evidence columns needed on `instrument_tags`** (exact names/types are a research/
  planning decision, not locked here): the orthogonalized/partial factor loading, its
  incremental R², a sign-stability measure across rolling windows, and a boolean/threshold
  outcome per the seeded APR bar (D-05). Migration required.

### Rollout strategy
- **D-03:** Shadow mode first, non-negotiable — this is a standing CLAUDE.md principle, not
  a phase-specific choice, and this filter changes what feeds `ensemble_trainer`'s training
  stratification and `ic_engine`'s IC measurement once live. TagCalibrator writes the new
  evidence columns for every empirical row informationally in this phase. A diagnostic script
  (new, this phase) reports what breadth-universe/peer-pool membership *would* change if the
  two consumers switched from human-only to human-OR-passes-materiality — reviewed (by the
  user, and via cross-AI review per D-06) before either consumer's live query actually
  changes. Cutting over the two consumers' queries themselves may be a **separate, later
  phase** gated on this diagnostic's findings — do not assume cutover is in this phase's scope
  without re-confirming after the shadow-mode diagnostic lands.

### Threshold-selection philosophy
- **D-04:** Do not average or arbitrarily pick between Codex's (`abs(partial_beta) >= 0.35`,
  `sample_n >= 756`, sign-stable 3/4 windows), Fable's (peer-relative distribution check), or
  AGY's (`|beta| >= 0.30`, asset-class prior constraint) proposed numbers as if reconciling
  them produced a validated answer — none were derived from this corpus's actual distribution.
- **D-05:** Seed the more conservative of the three reviewers' thresholds as new
  `alpha.tag_calibrator.materiality.*` APR keys, each description explicitly marked
  `[initial_estimate]`/uncalibrated, matching this project's own APR-calibration-backlog
  convention (`docs/foundation/apr-calibration-backlog.md`) for exactly this situation.
  Empirical re-calibration (comparing the statistic's distribution across known-good
  human-tagged symbols vs. common-beta-only noise symbols) is real follow-up work, not
  required to ship this phase's shadow-mode measurement.

### Null-arm control
- **D-06:** Circular time-shift of the `factor_series` proxy's own return series — NOT a
  symbol-shuffle (tests the wrong null: "distinguishable from a random other symbol," and
  destroys the market-beta relationship the filter is supposed to be controlling for) and NOT
  a candidate-return shift (would also contaminate the market-beta control). Time-shifting
  only the factor proxy isolates whether the incremental loading survives once the temporal
  candidate-to-factor link is broken while the candidate-to-market link and the factor's own
  autocorrelation structure are preserved. Reuses the circular-shift null pattern already
  established in this codebase (`scripts/analysis/tsmom_per_symbol_ic_screen.py`) rather than
  inventing a new methodology.
- Must clear this null-arm control before any candidate's materiality flag is trusted — this
  generalizes the project's standing "any regime candidate must clear a null-arm (scrambled-
  data) control" rule (previously applied to HMM regimes only) to any auto-classifier gating
  a regime-adjacent label, per Fable's explicit framing during the todo-379 review.

### Cross-AI review
- **D-07:** Get Fable involved in reviewing the eventual PLAN.md/design for this phase before
  implementation — user explicitly authorized this ("feel free to use fable") for this
  specific piece of work, which clears the project's standing bar for Fable use (genuinely
  hard, ambiguous statistical/architecture design, not routine coding). Pair with Codex
  and/or AGY as the standing default, not Fable alone.

### Folded Todos
- **Todo 125** (`tag_calibrator-discovery-oos-gate-not-enforced`): TagCalibrator computes a
  `discovery_state: pending_oos` field but never enforces it — a first-pass discovery writes
  a fully live row immediately, identical to a confirmed one. Folded in as a hard requirement:
  this phase's materiality filter is what first makes newly-discovered empirical tags
  consumer-visible in a load-bearing way (today's stopgap ignores them entirely), so the
  pending-OOS gate becomes directly load-bearing rather than a latent gap. A newly-discovered
  empirical tag must not be materiality-eligible until `discovery_oos_days` of confirmation
  have elapsed.
- **Todo 126** (`instrument-tags-valid-to-no-consumer-contract`): no consumer currently
  filters on `valid_to` (expiry), "currently harmless" because no live consumer reads the
  `sensitivity`/`macro_driver` tags TagCalibrator expires. Folded in because this phase is
  exactly the change that ends that harmlessness: once an empirical tag can gate a live
  regime label via the materiality filter, an expired (`valid_to` set) row must not keep
  gating it. Both consumers' new materiality-aware queries must filter `valid_to IS NULL`.
  Note: this todo's file still references the now-deleted `equity_regime_model.py` (removed
  todo 381, 2026-09-17) — update/close it as stale alongside this phase's work rather than
  citing that file path.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### This phase's own design record
- `.planning/todos/completed/379-empirical-tags-contaminate-equity-breadth-and-peer-grouping.md` — the stopgap this phase extends, full resolution record.
- `.planning/todos/pending/380-itr-materiality-filtered-empirical-tags-and-eq-prefix-naming-collision.md` — this phase's source todo; all three reviewers' (Codex/Fable/AGY) complete original proposals.
- `docs/plans/2026-09-17-itr-source-filter-breadth-peer-grouping-design.md` — the original stopgap design doc.
- `.planning/todos/pending/125-tag-calibrator-discovery-oos-gate-not-enforced.md` — folded todo, discovery_oos_days enforcement.
- `.planning/todos/pending/126-instrument-tags-valid-to-no-consumer-contract.md` — folded todo, valid_to filtering (needs its own stale-reference correction to the deleted equity_regime_model.py path).

### ITR architecture
- `docs/foundation/instrument-tag-registry.md` — full ITR spec: tag lifecycle, `TagCalibrator`'s 3-pass measurement engine, `alpha.tag_calibrator.*` APR namespace, Known Gaps section (already flags `discovery_oos_days` unenforced and `sensitivity`/`macro_driver` tags unconsumed — this phase is the first concrete consumer design for those tags).
- `docs/foundation/adaptive-parameter-registry.md` — APR pattern this phase's threshold seeding follows; `docs/foundation/apr-calibration-backlog.md` for the uncalibrated-parameter convention.
- `production/migrations/343_itr_measurement_gap_fixes.sql` — the migration that wired `eq_low_vol`/`eq_momentum`/`eq_quality` as measurable; relevant precedent for how factor_series proxies get assigned.

### Related code (current state as of 2026-09-17)
- `services/tag_calibrator.py` — measurement engine this phase's Pass 4 extends.
- `src/intelligence/regime_signals/breadth_vol.py` — equity breadth consumer (the live successor to the deleted `equity_regime_model.py`, todo 381).
- `services/cross_sectional_regime_model.py` (`_load_tags_by_symbol`, `_resolve_group_symbols`) — peer-group consumer.
- `scripts/analysis/tsmom_per_symbol_ic_screen.py` — existing circular-shift null pattern to reuse for D-06.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `TagCalibrator`'s existing Pass 1 (measure) / Pass 2 (BH-FDR) / Pass 3 (decide) structure —
  the new orthogonalized-loading computation is a natural extension of Pass 1, not a parallel
  system.
- `scripts/analysis/tsmom_per_symbol_ic_screen.py`'s circular-shift null implementation —
  reuse directly for D-06 rather than reimplementing.
- `alpha.tag_calibrator.*` APR namespace (7 existing keys: `fdr_alpha`, `expiry_consecutive_fails`, `discovery_oos_days`, `min_sample_n`, `hac_max_lag`, `half_life_min_days`/`half_life_max_days`) — new materiality-threshold keys join this namespace.

### Established Patterns
- ConfigService/VocabularyService cache-at-init, consumer-reads-decided-state pattern — the
  precedent D-01/D-02 follow (measurement stays in one place, consumers read cheap cutoffs).
- Shadow-mode-before-cutover — already used for the portfolio covariance diagnostic and the
  `ic_engine.py` routing fix's own dry-run validation; D-03 follows the same discipline.
- `source='human'` vs `source='empirical'` distinction (todo 379) — this phase's materiality
  filter is the mechanism that makes `source='empirical'` rows trustworthy enough to join
  `source='human'` rows in identity-adjacent consumers, without collapsing the distinction
  todo 379 established.

### Integration Points
- `instrument_tags` schema — new evidence columns via migration.
- `services/tag_calibrator.py`'s `_apply_decision`/`insert_discovery`/`upsert_empirical` paths — Pass 4 hooks in here.
- `breadth_vol.py`/`cross_sectional_regime_model.py`'s tag-reading queries — read-time threshold application (shadow mode: diagnostic only, not live query changes, in this phase).

</code_context>

<specifics>
## Specific Ideas

User explicitly directed the discussion to be resolved via first-principles reasoning
("council of senior engineers," Renaissance/Jim Simons rigor) rather than a menu vote —
all four decisions above (D-01 through D-06) were reasoned through this way and presented
for confirmation; no pushback received, decisions stand as written.

</specifics>

<deferred>
## Deferred Ideas

### Reviewed Todos (not folded)
- **Todo 272** (`instrument-tag-peer-group-coverage-auditor`): a different capability (an
  audit tool for thin/missing tag coverage) than this phase's materiality filter. Related
  domain, kept separate to avoid scope creep — remains its own future todo.

The actual cutover of `breadth_vol.py`/`cross_sectional_regime_model.py`'s live queries
(vs. this phase's shadow-mode diagnostic) may become its own follow-on phase, gated on the
diagnostic's findings — see D-03.

</deferred>

---

*Phase: 175-itr-materiality-filtered-empirical-tags-for-breadth-peer-gro*
*Context gathered: 2026-09-18*
