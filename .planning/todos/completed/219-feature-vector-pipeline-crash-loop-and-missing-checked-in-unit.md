---
status: completed
priority: P0
filed: 2026-07-31
closed: 2026-07-31
source: writing tests/unit/services/test_service_auditor_registry_integrity.py for todo 200 -- the existence check surfaced this live
---

**CLOSED 2026-07-31** -- both parts done. (1) `"feature.smc.order_blocks.strength_fallback"`
added to `_THRESHOLD_KEYS` in `services/feature_vector_pipeline.py` (it already had a
`config_schema`/`config_state` row, default 0.5 -- only the `_THRESHOLD_KEYS` tuple entry was
missing, which is what `_check_prewarmed()`'s fail-loud guard was correctly catching).
`systemctl reset-failed` + `start` confirmed the daemon comes up and stays up (no crash-loop
restart observed). (2) `production/systemd/indicagent-feature-vector-pipeline.service` added,
transcribed directly from the live `systemctl cat` output (After=...wave2.target, matches the
box exactly) -- no live redeploy needed since content was already identical, this closes the
repo/deploy drift only. Todo 200's test (`test_service_auditor_registry_integrity.py`) updated
to drop the now-stale `_MISSING_UNIT_ALLOWLIST` entry for this unit.

# `indicagent-feature-vector-pipeline` has been crash-looping (start-limit-hit) for ~2 days,
# silently -- and its systemd unit file was never checked into `production/systemd/`

## What

While writing the todo-200 registry-integrity test, the existence check (does every
`_DAG_ORDER`/`_AGENT_ID_TO_UNIT` entry have a matching file under `production/systemd/`)
failed for `indicagent-feature-vector-pipeline` -- the checked-in unit set has no file for it,
even though it's a live, always-on daemon (DAG priority 6, NOT in `_ONESHOT_UNITS`).

Checking the live box directly (`systemctl status indicagent-feature-vector-pipeline`):
the unit **does** exist at `/etc/systemd/system/indicagent-feature-vector-pipeline.service`
(loaded, enabled) but has been `failed (Result: exit-code)` since **2026-07-29 07:36:31 EDT
(~2 days ago as of this filing)**, `start-limit-hit` -- systemd stopped even attempting
restarts.

`journalctl -u indicagent-feature-vector-pipeline` shows the actual crash:

```
AssertionError: feature.* key 'feature.smc.order_blocks.strength_fallback' read while
building FeatureFactoryConfig but missing from _THRESHOLD_KEYS -- it will always fall
through to its hardcoded default; add it to _THRESHOLD_KEYS
  File "services/feature_vector_pipeline.py", line 857, in _prewarm_threshold_config
  File "services/feature_vector_pipeline.py", line 730, in _float
  File "services/feature_vector_pipeline.py", line 718, in _check_prewarmed
```

This is `_check_prewarmed()`'s own fail-loud APR guard doing exactly what it's designed to
do (CLAUDE.md's "migrate-as-you-go" / APR-key-missing detection) -- but because it fires at
`_setup()` time, every restart attempt crashes identically, and systemd's `StartLimitBurst`
gave up after 5 attempts within `StartLimitIntervalSec=300`.

## Why this matters

`FeatureVectorPipeline` is the core v3.0 compute daemon -- CLAUDE.md's pipeline diagram:
`IBKR TWS -> FeatureVectorPipeline (compute) -> FeatureVectorWriter -> feature_vectors ->
forward_return_writer -> ic_engine -> ...`. If it's down, live streaming feature-vector
computation has stopped entirely (separate from the currently-running `ic_engine` corpus-rebuild
batch job, which reads already-written `feature_vectors` rows and is unaffected). This is
exactly the failure class todo 200 exists to catch -- a real outage `service_auditor.py`
never surfaced, this time because the unit isn't even in its checked-in registry, so nobody
would think to check `systemctl status` on it. Unknown how long ago live trading/shadow-mode
value was lost as a result, if this daemon is expected to run continuously; needs a decision
on urgency once picked up.

Separately: `production/systemd/` (the repo's checked-in copy of deployed units) has no file
for this unit at all, despite it being live-deployed and enabled on the box. Repo/deploy
drift -- worth fixing regardless of the crash, so a redeploy from a clean checkout doesn't
silently drop this daemon.

## Proposed fix (two independent parts, either can go first)

1. **Crash fix**: add `"feature.smc.order_blocks.strength_fallback"` to `_THRESHOLD_KEYS` in
   `services/feature_vector_pipeline.py` (near line 857/`_prewarm_threshold_config`), following
   the existing APR migrate-as-you-go pattern already used for every other `feature.*` key in
   that file. Then `systemctl reset-failed indicagent-feature-vector-pipeline && systemctl
   start indicagent-feature-vector-pipeline` and confirm it stays up.
2. **Repo drift fix**: copy the live unit file (`systemctl cat
   indicagent-feature-vector-pipeline` on the box) into `production/systemd/
   indicagent-feature-vector-pipeline.service`, diffed against a comparable already-checked-in
   unit (e.g. `indicagent-feature-vector-writer.service`) for consistency, then add it to
   `tests/unit/services/test_service_auditor_registry_integrity.py`'s cleanup (remove the
   now-unneeded allow-list entry, if todo 200 added one as an interim measure).

Not attempted in this session -- todo 200's task was explicitly scoped to writing the test,
not fixing `service_auditor.py` or any live service; this finding was surfaced as a side
effect of that test passing over real data, not chased down further.

## References

- `services/feature_vector_pipeline.py:718,730,857` -- crash site
- `tests/unit/services/test_service_auditor_registry_integrity.py` -- the test that surfaced
  this (todo 200)
- `production/systemd/indicagent-feature-vector-writer.service` -- comparable already-checked-in
  unit to model the new file on
