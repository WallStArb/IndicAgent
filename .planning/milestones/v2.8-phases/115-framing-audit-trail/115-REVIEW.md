---
phase: 115-framing-audit-trail
reviewed: 2026-06-05T00:00:00Z
depth: standard
files_reviewed: 38
files_reviewed_list:
  - production/migrations/119_framing_audit_trail.sql
  - services/signal_writer.py
  - src/intelligence/trading/anchored_vwap_reversion.py
  - src/intelligence/trading/choch_reversal.py
  - src/intelligence/trading/cross_asset_divergence.py
  - src/intelligence/trading/cvd_divergence.py
  - src/intelligence/trading/cvd_spike.py
  - src/intelligence/trading/delta_exhaustion.py
  - src/intelligence/trading/divergence_stack.py
  - src/intelligence/trading/dual_divergence.py
  - src/intelligence/trading/failed_breakout.py
  - src/intelligence/trading/fvg_fill.py
  - src/intelligence/trading/hvn_rejection.py
  - src/intelligence/trading/lvn_breakout.py
  - src/intelligence/trading/mean_reversion.py
  - src/intelligence/trading/microstructure_utils.py
  - src/intelligence/trading/mtf_alignment.py
  - src/intelligence/trading/ofi_continuation.py
  - src/intelligence/trading/ofi_divergence.py
  - src/intelligence/trading/ofi_spike.py
  - src/intelligence/trading/orb15.py
  - src/intelligence/trading/orb30.py
  - src/intelligence/trading/pattern_completion.py
  - src/intelligence/trading/poc_rejection.py
  - src/intelligence/trading/prev_day_level_test.py
  - src/intelligence/trading/regime_transition.py
  - src/intelligence/trading/second_leg_continuation.py
  - src/intelligence/trading/signal_schema.py
  - src/intelligence/trading/trade_framer.py
  - src/intelligence/trading/trend_following.py
  - src/intelligence/trading/vcp.py
  - src/intelligence/trading/vwap_reclaim.py
  - src/observability/metrics.py
  - src/persistence/repository/signal_ledger_repository.py
  - tests/unit/intelligence/test_signal_ledger.py
  - tests/unit/intelligence/test_signal_schema.py
  - tests/unit/intelligence/test_trade_framer.py
  - tests/unit/services/test_signal_writer.py
findings:
  critical: 1
  warning: 4
  info: 3
  total: 8
status: issues_found
---

# Phase 115: Framing Audit Trail - Code Review Report

**Reviewed:** 2026-06-05
**Depth:** standard
**Files Reviewed:** 38
**Status:** issues_found

## Summary

Phase 115 adds five framing audit columns (`stop_basis`, `stop_type_col`, `structural_stop_distance_atr`, `adaptive_buffer_mult`, `plugin_regime_type`) to `signal_ledger`, rewires `frame_trade()` to classify stop basis and capture the adaptive buffer multiplier at signal fire time, and threads those fields all the way through `make_signal_from_frame` -> signal Kafka payload -> `signal_writer` -> `LedgerEntry` -> `_INSERT_SQL`.

The core data flow is structurally sound. All 26 I7 plugins correctly pass `regime_type=self.regime_type` to `frame_trade()`. The positional SQL mapping is correct: `LedgerEntry.stop_type` (Python field name) maps positionally to `stop_type_col` (DB column name) at `$30`.

One critical defect found: `stop_structure_age_bars` has been computed in `frame_trade()` and stored in `TradeFrame` since migration 035, but is never included in `LedgerEntry` or `_INSERT_SQL`. Phase 115 adds the other four framing audit fields but silently skips this one, leaving the DB column permanently NULL. Additionally there are four quality/maintainability findings detailed below.

---

## Critical Issues

### CR-01: `stop_structure_age_bars` computed but never persisted - DB column always NULL

**File:** `src/intelligence/trading/trade_framer.py:1087`, `src/persistence/repository/signal_ledger_repository.py:139`

