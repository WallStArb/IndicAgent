# D7 check split_horizon_fresh (archived)

Date: 2026-11-11. Archived 2026-11-14.
Outcome: landed on main at `c076ff72d` (hardened at `91956d176`): a required 5m D7 check in
`src/intelligence/bars/integrity_checks.py`, emitted by `services/bar_reconciliation_audit.py` and
required by `src/intelligence/bars/verdict_gate.py`; step 7 runbook item A4 depends on it. The
open item it named, the reselect trigger on a split write, is tracked in
`docs/operations/massive-step7-runbook.md`.

Decision kept: judge the content, not a horizon record. The selection horizon is not persisted on
every path (`--reselect-only` and the step 7 rebuild call `select_and_write` directly), so the check
recomputes `raw close / scale(session)` with selection's own arithmetic over the splits known now
and counts canonical Massive 5m bars that differ, with exact equality (a tolerance would hide a
one-split error on a small factor). This also catches a split voided after selection and a
canonical bar whose raw row is gone. 1d needs no new check: `canonical_recompute` already fails a
stale Massive 1d bar.

Full text: git history, `docs/plans/2026-11-11-split-horizon-fresh-check.md` as of `c076ff72d`.
