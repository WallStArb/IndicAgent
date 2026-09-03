---
phase: 151-feature-primitives-expansion-theory-motivated-interaction-la
reviewed: 2026-08-05T18:57:13Z
depth: standard
files_reviewed: 29
files_reviewed_list:
  - production/migrations/286_cluster_regime_conditioned.sql
  - production/migrations/287_calendar_velocity_atomics.sql
  - production/migrations/288_recency_statistical_atomics.sql
  - production/migrations/289_cross_asset_spread_beta_atomics.sql
  - production/migrations/290_named_interaction_primitives.sql
  - production/migrations/291_theory_motivated_interactions.sql
  - services/backfill_feature_factory.py
  - services/feature_vector_pipeline.py
  - services/ic_engine.py
  - src/intelligence/feature_cache.py
  - src/intelligence/feature_factory.py
  - src/intelligence/features/cross_asset_series.py
  - src/intelligence/features/feature_vector_persistence.py
  - src/intelligence/schemas.py
  - tests/unit/intelligence/test_feature_factory_batch_parity.py
  - tests/unit/intelligence/test_feature_factory_batch.py
  - tests/unit/intelligence/test_feature_factory_p7.py
  - tests/unit/intelligence/test_feature_registry_service.py
  - tests/unit/pipeline/pipeline_helpers.py
  - tests/unit/services/test_backfill_feature_factory.py
  - tests/unit/services/test_feature_vector_pipeline_cross_asset.py
  - tests/unit/services/test_feature_vector_writer_column_mapping.py
  - tests/unit/services/test_feature_vector_writer.py
  - tests/unit/test_canary_predictors.py
  - tests/unit/test_feature_factory.py
  - tests/unit/test_ic_engine_clustering.py
  - tests/unit/test_ic_engine_compute_split.py
  - tests/unit/test_ic_engine_fingerprint.py
  - tools/scan_binary_patterns.py
findings:
  critical: 1
  warning: 5
  info: 2
  total: 8
status: fixed
fixed: 2026-08-05
fix_summary: |
  CR-01 fixed: TestIsPromotionEligible reassembled contiguously (4 dead-nested
  tests now correctly collected, 36/36 pass). WR-01 fixed: ddof=1 mismatch in
  build_symbol_beta_series. WR-02 fixed: 5 live-path cross-asset deques raised
  from maxlen=500 to maxlen=2520 to match their APR ceiling. WR-03 fixed:
  equity_beta_z/rate_beta_z now default None (was a fabricated 0.0), closing
  the fake-zero half of todo 264 (the live-wiring gap itself remains open).
  WR-05 fixed: docstring field count corrected 270->292. IN-01 fixed:
  _correlation/_safe_corr consolidated into src/intelligence/utils/core.py's
  safe_corr (discovered mid-fix: a stale, unreachable sibling utils.py file
  predating a utils/ package refactor -- reverted that file untouched, put
  the real fix in the live module). WR-04 and IN-02 filed as todos 265/264
  (live-daemon production-behavior changes, deferred rather than rushed).
  Full tests/unit/ suite green throughout (one known unrelated pre-existing
  migration-number collision from a different concurrent session).
---

# Phase 151: Code Review Report

**Reviewed:** 2026-08-05T18:57:13Z
**Depth:** standard
**Files Reviewed:** 29
**Status:** issues_found

## Summary

Reviewed the six Phase 151 migrations (286-291) plus the compute/persistence/live-pipeline
surface they land on: `feature_factory.py`'s ~113 new primitives (calendar cycle/TDOM/minute,
velocity, recency/statistical atomics, cross-asset spread/beta, named cross-TF divergences +
calendar flags, theory-motivated compound interactions), `cross_asset_series.py` (new Ring-1
module), the `feature_cache.py`/`feature_vector_persistence.py`/`ic_engine.py`/
`backfill_feature_factory.py`/`feature_vector_pipeline.py` wiring, and the associated unit
tests. The implementation is disciplined overall — index-derived (not hand-typed) persistence
column slices verified against `schemas.py`'s actual field order, consistent `_guard`/
`_guard_counted` application, NamedTuple contracts replacing positional tuples to prevent
future drift, and unusually thorough test coverage including parity, causality, and
cold-start-boundary tests.

