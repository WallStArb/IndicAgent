---
phase: 23-signal-generator-gate
verified: 2026-03-10T07:30:00Z
status: passed
score: 10/10 must-haves verified
re_verification: false
---

# Phase 23: Signal Generator Gate — Verification Report

**Phase Goal:** Fix signal generator to emit onset events (not persistent condition fires), add cross-bar memory with direction flip suppression, clean up dead InputSpec timeframe declarations, and make an explicit decision on 4h/1d processing scope.
**Verified:** 2026-03-10T07:30:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Signal generator publishes at most one signal per MIN_BARS_BETWEEN_SIGNALS bars per (symbol, tf) | VERIFIED | `_check_gate` returns True (suppress) when `bars_since < min_bars`; wired in `_process_bar` at line 762 |
| 2 | Direction flip is suppressed while prior signal is unresolved | VERIFIED | `_check_gate` returns True when `direction != gate["direction"] and not gate["resolved"]`; test `test_gate_flip_suppressed_while_unresolved` passes |
| 3 | Direction flip is allowed once a direction=0 lifecycle exit arrives on own stream | VERIFIED | `_resolution_listener_loop` sets `gate["resolved"] = True` on `direction=0`; test `test_gate_flip_allowed_after_resolution` passes |
| 4 | Gate state initializes to empty dict; first signal per (symbol, tf) always publishes | VERIFIED | `self._signal_gate: dict[tuple[str, str], dict] = {}` in `__init__` at line 383; `_check_gate` returns `False` when `gate is None`; test `test_gate_first_signal_always_publishes` passes |
| 5 | Service reads own signals:SYMBOL:TF:aggregated stream to detect resolution events | VERIFIED | `_resolution_listener_loop` uses `xread` with `last_ids` starting at `"$"`, launched as `asyncio.create_task` in `start()` at line 1043 |
| 6 | All 17 I7 plugins have InputSpec(timeframe='.*') instead of timeframe='1m' | VERIFIED | `grep timeframe="1m"` in `src/intelligence/trading/` returns zero matches; 17 files confirmed with `timeframe=".*"` (fvg_fill.py has 2 hits — one in comment, one in InputSpec) |
| 7 | Both services have explicit comment documenting 4h/1d intentional exclusion | VERIFIED | Comment "4h and 1d intentionally excluded: day-trading focus…" present in `market_analysis_service.py` (line 153) and `signal_generator_service.py` (line 437) |
| 8 | fvg_fill.py carries canonical explanation comment for timeframe='.*' | VERIFIED | Two-line comment at lines 35-36 explaining InputSpec.timeframe is not enforced by registry or service |
| 9 | All 5 gate tests pass (GREEN) | VERIFIED | `pytest -k gate` shows 5 passed; full suite 1430/1430 passing |
| 10 | No new ruff errors beyond pre-existing E501 baseline | VERIFIED | Only error beyond E501 is pre-existing in `cis_scorer.py` (not a phase 23 file); E501 on `_update_gate` signature is documented as accepted in 23-02 decisions |

