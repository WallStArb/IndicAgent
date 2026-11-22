# Post-D1 landing runbook (archived)

Date: 2026-11-15. Archived 2026-11-22.
Outcome: executed. The held refactor stack, L1 kernels, R2 production-path golden and L3 universe landed on main (migrations 595 to 597 and 600 exist, the corpus universe and membership writer are live; the step 7 rebuild, D5 timers and Part F are done). The held worktrees it names are gone. Remaining operator steps (sudo unit cleanup) are in `.planning/STATE.md`; the R2 remainder is tracked in todo 614.

Ideas kept:
- Everything that moves `rebuild_code_key()` lands in one window before the corpus rerun pins, so the key moves once; nothing in its closure is edited after `--new-run`.
- Land after all of the quiet-list audits (not D1 alone) and before the restart, so every unit picks up new code with a single restart.
- Land in the order that minimizes conflicts: the widest stack first, then kernels, then tests, then the module that touches the shared services last.
- Rollback is `git revert` of a contiguous pushed range, never a reset of main; a migration that deletes history needs its own rollback text.
- Migration numbers are rechecked against `origin/main` at landing (`tools/gate.py` stops on a clash).

Full text: git history, `docs/plans/2026-11-15-post-d1-landing-runbook.md` as of `cf592e234`.
