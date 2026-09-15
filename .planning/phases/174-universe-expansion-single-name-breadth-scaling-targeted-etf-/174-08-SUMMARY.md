---
phase: 174-universe-expansion-single-name-breadth-scaling-targeted-etf
plan: 08
subsystem: database
tags: [apr, pandas-qcut, stratified-sampling, russell-3000, instrument-onboarding, reproducibility]

# Dependency graph
requires:
  - phase: 174-03
    provides: "onboard_instrument() -- the single sanctioned instrument-onboarding code path"
  - phase: 174-04
    provides: "parse_holdings()/fetch_holdings() -- validated Russell 3000 population sourcing, corrected IWV endpoint"
provides:
  - "alpha.universe.* APR keys (migration 339): stratified_sample_random_state, cap_bucket_count, target_sample_size"
  - "stratified_sample() -- pure, qcut-bucketed, APR-seeded, reproducible market-cap-stratified draw"
  - "scripts/infrastructure/universe_expansion_stratified_sourcing.py main() -- dry-run-by-default CLI, writes only via onboard_instrument()"
affects: [174-12]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Shared _bucket_population() helper so a pure draw function and its CLI report can never compute qcut boundaries differently"
    - "Deterministic, RNG-free target-size allocation across buckets with iterative capacity-shortfall redistribution"
    - "Gateway pre-flight probe (one qualify_instrument() call against a known-good existing symbol) before a bulk onboarding loop, to fail loud instead of mass-rejecting"

key-files:
  created:
    - production/migrations/339_universe_sampling_apr_keys.sql
    - scripts/infrastructure/universe_expansion_stratified_sourcing.py
    - tests/unit/scripts/test_universe_expansion_stratified_sourcing.py
  modified: []

key-decisions:
  - "Every sampled single-name equity is tagged eq_broad only -- Plan 04's parse_holdings() narrow three-column contract (symbol/name/market_cap) carries no sector/value/growth data through to this script, so a finer eq_* split isn't derivable here without a second data source. A follow-on re-tagging pass is a separate task, not this plan's scope."
  - "Bucket bounds (cap_bucket_min/cap_bucket_max) are carried on every drawn row, computed via a shared _bucket_population() helper the draw and the CLI summary both call, so 'lowest bucket' can never be ambiguous or drift between what was drawn and what is reported."
  - "Remainder allocation and capacity-shortfall redistribution are both RNG-free and iterative -- allocation must stay reproducible independent of the seeded draw that follows it, and must converge even when one bucket's true population is smaller than its even-split allocation."

requirements-completed: [D-01, D-02, D-03, V5]

# Metrics
duration: ~20min
completed: 2026-09-15
---

# Phase 174 Plan 08: Market-Cap-Stratified Sampling Script Summary

**`stratified_sample()` -- a pure, pandas.qcut-bucketed, APR-seeded draw over Plan 04's Russell 3000 population, proven reproducible/seed-sensitive/stratum-balanced by 13 unit tests, plus a dry-run-by-default CLI that writes only through Plan 03's onboard_instrument() and refuses to draw until `alpha.universe.target_sample_size` is set from a real measurement (D-01).**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-09-15T11:05:00Z (approx, first file read)
- **Completed:** 2026-09-15T11:21:37Z
- **Tasks:** 3/3
- **Files modified:** 3 (all new)

## Accomplishments