**Score:** 10/10 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `services/signal_generator_service.py` | `_signal_gate` dict, `_check_gate`, `_update_gate`, resolution listener | VERIFIED | All four present; gate wired in `_process_bar` before stream publish; listener launched as asyncio task |
| `services/signal_generator_service.py` | `MIN_BARS_BETWEEN_SIGNALS` and `TF_SECONDS` module-level constants | VERIFIED | Lines 68-70; `{"1m": 3, "5m": 2, "15m": 2, "1h": 2}` and `{"1m": 60, "5m": 300, "15m": 900, "1h": 3600}` |
| `tests/unit/service_tests/test_signal_generator_service.py` | 5 gate test functions under `# Signal gate` section | VERIFIED | 5 tests present and all passing; `__new__` bypass pattern with manual `_signal_gate` dict seeding |
| `src/intelligence/trading/fvg_fill.py` | `InputSpec(timeframe=".*")` (representative for all 17 plugins) | VERIFIED | `timeframe=".*"` confirmed; canonical explanation comment present at lines 35-36 |
| `services/market_analysis_service.py` | Explicit 4h/1d exclusion comment | VERIFIED | Comment at line 153 |
| `services/signal_generator_service.py` | Explicit 4h/1d exclusion comment | VERIFIED | Comment at line 437 |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `_process_bar` | `_check_gate` | called before stream publish; returns bool (True=suppress) | WIRED | Line 762: `if self._check_gate(symbol, timeframe, _direction, timestamp):` inside outer `if result.selected_signal:` guard |
| `_process_bar` | `_update_gate` | called after successful xadd, guarded with `if result.selected_signal:` | WIRED | Lines 843-846: `if stream_entry_id and result.selected_signal:` then `self._update_gate(...)` |
| `start()` | `_resolution_listener_loop` | `asyncio.create_task` at service startup | WIRED | Line 1043: `asyncio.create_task(self._resolution_listener_loop())` alongside other background tasks |
| I7 plugins (17 files) | `InputSpec` | `InputSpec(symbol=".*", timeframe=".*", lookback=N)` | WIRED | All 17 files confirmed; zero `timeframe="1m"` matches remaining in `src/intelligence/trading/` |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| gate-init | 23-01, 23-02 | Gate state initialized; first signal always publishes | SATISFIED | `_signal_gate = {}` in `__init__`; `_check_gate` returns False for missing gate entry |
| gate-cooldown | 23-01, 23-02 | Bars-since-last-signal cooldown suppression | SATISFIED | `bars_since < min_bars` check in `_check_gate`; two cooldown tests passing |
| gate-flip-suppressed | 23-01, 23-02 | Flip suppressed while prior signal unresolved | SATISFIED | `direction != gate["direction"] and not gate["resolved"]` check; test passing |
| gate-flip-allowed | 23-01, 23-02 | Flip allowed after direction=0 resolution event | SATISFIED | `_resolution_listener_loop` sets `resolved=True` on `direction=0`; test passing |
| inputspec-cleanup | 23-03 | Remove misleading `timeframe="1m"` from all 17 I7 plugins | SATISFIED | Zero `timeframe="1m"` matches in trading dir; 17 files with `".*"` |
| 4h-1d-exclusion | 23-03 | Explicit comment in both services documenting day-trading scope | SATISFIED | Comment present in both service `_load_config()` sections |

---

### Anti-Patterns Found

None detected. Scan of phase 23 modified files:

- No `TODO/FIXME/PLACEHOLDER` comments introduced
- No stub `return null` / `return {}` patterns
- Gate suppression correctly produces `AggregatedResult(selected_signal=None, resolution_method="gate_suppressed")` — same pattern as existing `rr_filtered` path, not a placeholder
- `_resolution_listener_loop` has full implementation: stream subscription, cursor advancement, field extraction, gate mutation — not a stub

---

### Human Verification Required

The following behavior cannot be verified statically and should be observed in a live run:

#### 1. Gate suppresses condition re-fires in production

**Test:** Observe `journalctl -u indicagent-signal-generator -f` during a live session. When a signal fires for a given (symbol, tf), confirm that the same setup does not emit a second signal on the next 1-3 bars while the condition persists.
**Expected:** Debug log line `"Signal gated"` visible when a signal would have fired within the cooldown window; no duplicate signals in `signal_ledger` within 3 bars of each other on 1m.
**Why human:** Requires live market data and a condition that persists across multiple bars to trigger the gate path.

#### 2. Resolution listener clears gate after lifecycle exit

**Test:** After a signal activates and exits via `signal_lifecycle_service`, observe that a direction flip fires on the next bar rather than being suppressed.
**Expected:** `"Gate resolved"` debug log appears after lifecycle publishes `direction=0`; next opposing signal publishes without gate suppression log.
**Why human:** Requires a full lifecycle cycle (activation → exit) which takes minutes to hours in live trading.

These are observability checks, not functional gaps. All automated verification passes.

---

### Gaps Summary

None. All phase 23 goals are achieved:

1. **Onset-only publishing** — gate cooldown prevents same condition re-firing every bar
2. **Cross-bar memory** — `_signal_gate` dict persists direction/timestamp/resolved state across bars
3. **Direction flip suppression** — `_check_gate` blocks flip while `resolved == False`
4. **Resolution detection** — `_resolution_listener_loop` clears gate on `direction=0` lifecycle exit
5. **InputSpec cleanup** — 17 plugin files updated; zero `timeframe="1m"` dead declarations remain
6. **4h/1d explicit decision** — documented as intentional day-trading scope exclusion in both service configs

All 8 documented commits exist and are reachable. 1430/1430 unit tests passing. No new ruff errors.

---

_Verified: 2026-03-10T07:30:00Z_
_Verifier: Claude (gsd-verifier)_