Diffing the reviewed test file against its pre-Phase-151 revision surfaced one real,
provable regression: a new module-level test function was inserted in the middle of an
existing test class body, silently turning four previously-passing tests into unreachable
nested function definitions that pytest never collects. The file's own comment
misattributes this to "a pre-existing indentation defect," which is incorrect — `git diff`
against the phase's base commit shows the four tests were correctly indented as class
methods before this phase's edit.

Beyond that, this review found a live-vs-batch parity gap that reproduces a bug class this
same codebase already fixed once before (migration 256, CR-02: a hardcoded cap silently
undercutting an operator/ML-tunable APR window), a statistical estimator inconsistency
(mismatched `ddof` between `np.cov`/`np.var`) in the new factor-beta computation, a stale
field-count in `feature_factory.py`'s own docstrings, and a documented-but-real "None means
not measured" contract violation on the live path for the two new nullable beta fields.

## Critical Issues

### CR-01: New test insertion silently turns 4 existing tests into dead code (never collected)

**File:** `tests/unit/intelligence/test_feature_registry_service.py:649-668` (new function),
breaking `tests/unit/intelligence/test_feature_registry_service.py:670,686,702,721`
(pre-existing tests)

**Issue:** The Phase 151 diff inserts a new module-level function,
`test_every_interaction_row_has_exactly_two_parents` (line 649), directly between
`class TestIsPromotionEligible:`'s second method (`test_false_when_passes_unmet`, ends at
line 608) and what were previously its next four methods
(`test_false_when_observations_unmet`, `test_false_when_neither_met`,
`test_reads_floors_from_passed_arguments_not_hardcoded`, `test_false_for_unknown_feature`).
Those four `def ...(self):` blocks are still indented at 4 spaces, but because the new
function is a *module-level* `def` (0 indentation) rather than a new class statement,
Python parses the four subsequent 4-space-indented `def`s as **nested function
definitions inside** `test_every_interaction_row_has_exactly_two_parents`, not as methods of
`TestIsPromotionEligible`. They are defined every time that test runs and then discarded —
pytest never discovers or executes them.

Verified via AST comparison against the pre-Phase-151 revision
(`git show 7ee75467:tests/unit/intelligence/test_feature_registry_service.py`): before this
diff, `TestIsPromotionEligible` correctly had all 6 methods. After this diff, the class has
only 2, and the AST shows the other 4 function names nested inside
`test_every_interaction_row_has_exactly_two_parents`.

The code's own comment (lines ~211-221 of the current file, near
`test_interaction_tier_population_within_cap`) claims: *"that location sits inside a
pre-existing indentation defect ... That defect predates this plan and is out of scope
here (SCOPE BOUNDARY)."* This is factually wrong per the diff — the defect is introduced
by this exact insertion, not pre-existing, and the comment gives a false sense that it was
triaged and knowingly deferred.

**Impact:** Four regression tests for `FeatureRegistryService.is_promotion_eligible()`'s
recovery-floor logic (a real promotion/demotion decision gate) are silently disabled. CI
stays green; coverage silently regresses. This is exactly the "silent wrong answer" class
CLAUDE.md's design mindset flags as worse than a loud crash — a currently-broken
`is_promotion_eligible` would not be caught by this test file anymore.

**Fix:** Move the new tests (`test_every_interaction_row_has_exactly_two_parents`,
`_fetch_interaction_rows`, `_LIVE_DB_DSN`, and `test_interaction_tier_population_within_cap`)
to the true module tail, *after* `class TestIsPromotionEligible`'s closing method, restoring
the four now-dead methods to their correct indentation/position inside the class. Then run
`pytest --collect-only tests/unit/intelligence/test_feature_registry_service.py -q` and
confirm the collected count includes all 6 `TestIsPromotionEligible` tests plus the 2 new
ones (8 total in that region), not 4.

```python
# Correct shape: keep TestIsPromotionEligible's body contiguous, place new
# module-level tests fully after the class.
class TestIsPromotionEligible:
    def test_true_when_both_floors_met(self): ...
    def test_false_when_passes_unmet(self): ...
    def test_false_when_observations_unmet(self): ...
    def test_false_when_neither_met(self): ...
    def test_reads_floors_from_passed_arguments_not_hardcoded(self): ...
    def test_false_for_unknown_feature(self): ...


# --- new Phase 151 tests, module level, after the class ---
_LIVE_DB_DSN = "postgresql://postgres:postgres@localhost:5432/indicagent"


def _fetch_interaction_rows(): ...
def test_every_interaction_row_has_exactly_two_parents(): ...
def test_interaction_tier_population_within_cap(): ...
```

