---
status: pending
priority: P1
filed: 2026-09-26
source: adopted unified design (todo 436), sections 11 and 12.2; Fable review items 1 and 8
---

# Forward-span integrity: make oos_start write-once and purge IC targets that cross it

## What

1. `snapshot.py` refuses research reads past `alpha.validation.oos_start`, but the key is a mutable
   APR value: one config write silently reopens the forward span. Add a DB trigger refusing updates
   to that key (a migration; commit it in the same breath as applying it).
2. `ic_engine` bounds rows by `bar_ts <= training_window_end`, so the forward returns of the last
   bars reach past the vintage end by up to the horizon. Purge IC rows whose target window ends at
   or after `oos_start`, and fix the bound. Lands with the next planned ic_engine recompute (phase
   186), never mid-run.
3. Record the 7 looks in `.planning/gate_look_log.jsonl` against the forward span in the ledger's
   disclosure section, as E18 requires.

## Done when

The trigger is live and tested, the IC bound excludes targets crossing `oos_start`, and the looks
are disclosed.
