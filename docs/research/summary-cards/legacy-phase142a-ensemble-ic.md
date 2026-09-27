---
card_id: legacy-phase142a-ensemble-ic
kind: legacy_verdict
title: Phase 142A ensemble IC measurement (EIC-01..05)
idea: Measure whether the ensemble output itself has IC before testing any execution rule, via a measurement engine, decay-curve hold calibration, a hard EIC-04 gate and an EIC-05 diagnosis tool.
verdict: DEAD
verdict_date: 2026-09-02
recipe:
  spec: null
  script: scripts/ops/alpha/ops_ensemble_ic_gate.py
  recipe_commit: c141ac3217684aa372e03e32ce8c8b6387db1c83
results:
  - name: alpha_ensemble_ic_rows
    value: 0
    source: db:alpha_ensemble_ic
  - name: eic_gate_and_diagnosis_scripts
    value: built and unit-verified, never executed against real alpha_ensemble_ic rows
    source: .planning/milestones/v3.1-phases/142A-ensemble-ic-measurement/142A-VERIFICATION.md
known_defects:
  - "Pooled cross-sectional measurement unreachable: alpha_events never contains symbol='POOLED', so EIC-05 Section 2 was a permanent no-op (captured as todo 046, never done)."
  - The phase verification states the engine was never run live against the corpus; EIC-04/EIC-05 were unit-verified against the empty-table path only.
spans_looked_at: []
forward_span_looks: 0
tables: [alpha_ensemble_ic]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - .planning/milestones/v3.1-phases/142A-ensemble-ic-measurement/142A-VERIFICATION.md
  - .planning/milestones/v3.1-phases/142A-ensemble-ic-measurement/142A-02-SUMMARY.md
  - db:alpha_ensemble_ic
related_cards: [legacy-ensemble-champion]
---

# Phase 142A ensemble IC measurement (EIC-01..05)

## What was tried

Phase 142A built EnsembleICEngine (per-symbol ensemble-output IC with decay curves), the
EIC-04 hard gate script and the EIC-05 four-section failure diagnosis script, to prove the
ensemble OUTPUT has IC before any execution rule was tested.

## What was found

The machinery was built, code-reviewed (2 blockers, 3 warnings, fixed or documented) and
verified, but never executed against real data: the engine run was explicitly out of scope and
was never performed afterwards. `alpha_ensemble_ic` holds 0 rows. The EIC-04 gate and EIC-05
diagnosis were never evaluated on real rows, so phase 142A produced no measurement verdict.

## Known defects

Pooled cross-sectional IC was unreachable by construction (todo 046). The gate's denominator
was scoped to the gate lookahead only after review fix CR-02. The engine run never happened,
so nothing downstream ever consumed the tables it would have written.

## Why closed

The process was abandoned without ever running its gate: the corpus moved to phase 148's OOS
proof gates instead, and later the unified research-to-production design (E18) retired the old
chain. DEAD, not FAIL: no gate look ever evaluated this process on real data.

## Where the numbers came from

Row count read 2026-09-27:

```sql
SELECT count(*) FROM alpha_ensemble_ic;  -- 0
```

All other numbers are quoted from `.planning/milestones/v3.1-phases/142A-ensemble-ic-measurement/142A-VERIFICATION.md` (committed 2026-09-02).
