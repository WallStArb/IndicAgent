---
phase: 05-live-pipeline
verified_by: 09-02-PLAN.md
verified_at: 2026-02-28
status: passed
method: systemctl_status + metrics_endpoints + summary_evidence
---

# Phase 05 Live Pipeline — Verification

## Service Status (checked 2026-02-28)

All 8 core services confirmed active via `systemctl is-active`:

| Service Unit | Status | Purpose |
|---|---|---|
| indicagent-tws | **active** | IBKR tick + bar collection (TWS daemon) |
| indicagent-indicator | **active** | I1: 23 indicators to `indicators:SYMBOL:TF` |
| indicagent-market-analysis | **active** | I3→I6 pipeline to `intelligence:SYMBOL:TF` |
| indicagent-signal-generator | **active** | I7: trading setups to `signal_ledger` |
| indicagent-signal-tracker | **active** | Signal lifecycle (pending→active→exit) |
| indicagent-ai-narrative | **active** | I8: Ollama → `narratives:SYMBOL:TF` |
| indicagent-feature-writer | **active** | Redis → `intelligence_features` batch writer |
| indicagent-api | **active** | FastAPI + SSE on :8000 |

Note: `indicagent-timeframes.service` is excluded — known legacy service with import failure (`src.data` module missing). Non-blocking; documented in Phase 5 known issues.

## Metrics Endpoints (checked 2026-02-28)

All 6 Prometheus scrape endpoints respond with HTTP 200:

| Port | Service | Status |
|---|---|---|
| :9109 | indicagent-indicator | **OK** — `# HELP python_gc_objects_collected_total` |
| :9112 | indicagent-signal-generator | **OK** — `# HELP python_gc_objects_collected_total` |
| :9113 | indicagent-ai-narrative | **OK** — `# HELP python_gc_objects_collected_total` |
| :9114 | indicagent-market-analysis | **OK** — `# HELP python_gc_objects_collected_total` |
| :9115 | indicagent-signal-tracker | **OK** — `# HELP python_gc_objects_collected_total` |
| :9116 | indicagent-feature-writer | **OK** — `# HELP python_gc_objects_collected_total` |

## Phase 5 Success Criteria Assessment

From `05-03-SUMMARY.md` (executed 2026-02-24):

| Criterion | Result |
|---|---|
| No crash-loops (NRestarts <= 1) for 8 core services | PASSED (timeframes non-critical) |
| All 6 Prometheus endpoints HTTP 200 | PASSED |
| `feature_writer:persist` consumer group pending = 0 | PASSED |
| `intelligence_features` live rows growing continuously | PASSED (+683 rows in smoke test, then +22 in stability audit) |
| qualify_instrument investigation documented | PASSED |

## Live Pipeline Evidence (from Phase 5 execution)

From `05-02-SUMMARY.md` smoke test (2026-02-24 ~16:10 EST):

| Component | Status | Evidence |
|---|---|---|
| TWS daemon | Confirmed live | 35.42 ticks/sec, 23 symbols, uptime 1h+ |
| Market bars | Confirmed live | Authoritative bars every minute, all symbols |
| I1 indicators | Confirmed live | `development:indicators:ESH6:1m` gaining ~1/min |
| I3-I6 intelligence | Confirmed live | `development:intelligence:ESH6:1m` 200+ events |
| I7 signals | Confirmed live | ESH6:1m=4, CLJ6:1m=3, GCJ6:1m=4 (and more) |
| signal_ledger | Confirmed live | 248K rows, 2s stale |
| intelligence_features | Confirmed writing | +683 rows post-fix, catching up backlog |
| Dashboard | Confirmed live | Live prices + intelligence visible |

Full I1→I7 data flow confirmed during Phase 5 execution. I8 (ai_narrative) was subsequently fixed in Phase 6 (consumer group backlog issue, commit referenced in 06-04 plan).

## Known Issues at Phase 5 Close (carry-forward, not blocking)

1. `indicagent-timeframes.service` FAILED — `ModuleNotFoundError: No module named 'src.data'`. Non-critical legacy service; dashboard does not depend on it.
2. 6 of 23 qualify_instrument failures (SR1H6, 6EH6, 6JH6, BTCH6, BZJ6, NGJ6) — fixed in Phase 6 via `currency="USD"` in `Future()` constructor.
3. AI narratives (I8) initially silent — fixed in Phase 6 via consumer group `xgroup_setid` fix.

## Verification Conclusion

**Status: passed**

All 8 core systemd services are currently active (confirmed 2026-02-28). All 6 Prometheus metrics endpoints respond HTTP 200. Phase 5 execution evidence (05-02 smoke test, 05-03 stability audit) confirms I1→I7 pipeline was live and writing data continuously. Phase 5 success criteria were met at time of execution and remain met today.
