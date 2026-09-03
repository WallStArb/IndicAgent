---
phase: 144-cross-sectional-regime-model-regime-group
plan: 05
subsystem: intelligence
tags: [ic-engine, regime-group, cross-sectional, apr, contamination-fix]

# Dependency graph
requires:
  - phase: 144-01
    provides: market_regimes.regime_group column (migration 229, renamed from asset_class) + alpha.regime.groups APR key + per-group threshold namespaces
  - phase: 144-04
    provides: services.cross_sectional_regime_model._parse_group_configs (str | list[dict] JSON-parse fix, filters to enabled=true groups)
provides:
  - "services/ic_engine.py: AmbiguousRegimeGroupError + _build_symbol_regime_class -- symbol -> regime_group routing, fail-loud on ambiguity, omit-not-default on zero-match"
  - "ICEngineConfig.regime_groups_json field + JSON-shape-safe from_apr binding (never str()-on-list)"
  - "All 4 market_regimes asset_class='equity' SQL sites generalized to regime_group, driven per-enabled-group"
  - "_compute_cross_sectional_tf(regime_group, symbol_list, ...): symbol_list is THE contamination-bug fix -- chunk_sql now filters fv.symbol = ANY(%(symbol_list)s), scoping each group's pooled IC to its own peer symbols only"
  - "mr_dicts_by_group: {group_name -> {tf -> {ts -> label}}}, each per-symbol worker receives only its own symbol's group's dict"
  - "Cross-sectional pass loops enabled_groups x tfs x that group's own regime labels, pooling only that group's peer symbols per cell"
  - "equity_model_enabled retired as a standalone APR-driven kill-switch; runtime value now derived from bool(enabled_groups)"
affects: [144-06-corpus-rerun-and-acceptance-gate]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Symbol -> regime_group routing is fail-loud on ambiguity (AmbiguousRegimeGroupError) and omit-not-default on zero-match -- a symbol with no matching enabled group is excluded from regime-stratified IC (pooled IC pass still covers it), never silently mislabeled under an unrelated group's regime."
    - "Cross-sectional pooling scoping: symbol_list threaded as a bound SQL param (fv.symbol = ANY(%(symbol_list)s)), never string-interpolated -- matches the plan's threat model T-144-05-SQL mitigation."
    - "ICEngineConfig stays a flat, picklable dataclass of primitives: regime_groups_json is a JSON STRING field (not a parsed list), normalized once in from_apr() from APR's already-parsed-list-or-raw-string shape, then re-parsed via _parse_group_configs() in main()."

key-files:
  created:
    - tests/unit/test_ic_engine_routing.py
  modified:
    - services/ic_engine.py

key-decisions:
  - "Retired alpha.regime.equity_model_enabled as the runtime kill-switch in favor of bool(enabled_groups): grep -rn equity_model_enabled services/ src/ scripts/ confirmed services/ic_engine.py is the SOLE runtime reader of the APR key (config_state value only otherwise referenced in migration comments and a shell-script comment, never read at runtime). The ICEngineConfig.equity_model_enabled dataclass field and its from_apr() binding were KEPT (not removed) because two existing test call sites construct ICEngineConfig directly with equity_model_enabled=True as a required positional/keyword field (tests/unit/test_hac_ic_sharpe.py, tests/unit/test_ic_engine_lifecycle_hook.py's shared _make_config helper, itself re-imported by tests/unit/test_ic_engine_staleness.py) -- removing the field would have required touching 3 test files for a field that is otherwise cosmetically dead, disproportionate to the actual retirement goal. The field is now VESTIGIAL: nothing in services/ic_engine.py's runtime path reads config.equity_model_enabled anymore. The local variable name `equity_model_enabled` is kept throughout main() for minimal diff against the rest of the (already large) function, but its value is now bool(enabled_groups) -- computed AFTER building enabled_groups from the new alpha.regime.groups[].enabled flags, never from the old standalone flag. This eliminates the actual risk Pitfall 3 warned about (two independently-settable on/off sources of truth that could drift): only ONE value now drives behavior."
  - "_build_symbol_regime_class duplicated (not imported) from the equivalent tag-routing logic in cross_sectional_regime_model.py's _resolve_group_symbols, per RESEARCH.md Open Question 1's own recommendation to keep them separate -- they answer inverse questions (symbol->group vs group->peer-symbols) and only ic_engine.py's side needs AmbiguousRegimeGroupError, since the dispatcher resolves one group's peers at a time and never needs to detect cross-group ambiguity."
  - "regime_group is NOT persisted on feature_ic_scores rows -- confirmed via schema read, no regime_group column exists there. Group identity stays implicit in regime_label string uniqueness across enabled groups (documented invariant, RESEARCH.md Pitfall 4), unchanged by this plan."

