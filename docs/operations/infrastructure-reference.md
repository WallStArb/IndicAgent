# Infrastructure Reference

**Last Updated:** 2026-05-02

Operational details moved from CLAUDE.md to reduce context size.

## Observability Stack

All telemetry is push-based — services push OTLP to the Collector, no per-service scrape endpoints.

| Container | Port(s) | Purpose |
|-----------|---------|---------|
| `otel-collector` | `:4317` (gRPC), `:4318` (HTTP), `:8889` (Prometheus exporter) | Central telemetry hub — receives metrics/traces/logs from all services, fans out to Prometheus/Tempo/Loki |
| `indicagent-prometheus` | `:9090` | Scrapes OTel Collector `:8889` only; evaluates alert rules |
| `indicagent-grafana` | `:3001` | Dashboards — datasources: Prometheus, Tempo, Loki |
| `indicagent-loki` | `:3100` | Log aggregation (receives from OTel Collector) |
| `indicagent-tempo` | `:3200` (HTTP), `:4317` (OTLP) | Distributed traces (receives from OTel Collector) |
| `indicagent-alertmanager` | `:9093` | Alert routing — receives from Prometheus |
| `indicagent-mlflow` | `:5000` | ML experiment tracking |
| `indicagent-langfuse` | `:3000` (internal) | LLM call observability |

**Verify Prometheus rules loaded:**
```bash
docker exec indicagent-prometheus wget -qO- http://localhost:9090/api/v1/rules
```

**Check OTel Collector is receiving:**
```bash
docker logs indicagent-otel-collector --tail 20
```

**Grafana datasources config:** `production/grafana/provisioning/datasources/`
**Alert rules:** `production/alertmanager-rules.yml` (must be volume-mounted — Prometheus silently loads zero rules if missing)

## Data Pipeline Debugging

When investigating "service not writing to database":
1. **Check service health metrics first** — `events_consumed` and `batches_written` in logs. If increasing, service is working.
2. **Check which symbols ARE in target table** — `SELECT DISTINCT symbol FROM intelligence_features WHERE ts > NOW() - INTERVAL '2 hours';`
3. **Trace data flow upstream** — TWS → bars → indicator → intelligence → feature_writer → DB
4. **Verify service configs include the symbol** — Check startup logs for `"symbols"` list
5. **Check prerequisite data exists** — New contracts need historical backfill before intelligence pipeline processes them
6. **Kafka/IBKRProvider verification** — `docker exec redpanda rpk topic consume market.bars --offset N` (or `--from-end`). Provider emissions: `journalctl -u indicagent-ibkr-provider --since "2 minutes ago" | grep "1m bar emitted"`. If bars emitted but Kafka stale: `grep "Published to Kafka successfully"`. Merger routing: `journalctl -u indicagent-provider-merger --since "2 minutes ago"`.

## Sudo

`echo 'PASSWORD' | /usr/bin/sudo.ws -S <cmd>` — plain sudo active via `update-alternatives` (switched 2026-03-15; sudo-rs blocked stdin). For heredocs, write to `/tmp` first then `sudo cp`. Password stored in memory, not here.

## INDICAGENT_ENV Mismatch

Services bake their topic prefix at startup from `.env`. If `INDICAGENT_ENV` changes between restarts, services use different topic names and bars stop flowing silently. Symptom: IBKR provider emits to `market.bars.raw.ibkr` but merger consumes `development.market.bars.raw.ibkr`. Fix: restart all pipeline services together after any `INDICAGENT_ENV` change. Diagnose: `grep topics_consumed logs/provider_merger_agent.log`.

## Environment Variables

`INDICAGENT_ENV`, `DATABASE_URL` (postgres), `IBKR_HOST=192.168.1.157`, `IBKR_PORT=7497`, `OLLAMA_BASE_URL=:11434`, `OLLAMA_DEFAULT_MODEL=gemma4:e4b`

## CodeRabbit Notes

- 150 files max per review. Use `--base HEAD~N` to review recent commits.
- Process can get killed (exit code 137/OOM) on large diffs — review smaller chunks.
- On main: `coderabbit review --plain -t all` fails with "no merge base". Use `-t uncommitted` instead.
- Simplify workflow: Launches 3 parallel agents (reuse, quality, efficiency).

## Pre-Commit Hook

Location: `.git/hooks/pre-commit` (not in version control). When exclusions need updating for non-plugin infrastructure classes, edit line 54 grep pattern. Current exclusions: Plugin|Test|Data|Protocol|Enum|Error|Exception|Config|Result|State|Score|Frame|Entry|Event|Spec|Type|Info|Registry|Manager|Builder|Handler|Tracker|Scorer|Aggregat|Transition|Monitor|Stage|Runner|Client|Service|Target|Profile|Weight|Provider|Chain
