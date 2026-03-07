---
phase: 15-validated-alpha
plan: GAP-02
type: execute
wave: 2
depends_on: ["GAP-01"]
files_modified:
  - src/intelligence/trading/candlestick_pattern_setup.py
  - tests/unit/intelligence/test_trading_setups.py
autonomous: true
gap_closure: true
requirements: [ALPHA-03]

must_haves:
  truths:
    - "CandlestickPatternSetupPlugin reads all 9 new Tier 1 pattern fields from the features dict"
    - "Each new pattern produces correct direction, confidence, and signal_type when trend regime agrees"
    - "All new patterns respect the same CNDL-02 volume/S&R confirmation gate as existing patterns"
    - "Nine validate_alpha.py audit-trail runs exist in docs/validation/ (verdict=BOOTSTRAP for all 9)"
    - "Full unit test suite passes with no regressions"
  artifacts:
    - path: "src/intelligence/trading/candlestick_pattern_setup.py"
      provides: "I7 plugin reading all 9 new pattern fields from I5"
      contains: "three_white_soldiers"
    - path: "tests/unit/intelligence/test_trading_setups.py"
      provides: "Tests for each new pattern path through CandlestickPatternSetupPlugin"
    - path: "docs/validation/2026-03-07-patt_CandlestickPatterns-morning_star-bootstrap.json"
      provides: "Bootstrap audit trail (one of nine)"
  key_links:
    - from: "CandlestickPatternsPlugin (I5)"
      to: "CandlestickPatternSetupPlugin (I7)"
      via: "features.get('<pattern_name>', 0.0) named reads in compute_full()"
      pattern: "features\\.get.*three_white_soldiers"
---

<objective>
Bootstrap-promote all 9 Tier 1 candlestick patterns from I5 (CandlestickPatternsPlugin — already live) to I7 (CandlestickPatternSetupPlugin), closing Gap 2 from the verification report.

Purpose: The patterns are already computed in I5 and written to intelligence_features.i5 on every bar. The only missing link is the I7 read. This plan adds all 9 named reads to CandlestickPatternSetupPlugin.compute_full() using TDD, then writes bootstrap audit trails for all 9 patterns (expected: BOOTSTRAP — same data-absence policy as GAP-01).

Output: CandlestickPatternSetupPlugin can fire signals for all 15 candlestick patterns (6 original + 9 new). Nine bootstrap JSON files in docs/validation/ for audit trail completeness.
</objective>

<execution_context>
@/home/bg/.claude/get-shit-done/workflows/execute-plan.md
@/home/bg/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/15-validated-alpha/15-CONTEXT.md
@.planning/phases/15-validated-alpha/15-VERIFICATION.md
@.planning/phases/15-validated-alpha/15-GAP-01-PLAN.md

<interfaces>
<!-- Key interfaces the executor needs. -->

From src/intelligence/trading/candlestick_pattern_setup.py (current state):

Current 6 named reads (lines 72-77):
```python
engulfing_bull = float(features.get("engulfing_bull", 0.0))
engulfing_bear = float(features.get("engulfing_bear", 0.0))
pin_bar_bull = float(features.get("pin_bar_bull", 0.0))
pin_bar_bear = float(features.get("pin_bar_bear", 0.0))
hammer = float(features.get("hammer_detected", 0.0))
shooting_star = float(features.get("shooting_star_detected", 0.0))
```

Current 6 candidate entries (lines 82-93):
```python
if hammer > 0.0:
    candidates.append((0, 1, "hammer", 0.65, True))
if shooting_star > 0.0:
    candidates.append((0, -1, "shooting_star", 0.65, True))
if engulfing_bull > 0.0:
    candidates.append((1, 1, "engulfing", 0.55, False))
if engulfing_bear > 0.0:
    candidates.append((1, -1, "engulfing", 0.55, False))
if pin_bar_bull > 0.0:
    candidates.append((2, 1, "pin_bar", 0.45, False))
if pin_bar_bear > 0.0:
    candidates.append((2, -1, "pin_bar", 0.45, False))
```

9 new patterns to add (from CONTEXT.md and VERIFICATION.md gap description):
Candidate tuple format: (priority_rank, direction, pattern_name, base_confidence, sr_auto_satisfied)