- Registered `alpha.universe.stratified_sample_random_state` (default 42, `[user_preference]`), `alpha.universe.cap_bucket_count` (default 10, `[initial_estimate]`), and `alpha.universe.target_sample_size` (default 0 = UNSET, `[initial_estimate]`) via migration 339, following migration 307's paired `config_schema`/`config_state` INSERT pattern. Applied live, verified idempotent (re-run produced zero row changes), and confirmed loadable through `ConfigService`'s `alpha.` allowlist prefix.
- `stratified_sample()` (pure, no I/O) draws a market-cap-stratified sample: excludes already-onboarded symbols before bucketing, buckets via `pandas.qcut(labels=False, duplicates="drop")`, asserts per-bucket mean market cap is monotonically non-decreasing (guarding against a silent qcut-ordering reversal that would invert the entire down-cap reading of the sample), allocates the target size across buckets deterministically (remainder to the smallest-cap buckets, RNG-free), and draws within each bucket using a single `np.random.default_rng(seed)` created once and used sequentially in ascending bucket order.
- CLI `main()` fetches all three APR values live at run start, fails loud naming `alpha.universe.target_sample_size` when it is still 0, writes a timestamped dry-run CSV with a correct per-bucket population/drawn summary table, and gates `--commit` mode behind a gateway pre-flight probe (one `qualify_instrument()` call against a known-good existing corpus symbol) that aborts before the onboarding loop starts if `ib-gateway` is unreachable -- otherwise a stopped gateway would silently mass-reject every symbol and look like a data problem (T-174-50).
- 13 unit tests (exceeds the 12-case spec) cover reproducibility (list-order equality), seed sensitivity, even stratum balance, deterministic remainder allocation (directed at buckets 0/1/2), capacity-shortfall redistribution, population exhaustion, pre-bucketing exclusion (boundaries shift measurably), unset/negative `target_size` crash-loud, no-duplicates, ascending bucket ordering, and bucket-bounds correctness -- all synthetic-fixture, zero DB/network. Full `tests/unit/` suite stays green (2 pre-existing unrelated skips).

## Task Commits

Each task was committed atomically:

1. **Task 1: Migration 339 -- alpha.universe.* sampling APR keys** - `ee1a36bee` (feat)
2. **Task 2: Stratified sampling script with a seeded, reproducible draw** - `21ed6d4da` (feat)
3. **Task 3: Unit coverage for reproducibility, stratum balance, and the unset-target guard** - `1da53fb8e` (test)

_Plan metadata commit follows this summary._

## Files Created/Modified

- `production/migrations/339_universe_sampling_apr_keys.sql` -- three `alpha.universe.*` APR keys, applied live and idempotency-verified.
- `scripts/infrastructure/universe_expansion_stratified_sourcing.py` -- `stratified_sample()`, `_bucket_population()`, `_allocate_target()`, `main()`; 377 lines.
- `tests/unit/scripts/test_universe_expansion_stratified_sourcing.py` -- 13 tests against synthetic population fixtures; 244 lines.

## Decisions Made

