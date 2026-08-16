# 331 - `VocabularyDriftAuditor`'s windowed source-query design structurally can't catch a registry gap in sparse/old data

**Filed:** 2026-08-16
**Source:** Final whole-branch review of todo 327 (subagent-driven-development, opus reviewer),
Recommendation #4 -- the root-cause explanation for why migration 233's missing `4h` code sat
undetected for 3 years despite `VocabularyDriftAuditor` existing specifically to catch this.

## Finding

`src/config/vocabulary_drift.py` bounds every namespace's source-column query by
`infra.vocabulary_drift.window_days` (APR-sourced, default 30) -- e.g. the `timeframe` check's
query is `WHERE timestamp > now() - ($1 || ' days')::interval`. `4h` bars have 2,184 rows total
across `market_data_ohlcv_tradeable`, most recent bar 2026-08-06, spanning back to 2023-08-08 --
sparse enough, and often enough outside any given 30-day window, that the auditor could
structurally never observe a `4h` row during a run and therefore never flag it as an
"observed code the registry doesn't know about."

This isn't a one-off: the auditor's own documented guard ("Source-idle != mass deprecation. An
empty observed set... is skipped entirely") means a namespace with intermittently-sparse data is
*indistinguishable* from a namespace with no data at all during any window where the real code
happens not to appear -- the exact shape of gap that let `4h`'s absence from the registry go
unnoticed for three years despite regular, passing audit runs (confirmed 2026-07-18 through
2026-08-02 runs all reported `passed=true, unregistered_code_count=0` for `timeframe`).

This class of gap applies to every namespace `vocabulary_drift.py` checks, not just `timeframe`
-- any namespace whose live source column emits a code rarely enough to fall outside the rolling
window has the same blind spot.

## Fix (needs design, not obvious)

Options to weigh, not yet decided:
1. **All-time distinct-code check, run less frequently** -- a second, separate query with no
   time bound (`SELECT DISTINCT code FROM <source>` with no WHERE), run on a longer cadence
   (weekly/monthly) alongside the existing windowed check, specifically to catch sparse/rare
   codes the windowed check structurally can't see. Real cost: a full-table distinct scan on a
   TimescaleDB hypertable is not free at this project's row counts -- needs the same
   measure-before-theorizing discipline as any other batch job touching these tables
   (`docs/foundation/performance-investigation-sop.md`).
2. **Track "last observed" per code**, not just per namespace -- flag a registered code that
   hasn't been observed in N runs as worth a human look (different failure mode than "unregistered
   code observed," but related enough to live in the same system).
3. Leave the windowed design as-is (it does correctly serve its stated purpose -- catching an
   actively-emitting code the registry never heard of) and treat "sparse/rare code missing from
   registry" as a class of gap this system was never meant to close, documented as an explicit
   known limitation instead of silently assumed covered.

Whichever direction: update `docs/foundation/controlled-vocabulary-registry.md`'s
`VocabularyDriftAuditor` section to state the chosen scope explicitly, so a future reader doesn't
assume windowed coverage means complete coverage (which is exactly the wrong assumption this
3-year gap proves people can and do make).
