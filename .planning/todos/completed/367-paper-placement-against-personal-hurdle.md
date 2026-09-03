---
status: completed
priority: P1
filed: 2026-09-02
resolved: 2026-09-02
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

## Resolution (2026-09-02, same day)

**All five scope items resolved; todo closed.**

- **Phase 148's Gate-1-passing construction: KILLED ON PAPER.**
  `scripts/analysis/phase148_personal_hurdle_placement.py` placed it against the 0b
  hurdle from existing numbers: fails the worst-case band rule on every (tf, scale)
  cell, 5 of 8 fail even the most favorable band, and — turnover-independent — Gate 2's
  realized OOS frame P&L was negative GROSS of personal costs (mean -0.1215 R, Sharpe
  0.385), so the lower personal hurdle has no positive gross edge to rescue. 0b's
  "wrong trader" insight does not apply to this construction. Verdict registered:
  `concept_registry` `phase148_alpha_score_directional`, migration 328. Caveat recorded:
  15m mid/slow/extended clear the most favorable band 4.7-11.7x — that mass belongs to
  the demeaned-residual thread (workstream 2's 15m diagnostic), which this verdict does
  not touch.
- **`gap_z`: verdict line recorded** in the program doc's 0c results — @ H=1, avg IC
  0.1039, worst-case margin 23.4x, per-symbol support 3/85 → CLEARS (thin support);
  shortlist combination input, not construction material.
- **`alpha_score` demeaned residual:** superseded by workstream 2's stronger diagnostic
  (as pre-noted in the re-scope).
- **N1 residual:** blocked on structural instability (todo 364), unchanged.
- **Second screen bug found and fixed during this work:** `personal_edge_paper_screen.py`'s
  `_LIVE_SPREAD_ANCHOR` was 0.0014 (14bp), a 10x transcription of 0b's measured 0.000138
  (1.4bp). Conservative direction — 208/208 verdicts and the 87 broad-support set
  unchanged on re-run; recorded margins were understated and are corrected in the program
  doc (8.8x-207x, was 1.25x-29x). 0b's own hurdle table unaffected.
