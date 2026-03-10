---
phase: 17-llm-wiring-fix
verified: 2026-03-06T16:00:00Z
status: passed
score: 8/8 must-haves verified
re_verification: false
---

# Phase 17: LLM Wiring Fix Verification Report

**Phase Goal:** Fix signal_id linkage (signals:aggregated missing UUID) and regime vocabulary mismatch (plugin vocab vs cache keys) — closes LLM-04/LLM-05 production breaks, restores E2E Flow 3 + Flow 4
**Verified:** 2026-03-06T16:00:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SessionExtremesSetup emits 'session_extreme_london' when london=1.0, ny=0.0 | VERIFIED | `regime_ctx = f"session_extreme_{session_ctx}"` at line 139; TestRegimeVocabulary::test_regime_context_london PASSED |
| 2 | SessionExtremesSetup emits 'session_extreme_ny' when london=0.0, ny=1.0 | VERIFIED | Same line 139 branch; TestRegimeVocabulary::test_regime_context_ny PASSED |
| 3 | SessionExtremesSetup emits 'session_extreme_both' when london=1.0, ny=1.0 | VERIFIED | TestRegimeVocabulary::test_regime_context_overlap_both PASSED |
| 4 | The session label (session:london / session:ny / session:both) appears in supporting_factors | VERIFIED | `supporting.append(f"session:{session_ctx}")` at line 140; 3 supporting_factors tests PASSED |
| 5 | regime_context never contains bare 'london', 'ny', or 'both' strings | VERIFIED | `grep '"london"\|"ny"\|"both"' session_extremes_setup.py` returns only internal `session_ctx` variable assignment lines (133-137), not the return dict — `regime_context` key at line 152 uses `regime_ctx` |
| 6 | signal_id UUID from winning LedgerEntry appears in signals:aggregated stream message | VERIFIED | `message["signal_id"] = selected_entry.signal_id if selected_entry else ""` at line 685; test_build_ledger_entries_winning_entry_has_signal_id PASSED |
| 7 | parse_aggregated_signal() returns the signal_id field from the stream | VERIFIED | `"signal_id": _get("signal_id")` at line 156 in ai_narrative_service; test_parse_aggregated_signal_includes_signal_id + _empty_when_missing PASSED |
| 8 | _build_llm_call_payload() uses signal_data['signal_id'] instead of hardcoded empty string | VERIFIED | `"signal_id": str(sd.get("signal_id", ""))` at line 212; test_build_llm_call_payload_uses_signal_id_from_signal_data PASSED |

