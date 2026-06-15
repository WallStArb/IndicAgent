---
phase: 125-apr-full-migration-all-three-tiers
plan: "05"
type: execute
wave: 4
depends_on:
  - "01"
  - "04"
files_modified:
  - src/intelligence/trading/cis_scorer.py
  - services/intelligence_pipeline.py
  - .planning/todos/pending/025-parameter-store-full-plugin-migration.md
  - .planning/todos/done/025-parameter-store-full-plugin-migration.md
autonomous: true
requirements:
  - APR-01
  - APR-02
  - APR-03

must_haves:
  truths:
    - "CISScorer.score() reads CIS_FIRE_THRESHOLD, BUCKET_AGREE_MIN, BUCKET_NOISE_FLOOR from APR via module-level _config_service singleton"
    - "intelligence_pipeline._THRESHOLD_KEYS contains all 10 migration 132 keys with correct defaults"
    - "cis_scorer.set_config_service() is called in _prewarm_threshold_config() alongside confidence_utils, zone_engine, aggregator"
    - "TODO 025 is moved from pending to done"
    - "pytest tests/unit/ -q introduces no new failures vs baseline 42"
    - "config_state contains >= 51 rows matching threshold.*, weights.*, or feature.zone_engine.* keys (zero hard-coded constants remain in src/)"
  artifacts:
    - path: "src/intelligence/trading/cis_scorer.py"
      provides: "Module-level _config_service singleton + set_config_service() + APR reads in score()"
      contains: "set_config_service"
    - path: "services/intelligence_pipeline.py"
      provides: "_THRESHOLD_KEYS extension + cis_scorer injection in _prewarm_threshold_config"
      contains: "threshold.cis.fire_threshold"
    - path: ".planning/todos/done/025-parameter-store-full-plugin-migration.md"
      provides: "Closed TODO"
  key_links:
    - from: "services/intelligence_pipeline.py _prewarm_threshold_config()"
      to: "src/intelligence/trading/cis_scorer.py set_config_service()"
      via: "module import + call"
      pattern: "cis_scorer.set_config_service"
    - from: "src/intelligence/trading/cis_scorer.py CISScorer.score()"
      to: "_config_service.get_sync()"
      via: "module-level _config_service singleton"
      pattern: "_config_service.get_sync.*threshold\\.cis"
---

<objective>
Wire CIS gate constants to APR in cis_scorer.py and extend intelligence_pipeline to inject config and prewarm all 10 new keys. Close TODO 025.

