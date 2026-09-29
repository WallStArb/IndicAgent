---
card_id: legacy-ha-extreme-volume-divergence
kind: legacy_verdict
title: H-A extreme-volume divergence (15m, within-symbol Track 1)
idea: "A fresh price extreme on unusually light volume reverses over the next 15m bar, within each symbol."
verdict: FAIL
verdict_date: 2026-09-24
recipe:
  spec: docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md
  script: scripts/analysis/extreme_volume_divergence_track1.py
  recipe_commit: f461bdc549c0cdc901046aa46ae68648ec461d51
results:
  - name: gated_1bar_family_ic
    value: -0.0022
    source: docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
  - name: gated_1bar_ci
    value: "[-0.0051, +0.0005]"
    source: docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
  - name: gated_1bar_null_p_predicted_direction
    value: 0.92
    source: docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
  - name: gated_1bar_thirds
    value: "negative in all 3 thirds"
    source: docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
  - name: gated_1bar_qualifying_symbols
    value: "0.9% of symbols BY-qualify"
    source: docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
  - name: reported_2bar_family_ic
    value: "-0.0033, CI [-0.0067, -0.0002] entirely negative, 8 symbols significant the wrong way"
    source: docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
  - name: run_setup
    value: "233 symbols, B=2000, N=1000, panel-synchronous whole-date shift null (todo 372's reviewed fix), BY-FDR, in-sample only"
    source: docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
  - name: failed_criteria
    value: "all five gated criteria fail"
    source: docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
known_defects:
  - "The effect is weakly in the reverse direction (light volume at a fresh extreme leans toward continuation, a capitulation read). The reverse direction was not pre-registered and is at the effect floor, so it is not claimable from this run."
  - "Afternoon is more negative than morning, so the effect is not the open's volume smile."
  - "The run followed todo 372's fixes (panel-synchronous shift null, volume-z diurnal bias). Results before those fixes are not part of this record."
  - "The pre-registration's Status line still reads that neither hypothesis has run; the run record is the ledger row and the untracked log named in the prose below."
spans_looked_at:
  - {start: 2006-09-01, end: 2025-12-24, role: in_sample}
forward_span_looks: 0
tables: [feature_vectors, forward_returns]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md
  - .planning/todos/completed/372-panel-sync-shift-null-not-actually-panel-synchronous-plus-volume-z-diurnal-bias.md
  - docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
related_cards: [legacy-hb-confirmed-reversal]
---

# H-A extreme-volume divergence (15m, within-symbol Track 1)

Author: Claude Sonnet 5.5, 2026-09-29
Informed by: `docs/research/construction-verdict-ledger.md` section 4 row H-A `extreme_volume_divergence`; `docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md`

## What was tried

Pre-registered Track 1 (signal existence) for hypothesis H-A: at a fresh trailing extreme on
light volume, the next bar reverses. 15m bars, 233 symbols with enough finite rows before
`alpha.validation.oos_start`, a within-symbol continuous statistic, family IC with a bootstrap CI
(B=2000), a panel-synchronous whole-date shift null (N=1000), BY-FDR per symbol, thirds
stability, and a diurnal sub-panel. Five gated criteria; the primary horizon is 1 bar and 2 bars
is reported.

## What was found

All five gated criteria fail. The gated 1-bar family IC is -0.0022 (CI [-0.0051, +0.0005], null p
0.92 for the predicted direction), negative in all three thirds, with 0.9% of symbols
qualifying. The 2-bar horizon is -0.0033 with a CI entirely below zero and 8 symbols significant
the wrong way. Light volume at a fresh extreme leans very slightly toward continuation, and the
afternoon is more negative than the morning.

## Known defects

See front matter. The reverse direction is not claimable: it was not pre-registered and sits at
the effect floor.

## Why closed

The ledger froze it FAIL on all five gated criteria. It cannot be rerun as-is: the recipe script
is deleted by 186-16, `feature_vectors` is rebuilt, and E15 changed the gates. Any reopening is a
new pre-registered family member with its own count.

## Where the numbers came from

Every number is copied from the ledger section 4 row. The run log
`logs/extreme_volume/h_a_h_b_track1_20260924T201208Z.json` (untracked, gitignored) records
`git_commit` f461bdc549c0cdc901046aa46ae68648ec461d51, `oos_start` 2025-12-24 05:15 UTC and
`smoke` false; it is named here in prose only and is not a source. No query was run and no script
was rerun.

`recipe_commit` is the run commit the ledger names (`f461bdc54`), resolved with `git rev-parse
f461bdc54`. `git cat-file -e f461bdc549c0cdc901046aa46ae68648ec461d51:scripts/analysis/extreme_volume_divergence_track1.py`
succeeds, so the pointer names the script as it stood at the run. `tables` come from the script's
`FROM feature_vectors` and `JOIN forward_returns` (the `config_state` read is APR).

The run was in-sample only, so the span ends at `oos_start`; the start follows the 186-01 corpus
start convention. `forward_span_looks` is 0. The same run produced the H-B verdict on
`legacy-hb-confirmed-reversal`.