**Score:** 8/8 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/intelligence/trading/session_extremes_setup.py` | Corrected regime_context vocabulary; `session_extreme_` pattern | VERIFIED | Line 139: `regime_ctx = f"session_extreme_{session_ctx}"`; line 140: `supporting.append(f"session:{session_ctx}")`; line 152: return dict uses `regime_ctx` |
| `tests/unit/intelligence/trading/test_session_extremes_setup.py` | Updated + new tests covering all 3 session regime strings and supporting_factors | VERIFIED | TestRegimeVocabulary class with 6 new tests; 4 existing tests updated; all 33 tests PASSED |
| `services/signal_generator_service.py` | signal_id injection + stream-first ordering; `selected_entry.signal_id` pattern | VERIFIED | Line 685: injection; lines 686-688: xadd; lines 691-702: DB insert second |
| `services/ai_narrative_service.py` | signal_id extracted + passed through; `sd.get("signal_id"` pattern | VERIFIED | Line 156: parse return dict; line 212: payload builder |
| `tests/unit/service_tests/test_signal_generator_service.py` | signal_id threading test | VERIFIED | test_build_ledger_entries_winning_entry_has_signal_id PASSED |
| `tests/unit/service_tests/test_ai_narrative_helpers.py` | signal_id passthrough tests for parse + payload builder | VERIFIED | 4 new tests all PASSED |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `session_extremes_setup.compute_full()` | `llm_calls.regime` | `regime_context` field stored verbatim; pattern `session_extreme_(london\|ny\|both)` | WIRED | Line 139 sets `regime_ctx`; line 152 assigns to `"regime_context"` in return dict |
| `signal_generator_service._process_bar()` | `signals:aggregated stream message` | `selected_entry = next(...was_selected...); message['signal_id'] = selected_entry.signal_id` | WIRED | Lines 684-685: injection before xadd at line 686 |
| `ai_narrative_service.parse_aggregated_signal()` | `_build_llm_call_payload()` | `signal_data['signal_id']` from parse result; pattern `sd.get("signal_id"` | WIRED | Line 156 extracts; line 212 uses `sd.get("signal_id", "")` |
| `_build_llm_call_payload()` | `llm_calls:stream message` | `"signal_id"` key in payload consumed by `llm_writer_service._parse_llm_call_fields` | WIRED | Line 212 confirmed present; stale comment "not in aggregated stream" removed |
| stream xadd | insert_signals DB call | execution order: xadd at line 686 precedes insert_signals at line 693 | WIRED | DB INSERT block (lines 690-702) starts after stream block ends at line 688 |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| LLM-04 | 17-02-PLAN.md | New llm_writer_service batch INSERTs from llm_calls:stream; back-fills outcome fields by signal_id; recomputes llm_model_scores | SATISFIED | signal_id now threaded through stream → ai_narrative_service → llm_calls payload; WHERE signal_id = $1::uuid will now match rows; enabling the back-fill loop |
| LLM-05 | 17-01-PLAN.md | ai_narrative_service reads Redis score cache; moves is_significant model to position 0 for matching call_type + regime | SATISFIED | SessionExtremesSetup now emits `session_extreme_*` regime strings that match the routing vocab; score accumulation keys are now reachable by `_apply_score_routing()` |

**No orphaned requirements:** REQUIREMENTS.md maps only LLM-04 and LLM-05 to Phase 17, both accounted for.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `services/ai_narrative_service.py` | 224, 229-231 | `# not in aggregated stream` comments on `session`, `cis_score`, `entry_zone_low/high` fields | Info | These comments are on different fields (not `signal_id`); the plan only required removing the comment from the `signal_id` line. The remaining comments are accurate for those fields. |

No blocker or warning anti-patterns found. The surviving comments at lines 224/229-231 correctly document that `session`, `cis_score`, and zone fields are not in the aggregated stream — this is true and the plan did not scope their removal.

---

### Human Verification Required

#### 1. E2E Flow 3 — signal_id lands in llm_calls DB row

**Test:** Observe a live signal fire in logs (`journalctl -u indicagent-signal-generator -f`). Query `signal_ledger` for the signal_id. Then query `llm_calls` for a row with that signal_id after `ai_narrative_service` processes it.
**Expected:** `SELECT signal_id FROM llm_calls WHERE signal_id = '<uuid>'` returns 1 row with the UUID, not NULL.
**Why human:** Requires live IBKR data feed, running services, and a signal to fire naturally — cannot simulate end-to-end in unit tests.

#### 2. E2E Flow 4 — outcome back-fill WHERE clause matches rows

**Test:** After a signal closes (outcome recorded in `signal_ledger`), check `llm_calls` for the same signal_id to confirm the outcome field was back-filled.
**Expected:** `SELECT outcome FROM llm_calls WHERE signal_id = '<uuid>'` returns a non-NULL outcome string.
**Why human:** Requires a complete signal lifecycle (activation + exit) in a live environment plus the llm_writer_service back-fill cycle running.

#### 3. Adaptive routing activation check

**Test:** After 30+ SessionExtremesSetup signals accumulate in `llm_calls` under a `session_extreme_*` regime key, check that `ai_narrative_service._apply_score_routing()` promotes a model for that key.
**Expected:** Log or Redis score cache shows a model promoted to position 0 for `session_extreme_london` / `session_extreme_ny` / `session_extreme_both`.
**Why human:** Requires statistical accumulation of 30+ outcome-linked rows per regime key — cannot be fast-tracked in unit tests.

---

### Gaps Summary

No gaps. All 8 observable truths verified against the actual codebase. Both requirement IDs satisfied with direct code evidence. All commits verified in git history (f7fe7a7, 5f764ad, 4a355ae). Full unit suite: 1195 passing, 0 failures. Ruff: 0 errors.

The three human verification items are end-to-end runtime behaviors that cannot be verified statically — they represent the intended production outcomes that this phase unblocks, not defects in the implementation.

---

## Test Suite Summary

| Suite | Result |
|-------|--------|
| `tests/unit/intelligence/trading/test_session_extremes_setup.py` | 33/33 PASSED |
| `tests/unit/service_tests/test_ai_narrative_helpers.py` | 8/8 PASSED (4 new) |
| `tests/unit/service_tests/test_signal_generator_service.py` | 29/29 PASSED (1 new) |
| Full `tests/unit/` | 1195 PASSED, 0 failed |
| Ruff | 0 errors |

## Commits Verified

| Hash | Description |
|------|-------------|
| `f7fe7a7` | feat(17-01): fix SessionExtremesSetup regime_context vocabulary for LLM routing |
| `5f764ad` | test(17-02): add failing tests for signal_id threading |
| `4a355ae` | feat(17-02): thread signal_id through aggregated stream into llm_calls |

---

_Verified: 2026-03-06T16:00:00Z_
_Verifier: Claude (gsd-verifier)_