Purpose: This is the final integration step. CISScorer.score() currently uses the 3 gate constants as module-level literals. This plan adds the module-level config singleton (same pattern as confidence_utils.py), wires it into score(), and extends the pipeline prewarm to cover migration 132 keys. TODO 025 closes when this plan ships.
Output: cis_scorer.py with set_config_service() + APR reads. intelligence_pipeline.py with 10 new _THRESHOLD_KEYS entries. TODO 025 moved to done.
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
@.planning/phases/125-apr-full-migration-all-three-tiers/125-D-SUMMARY.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Add module-level config singleton and APR reads to cis_scorer.py</name>
  <read_first>
    - src/intelligence/trading/cis_scorer.py (full file — understand module-level constants block, CISScorer.score() method to find lines using CIS_FIRE_THRESHOLD, BUCKET_AGREE_MIN, BUCKET_NOISE_FLOOR)
    - src/intelligence/trading/confidence_utils.py (lines 40-46 — reference for the exact module-level singleton pattern to replicate)
  </read_first>
  <files>src/intelligence/trading/cis_scorer.py</files>
  <action>
    Add module-level config singleton immediately before the BUCKET_NAMES tuple definition (after the existing module-level constants block):

      _config_service: Any | None = None


      def set_config_service(config: Any) -> None:
          """Inject ConfigService for APR-backed CIS gate constants.

          Called by intelligence_pipeline._prewarm_threshold_config() at startup.
          Same pattern as confidence_utils.set_config_service().
          """
          global _config_service
          _config_service = config

    Ensure "from typing import Any" is already imported (it is via the dataclass field — verify; add if not present).

    In CISScorer.score(), locate the two places the constants are used:
      Line ~244: if abs(cis_score) > CIS_FIRE_THRESHOLD:
      Line ~253: bucket_array = scores_array * cis_sign; agreeing = int(np.sum(bucket_array > BUCKET_NOISE_FLOOR))
      Line ~256: if agreeing < BUCKET_AGREE_MIN:

    Immediately before "direction = 0" (just before those checks), add runtime reads:

      fire_threshold = (
          _config_service.get_sync("threshold.cis.fire_threshold", CIS_FIRE_THRESHOLD)
          if _config_service is not None
          else CIS_FIRE_THRESHOLD
      )
      bucket_agree_min = (
          int(_config_service.get_sync("threshold.cis.bucket_agree_min", BUCKET_AGREE_MIN))
          if _config_service is not None
          else BUCKET_AGREE_MIN
      )
      bucket_noise_floor = (
          _config_service.get_sync("threshold.cis.bucket_noise_floor", BUCKET_NOISE_FLOOR)
          if _config_service is not None
          else BUCKET_NOISE_FLOOR
      )

    Then replace the three constant usages:
      CIS_FIRE_THRESHOLD -> fire_threshold
      BUCKET_AGREE_MIN -> bucket_agree_min
      BUCKET_NOISE_FLOOR -> bucket_noise_floor

    Keep the module-level constants CIS_FIRE_THRESHOLD, BUCKET_AGREE_MIN, BUCKET_NOISE_FLOOR as-is — they are the hardcoded fallbacks and public API for tests. Do not delete them.
  </action>
  <verify>
    .venv/bin/python -c "from src.intelligence.trading.cis_scorer import CISScorer, set_config_service; print('import ok')"
    Expected: import ok

    grep -n "def set_config_service" src/intelligence/trading/cis_scorer.py
    Expected: 1 result

    grep -n "threshold.cis.fire_threshold" src/intelligence/trading/cis_scorer.py
    Expected: 1 result (the get_sync call)

    grep -n "threshold.cis.bucket_agree_min" src/intelligence/trading/cis_scorer.py
    Expected: 1 result

    grep -n "threshold.cis.bucket_noise_floor" src/intelligence/trading/cis_scorer.py
    Expected: 1 result

    .venv/bin/pytest tests/unit/intelligence/ -q -k "cis" --no-header 2>&1 | tail -10
    Expected: no new failures
  </verify>
  <done>set_config_service() exists in cis_scorer.py at module level. score() reads all 3 gate constants via _config_service.get_sync() with fallbacks to the original constants. Module-level CIS_FIRE_THRESHOLD/BUCKET_AGREE_MIN/BUCKET_NOISE_FLOOR constants are preserved.</done>
</task>

