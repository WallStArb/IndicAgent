---
phase: 139
reviewers: [codex]
reviewed_at: 2026-06-23T23:51:02Z
plans_reviewed: [139-P1-PLAN.md, 139-P2-PLAN.md, 139-P3-PLAN.md]
notes: >
  antigravity on this machine resolves to a VS Code-like IDE launcher (v1.107.0), not the Google AI CLI.
  Ollama (qwen3.5:4b) timed out on a 133-line prompt.
  Claude skipped (self — running inside Claude Code).
  Codex produced substantive findings; four HIGH concerns verified against codebase before writing.
---

# Cross-AI Plan Review — Phase 139

## Codex Review

**Summary**

P1 and P2 are directionally good, but they are not yet internally consistent. The biggest problems are a mathematically infeasible weighting spec, a missing `topic` argument in the Kafka publish call, and a hypertable key design that won't work as written. P3 is reasonable as a read-only report wave, but it is too thin to validate the phase goals on its own. Overall risk is high until the math and storage contracts are tightened.

**Strengths**

- The plan preserves the project's core architecture: pure math in `src/intelligence/`, batch services in `services/`, and shadow-only emission.
- It correctly avoids the old `precomputed=` bypass and keeps the single-source-of-truth math pattern.
- It respects key operational rules: `asyncpg`, `msg=` on Kafka publish, `await` on publish, UTC timestamps, and structured logging.
- The `effective_n` gate and `top_features NOT NULL` invariant show good awareness of data-quality risks.
- P3 correctly treats the report as read-only and allows "NO DATA" instead of crashing.

**Concerns**

- **P1, HIGH:** `alpha.ensemble.max_feature_weight = 0.20` conflicts with `alpha.ensemble.min_passing_features = 3`. With only 3–4 features, no valid weight vector exists: 3 × 0.20 = 0.60 ≠ 1.0 and 4 × 0.20 = 0.80 ≠ 1.0. The iterative proportional redistribution algorithm will never converge. Fix: raise `min_passing_features` to 5 (floor where 5 × 0.20 = 1.0 is achievable), or implement a fallback that relaxes the cap when uncapped features cannot absorb the excess.
- **P1/P2, HIGH:** `alpha_events` is specified as a TimescaleDB hypertable on `bar_ts` with `PRIMARY KEY (event_id)`. TimescaleDB cannot enforce unique constraints that do not include the partitioning column. Every existing hypertable in the project includes the time column in its PK (e.g., migration 160: `PRIMARY KEY (symbol, tf, bar_ts)`). Fix: change PK to `(event_id, bar_ts)`, or explicitly drop the PK and rely on the `ON CONFLICT` guard at the application layer.
- **P2, HIGH:** The plan specifies `await self._producer.publish(msg=payload)`, but the actual signature in `src/core/kafka_utils.py:95` is `publish(self, topic: str, msg: dict, key: str | None = None)`. The `topic` positional argument is missing in the plan. AlphaEmitter must pass `topic=topic_alpha_events(settings.env_name)` as the first argument.
- **P2, HIGH:** The emission gate `alpha_ci_lower > 0` suppresses every short signal. A negative alpha score produces a CI such as `(-3.0, -0.5)`, where `ci_lower = -3.0` never satisfies `> 0`. The gate must be direction-aware: long emits when `alpha_ci_lower > 0`; short emits when `alpha_ci_upper < 0`.
- **P1, MEDIUM:** The phase goal says "Ledoit-Wolf shrinkage covariance → ensemble_weights," but the described weight algorithm is IC-Sharpe redistribution. As written, covariance is computed for OTel diagnostics only and does not influence the weight vector. If LW is intentionally diagnostic only, rename the step in the phase goal and architecture doc to avoid confusion. If it should influence weights, specify the exact formula (e.g., eigendecomposition-based deflation, or Markowitz minimum-variance under IC Sharpe expected returns).
- **P2, MEDIUM:** APR loading via a direct `SELECT ... FROM config_state WHERE config_key LIKE 'alpha.%'` bypasses the `ConfigService` cache and hot-reload path. The rest of the system uses `ConfigService.get_sync()`. Consider prewarm via `load_config_service_sync()` (as in `ic_engine.py`) or an equivalent that routes through the established config path.
- **P2, MEDIUM:** The emission gate handles the all-negative weight case (`effective_n < gate`) with a rejection counter, but `compute_alpha_score()` with a zero-sum weight vector would produce `alpha_score = 0.0` and CI `(0.0, 0.0)`. The emitter should skip entirely when `effective_n = 0` before entering gate logic.
- **P2, MEDIUM:** `alpha_events` idempotency is confirmed via `ON CONFLICT DO NOTHING`, but the plan does not specify what column set the conflict target uses, which is required when the PK changes (see HIGH above).
- **P3, MEDIUM:** The report wave is too shallow for a phase-completion artifact. It should include an upstream readiness table (row counts for `feature_vectors`, `forward_returns`, `feature_ic_scores` with `passes_walkforward=true`, `ensemble_weights`, `ensemble_alpha`, `alpha_events`) and rejection reason breakdowns so operators can diagnose blockage without querying the DB manually.
- **P1, LOW:** `select_features_per_stratum()` keeps the max-IC-Sharpe row per feature_name, but the plan does not specify a deterministic tie-break when two lookaheads have identical IC Sharpe. Add `ORDER BY ic_sharpe DESC, lookahead_bars ASC LIMIT 1` or equivalent in the Python groupby logic.
- **P3, LOW:** The report should include threshold calibration diagnostics (e.g., distribution of `abs(alpha_score)` vs the per-TF thresholds) to show the transaction-cost model basis, otherwise the "empirical threshold" remains a label rather than a documented calibration.

