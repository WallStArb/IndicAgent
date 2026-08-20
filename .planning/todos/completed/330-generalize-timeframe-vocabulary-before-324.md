# 330 - Generalize `src/core/timeframe_vocabulary.py` to a namespace-parameterized module before todo 324 lands

**Filed:** 2026-08-16
**Source:** Final whole-branch review of todo 327 (subagent-driven-development, opus reviewer),
Important finding #5.

## Finding

`src/core/timeframe_vocabulary.py` (todo 327) holds an entire `VocabularyService` instance
(covering every CVR namespace) behind a module named and scoped for `timeframe` specifically —
`set_vocabulary_service()`, `standard_timeframes()`, `assert_known_subset()` are all
`timeframe`-flavored names wrapping namespace-agnostic logic.

Todo 324 (gradient vocabulary → CVR `gradient_scale` namespace, PRIORITIES.md P3, settled under
the D-07 criterion) needs precisely this same sync-context accessor pattern. When it lands it
will either import from `timeframe_vocabulary` (nonsensical at the call site — why would gradient
vocab code import a module named for timeframes) or declare a second `_vocab_service` module
global, which can then drift out of sync with `timeframe_vocabulary`'s about which
`VocabularyService` instance is actually registered in a given process.

The reviewer's framing (independently endorsed): this is not premature abstraction, since the
generalized shape is *smaller* than the current one, not larger — the same code with `"timeframe"`
hardcoded into `active_codes("timeframe")` calls becomes a `namespace: str` parameter.

## Fix

1. Rename `src/core/timeframe_vocabulary.py` → `src/core/vocabulary_access.py` (or similar).
2. Generalize the API: `set_vocabulary_service(vocab)` (unchanged — one process, one registered
   service, namespace-agnostic), `codes(namespace: str, default: tuple[str, ...]) -> tuple[str, ...]`,
   `assert_known_subset(namespace: str, values: tuple[str, ...], *, context: str) -> None`.
3. Add `standard_timeframes(default=...) -> tuple[str, ...]` as a thin 3-line convenience wrapper
   (`return codes("timeframe", default)`) so todo 327's 5 call sites need zero changes beyond the
   import path.
4. Repoint all 5 existing `from src.core import timeframe_vocabulary` call sites at the renamed
   module.
5. Todo 324, when it lands, calls `codes("gradient_scale", ...)` / `assert_known_subset("gradient_scale", ...)`
   directly — no new module, no second global.

**Sequencing: do this before todo 324, not after.** Cheap now (one module rename + a parameter
lift, 5 known call sites to repoint, all already covered by existing tests). Expensive after —
once todo 324 exists as a second concrete consumer with its own timeframe-shaped copy-paste, the
generalization becomes a bigger, riskier refactor touching two independently-evolved modules
instead of one clean rename.
