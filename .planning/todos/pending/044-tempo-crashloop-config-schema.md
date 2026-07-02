# indicagent-tempo container crash-looping — stale config schema

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