<task type="auto">
  <name>Task 2: Extend intelligence_pipeline _THRESHOLD_KEYS and _prewarm_threshold_config</name>
  <read_first>
    - services/intelligence_pipeline.py (lines 376-475 — read the full _THRESHOLD_KEYS tuple and _prewarm_threshold_config method to understand where to extend each)
  </read_first>
  <files>services/intelligence_pipeline.py</files>
  <action>
    In _THRESHOLD_KEYS tuple, add a new section after the last existing Tier C zone_engine entry (after the "weights.zone_engine.proximity" line):

      # --- migration 132: Phase 125 CIS gate constants ---
      ("threshold.cis.fire_threshold", 0.35),
      ("threshold.cis.bucket_agree_min", 3),
      ("threshold.cis.bucket_noise_floor", 0.1),
      # --- migration 132: Phase 125 zone entry width gate (consumed by Phase 126) ---
      ("feature.zone_engine.min_zone_width_atr", 1.5),
      ("feature.zone_engine.min_zone_width_atr.equity_etf", 1.5),
      ("feature.zone_engine.min_zone_width_atr.forex", 1.0),
      ("feature.zone_engine.min_zone_width_atr.futures", 1.5),
      # --- migration 132: Phase 125 anchored_vwap_reversion Tier B weights ---
      ("weights.vwap_reversion.sigma_magnitude", 0.40),
      ("weights.vwap_reversion.hurst_quality", 0.35),
      ("weights.vwap_reversion.vol_stability", 0.25),

    In _prewarm_threshold_config(), in the imports block that already has confidence_utils, volume_profile_utils, zone_engine, aggregator, add cis_scorer:

      from src.intelligence.trading import (  # noqa: PLC0415
          aggregator,
          cis_scorer,
          confidence_utils,
          volume_profile_utils,
          zone_engine,
      )

    After the aggregator.set_config_service call, add:
      cis_scorer.set_config_service(self._config_service)

    Do NOT change any other logic.
  </action>
  <verify>
    grep -n "threshold.cis.fire_threshold" services/intelligence_pipeline.py
    Expected: 1 result (in _THRESHOLD_KEYS)

    grep -n "feature.zone_engine.min_zone_width_atr" services/intelligence_pipeline.py
    Expected: 4 results (4 zone keys)

    grep -n "weights.vwap_reversion" services/intelligence_pipeline.py
    Expected: 3 results

    grep -n "cis_scorer.set_config_service" services/intelligence_pipeline.py
    Expected: 1 result (in _prewarm_threshold_config)

    .venv/bin/python -c "from services.intelligence_pipeline import IntelligencePipelineComputeAgent; print(len(IntelligencePipelineComputeAgent._THRESHOLD_KEYS))"
    Expected: previous count + 10 (was 42 entries before Phase 125, now 52)
  </verify>
  <done>_THRESHOLD_KEYS contains 10 new entries from migration 132. _prewarm_threshold_config imports cis_scorer and calls cis_scorer.set_config_service(self._config_service) after the other set_config_service calls.</done>
</task>

<task type="auto">
  <name>Task 3: Close TODO 025, run full unit suite, verify zero hard-coded constants</name>
  <read_first>
    - .planning/todos/pending/025-parameter-store-full-plugin-migration.md (read content to carry it to done with a completion note)
  </read_first>
  <files>
    .planning/todos/done/025-parameter-store-full-plugin-migration.md
  </files>
  <action>
    Move TODO 025 from pending to done by creating the done file with the original content plus a completion banner at the top:

      # DONE: Parameter Store Full Plugin Migration
      Completed: 2026-06-14 via Phase 125 (125-apr-full-migration-all-three-tiers)
      Plans: 125-PLAN-A through 125-PLAN-E

      ## What was delivered
      - Migration 132: 10 new APR keys (3 CIS gate, 4 zone_engine min_zone_width_atr, 3 vwap_reversion weights)
      - _validate_weights_sum() added to confidence_utils.py; called in all 6 applicable Tier B plugins
      - anchored_vwap_reversion weight reads wired to ConfigService
      - cis_scorer CIS gate constants wired to APR via module-level singleton
      - BOOTSTRAP_WEIGHTS renamed to _CONFIG_UNAVAILABLE_FALLBACK
      - intelligence_pipeline._THRESHOLD_KEYS extended with all 10 migration 132 keys
      - intelligence_pipeline._prewarm_threshold_config injects cis_scorer.set_config_service

      ## Deferred items (captured in separate todos)
      - trade_framer.py constants: requires counterfactual_pnl_r data (Phase 127+)
      - confidence_utils.py rename to confidence.py: 39 import sites (see todo 2026-06-14-rename-confidence-utils.md)
      - zone_engine._cfg() rename to _read_config(): see todo 2026-06-14-rename-cfg-in-zone-engine.md

      ---
      [original content below]

    Then append the original content of the pending file below the completion banner.

    Delete the pending file: rm .planning/todos/pending/025-parameter-store-full-plugin-migration.md
    (Use Bash to delete it; Write tool can only create/overwrite, not delete)

    Then run the full unit suite:
    .venv/bin/pytest tests/unit/ -q --no-header 2>&1 | tail -20
    Record the failure count. It must not exceed 42 (the pre-Phase-125 baseline).
  </action>
  <verify>
    ls .planning/todos/done/025-parameter-store-full-plugin-migration.md
    Expected: file exists

    ls .planning/todos/pending/025-parameter-store-full-plugin-migration.md 2>&1
    Expected: No such file or directory

    .venv/bin/pytest tests/unit/ -q --no-header 2>&1 | grep -E "^[0-9]+ passed"
    Expected: count >= previous passing tests (no regressions)

    .venv/bin/pytest tests/unit/ -q --no-header 2>&1 | grep -E "failed" | head -5
    Expected: 42 or fewer failures (no new failures vs baseline)

    # Verify >= 51 APR keys exist in config_state (ROADMAP success criterion #2)
    PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT COUNT(*) FROM config_state WHERE config_key LIKE 'threshold.%' OR config_key LIKE 'weights.%' OR config_key LIKE 'feature.zone_engine.%';"
    Expected: >= 51

    # Verify zero hard-coded constants remain for the 6 migrated literals
    grep -rn "CIS_FIRE_THRESHOLD\|BUCKET_AGREE_MIN\|BUCKET_NOISE_FLOOR" src/intelligence/trading/ | grep -v "cis_scorer.py" | grep -v ".pyc"
    Expected: 0 results (constants only referenced inside cis_scorer.py itself as fallbacks)

    grep -n "0\.40 \* sigma_magnitude" src/intelligence/trading/anchored_vwap_reversion.py
    Expected: 0 results (hardcoded composite removed in Plan B)
  </verify>
  <done>TODO 025 file exists in .planning/todos/done/ with a completion banner. The pending file no longer exists. pytest tests/unit/ -q shows no new failures beyond the 42 baseline. config_state has >= 51 rows matching the APR key prefixes. CIS_FIRE_THRESHOLD/BUCKET_AGREE_MIN/BUCKET_NOISE_FLOOR appear only inside cis_scorer.py (as fallback constants). The literal "0.40 * sigma_magnitude" is gone from anchored_vwap_reversion.py.</done>
