---
phase: 144-cross-sectional-regime-model-regime-group-planned
plan: 04
subsystem: intelligence
tags: [regime-model, cross-sectional, dispatcher, ic-engine, apr, corpus-pipeline]

# Dependency graph
requires:
  - phase: 144-01
    provides: market_regimes.regime_group column (migration 229) + alpha.regime.groups APR key + per-group threshold namespaces
  - phase: 144-02
    provides: src.intelligence.regime_signals.tf_window/_tf_window, breadth_vol.compute()/build_tiers()/PROB_KEYS, curve_credit.compute()/build_tiers()/PROB_KEYS
  - phase: 144-03
    provides: src.intelligence.regime_signals.commodity_momentum_ts and fx_dollar_carry (compute()/build_tiers()/PROB_KEYS, REFERENCE_SYMBOLS)
provides:
  - "src.intelligence.regime_signals.REGISTRY: dict[str, module] mapping all four signal_type strings to their pluggable signal module"
  - "services/cross_sectional_regime_model.py: generic multi-group dispatcher (main(), DB fetch/write, TF-window pre-scaling, D-06 oneshot contract) replacing equity_regime_model.py in the corpus pipeline"
  - "market_regimes rows written with regime_group set on every row for equity + rates (commodity/fx groups ship enabled=false, wired but not yet run)"
  - "services/equity_regime_model.py retained as a deprecated single-group rollback path (docstring-only change)"
  - "corpus pipeline step-4 slot runs cross_sectional_regime_model.py instead of equity_regime_model.py"
affects: [144-05-ic-engine-routing]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "_parse_group_configs accepts str | list[dict] -- json.loads() only fires for a raw string input; an already-parsed list (the live shape returned by ConfigService's json-typed cache) passes through unchanged. Prevents the str(cfg.get_sync(...)) repr-string bug (Python repr uses single quotes/True/False, which is not valid JSON)."
    - "Dispatcher pre-scales every daily-bar-denominated APR window param to the target TF via _tf_window() BEFORE calling a signal module's compute() -- signal modules stay TF-agnostic, matching the convention locked by 144-01's migration and 144-02's breadth_vol/curve_credit."
    - "REFERENCE_SYMBOLS module attribute (fx_dollar_carry's UUP/HYG) is fetched alongside peer-group symbols via getattr(signal_mod, 'REFERENCE_SYMBOLS', ()) -- a signal module can require inputs outside its own tag-resolved peer group without the dispatcher needing per-module special-casing."
    - "Unknown signal_type in alpha.regime.groups fails loud (RuntimeError, never a silent skip) -- config-authoring errors surface immediately, matching the fail-loud AmbiguousRegimeGroupError precedent this phase establishes for ic_engine.py routing (Plan 05)."

key-files:
  created: []
  modified:
    - src/intelligence/regime_signals/__init__.py
    - services/cross_sectional_regime_model.py
    - services/equity_regime_model.py
    - scripts/ops/corpus/ops_corpus_pipeline_run.sh
    - tests/unit/test_cross_sectional_regime_model.py

key-decisions:
  - "Split the single-file deliverable into two atomic commits by writing a Task-1-scoped version of cross_sectional_regime_model.py (pure functions only, no DB/main() imports) first, then extending it in Task 2's commit with the DB/runtime layer -- keeps each commit's diff matching its task's stated <files> scope rather than landing the whole file in one commit."
  - "_parse_group_configs still filters to enabled=true groups internally (matches the plan doc's original behavior and the test file's test_filters_disabled_groups expectation) -- the union-type fix only changes HOW the input is parsed (str vs already-parsed list), not what the function returns."
  - "Rephrased the module docstring's no-worker-pool explanation to avoid the literal substring 'ProcessPoolExecutor' -- the plan's own automated verify command is a raw grep for that string with no comment/import distinction, so explaining the absence of a pool in prose would have false-failed its own acceptance check."

patterns-established:
  - "cross_sectional_regime_model.py dispatcher shape: parse group configs -> resolve peer symbols via instrument_tags -> load per-group APR params -> for each TF, pre-scale window params -> fetch peer+reference bars (fresh connection) -> compute() -> assign_labels() -> upsert. Plan 05's ic_engine.py routing consumes market_regimes.regime_group rows this dispatcher writes."

requirements-completed: []

# Metrics
duration: ~45min
completed: 2026-07-12
---

# Phase 144 Plan 04: Cross-Sectional Regime Model Dispatcher Summary