**Suggestions**

- Raise `alpha.ensemble.min_passing_features` APR default to 5 in migration 168.
- Fix emission gate to be direction-aware (separate `ci_lower > 0` for longs, `ci_upper < 0` for shorts).
- Add `topic` as first argument in AlphaEmitter's publish call: `await self._producer.publish(topic_alpha_events(settings.env_name), msg=payload)`.
- Change `alpha_events` PK to `(event_id, bar_ts)` to satisfy TimescaleDB partitioning constraint.
- Add a deterministic tie-break in `select_features_per_stratum()`.
- Guard emitter against zero-weight strata before any CI math.
- Add `min_passing_features` check in the emitter too (skip stratum if fewer than N features have non-zero weight after derive_weights).
- Clarify whether LW is diagnostic-only or influences weights; update the phase goal description to match.
- Expand P3 report to include upstream row counts and per-TF rejection reason breakdowns.

**Risk Assessment**

**High.** The plan is close on plumbing, but four independently verifiable HIGH defects exist: cap/min-feature math infeasibility, TimescaleDB PK constraint, missing Kafka topic argument, and sign-inconsistent emission gate. All four are correctness bugs, not style issues. Fix before execution.

---

## Consensus Summary

Only one reviewer (Codex) produced substantive output. No multi-reviewer consensus possible, but all four HIGH findings were independently verified against the live codebase:

| Finding | Verified against | Result |
|---------|-----------------|--------|
| Kafka `publish()` missing `topic` arg | `src/core/kafka_utils.py:95` | **CONFIRMED** — signature is `publish(self, topic: str, msg: dict, ...)` |
| Weight cap infeasibility (3 features × 0.20 ≠ 1.0) | Math | **CONFIRMED** — 3 × 0.20 = 0.60; iterative redistribution cannot converge |
| `alpha_events` PK incompatible with TimescaleDB hypertable | `production/migrations/160_ic_engine_tables.sql:50` — all existing hypertable PKs include `bar_ts` | **CONFIRMED** |
| Emission gate `ci_lower > 0` suppresses all shorts | Math | **CONFIRMED** — short signals have negative CI; need direction-aware gate |

### Agreed Strengths

- Architecture SoC is clean: pure math in Ring 1 module, services as thin compute shells.
- Crash-loud startup gates prevent silent empty runs — correct failure mode.
- `top_features NOT NULL` invariant and `effective_N >= 3.0` gate are the right data integrity choices.
- Shadow-only mode with ON CONFLICT idempotency is the right operational posture for first run.

### Agreed Concerns (all from single reviewer but codebase-verified)

1. **[P2, HIGH] Kafka publish missing `topic` argument** — will crash at runtime on first emit attempt.
2. **[P1, HIGH] Weight cap infeasibility with `min_passing_features = 3`** — `derive_weights()` cannot converge for strata with fewer than 5 features.
3. **[P1/P2, HIGH] `alpha_events` hypertable PK excludes `bar_ts`** — TimescaleDB will reject or silently not enforce the unique constraint.
4. **[P2, HIGH] Emission gate sign bug** — `alpha_ci_lower > 0` will suppress 100% of short emissions.

### Divergent Views

N/A — single reviewer.

---

## Recommended Pre-Execution Fixes

These four HIGH items should be corrected in the plan files before `/gsd-execute-phase 139` is run:

1. **P1 migration 168 + P1 APR seed:** Change `alpha.ensemble.min_passing_features` default from `3` to `5`.
2. **P1 migration 168 DDL:** Change `alpha_events` PRIMARY KEY to `(event_id, bar_ts)`.
3. **P2 AlphaEmitter Task 2:** Update publish call spec to `await self._producer.publish(topic_alpha_events(settings.env_name), msg=payload)`.
4. **P2 AlphaEmitter Task 2:** Fix emission gate to direction-aware: `(alpha_score > 0 AND alpha_ci_lower > 0) OR (alpha_score < 0 AND alpha_ci_upper < 0)`.
