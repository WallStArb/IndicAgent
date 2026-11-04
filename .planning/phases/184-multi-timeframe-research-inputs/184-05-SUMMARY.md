---
phase: 184-multi-timeframe-research-inputs
plan: 05
subsystem: research battery
tags: [e17, null-battery, persistent-predictor, certificate]
requires: [184-01, 184-02, 184-03, 184-04, 184-06, 184-07, 184-08]
provides: [null_battery_persistent, BatteryCertificate, CertificateRequest, admit, NotCertified, PASSING_CERTIFICATES, families.features.centred, families.features.NULL_BATTERY]
affects: [184-09, 184-10]
key-files:
  created: [src/intelligence/research/null_battery_persistent.py, src/intelligence/research/families/features.py, tests/unit/research/test_null_battery_persistent.py, tests/unit/research/test_families_features.py, .planning/phases/184-multi-timeframe-research-inputs/184-05-BATTERY.md, .planning/todos/pending/586-persistent-battery-gating-cell-failure.md]
  modified: [scripts/research/e17_null_battery.py, .planning/todos/PRIORITIES.md]
requirements-completed: [MTF-B6, MTF-B7]
completed: 2026-11-04
---

# Phase 184 Plan 05: persistent-predictor E17 battery

26 cells (25 gating, 1 diagnostic) route an AR(1) or research-kernel predictor through align, smoothing and `centred` into the member and S8 book E17 tests; six certificates pass, seven fail.

## Result

Run at 1,000 simulations, 4,000 sessions, 60 names, battery module commit 9ceb891b6 (run at its pre-rebase hash 49e21bb41, clean). Gates are the 0.05 (67) and 0.01 (18) bounds in both arms; 0.00167 is descriptive.

PASSING_CERTIFICATES (identity, window, smoothing, source tf, book tf, memory bound), all horizon 1, equal_weight, max_age_rows 1:
- feature, 1h source, 1d book, 140 bars
- feature, 15m source, 1d book, 520 bars
- feature, 1d source, 1d book, smoothing 5, 252 bars
- rk_high_dist 126, 1d, max_gap_rows 2, 125 bars
- rk_vwap_dev 20, 1d, max_gap_rows 2, 19 bars
- rk_vwap_dev 20, 1h source, max_gap_rows 2, 19 bars

Failing (refused until todo 586): feature 1d unsmoothed (tau 60, 200, static 200), feature 5m (tau 200), feature 1d smoothing 21 (tau 5), smoothing 63 (tau 5, 60), feature 1h smoothing 21, rk_price_percentile 126, feature 1d on the hourly book (tau 200). Oversize grows with persistence, consistent with an HAC lag that does not scale with weight persistence; no fix proposed.

## For 184-09

`families/features.py` exposes `centred(x, *, bars_per_session, coverage_floor, sign=1)` and `NULL_BATTERY`. Admission is `null_battery_persistent.admit(CertificateRequest(...))`, where the request carries the certificate's discrete fields plus `source_memory_bars`.

## Deviations

- Amendment (b) (one admission mechanism in `certificate.py`, schema v2, certify script) is not implemented: the lead's brief specified `PASSING_CERTIFICATES` in the battery module, and the fitted-book certificate is already voided by 187-09 pending its own rerun. `admit` and the per-cell route keys are shaped so a later move into `certificate.py` is mechanical; the battery's `e17_null_battery` driver still writes the record.
- `kernel_source` refuses percentile and high-distance kernels without a config (stored-window check, 184-REVIEWS row 10), so the battery passes a stand-in with the production stored windows (50, 200, 252) instead of `config=None`; vwap_dev also needs a constant volume basis.
- Cells also list 40% of names late plus one late name; sessions are 4,000 (not 3,000).
- Driver edit: `dataclasses.asdict(sc)` in the record (nested certificate).
- Tests were written before the module but not run red first.
- Compare-all not run (lead).

## Gates

Unit suite exit 0 and repro_frozen bit-identical on the rebased tree; pinned spec hashes green.
