---
phase: 173-broadcast-feature-significance-correction-fix-pooled-cross-s
plan: 01
subsystem: alpha-measurement
tags: [concept_registry, broadcast-detection, apr, config_service, ic_engine, jsonb]

requires: []
provides:
  - "alpha.ic.broadcast_variance_threshold APR key (migration 324), shared by the offline
    detector and Plan 04's compute-time invariance assertion"
  - "Three-way ('broadcast'/'idiosyncratic'/'inconclusive') classifier with a
    temporal-variance guard in scripts/ops/alpha/ops_broadcast_feature_audit.py"
  - "A durable, empirically-measured concept_registry.metadata->>'broadcast' flag on every
    active, gate-joined domain='feature' row (38 broadcast=true, 255 broadcast=false)"
affects: [173-02, 173-03, 173-04]

tech-stack:
  added: []
  patterns:
    - "JSONB merge UPDATE (metadata || jsonb_build_object(...)) scoped to a locked predicate,
      never a full-row metadata replace"
    - "Stratified-across-full-history bar_ts sampling instead of recency-only, to avoid
      false negatives when the most recent window is itself degenerate"

key-files:
  created:
    - production/migrations/324_ic_broadcast_variance_threshold.sql
  modified:
    - scripts/ops/alpha/ops_broadcast_feature_audit.py
    - tests/unit/scripts/test_ops_broadcast_feature_audit.py

