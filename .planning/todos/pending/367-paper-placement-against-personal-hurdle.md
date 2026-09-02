---
status: pending
priority: P1
filed: 2026-09-02
source: personal-scale edge determination program, 2026-09-02 (user-approved plan after
  council review) -- workstream 0c
---

# 367 — Paper placement: evaluate already-measured signal mass against the 0b personal hurdle

Workstream 0c of `docs/plans/2026-09-02-personal-scale-edge-determination-plan.md`. Blocked
on workstream 0b's hurdle function existing (same doc, assumptions pre-registered there).
Consumes existing numbers only -- no new measurement runs.

**What:** evaluate each of the following against the 0b hurdle function, per its own
(IC, breadth, autocorrelation, horizon) tuple:

- the 5-10d range/vol signal mass (162 FDR-passing pooled cells at 1d lookahead 5;
  `range_to_close`/`range_pct_fast`/`ctf_regime_align`/`atr_z`/`bars_since_high`/
  `hurst`/`yang_zhang_vol_z` family)
- the N1 residual (`nonlinear_interaction_combiner`'s surviving small residual at
  1h/15m/5m)
- the `alpha_score` demeaned residual (todo 277's finding)
- `gap_z` (71-symbol unanimous, the broadest clean per-symbol feature)
- Phase 148's Gate-1-passing per-symbol directional construction

**Verdicts:** killed on paper / advanced / needs-a-construction (mass clears the hurdle
but no construction exists to falsify). Write each verdict to `concept_registry` with
`domain='construction'` per the program doc's governance rule.

**Pre-registered decision-gate connection:** if any "needs-a-construction" verdict lands
on the 5-10d band, exactly ONE new construction gets designed and pre-registered for it
(program doc, decision rule 2). If nothing clears, the kill criterion fires (rule 3).

## References

- `docs/plans/2026-09-02-personal-scale-edge-determination-plan.md` -- the program
- todo 277, todo 278 -- residual threads
- `docs/research/measurement-nonlinear-interaction-combiner.md` -- N1 residual numbers
