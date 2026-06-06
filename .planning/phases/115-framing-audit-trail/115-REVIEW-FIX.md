---
phase: 115-framing-audit-trail
fixed_at: 2026-06-05T14:35:00Z
review_path: .planning/phases/115-framing-audit-trail/115-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 5
skipped: 0
status: all_fixed
---

# Phase 115: Code Review Fix Report

**Fixed at:** 2026-06-05T14:35:00Z
**Source review:** .planning/phases/115-framing-audit-trail/115-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 5 (1 Critical, 4 Warnings)
- Fixed: 5
- Skipped: 0

## Fixed Issues

### CR-01: `stop_structure_age_bars` computed but never persisted

**Files modified:** `src/intelligence/trading/signal_schema.py`, `src/persistence/repository/signal_ledger_repository.py`, `services/signal_writer.py`
**Commit:** 38238809
**Applied fix:**
- Added `sig["stop_structure_age_bars"] = tf.stop_structure_age_bars` to `make_signal_from_frame()` in `signal_schema.py`
- Added `stop_structure_age_bars: int | None = None` field to `LedgerEntry` dataclass
- Added `self.stop_structure_age_bars` as `$34` in `_to_row()`
- Added `stop_structure_age_bars` to `_INSERT_SQL` column list and VALUES (`$34`)
- Added `stop_structure_age_bars=sig.get("stop_structure_age_bars")` in `_payload_to_ledger_entries()`

### WR-01: Emission Gate 2 (`stop_type == "unknown"`) is dead code

**Files modified:** `src/intelligence/trading/signal_schema.py`
**Commit:** 38238809
**Applied fix:** Replaced the unreachable `raise ValueError` gate with an `assert` that documents the invariant. `frame_trade()` always resolves a stop_type with "atr" as fallback — "unknown" never occurs in production. The assert makes the invariant explicit rather than silently dead.

### WR-02: `ema_21_support` / `ema_21_resistance` absent from `_stop_type_to_structure_type` map

**Files modified:** `src/intelligence/trading/trade_framer.py`
**Commit:** 61548ce8
**Applied fix:** Added `"ema_21_support": "ema_21_support"` and `"ema_21_resistance": "ema_21_resistance"` entries to `_MAP` in `_stop_type_to_structure_type()`. These stop types are returned by `_resolve_stop_long/short()` at priority 4b but were missing from the map, causing them to fall through to `"atr_fallback"` as the `stop_structure_type` label.

### WR-03: `LedgerEntry.stop_type` field name vs `stop_type_col` DB column silent mismatch

**Files modified:** `src/persistence/repository/signal_ledger_repository.py`, `services/signal_writer.py`
**Commit:** 38238809
**Applied fix:** Renamed `LedgerEntry.stop_type` to `LedgerEntry.stop_type_col` to match the DB column name exactly. Updated `_to_row()` comment and `signal_writer.py` `_payload_to_ledger_entries()` to use `stop_type_col=sig.get("stop_type")` (signal payload key is still "stop_type", DB column is "stop_type_col").

### WR-04: Test helper `_make_agent()` mocks stale `_consumer_lag` attribute

**Files modified:** `tests/unit/services/test_signal_writer.py`
**Commit:** 4f1de17b
**Applied fix:** Removed `agent._consumer_lag = MagicMock()` from `_make_agent()`. Added a comment explaining that the remaining OTel instrument mocks are needed because `__new__` bypasses `BaseWriter.__init__`.

---

**Post-fix test run:** `pytest tests/unit/ -q` — 4368 passed, 29 skipped, 0 failed.

Three tests required updates alongside the source fixes:
- `tests/unit/intelligence/test_signal_ledger.py`: 4 param count assertions updated 33 -> 34 (stop_structure_age_bars adds one param)
- `tests/unit/services/test_signal_writer.py`: `test_stop_type_extracted` updated for `stop_type_col` rename
- `tests/unit/intelligence/trading/test_signal_quality_hardening.py`: `test_rejects_unknown_stop_type` updated from `ValueError` to `AssertionError` (gate 2 is now an assert)

---

_Fixed: 2026-06-05T14:35:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
