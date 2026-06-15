---
phase: 125-apr-full-migration-all-three-tiers
plan: C
type: execute
wave: 1
depends_on: []
files_modified:
  - src/intelligence/trading/confidence_utils.py
  - tests/unit/intelligence/test_param_store_migration.py
autonomous: true
requirements:
  - APR-03

must_haves:
  truths:
    - "_validate_weights_sum exists in confidence_utils.py with the correct signature and raises ValueError on bad sums"
    - "set_config_service parameter is renamed from cfg to config in confidence_utils.py"
    - "_validate_weights_sum raises ValueError (not AssertionError) when weights do not sum to 1.0"
    - "two cleanup TODOs are captured in .planning/todos/pending/ for future rename work"
  artifacts:
    - path: "src/intelligence/trading/confidence_utils.py"
      provides: "_validate_weights_sum utility + cfg->config fix"
      contains: "_validate_weights_sum"
    - path: "tests/unit/intelligence/test_param_store_migration.py"
      provides: "Tests for _validate_weights_sum and updated teardown"
  key_links:
    - from: "src/intelligence/trading/confidence_utils.py"
      to: "src/intelligence/trading/anchored_vwap_reversion.py"
      via: "import _validate_weights_sum"
      pattern: "from.*confidence_utils.*import.*_validate_weights_sum"
---

<objective>
Add _validate_weights_sum utility to confidence_utils.py, fix the cfg parameter name, and capture two cleanup TODOs.

Purpose: Centralizes the weight-sum invariant in one place so all 6 applicable Tier B plugins share one code path. The cfg rename in set_config_service() closes naming violation D-04. Two cleanup TODOs flag the confidence_utils.py rename and zone_engine._cfg() rename for a future polish phase.
Output: confidence_utils.py with new utility + parameter fix. Unit tests covering the utility. Two todo files capturing deferred renames.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/phases/125-apr-full-migration-all-three-tiers/125-CONTEXT.md
@.planning/phases/125-apr-full-migration-all-three-tiers/125-RESEARCH.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add _validate_weights_sum and fix cfg parameter in confidence_utils.py</name>
  <read_first>
    - src/intelligence/trading/confidence_utils.py (full file — understand current set_config_service signature at line 43, module structure before adding the new function)
    - tests/unit/intelligence/test_param_store_migration.py (full file — understand teardown_function which calls cu.set_config_service(None); the call still works after parameter rename since the parameter is positional)
  </read_first>
  <files>src/intelligence/trading/confidence_utils.py</files>
  <action>
    Change 1: Rename parameter in set_config_service.
    At line 43, change the signature from:
      def set_config_service(cfg: Any) -> None:
    to:
      def set_config_service(config: Any) -> None:
    Inside the function body, change the assignment from:
      _config_service = cfg
    to:
      _config_service = config
    The module-level variable _config_service is fine — only the function parameter is renamed.

    Change 2: Add _validate_weights_sum function immediately after get_min_ctf_score() (after line ~57).
    The function:

      def _validate_weights_sum(weights: dict[str, float], plugin: str, tol: float = 1e-6) -> None:
          """Validate that confidence weights sum to 1.0 within floating-point tolerance.

          Raises ValueError (not AssertionError — asserts disabled by -O) if the
          invariant is violated. Called at prewarm/init time so bad DB seeds or
          bad operator writes fail fast at daemon startup, before any signal fires.

          Args:
              weights: Dict of weight name to value (e.g. {'roc': 0.40, 'vol': 0.35, ...}).
              plugin:  Human-readable plugin name for error messages.
              tol:     Floating-point tolerance. Default 1e-6 handles float repr of 0.40+0.35+0.25.
          """
          total = sum(weights.values())
          if abs(total - 1.0) > tol:
              raise ValueError(f"{plugin} weights sum to {total:.6f}, expected 1.0")

    Place this after get_min_ctf_score() and before clamp01().

    Do NOT change any other function signatures, constants, or logic in the file.
  </action>
  <verify>
    .venv/bin/python -c "from src.intelligence.trading.confidence_utils import _validate_weights_sum; _validate_weights_sum({'a': 0.40, 'b': 0.35, 'c': 0.25}, 'TestPlugin'); print('ok')"
    Expected: ok

    .venv/bin/python -c "from src.intelligence.trading.confidence_utils import _validate_weights_sum; import sys; [print(e) for e in [repr(e)] if (lambda: (_ for _ in ()).throw(e))()] if False else None; _validate_weights_sum({'a': 0.40, 'b': 0.40, 'c': 0.25}, 'TestPlugin')" 2>&1 | grep ValueError
    Expected: ValueError in output

    grep -n "def set_config_service" src/intelligence/trading/confidence_utils.py
    Expected: line contains "config: Any" not "cfg: Any"

    .venv/bin/python -c "import src.intelligence.trading.confidence_utils as cu; cu.set_config_service(None); print('ok')"
    Expected: ok (positional call still works)
  </verify>
  <done>_validate_weights_sum exists in confidence_utils.py with the exact signature specified. It raises ValueError (not AssertionError) when abs(sum - 1.0) > 1e-6. set_config_service parameter is named config not cfg.</done>
