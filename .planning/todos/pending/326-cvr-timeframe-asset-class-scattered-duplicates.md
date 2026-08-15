# 326 - `timeframe`/`asset_class` CVR namespaces already exist but nothing reads them — live scatter and one confirmed drift bug

**Filed:** 2026-08-15
**Source:** Found while re-checking todo 324's CVR-fit question after user pushback ("CVR really
should be a cheap single source of truth for lists — we have many scattered throughout"). Grepped
for evidence rather than reasoning abstractly; found real, live scatter in namespaces CVR already
owns. Prompted [[D-07]] in `docs/foundation/controlled-vocabulary-registry.md` (this doc).

## Confirmed

### `asset_class` — live drift bug, not just scatter
- CVR `asset_class` namespace has 3 codes (`equity`, `futures`, `fx` — verified directly against
  `controlled_vocabulary` table).
- `src/api/routes/instruments.py` hardcodes `Literal["equity", "futures", "fx", "crypto"]` in two
  places (lines ~35, ~53) — a fourth value, `"crypto"`, that exists nowhere in the registry or in
  `get_active_contracts()`. This is served by the live `indicagent-api.service`.
- Fix: source the Literal (or a runtime validator) from `VocabularyService.codes("asset_class")`
  instead of a hand-typed tuple; drop `"crypto"` unless a real crypto instrument is intended to be
  onboarded (check with the user — this looks like copy-paste from a generic template, not an
  intentional roadmap item).

### `timeframe` — 9 independently-hardcoded tuples, one same-name collision
`timeframe` is a live CVR namespace (5 codes) with `VocabularyService` and an API route already
built (`GET /timeframe`). None of the following read from it:

- `src/core/service_utils.py:80` — `CROSS_ASSET_VALID_TFS = frozenset({"1m", "5m", "15m", "1h"})`
- `src/intelligence/services/feature_validation_analyzer.py:49` — `_TIMEFRAMES = ["1m", "5m", "15m", "1h"]`
- `services/bar_writer.py:58` — `_BAR_TFS = ("1m", "5m", "15m", "1h", "4h", "1d")`
- `src/core/bar_history.py:27` — `_STANDARD_TFS = ("1m", "5m", "15m", "1h")`
- `src/intelligence/utils.py:12` and `src/intelligence/utils/core.py:12` — `INTRADAY_ONLY_TFS = ("1m", "5m", "15m")`. **Verified, not a re-export**: `diff` shows `utils.py` (147 lines) is byte-identical to the first 147 lines of `utils/core.py` (167 lines) — a whole duplicated module, not just this one constant. That's a bigger, separate cleanup (dead-file-vs-live-file question) than this todo's scope; flagging here since it's where the duplicate constant was found, but the module-level duplication itself needs its own investigation (which file is actually imported live, is the other dead) before merging into this fix.
- `src/intelligence/services/hmm_trainer.py:53` — `_DEFAULT_TARGET_TFS = ("1m", "5m", "15m", "1h", "4h", "1d")`
- `src/intelligence/pipeline/feature_pipeline_executor.py:67` — `_STANDARD_TFS = ("1m", "5m", "15m", "1h", "4h", "1d")` — **same name as `bar_history.py`'s `_STANDARD_TFS`, different value (6 tfs vs. 4)**. Both modules are live (`feature_vector_pipeline.service` uses the pipeline executor). A future consolidation/refactor that assumes the two `_STANDARD_TFS` symbols are interchangeable would silently pick up the wrong set.
- `services/signal_auditor.py:37` — `_COVERAGE_TFS = ("1m", "5m", "15m", "1h")`
- Several inline literal tuples (`("1m", "5m", "15m")`) in `src/intelligence/trading/*.py` — these
  files are still imported by live plugin registration (`register_plugins.py` etc.), unlike the
  `archive/trading_i7/` copies which are dead (`indicagent-intelligence-pipeline.service` is
  `failed`) — confirm liveness per-file before including in the sweep, don't assume archived.

Fix: pick one canonical constant sourced from `VocabularyService.codes("timeframe")` (or
`.active_codes()` where deprecated codes should be excluded) in Ring 0, and repoint the ~9 call
sites at it, deleting the duplicates. Where a call site intentionally needs a *subset* (e.g.
`INTRADAY_ONLY_TFS` excludes `1d`), express that as a `vocabulary_group` (per the existing
`vocabulary_group_member` pattern already used for `regime_hmm`) rather than a fresh hardcoded
tuple, so the subset relationship is registry-visible too.

## Scope note

This is a mechanical consolidation + one real correctness fix (`asset_class`/`crypto`), not new
governance design — [[324]] is the separate, smaller task of extending CVR's *coverage* (adding
the not-yet-governed `gradient_scale` namespace under the new D-07 criterion this todo's grep
justified). Do 326 first if sequencing matters — it's a pure win with a real live bug in it and no
open design questions; 324 needs the `has_live_source` auditor change designed first.
