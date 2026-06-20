---
phase: 137-feature-factory
plan: 6
type: execute
wave: 4
depends_on: [3, 4, 5]
files_modified:
  - services/intelligence_pipeline.py
  - src/intelligence/register_plugins.py
  - src/intelligence/archive/README.md
autonomous: true
requirements: [SC-6, SC-7, SC-8, SC-10]

threat_model:
  assets:
    - "Live IntelligencePipeline (the hot path producing real-time feature_vectors)"
    - "I5/I6/I7 plugin code (years of domain knowledge - archived, not deleted, D-09)"
    - "Pipeline APR prewarm (feature.* keys must load before first compute)"
  threats:
    - id: T1
      description: "FeatureFactory wired but feature.* APR keys not prewarmed at pipeline init - compute runs with wrong/missing periods or crashes on first bar"
      severity: high
      mitigation: "Add all 16 feature.* keys to _THRESHOLD_KEYS and build FeatureFactoryConfig in _prewarm_threshold_config; acceptance criterion asserts the keys are in _THRESHOLD_KEYS and config builds at init"
    - id: T2
      description: "Plugin dispatch left partially wired - pipeline still calls PluginExecutor for some tiers, double-computing or emitting stale signals after cutover (SC-8)"
      severity: high
      mitigation: "Remove all TIER_I1..TIER_I7 dispatch from the compute path, replace with single FeatureFactory.compute() call; acceptance criterion greps for zero PluginExecutor/process_bar/TIER_I dispatch in the pipeline compute path"
    - id: T3
      description: "Archiving I5/I6/I7 breaks imports elsewhere (register_plugins, tests, other services) - collection-time ImportError, system-wide breakage"
      severity: high
      mitigation: "grep -r for archived module imports across src/ services/ tests/ before moving; update or remove references; run full unit suite as the gate (SC-10)"
    - id: T4
      description: "Plugins modified during archival (D-09 requires intact-without-modification archival; Phase 138 prunes/transforms)"
      severity: medium
      mitigation: "git mv only - no edits to plugin files; acceptance criterion: archived files are byte-identical to pre-move (git mv preserves)"
  block_on: [T1, T2, T3]

must_haves:
  truths:
    - "IntelligencePipeline calls FeatureFactory.compute() per bar and publishes FeatureVectorRecord to topic_feature_vectors"
    - "IntelligencePipeline has zero references to PluginRegistry/PluginExecutor process_bar dispatch and zero TIER_I1..TIER_I7 plugin loops in the compute path"
    - "All I5, I6, I7 code lives under src/intelligence/archive/ intact (unmodified)"
    - "feature.* APR keys are prewarmed at pipeline init and FeatureFactoryConfig is built from them"
    - "A live 1m bar produces a feature_vectors row (smoke test)"
    - "Full unit suite is green"
  artifacts:
    - path: "services/intelligence_pipeline.py"
      provides: "Pipeline cutover: FeatureFactory.compute() replaces plugin dispatch; feature.* prewarm; FeatureVectorRecord publish"
      contains: "FeatureFactory"
    - path: "src/intelligence/archive/README.md"
      provides: "Record of archived I5/I6/I7 modules and rationale (D-09)"
      contains: "archive"
  key_links:
    - from: "services/intelligence_pipeline.py _process_bar_compute"
      to: "src/intelligence/feature_factory.py FeatureFactory.compute"
      via: "single compute call replacing plugin dispatch"
      pattern: "FeatureFactory|feature_factory"
    - from: "services/intelligence_pipeline.py"
      to: "src/core/stream_keys.py topic_feature_vectors"
      via: "Kafka publish of FeatureVectorRecord (msg= kwarg)"
      pattern: "topic_feature_vectors"
    - from: "services/intelligence_pipeline.py _prewarm_threshold_config"
      to: "config_state feature.* keys"
      via: "_THRESHOLD_KEYS additions + FeatureFactoryConfig build"
      pattern: "feature\\.momentum\\.window_short"
---

<objective>
Execute the atomic cutover (D-09): wire `FeatureFactory.compute()` into `IntelligencePipeline` (replacing the 138-plugin `PluginExecutor` dispatch with one call), prewarm the `feature.*` APR keys and build `FeatureFactoryConfig` at init, publish `FeatureVectorRecord` to `topic_feature_vectors`, and move all I5/I6/I7 code to `src/intelligence/archive/` intact. Then verify the Phase 137 done-gate: a live 1m bar produces a `feature_vectors` row, zero plugin-dispatch references remain, and the full unit suite is green.

