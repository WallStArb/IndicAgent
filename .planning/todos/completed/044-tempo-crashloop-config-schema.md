# indicagent-tempo container crash-looping — stale config schema

**Resolved 2026-07-10:** two config keys were stale for Tempo 3.0, not one. (1) The `compactor:`
block was removed entirely upstream — confirmed via Grafana's official migrate-to-3 doc: monolithic
deployments handle block retention/compaction internally in the live-store component, no replacement
config needed (`backend_scheduler`/`backend_worker` only apply to microservices-mode Tempo). Deleted
the block. (2) Fixing that surfaced a second, previously-masked parse failure: `usage_report:
reporting_enabled: false` is not a real Tempo 3.0 key — the actual top-level block is `reporting:
enabled: false` (confirmed against the `-reporting.enabled` CLI flag; Tempo silently accepted the
stale key as a no-op default-enabled report rather than a strict-unmarshal error, which is why it
hadn't been caught by the original diagnosis). Fixed both in `production/tempo.yaml`, restarted via
`docker compose up -d tempo`. Verified stable: `/ready` returns 200, `RestartCount` stopped
incrementing, no crash-loop restarts over several minutes of observation, and
`indicagent-otel-collector`'s `tempo` DNS-lookup errors (a symptom of the crash loop, not a separate
bug) stopped appearing after the fix. Left the residual `backend-scheduler`/`backend-worker`
"no jobs found" warn/error log lines alone — confirmed benign, self-throttling polling noise from a
component that isn't required in monolithic mode; log rotation caps (`max-size`/`max-file`, already
present) bound any growth.

**Found:** 2026-07-02, during a routine infra tidy-up pass (unrelated to active work).

`indicagent-tempo` (`grafana/tempo:3.0.0`) is in a permanent restart loop:

```
failed parsing config: failed to parse configFile /etc/tempo/tempo.yaml: yaml: unmarshal errors:
  line 22: field compactor not found in type app.Config
```

`production/tempo.yaml` line 22 has a top-level `compactor:` key:

```yaml
compactor:
  compaction:
    block_retention: 168h
```

This key's location (or name) no longer matches the config schema expected by Tempo 3.0's
`app.Config` struct. Container has been created "10 days ago" per `docker ps`, suggesting
this has been broken since that image version was deployed — distributed tracing (spans)
have not been ingested for some unknown period.

**Action:** Check Tempo 3.0's current config reference (config schema changed across major
versions — `compactor` may need to move under a different parent key, e.g. `storage.trace`
or a renamed top-level block) and fix `production/tempo.yaml` to match. Then:
```bash
cd production && docker compose up -d tempo
docker logs indicagent-tempo --tail 20   # confirm no more parse errors, container stays Up
```

**Blocked on:** nothing — safe to fix anytime; low urgency since it doesn't affect trading
pipeline correctness, only distributed-trace observability (spans still emit from services,
just aren't being collected/stored).
