# 314 - compressed_hypertable_write_session collides with TimescaleDB's own compression policy job

**Filed:** 2026-08-14
**Source:** Found live while babysitting the fifth `regime_writer` relaunch (post-todo-312 fix
verification, see `project_disk_full_incident_2026_08_13` memory). AA/15m failed with:

```
"error": "deadlock detected\nDETAIL:  Process 64694 waits for RowExclusiveLock on relation
410139124 ...; blocked by process 57542.\nProcess 57542 waits for AccessExclusiveLock on
relation 410139124 ...; blocked by process 64694."
```

`pg_stat_activity` confirmed 57542 was `Columnstore Policy [1065]` (job_id 1065, TimescaleDB's
own scheduled compression job for `feature_vectors`, `hypertable_id: 85`, `compress_after: "6
mons"`), running `CALL _timescaledb_functions.policy_compression()`, wedged for **2.5+ hours**
(`query_start` 10:46:52, predates this session's regime_writer restart entirely) waiting on a
relation lock. `pg_blocking_pids(57542) = {64694}` -- a `regime_writer` UPDATE. Root cause:
neither `compressed_hypertable_write_session`/`async_compressed_hypertable_write_session`
(`services/_batch_utils.py`) nor any of its callers pauses the target hypertable's compression
policy job for the session's duration. Two independent mechanisms (TimescaleDB's automatic
policy-driven compress, and the write session's own manual decompress-all/write-all/
recompress-all) compete for exclusive locks on the same chunks with no coordination between
them -- most of the time the policy job just loses the race and queues (which is why this went
undetected until now: it manifests as the policy job silently starving, not erroring), but
sometimes the lock-acquisition order tips into a genuine circular wait, and Postgres's deadlock
detector kills one side.

**This is a worse failure mode than todo 312's underflow bug, not a lesser variant of it:** the
underflow bug was deterministic and tied to specific numeric values (same symbol fails every
retry, until fixed). This one is timing-dependent -- any symbol, on any run, can lose its write
depending on lock-acquisition timing, and re-running the identical symbol/tf may or may not
reproduce it. A per-symbol retry-and-skip pattern (which is what `regime_writer` already does on
`write_failed`) does not self-heal this the way it does for a deterministic bug -- silent gaps
can persist indefinitely if the colliding policy job keeps retriggering.

**Immediate mitigation applied this session (not a fix):** paused job 1065
(`SELECT alter_job(1065, scheduled => false)`) and terminated the wedged backend
(`pg_terminate_backend(57542)`) so the in-flight `regime_writer` run (started 12:30:37 UTC
2026-08-14) can proceed without further collisions from *this* job. **Job 1065 needs to be
re-enabled** (`SELECT alter_job(1065, scheduled => true)`) once that run completes --
whoever picks this up should check `ps aux | grep regime_writer` first and not re-enable it out
from under a still-running write session.

**Status:** pending, P0 -- silent, timing-dependent data loss on every writer using
`compressed_hypertable_write_session` against a hypertable with an active compression policy,
not scoped to `regime_writer` alone.

## Scope

1. Real fix belongs in `compressed_hypertable_write_session`/
   `async_compressed_hypertable_write_session` itself (`services/_batch_utils.py`), not in each
   caller: pause the target hypertable's compression policy job(s)
   (`timescaledb_information.jobs WHERE config->>'hypertable_id' = <id> AND proc_name =
   'policy_compression'`, `alter_job(job_id, scheduled => false)`) at session entry, restore the
   prior `scheduled` value at session exit (success or failure -- same `try/finally` shape as the
   existing `statement_timeout` save/restore from todo 306's third bug).
2. Check whether any *other* live writer against a compressed hypertable (not routed through
   `compressed_hypertable_write_session`) has the same exposure -- `ic_engine.py`'s deferred
   migration (todo 307) is the obvious candidate to check first.
3. Confirm no other hypertable currently has both an active compression policy AND a live
   `compressed_hypertable_write_session` caller -- `feature_vectors` (hypertable_id 85) is the
   one caught live here; audit the `_KNOWN_COMPRESSED_HYPERTABLES` list (todo 308) against
   `timescaledb_information.jobs` for the rest.
4. Add regression coverage: a test that starts a compression-policy-bearing hypertable's write
   session and asserts the policy job is paused for the duration and restored after.

## Where

- `services/_batch_utils.py` -- `compressed_hypertable_write_session` /
  `async_compressed_hypertable_write_session`
- `timescaledb_information.jobs` / `alter_job()` -- the pause/resume mechanism
- `services/regime_writer.py` -- the caller that surfaced this
