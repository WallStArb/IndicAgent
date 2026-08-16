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