**Built the generic multi-group `cross_sectional_regime_model.py` dispatcher that replaces the equity-only `equity_regime_model.py` in the corpus pipeline's step-4 slot, wiring the REGISTRY, the JSON-parse fix for the already-parsed APR config shape, and TF-window pre-scaling for every enabled `alpha.regime.groups` entry.**

## Performance

- **Duration:** ~45 min
- **Started:** 2026-07-12T18:38:00Z
- **Completed:** 2026-07-12T18:57:00Z
- **Tasks:** 2/2 completed
- **Files modified:** 5 (1 created new — `__init__.py` — plus 4 modified)

## Accomplishments
- `src/intelligence/regime_signals/__init__.py`: `REGISTRY` dict mapping all four `signal_type` strings (`breadth_vol`, `curve_credit`, `commodity_momentum_ts`, `fx_dollar_carry`) to their pluggable signal modules — registry completeness independent of group enablement
- `services/cross_sectional_regime_model.py`: complete generic dispatcher — pure functions (`_parse_group_configs` with the `str | list[dict]` JSON-parse fix, `_resolve_group_symbols`, `_bucket`, `_assign_labels`) plus the full runtime (`main()`, DB fetch/write, TF-window pre-scaling via `_tf_window()`, D-06 `JOB_COMPLETED_TOTAL` oneshot contract, no worker pool)
- `services/equity_regime_model.py`: deprecation docstring header only — retained as the emergency single-group rollback path, zero functional changes
- `scripts/ops/corpus/ops_corpus_pipeline_run.sh`: step-4 slot swapped from `equity_regime_model.py` to `cross_sectional_regime_model.py`, same slot, no step renumbering (still 8 steps)
- `tests/unit/test_cross_sectional_regime_model.py`: 18 tests, extended beyond the plan doc's original test file with a both-input-shapes regression test (`test_str_and_list_inputs_normalize_identically`) proving `_parse_group_configs` normalizes an already-parsed `list[dict]` and an equivalent raw JSON string identically

## Task Commits

Each task was committed atomically:

1. **Task 1: REGISTRY + dispatcher pure functions (with JSON-parse fix)** - `0e6f0486` (feat)
2. **Task 2: dispatcher main()/fetch/write + TF-scaling + deprecation header + pipeline swap** - `1fed751c` (feat)

_Note: both tasks were `tdd="true"`. As in 144-02, the module logic being ported (dispatcher shape, TF-scaling convention) already existed in a research-vetted, bug-fixed design (the plan doc's own already-complete pure-function code, cross-checked against `equity_regime_model.py`'s fresh-connection/D-06 patterns) — implementation and test were written together per task and verified green before commit, rather than a separate RED-then-GREEN cycle discovering novel behavior._

