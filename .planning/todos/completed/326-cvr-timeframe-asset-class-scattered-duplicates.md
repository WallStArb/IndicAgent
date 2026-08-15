# 326 - `asset_class` CVR namespace already exists but nothing read it — live drift bug (CLOSED, timeframe half split to 327)

**Filed:** 2026-08-15
**Source:** Found while re-checking todo 324's CVR-fit question after user pushback ("CVR really
should be a cheap single source of truth for lists — we have many scattered throughout"). Grepped
for evidence rather than reasoning abstractly; found real, live scatter in namespaces CVR already
owns. Prompted [[D-07]] in `docs/foundation/controlled-vocabulary-registry.md` (this doc).

## Confirmed

### `asset_class` — three-way scatter, not just two, resolved 2026-08-15
- CVR `asset_class` namespace has 3 codes (`equity`, `futures`, `fx` — verified directly against
  `controlled_vocabulary` table; migration 233 deliberately seeded exactly these 3, matching what
  `instruments.contract_details->>'asset_class'` actually emits).
- `src/api/routes/instruments.py`'s `InstrumentUpsert`/`InstrumentUpdate` write-path models
  (lines ~35, ~53) hardcode `Literal["equity", "futures", "fx", "crypto"]` — a 4th value.
- **A third independent source also exists**: `AssetClass(StrEnum)` in `src/core/models.py` (Ring
  0) has **5** values — `equity`, `futures`, `fx`, `crypto`, `option`. `src/providers/ibkr.py:946`
  has a live contract-qualification branch for `AssetClass.CRYPTO`; `AssetClass.OPTION` is
  declared but referenced nowhere else in the repo.
- **Resolved by checking the DB, not assumption**: asked the user whether `crypto` is real; they
  pointed at crypto-exposed names in the universe (MARA, MSTR, IBIT, COIN). Checked
  `instruments.contract_details->>'asset_class'` for all four — **all classified `equity`**
  (correct — they trade as regular shares/ETF units, not native crypto contracts), and
  `count(*) WHERE asset_class = 'crypto'` across all of `instruments` is **0**. The premise behind
  "crypto is live" doesn't hold; those are crypto-*themed* equities, not `asset_class='crypto'`
  rows. `ibkr.py`'s `AssetClass.CRYPTO` branch is real but currently dead code (nothing calls it
  with a crypto contract today).
- **Verdict:** CVR's 3 codes are correct and complete for what's actually live. The API's
  `Literal` is the odd one out — drop `"crypto"` from both `InstrumentUpsert`/`InstrumentUpdate`.
  Leave `AssetClass.CRYPTO`/`AssetClass.OPTION` in the Ring 0 enum alone (harmless forward
  capability; `ibkr.py` already depends on `CRYPTO` existing as a symbol even though unused).
- Fix: source the Literal (or a runtime validator) from `VocabularyService.codes("asset_class")`
  instead of a hand-typed tuple, so this can't silently re-drift the next time CVR's registry
  changes. **The moment a real crypto instrument is onboarded, add it to CVR via migration first**
  — that's what makes it appear in this API automatically, not another hand-edit of the Literal.

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

## Status (2026-08-15)

**`asset_class` fix: DONE, committed `66ee8b055`.** `src/api/routes/instruments.py` now validates
against the CVR `controlled_vocabulary` registry at request time instead of a hardcoded `Literal`;
two new regression tests prove `"crypto"` is rejected on both POST and PUT. Full `tests/unit/`
suite green.

**`timeframe` consolidation: split out to [[327]].** It's a materially harder problem than
`asset_class` was — most of the 9 call sites are Ring 0 sync modules with no existing DB pool or
async-init hook to read `VocabularyService` from (unlike `instruments.py`, which already had a
per-request DB handle to reuse), plus a same-name-different-value collision and a whole duplicated
module (`utils.py`/`utils/core.py`) that both need resolving before any constant inside them is
safe to touch. Matches this codebase's own precedent for not bolting a registry-read into a hot
path in the same sweep that found the gap (`_batch_utils.py`'s todo-308 comment, `ic_engine.py`'s
todo 307) — deserves its own focused pass.

## Scope note

[[324]] (adding the not-yet-governed `gradient_scale` namespace under the new D-07 criterion this
todo's grep justified) is separate work, needs the `has_live_source` auditor change designed
first.