## Warnings

### WR-01: `build_symbol_beta_series` mixes `np.cov` (ddof=1) with `np.var` (ddof=0)

**File:** `src/intelligence/features/cross_asset_series.py:361-372`

**Issue:** `raw_equity_beta = cov_spy / var_spy` computes `cov_spy` via `np.cov(sym_arr,
spy_arr)[0, 1]` (NumPy default `ddof=1`, divides by `N-1`) and `var_spy` via
`np.var(spy_arr)` (NumPy default `ddof=0`, divides by `N`). The two normalizations don't
cancel, so the resulting "OLS slope" is biased high by a factor of `N/(N-1)` relative to the
textbook estimator (verified numerically: with `factor_beta_window`'s allowed minimum of 10
bars, the bias is ~11%; at the seeded default of 60 bars, ~1.7%). The identical pattern
repeats for `raw_rate_beta` (`cov_tlt`/`var_tlt`, lines 370-372).

Because `equity_beta_z`/`rate_beta_z` are z-scored over a rolling deque (line 365-367,
373-376) and the window is *constant* once the deque reaches `factor_beta_window`, the
multiplicative bias is the same for every entry in a fully-warmed deque and cancels out of
the z-score arithmetically. It does **not** cancel during the deque's own warm-up ramp
(`len(equity_beta_hist) < factor_beta_zscore_window`, where the "N" behind each raw value is
`equity_beta_hist`'s length at append-time, not the OLS window `N` — actually the OLS
window itself is fixed at `factor_beta_window`, so the *raw* beta magnitude bias is constant
once `sym_ret_hist` reaches its own maxlen; it is the z-score baseline that briefly mixes
constant-bias and full-bias values during warm-up). No unit test asserts a numeric beta
value against an independent OLS reference — only `math.isfinite()` is checked
(`tests/unit/services/test_backfill_feature_factory.py:304-319`), so this would not be
caught by the current suite.

**Fix:**
```python
var_spy = float(np.var(spy_arr, ddof=1))   # match np.cov's default ddof
...
var_tlt = float(np.var(tlt_arr, ddof=1))
```
or equivalently switch `np.cov(..., ddof=0)` to match `np.var`'s default. Either is fine as
long as both use the same `ddof`.

### WR-02: Live-path cross-asset deques hardcode `maxlen=500`, silently capping windows the APR schema allows up to 2520

**File:** `src/intelligence/feature_cache.py:77-79` (`_tip_tlt_ratio_history`,
`_hyg_lqd_ratio_history`, `_sb_corr_history`), consumed at lines 611-613, 626-628, 652-654

**Issue:** `feature.tip_tlt.zscore_window`, `feature.hyg_lqd.zscore_window`,
`feature.sb_corr.zscore_window`, and `feature.factor_beta.zscore_window` (migration 289) all
declare `max_value = 2520` and `ML learning target: yes`, meaning an automated APR tuner is
explicitly permitted to raise these above 500. But the live `FeatureCache` dataclass backs
each of these with a `deque(maxlen=500)` (a dataclass `field(default_factory=...)`, which
cannot read `config` at declaration time). If any of these windows is ever tuned above 500,
the **live** path silently truncates to the most recent 500 observations regardless of the
configured window, while the **batch** path (`build_cross_asset_series`,
`src/intelligence/features/cross_asset_series.py:130-141`, correctly sizes its deques to
`config.tip_tlt_zscore_window` etc.) uses the full configured window. This reproduces,
exactly, the bug class this codebase already found and fixed once before: migration
`256_session_vp_rolling_window_live_cap_correction.sql` documents the identical shape (a
hardcoded live-path cap silently undercutting a configured/tunable window) for
`BarHistory(maxlen=200)` vs `momentum_zscore_window`/`hurst_window`/`vix_zscore_window`
(default 252, "already silently exceeding 200"). At the seeded defaults (252) this doesn't
currently manifest, but nothing in the code prevents the APR learner from crossing 500,
and no test would catch it (no test exercises a window > 500).