| I5 field name         | Direction | priority | base_confidence | sr_auto |
|-----------------------|-----------|----------|-----------------|---------|
| three_white_soldiers  | 1 (bull)  | 1        | 0.75            | False   |
| three_black_crows     | -1 (bear) | 1        | 0.75            | False   |
| morning_star          | 1 (bull)  | 2        | 0.80            | False   |
| evening_star          | -1 (bear) | 2        | 0.80            | False   |
| three_inside_up       | 1 (bull)  | 3        | 0.65            | False   |
| three_inside_down     | -1 (bear) | 3        | 0.65            | False   |
| harami_cross          | context   | 4        | 0.60            | False   |
| dark_cloud_cover      | -1 (bear) | 3        | 0.70            | False   |
| piercing_line         | 1 (bull)  | 3        | 0.70            | False   |

Note on harami_cross: direction is determined by trend_regime (bullish trend → direction=1, bearish → direction=-1). It has no intrinsic direction — use `trend_dir` (already computed from trend_regime in the function).

The I5 field names match exactly what CandlestickPatternsPlugin outputs.
Confirm with: grep -n "three_white_soldiers\|morning_star\|harami_cross" src/intelligence/patterns/candlestick_patterns.py

From src/intelligence/patterns/candlestick_patterns.py (output field names, for reference):
The existing I5 plugin outputs frozenset of 18 fields. The 9 new fields are:
"three_white_soldiers", "three_black_crows", "morning_star", "evening_star",
"three_inside_up", "three_inside_down", "harami_cross", "dark_cloud_cover", "piercing_line"
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Write RED tests for 9 new patterns in CandlestickPatternSetupPlugin</name>
  <files>tests/unit/intelligence/test_trading_setups.py</files>
  <behavior>
    For each new pattern, write a test that:
    1. Builds a features dict with the pattern field set to 1.0 and trend_regime agreeing with expected direction
    2. Builds a minimal OHLCV df (20+ bars, last close = 5000.0, ATR-compatible)
    3. Calls plugin.compute_full({"main": df, "features": features})
    4. Asserts result["direction"] == expected_direction and result["signal_type"] contains the pattern name

    Tests to write (one per new pattern — 9 total):
    - test_three_white_soldiers_bullish: features={"three_white_soldiers": 1.0, "trend_regime": 0.7, ...} → direction=1, signal_type contains "three_white_soldiers"
    - test_three_black_crows_bearish: features={"three_black_crows": 1.0, "trend_regime": -0.7, ...} → direction=-1
    - test_morning_star_bullish: features={"morning_star": 1.0, "trend_regime": 0.7, ...} → direction=1
    - test_evening_star_bearish: features={"evening_star": 1.0, "trend_regime": -0.7, ...} → direction=-1
    - test_three_inside_up_bullish: features={"three_inside_up": 1.0, "trend_regime": 0.7, ...} → direction=1
    - test_three_inside_down_bearish: features={"three_inside_down": 1.0, "trend_regime": -0.7, ...} → direction=-1
    - test_harami_cross_follows_trend: features={"harami_cross": 1.0, "trend_regime": 0.7, ...} → direction=1 (follows bullish trend)
    - test_dark_cloud_cover_bearish: features={"dark_cloud_cover": 1.0, "trend_regime": -0.7, ...} → direction=-1
    - test_piercing_line_bullish: features={"piercing_line": 1.0, "trend_regime": 0.7, ...} → direction=1

    Each test must also include volume_sma_20 in features so the volume confirmation path works (set vol > 1.3x vol_sma_20 in the df, or include nearest_support/resistance close to entry price for S/R path).

    Use the existing test helpers in test_trading_setups.py (look for make_ohlcv or similar helper) — or build a minimal 20-row DataFrame inline.

    At this point (before Task 2), these 9 tests MUST FAIL because the plugin does not yet read these fields. Confirm by running pytest and observing assertion failures (direction=0 or signal_type="none" instead of expected values).
  </behavior>
  <action>
    Append the 9 new test methods to the existing TestCandlestickPatternSetup class in tests/unit/intelligence/test_trading_setups.py (or create a new TestCandlestickTier1Patterns class in the same file).

    Pattern for each test (use nearest_support for S/R confirmation since volume can be tricky to set up):
    ```python
    def test_three_white_soldiers_bullish(self):
        import pandas as pd
        from src.intelligence.trading.candlestick_pattern_setup import CandlestickPatternSetupPlugin
        n = 25
        close = [5000.0] * n
        df = pd.DataFrame({
            "open": [4995.0] * n, "high": [5010.0] * n,
            "low": [4990.0] * n, "close": close, "volume": [1200.0] * n,
        })
        features = {
            "three_white_soldiers": 1.0,
            "trend_regime": 0.7,
            "atr_14": 10.0,
            "nearest_support": 4997.0,  # within 0.3*ATR=3 of close=5000 → S/R confirms
            "volume_sma_20": 1000.0,    # vol 1200 > 1.3*1000=1300? No → use nearest_support path
        }
        result = CandlestickPatternSetupPlugin().compute_full({"main": df, "features": features})
        assert result.get("direction") == 1
        assert "three_white_soldiers" in result.get("signal_type", "")
    ```

    Run pytest after writing tests to confirm RED state.
  </action>
  <verify>
    <automated>.venv/bin/pytest tests/unit/intelligence/test_trading_setups.py -k "three_white_soldiers or three_black_crows or morning_star or evening_star or three_inside or harami_cross or dark_cloud or piercing_line" -v 2>&1 | grep -E "(FAILED|PASSED|ERROR)" | head -20</automated>
  </verify>
  <done>All 9 new tests exist in test_trading_setups.py and FAIL (direction=0 or signal_type="none" returned — patterns not yet read by I7 plugin). Existing tests still pass.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Implement 9 new pattern reads in CandlestickPatternSetupPlugin (GREEN)</name>
  <files>src/intelligence/trading/candlestick_pattern_setup.py</files>
  <behavior>
    After adding reads + candidates, the 9 RED tests from Task 1 must turn GREEN.
    No existing test should regress.
  </behavior>
  <action>
    In src/intelligence/trading/candlestick_pattern_setup.py, make two additions to compute_full():

    ADDITION 1 — Named reads block (after line 77, after existing 6 reads):
    ```python
    # New Tier 1 patterns (bootstrap-promoted via 15-GAP-02)
    three_white_soldiers = float(features.get("three_white_soldiers", 0.0))
    three_black_crows = float(features.get("three_black_crows", 0.0))
    morning_star = float(features.get("morning_star", 0.0))
    evening_star = float(features.get("evening_star", 0.0))
    three_inside_up = float(features.get("three_inside_up", 0.0))
    three_inside_down = float(features.get("three_inside_down", 0.0))
    harami_cross = float(features.get("harami_cross", 0.0))
    dark_cloud_cover = float(features.get("dark_cloud_cover", 0.0))
    piercing_line = float(features.get("piercing_line", 0.0))
    ```

    ADDITION 2 — Candidates block (after existing 6 candidates, before `if not candidates:`):
    ```python
    if three_white_soldiers > 0.0:
        candidates.append((1, 1, "three_white_soldiers", 0.75, False))
    if three_black_crows > 0.0:
        candidates.append((1, -1, "three_black_crows", 0.75, False))
    if morning_star > 0.0:
        candidates.append((2, 1, "morning_star", 0.80, False))
    if evening_star > 0.0:
        candidates.append((2, -1, "evening_star", 0.80, False))
    if three_inside_up > 0.0:
        candidates.append((3, 1, "three_inside_up", 0.65, False))
    if three_inside_down > 0.0:
        candidates.append((3, -1, "three_inside_down", 0.65, False))
    if harami_cross > 0.0:
        # harami_cross has no intrinsic direction — align with trend
        trend_dir_local = 1 if float(features.get("trend_regime", 0.0)) > 0 else -1
        candidates.append((4, trend_dir_local, "harami_cross", 0.60, False))
    if dark_cloud_cover > 0.0:
        candidates.append((3, -1, "dark_cloud_cover", 0.70, False))
    if piercing_line > 0.0:
        candidates.append((3, 1, "piercing_line", 0.70, False))
    ```

    IMPORTANT — harami_cross direction: trend_dir is computed later in the function (line ~104).
    To avoid forward-reference, compute `trend_dir_local` inline inside the harami_cross block
    using `float(features.get("trend_regime", 0.0))` directly. This is slightly redundant but safe
    and avoids restructuring the function flow.

    Also update the docstring Priority order comment to include the new patterns:
    ```
        1: engulfing_bull, engulfing_bear, three_white_soldiers, three_black_crows
        2: pin_bar_bull, pin_bar_bear, morning_star, evening_star
        3: three_inside_up/down, dark_cloud_cover, piercing_line
        4: harami_cross  (direction follows trend)
    ```
  </action>
  <verify>
    <automated>.venv/bin/pytest tests/unit/intelligence/test_trading_setups.py -v -x 2>&1 | tail -15</automated>
  </verify>
  <done>
    All 9 new pattern tests pass (GREEN). All previously passing tests in test_trading_setups.py continue to pass. No regressions.
  </done>
