---
status: done
priority: P1
filed: 2026-09-30
source: plan 186-18, todo 289 measurement
---

# regime_volatility at 1d is gated off for about 98% of segments: the 3-state fit collapses on the 250-day windows

## What

The 186-18 sweep (`evidence/186-18-regime-coverage.json`, key `todo_289`, all 931
`compute_eligible_1d` names) measured the volatility family's pooled 1d skip fraction at 0.982 at
the live 252-bar schedule (0.984 at 126, 0.979 at 504), every skip a degenerate-occupation
verdict. Only 215 of 12,012 attempted segments are written; 145 of 931 names get any label. In 560
of the 742 names with no label the minimum state occupation of the training decode is exactly 0:
the 3-state model on `[realized_vol, vol_of_vol]` over 250-day windows (APR
`alpha.hmm_volatility.vol_window` and `vol_of_vol_window` 250, `n_components` 3) leaves a state
empty. The refit schedule is not the lever (todo 289 closed on that measurement).

## Why it matters

`regime_volatility` and its `hmm_vol_*` columns are book inputs through todo 435. The 186-25/186-26
rebuild reproduces this coverage unless the model configuration changes first: at 1d the column is
labeled on about 1.7% of rows after the first boundary.

## Next

Decide, on bars only, before the rebuild: observation windows (the 250/250 pair makes both
columns nearly constant inside a segment), `n_components` 2 versus 3 at 1d, and whether the
occupation floor (`feature.hmm.min_state_occupation` 0.05) is the right gate for a slow
volatility axis. Every change relabels the family, so it goes through the sweep script with
`--override` and a rule written before the run, then a golden regeneration in its own commit.
Decide whether 1d volatility belongs in the rebuild at all (the trend family labels 0.84 of rows).

## Decision rule (preregistered 2026-10-02, committed before any candidate run)

Instrument: `scripts/infrastructure/features_regime_kernel_coverage_sweep.py`, read-only, one JSON
report per arm under `evidence/478-*.json` (untracked, the 186-18 convention). Every arm runs
`--symbols @compute_eligible_1d --tfs 1d --families volatility --workers 6` at the live schedule
(refit 252, warmup 504) and the live floor (`feature.hmm.min_state_occupation` 0.05). The floor is
held identical in every arm: it is the degeneracy detector this decision exists to satisfy, not a
lever, and lowering it would admit exactly the collapsed fits the gate exists to refuse. The first
boundary is max(504, K x 50) = 504 obs rows in every arm, so attempted-segment grids coincide;
post-boundary denominators differ slightly across arms because a shorter `valid_start` (window sum
minus 2) leaves more early history observable. Each arm is judged on its own post-boundary rows,
which is what the rebuild would write, so that difference is the measurement, not a confound.

Arms (live baseline verified in `config_state` 2026-10-02):

- A control: live config (250/250, K=3)
- B: 60/60, K=3
- C: 20/20, K=3
- D: 60/120, K=3
- E: 60/60, K=2
- F: 20/20, K=2

Instrument check: arm A must reproduce the 186-18 collapse (pooled skip fraction >= 0.95). If it
does not, halt and investigate before reading any candidate arm: the data or the instrument
changed and the premise of this decision no longer holds.

Qualification: an arm qualifies when its pooled `labeled_fraction_after_first_boundary` >= 0.50 and
it has zero errored cells. 0.50 is the floor at which the axis carries book-input value: trend
labels 0.84 of 1d rows, so half of that is the minimum worth relabeling for, against 0.017 today.

Decision: among qualifying arms take the first in this fixed preference order, each step the more
conservative change: B > C > D > E > F. K=3 over K=2 keeps the calm/elevated/turbulent vocabulary
and its CVR codes intact (171-FINAL validated both; K=2 leaves `elevated` a dead code). The 1:1
window ratio changes exactly one design dimension from live (length, not ratio); within that, 60
bars over 20 keeps the axis slow (monthly, not weekly, realized vol). If no arm qualifies, drop 1d
from the volatility family in the 186-26 rebuild and measure the family's intraday coverage in a
follow-up all-tf pass for the record; forcing labels out of a degenerate configuration is not an
option.

## Stage-1 result (run 2026-10-02, after the rule above was committed as b1e4463a5)

| Arm | Config | skip | labeled | written segs | Verdict |
|---|---|---|---|---|---|
| A | 250/250 K=3 (live) | 0.9821 | 0.0177 | 215 | instrument check pass (reproduces 186-18 exactly) |
| B | 60/60 K=3 | 0.7512 | 0.2436 | 3358 | fails 0.50 |
| C | 20/20 K=3 | 0.6048 | 0.3916 | 5403 | fails 0.50 |
| D | 60/120 K=3 | 0.8264 | 0.1673 | 2328 | fails 0.50 |
| E | 60/60 K=2 | 0.0029 | 0.9970 | 13457 | qualifies |
| F | 20/20 K=2 | 0.0025 | 0.9974 | 13639 | qualifies |

Zero errored cells in every arm. Decision by the rule: **E (vol_window 60, vol_of_vol_window 60,
n_components 2)**. The three-state fit is structurally degenerate at 1d (best K=3 arm reaches
0.39); K=2 eliminates the collapse (39 degenerate segments of 13,496 attempted). `elevated`
becomes a label the 1d axis never emits; the CVR codes stay seeded, K=2 is the 171-FINAL
validated pair.

## Stage-2 rule (preregistered 2026-10-02, before the intraday verification run)

`alpha.hmm_volatility.n_components` and the window seeds are family-global, but stage 1 measured
1d only. Before any seed change lands, E must not regress the intraday tfs: on each tf with
coverage, E's `labeled_fraction_after_first_boundary` >= control's minus 0.02, and E's skip
fraction <= control's plus 0.02 (reports `evidence/478-verify-*-intraday.json`). If any tf
regresses beyond tolerance, the global seed change is refused: n_components becomes per-tf (new
APR key plus a `model_fields` change, owned by the 186-26 executor), and the 1d verdict E stands
either way. Follow-through on a pass: one migration (250/250/3 -> 60/60/2, provenance
`[rca_analysis]`, cross-referencing this todo and the evidence files), then the golden
regeneration (`features_capture_regime_kernel_golden.py --regenerate` with a pre-change `--dump`)
in its own commit.

## Outcome (2026-10-02)

Both stages ran under the preregistered rules; the seed change landed.

- Stage 2 (intraday non-regression, control vs E, 931 names x 15m/1h/5m): PASS on every tf
  with wide margin. E labeled 0.99722 / 0.99976 / 0.97655 vs control 0.36615 / 0.30765 / 0.43054;
  E skip 0.00271 / 0.00023 / 0.02315 vs control 0.63210 / 0.68970 / 0.56922. The control's
  intraday coverage was itself majority-skipped, so the old seeds were degenerate at every tf.
  Evidence: `evidence/478-verify-A-control-intraday.json`, `evidence/478-verify-E-intraday.json`.
- Migration 433 (`5c1c4c7c5`; its comment says todos/done, this file's real home is todos/completed):
  vol_window 250 -> 60, vol_of_vol_window 250 -> 60, n_components 3 -> 2, with config_schema
  provenance updates and config_history rows.
- Golden regenerated in its own commit (`cad3ffed0`): the four volatility cases flipped
  (SPY/1d, SPY/1h, TLT/1d, LQD/1d), trend cases byte-identical, `--verify` OK on all 10 digests.
- Stored regime columns stay gated until the 186-26 rebuild (todos 248/451); the rebuild is the
  first consumer of the new seeds. 467 closed separately (`33c099c77`).