key-decisions:
  - "Kept the codebase-wide config_schema/config_state ON CONFLICT (config_key) house style
    (matching migration 298's own template) over a literal but unsatisfiable acceptance
    criterion (grep -c 'ON CONFLICT DO NOTHING' == 3) -- no migration in the repo achieves
    that literal count, including the plan's own cited template."
  - "amd_phase accepted as a genuine broadcast feature beyond D-02's list and the 5 expected
    Phase 142.5 additions -- source-verified (_amd_phase_ordinal is a pure bar_ts-to-ordinal
    mapping, zero symbol dependence)."
  - "Rewrote timestamp sampling from recency-only (ORDER BY bar_ts DESC LIMIT N) to stratified
    across the full 2005-2026 history -- the most recent ~200 timestamps are 100% RTH-only
    equities (ingestion stalled since 2026-08-13), which produced false 'inconclusive'
    verdicts for genuinely bar_ts-only features (in_ny_session) that do vary earlier in
    history."
  - "in_london_kz manually persisted broadcast=true with a distinct, honest evidence tag
    (source_verified_permanently_constant) rather than 'measured_broadcast' -- it is provably
    a pure bar_ts function (_in_london_kz(bar_ts, config), zero symbol dependence) but is
    LITERALLY constant 0 across all 73M+ rows in the corpus (confirmed by direct COUNT):
    the London killzone window (07:00-10:00 UTC) never overlaps NY RTH (13:30-20:00 UTC),
    and the tracked universe is 231/231 equities fetched useRTH=True. No sample size, however
    large, could ever produce temporal-guard evidence for this feature under the current
    universe -- it's a permanent data-composition fact, not a narrow-window artifact."

requirements-completed: [D-02, D-08, D-10]

duration: ~45min
completed: 2026-08-25
---

# Phase 173 Plan 01: Broadcast Feature Detector + Persistence Summary

**Built an empirical three-way broadcast/idiosyncratic/inconclusive classifier with a
temporal-variance guard, registered its epsilon as a shared APR key, and persisted the
authoritative population (38 features, a confirmed superset of D-02's 32-name floor) to
`concept_registry.metadata` for Plans 02-04 to read as a single source of truth.**

## Performance

- **Duration:** ~45 min (includes two multi-minute full-history DB queries)
- **Started:** 2026-08-25T16:03:00Z (approx, first commit 16:03:49Z)
- **Completed:** 2026-08-25T16:34:28Z
- **Tasks:** 3/3 completed
- **Files modified:** 3 (1 created, 2 modified) + 1 additional fix commit to the same script

## Accomplishments

- APR key `alpha.ic.broadcast_variance_threshold` (migration 324) live, seeded at the
  behavior-preserving value `1e-9`, documented as shared by both the offline detector and
  Plan 04's future compute-time assertion
- Detector's boolean contract replaced with a three-way verdict + temporal-variance guard,
  fixing the exact false-positive the plan's context named (`sweep_detected`/`manip_strength`
  no longer misclassify as broadcast)
- `--persist` write path lands a durable, merge-safe `broadcast` flag on `concept_registry`,
  scoped to exactly the locked target population (active + gate-joined domain='feature' rows)
- Live-run authoritative population: **38 broadcast features**, confirmed superset of every
  one of D-02's 32 enumerated names
- Found and fixed a real detector bug live during Task 3 (stratified sampling across full
  history instead of recency-only) -- see Deviations

## Task Commits

Each task was committed atomically:

1. **Task 1: Register the alpha.ic.broadcast_variance_threshold APR key** - `4e9ded24d` (feat)
2. **Task 2: Add the temporal-variance guard and the --persist write path to the detector**
   - `a4f903344` (test, RED)
   - `a9da25991` (feat, GREEN)
3. **Task 3: Run the detector across all timeframes and persist the authoritative population**
   - `bf456e1aa` (fix -- stratified sampling, found live during this task)
   - Persist itself is a database write, not a git commit (see below)

**Plan metadata:** commit pending (this SUMMARY + final docs commit)

## Files Created/Modified

- `production/migrations/324_ic_broadcast_variance_threshold.sql` - registers the shared APR
  epsilon key in `config_schema`/`config_state`/`config_history`
- `scripts/ops/alpha/ops_broadcast_feature_audit.py` - three-way classifier, temporal-variance
  guard, `--persist` write path, stratified-history sampling
- `tests/unit/scripts/test_ops_broadcast_feature_audit.py` - migrated to the three-way
  contract, extended with globally-constant/ordering/JSONB-shape coverage (18 tests total)

## Database State Change (not a git commit)

`concept_registry.metadata->>'broadcast'` is now populated on every active, gate-joined
`domain='feature'` row (293 rows total: 38 `true`, 255 `false`). This is a live-database
persistence action, not a code change -- there is no corresponding git commit, and running
`--persist` again is idempotent (same predicate, same evidence values, only
`broadcast_detected_at` changes).

**Evidence breakdown (293 in-scope rows):**

| Evidence | Count |
|---|---|
| `measured_broadcast` | 37 |
| `measured_idiosyncratic` | 241 |
| `inconclusive` | 14 |
| `source_verified_permanently_constant` | 1 (`in_london_kz`, manual correction, see below) |

**Out-of-scope rows (7, correctly untouched, no `broadcast` key):** 5 `status='candidate'`
rows + 2 gate-less tombstones (`new_high_flag`, `new_low_flag`, migration 284).

**The 38 authoritative broadcast features:**

```
amd_phase, day_of_month_cos, day_of_month_sin, days_to_month_end, dow_cos, dow_sin,
flight_quality, hour_of_day_cos, hour_of_day_sin, hyg_lqd_ret_z, in_london_kz,
in_ny_session, in_overlap, minute_of_hour_cos, minute_of_hour_sin, month_cos,
month_position, month_sin, opening_range, opex_flag, power_hour, quad_witching_flag,
quarter_cycle_cos, quarter_cycle_sin, quarter_position, sb_corr_fast, sb_corr_slow,
sb_corr_z, session_time_pos, tdom_cos, tdom_sin, tip_tlt_ret_z, vix_z,
week_of_month_cos, week_of_month_sin, week_of_year_cos, week_of_year_sin,
yield_slope_z
```

**Composition:** 31 of D-02's 32 names (measured), 1 D-02 name via source-verified manual
correction (`in_london_kz`), the 5 expected Phase 142.5 additions (`month_sin`, `month_cos`,
`opex_flag`, `quad_witching_flag`, `session_time_pos`), and 1 unexpected but source-verified
addition (`amd_phase`). All 32 D-02 names are present. Zero of D-02's 32 names are missing.

## Decisions Made

1. **House-style precedence over a miscounted acceptance criterion (Task 1).** The plan's
   acceptance criteria stated `grep -c "ON CONFLICT DO NOTHING"` should return 3 for the new
   migration. Verified this is unsatisfiable while following the plan's own cited template
   (migration 298) -- that file itself returns 1 for the same grep, and no migration in the
   entire `production/migrations/` directory returns 3 (checked via `grep -rc` across all
   files). Kept the universal `ON CONFLICT (config_key) DO NOTHING` house style. The
   migration's actual `<verify>` automated block (idempotent re-apply, value round-trips as
   1e-9) does not test this literal grep count, so no plan-level verification was skipped.

2. **amd_phase accepted as a genuine broadcast feature.** Task 3's action explicitly
   authorizes accepting a name "beyond the expected five additions" if source-code
   verification confirms it's genuinely bar_ts-derived. Read `_amd_phase_ordinal` in
   `src/intelligence/feature_factory.py`: `(bar_ts: datetime, config: FeatureFactoryConfig)
   -> float`, zero symbol dependence, ordinal-encodes UTC hour into 4 fixed AMD-cycle phases.
   Same shape as `in_overlap`/`power_hour`, which already classified correctly. Accepted.

