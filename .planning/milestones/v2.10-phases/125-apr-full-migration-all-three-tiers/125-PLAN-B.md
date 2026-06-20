---
phase: 125-apr-full-migration-all-three-tiers
plan: B
type: execute
wave: 2
depends_on:
  - 125-PLAN-A
  - 125-PLAN-C
files_modified:
  - src/intelligence/trading/anchored_vwap_reversion.py
autonomous: true
requirements:
  - APR-02

must_haves:
  truths:
    - "anchored_vwap_reversion reads sigma_magnitude, hurst_quality, vol_stability weights from ConfigService at runtime"
    - "hardcoded line 253 (0.40 * sigma_magnitude + ...) is replaced by config-backed variables"
    - "_validate_weights_sum is called in compute_full after weights are loaded"
  artifacts:
    - path: "src/intelligence/trading/anchored_vwap_reversion.py"
      provides: "APR-wired weight reads + invariant call"
      contains: "weights.vwap_reversion.sigma_magnitude"
  key_links:
    - from: "anchored_vwap_reversion.py compute_full()"
      to: "ConfigService.get_sync()"
      via: "self._config_service"
      pattern: "get_sync.*weights\\.vwap_reversion"
---

<objective>
Wire anchored_vwap_reversion.py weights to ConfigService and add _validate_weights_sum call after weight loading.

Purpose: The only Tier B plugin with un-migrated hardcoded weights (line 253: 0.40/0.35/0.25 literals). After this plan, all 6 applicable Tier B plugins will read weights from APR at runtime. Requires migration 132 keys to exist (depends on Plan A) and _validate_weights_sum to exist in confidence_utils.py (depends on Plan C).
Output: src/intelligence/trading/anchored_vwap_reversion.py with config-backed weights and weight-sum invariant guard.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/phases/125-apr-full-migration-all-three-tiers/125-CONTEXT.md
@.planning/phases/125-apr-full-migration-all-three-tiers/125-RESEARCH.md
@.planning/phases/125-apr-full-migration-all-three-tiers/125-A-SUMMARY.md
@.planning/phases/125-apr-full-migration-all-three-tiers/125-C-SUMMARY.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Wire weight reads and invariant check in anchored_vwap_reversion.py</name>
  <read_first>
    - src/intelligence/trading/anchored_vwap_reversion.py (full file — understand compute_full() structure, _config_service field, current hardcoded line 253)
    - src/intelligence/trading/momentum_breakout.py (reference: how a wired Tier B plugin loads weights via get_sync and the shape of that code block — read lines 80-130)
    - src/intelligence/trading/confidence_utils.py (verify _validate_weights_sum exists — Plan C must have completed before this plan runs)
  </read_first>
  <files>src/intelligence/trading/anchored_vwap_reversion.py</files>
  <action>
    In compute_full(), immediately after the two existing threshold reads (sigma_min from threshold.vwap_reversion.sigma_min and hurst_max from threshold.vwap_reversion.hurst_max), add three weight reads using the identical guard pattern:

      w_sigma = cfg.get_sync("weights.vwap_reversion.sigma_magnitude", 0.40) if cfg else 0.40
      w_hurst = cfg.get_sync("weights.vwap_reversion.hurst_quality", 0.35) if cfg else 0.35
      w_vol_s = cfg.get_sync("weights.vwap_reversion.vol_stability", 0.25) if cfg else 0.25

    Variable cfg is already defined at compute_full() line ~103 as self._config_service.

    After the three weight reads, call _validate_weights_sum with the weights dict and plugin name:
      from src.intelligence.trading.confidence_utils import _validate_weights_sum  # noqa: PLC0415
      _validate_weights_sum(
          {"sigma_magnitude": w_sigma, "hurst_quality": w_hurst, "vol_stability": w_vol_s},
          "trad_AnchoredVWAPReversion",
      )

    Plan C runs before Plan B (Plan B wave: 2, Plan C wave: 1), so _validate_weights_sum is guaranteed to exist. Import directly without any try/except fallback.

    Replace the hardcoded line 253:
      OLD: raw_conf = 0.40 * sigma_magnitude + 0.35 * hurst_quality + 0.25 * vol_stability
      NEW: raw_conf = w_sigma * sigma_magnitude + w_hurst * hurst_quality + w_vol_s * vol_stability

    Do NOT change any other logic, gates, state, or structure in this file.

    Namespace to use: weights.vwap_reversion.* (not weights.anchored_vwap.* — TODO 025 specifies vwap_reversion namespace).
  </action>
  <verify>
    .venv/bin/python -c "from src.intelligence.trading.anchored_vwap_reversion import AnchoredVWAPReversionPlugin; p = AnchoredVWAPReversionPlugin(); print('import ok')"

    grep -n "0\.40 \* sigma_magnitude" src/intelligence/trading/anchored_vwap_reversion.py
    Expected: 0 results (hardcoded line removed)

    grep -n "weights.vwap_reversion.sigma_magnitude" src/intelligence/trading/anchored_vwap_reversion.py
    Expected: 1 result (the get_sync call)

    grep -n "_validate_weights_sum" src/intelligence/trading/anchored_vwap_reversion.py
    Expected: 1 result (the call site)

    grep -n "try.*ImportError\|except ImportError" src/intelligence/trading/anchored_vwap_reversion.py
    Expected: 0 results (no try/except fallback — Plan C guarantees the function exists)

    .venv/bin/pytest tests/unit/intelligence/ -q -k "anchored_vwap" --no-header 2>&1 | tail -10
    Expected: no new failures vs baseline
  </verify>
  <done>The literal "0.40 * sigma_magnitude" does not appear in the file. Three weight reads use ConfigService.get_sync with weights.vwap_reversion.* keys and hardcoded fallbacks. _validate_weights_sum is called with a dict and plugin name "trad_AnchoredVWAPReversion". raw_conf computation uses the config-backed variables. No try/except ImportError guard present.</done>
</task>

</tasks>

<verification>
grep -n "weights.vwap_reversion" src/intelligence/trading/anchored_vwap_reversion.py
Expected: 3 lines (one per weight key)

grep -c "0\.40 \* sigma_magnitude" src/intelligence/trading/anchored_vwap_reversion.py
Expected: 0
</verification>

<success_criteria>
anchored_vwap_reversion.py reads all 3 confidence weights from ConfigService at runtime. The hardcoded composite formula is replaced. _validate_weights_sum is called after weight loading. No test regressions introduced.
</success_criteria>

<output>
After completion, create .planning/phases/125-apr-full-migration-all-three-tiers/125-B-SUMMARY.md
</output>
