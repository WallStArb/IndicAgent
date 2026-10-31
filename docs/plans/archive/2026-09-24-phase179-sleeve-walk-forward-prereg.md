# Phase 179 pre-registration: cross-asset sleeve walk-forward verdict (frozen record)

Original: 2026-09-24 (frozen 2026-09-25; rerun verdict 2026-09-25).
Archived 2026-10-31: voided-era prereg, results voided by the owner's 2026-10-30 data reset.

Hypothesis: production ensemble weights on the 13-symbol cross-asset sleeve (equity-group
pooled 1d IC, yearly refits, calibrated arms ic_proportional / vol_normalized /
mean_variance) survive a point-in-time walk-forward with a whole-panel shift null and
Westfall-Young correction. The first frozen run ended FIDELITY BROKEN on a
calibration-coverage defect and was rerun under methodology-change-ledger E14.

Verdict: FAIL, FIDELITY OK (best adjusted p 0.36). The in-sample Sharpe of about 1.19 does
not survive point-in-time weights, and the calibrated arms had 0% power on slow return-built
edges, so this FAIL says nothing about those. Ledger row:
docs/research/construction-verdict-ledger.md section 4; summary card
docs/research/summary-cards/legacy-phase179-sleeve-walk-forward.md.

Full text in git history at docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md as of 708f3fe09.
