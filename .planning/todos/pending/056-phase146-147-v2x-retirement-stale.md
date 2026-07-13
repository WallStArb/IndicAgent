# Phase 147 gate dangles on unrun work; Phase 148's v2.x retirement half describes retiring an already-dead system

**Filename says "146/147"; current numbers are 147/148** (I7 Alpha Scorer Transition / Alpha
Scoring System + v2.x Retirement Gate) — filename kept as-is per this repo's no-rename
convention, body below uses current numbers throughout.

**Found:** 2026-07-03, via ROADMAP reconciliation pass (`.planning/research/2026-07-03-roadmap-reconciliation.md`, finding F3).

Three compounding problems, not yet fixed in ROADMAP.md (deliberately left for an operator call
first — see below):

1. **Phase 147's conditional gate cites CORPUS-07, which was never run.** Phase 141 is
   ✅ COMPLETE with requirements CORPUS-01..06 — no CORPUS-07 anywhere in its actual requirement
   list. The only trace of "CORPUS-07" is a next-steps recommendation (item 7) in
   `docs/analysis/ic-validation-report-58sym.md`. As written, 147's gate can never fire.
2. **Topdown D7 already pre-committed the outcome the gate was waiting for:** "Phase 147
   collapses to retirement-by-default now... rare survivors become predictors via D1 — no
   adapter contract, no `alpha.i7.mixing_weight_*` keys, no I7-03 ensemble ingestion path." The
   ROADMAP's 147 still specs the full I7-01..05 conversion apparatus (3 plan waves, mixing-weight
   APR keys, an `alpha_score` column on `signal_events`) that D7 already ruled unnecessary.
3. **v2.x is dead in fact, not merely deprecated** (bottomup audit §1.1/§5.1): `intelligence-pipeline.service`
   failed with `ExecStart` pointing at a deleted file, the I7 signal topic has had no producer
   since the D-09 cutover, `signal_events`/`trade_frames` frozen at 1,601 rows since 2026-06-22,
   CLAUDE.md itself marks the whole tier ARCHIVED. Phase 148's SCORE-04 (v3 vs v2.x counterfactual
   comparison "on the same symbols/period") has no comparable v2.x data population and never will;
   SCORE-05's retirement procedure describes disabling a systemd unit that's already failed-dead.

**Concrete fix sketched in the reconciliation doc (F3, not yet applied):**
- Phase 147 collapses to one wave: run the CORPUS-07 plugin-capture analysis itself as this
  phase's first deliverable; default outcome is retirement per D7; any survivor registers as an
  ordinary predictor (feature-grain, measured by `ic_engine`, per intel-15's grain rule) — delete
  I7-02/03/04 as requirements.
- Phase 148: change Depends-on from `i7_conversion_complete = 1` to "Phase 147's CORPUS-07
  evaluation complete." Reframe SCORE-04 as a documentation note (why no comparison population
  exists) or delete it. Reframe SCORE-05 from "retirement" to "decommission-in-fact" (unit
  removal, table archival, doc cleanup). The two-gate *promotion* half (SCORE-01/02/03) is
  unchanged and remains the real milestone exit — this only shrinks the retirement half.

**Blocked on an operator call, deliberately not decided unilaterally** (bottomup Open Q1):
**archive v2.x cleanly vs. delete outright**, and whether the SCORE-05 decommission checklist
should execute *before* Phase 148 (cheap cleanup, independent of the v3 proof gate) rather than
gated behind it as currently structured. Conflating "prove v3" with "bury the v2.x corpse" holds
free cleanup hostage to a statistical gate it doesn't need.

**Action:** get the operator call above, then rewrite Phase 147/148 per the sketch. Not urgent
in the sense that nothing breaks today, but 147 currently can't ever pass its own gate as
written — worth fixing before either phase is planned.
