---
status: pending
priority: P2
filed: 2026-09-24
source: Phase 178 post-recompute pipeline run
---

# ops_ic_shrinkage's out-of-fold gate dies on Postgres's 1h idle-session timeout

The 2026-09-24 run on the fresh 178 IC finished Part A (ic_shrunk written for 69,346 POOLED rows,
committed) and then failed in Part B, `_run_out_of_fold_gate` (main line ~517), after ~2h20m:
`ConnectionDoesNotExistError: connection was closed in the middle of operation`. The server
logged `terminating connection due to idle-session timeout` at 20:36 (idle_session_timeout = 1h):
a connection held across a long compute went idle past it. Same failure class ic_engine fixed
with short-lived connections (todo 102). Fix: acquire per statement or per short block, never
hold one across the compute.

Consequence today: the gate was not re-evaluated on the fresh IC. `alpha.ensemble.ic_input`
was already `ic_shrunk` (gate PASSED 2026-09-10 and 2026-09-22; the flip is one-way), so the
trainer ran on ic_shrunk regardless. Re-run the gate after the fix to confirm it still passes on
the Phase 178 IC.