patterns-established:
  - "Cross-sectional cell identity is now (regime_group, tf, regime_label) instead of implicitly-always-equity (tf, regime_label) -- any future group added to alpha.regime.groups automatically gets its own routing, market_regimes prerequisite check, mr_dict, and peer-scoped cross-sectional pooling with zero additional ic_engine.py code, as long as its tag_filter doesn't overlap an already-enabled group's."

requirements-completed: []

# Metrics
duration: ~36min active work (+ ~12min full-suite verification wait)
completed: 2026-07-12
---

# Phase 144 Plan 05: IC Engine regime_group Routing Summary

**Wired `regime_group` routing into `ic_engine.py` (fail-loud `AmbiguousRegimeGroupError`, omit-not-default unrouted symbols) and fixed the confirmed cross-sectional contamination bug by threading a `symbol_list` peer-scoping filter into `_compute_cross_sectional_tf`'s `chunk_sql`, so `fi_*` bonds, GLD/SLV/VNQ, and IBIT no longer pool into equity-labeled regime cells.**

## Performance

- **Duration:** ~36 min active edit/commit work (base commit 15:10:15 -> Task 2 commit 15:46:23 EDT); full `.venv/bin/pytest tests/unit/ -q` verification run took an additional ~11.5 min (692s) of wall-clock wait, run once and reused per coordinator instruction
- **Started:** 2026-07-12T19:10:15Z
- **Completed:** 2026-07-12T19:46:23Z
- **Tasks:** 2/2 completed
- **Files modified:** 2 (1 created — `tests/unit/test_ic_engine_routing.py` — plus 1 modified)

## Accomplishments
- `AmbiguousRegimeGroupError` + `_build_symbol_regime_class(tags_by_symbol, group_configs)`: pure routing function, fail-loud on multi-group tag_filter overlap, omit-not-default on zero-match, skips disabled groups entirely -- ported from the canonical plan doc's Task 5 Step 1/3 code (verified correct-as-written against the live codebase, no drift)
- `ICEngineConfig.regime_groups_json: str = "[]"` field + JSON-shape-safe `from_apr()` binding: normalizes `alpha.regime.groups`'s already-parsed-list-vs-raw-string APR shape once, never `str()`s a `list[dict]` (which would produce Python-repr, not valid JSON)
- All 4 `market_regimes WHERE asset_class='equity'` SQL sites generalized to `WHERE regime_group=%s`, each driven by a loop over `enabled_groups` instead of a single hardcoded equity check: `_assert_prerequisites` (startup gate), the regime-timestamp prefetch inside `_compute_cross_sectional_tf`, the `mr_dicts_by_group` loader, and the cross-sectional pass's `DISTINCT regime_label` query
- `_compute_cross_sectional_tf` gains `regime_group: str` and `symbol_list: list[str]` as two additional params (config/rng threading from Phase 143.1 left completely unchanged, no reversion to a plain `apr` dict); `chunk_sql` gains `AND fv.symbol = ANY(%(symbol_list)s)` -- the actual contamination-bug fix, since `chunk_sql` previously had no symbol filter at all
- `mr_dicts_by_group: {group_name -> {tf -> {ts -> label}}}` replaces the single equity-only `mr_dict_by_tf`; each per-symbol worker's arg tuple now passes `mr_dicts_by_group.get(symbol_regime_class.get(symbol))` -- only its own symbol's group's dict, never another group's labels
- Cross-sectional pass caller loops `enabled_groups x tfs x that group's own regime labels`, resolving `symbols_by_group` from `symbol_regime_class` and passing each group's own peer symbol list into `_compute_cross_sectional_tf`
- `tests/unit/test_ic_engine_routing.py`: 8 tests covering fi-symbol routing, equity-symbol routing, zero-match omission, disabled-group exclusion, group-order independence, ambiguous-match error, empty-tags exclusion, and a preferred-fi routing case