3. **in_london_kz: source-verified manual correction, not blind override.** The empirical
   detector correctly reported `inconclusive` for this name in all 4 timeframes, even at
   `--n-timestamps 200` stratified across the full 2005-2026 history. Investigated rather than
   overridden blindly: `SELECT in_london_kz, count(*) FROM feature_vectors WHERE tf='5m' GROUP
   BY in_london_kz` returns exactly one row -- `0|73164003` -- the value is **literally
   constant across every row in the entire corpus**. Root cause: the London killzone window
   (`feature.session.london_kz_start_utc_hour=7` to `london_kz_end_utc_hour=10`, i.e.
   07:00-10:00 UTC) never overlaps NY RTH (`ny_start_utc_hour=13`, `ny_start_utc_minute=30` to
   `ny_end_utc_hour=20`, i.e. 13:30-20:00 UTC), and the tracked universe is 231/231 equities
   fetched with `useRTH=True` (`src/providers/ibkr.py`'s `use_rth = sec_type == "STK"`). No
   sample, however large or however sampled, could ever produce temporal-guard evidence for
   this feature under the current universe composition -- it is a permanent data-composition
   fact, not a detection failure. Given the source-code proof (`_in_london_kz(bar_ts, config)`,
   zero symbol dependence, same pure-function shape as every other correctly-classified
   calendar feature) and the plan's own precedent for treating source verification as
   authoritative, applied a targeted, documented manual `UPDATE` (same JSONB-merge idiom,
   same locked predicate) setting `broadcast=true` with a distinct, honest evidence tag
   (`source_verified_permanently_constant`, not `measured_broadcast` -- it was never actually
   measured, and mislabeling it as measured would misrepresent what was found).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Recency-only bar_ts sampling produced false negatives for genuinely
broadcast features**
- **Found during:** Task 3's authoritative run (first live run with `--n-timestamps 200`)
- **Issue:** `_SAMPLE_TIMESTAMPS_SQL` picked the most recent N `bar_ts` values
  (`ORDER BY bar_ts DESC LIMIT N`). This corpus's active universe is 231/231 equities, fetched
  `useRTH=True` (regular-trading-hours-only), and intraday ingestion has been stalled since
  2026-08-13 (confirmed: `max(bar_ts)` for `tf='5m'` is `2026-08-13 19:55:00+00`). The most
  recent 200-timestamp window is therefore 100% within NY RTH hours, so `in_ny_session` (a
  provably pure `bar_ts`-only function, verified via `src/intelligence/feature_factory.py`)
  read as constant=1 with zero temporal variance in that window, despite real off-RTH
  evidence existing earlier in the corpus's full 2005-2026 history (confirmed:
  `in_ny_session=0` rows with 220+ distinct symbols as recently as 2026-03-06).
- **Fix:** Replaced `_SAMPLE_TIMESTAMPS_SQL` (recency-limited) with `_CANDIDATE_TIMESTAMPS_SQL`
  (fetches all qualifying `bar_ts` values) + a new `_stratified_sample()` helper that picks
  `--n-timestamps` values evenly spaced across the full sorted history in Python.
- **Files modified:** `scripts/ops/alpha/ops_broadcast_feature_audit.py`
- **Verification:** All 18 pre-existing/extended unit tests still pass unchanged (the pure
  classifier functions' contracts are untouched). Task 2's live-verify criterion re-confirmed
  (`sweep_detected`/`manip_strength` still correctly not broadcast). Full `tests/unit/` suite
  green. Live re-run with the fix correctly surfaced `in_ny_session` as broadcast in 3/4
  timeframes (was 0/4 before the fix).
- **Committed in:** `bf456e1aa`

### Documented, Non-Auto-Fixed Finding

**in_london_kz required a source-verified manual correction, not an automated fix** (see
Decision 3 above) -- this is a genuine, permanent data-composition fact (the killzone window
never overlaps the RTH-only universe's data), not a bug the detector script could have been
made to measure. Documented thoroughly rather than silently patched into the detector's
general-purpose classifier logic, which would have conflated "provably broadcast but
permanently unmeasurable" with "measured broadcast" for future readers of that code.

## Known Stubs

None -- this plan's deliverable is fully wired (migration applied, script live-tested against
production data, `concept_registry` rows persisted and verified).

## Self-Check: PASSED

- `production/migrations/324_ic_broadcast_variance_threshold.sql` - FOUND
- `scripts/ops/alpha/ops_broadcast_feature_audit.py` - FOUND (modified)
- `tests/unit/scripts/test_ops_broadcast_feature_audit.py` - FOUND (modified)
- Commit `4e9ded24d` - FOUND in `git log`
- Commit `a4f903344` - FOUND in `git log`
- Commit `a9da25991` - FOUND in `git log`
- Commit `bf456e1aa` - FOUND in `git log`
- `alpha.ic.broadcast_variance_threshold` in `config_state` - FOUND, value `1e-9`
- `concept_registry.metadata->>'broadcast'='true'` count - FOUND, 38 rows, superset of D-02's
  32 names (verified: 32/32 present)