</task>

<task type="auto">
  <name>Task 3: Bootstrap audit trails for all 9 candlestick patterns and full suite verification</name>
  <files>docs/validation/</files>
  <action>
    GAP-01 already adds --bootstrap flag to validate_alpha.py. This task depends on GAP-01 being executed first IF running sequentially. However, since both plans are Wave 1 (parallel), run these bootstrap commands only after GAP-01 has been applied (or implement inline if running standalone).

    If --bootstrap flag is not yet available (GAP-01 not yet applied), skip to full suite verification and note that bootstrap runs must happen after GAP-01 execution. Otherwise:

    Run bootstrap audit trail for all 9 candlestick patterns:
    ```bash
    .venv/bin/python production/scripts/validate_alpha.py --plugin patt_CandlestickPatterns --field three_white_soldiers --days 90 --bootstrap
    .venv/bin/python production/scripts/validate_alpha.py --plugin patt_CandlestickPatterns --field three_black_crows --days 90 --bootstrap
    .venv/bin/python production/scripts/validate_alpha.py --plugin patt_CandlestickPatterns --field morning_star --days 90 --bootstrap
    .venv/bin/python production/scripts/validate_alpha.py --plugin patt_CandlestickPatterns --field evening_star --days 90 --bootstrap
    .venv/bin/python production/scripts/validate_alpha.py --plugin patt_CandlestickPatterns --field three_inside_up --days 90 --bootstrap
    .venv/bin/python production/scripts/validate_alpha.py --plugin patt_CandlestickPatterns --field three_inside_down --days 90 --bootstrap
    .venv/bin/python production/scripts/validate_alpha.py --plugin patt_CandlestickPatterns --field harami_cross --days 90 --bootstrap
    .venv/bin/python production/scripts/validate_alpha.py --plugin patt_CandlestickPatterns --field dark_cloud_cover --days 90 --bootstrap
    .venv/bin/python production/scripts/validate_alpha.py --plugin patt_CandlestickPatterns --field piercing_line --days 90 --bootstrap
    ```

    Each exits 0 and writes a bootstrap JSON to docs/validation/.

    Then run the full unit suite:
    ```bash
    .venv/bin/pytest tests/unit/ -x -q
    ```

    Then ruff check on modified files:
    ```bash
    .venv/bin/ruff check src/intelligence/trading/candlestick_pattern_setup.py
    ```
  </action>
  <verify>
    <automated>.venv/bin/pytest tests/unit/ -q 2>&1 | tail -5</automated>
  </verify>
  <done>
    - Full unit suite passes with no regressions (expected: 1295+ tests passing — 1286 baseline + 9 new candlestick tests)
    - Nine bootstrap JSON files in docs/validation/ with patt_CandlestickPatterns and respective field names
    - Ruff check exits with 0 new errors on candlestick_pattern_setup.py
  </done>
</task>

</tasks>

<verification>
# Confirm all 9 new patterns read by I7:
grep -n "three_white_soldiers\|morning_star\|harami_cross\|dark_cloud_cover\|piercing_line" src/intelligence/trading/candlestick_pattern_setup.py | wc -l

# Confirm bootstrap files:
ls docs/validation/*CandlestickPatterns*bootstrap*.json | wc -l

# Full suite:
.venv/bin/pytest tests/unit/ -q 2>&1 | tail -3
</verification>

<success_criteria>
- CandlestickPatternSetupPlugin reads all 9 new Tier 1 pattern fields from features dict
- All 9 new I7 pattern tests pass (GREEN after RED in Task 1)
- All existing candlestick setup tests continue to pass (no regressions)
- Nine bootstrap JSON files in docs/validation/ for the 9 new candlestick patterns
- Full unit suite passes with no regressions
- Ruff: no new errors on modified files
</success_criteria>

<output>
After completion, create `.planning/phases/15-validated-alpha/15-GAP-02-SUMMARY.md`
</output>