## Task Commits

Each task was committed atomically:

1. **Task 1: `_build_symbol_regime_class` + `ICEngineConfig.regime_groups_json` + routing test** - `7fcbdf12` (feat)
2. **Task 2: regime_group SQL sites + `_compute_cross_sectional_tf` symbol_list fix + per-group loop** - `59e78d9d` (feat)

_Note: Task 1 was `tdd="true"`. As in 144-02/144-04, the routing logic being added already existed in a research-vetted, already-unit-tested form in the canonical plan doc (verified correct-as-written against the live codebase during RESEARCH.md's audit) -- this is porting known-good logic, not discovering novel behavior, so implementation and test were written together and verified green before commit, matching the precedent set by both prior Wave 1/2 plans in this phase._

## Files Created/Modified
- `services/ic_engine.py` - `AmbiguousRegimeGroupError`, `_build_symbol_regime_class`, `ICEngineConfig.regime_groups_json`, `_assert_prerequisites(group_configs=...)`, `_compute_cross_sectional_tf(regime_group, symbol_list, ...)`, `mr_dicts_by_group`, per-group cross-sectional pass loop, `equity_model_enabled` retirement
- `tests/unit/test_ic_engine_routing.py` - 8 unit tests for `_build_symbol_regime_class`

## Decisions Made

**`equity_model_enabled` retirement (RESEARCH.md Open Question 2 / Pitfall 3), with grep evidence:**

```
$ grep -rn "equity_model_enabled" services/ src/ scripts/
services/ic_engine.py:394:    equity_model_enabled: bool
services/ic_engine.py:487-488: equity_model_enabled=str(cfg.get_sync("alpha.regime.equity_model_enabled", "true"))...
services/ic_engine.py:550,558,588,590: _assert_prerequisites() param + docstring + gate
services/ic_engine.py:743,745,895,899,917: _compute_symbol_tf/main() docstrings and comments
services/ic_engine.py:1506,2112,2149,2701-2704,2736-2748,2785,2885,2987,2997,3117: main()/_persist_corpus_results
scripts/ops/corpus/ops_corpus_pipeline_run.sh:325: comment only, not a runtime read
scripts/ops/alpha/ops_ic_null_calibration.py:21: comment only, not a runtime read

$ grep -rn "alpha.regime.equity_model_enabled" services/ src/ scripts/ production/ docs/
services/ic_engine.py:488: the sole runtime cfg.get_sync() read
production/migrations/229_regime_group.sql:15: "is NOT retired here; its retirement is decided in Plan 05..."
production/migrations/174_market_regimes.sql: original seed migration (comments + INSERT)
scripts/ops/corpus/ops_corpus_pipeline_run.sh:325: comment only
```

`services/ic_engine.py` is confirmed the SOLE runtime consumer of `alpha.regime.equity_model_enabled` -- every other hit is either a docstring/comment, a migration-file description, or the same shell-script comment referenced twice. Per the plan's instruction, this qualifies for retirement.

**Resolution:** the standalone kill-switch is retired -- `main()`'s runtime `equity_model_enabled` local variable is now derived as `bool(enabled_groups)` (computed after parsing `alpha.regime.groups` via `_parse_group_configs`), never from `config.equity_model_enabled`. The `ICEngineConfig.equity_model_enabled` dataclass field and its `from_apr()` binding from the old APR key were **kept** rather than deleted, because three existing test files construct `ICEngineConfig(...)` directly with `equity_model_enabled=True` as an explicit field (`tests/unit/test_hac_ic_sharpe.py`, `tests/unit/test_ic_engine_lifecycle_hook.py`'s `_make_config` helper -- itself re-imported by `tests/unit/test_ic_engine_staleness.py`). Field removal would have forced edits to all three for a field whose only remaining risk (behavioral drift) is fully eliminated once nothing reads it. This matches the codebase's own established convention for this exact scenario, documented literally in `ICEngineConfig`'s own docstring for the Phase 143/143.1 fields: default new/changed fields rather than break existing direct-constructor test call sites. The field is now vestigial (bound but unread); only `bool(enabled_groups)` drives behavior, eliminating the two-sources-of-truth drift risk Pitfall 3 warned about.

