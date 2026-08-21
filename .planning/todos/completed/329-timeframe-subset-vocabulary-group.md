# 329 - Express `_COVERAGE_TFS`/`_TIMEFRAMES`'s shared 4-timeframe subset as a CVR `vocabulary_group`, not just an assertion

**Filed:** 2026-08-16
**Source:** Final whole-branch review of todo 327 (subagent-driven-development, opus reviewer),
Important finding #3.

## Finding

`services/signal_auditor.py::_COVERAGE_TFS` and `src/intelligence/services/feature_validation_analyzer.py::_TIMEFRAMES`
hold byte-identical literal timeframe subsets (`1m`/`5m`/`15m`/`1h`). Todo 327 gave both a
startup `timeframe_vocabulary.assert_known_subset()` call rather than forcing them onto the full
CVR set, since no evidence existed that excluding `1d`/`4h` was accidental vs. intentional
(preserving behavior was correct).

The reviewer's point, independently verified: these two literals are **literally D-07's own
admission condition** (a fixed code set independently hardcoded in ≥2 files) — the exact
criterion added to `docs/foundation/controlled-vocabulary-registry.md` last session. The chosen
guard (`assert_known_subset`) only catches "this literal references a code CVR never
registered" — it does **not** catch the two literals silently drifting apart from *each other*,
and it doesn't make the subset relationship registry-visible anywhere queryable.

CVR already has the mechanism for this: `vocabulary_group`/`vocabulary_group_member` (used today
for `regime_hmm`'s trending/transition groupings, `regime_cross_sectional_equity`'s vol-tier ×
direction facets, etc. — 15 group rows total, zero for `timeframe`).

## Fix

1. Migration: add a `timeframe` vocabulary group (e.g. `intraday_plus_hourly` or similar —
   name it for what the 4 timeframes have in common, not just their count) with members
   `1m`/`5m`/`15m`/`1h`.
2. Repoint both call sites at `vocab.group_codes("timeframe", "<group_name>")` instead of the
   literal tuple + `assert_known_subset()`.
3. Delete the now-redundant `assert_known_subset()` calls (the group membership check is the
   registry-native replacement).

Zero behavior change (same 4 timeframes either way) — this is purely making an already-real
subset relationship registry-visible, closing the residual same-shape-different-file drift risk
the assertion-only guard left open.

## Closed 2026-08-21

Executed exactly as scoped:

1. **Migration 322** adds `vocabulary_group`/`vocabulary_group_member` rows for
   `('timeframe', 'intraday_plus_hourly')` with members `1m`/`5m`/`15m`/`1h`, same
   pattern as the existing `regime_hmm`/`regime_cross_sectional_equity`/
   `regime_cross_sectional_rates` groups (migration 233).
2. `src/core/vocabulary_access.py` gained `group_codes(namespace, group_name,
   default)`, mirroring `codes()`'s fallback-permissive contract (silent fallback
   if unregistered, warning-logged fallback if the group resolves empty). One
   design decision beyond a literal port of `VocabularyService.group_codes()`:
   `vocabulary_group_member` carries no per-member ordering of its own (it's a
   plain join table), so `group_codes()` filters the namespace's own
   sort_order-ordered `codes()` list down to the group's membership rather than
   sorting alphabetically -- alphabetical would have produced the visibly wrong
   `"1h", "15m", "1m", "5m"` instead of the chronological `"1m", "5m", "15m",
   "1h"`.
3. Both call sites repointed: `SignalAuditor._coverage_tfs`/
   `FeatureValidationAnalyzer._timeframes` are now instance attributes resolved
   in `_setup()` from `vocabulary_access.group_codes("timeframe",
   "intraday_plus_hourly", default=<original literal>)`, replacing the
   `assert_known_subset()` calls. The module-level literals (`_COVERAGE_TFS`/
   `_TIMEFRAMES`) stay as the pre-registry fallback default, same role
   `_DEFAULT_TIMEFRAMES` already plays for `standard_timeframes()`.

**Behavior note, not a deviation from spec:** the todo's "zero behavior change"
claim holds for the steady-state case (CVR migration applied, group populated) --
but the *failure-mode* shape did change, worth recording since it wasn't spelled
out in the original fix note. `assert_known_subset()` hard-crashed daemon startup
if the literal referenced a timeframe code CVR didn't know about at all.
`group_codes()` instead silently falls back to the literal default (with a
warning log) if the *group* isn't registered or resolves empty -- consistent with
every other `vocabulary_access` reader's established fallback-permissive
contract, but a real trade: a broken/unseeded group migration now degrades
silently to the pre-registry literal instead of crashing loud. Judged acceptable
because (a) it matches this module's own established design throughout, and (b)
the actual drift risk this todo exists to close (the two literals silently
diverging from each other) is fully closed either way -- both call sites always
resolve from the same single source now, whether that source is the CVR group or
the fallback literal.

**Tests:** `tests/unit/core/test_vocabulary_access.py` gained 6 new tests for
`group_codes()` (unregistered fallback, registered read, sort-order-not-
alphabetical, empty-group fallback + warning log, silent-when-unregistered).
`tests/unit/_vocabulary_fakes.py`'s shared `FakeVocabularyService` extended with
a `groups` kwarg. Both `test_signal_auditor.py`/`test_feature_validation_analyzer.py`'s
old "asserts subset, raises on drift" setup tests replaced with "resolves from
CVR group" + "falls back to literal when group unregistered" pairs, matching the
new mechanism's actual contract. Full `tests/unit/` suite green (no regressions).
Ruff/black clean on all touched files.

**Aside, filed separately as its own todo, not part of this fix:** verifying this
change didn't introduce new mypy violations surfaced a pre-existing, unrelated
gap -- CI's mypy-baseline gate appears to be failing on every PR regardless of
content due to a mypy-version drift between whatever generated
`.mypy-baseline.txt` and the locally-installed 2.3.0. See
[346](346-mypy-baseline-version-drift-false-positive-new-violations.md).

**Follow-up, 2026-08-21 (same day, working todo 342 next):** `vulture`'s full
CI-equivalent run surfaced `assert_known_subset()` as genuinely dead code --
this fix removed its only two callers and nothing else in `src/`/`services/`/
`scripts/` ever called it (confirmed by direct grep). Removed the function,
its 4 dedicated unit tests, and the now-stale references to it in
`group_codes()`'s own docstring and `FakeVocabularyService`'s docstring.
`vulture`'s full run is back to only its one pre-existing, unrelated finding
(`feature_repository.py`'s `insert_batch`). Full `tests/unit/` suite still
green.
