---
card_id: legacy-hb-confirmed-reversal
kind: legacy_verdict
title: H-B confirmed reversal, K=3 (15m, within-symbol Track 1)
idea: "After a fresh extreme is followed by a K=3 bar confirmation pattern, the next bar reverses, within each symbol."
verdict: FAIL
verdict_date: 2026-09-24
recipe:
  spec: docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md
  script: scripts/analysis/extreme_volume_divergence_track1.py
  recipe_commit: f461bdc549c0cdc901046aa46ae68648ec461d51
results:
  - name: gated_1bar_family_ic
    value: "+0.0007, CI [-0.0030, +0.0046], null p 0.37"
    source: docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
  - name: gated_1bar_sub_thirds
    value: "+0.0029, +0.0017, -0.0022"
    source: docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
  - name: gated_1bar_qualifying_symbols
    value: "0 of 233"
    source: docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
  - name: reported_2bar_family_ic
    value: "+0.0029, CI through zero, positive in all thirds, 0 qualifiers"
    source: docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
  - name: failed_criteria
    value: "all five gated criteria fail"
    source: docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
known_defects:
  - "Ungated K robustness numbers (not counted, forking-path results): K=1 +0.0006, K=2 +0.0004, K=5 +0.0042 (positive in all thirds). Choosing K=5 after seeing it is the forking path the pre-registration forbids; it is not a lead without a fresh pre-registration and its own N_tested increment."
  - "The 2-bar and K robustness numbers are reported, not gated, so they do not change the verdict."
  - "The first H-B constructions were flawed and redesigned from scratch (AGY rounds 1 and 2, redesign 2026-09-09); this verdict is on the redesign (vectorized forward-scan anchor)."
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
related_cards: [legacy-ha-extreme-volume-divergence]
---

# H-B confirmed reversal, K=3 (15m, within-symbol Track 1)

Author: Claude Sonnet 5.5, 2026-09-29
Informed by: `docs/research/construction-verdict-ledger.md` section 4 row H-B `confirmed_reversal` K=3; `docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md`

## What was tried

Hypothesis H-B from the same pre-registration and the same run as H-A: after a fresh extreme
bar, a K=3 confirmation pattern precedes a reversal on the next bar. K=3 is the gated setting;
K=1, 2 and 5 were reported ungated as robustness. Same machinery as H-A: 233 symbols, 15m,
family IC with a bootstrap CI, panel-synchronous whole-date shift null, BY-FDR, thirds.

## What was found

No detectable signal, and all five gated criteria fail. Gated 1-bar family IC is +0.0007 (CI
[-0.0030, +0.0046], null p 0.37), sub-thirds +0.0029, +0.0017 and -0.0022, and 0 of 233 symbols
qualify. The 2-bar horizon (+0.0029) is positive in all thirds but has a CI through zero and no
qualifiers.

## Known defects

See front matter. The ungated K=5 value (+0.0042) is a forking-path result that does not count.

## Why closed

The ledger froze it FAIL. The K=5 lead is explicitly not a lead without a fresh pre-registration
and its own N_tested increment. It cannot be rerun as-is: the recipe script is deleted by
186-16, `feature_vectors` is rebuilt, and E15 changed the gates.

## Where the numbers came from

Every number is copied from the ledger section 4 row. The run log
`logs/extreme_volume/h_a_h_b_track1_20260924T201208Z.json` (untracked, gitignored) holds the same
run as the H-A card and is named in prose only. No query was run and no script was rerun.

`recipe_commit` is the run commit the ledger names (`f461bdc54`), resolved with `git rev-parse
f461bdc54`; the script exists at that commit (`git cat-file -e` succeeds). `tables` come from the
script's `FROM feature_vectors` and `JOIN forward_returns`.

The run was in-sample only, so the span ends at `oos_start`; the start follows the 186-01 corpus
start convention. `forward_span_looks` is 0.
