---
phase: 125-apr-full-migration-all-three-tiers
plan: "04"
type: execute
wave: 3
depends_on:
  - "03"
  - "02"
files_modified:
  - src/intelligence/trading/gap_analysis_setup.py
  - src/intelligence/trading/mean_reversion.py
  - src/intelligence/trading/momentum_breakout.py
  - src/intelligence/trading/squeeze_expansion.py
  - src/intelligence/trading/vwap_reclaim.py
  - src/intelligence/trading/cis_scorer.py
autonomous: true
requirements:
  - APR-02
  - APR-03

must_haves:
  truths:
    - "_validate_weights_sum is called in all 6 applicable Tier B plugins after weight loading"
    - "liquidity_sweep_reclaim and supply_demand_setup do NOT have _validate_weights_sum calls (base+scale formulas, not weighted sums)"
    - "BOOTSTRAP_WEIGHTS in cis_scorer.py is renamed to _CONFIG_UNAVAILABLE_FALLBACK"
    - "CacheManager._load_cis_weights() -> CISScorer.update_weights() chain is intact and satisfies CONTEXT.md D-01"
    - "No new test failures introduced vs baseline 42"
  artifacts:
    - path: "src/intelligence/trading/gap_analysis_setup.py"
      provides: "_validate_weights_sum call after weight loading"
      contains: "_validate_weights_sum"
    - path: "src/intelligence/trading/mean_reversion.py"
      provides: "_validate_weights_sum call after weight loading"
      contains: "_validate_weights_sum"
    - path: "src/intelligence/trading/momentum_breakout.py"
      provides: "_validate_weights_sum call after weight loading"
      contains: "_validate_weights_sum"
    - path: "src/intelligence/trading/squeeze_expansion.py"
      provides: "_validate_weights_sum call after weight loading"
      contains: "_validate_weights_sum"
    - path: "src/intelligence/trading/vwap_reclaim.py"
      provides: "_validate_weights_sum call after weight loading"
      contains: "_validate_weights_sum"
    - path: "src/intelligence/trading/cis_scorer.py"
      provides: "BOOTSTRAP_WEIGHTS renamed to _CONFIG_UNAVAILABLE_FALLBACK"
      contains: "_CONFIG_UNAVAILABLE_FALLBACK"
  key_links:
    - from: "gap_analysis_setup.py compute_full()"
      to: "confidence_utils._validate_weights_sum"
      via: "import _validate_weights_sum"
    - from: "cis_scorer.py CISScorer.__init__"
      to: "_CONFIG_UNAVAILABLE_FALLBACK"
      via: "self._weights = weights if weights is not None else _CONFIG_UNAVAILABLE_FALLBACK"
---

<objective>
Add _validate_weights_sum calls to the 5 remaining applicable Tier B plugins and rename BOOTSTRAP_WEIGHTS to _CONFIG_UNAVAILABLE_FALLBACK in cis_scorer.py. Verify the existing CacheManager weight-load chain satisfies CONTEXT.md D-01.

