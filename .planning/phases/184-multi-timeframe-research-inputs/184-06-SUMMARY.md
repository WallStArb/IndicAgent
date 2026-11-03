---
phase: 184-multi-timeframe-research-inputs
plan: 06
subsystem: research
tags: [spec, panel, mtf]
requires: [184-01, 184-03]
provides: [MemberInputSpec, MemberSpec.input, MemberSpec.smoothing_half_life, PanelSpec.fields closes_at, Panel.closes_at]
affects: [184-05, 184-07, 184-09, 184-10]
key-files:
  modified: [src/intelligence/research/spec.py, src/intelligence/research/panel.py, tests/unit/research/test_panel_optional_fields.py, docs/foundation/glossary.md]
  created: [tests/unit/research/test_spec_member_inputs.py]
requirements-completed: [MTF-B1a, MTF-B1b, MTF-B5, MTF-B7]
completed: 2026-11-03
---

# Phase 184 Plan 06: spec surface for feature and kernel members Summary

Optional member `input` block and `smoothing_half_life` menu in spec.py, plus an optional per-row `Panel.closes_at` array, with no recorded hash moved.

## What changed

- `MemberInputSpec` (kinds feature and kernel; `config_projection_hash` required for both; feature needs `coverage_floor` and forbids windows and gap; kernel needs `windows` and `max_gap_rows`, and `column` must be `<family>_w<window>` matching `windows`).
- `MemberSpec.input`, `MemberSpec.smoothing_half_life` (Literal 5, 21, 63; refused without an input, B5). `_OPTIONAL_MEMBER_FIELDS` drops both from each member's canonical form while unset.
- `FamilySpec` refuses an input without `closes_at` in `panel.fields`, and smoothing on a non-1d panel.
- `"closes_at"` added to `PanelSpec.fields`. `panel.CLOSES_AT` joins `OPTIONAL_ARRAY_FIELDS` so save and load use the one optional-array path; `select_symbols` keeps it unsliced (it is per row); `runner._sub_panel` already row-slices it.
- Glossary entry `smoothing menu`.

## Gates

Suite `tests/unit/ -n auto` exit 0; `repro_frozen` bit-identical; `test_spec_hashes_pinned` green with an empty diff.

## Deviations

- `panel_81fa9178ca4ad603` is not on this host (`logs/research/snapshots` is absent), so the snapshot verify test skips. Byte neutrality is covered by a test that a plain panel writes no `closes_at.npy`; repro_frozen replays the frozen verdicts.
- Compare-all was not run (plan text lists it; the lead's gate list does not).

## Notes for plans 05 and 07

- `snapshot.py` still refuses `closes_at` in `fields` (its allow-list is high, low, sector_pit): plan 07 must extend it and fill the array as `datetime64[ns]` shape `[n]`.
- `closes_at` is not scaled or column-selected by `dividends.total_return` (per row, carried by `dataclasses.replace`).
