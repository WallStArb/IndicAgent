---
priority: P3
status: pending
source: /simplify pass on Phase 173's diff, 2026-08-26 (altitude review agent)
---

# Three design-depth notes from Phase 173, all already reviewed and accepted — not bugs,
# not urgent, recorded for future consideration only

## 1. `_BROADCAST_CLUSTER_ID_OFFSET = 10000` is a numeric-range partition bolted onto the
BH-FDR `(regime, lookahead_bars, cluster_id)` grouping key, not a schema-level discriminant

`services/ic_engine.py:198` and consumers. Keeps broadcast and per-symbol cluster IDs from
colliding by relying on the offset staying below `cluster_id`'s `smallint` ceiling (documented,
bounded — ~40 broadcast features leaves wide margin, no runtime risk today). The deeper fix
would be a real `cell_kind` field in the grouping tuple instead of encoding kind as a numeric
range. Notably this is the same offset-in-shared-ID-space technique the phase deletes elsewhere
(the old `CONTEXT_FEATURES` daily-cadence path) as a named anti-pattern.

**Why not changed:** this exact mechanism was reviewed and passed by both codex and agy in
Phase 173's mandatory Wave-3 review ("BH-FDR family composition, boundary-scan edge cases,
cluster_id offset bound — confirmed looks correct, no action needed"). Re-opening it via
/simplify would re-litigate an already-reviewed, explicitly-bounded, working decision.

## 2. `_fingerprint_computational_key` special-cases the literal string `"broadcast_hash"`
instead of classifying watermark sub-keys generically at the point they're produced

`services/ic_engine.py:1366-1372`. This was a real bug found and fixed live during 173-03
execution (a broadcast-flag flip would otherwise have silently served stale IC values). The
fix is honest about its own scope — the docstring calls it "the one exception" — but the general
form would classify each watermark sub-key as computational-vs-status-only at
`_watermark_concept_registry` (~line 1044) instead of name-sniffing one hardcoded key in the
consumer. Worth doing if a future watermark field also needs this distinction; not urgent now
since the current exception is narrow and disclosed, not hidden.

## 3. `_D02_ENUMERATED_BROADCAST_FEATURES` (32-name validation floor) lives in the ops script,
not a test — will drift silently with no CI signal

`scripts/ops/alpha/ops_broadcast_feature_audit.py:202-237`. Used only as an operator-facing
sanity-check warning on `--persist`, not to drive classification (the empirical detector still
decides). Moving the equivalent "detector output matches the documented floor" assertion into
`tests/unit/scripts/test_ops_broadcast_feature_audit.py` would catch drift at CI time instead of
silently on some future live run. Low risk either way since it's a floor-check, not the
classification path itself.

## Recommendation

None urgent. #1 and #2 are legitimate architecture notes for a future phase that touches
`ic_engine.py`'s clustering/fingerprinting more broadly — don't do a standalone refactor just
for these. #3 is a cheap, safe pickup whenever `ops_broadcast_feature_audit.py` is next touched.
