---
status: pending
priority: P1
filed: 2026-09-02
source: personal-scale edge determination program, 2026-09-02 (user-approved plan after
  council review) -- workstream 0c
---

# 367 — Paper placement: evaluate already-measured signal mass against the 0b personal hurdle

Workstream 0c of `docs/plans/2026-09-02-personal-scale-edge-determination-plan.md`.
Consumes existing numbers only -- no new measurement runs.

**Executed 2026-09-02 (partial):** the 5-10d range/vol mass is placed. The flat library
screen (`scripts/analysis/personal_edge_paper_screen.py`) found 208 FDR-passing 1d cells,
all clearing the worst-case standalone personal hurdle; decision rule 2 fired;
`range_pct_fast` @ H=5 was selected and falsified DEAD (pre-registration 1). That branch
is closed; do not re-open it here.

## Remaining scope (re-scoped 2026-09-02)

- **Phase 148's Gate-1-passing per-symbol directional construction** -- the substantive
  remainder. 0b's headline is that the institutional-calibrated Gate 2 that killed it
  measured the wrong trader; placing this construction's own (IC, breadth, autocorr,
  horizon) tuple against the personal hurdle is cheap (existing numbers) and directly
  feeds the todo 368 successor decision and the program's decision-gate rules 1 and 3.
- **`gap_z`** -- verify its (feature, H) cell is among the 208 placed cells and record
  the explicit verdict line in the program doc's 0c results.
- **The `alpha_score` demeaned residual (todo 277)** -- superseded: workstream 2's 15m
  diagnostic is a strictly stronger test than a paper placement. Close this item when
  that diagnostic runs.
- **The N1 residual** -- blocked: N1 is structurally unstable (bit-identical re-runs
  disagree, todo 364); placing an unstable number against a hurdle is meaningless until
  that is resolved.

**Verdicts:** killed on paper / advanced / needs-a-construction. Construction-level
verdicts land in `concept_registry` `domain='construction'` per the program doc's
governance rule.

## References

- `docs/plans/2026-09-02-personal-scale-edge-determination-plan.md` -- the program
  (§ 0c results carries the scope-completion note)
- todo 277, todo 278 -- residual threads
- `docs/research/measurement-nonlinear-interaction-combiner.md` -- N1 residual numbers
