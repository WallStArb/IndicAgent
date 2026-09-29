---
card_id: legacy-alpha-score-residual-single-security-15m
kind: legacy_verdict
title: alpha_score residual against its own symbol's 15m forward return (single-security, then sector-bucketed)
idea: "The cross-sectionally demeaned alpha_score residual predicts each symbol's own 15m forward return, per name."
verdict: FAIL
verdict_date: 2026-09-03
recipe:
  spec: docs/plans/2026-09-02-personal-scale-edge-determination-plan.md
  script: scripts/analysis/alpha_score_residual_single_security_15m.py
  recipe_commit: f8eceadf4c0108087ecd0138f9805c715096789f
results:
  - name: family_stat
    value: "0.00277, CI [0.0008, 0.00466], floor 0.0027 (clears the effect-size floor)"
    source: db:concept_registry
  - name: family_null_conditions
    value: "family panel-synchronous shift null p 0.002; raw arm null p 0.001 (both null conditions pass as recorded)"
    source: db:concept_registry
  - name: qualifying_symbols_by_fdr
    value: "0 of 231 qualify BY-FDR positive against the 10% floor (condition 4 fails, decisive)"
    source: db:concept_registry
  - name: raw_arm
    value: "raw (non-residualized) arm stat 0.01054, CI [0.00607, 0.01505], about 3.8x the residual family stat"
    source: db:concept_registry
  - name: temporal_thirds
    value: "0.00281, 0.00172, 0.00301"
    source: db:concept_registry
  - name: pooled_sidecars_and_regime
    value: "pooled Spearman 0.00288, pooled Pearson 0.00174; only regime passing BH is low_neutral (0.00398)"
    source: db:concept_registry
  - name: panel
    value: "14,750,919 rows, 231 symbols, 3,469 dates, in-sample bar_ts < 2025-12-24"
    source: db:concept_registry
  - name: bucketed_retest_2026_09_11
    value: "0 of 8 sector buckets qualify; every raw bucket null_p between 0.15 and 0.80 (0.05 not reached before correction); pre-registered fast-kill (at most 1 of about 8) triggers"
    source: docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
known_defects:
  - "Todo 372 finding 1 (fixed 2026-09-11, commit 5dd25cd15): Panel.sync_shift_null_p shifted each symbol by k modulo its own active-date count instead of on the shared panel calendar, degrading the panel-synchronous null into independent per-symbol shifts and understating the false-positive rate. The recorded family null p (0.002) came from code before that fix; a later commit (cfc4a5b20) also fixed the null p denominator dropping NaN replicates. The FAIL rests on condition 4 (0 of 231), which those null bugs do not touch."
  - "The raw arm being about 3.8x stronger confirms the predictivity is dominated by the common market component that per-bar demeaning strips."
  - "The bucketed retest used a fixed 8-bucket sector mapping (instruments.contract_details sector) with 24 NULL-sector symbols excluded ex ante."
  - "In-sample diagnostic only; the design commit (dc4288d0fe34c14409cf5d75dc55dd9f1922de14) preceded the run."
spans_looked_at:
  - {start: 2006-09-01, end: 2025-12-23, role: in_sample}
forward_span_looks: 0
tables: [alpha_events, forward_returns, instruments, concept_registry]
status_now: reopened
reopened_as: "construction-verdict-ledger.md section 2: a 15m single-name family on S1 residual targets"
reproducible: false
sources:
  - docs/plans/2026-09-02-personal-scale-edge-determination-plan.md
  - production/migrations/330_concept_registry_residual_single_security_verdict.sql
  - scripts/analysis/alpha_score_residual_bucketed_retest_15m.py
  - db:concept_registry
  - docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
related_cards: []
---

# alpha_score residual against its own symbol's 15m forward return (single-security, then sector-bucketed)

Author: Claude Sonnet 5.5, 2026-09-29
Informed by: `docs/research/construction-verdict-ledger.md` section 4 row `alpha_score_residual_single_security_15m`; migration 330

## What was tried

Pre-registration 2 (workstream 2 of the personal-scale edge program, todo 278's mandated
diagnostic): per-bar cross-sectionally demeaned `alpha_score` residual against its own symbol's
15m forward return on the full in-sample panel (bar_ts before 2025-12-24), with four
conditions: family statistic above an effect-size floor, a panel-synchronous null, a raw-arm
comparison, and per-name qualification (at least 10% of names BY-FDR positive). On 2026-09-11 a
bucketed retest re-ran condition 4 as BY-FDR across 8 sector buckets instead of 231 symbols.

## What was found

Conditions 1 to 3 pass: the family statistic 0.00277 clears the 0.0027 floor and both null
conditions pass. Condition 4 fails decisively: 0 of 231 names qualify. The effect is uniformly
dilute and common, not concentrated per-name alpha; the raw arm is about 3.8x stronger, so the
predictivity is mostly the market component the demeaning strips. The bucketed retest found
0 of 8, with every raw bucket null_p at 0.15 or above, and closes both forms of condition 4.

## Known defects

See front matter, including the null-shift bug fixed on 2026-09-11 that postdates the recorded
null p.

## Why closed

The ledger froze it FAIL, bucketed retest also FAIL, closed. It is reopened in ledger section 2
(owner decision 2026-09-25): the per-name concentration gate is removed under E15, a weak effect
spread across many names is now the target shape, and S1 removes the common component that
dominated the raw arm. The reopened form is a new pre-registered family member on S1 residual
targets, disclosed as seen data; this card stays the closed-verdict record. It cannot be rerun
as-is: the script is deleted by 186-16, `alpha_events` is dropped under phase 186, and E15
removed the gate it failed.

## Where the numbers came from

Statistics come from the `concept_registry` row for `alpha_score_residual_single_security_15m`
(`domain = 'construction'`, `status = 'deprecated'`, migration 330); the bucketed-retest numbers
come from the ledger row. Read-only SQL, run 2026-09-29:

```sql
SELECT name, status, added_phase, created_at, metadata FROM concept_registry
WHERE domain = 'construction' AND status = 'deprecated' ORDER BY created_at;
```

No script was rerun. `recipe_commit` is `git log -1 --format=%H --before="2026-09-03 23:59:59"
-- scripts/analysis/alpha_score_residual_single_security_15m.py`; the bucketed retest script
(last commit `8841bc2196d19d7450feaca6255d5d70e38fdf32`) is in `sources`. `tables` are the
script's `FROM alpha_events ... JOIN forward_returns` fetch, the retest's `instruments` read, and
`concept_registry` as the verdict store. The plan's expected tables did not include `alpha_events`;
the script reads it directly, so it is listed.

The span start follows the 186-01 corpus start convention and the end is the day before
`oos_start`. `forward_span_looks` is 0: both runs were in-sample only.
