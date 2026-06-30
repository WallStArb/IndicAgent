---
**Created:** 2026-06-30
**Area:** intelligence
**Type:** correctness
**Priority:** P1
**Effort:** 4-6h (new service + systemd unit + migration + integration test)
**Benefit:** Closes the fundamental architecture violation that ensemble weights are permanently frozen; adds temporal self-correction to the IC engine without human intervention
**Risk:** Medium — new daily service with EnsembleBuilder trigger; regime-shift detection logic is subtle (do NOT re-solve on broad decay)
**Gate:** todo 031 (gap-stratified IC) AND todo 032 (empirical thresholds) complete — implementing this on top of contaminated IC or researcher-set thresholds propagates corruption
---

# 033 — Alpha Decay Monitor

Third and final in the correctness gap execution chain. See design doc:
`docs/plans/2026-06-30-alphaengine-correctness-gaps.md`

## What

New daily service (`services/alpha_decay_monitor.py`, extends `BaseBatch`) that:

1. For each active (feature, symbol, tf, regime) cell in the current weight_version, pulls
   the last 2,000 independent non-gap observations and computes Spearman IC + bootstrap CI
2. Flags `is_decaying = true` when `ic_ci_lower <= alpha.decay.ci_lower_threshold` AND
   the cell is material (`weight × |ic_ci_lower| > alpha.decay.materiality_threshold`)
3. Distinguishes individual decay from regime shift: if >=
   `alpha.decay.regime_shift_fraction` of cells are decaying simultaneously, log as
   `suspected_regime_shift` and do NOT trigger a re-solve (broad decay is a regime signal,
   not a correction opportunity)
4. Triggers EnsembleBuilder oneshot on confirmed individual decay (exclude decayed cells)
5. Monitors recovery: re-includes cells once IC is positive on a non-overlapping window

## Files

- `services/alpha_decay_monitor.py` (new — extends `BaseBatch`)
- `indicagent-alpha-decay-monitor.service` (new systemd unit — daily at 06:00 UTC)
- `services/service_auditor.py` — add to `_DAG_ORDER`, `_LAG_THRESHOLDS`,
  `_AGENT_ID_TO_UNIT`
- New migration:
  - INSERT `alpha.decay.ci_lower_threshold = 0.0`
  - INSERT `alpha.decay.materiality_threshold = 0.001`
  - INSERT `alpha.decay.regime_shift_fraction = 0.60`
  - INSERT `alpha.decay.rolling_window_obs = 2000`

## Critical Design Invariants

- Use non-gap observations only (mirrors Gap 1 fix — `has_gap_before_entry = false`)
- Same N-bar sub-sampling stride as ic_engine (`alpha.ic.subsample_min_stride`)
- Bootstrap CI uses 2,000 resamples (same as ic_engine)
- Re-solve writes a new `weight_version` — decay monitor must read the new version on
  next run, not the one that triggered the re-solve
- Regime-shift detection is read-only: log, do not act

## Verification

1. Migration applies cleanly
2. Service starts and processes all weight cells without error on a dry run
3. `pytest tests/unit/ -q` green
4. Manually set one `feature_ic_scores` cell to `ic_ci_lower = -0.05` and confirm decay
   is flagged and EnsembleBuilder oneshot is triggered
5. Simulate >=60% cells decaying; confirm regime-shift path fires (no re-solve)
6. Service appears in `service_auditor` health check
