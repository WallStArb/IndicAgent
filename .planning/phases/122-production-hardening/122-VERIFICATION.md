---
phase: 122-production-hardening
verified: 2026-06-12T20:00:00Z
status: gaps_found
score: 5/7 success criteria verified
re_verification: false
gaps:
  - truth: "intelligence_features table has columns named i1, i3, i4, i5 -- live writes and reads use new names"
    status: failed
    reason: "Migration 125 SQL file exists and code was updated, but migration was NOT applied to the DB. DB still has technical_indicators/pattern_detections/regime_features/confluence_scores. feature_writer._INSERT_FEATURE_SQL references i1/i5/i3/i4 which do not exist in the DB -- every live feature INSERT fails at runtime."
    artifacts:
      - path: "production/migrations/125_rename_intelligence_features_columns.sql"
        issue: "File exists and is correct but has not been applied to the database"
      - path: "services/feature_writer.py"
        issue: "INSERT references i1/i5/i3/i4 columns that do not exist in DB yet"
      - path: "src/api/routes/features.py"
        issue: "SELECT references i1/i5/i3/i4 columns that do not exist in DB yet"
      - path: "src/api/routes/signals.py"
        issue: "SELECT references i1/i5/i3/i4 columns that do not exist in DB yet"
      - path: "src/api/routes/narrative.py"
        issue: "SELECT references i1/i5/i3/i4 columns that do not exist in DB yet"
    missing:
      - "Apply migration 125: PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/125_rename_intelligence_features_columns.sql"

  - truth: "feature_replay.py --shadow-setups --symbols ESM6 --since 2026-06-01 --workers 1 runs to completion and produces signals"
    status: failed
    reason: "CR-01 from code review: _reconstruct_intelligence_event passes source='feature_replay' but IntelligenceEvent.source is Literal['live', 'backfill']. Pydantic raises ValidationError on every row. The try/except catches it, logs warning, returns None. Every row is skipped. Script completes with zero signals -- silently non-functional."
    artifacts:
      - path: "production/scripts/feature_replay.py"
        issue: "Line 148: source='feature_replay' -- not a valid Literal value; should be source='backfill'"
    missing:
      - "Change line 148: source='backfill'  # was 'feature_replay' -- not a valid Literal value"

  - truth: "narrative route correctly reads I2 tier data for LLM context after migration 124"
    status: failed
    reason: "CR-02 from code review: _SIGNAL_QUERY at line 163 selects f.market_context (not f.i2). _build_context_from_row reads row.get('market_context') for the i2= field. After migration 124, market_context contains only {cross_asset: {...}}. LLM receives empty I2 context -- all RSIEvents/StochasticEvents/ADXEvents context missing from narratives."
    artifacts:
      - path: "src/api/routes/narrative.py"
        issue: "Line 163 selects f.market_context; line 125 maps it to i2. Should select f.i2 instead."
    missing:
      - "In _SIGNAL_QUERY replace f.market_context with f.i2"
      - "In _build_context_from_row replace row.get('market_context') with row.get('i2') for i2 field"

  - truth: "pytest tests/unit/ exits 0 -- all plan-introduced tests pass"
    status: failed
    reason: "Plan 06 introduced 4 new test regressions in test_run_historical_pipeline.py. TestBuildLedgerEntries and TestBuildLedgerEntriesFeatureTs call _build_ledger_entries without bar_history (defaults None). The Plan 06 last_bar=None change now returns empty list instead of generating an entry, breaking the expected behavior in these tests. Pre-plan state: 55 pass, 5 fail. Current state: 51 pass, 9 fail -- 4 new failures."
    artifacts:
      - path: "tests/unit/scripts/test_run_historical_pipeline.py"
        issue: "TestBuildLedgerEntries::test_returns_one_entry_per_ranked_signal -- expects 1 entry, gets 0 (no bar_history)"
      - path: "tests/unit/scripts/test_run_historical_pipeline.py"
        issue: "TestBuildLedgerEntries::test_selected_signal_has_was_selected_true -- expects was_selected entry, gets 0"
      - path: "tests/unit/scripts/test_run_historical_pipeline.py"
        issue: "TestBuildLedgerEntriesFeatureTs::test_feature_ts_passes_through -- same root cause"
      - path: "tests/unit/scripts/test_run_historical_pipeline.py"
        issue: "TestBuildLedgerEntriesFeatureTs::test_feature_ts_defaults_to_none -- same root cause"
    missing:
      - "Tests must be updated to pass bar_history with a mock bar so _build_ledger_entries can generate a deterministic signal_id"
      - "Alternatively accept empty list with a comment explaining the tests now require bar data -- but test intent should be preserved"
human_verification:
  - test: "Apply migration 125 and verify feature_writer can insert a row"
    expected: "INSERT succeeds without 'column i1 does not exist' error"
    why_human: "Migration must be applied in production environment; verification requires live write test"
---

# Phase 122: I2 Tier Persistence Fix — Verification Report