Purpose: Completes the weight-sum invariant coverage across all 6 plugins where it semantically applies. The cis_scorer rename clarifies that BOOTSTRAP_WEIGHTS is a cold-start fallback only, not the primary weight source. CONTEXT.md D-01 requires CISScorer to load weights from cis_weights table at startup — this is ALREADY SATISFIED by existing infrastructure: CacheManager._load_cis_weights() queries cis_weights and calls CISScorer.update_weights() at startup and every 30 minutes. Task 3 of this plan verifies that chain is intact so no new DB load infrastructure needs to be added. Depends on Plan B (anchored_vwap_reversion already wired) and Plan C (_validate_weights_sum function exists).
Output: 5 Tier B plugins + cis_scorer.py updated. D-01 compliance confirmed.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/phases/125-apr-full-migration-all-three-tiers/125-CONTEXT.md
@.planning/phases/125-apr-full-migration-all-three-tiers/125-RESEARCH.md
@.planning/phases/125-apr-full-migration-all-three-tiers/125-B-SUMMARY.md
@.planning/phases/125-apr-full-migration-all-three-tiers/125-C-SUMMARY.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add _validate_weights_sum to 5 Tier B plugins</name>
  <read_first>
    - src/intelligence/trading/gap_analysis_setup.py (find where weights are loaded via get_sync; add call immediately after)
    - src/intelligence/trading/mean_reversion.py (same)
    - src/intelligence/trading/momentum_breakout.py (same — this is the reference plugin; understand the weight-loading pattern)
    - src/intelligence/trading/squeeze_expansion.py (same)
    - src/intelligence/trading/vwap_reclaim.py (same)
    - src/intelligence/trading/liquidity_sweep_reclaim.py (READ ONLY — verify it uses base+scale formula and must NOT get _validate_weights_sum)
    - src/intelligence/trading/supply_demand_setup.py (READ ONLY — verify it uses base+scale formula and must NOT get _validate_weights_sum)
  </read_first>
  <files>
    src/intelligence/trading/gap_analysis_setup.py
    src/intelligence/trading/mean_reversion.py
    src/intelligence/trading/momentum_breakout.py
    src/intelligence/trading/squeeze_expansion.py
    src/intelligence/trading/vwap_reclaim.py
  </files>
  <action>
    For each of the 5 applicable plugins, locate where the Tier B weights are loaded from ConfigService inside compute_full() (they use cfg.get_sync("weights.<plugin>.<factor>", default) pattern). Immediately after the last weight read, add:

      from src.intelligence.trading.confidence_utils import _validate_weights_sum  # noqa: PLC0415
      _validate_weights_sum(
          {<weight_name>: <variable>, ...},
          "<PluginName>",
      )

    The weight dict passed must use the same keys as in the config_state (the factor name portion, e.g. "geo", "vol", "timing", "type" for gap_analysis). The plugin name string should be the plugin's .name class attribute value.

    Expected weight dicts per plugin (verify actual variable names from the source before applying):
      gap_analysis_setup: keys "geo", "vol", "timing", "type" (must sum to 1.0: 0.40+0.25+0.20+0.15)
      mean_reversion: keys "rsi_extreme", "div_score", "vol_stability", "sr_proximity" (0.30+0.30+0.20+0.20)
      momentum_breakout: keys "roc", "vol", "break_margin" (0.40+0.35+0.25)
      squeeze_expansion: keys "squeeze_bars", "vol_expansion", "momentum" (0.35+0.35+0.30)
      vwap_reclaim: keys "vol", "duration", "trend_align", "sr_proximity" (0.30+0.30+0.20+0.20)

    CRITICAL: Do NOT add _validate_weights_sum to liquidity_sweep_reclaim.py or supply_demand_setup.py — they use base_conf + scale * ramp() formulas and the parameters do not sum to 1.0.

    Do NOT change any other logic in these files.
  </action>
  <verify>
    For each plugin, verify the call exists:
    grep -l "_validate_weights_sum" src/intelligence/trading/gap_analysis_setup.py src/intelligence/trading/mean_reversion.py src/intelligence/trading/momentum_breakout.py src/intelligence/trading/squeeze_expansion.py src/intelligence/trading/vwap_reclaim.py
    Expected: all 5 files listed

    Verify exempt plugins do NOT have it:
    grep "_validate_weights_sum" src/intelligence/trading/liquidity_sweep_reclaim.py src/intelligence/trading/supply_demand_setup.py
    Expected: no output (0 matches)

    .venv/bin/python -c "from src.intelligence.trading.gap_analysis_setup import GapAnalysisSetupPlugin; print('ok')"
    .venv/bin/python -c "from src.intelligence.trading.mean_reversion import MeanReversionPlugin; print('ok')"
    .venv/bin/python -c "from src.intelligence.trading.momentum_breakout import MomentumBreakoutPlugin; print('ok')"
    .venv/bin/python -c "from src.intelligence.trading.squeeze_expansion import SqueezeExpansionPlugin; print('ok')"
    .venv/bin/python -c "from src.intelligence.trading.vwap_reclaim import VWAPReclaimPlugin; print('ok')"
    Expected: all 5 print 'ok'
  </verify>
  <done>_validate_weights_sum is called in all 5 plugins immediately after weight loading. Neither liquidity_sweep_reclaim nor supply_demand_setup has the call. All 5 plugins import cleanly.</done>
