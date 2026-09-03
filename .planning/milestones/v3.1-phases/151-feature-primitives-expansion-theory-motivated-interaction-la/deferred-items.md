# Deferred Items — Phase 151

Out-of-scope discoveries found during plan execution, logged per SCOPE BOUNDARY
(fix in a dedicated task/todo, not inline during an unrelated plan).

## 151-06: Dead test methods in test_feature_registry_service.py (pre-existing, not caused by this plan)

**Found during:** Plan 151-06, Task 3 (writing `test_interaction_tier_population_within_cap`).

**Issue:** `tests/unit/intelligence/test_feature_registry_service.py`'s `TestIsPromotionEligible`
class is broken by an indentation defect predating this plan. After
`test_false_when_passes_unmet` (a real class method), the file drops to column 0 for a
comment block, `_LIVE_DB_DSN`, `_fetch_interaction_rows()`, and
`test_every_interaction_row_has_exactly_two_parents()` (all correctly module-level, added by
plan 151-05). But the four methods that were originally meant to close out
`TestIsPromotionEligible` --  `test_false_when_observations_unmet`,
`test_false_when_neither_met`, `test_reads_floors_from_passed_arguments_not_hardcoded`,
`test_false_for_unknown_feature` -- are still indented 4 spaces (`self` parameter, clearly
intended as class methods) immediately after `test_every_interaction_row_has_exactly_two_parents()`'s
body, with no `class` statement re-opened. Python parses this as valid syntax: the four
`def`s become **nested functions inside `test_every_interaction_row_has_exactly_two_parents()`**,
never called, never collected by pytest. Confirmed via `git diff HEAD` that this indentation
already existed before plan 151-06 touched the file -- introduced by whichever prior plan
inserted the arity-test block into the middle of the class (151-05, based on the block's own
`# T-151-09` heading).

**Impact:** 4 tests silently do not run (`is_promotion_eligible`'s partial-floor/neither-met/
custom-floor/unknown-feature branches are untested, though `TestIsPromotionEligible`'s first two
methods, `test_true_when_both_floors_met`/`test_false_when_passes_unmet`, do still run and
exercise the same method). Not a collection-breaking error -- `ast.parse` and `pytest` both
succeed silently; this is a "tests silently don't run" defect, not a loud failure.

**Not fixed here:** Out of scope for 151-06 (SCOPE BOUNDARY -- pre-existing, unrelated to this
plan's 10 Theory-Motivated Interaction compounds). Plan 151-06 avoided the defect by placing its
own new test (`test_interaction_tier_population_within_cap`) at the true module tail instead of
adjacent to the broken block, so it is not itself swallowed by the same nesting bug (confirmed via
`ast.parse` + a live pytest collection/run).

**Suggested fix (not applied):** Dedent the four orphaned methods back to 4-space class-method
indentation immediately following `TestIsPromotionEligible`'s `test_false_when_passes_unmet`, and
relocate the `# T-151-09` comment block / `_LIVE_DB_DSN` / `_fetch_interaction_rows()` /
`test_every_interaction_row_has_exactly_two_parents()` block to after the class closes (or to the
module tail, matching this plan's own new test's placement). File a todo if picked up later.
