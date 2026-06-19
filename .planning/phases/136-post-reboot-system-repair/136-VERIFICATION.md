---
phase: 136-post-reboot-system-repair
verified: 2026-06-19T03:00:00Z
status: passed
score: 14/14 must-haves verified
gaps: []
human_verification:
  - test: "Restart indicagent-intelligence-pipeline with Kafka idle and observe shutdown time"
    expected: "systemctl stop completes in under 5s; no SIGKILL in journalctl output"
    why_human: "Cannot verify real-time signal/async behavior without a live service and idle Kafka state"
---

# Phase 136: Post-Reboot System Repair Verification Report

**Phase Goal:** Repair the system after a server reboot - fix data integrity gaps, eliminate a known signal-quality defect, and restore production reliability.
**Verified:** 2026-06-19T03:00:00Z
**Status:** passed
**Re-verification:** No - initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Stop-correction error messages report a dimensionless ATR ratio, not a raw price distance | VERIFIED | `plugin_utils.py:189,226` interpolate `original_inside_distance / max(atr, _ATR_EPSILON)` |
| 2 | A zero-ATR bar in the stop-correction path raises ValueError, not ZeroDivisionError | VERIFIED | `_ATR_EPSILON = 1e-8` at `plugin_utils.py:106`; division guarded by `max(atr, _ATR_EPSILON)` |
| 3 | validate_signal returns a value whose truthiness is unchanged for all existing call sites | VERIFIED | `ValidationResult.__bool__` at `signal_schema.py:91` delegates to `.valid` |
| 4 | executor.schema_violation log events include a reason field naming the failure class | VERIFIED | `executor.py:905` logs `reason=result.reason`; result bound at line 898 |
| 5 | FVGFill no longer participates in the I7 trade-signal tier | VERIFIED | `register_plugins.py:642` shows restoration comment; Python import assert passes; TIER_I7 count = 35 |
| 6 | SMC-tier FVG detection (fvg_type/fvg_top/fvg_bottom features) remains active | VERIFIED | Import at line 117 and `register_pattern` at line 410 both retained |
| 7 | SIGTERM to intelligence_pipeline unblocks the Kafka async-for loop even when no messages are flowing | VERIFIED (code) | `_register_signal_handlers` override at `intelligence_pipeline.py:642` schedules `_shutdown_consumer()` which calls `await self._kafka_consumer.stop()` at line 657 |
| 8 | An in-flight stop signal halts the message loop before processing the next message | VERIFIED | Inner stop-check `if not self.running: break` at `intelligence_pipeline.py:702` |
| 9 | feature_writer crashes at startup with a RuntimeError naming the missing column when a Phase-130 CTF column is absent | VERIFIED | `_verify_schema()` at `feature_writer.py:392`; raises `RuntimeError` naming `sorted(missing)` and "migration 130"; called in `_setup()` at line 411 before Kafka start |
| 10 | Live feature writes no longer duplicate CTF keys inside cross_timeframe_context JSONB | VERIFIED | `feature_writer.py:228` excludes `CTF_DEDICATED_COLUMNS` from `model_dump` |
| 11 | Replay writes no longer duplicate CTF keys inside cross_timeframe_context JSONB | VERIFIED | `run_historical_pipeline.py:750` applies identical `exclude=CTF_DEDICATED_COLUMNS` |
| 12 | Every signal_events row in the gap window has a matching intelligence_features row (zero orphans) | VERIFIED | DB query returns 0; 912 gap-window signal_events all matched post-replay |
| 13 | No duplicate intelligence_features rows exist for the gap window | VERIFIED | ON CONFLICT DO UPDATE guarantee; duplicate-detection query returned 0 |
| 14 | No intelligence_features row contains a ctf_score key inside cross_timeframe_context JSONB | VERIFIED | `SELECT COUNT(*) FROM intelligence_features WHERE cross_timeframe_context ? 'ctf_score'` returns 0 |

