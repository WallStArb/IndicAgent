---
status: completed
priority: P1
filed: 2026-07-17
closed: 2026-07-17
source: root-cause investigation of the 143.1-07 corpus re-run's repeated cross-sectional
  connection-drop crash — the tempo crash loop surfaced as a network-churn contributing
  factor during that investigation, then turned out to be its own genuine, independent bug
---

# `indicagent-tempo` crash loop — todo 044's own fix was wrong, container has been broken for 3 weeks

## Finding

While root-causing the 143.1-07 corpus re-run's repeated crash (`server closed the
connection unexpectedly` in `ic_engine.py`'s cross-sectional pass — see the sibling fix in
`services/ic_engine.py`'s `_compute_cross_sectional_tf`, this same investigation), `docker ps -a`
showed `indicagent-tempo` in a continuous restart loop: `RestartCount=6457` over ~3 weeks,
restarting roughly every 60 seconds. Each restart churns a veth pair on `production_default` —
the same Docker bridge network TimescaleDB's container sits on — which was investigated as a
plausible aggravating factor for the corpus crash (though the corpus fix stands on its own
regardless of this).

**Root cause: todo 044 (closed 2026-07-10) misdiagnosed its own second finding.** That todo
correctly removed the stale `compactor:` block, but then "fixed" a second parse error by
changing `usage_report: reporting_enabled: false` to `reporting: enabled: false`, reasoning from
the `-reporting.enabled` CLI flag name. That reasoning was wrong — Grafana/Cortex-family
binaries commonly have a CLI flag namespace that does not mirror the YAML struct's field names.
Verified directly against the compiled binary (`grafana/tempo:3.0.0`, revision `d399842f5`,
unchanged since 2026-05-28 — this was never an image-version drift): extracted the binary
(`docker cp` from a stopped container) and grepped its struct tags with `strings`:

```
yaml:"usage_report,omitempty"
yaml:"reporting_enabled"
```

The correct structure was `usage_report: { reporting_enabled: false }` — i.e. the pre-044
config, not the post-044 one. Todo 044's fix regressed a working key into a broken one, and its
own "Verified stable" claim at the time was not actually checked against a real subsequent
restart cycle (or was checked against a stale container instance) — reproduced the parse
failure standalone (`docker run --rm -v .../tempo.yaml:/etc/tempo/tempo.yaml:ro
grafana/tempo:3.0.0 -config.file=/etc/tempo/tempo.yaml`) before touching anything live, then
verified the corrected form starts cleanly the same way.

## Fix

`production/tempo.yaml`: `reporting: enabled: false` → `usage_report: reporting_enabled: false`,
with a comment recording the correct struct-tag provenance so a third misdiagnosis doesn't
recur. Restarted via `docker compose up -d tempo` (`cd production`); confirmed no restart over a
90-second observation window (`RestartCount` unchanged, container status `Up`/`running`
throughout) — a clean pass where the pre-fix container would already have restarted at least
once.

## Not done

- `docker logs indicagent-tempo` clean startup was confirmed; span/trace ingestion itself
  (whether Grafana's Tempo datasource now shows fresh traces) was not separately verified —
  low priority, this is observability-only, doesn't affect the trading pipeline.
- Todo 044 itself is left as-is in `completed/` (not edited) — per this project's convention of
  not rewriting resolved-todo history; this todo is the correction record instead.
