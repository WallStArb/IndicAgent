---
phase: 115
plan: "02"
subsystem: signal_schema
tags: [tdd, signal-dict, audit-trail, framing, cross_asset_divergence]
dependency_graph:
  requires: [TradeFrame.adaptive_buffer_mult, TradeFrame.plugin_regime_type, TradeFrame.stop_basis, TradeFrame.structural_stop_distance_atr]
  provides: [signal_dict.stop_basis, signal_dict.structural_stop_distance_atr, signal_dict.adaptive_buffer_mult, signal_dict.plugin_regime_type]
  affects: [signal_writer, signal_ledger, all I7 consumers of make_signal_from_frame()]
tech_stack:
  added: []
  patterns: [TDD red-green, single-authority construction invariant]
key_files:
  created: []
  modified:
    - src/intelligence/trading/signal_schema.py
    - src/intelligence/trading/cross_asset_divergence.py
    - tests/unit/intelligence/test_signal_schema.py
decisions:
  - "Four framing audit fields assigned inside make_signal_from_frame() after zone fields - single authority, no plugin-level injection permitted"
  - "Removed signal['stop_basis'] = tf.stop_basis from cross_asset_divergence.py (line 234) - was the only manual injection violating the construction invariant"
  - "Used plugin_regime_type (not regime_type_used) per 115-01 field naming decision, consistent across both plans"
metrics:
  duration_seconds: 71
  completed_date: "2026-06-05"
  tasks_completed: 1
  tasks_total: 1
  files_changed: 3
---

# Phase 115 Plan 02: Propagate Framing Audit Fields through make_signal_from_frame() Summary

Four framing audit fields (stop_basis, structural_stop_distance_atr, adaptive_buffer_mult, plugin_regime_type) propagated from TradeFrame into every signal dict through make_signal_from_frame(), with the one manual violation in cross_asset_divergence.py removed.

## Tasks Completed

| Task | Description | Commit | Files |
|------|-------------|--------|-------|
| 2 (RED) | Add TestFramingAuditPropagation failing tests | 7bc5baa9 | test_signal_schema.py |
| 2 (GREEN) | Add four audit field assignments; remove manual injection | ad2cee2f | signal_schema.py, cross_asset_divergence.py |

## What Was Built

**`make_signal_from_frame()` in signal_schema.py** gained four assignments immediately after the zone fields (lines 290-293):

```python
sig["stop_basis"] = tf.stop_basis
sig["structural_stop_distance_atr"] = tf.structural_stop_distance_atr
sig["adaptive_buffer_mult"] = tf.adaptive_buffer_mult
sig["plugin_regime_type"] = tf.plugin_regime_type
```

These fields are populated in every signal dict, using TradeFrame defaults when no explicit values were set (stop_basis=None, structural_stop_distance_atr=None, adaptive_buffer_mult=1.0, plugin_regime_type=None).

**`cross_asset_divergence.py` line 234 deleted** - the manual `signal["stop_basis"] = tf.stop_basis` injection after `make_signal_from_frame()` was removed. This was the only plugin violating the construction invariant. The `"stop_basis"` entry in the plugin's `outputs` frozenset at line 86 was retained - it declares the plugin's output contract, not an injection point.

**Test class `TestFramingAuditPropagation`** added with 5 tests:
1. `test_stop_basis_propagated` - "structure_snap" value survives frame→dict
2. `test_structural_stop_distance_atr_propagated` - 0.8 value survives frame→dict
3. `test_adaptive_buffer_mult_propagated` - 0.968 (Hurst-tightened) value survives
4. `test_plugin_regime_type_propagated` - "trend" value survives
5. `test_defaults_propagated_when_fields_not_set` - stop_basis present even with default None; adaptive_buffer_mult=1.0 default present

Total test count: 119 (was 107 at wave start; 115-01 brought it to 107, 115-02 adds 12 net... actually test_signal_schema was 7 tests before, now 12; test_trade_framer was 101 before; total across both files is 119).

## Deviations from Plan

None - plan executed exactly as written. Field name `plugin_regime_type` was already resolved in 115-01 and the context note in the PLAN.md explicitly noted this.

## Self-Check: PASSED

| Item | Status |
|------|--------|
| src/intelligence/trading/signal_schema.py | FOUND |
| src/intelligence/trading/cross_asset_divergence.py | FOUND |
| tests/unit/intelligence/test_signal_schema.py | FOUND |
| commit 7bc5baa9 (RED) | FOUND |
| commit ad2cee2f (GREEN) | FOUND |
| adaptive_buffer_mult assignment in signal_schema.py | FOUND (line 292) |
| signal["stop_basis"] in cross_asset_divergence.py | NOT FOUND (correctly removed) |
| 119 tests pass | PASSED |