**Issue:** `frame_trade()` computes `stop_structure_age_bars` via `_get_structure_age_bars()` and stores it in `TradeFrame.stop_structure_age_bars` (line 1105). Migration 035 added the matching `stop_structure_age_bars INTEGER` column to `signal_ledger`. Phase 115 adds four of the five planned framing audit fields to `LedgerEntry` and `_INSERT_SQL` but omits `stop_structure_age_bars` entirely. The computed value is discarded after every `frame_trade()` call. The DB column is always NULL for every signal ever written, making it useless for the segmentation analysis it was designed for.

**Fix:** Add `stop_structure_age_bars` to `LedgerEntry`, `_to_row()`, and `_INSERT_SQL`:

```python
# LedgerEntry (signal_ledger_repository.py) — add after plugin_regime_type:
stop_structure_age_bars: int | None = None
```

```python
# _to_row() tuple — add as $34:
self.stop_structure_age_bars,  # $34
```

```sql
-- _INSERT_SQL column list (add after plugin_regime_type):
stop_basis, stop_type_col, structural_stop_distance_atr,
adaptive_buffer_mult, plugin_regime_type, stop_structure_age_bars

-- VALUES:
$29, $30, $31,
$32, $33, $34
```

```python
# signal_writer.py _payload_to_ledger_entries — read from signal:
stop_structure_age_bars=sig.get("stop_structure_age_bars"),
```

```python
# signal_schema.py make_signal_from_frame — add after adaptive_buffer_mult line:
sig["stop_structure_age_bars"] = tf.stop_structure_age_bars
```

---

## Warnings

### WR-01: Emission Gate 2 (`stop_type == "unknown"`) is dead code

**File:** `src/intelligence/trading/signal_schema.py:243-245`

**Issue:** `make_signal_from_frame()` gate 2 rejects frames where `tf.stop_type == "unknown"`. However, `_resolve_stop_long()` and `_resolve_stop_short()` in `trade_framer.py` never return `"unknown"` as a stop type - the exhaustive priority ladder terminates in an `"atr"` fallback. The gate condition is structurally unreachable. Any future developer reading this gate may believe it catches real production cases and write tests against it or depend on it as documentation.

**Fix:** Remove the gate or replace it with a comment clarifying the invariant:
```python
# Gate 2: stop_type is always set by frame_trade() - "atr" is the fallback, "unknown" never occurs.
# This guard is defensive documentation only.
assert tf.stop_type != "unknown", "frame_trade() must always resolve a stop_type"
```
Or simply remove lines 243-245 entirely, since `frame_trade()` is the sole call path and its output is guaranteed.

---

### WR-02: `ema_21_support` / `ema_21_resistance` stop types absent from `_stop_type_to_structure_type` map

**File:** `src/intelligence/trading/trade_framer.py:194-209`

**Issue:** `_resolve_stop_long()` and `_resolve_stop_short()` can return stop types `"ema_21_support"` and `"ema_21_resistance"` (lines 542, 611) as priority 4b structural stops. These are not present in `_stop_type_to_structure_type._MAP`, so they silently fall through to `"atr_fallback"` as their `stop_structure_type` label in `TradeFrame`. Although `stop_structure_type` is not persisted to the DB (only `stop_type_col` which gets the correct raw value), this mismatch corrupts the in-process `TradeFrame.stop_structure_type` field and could mislead any future code that reads it.

**Fix:** Add the missing entries to `_MAP`:
```python
_MAP = {
    ...
    "ema_21_support": "ema_21_support",
    "ema_21_resistance": "ema_21_resistance",
}
```

---

### WR-03: `LedgerEntry.stop_type` Python field name vs `stop_type_col` DB column name — silent naming mismatch

**File:** `src/persistence/repository/signal_ledger_repository.py:90`, `src/persistence/repository/signal_ledger_repository.py:128`

**Issue:** The `LedgerEntry` dataclass field is named `stop_type` (line 90) but the corresponding DB column is `stop_type_col` (migration 119, line 7). The mapping is correct only because `_to_row()` uses positional parameters (the Python field value at index 29 maps to `$30` in `_INSERT_SQL` which names the `stop_type_col` column). Any future refactor that adds non-positional DB access (e.g. named parameters, ORM, direct column reference by name) would silently map `stop_type` to the wrong column. The `_SELECT_ACTIVE_COLS` query does not select `stop_type_col` at all, so reads don't see this field.