**Phase Goal:** Eliminate the hidden training/production bias in `intelligence_features` -- I2Events schema is fully declared (no extra="allow"), live and historical pipelines produce identical `i2` content, and `intelligence_features` gains a dedicated `i2` JSONB column separated from `market_context`.
**Verified:** 2026-06-12T20:00:00Z
**Status:** gaps_found
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths (from ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | I2Events declares exactly 45 fields; extra="forbid"; startup crashes on undeclared output | VERIFIED | `I2Events.model_fields` count=45; `ConfigDict(extra="forbid")` at line 128; `validate_schema_coverage` includes I2Events in tier_checks |
| 2 | I2Events contains zero MACD field declarations | VERIFIED | All 8 MACD fields removed; `I2Events(macd_cross_bullish=1.0)` raises ValidationError |
| 3 | run_analysis_pipeline returns (flat, tiered) 2-tuple; tiered["i2"] contains only I2 outputs | VERIFIED | `return intelligence, tiered` at line 558; `tiered.setdefault(tier_key_lower, {}).update(out)` at line 551; no MACD fields in i2 |
| 4 | _build_intelligence_event constructs i2=I2Events(**tiered.get("i2", {})) | VERIFIED | Line 629: `i2=I2Events(**tiered.get("i2", {}))` -- no _pick helper; _pick deleted |
| 5 | intelligence_features has i2 JSONB column; market_context contains only cross_asset | VERIFIED | DB confirms `i2 jsonb not null default '{}'::jsonb` column present; migration 124 applied |
| 6 | feature_writer writes i2 to dedicated column; market_context receives only cross-asset | PARTIAL | Code correct: `i2_data = event.i2.model_dump(exclude_none=True)` split from market_ctx. BUT migration 125 not applied -- `i1/i3/i4/i5` columns in INSERT do not exist in DB. Live writes fail. |
| 7 | _load_precomputed_features SELECT includes i2 and market_context; --use-precomputed-features path complete | VERIFIED | Line 1007: `i2, market_context` in SELECT; row unpacking 10-element with i2_col, mkt_col |

**Score:** 5/7 success criteria verified (SC-6 partial, SC-5 fully verified for migration 124 only)

### Requirement IDs Cross-Reference

The 4 requirement IDs listed in PLAN frontmatters map to ROADMAP success criteria. REQUIREMENTS.md does not exist as a separate file (requirements are embedded in ROADMAP.md):

| Requirement | Plans | Status | Notes |
|-------------|-------|--------|-------|
| I2-PERSIST-01 | 122-01 | VERIFIED | I2Events 45-field strict contract + validate_schema_coverage |
| I2-PERSIST-02 | 122-02 | VERIFIED | run_analysis_pipeline 2-tuple + tiered dict construction |
| I2-PERSIST-03 | 122-03 | VERIFIED | Migration 124 applied; i2 column exists in DB |
| I2-PERSIST-04 | 122-04 | PARTIAL | Code correct; migration 125 not applied -- live writes broken |

### Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `src/intelligence/schemas.py` | VERIFIED | I2Events: 45 fields, extra="forbid", MACD fields removed, 19 composite fields added |
| `src/intelligence/register_plugins.py` | VERIFIED | I2Events imported; I2 tuple in tier_checks; validate_schema_coverage covers I2 |
| `tests/unit/intelligence/test_schemas.py` | VERIFIED | TestI2EventsSchema with 5 tests, all pass |
| `tests/unit/intelligence/test_i2_schema.py` | VERIFIED | MACD fields asserted absent; composite fields asserted present |
| `production/scripts/run_historical_pipeline.py` | VERIFIED | 2-tuple return, tiered dict construction, _pick deleted, _load_precomputed_features 10-element |
| `tests/unit/scripts/test_run_historical_pipeline.py` | PARTIAL | test_returns_14_tuple passes; BUT 4 new regressions in TestBuildLedgerEntries introduced by Plan 06 |
| `production/migrations/124_add_i2_column.sql` | VERIFIED | 3 statements: ADD COLUMN IF NOT EXISTS, backfill, market_context cleanup; applied to DB |
| `production/migrations/125_rename_intelligence_features_columns.sql` | ORPHANED | File exists with 4 RENAME COLUMN statements; NOT applied to DB; code already uses new names |
| `services/feature_writer.py` | STUB | 33-element tuple code correct; i2_data split correct; SQL uses i1/i5/i3/i4 but DB has old names -- live inserts fail |
| `production/scripts/feature_replay.py` | STUB | File exists, CLI works, ON CONFLICT correct; BUT source="feature_replay" causes ValidationError on every row -- zero signals produced |
| `tests/unit/scripts/test_feature_replay.py` | VERIFIED | 7 static guard tests pass |
| `src/api/routes/features.py` | STUB | Code uses i1/i3/i4/i5 column names; DB still has old names; API reads fail |
| `src/api/routes/signals.py` | PARTIAL | Column names updated; but _TERMINAL_STATUSES is misnamed (CR-03, logic accidentally correct) |
| `src/api/routes/narrative.py` | STUB | Reads market_context instead of i2 for I2 tier data; LLM gets empty I2 context post-migration 124 |
| `src/intelligence/trading/zone_engine.py` | VERIFIED | get_atr_with_floor used; if atr is None: return [] guard present |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| I2Events extra="forbid" | plugin outputs | startup validation | WIRED | validate_schema_coverage crashes startup on undeclared fields |
| register_plugins.py validate_schema_coverage | I2Events | tier_checks list | WIRED | I2Events in tier_checks at position 0 |
| run_analysis_pipeline | tiered dict | tiered.setdefault | WIRED | `tiered.setdefault(tier_key_lower, {}).update(out)` confirmed |
| _build_intelligence_event | I2Events | tiered.get("i2") | WIRED | Line 629 confirmed |
| feature_writer._record_to_insert_params | i2 column | i2_data = event.i2.model_dump | WIRED in code | NOT WIRED to DB -- column i1/i3/i4/i5 don't exist yet |
| _event_to_sync_params | i2 column | json.dumps(event.i2.model_dump) | WIRED | Line 662 confirmed; 14-element tuple verified |
| _load_precomputed_features | i2, market_context | SELECT includes both | WIRED | Lines 1007, 1016 confirmed |
| feature_replay._reconstruct_intelligence_event | IntelligenceEvent | source="backfill" | NOT WIRED | source="feature_replay" -- ValidationError on every row |
| narrative.py _SIGNAL_QUERY | i2 column | SELECT f.i2 | NOT WIRED | Still selects f.market_context |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `production/scripts/feature_replay.py` | 148 | `source="feature_replay"` -- invalid Literal | BLOCKER | Every row reconstruction fails; script produces zero signals |
| `src/api/routes/narrative.py` | 163, 125 | Reads market_context instead of i2 | BLOCKER | LLM receives empty I2 context post-migration 124 |
| `src/api/routes/signals.py` | 28-31 | `_TERMINAL_STATUSES` contains open statuses (named backwards) | WARNING | Logic accidentally correct; dangerous naming invites future inversion bug |
| migration 125 | -- | Not applied to DB; code already uses new column names | BLOCKER | All live feature reads/writes referencing i1/i3/i4/i5 fail at runtime |
| `tests/unit/scripts/test_run_historical_pipeline.py` | 820, 826, 1066, 1075 | TestBuildLedgerEntries has 4 regressions from Plan 06 | WARNING | Tests call _build_ledger_entries without bar_history; now returns empty list |

### Human Verification Required

#### 1. Apply Migration 125 and Verify Live Feature Writes

**Test:** Run `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -f production/migrations/125_rename_intelligence_features_columns.sql` then verify feature_writer can insert a row
**Expected:** INSERT succeeds; columns renamed to i1/i3/i4/i5 visible in `\d intelligence_features`
**Why human:** Migration must be applied in the running environment; requires service restart coordination

## Gaps Summary

Four gaps block complete goal achievement:

**Gap 1 (Blocker): Migration 125 not applied.** The code across feature_writer, historical pipeline, and all 3 API routes was updated to use canonical column names (i1/i3/i4/i5) but migration 125 was not applied. The DB still has `technical_indicators`, `pattern_detections`, `regime_features`, `confluence_scores`. Every live feature INSERT and every API SELECT that references i1/i3/i4/i5 fails with a "column does not exist" error. The migration file is correct and ready to apply.

**Gap 2 (Blocker): feature_replay.py silently produces zero signals.** `_reconstruct_intelligence_event` at line 148 passes `source="feature_replay"` to IntelligenceEvent. The schema declares `source: Literal["live", "backfill"]`. Pydantic raises ValidationError on every row; the try/except silently returns None; every row is skipped. The fix is one character change: `source="backfill"`.

**Gap 3 (Blocker): narrative route reads market_context instead of i2.** Post migration 124, market_context contains only `{cross_asset: {...}}`. The narrative route's SQL still selects `f.market_context` and maps it to the `i2=` field in the context builder. Every narrative generated after migration 124 lacks I2 tier data (RSI, Stochastic, ADX, Volume, composite fields). The LLM is reasoning without this context.

**Gap 4 (Warning): 4 new test regressions from Plan 06.** Plan 06's last_bar=None warning+continue change caused `TestBuildLedgerEntries` and `TestBuildLedgerEntriesFeatureTs` to fail. These tests call `_build_ledger_entries` without `bar_history` (defaults to None), so `last_bar` is None and the new code skips signal generation, returning empty entries. The tests expected 1 entry. The tests need to be updated to provide a mock bar_history -- they test real behavior that should still work.

Gaps 1-3 are blocking production correctness (live writes fail, narrative context is wrong, replay is inert). Gap 4 is a test coverage regression.

---

_Verified: 2026-06-12T20:00:00Z_
_Verifier: Claude (gsd-verifier)_
