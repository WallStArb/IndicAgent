# Family 2 evidence run: readiness (2026-10-26)

Author: indicagent-5b (research lane)

The owner approved exactly one family 2 evidence run (build-first lifted for it alone):
`.venv/bin/python scripts/research/run_spec.py --spec research/specs/family2_overnight_intraday.yaml`.
It is one counted look at vintage 1 under E18.

## Gates before firing (all must hold)

1. Phase 191 plan 20's 1d re-derive has landed (owner amendment 2026-10-27, commit 60e5a6dc3:
   build-first lifts there, not at plan 25; the runner's import closure touches no file in
   plans 191-21 to 191-25). indicagent-3a sends the notice.
2. Done 2026-10-27: indicagent-3a's D-191-P message ("5m reselect landed, 15m/1h grid
   re-derived after D-191-P, 5m selection gate exit 0"; logs/selection_gate_20261027T072705Z.json,
   1529/1529 clean). Family 2's S0 reads canonical 15m 2006-2025, derived from 5m.
3. The family 2 code is committed and the checked files are clean (`provenance.require_clean`).

## Staged and verified

- Code path: a synthetic run of the real spec (1,500 sessions, 60 names) completes all six
  members. Before a138749f7 every member ended guard_failed (prefix-sum rounding broke the S3
  memory guard), so the approved run would have been lost.
- Universe: compute_eligible is 233 names (as at prereg); the members universe (EQ, no intl_*
  tag) is 187. The panel is the size family 1 ran on, so memory is fine.
- Dividends (total_return): all 187 have Yahoo coverage; 149 cover the scored span
  2010-01-04 to 2025-12-23, the rest start later. The data_quality block discloses the
  uncovered share (todo 501).
- Recording: the run writes its D_s series and headline numbers through S6 (187-02) and joins
  the StepM selection universe.

## Known limits (disclosed, not blocking)

- The members universe (B3) is read at run time from the current classification, not pinned in
  the snapshot. Its hash is recorded (`members_universe_hash`), so the record has lineage, but a
  later replay depends on the classification as of the replay. Plan 187-03's replay script
  refuses such specs rather than replaying them inexactly.
- Costs never enter the statistic. The first-cut cost model (todo 437) is needed for promotion,
  not for this evidence run.