**Fix:** Either raise the deque's `maxlen` to match the schema's true ceiling (2520,
mirroring `_spy_realized_vol_history`/`_yield_ratio_history`'s own pre-existing 500 cap
being sized to `vix_zscore_window`/`yield_curve_zscore_window`'s smaller allowed range), or
size the deque dynamically from `self._feature_factory_config` the first time
`update_cross_asset()` runs. At minimum, cap `config_schema.max_value` for these four keys
at 500 to match the actual live-path ceiling until the deque is fixed, so the documented
tunable range cannot silently exceed what the code can honor. File a todo if deferring,
per this codebase's own convention (see the pending todo already filed for the sibling
`feature.cross_asset.role_symbols` orphaned-key gap).

### WR-03: `equity_beta_z`/`rate_beta_z` live-path default (0.0) violates the class's own "None means not measured" contract

**File:** `src/intelligence/feature_cache.py:75-76` (dataclass defaults);
`services/feature_vector_pipeline.py` (no write site — grepped, confirmed `cache.equity_beta_z`/
`cache.rate_beta_z` are never assigned anywhere in this file)

**Issue:** `schemas.py`'s `FeatureVector.equity_beta_z`/`rate_beta_z` docstring is explicit:
*"None for SPY itself ... rather than a silently-wrong constant 1.0"* — i.e., `None` is the
contract for "not measured," never a numeric placeholder. `FeatureCache.equity_beta_z`/
`rate_beta_z` default to `0.0` (not `None`), and Plan 151-09 wired live cross-asset broadcast
for the other 7 new fields (`tip_tlt_ret_z`, `hyg_lqd_ret_z`, `sb_corr_fast/slow/z`) but
explicitly left these two unwired ("live: not yet wired, plan 151-09" — confirmed still true
after 151-09 landed; no assignment site exists in `feature_vector_pipeline.py`). Every live
`FeatureVector` for every non-SPY/non-TLT symbol therefore carries `equity_beta_z=0.0`/
`rate_beta_z=0.0` — a fake "zero beta" — indistinguishable downstream from a genuine
zero-beta measurement, for as long as the live pipeline runs before this gap is closed.

This is a known, documented gap (not a silent surprise to the implementer), and the live
IBKR ingestion chain is currently intentionally stopped, so it has no live-data blast radius
today. It is flagged here because it directly contradicts a class-level invariant this same
plan enforced correctly for the sibling fields, and because "currently stopped" is an
operational fact that can change without this code changing.

**Fix:** Either default `FeatureCache.equity_beta_z`/`rate_beta_z` to `None` (requires
loosening the dataclass field type to `float | None`) so the live path degrades to the
documented "not measured" contract instead of a fake zero, or file/confirm a tracked todo
(mirroring the pattern already used for the orphaned `feature.cross_asset.role_symbols`
key) so this doesn't silently ship live-computed feature vectors with a fabricated beta if
ingestion resumes before the wiring lands.

### WR-04: `_guard_counted`'s "observable tripwire" guarantee only holds on the batch path

**File:** `src/intelligence/feature_factory.py:3694-3735` (counter + report),
`:8113` (sole `_report_guard_counted_substitutions()` call site, inside `compute_batch()`)

**Issue:** `_guard_counted()` is explicitly designed (per its own docstring) to make a
non-finite substitution "OBSERVABLE rather than a silent collapse," as opposed to a bare
`np.nan_to_num()` call that "would substitute the same 0.0 with no trace at all." That
guarantee is real for the batch/backfill path, where `_report_guard_counted_substitutions()`
is called once per `compute_batch()` invocation. It is **not** real for the live daemon
path: `compute()` (used exclusively by `FeatureVectorPipeline`, the only process that calls
`FeatureFactory.compute()` outside of tests) also calls `_guard_counted()` for the same 10
Theory-Motivated Interaction products, incrementing the same module-level
`_GUARD_COUNTED_SUBSTITUTIONS` dict — but `_report_guard_counted_substitutions()` is, by the
code's own docstring, "NOT called from compute()." The live daemon process never calls
`compute_batch()`, so a substitution that fires on the live path increments a counter that
is never logged, never reset, and never observed by any operator — precisely the "silent
collapse" failure mode this construct exists to prevent, just deferred from "value" to
"event."

