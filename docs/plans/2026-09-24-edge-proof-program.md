# Edge proof program (v3.4)

**Author:** Claude (Opus 5.5), 2026-09-24; reviewed by AGY the same day (four findings adopted:
harness instead of DB services, excess-over-null power, two-level decision, 179 off 178's path),
at Brandon's request ("come up with concrete steps and make our priorities/roadmap reflect what
levers need to be pulled").
**Status:** SUPERSEDED 2026-09-26 by `docs/plans/2026-09-26-unified-research-to-production-design.md`
(adopted, E18), which owns the sequence from here. Milestone v3.4 closed 2026-09-26: 178 and 182
complete, 179 and 181 verdicts FAIL, 177 and 180 superseded. Condensed 2026-10-31 (todo 568) to
this status page; the full text stands at commit `8b4f2c9c4` and the phase detail in
`.planning/milestones/v3.4-ROADMAP.md`. The levers and their rationale now live in
`.planning/ROADMAP.md` ("v3.4 rationale").

## Record

- Standing when the milestone was set (2026-09-24): 14 constructions run to a definitive verdict,
  zero PASS (`docs/research/construction-verdict-ledger.md`); effective feature-corpus breadth
  about 8 independent bets out of about 290 columns. Phase 174's single-name breadth gate failed
  (D-10, shared market beta dominates); the 13-symbol cross-asset ETF basket passed (avg pairwise
  corr 0.088, n_eff 6.3).
- The only positive result on record, todo 378's cross-asset diagnostic (signed `vol_normalized`
  ann. Sharpe about 1.19 vs `equal_weight` 0.18), was discounted on three grounds: mostly
  in-sample (about 90% of the window scored ensemble weights fitted through 2025-12-24), wrong
  comparator (long-only, signal-free, rather than a null-signal arm), underpowered out of sample
  (9-month holdout, t about 1.0). Do not cite it as edge evidence.

## Phases (one line each)

- **177 Data integrity floor:** superseded; carried by phase 185 and todos 411/395/387.
- **178 Recompute throughput bundle:** complete; full recompute about 3.3 days to about 1.1 days,
  champion weights refreshed (todo 404).
- **179 Cross-asset sleeve walk-forward:** FAIL (best arm excess +0.22, adjusted p 0.36;
  pre-registration `docs/plans/2026-09-24-phase179-sleeve-walk-forward-prereg.md`, FROZEN).
- **180 Cross-asset breadth expansion:** superseded; carried by the 931-name daily universe.
- **181 Construction track:** FAIL (H-A and H-B both FAIL Track 1 2026-09-24; TSMOM on the sleeve
  FAIL, p 0.22; ledger reached 16).
- **182 Security classification hierarchy:** complete (todo 384).
- **183 Research layer:** carried into v3.5; `.planning/ROADMAP.md` phase 183.

Working rules that carried forward: pre-register before looking; the holdout is read once per
method, last; every verdict lands in the ledger with the current N_tested. Phase numbers are
stable IDs. `.planning/ROADMAP.md` carries the phase entries, `.planning/STATE.md` the position,
`.planning/todos/PRIORITIES.md` the todo tiers.
