---
phase: 174-universe-expansion-single-name-breadth-scaling-targeted-etf
plan: 15
subsystem: analysis
tags: [pre-registration, gate, correlation-structure, instrument-onboarding, apr, ibkr-backfill]

# Dependency graph
requires:
  - phase: 174-10
    provides: "--dimension flag on infrastructure_run_historical_pipeline.py; the Corpus Pipeline Gotcha UPSERT pattern for backfill_status when the fetch script itself doesn't write that table"
  - phase: 174-13
    provides: "instruments.compute_eligible_1d column, COMPUTE_READY_1D_PREDICATE_SQL, get_active_contracts(dimension='compute_1d')"
  - phase: 174-14
    provides: "universe_expansion_correlation_structure_check.py, evaluate_d10_gate(), the two pre-registered D-10 thresholds as literal code constants"
provides:
  - "alpha.universe.pilot_sample_size APR key (migration 342), distinct from target_sample_size"
  - "universe_expansion_pilot_draw.py -- pilot-sized draw reusing stratified_sample()/_run_commit() directly, 1d-only backfill seeding"
  - "universe_expansion_promote_compute_eligible.py -- re-runnable dimension-aware promotion tool (compute / compute_1d), reusable by Plan 12"
  - "docs/research/phase174-down-cap-correlation-gate-verdict.md -- D-10 VERDICT: FAIL, with measured numbers and a pivot recommendation"
  - "40-symbol down-cap pilot cohort in the corpus: real 1d history, compute_eligible_1d=true, compute_eligible=false, tagged eq_broad + single_name_equity"
affects: [174-11-ic-engine-scale-measurement, 174-12-full-scale-down-cap-draw]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dedicated pilot-size APR key kept structurally separate from the full-draw APR key, with a start-up assertion that the full-draw key is still unset -- proves at run time that a small-scale gate run cannot silently borrow or defeat a crash-loud guard meant for the large-scale run"
    - "Promotion tool selects both a target column and a predicate constant from one module-owned literal dict keyed by a caller-supplied dimension string, never building either from argv text -- same structural pattern as settings.py's _ACTIVE_CONTRACTS_DIMENSION_CLAUSES"
    - "A str.format() column-name substitution kept textually distinct from parameterized value binding in the same UPDATE, specifically to satisfy a literal-grep acceptance check auditing for accidental SQL-injection-shaped f-string construction"

key-files:
  created:
    - production/migrations/342_universe_pilot_sample_size_apr_key.sql
    - scripts/infrastructure/universe_expansion_pilot_draw.py
    - scripts/infrastructure/universe_expansion_promote_compute_eligible.py
    - docs/research/phase174-down-cap-correlation-gate-verdict.md
  modified: []

key-decisions:
  - "D-10's gate FAILED on both pre-registered thresholds by a wide margin (unconditional 0.3025 vs <=0.10 threshold, 3.0x miss; high_bear 0.4303 vs <=0.30 threshold, 1.4x miss) -- Plan 11 must leave alpha.universe.target_sample_size at 0, and Plan 12's full-scale down-cap draw must not proceed under the current (unbiased market-cap-stratified-random) construction."
  - "The union-cohort diagnostic (pilot + existing 128-name book, non-gating) shows the pilot does not diversify against the existing book either -- the union's correlation numbers are a simple size-weighted blend of the two halves, not a meaningfully lower combined number, reinforcing rather than complicating the FAIL verdict."
  - "This verdict is NOT added to construction-verdict-ledger.md: that ledger's own stated scope is predictive-signal/IC hypothesis tests, explicitly excluding infrastructure/data-population diagnostics unless they were themselves the thing under test. No IC/edge measurement was made against this cohort."
  - "The 40-symbol pilot cohort stays in the corpus (data-retention principle) at compute_eligible_1d=true, compute_eligible=false -- a real, cheaply-acquired down-cap measurement asset regardless of the FAIL verdict, not deleted or hidden."

requirements-completed: [D-01, D-02, D-03, D-09, D-10, V5]

# Metrics
duration: ~20min
completed: 2026-09-16
---

# Phase 174 Plan 15: D-10 Down-Cap Pilot Gate Summary

**The pre-registered D-10 gate ran against a real, mechanically-drawn 40-symbol down-cap pilot (1d-only backfill, 195,898 bars, 0 fetch errors) and FAILED both thresholds by a wide margin -- unconditional avg pairwise correlation 0.3025 vs <=0.10 (3.0x miss), high_bear 0.4303 vs <=0.30 (1.4x miss) -- leaving `alpha.universe.target_sample_size` at 0 and blocking Plan 12's full-scale draw under the current design.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-09-16T09:29:00-04:00 (approx, worktree branch check)
- **Completed:** 2026-09-16T09:46:06-04:00
- **Tasks:** 3/3 completed
- **Files modified:** 4 (all new)