**Fix:** Rename the `LedgerEntry` field to match the DB column to eliminate the silent mismatch:
```python
# Before:
stop_type: str | None = None

# After:
stop_type_col: str | None = None
```
Update all references in `signal_writer.py` (`stop_type_col=sig.get("stop_type")`) and `_to_row()` comment.

---

### WR-04: Test helper `_make_agent()` mocks attributes absent from `SignalWriter`

**File:** `tests/unit/services/test_signal_writer.py:37-44`

**Issue:** The test agent construction at lines 37-44 sets `agent._consumer_lag`, `agent._buffer_depth_gauge`, `agent._buffer_overflow_total`, `agent._flush_latency`, `agent._commit_latency`, `agent._parse_failures_total`, `agent._flush_errors_total`, and `agent._commit_errors_total` as `MagicMock()` instances. `SignalWriter` does not declare `_consumer_lag` — it was removed from the class. The other seven attributes ARE legitimately created by `BaseWriter.__init__`, but because `__new__()` bypasses `__init__`, the mocks replace real OTel instruments. If a refactor adds behavior conditioned on the real type of any of these (e.g. checking `.is_recording()`), the mocks will silently pass. More critically, `_consumer_lag` being mocked silently hides that the class no longer has that attribute, making the test appear to cover a code path that doesn't exist.

**Fix:** Remove `agent._consumer_lag` from `_make_agent()`. Document the remaining mock rationale (bypassing OTel init in unit tests). Consider asserting `not hasattr(agent_real_instance, "_consumer_lag")` to lock the contract.

---

## Info

### IN-01: `ADAPTIVE_BUFFER_HARD_CAP` (1.40) is structurally unreachable

**File:** `src/intelligence/trading/trade_framer.py:104`, `src/intelligence/trading/trade_framer.py:130`

**Issue:** The hard cap `min(result, base_mult * ADAPTIVE_BUFFER_HARD_CAP)` at line 130 with `ADAPTIVE_BUFFER_HARD_CAP = 1.40` can never be reached: the maximum GARCH multiplier at `vol_ratio=1.50` is `1.35`, and the shock floor also caps at `base_mult * 1.35`. The hard cap of `1.40` is always `> result` for any input. The constant creates an impression of a safety ceiling that doesn't actually constrain the computation, which can mislead future calibration work.

**Fix:** Either remove the cap (simplify the code) or document explicitly why `1.40 > 1.35` is intentional headroom for future formula changes:
```python
# ADAPTIVE_BUFFER_HARD_CAP is forward-looking headroom -- not currently reachable by
# the piecewise-linear formula (max output = 1.35). Keeps a ceiling for future calibration.
```

---

### IN-02: Two stale TODO comments about regime-gate optimization across 34/36 plugins

**File:** `src/intelligence/trading/trend_following.py:59`, `src/intelligence/trading/mean_reversion.py:60-63`

**Issue:** Both plugins carry TODO comments noting that the regime-gate-before-OHLCV optimization should be applied to the remaining 34/36 I7 plugins. This is an open technical debt item that predates Phase 115. It is not introduced by this phase but is visible in the reviewed files.

**Fix:** Track as a separate task. These comments should be converted to a formal backlog item and removed from code once the optimization work is scheduled.

---

### IN-03: `assert self._repo is not None` in hot path

**File:** `services/signal_writer.py:138`

**Issue:** `assert self._repo is not None` in `_flush_batch()` will silently become a no-op if the process is ever launched with `python -O` (optimize flag, which strips asserts). This is not a concern for the current deployment model (systemd + explicit Python invocation), but it diverges from the project's stated preference for loud failures over silent ones. The project principle is "silent wrong answers are worse than loud crashes."

**Fix:** Replace with an explicit guard:
```python
if self._repo is None:
    raise RuntimeError("SignalWriter._repo not initialized — _setup() must complete before flush")
```

---

_Reviewed: 2026-06-05_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