</task>

</tasks>

<verification>
Full checklist:

1. grep "threshold.cis.fire_threshold" src/intelligence/trading/cis_scorer.py services/intelligence_pipeline.py
   Expected: 1 hit in each file

2. grep -rl "_validate_weights_sum" src/intelligence/trading/ | sort
   Expected: 6 files (anchored_vwap_reversion, gap_analysis_setup, mean_reversion, momentum_breakout, squeeze_expansion, vwap_reclaim)

3. grep "_CONFIG_UNAVAILABLE_FALLBACK" src/intelligence/trading/cis_scorer.py
   Expected: definition + usage in __init__

4. grep "cis_scorer.set_config_service" services/intelligence_pipeline.py
   Expected: 1 result

5. .venv/bin/pytest tests/unit/ -q --no-header 2>&1 | tail -3
   Expected: no new failures vs 42 baseline

6. PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT COUNT(*) FROM config_state WHERE config_key LIKE 'threshold.%' OR config_key LIKE 'weights.%' OR config_key LIKE 'feature.zone_engine.%';"
   Expected: >= 51

7. grep -rn "CIS_FIRE_THRESHOLD\|BUCKET_AGREE_MIN\|BUCKET_NOISE_FLOOR" src/intelligence/trading/ | grep -v "cis_scorer.py" | grep -v ".pyc"
   Expected: 0 results
</verification>

<success_criteria>
CIS gate constants read from APR at runtime in CISScorer.score(). All 10 migration 132 keys in _THRESHOLD_KEYS. cis_scorer injected in prewarm. TODO 025 closed. pytest tests/unit/ passes without new failures. config_state >= 51 APR keys. No migrated literals remain outside their fallback definitions in src/intelligence/trading/.
</success_criteria>

<output>
After completion, create .planning/phases/125-apr-full-migration-all-three-tiers/125-E-SUMMARY.md
</output>