## Accomplishments

- Registered `alpha.universe.pilot_sample_size` (default 40, migration 342) as a key structurally separate from `alpha.universe.target_sample_size` -- applied live, idempotency-verified (re-run: 0 row changes).
- Built `universe_expansion_pilot_draw.py`, which imports and calls Plan 08's `stratified_sample()`/`_run_commit()` directly (no re-derivation), asserts `target_sample_size == 0` before AND after the commit run, rejects a pilot size outside [30, 50] without an explicit `--allow-out-of-range --reason`, and stops with a named finding rather than proceeding if the draw fails to reach the smallest market-cap bucket.
- Live `--commit` run drew and onboarded exactly 40 symbols (0 rejected, all qualified against IBKR), 4 of which landed in the smallest-cap decile (`cap_bucket=0`), confirming the draw genuinely reached down-cap. All 40 tagged both `eq_broad` (via `_run_commit`, unmodified) and `single_name_equity` (via a separate, additive statement this plan added) -- both `source='human'`.
- Backfilled the pilot at 1d only via the existing historical pipeline (`--timeframes 1d --dimension backfill --client-id 46`, `setsid`-detached): 195,898 bars, 0 fetch errors, ~2.5 minutes wall clock against a ~40-request/~few-minute estimate (`chunk_days.1d=7300` covers 20 years in one request per symbol; rate limit 58/600s -- nowhere near pacing). Zero non-1d rows created for any pilot symbol.
- Confirmed (again, same gap Plan 10 found) that `infrastructure_run_historical_pipeline.py` never writes `backfill_status` -- set `fetch_complete=true` from independently verified `market_data_ohlcv_tradeable` evidence, scoped to the 40 pilot symbols at `tf='1d'` only.
- Built `universe_expansion_promote_compute_eligible.py`: `--dimension {compute,compute_1d}` maps through a module-owned literal dict to both the target column and the imported predicate constant (`COMPUTE_READY_PREDICATE_SQL` / `COMPUTE_READY_1D_PREDICATE_SQL`, never retyped). Ran once with `--dimension compute_1d --commit`: 42 candidates (the 40 pilot symbols plus EMLC/VIXY, both already 1d-complete from Plan 10 but not yet `compute_eligible_1d`), all promoted. `get_active_contracts(dimension='compute')` unchanged at 233; `dimension='compute_1d'` grew by exactly 42 (231 -> 273).
- Ran the D-10 gate (`--gate`) against the pilot: exit code 2 (FAIL). Coverage filter dropped 13/40 pilot symbols (32.5%, materially higher than the baseline's 8.6%), realized N=27. Recorded per-symbol coverage for all 13 drops and an explicit stability statement.
- Ran two non-gating diagnostics: the pilot's full per-regime table (set beside the 117-name baseline from `174-14-SUMMARY.md`), and a union-cohort run (pilot + existing 128-name book = 168 symbols, 144 after coverage filter) showing the pilot does not diversify against the existing book either -- the union's numbers are a simple size-weighted blend, not a materially lower combined figure.
- Wrote `docs/research/phase174-down-cap-correlation-gate-verdict.md`: `**VERDICT:** FAIL`, both thresholds quoted verbatim from D-10 with the Plan 14 commit hash (`ec84788fb`) that introduced them, the full measured-numbers table, the coverage-filter accounting, the non-gating union and SPY-residualized diagnostics (each with an interpretation paragraph), and a `Pivot recommendation` section naming three candidate next moves without deciding among them.
- Verified `alpha.universe.target_sample_size` reads `0` before Task 1's commit, immediately after, and again after Task 3 -- three independent checkpoints, all `0`.
- Full `tests/unit/` suite green (0 failures, 2 pre-existing unrelated skips) after every task.

## Task Commits

Each task was committed atomically:

1. **Task 1: Draw the pilot and onboard it with 1d-only backfill seeds** - `84fab8e5d` (feat)
2. **Task 2: 1d-only backfill and the dimension-aware promotion tool** - `2e777cf20` (feat)
3. **Task 3: Run the D-10 gate and record the verdict** - `1a0dce796` (docs)

**Plan metadata:** this SUMMARY's own commit (docs: complete plan) -- committed separately per worktree convention.

## Files Created/Modified

- `production/migrations/342_universe_pilot_sample_size_apr_key.sql` -- registers `alpha.universe.pilot_sample_size` (default 40), applied live and idempotency-verified.
- `scripts/infrastructure/universe_expansion_pilot_draw.py` -- pilot-sized draw reusing Plan 08's `stratified_sample()`/`_run_commit()` directly; `--pilot-size` override, `--allow-out-of-range`, `--dry-run` (default) / `--commit`.
- `scripts/infrastructure/universe_expansion_promote_compute_eligible.py` -- `--dimension {compute,compute_1d}` promotion tool, module-owned literal dict, `--dry-run` (default) / `--commit`.
- `docs/research/phase174-down-cap-correlation-gate-verdict.md` -- the D-10 verdict document.

## Decisions Made

- **D-10's gate FAILED on both pre-registered thresholds.** Unconditional avg pairwise correlation 0.3025 (threshold <=0.10, misses by 3.0x); `high_bear` avg pairwise correlation 0.4303 (threshold <=0.30, misses by 1.4x). This is a real, wide-margin failure on a mechanically-drawn, down-cap-reaching sample -- not a marginal miss that further pilot iterations would plausibly close.
- **The pilot's per-regime correlation structure is essentially indistinguishable from the existing large/mega-cap book's**, regime by regime (see the full table in the verdict document). Down-cap market-cap stratification alone did not produce a materially less-correlated population.
- **The union-cohort diagnostic (non-gating) reinforces the FAIL**, rather than complicating it: the union's numbers are a simple size-weighted blend of the pilot-alone and baseline-alone numbers, meaning the pilot does not diversify meaningfully against the existing book either.
- **Not added to `construction-verdict-ledger.md`.** That ledger's own stated scope covers predictive-signal/IC hypothesis tests, explicitly excluding infrastructure/data-population diagnostics unless they were themselves the thing under test. This plan measured correlation structure, not IC or tradeable edge -- no `feature_ic_scores`/`alpha_ensemble_ic` measurement was made against this cohort. Recorded in the verdict document's own closing section with the reasoning, so this is not left ambiguous.
- **The 40-symbol pilot cohort stays in the corpus** (data-retention principle) at `compute_eligible_1d=true, compute_eligible=false` -- a real, cheaply-acquired measurement asset regardless of the FAIL verdict.
- **Client ID 46** used for the pilot backfill launch -- distinct from all other in-repo IBKR client IDs already in use (35 provider, 40 pipeline default, 41 Plan 10's backfill, 44 chunk probe, 45 Plan 08's gateway probe, 48 cost-hurdle), confirmed via `ps aux` before launch.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `infrastructure_run_historical_pipeline.py` does not write `backfill_status` -- set the checkpoint from verified evidence (repeat of a gap Plan 10 already found and documented)**
- **Found during:** Task 2, post-fetch verification
- **Issue:** After the 1d-only backfill completed cleanly (195,898 bars, 0 fetch errors), `backfill_status.fetch_complete` for the 40 pilot symbols at `tf='1d'` still read `false` -- the fetch script never writes that table (confirmed the same gap Plan 10's SUMMARY already documented for a different symbol set).
- **Fix:** Independently verified non-zero, listing-date-consistent `market_data_ohlcv_tradeable` rows for all 40 symbols at `1d` first, then ran CLAUDE.md's own already-documented Corpus Pipeline Gotcha UPSERT pattern, scoped to the 40 pilot symbols and `timeframe = '1d'` only (never corpus-wide, never any other timeframe).
- **Files modified:** none (database-only action; the pattern already exists as documented practice, carried forward from Plan 10's prior discovery of the same gap).
- **Verification:** `SELECT count(*) FROM backfill_status WHERE symbol = ANY(<pilot list>) AND tf='1d' AND fetch_complete` -> 40, reached before the promotion `UPDATE` ran; `SELECT count(*) FROM backfill_status WHERE symbol = ANY(<pilot list>) AND tf <> '1d'` -> 0 throughout.
- **Committed in:** n/a (data-only; folded into Task 2's commit message, no file to commit for this specific step).

**2. [Rule 1 - Bug] Acceptance-criteria literal grep would have failed on a docstring's own explanatory prose, not real SQL**
- **Found during:** Task 1, pre-commit verification of `universe_expansion_pilot_draw.py`
- **Issue:** The module docstring quoted the literal phrase `INSERT INTO instruments` while explaining why this script must not add a third unsanctioned writer to that table -- an explanatory reference, not real SQL -- but the plan's acceptance criteria greps for that exact literal substring and requires zero occurrences, since the check exists to catch a real bypass of `onboard_instrument()`, not to distinguish comment from code.
- **Fix:** Reworded the docstring to convey the identical meaning ("unsanctioned direct writers into the instruments table") without the literal substring.
- **Files modified:** `scripts/infrastructure/universe_expansion_pilot_draw.py`
- **Verification:** `grep -c "INSERT INTO instruments" scripts/infrastructure/universe_expansion_pilot_draw.py` -> 0; ruff clean; no functional code change.
- **Committed in:** `84fab8e5d` (Task 1 commit -- fixed before the task's own commit, not a separate deviation commit).

**3. [Rule 1 - Bug] Ruff's own auto-fix suggestion would have violated the plan's acceptance criteria**
- **Found during:** Task 2, ruff check of `universe_expansion_promote_compute_eligible.py`
- **Issue:** Ruff's `UP032` rule recommended converting the promotion tool's `str.format()`-built UPDATE statement into an f-string -- but the plan's acceptance criteria explicitly requires `grep -cE 'f"""?\s*UPDATE|f"UPDATE'` to return 0, specifically to keep the column-name substitution mechanism visually distinct from the parameterized `%(symbols)s` value binding in the same statement.
- **Fix:** Kept the `str.format()` construction and suppressed `UP032` with a targeted `# noqa` comment placed on the statement's opening line (a multi-line statement attributes the diagnostic to its first line, not the line containing `.format()`), with an inline comment explaining why the suppression is deliberate.
- **Files modified:** `scripts/infrastructure/universe_expansion_promote_compute_eligible.py`
- **Verification:** `.venv/bin/ruff check` passes clean; `grep -cE 'f"""?\s*UPDATE|f"UPDATE'` -> 0.
- **Committed in:** `2e777cf20` (Task 2 commit -- fixed before the task's own commit, not a separate deviation commit).

---

**Total deviations:** 3 auto-fixed (1 blocking, 2 bugs -- both bugs were literal-grep/lint-tooling frictions caught and fixed before any commit landed, not functional defects)
**Impact on plan:** None of these changed the plan's design or scope. #1 repeats a documented, already-understood gap from Plan 10 (not a new discovery); #2 and #3 are wording/lint-suppression fixes with zero functional code impact, both resolved before their respective task commits.

## Issues Encountered

- This worktree spawned without its own `.venv`/`.env` (both gitignored) -- symlinked both from the main checkout (`ln -s /home/bg/dev/indicagent/.venv .venv`, `ln -s /home/bg/dev/indicagent/.env .env`), matching the pattern documented in every prior Phase 174 plan's SUMMARY.
- The worktree branch's HEAD was found behind the plan's declared base commit at spawn time (on `763c23eac`, expected a descendant of `068f1f1b5`) -- per the `<worktree_branch_check>` protocol, the branch was reset (`git reset --hard 068f1f1b5`) to the correct base before any file reads or edits began. The working tree was clean at that point, so no work was at risk.

## User Setup Required

None -- no external service configuration required. `ib-gateway` was already `Up` at session start (confirmed via `docker ps`), consistent with Plan 10's finding that it recovered via the IBC nightly auto-restart.

## Next Phase Readiness

- **Plan 11 (ic_engine scale measurement) must leave `alpha.universe.target_sample_size` at 0.** D-10's gate FAILED; per the plan's own pre-registered branching, this key stays unset and Plan 12's full-scale down-cap draw must not proceed under the current (unbiased market-cap-stratified-random) construction.
- **Plan 12's full-scale down-cap draw is structurally blocked**, not just conventionally discouraged: `universe_expansion_stratified_sourcing.py`'s `_async_main()` returns exit code 1 with a `FAILED:` message whenever `target_sample_size <= 0` -- already merged, unit-tested code (Plan 08), unmodified by this plan.
- **`universe_expansion_promote_compute_eligible.py` is ready for Plan 12 to reuse** if a future down-cap construction (following the pivot recommendation) needs dimension-aware promotion -- no changes needed, it already serves both `compute` and `compute_1d`.
- **The verdict document's `Pivot recommendation` section names three candidate next moves** (sector-neutral/industry-spread stratification, cross-TF fusion as the competing STATE.md priority, beta-neutralization informed by the large raw/residualized correlation gap) without deciding among them -- this is the user's call per D-10's own framing, not decided by this plan.
- **The 40-symbol pilot cohort is a real, retained corpus asset** (real 1d history back to each symbol's listing/onboarding date, `compute_eligible_1d=true`) available to any future construction that wants to re-examine this population under a different design, regardless of this verdict.
- No blockers for this plan's own scope. All threat-model mitigations (T-174-60 through T-174-65, plus the carried-forward T-174-01/02/03/47) verified via the automated checks recorded above.

---
*Phase: 174-universe-expansion-single-name-breadth-scaling-targeted-etf*
*Completed: 2026-09-16*

## Self-Check: PASSED

- FOUND: production/migrations/342_universe_pilot_sample_size_apr_key.sql
- FOUND: scripts/infrastructure/universe_expansion_pilot_draw.py
- FOUND: scripts/infrastructure/universe_expansion_promote_compute_eligible.py
- FOUND: docs/research/phase174-down-cap-correlation-gate-verdict.md
- FOUND commit: 84fab8e5d
- FOUND commit: 2e777cf20
- FOUND commit: 1a0dce796
