# 327 - Consolidate 9 independently-hardcoded `timeframe` tuples into CVR — split out of todo 326

**Filed:** 2026-08-15
**Source:** Split out of [[326]] after finishing that todo's `asset_class` half (committed
`66ee8b055`). `timeframe`'s scatter deserves its own focused pass rather than a same-session
bolt-on — matching this codebase's own precedent: `services/_batch_utils.py`'s
`_KNOWN_COMPRESSED_HYPERTABLES` comment (todo 308) explicitly declined to wire a live/cached
registry lookup into a hot path "in the same sweep... deserves its own focused pass, not a
bolt-on in the final stretch of an already-large diff," for the same reason `ic_engine.py`'s
write paths were deferred to todo 307. `timeframe` is the same shape, at greater scale (9 call
sites vs. 1 set) and with an added wrinkle `asset_class` didn't have.

## Why this is harder than `asset_class` (326)

`asset_class`'s fix worked cleanly because `src/api/routes/instruments.py` already had a
per-request DB handle (`db_manager` via FastAPI `Depends`) and an established direct-query
pattern to copy from (`src/api/routes/vocabulary.py`). None of that infrastructure exists for
most of `timeframe`'s 9 call sites:

- `src/core/bar_history.py` (`_STANDARD_TFS`) and `src/core/service_utils.py`
  (`CROSS_ASSET_VALID_TFS`) are Ring 0 modules with no DB pool and no async-init hook — there is
  no existing precedent anywhere in the codebase for a sync Ring 0 module reading from
  `VocabularyService` (the one real usage, `src/api/routes/instruments.py`, is async with a
  per-request pool; the only other reference is a comment in `_batch_utils.py` explicitly
  declining to do this for a different registry). The `ConfigService`/`VocabularyService`
  cache-at-init pattern CLAUDE.md documents for module-level utilities
  (`_config_service: Any | None = None` + `set_config_service()` + `get_sync()` wrapper,
  registered in `FeatureVectorPipeline._prewarm_threshold_config()`) is the right shape to copy,
  but needs an equivalent prewarm hook designed for `VocabularyService` specifically — it doesn't
  exist yet.
- `src/intelligence/pipeline/feature_pipeline_executor.py`'s `_STANDARD_TFS` (6 tfs) and
  `src/core/bar_history.py`'s `_STANDARD_TFS` (4 tfs) share a name but disagree — before touching
  either, confirm neither is intentionally a narrower *subset* (which would make this a
  `vocabulary_group` design question, not a plain consolidation) vs. one being simply stale.
- `src/intelligence/utils.py` vs. `src/intelligence/utils/core.py` — confirmed byte-identical for
  their first 147 lines (`utils.py` is 147 lines total, `utils/core.py` is 167) during 326's
  investigation. This is a whole duplicated module, not just the `INTRADAY_ONLY_TFS` constant
  inside it. Needs its own investigation (which file is actually live-imported, is the other
  dead code, was one meant to supersede the other) *before* either copy's `INTRADAY_ONLY_TFS` can
  be safely repointed — fixing the constant inside a dead file is a no-op that looks like
  progress.
- Several inline tuples live in `src/intelligence/trading/*.py`, which — unlike the dead
  `archive/trading_i7/` copies — are still wired into live plugin registration
  (`register_plugins.py`). Confirm per-file liveness before including each in the sweep; don't
  bulk-assume archived.

## Scope for this todo

1. Design the sync-context read path: either (a) a `VocabularyService`-backed
   `_config_service`-style module (Ring 0, prewarmed once at whichever daemon's startup, `get_sync()`
   wrapper for the rest), mirroring the `ConfigService` pattern CLAUDE.md already documents, or
   (b) conclude some call sites should stay as static Ring 0 constants (genuinely no live daemon
   context to prewarm from, e.g. a pure library function importable from a script) and only
   consolidate those into ONE canonical constant rather than forcing a CVR read everywhere. Don't
   assume (a) is right for all 9 sites without checking each one's actual call context.
2. Resolve `utils.py` vs. `utils/core.py` liveness before touching `INTRADAY_ONLY_TFS` in either.
3. Resolve the `_STANDARD_TFS` naming collision — confirm intentional subset vs. stale drift.
4. Where a call site genuinely needs a subset (e.g. `INTRADAY_ONLY_TFS` excludes `1d`), express it
   as a `vocabulary_group` (existing `vocabulary_group_member` join-table pattern, already used for
   `regime_hmm`) so the subset relationship becomes registry-visible.
5. Repoint the confirmed-live call sites at whichever mechanism (1) settles on; delete the
   duplicates.

## Verification

Real production paths touch several live services (`feature_vector_pipeline`,
`bar_writer`, `signal_auditor`, plugin registration) — full `tests/unit/` green is necessary but
not sufficient; a live-daemon restart + smoke check is warranted for at least
`feature_vector_pipeline.service` given `feature_pipeline_executor.py`'s `_STANDARD_TFS` is in
its hot path today.

## Investigation complete, plan written (2026-08-15)

Full liveness check done before planning (per this codebase's own precedent against
consolidation-by-assumption). Real scope is **5 live call sites, not the original 9**:

**Live — in the plan:**
- `services/feature_vector_pipeline.py::_STANDARD_TFS` (confirmed running daemon)
- `services/bar_writer.py::_BAR_TFS` (registered DAG node, currently dormant pending ingestion
  resume, not archived)
- `src/intelligence/services/hmm_trainer.py::_DEFAULT_TARGET_TFS` (legit oneshot agent)
- `src/intelligence/services/feature_validation_analyzer.py::_TIMEFRAMES` (legit oneshot agent)
- `services/signal_auditor.py::_COVERAGE_TFS` (registered DAG node)

**Confirmed dead, split to [[328]] instead:**
- `src/intelligence/pipeline/feature_pipeline_executor.py` — the whole file, not just its
  `_STANDARD_TFS`. Misidentified as live in this todo's original filing (name resembles the
  genuinely-live `feature_vector_pipeline.py`); it's actually v2.x archived (Phase 089 DAG
  decomposition), zero live instantiation anywhere.
- `src/core/bar_history.py::_STANDARD_TFS`, `src/core/service_utils.py::CROSS_ASSET_VALID_TFS` —
  both unused anywhere in the repo.
- `src/intelligence/utils.py` — the whole bare file is unreachable (Python's import resolver
  picks the `utils/` package over it).
- `src/intelligence/utils/core.py::INTRADAY_ONLY_TFS`/`guard_intraday_only` — the live package
  copy, but its only callers are archived-path I7 plugins.

**Also found and fixed as a prerequisite**: CVR's own `timeframe` registry was missing `4h`
despite live data for it since 2023 — migration 317 in the plan.

**Design decision**: `feature_validation_analyzer.py`/`signal_auditor.py` keep their deliberate
4-timeframe subset (no documented rationale found for excluding `1d`/`4h` — not safe to assume
either way) rather than being forced onto the full CVR set; they gain a startup assertion instead
that the subset stays valid against the registry. The other 3 read the full dynamic set.

**Plan**: `docs/superpowers/plans/2026-08-15-timeframe-vocabulary-cvr-consolidation.md` — 8 tasks,
TDD throughout. Task 3 (`feature_vector_pipeline.py`) touches a currently-running daemon; the plan
explicitly defers the restart decision rather than assuming it, same posture as todo 261.