**Impact:** Low likelihood (the design doc itself argues a float64 product of two
z-scores essentially cannot overflow), but if it ever does fire live, there is currently no
way to know without attaching a debugger to a running process and inspecting
`feature_factory._GUARD_COUNTED_SUBSTITUTIONS`.

**Fix:** Either call `_report_guard_counted_substitutions()` periodically from
`FeatureVectorPipeline` (e.g. alongside its existing periodic regime-cache refresh), or
emit the OTel counter this project already has infrastructure for
(`src/observability/metrics.py`) directly from `_guard_counted()` on both paths, rather than
relying on a batch-only log-and-reset call.

### WR-05: `feature_factory.py`'s module/method docstrings still say "270 FeatureVector primitives"

**File:** `src/intelligence/feature_factory.py:1`, `:6633`, `:6651`

**Issue:** The module docstring (line 1: *"pure-function library for computing all 270
FeatureVector primitives"*) and `FeatureFactory.compute()`'s own docstring (lines 6633,
6651) were updated from the pre-Phase-151 value of 249, but only partially — to 270, not
292. `schemas.py`'s `FeatureVector` class docstring (correctly updated to 292) and every
updated test assertion (`tests/unit/test_canary_predictors.py:214`,
`tests/unit/test_feature_factory.py:88`, `tests/unit/intelligence/test_feature_factory_p7.py:47`
— all assert `292`, all pass) agree the true count is 292 (249 + 6 + 4 + 11 + 7 + 5 + 10).
270 is neither the pre- nor post-Phase-151 field count and appears to be a partial/aborted
update (perhaps counting only a subset of this phase's additions). A future reader trusting
this docstring over the dataclass itself will cite the wrong number.

**Fix:**
```python
"""FeatureFactory — pure-function library for computing all 292 FeatureVector primitives.
...
        """Compute all 292 FeatureVector primitives from bars + cache + config.
...
        FeatureVector with all 292 fields populated -- most set to finite
```

## Info

### IN-01: `_correlation` (feature_factory.py) and `_safe_corr` (feature_cache.py) are exact duplicate implementations

**File:** `src/intelligence/feature_factory.py:1735-1747`,
`src/intelligence/features/cross_asset_series.py:38` (imports `_safe_corr` from
`feature_cache.py`), `src/intelligence/feature_cache.py:1236-1251`

**Issue:** Both functions implement the identical mean-centered Pearson correlation formula
(`np.dot(xm, ym) / sqrt(np.dot(xm, xm) * np.dot(ym, ym))`, same degenerate-input guards)
under different names in different modules. `feature_cache.py`'s docstring explains this is
deliberate — importing `feature_factory.py`'s `_correlation` into `feature_cache.py` would
create a circular import, since `feature_factory.py` already imports `FeatureCache` from
`feature_cache.py`. That reasoning is sound for *that specific pair* of modules, but both
modules already import shared helpers from `src/intelligence/utils.py` (a dependency-free
Ring-1 leaf: `feature_factory.py` imports `clamp`/`find_peaks`/`find_troughs` from it).
Moving one canonical `_correlation`/`_safe_corr` implementation there would remove the
duplication without introducing a cycle. Two independently-maintained copies of the same
formula is a standing risk of silent future divergence (one gets a bugfix or tolerance
tweak, the other doesn't) in a codebase whose CLAUDE.md explicitly calls out this exact
failure shape ("two independent incidents hit the same shape of bug two weeks apart").

**Fix:** Move the correlation helper to `src/intelligence/utils.py` and have both
`feature_factory.py` and `feature_cache.py` import it from there.

### IN-02: `_equity_beta_history`/`_rate_beta_history` are dead scaffolding

**File:** `src/intelligence/feature_cache.py:80-81`

**Issue:** These two `FeatureCache` dataclass fields are declared but never read or written
anywhere in `feature_cache.py` (grepped repo-wide within this file — only the declaration
lines match). They appear to be scaffolding added in anticipation of the live-path beta
wiring that WR-03 above notes is still unwired even after Plan 151-09 landed.

**Fix:** No action needed until the live wiring lands; flagging only so a future cleanup
pass doesn't need to re-derive that these are intentionally-unused placeholders versus an
accidental leftover.

---

_Reviewed: 2026-08-05T18:57:13Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