**Other decisions:**
- `_build_symbol_regime_class` is a standalone duplicate (not an import) of the tag-routing logic already in `cross_sectional_regime_model.py`'s `_resolve_group_symbols` -- per RESEARCH.md's own recommendation (Open Question 1), since the two answer inverse questions (symbol->group here vs. group->peer-symbols there) and only this side needs `AmbiguousRegimeGroupError` (the dispatcher resolves one group's peers at a time, never needing cross-group ambiguity detection).
- Confirmed via live schema check that `feature_ic_scores` has no `regime_group` column -- group identity stays implicit in `regime_label` string uniqueness (RESEARCH.md Pitfall 4's documented invariant), unchanged by this plan; no schema migration needed.
- The docstring line in `_compute_cross_sectional_tf` originally written to describe the historical bug used the literal substring `asset_class='equity'`, which would have registered as a false-positive hit against this plan's own `grep -c "asset_class='equity'|asset_class = 'equity'"` acceptance check (mirroring the 144-04 lesson about a plan's own grep-based verify command catching prose, not just code) -- reworded to describe the column by reference (\"the (now-renamed, migration 229) equity-only asset class column\") instead of the literal string.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] Worktree reset to Wave 2 tip before starting execution**
- **Found during:** Startup, `<worktree_branch_check>` step
- **Issue:** The worktree's `git merge-base HEAD 374c7ec5` was HEAD itself (`16680c24`), an ancestor of the expected base `374c7ec5` -- missing Wave 2's plan 04 (dispatcher, `_parse_group_configs`) plus a handful of unrelated same-day docs/todo commits already on `main`. Executing against the stale base would have made this plan's `from services.cross_sectional_regime_model import _parse_group_configs` import fail immediately.
- **Fix:** Ran `git reset --hard 374c7ec5` per the orchestrator's explicit instruction in `<worktree_branch_check>`. `git status --short` was clean before the reset (no uncommitted work to lose).
- **Files modified:** None (branch pointer only).
- **Verification:** `git log --oneline -3` confirmed the reset landed on `374c7ec5`; `grep -n "def _parse_group_configs" services/cross_sectional_regime_model.py` confirmed the Wave 2 dispatcher was present before writing any code.

**2. [Rule 1 - Bug] Docstring literal string collision with the plan's own grep-based acceptance check**
- **Found during:** Task 2 verification (`grep -c "asset_class='equity'\|asset_class = 'equity'"` returned 1, not the required 0)
- **Issue:** A docstring I added to `_compute_cross_sectional_tf` describing the historical contamination bug used the literal substring `asset_class='equity'` in prose, which the plan's own automated verify grep cannot distinguish from a live SQL site.
- **Fix:** Reworded the docstring sentence to describe the column by reference instead of using the literal string.
- **Files modified:** `services/ic_engine.py`
- **Verification:** `grep -c "asset_class='equity'\|asset_class = 'equity'" services/ic_engine.py` returns 0; committed as part of Task 2's commit (`59e78d9d`).

**3. [Rule 3 - Blocking issue] `json` module not imported**
- **Found during:** Task 1, writing `ICEngineConfig.from_apr()`'s `regime_groups_json` normalization
- **Issue:** `services/ic_engine.py` had no `import json` -- required for `json.dumps()` when normalizing an already-parsed `list[dict]` APR value back to a JSON string.
- **Fix:** Added `import json` to the module's stdlib import block.
- **Files modified:** `services/ic_engine.py`
- **Verification:** `python3 -c "import ast; ast.parse(...)"` passed; full suite green; committed as part of Task 1's commit (`7fcbdf12`).

---

**Total deviations:** 3 auto-fixed (1 blocking worktree-state fix, 1 bug fix, 1 blocking missing-import fix)
**Impact on plan:** All three were necessary to complete the plan as specified; no scope creep, no architectural changes.

## Issues Encountered

The full-suite verification run (`'.venv/bin/pytest tests/unit/ -q`) took ~11.5 minutes (692s) — long enough that an earlier `timeout 550` wrapper cut it off mid-run (exit 143) before it could report results. Re-ran without the restrictive wrapper (backgrounded, no timeout) and confirmed completion: `1 failed, 5886 passed, 42 skipped, 367 warnings in 692.27s`. The 1 failure is the pre-existing, unrelated `tests/unit/test_feature_factory.py::TestRegimePrimitives::test_no_smooth_or_backward_in_factory` -- explicitly tolerated per this plan's and RESEARCH.md's stated baseline. No other collection errors or `ic_engine`-related failures, confirming Task 2's edits were applied against the correct live baseline (Pitfall 2's warning sign was absent).

## Known Stubs

None -- both the routing function and the SQL generalization are fully wired end-to-end. `commodity_energy`/`commodity_metals`/`commodity_agri`/`fx` groups remain `enabled: false` in `alpha.regime.groups` (a Phase 144 Plan 01/CONTEXT.md D-04 scope decision, not a stub introduced by this plan) -- `_build_symbol_regime_class` and the cross-sectional pass correctly skip them entirely since they're not in `enabled_groups`.

## Threat Flags

None beyond what 144-05-PLAN.md's own `<threat_model>` already registered and this plan implements as specified:
- T-144-05-SQL (all new WHERE clauses use bound params, `regime_group`/`symbol_list` never string-interpolated) -- implemented as specified; verified via direct read of every new SQL site.
- T-144-05-ROUTE (fail-loud `AmbiguousRegimeGroupError`, omit-not-default) -- implemented as specified, unit tested.
- T-144-05-JSON (`from_apr` normalizes already-parsed-list vs raw-string, never `str()`s a list) -- implemented as specified; `grep "str(cfg.get_sync" services/ic_engine.py` near the new binding returns nothing (the one unrelated hit, `ensemble_weight_version`, predates this plan and is a genuine string-typed APR value).
- T-144-05-CONTAM (`symbol_list` filter is the pooling contamination fix) -- implemented as specified; the actual correctness deliverable of this plan.

No new trust boundary or surface was introduced beyond what the plan's threat model already covers.

## User Setup Required

None -- no external service configuration required. Running `cross_sectional_regime_model.py` and the batched `ic_engine` re-run against this code is explicitly deferred to after the in-flight 143.1-07 corpus rebuild completes (CONTEXT.md D-07), per this phase's own sequencing decision -- not something this plan is responsible for triggering.

## Next Phase Readiness

- `ic_engine.py`'s regime_group routing and cross-sectional peer-scoping fix are code-complete and unit-tested; ready for the corpus re-run and D-05 acceptance-gate measurement step (Plan 06, per CONTEXT.md D-05/D-06/D-07 sequencing) once the in-flight 143.1-07 corpus rebuild completes and is verified clean.
- No blockers introduced by this plan. The `equity_model_enabled` retirement is a pure internal simplification (single source of truth) with no external-facing behavior change beyond the intended contamination fix.

## Self-Check: PASSED

- FOUND: services/ic_engine.py
- FOUND: tests/unit/test_ic_engine_routing.py
- FOUND commit: 7fcbdf12 (Task 1)
- FOUND commit: 59e78d9d (Task 2)
- Verified: `grep -c "asset_class='equity'\|asset_class = 'equity'" services/ic_engine.py` returns 0
- Verified: `grep "symbol = ANY(%(symbol_list)s)" services/ic_engine.py` matches
- Verified: `grep "_build_symbol_regime_class" services/ic_engine.py` matches
- Verified: `grep "regime_groups_json" services/ic_engine.py` matches
- Verified: `.venv/bin/pytest tests/unit/test_ic_engine_routing.py -v` — 8/8 passed
- Verified: full unit suite `.venv/bin/pytest tests/unit/ -q` — 5886 passed, 42 skipped, 1 pre-existing unrelated failure (`test_no_smooth_or_backward_in_factory`), consistent with the tolerated baseline noted in RESEARCH.md and prior phase summaries

---
*Phase: 144-cross-sectional-regime-model-regime-group*
*Completed: 2026-07-12*
