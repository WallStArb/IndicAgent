---
phase: 01-typed-event-schema
verified: 2026-02-23T10:15:00Z
status: passed
score: 5/5 must-haves verified
gaps: []
human_verification:
  - test: "Publish a live bar through market_analysis_service and confirm the intelligence: stream contains a single 'event' field with valid IntelligenceEvent JSON"
    expected: "redis-cli XREAD returns {'event': '{\"schema_version\":\"1.0\",\"ts\":...}'} — not 50+ flat fields"
    why_human: "Requires live Redis + running service; not exercised by unit tests alone"
  - test: "Open the dashboard while market_analysis_service is publishing and confirm intelligence tiles (GARCH sigma, regime, BOS, CTF score) render with real values"
    expected: "Dashboard displays non-null values for at least vol_regime, garch_sigma, bos_detected, ctf_score after a bar cycle"
    why_human: "Full SSE->parseIntelligence()->React render chain requires a live browser session"
---

# Phase 01: Typed Event Schema Verification Report

**Phase Goal:** Every intelligence output flows through one canonical typed bus — IntelligenceEvent replaces flat string k/v stream messages and intelligence_processor_service.py is gone
**Verified:** 2026-02-23T10:15:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | market_analysis_service.py publishes IntelligenceEvent objects (validated by Pydantic) to the intelligence: stream — malformed events are rejected at source | VERIFIED | `_publish_intelligence()` at line 372 constructs `IntelligenceEvent(...)`, wraps in `try/except ValidationError`, calls `event.model_dump_json()`, emits `{"event": <json>}` via `xadd`. Malformed events logged + returned early (line 422-430). |
| 2 | signal_generator_service.py, SSE route, and all downstream consumers deserialize IntelligenceEvent instead of raw field dicts — no more bare dict access | VERIFIED | `signal_generator_service.py` line 73: `_parse_intelligence_event()` calls `IntelligenceEvent.model_validate_json(raw)`. `signal_orchestrator_service.py` line 98: identical pattern. Dashboard `use-market-stream.ts` line 68: `JSON.parse(p.event || "{}")` then tier access (`i3.`, `i4.`, `i5.`, `smc.`, `i6.`). Zero flat `p["garch_sigma"]`-style accesses remain. |
| 3 | intelligence_processor_service.py is deleted from the codebase and all references point to market_analysis_service.py | VERIFIED | File does not exist in `services/`. Three test files deleted. `config/intelligence_processor.json` deleted. Zero references in `services/`, `tests/`, `src/` (main branch). `.worktrees/` references are separate git branches, not main. CLAUDE.md and skill files reference `market_analysis_service.py`. |
| 4 | The intelligence: stream messages contain tiered JSONB (i1/i3/i4/i5/smc/i6) with a schema_version field and platform dimension — not a flat string blob | VERIFIED | `src/intelligence/schemas.py`: `IntelligenceEvent` has `schema_version: Literal["1.0"] = "1.0"`, `platform: str = "futures"`, `source: Literal["live", "backfill"] = "live"`, sub-models `bar/i1/i3/i4/i5/smc/i6`. Stream payload is single `{"event": model_dump_json()}` — not flat k/v. |
| 5 | All 551+ existing tests still pass after the migration | VERIFIED | `pytest --ignore=tests/integration -q` → 562 passed, 0 failed. Test count grew from 551 baseline to 562 (11 net new tests for typed deserialization). |

**Score:** 5/5 truths verified

---

### Required Artifacts

