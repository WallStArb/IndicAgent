---
status: pending
priority: P2
filed: 2026-08-01
source: /simplify-adjacent "clean up docs tests scripts dead code" pass -- three parallel
  survey agents (docs staleness, dead code/scripts, test health) dispatched to scope a
  broader cleanup after the todo-201/220-adjacent doc staleness work. This is the biggest
  single finding from that pass, deliberately NOT executed without explicit user sign-off
  given its size (deleting ~150 files / 30k+ lines is a real decision, not a mechanical
  cleanup).
---

# `src/intelligence/` I1-I7 orchestration/plugin tree has no live production entry point -- ~153 files, ~30,000+ lines, needs an explicit delete-or-archive decision

## What

`services/intelligence_pipeline.py` -- the `ExecStart` target of the archived
`indicagent-intelligence-pipeline.service` -- is confirmed physically deleted from the tree
(matches CLAUDE.md's note about commit `cb8f581a`). Every file this deleted entry point
would have imported is unreachable from the live v3.0 path: `services/feature_vector_pipeline.py`
imports only `CacheManager`, `OutputQueue`, `PerKeyWorkerManager`, `PluginStateManager` from
`src/intelligence/pipeline/` -- nothing else from the tree below.

Dead subtree, by directory (all outside `src/intelligence/archive/`, which is intentionally
kept as historical reference and NOT included in this count):

| Path | Files | ~Lines | Live import path? |
|---|---|---|---|
| `src/intelligence/pipeline/{executor,feature_pipeline_executor,calibrator,quality_gate,ranker,regime_gate,signal_processor,tod_adjuster,winner_selector}.py` | 9 | 3,564 | None from `services/` -- only each other + tests |
| `src/intelligence/register_plugins.py` | 1 | 708 | Only `services/shadow_validator.py` (see caveat) |
| `src/intelligence/trading/*` minus 6 live files (`lifecycle_tracker.py`, `lifecycle_transitions.py`, `signal_outcome.py`, `signal_schema.py`, `structural_confluence.py`, `trade_framer.py` -- these ARE imported by live `signal_tracker`/`signal_writer`/`lifecycle_writer`/`alpha_frame_writer`/`signal_replay_auditor`) | 49 of 55 | ~14,000 for the dir | None -- the ~49 I7 plugin files have zero import sites outside `register_plugins.py` and their own tests |
| `src/intelligence/composites/` | 13 | -- | None found |
| `src/intelligence/confluence/` | 10 | -- | Only `tools/backtest_i6_plugin.py` / `tools/backtest_cross_tf_plugins.py` (themselves likely dead one-off tools, not verified in this pass) |
| `src/intelligence/plugins/` (base `PatternPlugin` class) | 3 | -- | Only the tree below |
| `src/intelligence/features/i1_indicators/` | 27 | 3,743 | Only `register_plugins.py` |
| `src/intelligence/features/i3_structure/` | 9 | 1,597 | Only `register_plugins.py` |
| `src/intelligence/features/smc_context/` | 15 | 2,484 | Only the dead `pipeline/executor.py` |

**Already deleted 2026-08-01** (no caveat, clean orphaned duplicate): `src/intelligence/features/i5_patterns/`
(17 files) -- `register_plugins.py` imports the `archive/i5_patterns` copy instead, so this
copy was unreachable from anywhere, with zero coupling to `shadow_validator.py` or anything
else. Not part of the remaining decision below.

## Update 2026-08-01: Group B's fate is resolved -- v2.x path will be revived, not deleted

User direction (2026-08-01, same session as todo 220's doc resync): the project intends to
eventually run the v2.x signal path again as a second, more conventional intelligence path
alongside v3.0's Renaissance-style AlphaEngine -- two intelligence paths, not a
migrate-and-retire. This resolves Group B's stated ambiguity below ("depends on whether/when
the paused IBKR ingestion chain resumes... needs the ingestion-resume plan settled first, or an
explicit 'we're not resuming the v2.x signal path' call") in the direction of **keep, don't
fold into #1's delete decision**. Group B (26+ SLA/I7 plugin test files) stays as-is pending the
actual revival work; do not delete or archive it as part of executing this todo's #1 decision.

This does NOT resolve the `shadow_validator.py` / `register_plugins.py` coupling in the section
below -- `shadow_registry` itself is still confirmed dead data (36 rows, `last_eval_at IS NULL`)
independent of whether the v2.x path is revived, so that part of the delete-vs-archive call
still applies to the confirmed-dead ~150-file subtree + Group A tests. It also strengthens the
case for **archive over delete** for the dead subtree itself (option 1b): if the revival
resumes the v2.x signal path with I1-I7 intact, some of what's dead today (not just Group B's
test coverage) may become live again, and archived-but-recoverable beats "recreate from git
history" for a path with a stated revival intent, not just a hypothetical one.

## The `shadow_validator.py` coupling (why this isn't a pure zero-reference case)

`register_plugins.py` (and transitively the whole tree) IS imported by one live,
systemd-scheduled service: `services/shadow_validator.py` (weekly timer,
`indicagent-shadow-validator.timer`). So this is not "zero references" in the strictest
grep sense. However, `src/intelligence/CLAUDE.md` itself states: *"shadow_registry's 36 rows
all have last_eval_at IS NULL -- confirmed dead, not just I5-I7."* `shadow_validator` runs
weekly, imports the entire plugin tree to get setup names, queries a table that is never
populated with new evaluable data (because the upstream signal generator is deleted), and
does nothing useful. Functionally dead, technically referenced.

## Test coverage riding on this dead code

A parallel test-health survey (same session) found two tiers of tests exercising this
subtree, with different confidence levels -- **do not auto-purge either without re-reading
this todo's decision below**:

**Group A -- confirmed dead pipeline subtree (18 files), same confidence as the code table
above:** `tests/unit/pipeline/test_signal_processor.py`, `test_executor_state_threading.py`,
`test_plugin_call_result.py`, `test_feature_pipeline_executor.py`,
`test_feature_pipeline_executor_seed.py`, `test_pipeline_recorder_wiring.py`;
`tests/unit/intelligence/pipeline/test_calibrator.py`, `test_quality_gate.py`, `test_ranker.py`,
`test_regime_gate.py`, `test_signal_processor_pipeline.py`, `test_tod_adjuster.py`,
`test_winner_selector.py`; `tests/unit/intelligence/test_regime_gate_soft.py`,
`test_executor_pre_validation.py`, `test_wave_isolation.py`, `test_pipeline_annotation.py`,
`test_metrics_compute.py`.

**Group B -- I7 plugin tier / Signal Ledger Architecture (26+ files), lower confidence --
flagged "currently dormant pending ingestion resume," NOT definitively architecturally dead**:
per MEMORY.md, the live IBKR ingestion chain is *intentionally paused* (2026-07-27), not
architecturally archived, at the *service* layer (`indicagent-signal-writer`,
`indicagent-lifecycle-writer`, `indicagent-signal-tracker-compute` etc. are still registered
in `service_auditor.py`'s `_DAG_ORDER`) -- while the SLA *tables* they'd write to
(`signal_events`/`trade_frames`/`trade_executions`) are separately and explicitly marked
ARCHIVED in root CLAUDE.md. This is a genuine ambiguity requiring a human call, not a survey
artifact: files include `tests/unit/intelligence/test_aggregator*.py`, `test_atr_utils.py`,
`test_cis_scorer.py`, `test_confidence.py`, `test_lifecycle_shadow.py`,
`test_lifecycle_tracker.py`, `test_trade_framer*.py`, `test_signal_schema.py`,
`test_weight_updater.py`, `test_zone_width_gate.py`, `tests/unit/intelligence/trading/*.py`,
plus service-level `tests/unit/services/test_lifecycle_tracker_d02.py`,
`test_signal_replay_auditor.py`, `test_signal_tracker*.py`, `test_signal_writer.py`,
`test_lifecycle_writer.py`.

**Excluded from both groups, confirmed still live**: `src/intelligence/trading/structural_confluence.py`
is imported by the live v3.0 `services/alpha_frame_writer.py` (Phase 142B) --
`tests/unit/test_structural_confluence.py` and `test_alpha_frame_writer_candidate_geometry.py`
test live code, not dead code.

## What needs to happen

This is a decision, not a mechanical fix -- pick one per bullet and execute:

1. **The ~150-file dead subtree + Group A tests (18 files)**: either (a) delete outright
   (git history preserves it, matches this project's "verify then delete, don't flag"
   convention), or (b) formally move to `src/intelligence/archive/` alongside the existing
   archived material, preserving the "kept for historical reference" framing CLAUDE.md
   already uses for that directory. Either way, `shadow_validator.py`'s dependency on
   `register_plugins.py` needs a decision too: gut it to stop importing the plugin tree
   (if the weekly job is worth keeping in some reduced form), or decommission the job
   entirely (matches `shadow_registry`'s already-confirmed-dead data).
2. **Group B (26+ tests, SLA/I7 plugin code)**: explicitly NOT bundled with #1 above --
   depends on whether/when the paused IBKR ingestion chain resumes. If it resumes with the
   v2.x signal path intact, these tests still have a future. If the resume plan routes
   exclusively through v3.0's alpha_events path (per CLAUDE.md's documented Pipeline v3.0
   flow), this code is dead too and should fold into #1's decision. Needs the ingestion-resume
   plan settled first, or an explicit "we're not resuming the v2.x signal path" call.

## Acceptance criteria

- [ ] Decision recorded (delete vs. archive) for the ~150-file dead subtree + shadow_validator.py coupling
- [ ] Decision executed: files removed or moved, shadow_validator.py updated or decommissioned
- [ ] Group A's 18 test files removed or moved alongside their subject code
- [x] Group B explicitly deferred with a stated trigger condition (ingestion resume decision), or resolved if that decision is already made elsewhere -- **resolved 2026-08-01: keep, v2.x signal path has a stated revival intent, not deleted/folded into #1**