</task>

<task type="auto">
  <name>Task 2: Rename BOOTSTRAP_WEIGHTS to _CONFIG_UNAVAILABLE_FALLBACK in cis_scorer.py</name>
  <read_first>
    - src/intelligence/trading/cis_scorer.py (full file — find all references to BOOTSTRAP_WEIGHTS: the constant definition ~line 47, the CISScorer.__init__ usage ~line 106, and the module docstring)
    - services/intelligence_pipeline.py (grep for BOOTSTRAP_WEIGHTS to check if it's imported externally; if so, must add a deprecated alias)
    - tests/unit/intelligence/ (grep for BOOTSTRAP_WEIGHTS to check if any tests import it)
  </read_first>
  <files>src/intelligence/trading/cis_scorer.py</files>
  <action>
    In cis_scorer.py:

    1. Rename the constant BOOTSTRAP_WEIGHTS to _CONFIG_UNAVAILABLE_FALLBACK (underscore prefix signals it is an implementation detail, not a public API).

    2. Update the CISScorer.__init__ usage:
      OLD: self._weights = weights if weights is not None else BOOTSTRAP_WEIGHTS
      NEW: self._weights = weights if weights is not None else _CONFIG_UNAVAILABLE_FALLBACK

    3. Update the module docstring: replace "BOOTSTRAP_WEIGHTS (version=0)" with "_CONFIG_UNAVAILABLE_FALLBACK (version=0)" in the comment about Phase B.

    4. If any tests or services import BOOTSTRAP_WEIGHTS by name, add a deprecated alias at the end of the constant definition block:
      BOOTSTRAP_WEIGHTS = _CONFIG_UNAVAILABLE_FALLBACK  # deprecated: use _CONFIG_UNAVAILABLE_FALLBACK

    If no external imports of BOOTSTRAP_WEIGHTS exist (grep confirms), do not add the alias — just rename.

    NOTE on D-01: The rename to _CONFIG_UNAVAILABLE_FALLBACK is the only change needed in cis_scorer.py to satisfy CONTEXT.md D-01. The requirement that CISScorer loads weights from the cis_weights table at startup is ALREADY MET by existing infrastructure — CacheManager._load_cis_weights() queries cis_weights and calls CISScorer.update_weights() at startup and every 30 minutes. _CONFIG_UNAVAILABLE_FALLBACK is only used before CacheManager has had a chance to run (the cold-start window). Do NOT add new DB load logic to CISScorer.__init__. Task 3 verifies the existing chain is intact.

    Do NOT change the values, types, or structure of the weights dict.
  </action>
  <verify>
    grep -n "BOOTSTRAP_WEIGHTS" src/intelligence/trading/cis_scorer.py
    Expected: 0 results OR only the deprecated alias line (if external imports exist)

    grep -n "_CONFIG_UNAVAILABLE_FALLBACK" src/intelligence/trading/cis_scorer.py
    Expected: at least 2 results (definition + usage in __init__)

    .venv/bin/python -c "from src.intelligence.trading.cis_scorer import CISScorer; s = CISScorer(); print('init ok')"
    Expected: init ok

    .venv/bin/pytest tests/unit/intelligence/ -q --no-header 2>&1 | tail -5
    Expected: no new failures vs baseline 42
  </verify>
  <done>BOOTSTRAP_WEIGHTS is renamed to _CONFIG_UNAVAILABLE_FALLBACK in cis_scorer.py. CISScorer.__init__ uses the new name. Module docstring updated. All unit tests pass without new failures.</done>
</task>

<task type="auto">
  <name>Task 3: Verify CacheManager._load_cis_weights chain satisfies D-01</name>
  <read_first>
    - src/intelligence/trading/cis_scorer.py (verify update_weights() method exists and accepts dict from DB)
    - services/intelligence_pipeline.py or wherever CacheManager lives (find _load_cis_weights() method — verify it queries cis_weights table and calls CISScorer.update_weights(); note the refresh interval)
  </read_first>
  <files></files>
  <action>
    This is a read-and-verify task. No file changes are expected unless the chain is broken.

    Locate CacheManager._load_cis_weights() (grep for "load_cis_weights" in services/ and src/). Read it to confirm:
    (a) It queries the cis_weights table (or equivalent) for current weights.
    (b) It calls CISScorer.update_weights() or equivalent to push weights into the scorer.
    (c) It runs at startup AND on a periodic schedule (the RESEARCH.md says every 30 minutes).

    If all three conditions hold: no code changes needed. Document findings in the task output.

    If the chain is broken (e.g., _load_cis_weights exists but doesn't call update_weights, or CISScorer.update_weights doesn't exist), fix it in cis_scorer.py or wherever the gap is. This would be unexpected given RESEARCH.md — escalate by noting the discrepancy in the plan summary.
  </action>
  <verify>
    grep -rn "load_cis_weights\|update_weights" services/ src/intelligence/ | grep -v ".pyc"
    Expected: hits for both _load_cis_weights (call site in CacheManager) and update_weights (definition in CISScorer or call from _load_cis_weights)

    grep -n "cis_weights" services/ src/ -r | grep -v ".pyc" | grep -v "test_"
    Expected: at least 1 hit confirming cis_weights table is queried by the load chain

    .venv/bin/python -c "
    from src.intelligence.trading.cis_scorer import CISScorer
    s = CISScorer()
    # Verify update_weights accepts a dict (D-01 contract)
    test_weights = {'w1': 0.5, 'w2': 0.3, 'w3': 0.2}
    s.update_weights(test_weights)
    print('update_weights ok')
    " 2>&1
    Expected: update_weights ok (or a clear AttributeError if update_weights doesn't exist — which would need fixing)
  </verify>
  <done>CacheManager._load_cis_weights() queries cis_weights table and calls CISScorer.update_weights() (or equivalent). The chain runs at startup and on a periodic schedule. D-01 is confirmed satisfied by existing infrastructure — no new DB load code added to CISScorer.__init__.</done>
</task>

</tasks>

<verification>
.venv/bin/pytest tests/unit/intelligence/ -q --no-header 2>&1 | grep -E "^(FAILED|ERROR|passed|failed)"
Baseline: 42 pre-existing failures. Phase 125 must not add new ones.

grep -rl "_validate_weights_sum" src/intelligence/trading/ | sort
Expected: 6 files (gap_analysis_setup, mean_reversion, momentum_breakout, squeeze_expansion, vwap_reclaim, anchored_vwap_reversion)

grep -rn "load_cis_weights\|update_weights" services/ src/intelligence/ | grep -v ".pyc"
Expected: chain confirmed intact (both load and update sides present)
</verification>

<success_criteria>
All 6 applicable Tier B plugins call _validate_weights_sum after weight loading. Neither exempt plugin (liquidity_sweep_reclaim, supply_demand_setup) has the call. BOOTSTRAP_WEIGHTS renamed in cis_scorer.py. CacheManager._load_cis_weights() -> CISScorer.update_weights() chain verified intact (D-01 satisfied by existing infrastructure). No new test failures.
</success_criteria>

<output>
After completion, create .planning/phases/125-apr-full-migration-all-three-tiers/125-D-SUMMARY.md
</output>
