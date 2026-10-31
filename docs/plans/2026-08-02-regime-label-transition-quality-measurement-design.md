# Regime Label Transition Quality - Measurement-First Design

**Status:** SUPERSEDED, and its question answered another way. The hysteresis fix it argued for
landed at the label source on 2026-08-27 (todo 005 closed, migration 326) without the full
measurement spec ever running; the measurement machinery it targets (`ic_engine`,
`feature_ic_scores`) was deleted in phase 186, and the label generators are now walk-forward
registry kernels (todo 248 deployed 2026-08-12, plan 186-13 merged 2026-09-30). Any purge or
smoothing question today is a spec field measured through the research runner (E15), not a
bespoke diagnostic. Written 2026-08-02, Opus-reviewed (5 critical findings) and rewritten the
same day, every load-bearing number re-verified against the live DB. Condensed 2026-10-31
(todo 568); the full spec stands at commit `ae391ad77`.

## The measurement population (the doc's lasting methodological point)

`market_regimes` is a continuous 24/7 calendar grid, not the population IC measurement
consumes. Measured 2026-08-02 for equity/5m: 2,083,837 grid rows, 595,008 on weekends, only
387,974 (18.6%) whose `ts` joins to a `feature_vectors.bar_ts` - and only those can ever
contribute an IC observation. Any transition or occupancy statistic computed on the full grid
is wrong for measurement purposes; the calendar grid suppresses apparent flicker and inflates
apparent transition counts. (An earlier draft's "15,734 transitions, 24% short" was computed
on the grid and superseded.)

On the joinable population: equity/5m had 6,998 label transitions, 3,647 (52.1%) not
surviving 3 consecutive joinable bars; rates/5m was starker at 139,660 runs, 95.7% under 3
bars. The joinable restriction also reorders stratum occupancy materially (low_bull is largest
on the grid but a mid-tier label on the joinable population). These numbers are also recorded
in `docs/research/intelligence-lifecycle-backlog-matrix.md`.

## Outcome

- Fixed at the source 2026-08-27 (todo 005, option 2 of the approaches weighed):
  `cross_sectional_regime_model.py` gained a causal min-hold-bars hysteresis smoother
  (`alpha.regime.cross_sectional.min_hold_bars=3`, migration 326). Post-fix bar-to-bar churn:
  equity 5.6% to 5.4%, rates 18.3% to 7.0%, fx 63.7% to 7.4%, commodity 84.0% to 6.0% - the
  fix surfaced that commodity and fx labels had been flipping on most consecutive bars,
  contaminating those groups' regime-stratified IC history. Full table and verification:
  `.planning/todos/completed/005-ic-regime-transition-purge.md`.
- The per-symbol HMM side is governed by todo 248 (full-history-fit lookahead; walk-forward
  is the only mode since plan 186-13) and the dual regime system note in CLAUDE.md.