## Files Created/Modified
- `src/intelligence/regime_signals/__init__.py` - `REGISTRY: dict[str, object]` mapping all four signal_type modules
- `services/cross_sectional_regime_model.py` - generic cross-sectional regime dispatcher (created across both task commits: pure functions in Task 1, DB/runtime in Task 2)
- `services/equity_regime_model.py` - deprecation docstring header (no functional change)
- `scripts/ops/corpus/ops_corpus_pipeline_run.sh` - step-4 slot script-name swap
- `tests/unit/test_cross_sectional_regime_model.py` - 18 unit tests (14 from the plan doc's original spec + 4 additional: `test_accepts_already_parsed_list`, `test_str_and_list_inputs_normalize_identically`, `test_regime_group_set_on_every_row`, `test_no_single_label_exceeds_sane_share_of_synthetic_fixture`)

## Decisions Made
- Split `cross_sectional_regime_model.py`'s single-file deliverable into two atomic commits matching the plan's per-task `<files>` scope: Task 1 landed only the pure, DB-free helper functions (`_parse_group_configs`/`_resolve_group_symbols`/`_bucket`/`_assign_labels`) importable for unit testing; Task 2 extended the same file with the DB/runtime layer (imports, constants, `main()`). This keeps each commit's diff auditable against its task's stated scope rather than landing the whole ~450-line file in one commit.
- Kept `_parse_group_configs`'s enabled-filtering behavior (returns only `enabled: true` groups) exactly as the plan doc and its own test suite (`test_filters_disabled_groups`) specify — the JSON-parse fix changes only HOW the raw input is normalized (`isinstance(raw, list)` branch vs. `json.loads()` branch), not what the function returns.
- Reference-symbol fetching (`fx_dollar_carry`'s `UUP`/`HYG`, needed regardless of whether those symbols match the `fx` group's own `tag_filter`) is handled generically via `getattr(signal_mod, "REFERENCE_SYMBOLS", ())` in the dispatcher's per-TF loop, rather than a `fx`-specific branch — any future signal module can opt into the same mechanism by declaring its own `REFERENCE_SYMBOLS` tuple.
- Rephrased a docstring sentence explaining the dispatcher's single-process design to avoid the literal substring `ProcessPoolExecutor` — the plan's Task 2 automated verify command (`! grep -q 'ProcessPoolExecutor' services/cross_sectional_regime_model.py`) is a raw string match with no comment/import distinction; using the word in prose (even to say "we deliberately don't use one") would have failed the plan's own acceptance check.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking issue] Worktree reset to main tip before starting execution**
- **Found during:** Startup, `<worktree_branch_check>` step
- **Issue:** The worktree's `merge-base` with the expected base commit `6bd36c86` was `16680c24`, an ancestor of `6bd36c86` missing Wave 1's three merged plans (144-01/02/03 — migration 229, `tf_window.py`, `breadth_vol.py`, `curve_credit.py`, `commodity_momentum_ts.py`, `fx_dollar_carry.py`). Executing against the stale base would have meant this plan's imports (`from src.intelligence.regime_signals.tf_window import _tf_window`, `from src.intelligence.regime_signals import REGISTRY` module targets) failed immediately.
- **Fix:** Ran `git reset --hard 6bd36c86` per the orchestrator's explicit instruction in `<worktree_branch_check>`. `git status --short` was clean before the reset (no uncommitted work to lose).
- **Files modified:** None (branch pointer only).
- **Verification:** `git log --oneline -5` confirmed the reset landed on `6bd36c86` with the three Wave 1 merge commits in history; `ls src/intelligence/regime_signals/` confirmed all four sibling-plan signal modules were present before writing any code.

## Known Stubs

None — the dispatcher is fully wired end-to-end (parse config → resolve symbols → fetch bars → pre-scale window params → compute → assign labels → upsert). No placeholder values or unwired code paths. `commodity_energy`/`commodity_metals`/`commodity_agri`/`fx` groups remain `enabled: false` in the APR config (migration 229, seeded by 144-01) — this is an intentional, documented phase-scope decision (CONTEXT.md D-04, todo 041 gates enablement), not a stub in this plan's own deliverable.

## Threat Flags

None beyond what 144-04-PLAN.md's own `<threat_model>` already registered and this plan implements as specified:
- T-144-04-DISP (unknown `signal_type` fails loud via `RuntimeError`, never silently skips) — implemented as specified.
- T-144-04-JSON (`_parse_group_configs`'s `str | list[dict]` fix) — implemented as specified, with regression test coverage.
- T-144-04-SQL (parameterized `market_regimes` upsert, `json.dumps()` + `::jsonb` cast) — implemented as specified, ported unchanged from the plan doc's Task 4 code.
- T-144-04-CONN (fresh-connection-per-fetch pattern) — implemented as specified.

No new trust boundary or surface was introduced beyond what the plan's threat model already covers.

## Self-Check: PASSED

- FOUND: src/intelligence/regime_signals/__init__.py (REGISTRY, 4 modules mapped)
- FOUND: services/cross_sectional_regime_model.py (parses, D-06 contract present, no ProcessPoolExecutor)
- FOUND: services/equity_regime_model.py deprecation header (git diff --stat shows 9 insertions, 0 deletions — docstring only)
- FOUND: scripts/ops/corpus/ops_corpus_pipeline_run.sh step-4 slot runs cross_sectional_regime_model.py; `Step %d/8` banner unchanged (grep count = 1)
- FOUND: tests/unit/test_cross_sectional_regime_model.py — 18/18 passed
- FOUND commit: 0e6f0486 (Task 1)
- FOUND commit: 1fed751c (Task 2)
- Verified: `grep "str(cfg.get_sync" services/cross_sectional_regime_model.py` returns nothing
- Verified: full unit suite `.venv/bin/pytest tests/unit/ -q` — 5878 passed, 42 skipped, 1 pre-existing unrelated failure (`test_no_smooth_or_backward_in_factory`), consistent with the tolerated baseline noted in RESEARCH.md and prior phase summaries

---
*Phase: 144-cross-sectional-regime-model-regime-group-planned*
*Completed: 2026-07-12*