</task>

<task type="auto">
  <name>Task 2: Add _validate_weights_sum tests and capture cleanup TODOs</name>
  <read_first>
    - tests/unit/intelligence/test_param_store_migration.py (full file — add _validate_weights_sum tests here, following existing test pattern. Update teardown_function if it calls cu.set_config_service(None) — parameter still works positionally so no change needed)
  </read_first>
  <files>
    tests/unit/intelligence/test_param_store_migration.py
    .planning/todos/pending/2026-06-14-rename-confidence-utils.md
    .planning/todos/pending/2026-06-14-rename-cfg-in-zone-engine.md
  </files>
  <action>
    In tests/unit/intelligence/test_param_store_migration.py, add the following tests at the end of the file (after existing tests, before any future additions):

      from src.intelligence.trading.confidence_utils import _validate_weights_sum
      import pytest

      def test_validate_weights_sum_passes_on_exact():
          _validate_weights_sum({"a": 0.40, "b": 0.35, "c": 0.25}, "TestPlugin")

      def test_validate_weights_sum_passes_within_tolerance():
          # 0.4+0.3+0.3 may not be exactly 1.0 due to float repr; must pass
          _validate_weights_sum({"a": 0.4, "b": 0.3, "c": 0.3}, "TestPlugin")

      def test_validate_weights_sum_raises_on_bad_seed():
          with pytest.raises(ValueError, match="TestPlugin weights sum to"):
              _validate_weights_sum({"a": 0.40, "b": 0.40, "c": 0.25}, "TestPlugin")

      def test_validate_weights_sum_raises_value_error_not_assertion_error():
          """ValueError must fire even under Python -O (which disables asserts)."""
          with pytest.raises(ValueError):
              _validate_weights_sum({"a": 0.60, "b": 0.60}, "BadPlugin")

    Create two cleanup TODO files:

    File 1: .planning/todos/pending/2026-06-14-rename-confidence-utils.md
    Content:
      # TODO: Rename confidence_utils.py to confidence.py
      Created: 2026-06-14
      Phase: Capture from Phase 125 D-05
      Status: pending

      ## What
      `confidence_utils.py` uses the retired word "Utils" (naming system §3 retired words list).
      Correct name: `src/intelligence/trading/confidence.py`

      ## Why deferred
      39 import sites across the codebase. Requires grep-and-replace across all callers.
      Out of scope for Phase 125 (which adds _validate_weights_sum to the file).

      ## How to do it
      1. git mv src/intelligence/trading/confidence_utils.py src/intelligence/trading/confidence.py
      2. grep -r "confidence_utils" src/ tests/ services/ to find all import sites
      3. Update all imports in one commit
      4. Update CLAUDE.md reference to the file

    File 2: .planning/todos/pending/2026-06-14-rename-cfg-in-zone-engine.md
    Content:
      # TODO: Rename _cfg() to _read_config() in zone_engine.py
      Created: 2026-06-14
      Phase: Capture from Phase 125 D-05
      Status: pending

      ## What
      `_cfg()` in zone_engine.py uses the banned abbreviation "cfg" (naming system §6 Tier 3 banned).
      Correct name: `_read_config()`

      ## Why deferred
      Phase 125 does not touch zone_engine.py code. Rename belongs in a dedicated cleanup commit.

      ## How to do it
      1. Rename _cfg() to _read_config() in zone_engine.py
      2. Update all call sites within zone_engine.py (internal function only)
  </action>
  <verify>
    .venv/bin/pytest tests/unit/intelligence/test_param_store_migration.py -v --no-header 2>&1 | tail -20
    Expected: All existing tests pass plus 4 new _validate_weights_sum tests pass

    ls .planning/todos/pending/2026-06-14-rename-confidence-utils.md
    ls .planning/todos/pending/2026-06-14-rename-cfg-in-zone-engine.md
    Expected: Both files exist
  </verify>
  <done>4 new _validate_weights_sum unit tests pass in test_param_store_migration.py. Two cleanup TODO files exist in .planning/todos/pending/ with content as specified above.</done>
</task>

</tasks>

<verification>
.venv/bin/pytest tests/unit/intelligence/test_param_store_migration.py -q --no-header 2>&1 | tail -5
Expected: all tests pass, no failures

grep -c "_validate_weights_sum" src/intelligence/trading/confidence_utils.py
Expected: at least 2 (function def + docstring reference)
</verification>

<success_criteria>
_validate_weights_sum is in confidence_utils.py with correct signature. set_config_service parameter is named config. 4 unit tests pass. Two cleanup TODO files captured.
</success_criteria>

<output>
After completion, create .planning/phases/125-apr-full-migration-all-three-tiers/125-C-SUMMARY.md
</output>