- **Single `eq_broad` tag for every sampled name.** The plan's `<interfaces>` section notes several candidate exposure tags (`eq_broad`/`eq_sector`/`eq_sub_sector`/`eq_small_cap`/`eq_value`/`eq_growth`) but Plan 04's `parse_holdings()` narrow three-column contract carries no sector/value/growth signal through to this script -- tagging by anything finer than `eq_broad` would require inventing data, not using it. Documented in the script's own header comment as a deliberate scope boundary, with a follow-on re-tagging pass flagged as separate work.
- **`_bucket_population()` factored out as a shared helper.** Initially the CLI's per-bucket summary table was passed the raw (un-bucketed, pre-exclusion) population, producing a fixed-but-wrong "population" column (see Deviations below). Rather than duplicating the qcut-bucketing logic in two places (draw vs. report) with the risk of the two silently diverging, both `stratified_sample()` and the CLI's summary printer now call the same `_bucket_population()` helper.
- **Gateway probe client ID 45.** Distinct from other in-repo IBKR client IDs already in use (40 default backfill, 44 chunk/rate-limit probe, 48 `personal_cost_hurdle.py`), all under `ibkr.py`'s `_MAX_CLIENT_ID=50` ceiling. Documented inline for future scripts to avoid collision.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Dry-run per-bucket population count was wrong**
- **Found during:** Task 2, live sanity-testing the dry-run path against the real IWV file (not part of the plan's stated verify command, but done before committing per this project's "measure, don't defer" convention)
- **Issue:** `_print_bucket_summary()` was passed the raw, pre-exclusion, un-bucketed `population` frame. Since that frame has no `cap_bucket` column, the population-count lookup silently fell back to `len(rows)` (the drawn count) for every bucket -- every row of the printed table showed `population == drawn`, which is wrong whenever the population is larger than the sample (always, in practice) and would have made the dry-run's own audit artifact misleading about how large each stratum actually is.
- **Fix:** Extracted `_bucket_population()` (exclusion + `pandas.qcut` bucketing) as a helper shared by `stratified_sample()` and the CLI's summary printer, so both compute bucket boundaries and membership identically. `main()` now calls `_bucket_population()` once for the summary table, separately from the sample draw.
- **Files modified:** `scripts/infrastructure/universe_expansion_stratified_sourcing.py`
- **Verification:** Re-ran the dry-run against the real 2,564-row IWV holdings file with `alpha.universe.target_sample_size` temporarily set to 30 -- population column now correctly shows ~244 per bucket (2,311 post-exclusion population / 10 buckets) instead of the flat "3" (== drawn count) it showed before the fix. Reset the APR key back to 0 afterward, per the plan's explicit instruction not to leave a non-zero target size set by this plan.
- **Committed in:** `21ed6d4da` (Task 2 commit -- fixed before the task's own commit, not a separate deviation commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** The fix was caught and corrected before Task 2's commit landed, so the committed code never carried the bug. No scope creep -- purely a correctness fix to the CLI's own audit output.

## Issues Encountered

- **Worktree had no `.venv`.** Symlinked `.venv -> /home/bg/dev/indicagent/.venv` at the start of this session, matching Plans 03/04's documented resolution for this known GSD-worktree gap.
- **Worktree HEAD required a `git reset --hard` to the correct phase base** (`0fcc363ff`) at spawn time -- the branch's initial HEAD (`763c23eac`) predated Plan 174's wave-1 tracking commit and was not a descendant of the expected base. Followed the mandatory `<worktree_branch_check>` protocol exactly (assert-then-reset to the named base commit, never self-recovering by force-rewinding a protected ref); this landed cleanly with no lost work since the reset moved the branch strictly forward onto a commit already merged to main.

## User Setup Required

None -- no external service configuration required. `ib-gateway`'s current stopped state (noted in RESEARCH.md) does not block this plan: dry-run mode never touches the gateway, and `--commit` mode is explicitly out of this plan's scope (Plan 12 owns the real run).

## Next Phase Readiness

- Plan 12 can now import `stratified_sample()` directly and call `main() --commit` once Plan 11 sets `alpha.universe.target_sample_size` from a measured ic_engine scale-up result -- no further sourcing/sampling design work remains.
- All three `alpha.universe.*` APR keys are live and confirmed loadable through `ConfigService`. `target_sample_size` is confirmed left at 0 (unset) as of this plan's completion, per D-01 -- this plan drew samples only transiently during its own dry-run sanity testing (never with `--commit`) and reset the key back to 0 afterward.
- No blockers for Plan 12 from this plan's work. The `_SAMPLE_TAGS = (("eq_broad", ...),)` single-tag default is a known, intentionally-scoped simplification a future sector/factor re-tagging pass can build on if the planner wants finer stratification-by-tag later.

---
*Phase: 174-universe-expansion-single-name-breadth-scaling-targeted-etf*
*Completed: 2026-09-15*

## Self-Check: PASSED

- FOUND: production/migrations/339_universe_sampling_apr_keys.sql
- FOUND: scripts/infrastructure/universe_expansion_stratified_sourcing.py
- FOUND: tests/unit/scripts/test_universe_expansion_stratified_sourcing.py
- FOUND commit: ee1a36bee (Task 1)
- FOUND commit: 21ed6d4da (Task 2)
- FOUND commit: 1da53fb8e (Task 3)
