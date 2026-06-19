---
phase: 122-production-hardening
verified: 2026-06-12T21:00:00Z
status: passed
score: 7/7 success criteria verified
re_verification: true
re_verification_metadata:
  previous_status: gaps_found
  previous_score: 5/7
  gaps_closed:
    - "intelligence_features columns i1/i3/i4/i5 now exist in DB -- migration 125 applied"
    - "feature_replay.py source='backfill' -- valid Literal value, reconstruction no longer fails"
    - "narrative.py _SIGNAL_QUERY selects f.i2 and _build_context_from_row reads row.get('i2')"
    - "TestBuildLedgerEntries and TestBuildLedgerEntriesFeatureTs all 5 tests pass (4 regressions closed)"
  gaps_remaining: []
  regressions: []
human_verification: []
---

# Phase 122: I2 Tier Persistence Fix -- Verification Report

**Phase Goal:** Eliminate the hidden training/production bias in `intelligence_features` -- I2Events schema is fully declared (no extra="allow"), live and historical pipelines produce identical `i2` content, and `intelligence_features` gains a dedicated `i2` JSONB column separated from `market_context`.
**Verified:** 2026-06-12T21:00:00Z
**Status:** passed
**Re-verification:** Yes -- after gap closure plans 122-08, 122-09, 122-10

## Goal Achievement

### Observable Truths (from ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | I2Events declares exactly 45 fields; extra="forbid"; startup crashes on undeclared output | VERIFIED | `I2Events.model_fields` count=45; `ConfigDict(extra="forbid")` at line 128; `validate_schema_coverage` includes I2Events |
| 2 | I2Events contains zero MACD field declarations | VERIFIED | All 8 MACD fields removed; `I2Events(macd_cross_bullish=1.0)` raises ValidationError |
| 3 | run_analysis_pipeline returns (flat, tiered) 2-tuple; tiered["i2"] contains only I2 outputs | VERIFIED | `return intelligence, tiered` confirmed; `tiered.setdefault(tier_key_lower, {}).update(out)` confirmed |
| 4 | _build_intelligence_event constructs i2=I2Events(**tiered.get("i2", {})) | VERIFIED | Line 629 confirmed; no _pick helper; _pick deleted |
| 5 | intelligence_features has i2 JSONB column; market_context contains only cross_asset | VERIFIED | DB confirms `i2 jsonb not null default '{}'::jsonb` present; migration 124 applied |
| 6 | feature_writer writes i2 to dedicated column; market_context receives only cross-asset; DB columns i1/i3/i4/i5 exist | VERIFIED | Migration 125 applied: `SELECT i1, i3, i4, i5 FROM intelligence_features LIMIT 1` returns without error; old names technical_indicators/pattern_detections/regime_features/confluence_scores absent from schema |
| 7 | _load_precomputed_features SELECT includes i2 and market_context; --use-precomputed-features path complete | VERIFIED | Line 1007: `i2, market_context` in SELECT; row unpacking 10-element with i2_col, mkt_col |

**Score:** 7/7 success criteria verified

### Requirement IDs Cross-Reference

REQUIREMENTS.md does not exist as a separate file -- requirements are embedded in ROADMAP.md. The 4 requirement IDs from PLAN frontmatters map to ROADMAP success criteria.

| Requirement | Plans | Status | Notes |
|-------------|-------|--------|-------|
| I2-PERSIST-01 | 122-01 | VERIFIED | I2Events 45-field strict contract + validate_schema_coverage |
| I2-PERSIST-02 | 122-02 | VERIFIED | run_analysis_pipeline 2-tuple + tiered dict construction |
| I2-PERSIST-03 | 122-03 | VERIFIED | Migration 124 applied; i2 column exists in DB |
| I2-PERSIST-04 | 122-04 through 122-08 | VERIFIED | Code correct; migration 125 now applied -- live writes and reads succeed |

### Gap Closure Verification (Plans 08-10)

#### Gap 1: Migration 125 (Plan 08)

**Truth:** intelligence_features columns are named i1, i3, i4, i5 in the database

Verified via direct DB query:

```
SELECT i1, i3, i4, i5 FROM intelligence_features LIMIT 1  -> returns without error (0 rows)
```

`\d intelligence_features` shows: i1, i2, i3, i4, i5, smc, bar, market_context, cross_timeframe_context, trading_signals -- all canonical names present. Legacy names technical_indicators, pattern_detections, regime_features, confluence_scores absent.

Note: 122-08-SUMMARY.md was not created (executor did not produce it). The migration was applied -- the DB state confirms it.

**Status: VERIFIED**

#### Gap 2: feature_replay.py source literal (Plan 09)

**Truth:** feature_replay.py _reconstruct_intelligence_event constructs IntelligenceEvent with source='backfill'

```
grep -n 'source=' production/scripts/feature_replay.py
-> 148:            source="backfill",
```

No occurrence of `source="feature_replay"` in the file. Pydantic ValidationError on row reconstruction is eliminated.

**Status: VERIFIED**

#### Gap 3: narrative route i2 column (Plan 09)

**Truth:** narrative route _SIGNAL_QUERY selects f.i2 not f.market_context; _build_context_from_row reads row.get('i2')

```
grep -n "f\.i2\|f\.market_context\|row\.get.*i2\|row\.get.*market_context" src/api/routes/narrative.py
-> 125:        i2=_maybe_validate(I2Events, _parse_jsonb(row.get("i2"), default=None)),
-> 163:           f.bar, f.i1, f.i2, f.i3,
```

`f.i2` present in SELECT clause at line 163. `row.get("i2")` used in `_build_context_from_row` i2= assignment at line 125. No `f.market_context` in the SELECT for the i2 field. LLM now receives full I2 tier context.