#### Plan 01-01 Artifacts (BUS-01, BUS-02)

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/intelligence/schemas.py` | IntelligenceEvent + all 7 sub-models | VERIFIED | 395 lines. Exports: `IntelligenceEvent`, `OHLCVBar`, `I1Indicators`, `I3Structure`, `I4Context`, `I5Patterns`, `SMCContext`, `I6Confluence`. All sub-models are Pydantic v2 `BaseModel`. |
| `services/market_analysis_service.py` | Updated publisher using IntelligenceEvent | VERIFIED | Contains `model_dump_json` at line 435. `_publish_intelligence()` constructs `IntelligenceEvent` with all 7 sub-models, catches `ValidationError`, emits `{"event": <json>}`. |
| `tests/unit/service_tests/test_market_analysis_service.py` | Tests for schema + publisher | VERIFIED | Contains `TestIntelligenceEventSchema` class with 8+ schema tests and `TestPublisherFormat` class. Contains `model_validate_json` and `IntelligenceEvent` throughout. |

#### Plan 01-02 Artifacts (BUS-03)

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `services/signal_generator_service.py` | Typed IntelligenceEvent consumer | VERIFIED | Contains `model_validate_json` (line 82). `_parse_intelligence_event()` pattern present. `parse_intelligence_message()` absent — 0 matches. |
| `services/signal_orchestrator_service.py` | Typed IntelligenceEvent consumer | VERIFIED | Contains `model_validate_json` (line 107). `_parse_intelligence_event()` pattern present. `parse_intelligence_message()` absent — 0 matches. |
| `src/api/routes/sse.py` | SSE relay with format comment | VERIFIED | Lines 69-72: comment block stating "Intelligence stream payload: {'event': '<IntelligenceEvent JSON>'} — see src/intelligence/schemas.py". No flat field access. |
| `dashboard/src/hooks/use-market-stream.ts` | Updated parseIntelligence() for nested JSON | VERIFIED | Line 68: `const event = JSON.parse(p.event || "{}")`. Tier extraction at lines 80-150+: `i3.nearest_support`, `i4.vol_regime`, `i5.rsi_div_bullish`, `smc.bos_detected`, `i6.ctf_score`. Contains `JSON.parse`. |
| `tests/unit/service_tests/test_signal_generator_service.py` | Tests for typed deserialization | VERIFIED | File exists. Contains `model_validate_json` and `IntelligenceEvent` at multiple points. 8 tests covering parse success, None on missing field, None on malformed JSON, None on ValidationError, and end-to-end attribute routing. |
| `tests/unit/service_tests/test_signal_orchestrator_helpers.py` | Tests for typed deserialization | VERIFIED | File exists. Contains `model_validate_json` and `IntelligenceEvent`. 4 replacement tests for `_parse_intelligence_event` covering valid/missing/malformed/ValidationError cases. |

#### Plan 01-03 Artifacts (BUS-04)

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `services/intelligence_processor_service.py` | DELETED — must not exist | VERIFIED | File does not exist. `ls` returns "MISSING". |
| `tests/unit/service_tests/test_intelligence_processor.py` | DELETED — must not exist | VERIFIED | File does not exist. |
| `tests/unit/service_tests/test_intelligence_processor_ohlcv.py` | DELETED — must not exist | VERIFIED | File does not exist. |
| `tests/unit/service_tests/test_intelligence_source_filter.py` | DELETED — must not exist | VERIFIED | File does not exist. |
| `config/intelligence_processor.json` | DELETED — must not exist | VERIFIED | File does not exist. |

---

### Key Link Verification

#### Plan 01-01 Key Links

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `services/market_analysis_service.py` | `src/intelligence/schemas.py` | `from src.intelligence.schemas import IntelligenceEvent` | WIRED | Import present at line 388-397 inside `_publish_intelligence()`. |
| `market_analysis_service._publish_intelligence()` | Redis XADD | `event.model_dump_json()` | WIRED | Line 435: `{"event": event.model_dump_json()}` passed to `xadd`. |
| `_run_analysis_pipeline()` | tiered dict return | dict with i3/i4/i5/smc/i6 keys | WIRED | Lines 268-278 confirm `tiered = {"i3": i3_results, "i4": i4_results, "i5": i5_results, "smc": smc_results, "i6": i6_results, "flat": flat}`. |

#### Plan 01-02 Key Links

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `services/signal_generator_service.py` | `src/intelligence/schemas.py` | `IntelligenceEvent.model_validate_json()` | WIRED | Import at line 44: `from src.intelligence.schemas import IntelligenceEvent`. Used at line 82: `IntelligenceEvent.model_validate_json(raw)`. |
| `services/signal_orchestrator_service.py` | `src/intelligence/schemas.py` | `IntelligenceEvent.model_validate_json()` | WIRED | Import at line 47. Used at line 107: `IntelligenceEvent.model_validate_json(raw)`. |
| `dashboard/src/hooks/use-market-stream.ts` | intelligence stream event field | `JSON.parse(p.event)` | WIRED | Line 68: `const event = JSON.parse(p.event || "{}")`. Followed by tier extractions on `event.i3`, `event.i4`, etc. |

#### Plan 01-03 Key Links

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `docs/for-ai-assistants/CLAUDE.md` | `market_analysis_service.py` | Updated service references | WIRED | Lines 77 and 129 reference `market_analysis_service.py`. Zero references to `intelligence_processor_service`. |
| `.claude/skills/wire-pipeline/SKILL.md` | `market_analysis_service.py` | Step 1 tier list instruction updated | WIRED | Confirmed 0 matches for `intelligence_processor_service` in `.claude/` skill files. `market_analysis_service` is referenced per 01-03 SUMMARY. |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| BUS-01 | 01-01 | System defines `IntelligenceEvent` Pydantic model with tiered JSONB structure (i1/i3/i4/i5/smc/i6), version field, and `platform` dimension | SATISFIED | `src/intelligence/schemas.py` exists with all 7 sub-models, `schema_version: Literal["1.0"]`, `platform: str = "futures"`. Pydantic v2 `BaseModel`. `extra="forbid"` on I3/I4/I5/SMC/I6, `extra="allow"` on I1. |
| BUS-02 | 01-01 | `market_analysis_service.py` publishes `IntelligenceEvent` to `intelligence:SYMBOL:TF` stream replacing flat k/v strings | SATISFIED | `_publish_intelligence()` constructs `IntelligenceEvent`, emits `{"event": model_dump_json()}`. Single field replaces ~50 flat string k/v pairs. |
| BUS-03 | 01-02 | All downstream consumers (signal_generator, API, ML) deserialize `IntelligenceEvent` instead of raw field dicts | SATISFIED | `signal_generator_service.py` and `signal_orchestrator_service.py` both use `_parse_intelligence_event()` with `model_validate_json()`. `parse_intelligence_message()` absent from both. Dashboard parses `p.event` as JSON. SSE route relays without flat-field access. `ai_narrative_service.py` confirmed non-consumer (reads `signals:` stream). |
| BUS-04 | 01-03 | `intelligence_processor_service.py` deprecated and removed; `market_analysis_service.py` is sole canonical pipeline | SATISFIED | Service file deleted. 3 test files deleted. Config deleted. 0 references in `services/`, `tests/`, `src/` on main branch. Worktree references are separate git branches (out of scope). |

All 4 requirement IDs from REQUIREMENTS.md are accounted for. No orphaned requirements detected.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `services/market_analysis_service.py` | 293 | `return {}` | INFO | Legitimate early-exit: insufficient bar history for pipeline run. Not a stub. |
| `services/signal_generator_service.py` | 117 | `return []` | INFO | Legitimate early-exit: no ranked signals in `AggregatedResult`. Not a stub. |
| `services/signal_orchestrator_service.py` | 146 | `return []` | INFO | Same as above — not a stub. |

No blocker or warning anti-patterns found. All `return {}` / `return []` patterns are documented early-exits with meaningful guard conditions, not placeholder stubs.

---

### Schema Validation Spot-Checks

Programmatic verification via `.venv/bin/python`:

```
schema import OK                        # all 8 classes importable
OK: I3Structure rejects extra fields    # extra="forbid" enforced
OK: I4Context rejects extra fields      # extra="forbid" enforced
schema_version default: 1.0
platform default: futures
source default: live
```

---

### Human Verification Required

#### 1. Live stream format confirmation

**Test:** With Dragonfly running, start `market_analysis_service.py` and let it process one bar. Read the resulting `intelligence:ES:1m` stream entry via `redis-cli XREAD COUNT 1 STREAMS intelligence:ES:1m 0`.
**Expected:** A single field key `event` containing a JSON string with `"schema_version":"1.0"`, `"platform":"futures"`, and nested `i3`/`i4`/`i5`/`smc`/`i6` objects — not 50+ flat keys like `garch_sigma`, `trend_regime`.
**Why human:** Requires live Redis + running service; unit tests mock the Redis xadd call.

#### 2. Dashboard intelligence tile rendering

**Test:** Open the dashboard while `market_analysis_service.py` is publishing. Observe the intelligence panel tiles for at least one symbol/timeframe.
**Expected:** Non-null values appear for regime indicators (vol_regime, garch_sigma), structure (nearest_support, trend_strength), SMC (bos_detected), and CTF score within 1-2 bar cycles.
**Why human:** Requires live browser + SSE connection + running services; the full `parseIntelligence()` → React state → render chain cannot be verified programmatically.

---

### Gaps Summary

No gaps. All 5 observable truths are verified, all artifacts exist and are substantive, all key links are wired, all 4 requirement IDs are satisfied. The two human verification items are runtime/browser confirmations of already-verified code paths — they do not constitute blocking gaps.

---

_Verified: 2026-02-23T10:15:00Z_
_Verifier: Claude (gsd-verifier)_
