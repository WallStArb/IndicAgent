# Environment Cleanup — Design

**Date:** 2026-05-14  
**Scope:** Bug fixes for two log-flooding services + disk/topic cleanup

---

## Problem

Three distinct issues are degrading the environment:

1. **Signal tracker floods logs** — `signal_rejected: missing_signal_id` fires 43k+ times per day because `make_signal()` never generates a `signal_id` and the pipeline publisher never stamps one. Signal tracker rejects every inbound signal silently, so lifecycle tracking is effectively broken.

2. **Feature snapshot writer floods logs** — `snapshot_writer_parse_failed` fires 16k+ times per day. `_run()` in `feature_snapshot_writer_agent.py` falls into `else str(payload)` when `payload` is a `dict` (normal Kafka consumer output), producing Python repr (`{'key': 'val'}`) instead of valid JSON. `model_validate_json` then fails on every message.

3. **Disk waste** — 496MB of logs (many uncompressed rotated files), 4 dead Redpanda topics from a retired `INDICAGENT_ENV=production` environment.

---

## Changes

### Fix 1 — Stamp `signal_id` before publishing (`intelligence_pipeline_agent.py`)

In `_publish_signals_or_dlq`, alongside the existing `sig.setdefault("ttl_bars", ...)` block, add:

```python
sig.setdefault("signal_id", str(uuid4()))
```

This ensures every signal carries a stable ID before it reaches any downstream consumer (signal_tracker, signal_writer, lineage_writer). `signal_writer` already falls back to `uuid4()` if absent — after this fix both services see the same ID.

**Import:** add `from uuid import uuid4` to `intelligence_pipeline_agent.py`.

### Fix 2 — Handle dict payload in snapshot writer (`feature_snapshot_writer_agent.py`)

Change `_parse_record` signature to accept `dict | bytes | str` and route dict inputs through `model_validate` instead of `model_validate_json`:

```python
def _parse_record(self, raw: dict | bytes | str) -> BarIntelligenceRecord | None:
    try:
        if isinstance(raw, dict):
            return BarIntelligenceRecord.model_validate(raw)
        return BarIntelligenceRecord.model_validate_json(raw)
    except (ValidationError, ValueError) as exc:
        self.logger.warning("snapshot_writer_parse_failed", error=str(exc))
        self._parse_errors.inc()
        return None
```

Also update the call site in `_run()` to pass `payload` directly instead of the `str(payload)` fallback:

```python
record = self._parse_record(payload)
```

### Fix 3 — Log cleanup

- Force-run `logrotate -f /etc/logrotate.d/indicagent` to compress all uncompressed rotated files immediately (~350–400MB freed)
- Change `rotate 7` → `rotate 3` in `/etc/logrotate.d/indicagent` — 3 days is sufficient; logs compress to ~300KB each

### Fix 4 — Delete dead Redpanda topics

Delete 4 `production.*` topics left from a retired `INDICAGENT_ENV=production` environment — no running service uses this prefix:

```
production.intelligence
production.intelligence.i7.signals
production.lifecycle.transitions
production.swarm.alpha
```

---

## What Is Not Changed

- Dead service files (`ctx_writer_agent.py`, `bar_replay_provider_agent.py`, etc.) — these are implemented but not yet deployed; `production/systemd/` reference units exist for all of them.
- DB — tables are small (≤19MB), no cleanup needed.
- Active Redpanda topics with no-prefix names — all are in active use.

---

## Success Criteria

- `signal_tracker_compute_agent.log` no longer floods with `signal_rejected`
- `feature_snapshot_writer_agent.log` no longer floods with `snapshot_writer_parse_failed`
- `logs/` directory drops from ~496MB to ~100MB or less
- `docker exec redpanda rpk topic list` shows no `production.*` topics