**Score:** 14/14 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/intelligence/trading/plugin_utils.py` | ATR epsilon guard + ratio error strings | VERIFIED | `_ATR_EPSILON = 1e-8` at line 106; 2 ratio interpolations at lines 189, 226 |
| `src/intelligence/trading/signal_schema.py` | ValidationResult NamedTuple + validate_signal returning it | VERIFIED | `class ValidationResult(NamedTuple)` at line 80; `__bool__` at line 91; all 8 failure literals present |
| `src/intelligence/register_plugins.py` | TIER_I7 without fvg_fill_plugin.name; restoration comment | VERIFIED | Comment at line 642; import and register_pattern retained at lines 117, 410; TIER_I7 len=35 |
| `services/intelligence_pipeline.py` | _register_signal_handlers override + inner stop-check | VERIFIED | Override at line 642; `await self._kafka_consumer.stop()` at lines 635, 657; inner break at line 702 |
| `production/systemd/indicagent-intelligence-pipeline.service` | TimeoutStopSec=90 | VERIFIED | Line 23 confirmed |
| `services/feature_writer.py` | _verify_schema() pre-flight + CTF exclusion | VERIFIED | `_verify_schema` at line 392; `_REQUIRED_COLUMNS` at line 56; `table_schema = 'public'` at line 69; exclude at line 228 |
| `production/scripts/run_historical_pipeline.py` | CTF key exclusion | VERIFIED | `exclude=CTF_DEDICATED_COLUMNS` at line 750 |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `signal_schema.py ValidationResult.__bool__` | all `if validate_signal(sig):` call sites | `__bool__` delegates to `.valid` | WIRED | `def __bool__` returns `self.valid`; executor binds result before conditional |
| `executor.py` | `validate_signal ValidationResult.reason` | `result = validate_signal(sig); log reason=result.reason` | WIRED | Lines 898 + 905 confirmed |
| `register_plugins.py TIER_I7` | shadow_registry auto-enroll loop | fvg_fill absent from TIER_I7 | WIRED | Python runtime assertion passes; count = 35 |
| `intelligence_pipeline.py _register_signal_handlers()` | `self._kafka_consumer.messages()` async generator | `await self._kafka_consumer.stop()` causes StopAsyncIteration | WIRED | Stop call at line 657 inside scheduled async task |
| `feature_writer.py _setup()` | `_verify_schema()` before Kafka start | called after `_connect_database()`, before `_setup_kafka_clients()` | WIRED | Line 411 ordering confirmed |
| `feature_writer.py cross_timeframe_context build` | `intelligence_features.cross_timeframe_context` JSONB | `model_dump(exclude=CTF_DEDICATED_COLUMNS)` | WIRED | Line 228 confirmed; DB query returns 0 rows with the key |
| `Migration 130 Statement 3 UPDATE` | `intelligence_features.cross_timeframe_context` | JSONB key-subtraction WHERE `ctf_score` present | WIRED | Executed; idempotent; count = 0 post-run |

### Requirements Coverage

No phase-specific requirements mapped in REQUIREMENTS.md for Phase 136.

### Anti-Patterns Found

None. No TODO/FIXME/placeholder comments found in modified files. No stub implementations detected. All code paths substantive.

### Notable Deviations (Not Blocking)

Two observations documented in Plan 05/06 summaries that do not block goal achievement:

1. **ctf_score top-level column NULL table-wide** - The replay script (`_event_to_sync_params`) never populated the 4 dedicated CTF top-level columns added by Phase 130. This is a pre-existing design gap in the replay script, not a regression from Phase 136. Signals read ctf_score from `signal_events.ctf_score` at fire time, not from `intelligence_features`. Deferred to `deferred-items.md`.

2. **Baseline orphan count was 0** - The intelligence_pipeline caught up via Kafka replay after services restarted post-reboot, so gap-window features were already written before Plan 05 ran. Replay ran anyway with `--overwrite-features` to refresh rows with the clean CTF-excluded write path. Primary objective (zero orphans) met either way.

### Human Verification Required

**1. Graceful SIGTERM Shutdown (Operational)**

**Test:** With `indicagent-intelligence-pipeline` running and Kafka idle, run `systemctl stop indicagent-intelligence-pipeline` and observe duration.
**Expected:** Stops within 5 seconds; no SIGKILL line in `journalctl -u indicagent-intelligence-pipeline`; consumer resumes from correct offset on restart.
**Why human:** Cannot verify real-time async signal/consumer behavior programmatically; requires a live service and idle Kafka state.

### Summary

All 14 must-have truths verified against the actual codebase and database. All 7 required artifacts exist, are substantive, and are properly wired. The phase goal - repair data integrity gaps, eliminate the FVGFill signal-quality defect, and restore production reliability - is achieved. One human verification item (graceful shutdown timing) cannot be verified programmatically.

---

_Verified: 2026-06-19T03:00:00Z_
_Verifier: Claude (gsd-verifier)_