This is Phase 137's final deliverable. There is no shadow period (D-09) - wire-and-cut in one deploy. I7 ran live until this plan; after it, `signal_events` is no longer written by the live pipeline.

GATING PRECONDITION: This plan must not run until P5's backfill is verified within 5% of theoretical max per (symbol, tf) (D-06). The executor must confirm the coverage gate from 137-P5-SUMMARY before cutover.

Purpose: SC-6 (pipeline calls FeatureFactory + writer persists), SC-7 (I5/I6/I7 archived), SC-8 (plugin dispatch removed), SC-10 (unit tests green).
Output: retargeted pipeline, archived plugins, green suite, live smoke-test confirmation.
</objective>

<execution_context>
@~/.claude/get-shit-done/workflows/execute-plan.md
@~/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/137-feature-factory/137-CONTEXT.md
@.planning/phases/137-feature-factory/137-RESEARCH.md
@.planning/phases/137-feature-factory/A-PATTERNS.md
@.planning/phases/137-feature-factory/137-P5-SUMMARY.md
@CLAUDE.md
@docs/plans/2026-06-20-v30-i7-transition.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Prewarm feature.* APR + wire FeatureFactory.compute() into the pipeline; remove plugin dispatch</name>
  <files>services/intelligence_pipeline.py</files>
  <read_first>
    - services/intelligence_pipeline.py (FULL read: __init__ ~122, _prewarm_threshold_config ~540, _THRESHOLD_KEYS ~376, _process_bar_inner ~791, _process_bar_compute ~841, the TIER_I1..TIER_I7 imports ~68-76, PluginExecutor usage ~56, the _run_i1_to_i6 and SignalProcessor.process() dispatch referenced at top docstring lines 5-6)
    - src/intelligence/feature_factory.py (FeatureFactory, FeatureFactoryConfig, FeatureCache from P3 - construction + compute signature)
    - src/intelligence/feature_cache.py (FeatureCache lifecycle: per (symbol,tf), refresh_regime cadence, update_cross_asset)
    - src/intelligence/schemas.py (FeatureVectorRecord - the publish payload)
    - src/core/stream_keys.py (topic_feature_vectors - publish target)
    - .planning/phases/137-feature-factory/A-PATTERNS.md ("APR Prewarm Registration" + "Kafka Publish Pattern" - msg= kwarg, _THRESHOLD_KEYS additions, set_config_service injection)
    - .planning/phases/137-feature-factory/137-RESEARCH.md (Pattern 4 prewarm registration)
  </read_first>
  <action>
    (1) Add the 16 feature.* keys to _THRESHOLD_KEYS (feature.momentum.window_short=5, window_long=20, zscore_window=252, feature.volume.zscore_window=20, feature.ofi.zscore_window=20, feature.cvd.slope_bars=5, feature.cmf.period=20, feature.vol.short_bars=5, feature.vol.long_bars=20, feature.hma.period=20, feature.adx.period=14, feature.hurst.window=252, feature.garch.window=100, feature.vix.zscore_window=252, feature.yield_curve.zscore_window=252, feature.regime.cache_refresh_bars=30) as additive entries.

    (2) In _prewarm_threshold_config, after keys load, build a FeatureFactoryConfig from the prewarmed values and construct a FeatureFactory instance held on self (self._feature_factory). Maintain a per-(symbol, tf) FeatureCache dict (self._feature_caches) using the _state(key) factory pattern (CLAUDE.md parallel-dict rule).

    (3) Replace the plugin-dispatch compute path in _process_bar_compute / _run_i1_to_i6 / SignalProcessor.process() with a single FeatureFactory.compute(bars, symbol, tf, cache, config) call producing a FeatureVector. Drive the FeatureCache: refresh regime features every regime_cache_refresh_bars; update cross-asset cache from cross-asset bar history; update CTF state on HTF bar arrival. Wrap the FeatureVector in a FeatureVectorRecord (symbol, tf, bar_ts, pipeline_version, regime, regime_label_source='filtered', vector) and publish to topic_feature_vectors via self._kafka_producer.publish(topic, msg=record_dict, key=...) - kwarg is msg= (NOT value=).

    (4) Remove TIER_I1..TIER_I7 / PluginExecutor / register_plugins dispatch from the compute path and their imports. The pipeline no longer fires I7 plugins or writes signal_events. Preserve the BaseDaemon lifecycle, bar subscription (topic_market_bars + topic_market_bars_htf), checkpointing, and output-queue backpressure. The 4-way output routing collapses to the single feature_vectors output.

    Keep all numeric params from APR (SC-9 discipline extends here). Timestamps UTC; format_iso_ts for serialization; structlog non-reserved kwargs.
  </action>
  <verify>
    .venv/bin/python -c "import ast; src=open('services/intelligence_pipeline.py').read(); assert 'FeatureFactory' in src or 'feature_factory' in src; assert 'PluginExecutor' not in src, 'PluginExecutor still referenced'; print('OK')" && .venv/bin/ruff check services/intelligence_pipeline.py
  </verify>
  <acceptance_criteria>
    - `grep -nE "PluginExecutor|PluginRegistry|\.process_bar\(|TIER_I[1-7]" services/intelligence_pipeline.py` returns 0 matches in the compute path
    - `grep -n "feature.momentum.window_short" services/intelligence_pipeline.py` returns >= 1 (key in _THRESHOLD_KEYS)
    - `grep -n "FeatureFactory\|feature_factory" services/intelligence_pipeline.py` returns >= 1
    - `grep -n "topic_feature_vectors" services/intelligence_pipeline.py` returns >= 1
    - `grep -n "msg=" services/intelligence_pipeline.py` shows the publish uses msg= (no `value=` on publish calls)
    - `.venv/bin/ruff check services/intelligence_pipeline.py` exits 0
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 2: Archive I5/I6/I7 intact + update register_plugins + fix broken imports</name>
  <files>src/intelligence/archive/README.md, src/intelligence/register_plugins.py</files>
  <read_first>
    - src/intelligence/register_plugins.py (FULL - all TIER_I5/TIER_I6/TIER_I7/TIER_SMC import lines and tier list definitions to remove/relocate)
    - docs/plans/2026-06-20-v30-i7-transition.md (archival approach: all I5-I7 archived intact, Phase 138 transforms - do NOT delete or edit)
    - .planning/phases/137-feature-factory/137-CONTEXT.md (D-09 archive scope: I5, I6, I7 moved to src/intelligence/archive/ intact without modification)
    - CLAUDE.md (file/class rename test sweep rule: grep tests/ for moved imports)
  </read_first>
  <action>
    First, enumerate the I5/I6/I7 module set: src/intelligence/features/i5_patterns/, src/intelligence/features/smc_context/ (I6 SMC), src/intelligence/confluence/ (I6 confluence), and the I7 trading-signal plugin modules under src/intelligence/trading/ that are registered in TIER_I7. Cross-check against register_plugins.py TIER_I5/TIER_I6/TIER_I7/TIER_SMC import lists for the authoritative set.

    git mv each I5/I6/I7 module into src/intelligence/archive/ preserving the relative subtree (e.g. archive/i5_patterns/, archive/smc_context/, archive/confluence/, archive/trading_i7/). Use git mv only - NO edits to plugin file contents (D-09 intact-without-modification, T4).

    Update register_plugins.py: remove the TIER_I5/TIER_I6/TIER_I7/TIER_SMC imports and tier lists that referenced the archived modules. Keep TIER_I1..TIER_I4 only if the pipeline still needs them - but per cutover (Task 1) the pipeline no longer dispatches any tier, so register_plugins is no longer imported by the live pipeline. Confirm whether register_plugins is still imported anywhere live; if only by archived code/tests, neutralize the dangling imports.

    Run a repo-wide sweep: `grep -rn "i5_patterns\|smc_context\|intelligence.confluence\|register_plugins" src/ services/ tests/` (excluding archive/). For each live reference to an archived module, either update the import to the archive path (for tests that intentionally test archived behavior) or remove it (for dead references). Tests that imported now-archived plugins must be moved alongside or marked skipped - do not leave collection-time ImportErrors.

    Write src/intelligence/archive/README.md documenting: what was archived (I5/I6/I7 module list), why (D-09 - institutional memory; Phase 138 IC discovery determines which I7 plugins become alpha scorers), and that the code is intact/unmodified.
  </action>
  <verify>
    .venv/bin/python -c "import services.intelligence_pipeline; print('pipeline imports clean')" && ls src/intelligence/archive/ && .venv/bin/pytest tests/unit/ -q --collect-only 2>&1 | tail -5
  </verify>
  <acceptance_criteria>
    - `src/intelligence/archive/` contains the I5 (i5_patterns), I6 (smc_context, confluence), and I7 (trading signal) modules
    - `src/intelligence/archive/README.md` exists and lists the archived tiers
    - `grep -rn "i5_patterns\|smc_context\|intelligence\.confluence" src/ services/ tests/ --include=*.py | grep -v "/archive/"` returns 0 live references (all references are inside archive/ or removed)
    - `.venv/bin/pytest tests/unit/ --collect-only -q` exits 0 (no collection-time ImportError)
    - `git status` shows the moves as renames (git mv preserved file content; no content diff on moved files)
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 3: Done-gate - backfill coverage check, live bar smoke test, full unit suite green</name>
  <files>services/intelligence_pipeline.py</files>
  <read_first>
    - .planning/phases/137-feature-factory/137-P5-SUMMARY.md (backfill coverage results - confirm within-5% gate per symbol/tf, D-06)
    - .planning/phases/137-feature-factory/137-CONTEXT.md (`<specifics>` "Phase 137 cutover done gate" - the 5 conditions)
    - services/intelligence_pipeline.py (the cutover from Task 1 - the live path under test)
  </read_first>
  <action>
    Execute the Phase 137 done-gate verification (no code changes expected unless a gate fails):

    (1) Backfill coverage gate (D-06): query backfill_status for per-(symbol, tf) rows_written vs theoretical_max; confirm pairs are within 5% of theoretical max (>= 95%), or are explicitly flagged < 80% and recorded as excluded from Phase 138. Use the verification query from 137-RESEARCH.md.

    (2) Live bar smoke test: restart the intelligence-pipeline service (systemctl per service DAG), let one live 1m bar flow through, and confirm a feature_vectors row appears for that bar: `SELECT count(*) FROM feature_vectors WHERE bar_ts > now() - interval '10 minutes'` returns >= 1. Confirm regime_label_source='filtered' and pipeline_version is set on the new row.

    (3) Zero plugin-dispatch confirmation: re-assert grep gates from Task 1.

    (4) Full unit suite: `.venv/bin/pytest tests/unit/ -q` green (SC-10).

    If any gate fails, fix the minimal cause (e.g. a prewarm key missing, a publish kwarg wrong) and re-run. Do not expand scope.
  </action>
  <verify>
    .venv/bin/pytest tests/unit/ -q && PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "SELECT count(*) FROM feature_vectors WHERE bar_ts > now() - interval '10 minutes';"
  </verify>
  <acceptance_criteria>
    - `.venv/bin/pytest tests/unit/ -q` exits 0 (SC-10)
    - `SELECT count(*) FROM feature_vectors WHERE bar_ts > now() - interval '10 minutes'` returns >= 1 after a live bar (smoke test)
    - The newest feature_vectors row has regime_label_source='filtered' and a non-null pipeline_version
    - backfill_status shows all completed pairs >= 95% coverage, or any < 80% pair is recorded as excluded in 137-P6-SUMMARY (D-06)
    - `grep -nE "PluginExecutor|\.process_bar\(|TIER_I[1-7]" services/intelligence_pipeline.py` returns 0 matches
  </acceptance_criteria>