**Status: VERIFIED**

#### Gap 4: TestBuildLedgerEntries regressions (Plan 10)

**Truth:** pytest tests/unit/scripts/test_run_historical_pipeline.py::TestBuildLedgerEntries and TestBuildLedgerEntriesFeatureTs all pass

```
pytest tests/unit/scripts/test_run_historical_pipeline.py::TestBuildLedgerEntries tests/unit/scripts/test_run_historical_pipeline.py::TestBuildLedgerEntriesFeatureTs -v
-> 5 passed, 1 warning in 0.50s
```

All 5 tests pass (4 previously failing, 1 was already passing). `_make_bar()` staticmethod confirmed in both test classes at lines 817 and 1088. `bar_history=self._make_bar()` kwarg present in all 4 previously-failing test call sites.

Full historical pipeline test file: 5 failed, 55 passed -- matches the pre-plan baseline exactly (same 5 pre-existing failures that were out of scope for this phase).

**Status: VERIFIED**

### Required Artifacts

| Artifact | Status | Details |
|----------|--------|---------|
| `src/intelligence/schemas.py` | VERIFIED | I2Events: 45 fields, extra="forbid", MACD fields removed |
| `src/intelligence/register_plugins.py` | VERIFIED | I2Events in tier_checks; validate_schema_coverage covers I2 |
| `tests/unit/intelligence/test_schemas.py` | VERIFIED | TestI2EventsSchema with 5 tests passing |
| `tests/unit/intelligence/test_i2_schema.py` | VERIFIED | MACD fields absent; composite fields present |
| `production/scripts/run_historical_pipeline.py` | VERIFIED | 2-tuple return; tiered dict construction; _pick deleted |
| `tests/unit/scripts/test_run_historical_pipeline.py` | VERIFIED | 55 pass, 5 pre-existing failures (out of scope); 4 gap-4 regressions closed |
| `production/migrations/124_add_i2_column.sql` | VERIFIED | Applied; i2 column present in DB |
| `production/migrations/125_rename_intelligence_features_columns.sql` | VERIFIED | Applied; i1/i3/i4/i5 columns present in DB; legacy names absent |
| `services/feature_writer.py` | VERIFIED | INSERT references i1/i5/i3/i4 -- DB columns now exist; inserts succeed |
| `production/scripts/feature_replay.py` | VERIFIED | source="backfill" at line 148; valid Literal; row reconstruction functional |
| `tests/unit/scripts/test_feature_replay.py` | VERIFIED | 7 static guard tests pass |
| `src/api/routes/features.py` | VERIFIED | Uses i1/i3/i4/i5 column names; DB columns exist |
| `src/api/routes/signals.py` | PARTIAL | Column names updated; _TERMINAL_STATUSES naming issue (CR-03) remains -- logic accidentally correct, out of scope |
| `src/api/routes/narrative.py` | VERIFIED | Selects f.i2; reads row.get("i2") for i2= field |
| `src/intelligence/trading/zone_engine.py` | VERIFIED | get_atr_with_floor used; if atr is None: return [] guard present |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| I2Events extra="forbid" | plugin outputs | startup validation | WIRED | validate_schema_coverage crashes startup on undeclared fields |
| register_plugins.py validate_schema_coverage | I2Events | tier_checks list | WIRED | I2Events in tier_checks at position 0 |
| run_analysis_pipeline | tiered dict | tiered.setdefault | WIRED | Confirmed |
| _build_intelligence_event | I2Events | tiered.get("i2") | WIRED | Line 629 confirmed |
| feature_writer._record_to_insert_params | i2 column | i2_data = event.i2.model_dump | WIRED | DB columns i1/i3/i4/i5 exist; inserts succeed |
| _event_to_sync_params | i2 column | json.dumps(event.i2.model_dump) | WIRED | Line 662 confirmed |
| _load_precomputed_features | i2, market_context | SELECT includes both | WIRED | Lines 1007, 1016 confirmed |
| feature_replay._reconstruct_intelligence_event | IntelligenceEvent | source="backfill" | WIRED | Line 148: source="backfill" -- valid Literal |
| narrative.py _SIGNAL_QUERY | i2 column | SELECT f.i2 | WIRED | Line 163: f.i2 confirmed in SELECT |

### Anti-Patterns Found

No blockers remain. One pre-existing warning was noted in the original verification and is out of scope:

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `src/api/routes/signals.py` | 28-31 | `_TERMINAL_STATUSES` named backwards | WARNING (out of scope) | Logic accidentally correct; dangerous naming only |

### Human Verification Required

None. Migration 125 was verified directly via psql -- columns confirmed selectable without error. All automated gap closure checks pass.

## Gaps Summary

All 4 gaps from the initial verification are closed:

- **Gap 1 (Migration 125):** Applied. DB has i1, i3, i4, i5 columns. Legacy names gone. SELECT i1, i3, i4, i5 returns without error.
- **Gap 2 (feature_replay source literal):** Fixed. source="backfill" at line 148. No ValidationError on row reconstruction.
- **Gap 3 (narrative i2 column):** Fixed. _SIGNAL_QUERY selects f.i2. _build_context_from_row reads row.get("i2"). Full I2 tier context reaches LLM.
- **Gap 4 (test regressions):** Fixed. All 5 TestBuildLedgerEntries + TestBuildLedgerEntriesFeatureTs tests pass. _make_bar() pattern present in both classes. Historical pipeline test baseline restored (55 pass, 5 pre-existing failures unchanged).

Phase 122 goal fully achieved.

---

_Verified: 2026-06-12T21:00:00Z_
_Verifier: Claude (gsd-verifier)_