</task>

</tasks>

<verification>
- IntelligencePipeline calls FeatureFactory.compute() per bar; publishes FeatureVectorRecord to topic_feature_vectors
- feature.* APR prewarmed; FeatureFactoryConfig built at init
- Zero PluginExecutor / process_bar / TIER_I dispatch in pipeline (SC-8)
- All I5/I6/I7 under src/intelligence/archive/ intact; no live imports of archived modules (SC-7)
- Live 1m bar produces a feature_vectors row with regime_label_source='filtered' (SC-6 smoke test)
- Backfill coverage within 5% of theoretical max (D-06 gate confirmed before cutover)
- Full unit suite green (SC-10)
</verification>

<success_criteria>
SC-6 (pipeline calls FeatureFactory; writer persists to feature_vectors) satisfied end-to-end via live smoke test.
SC-7 (I5/I6/I7 archived) satisfied: archive/ holds all three tiers intact; zero live references.
SC-8 (plugin registry dispatch removed) satisfied: zero dispatch references in IntelligencePipeline.
SC-10 (unit tests green) satisfied: full tests/unit/ suite passes.
</success_criteria>

<output>
After completion, create `.planning/phases/137-feature-factory/137-P6-SUMMARY.md`. Record the smoke-test result, final backfill coverage table, archived module list, and confirmation that all 5 cutover done-gate conditions are met.
</output>
