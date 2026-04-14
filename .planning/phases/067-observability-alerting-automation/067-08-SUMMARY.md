---
phase: 067-observability-alerting-automation
plan: 08
type: gap-closure
completed_date: "2026-04-14T08:13:56Z"
duration_seconds: 140
tasks_completed: 1
tasks_total: 1
subsystem: Grafana Alerting
tags: [grafana, prometheus, metrics, alerting, bug-fix]
---

# Phase 067 Plan 08: Fix Grafana Metric Name in Alert Rule and Dashboard

**One-liner:** Fixed CRITICAL alert rule `signals_dropped` and operations dashboard panel to reference correct Prometheus metric `signal_writer_agent_buffer_overflow_total` instead of nonexistent `signal_writer_buffer_dropped_total`.

## Summary

This gap-closure plan fixed a critical bug in Grafana alerting configuration where the `signals_dropped` alert rule was querying a nonexistent Prometheus metric. The alert rule expression and operations dashboard panel both referenced `signal_writer_buffer_dropped_total`, but the actual metric emitted by `BaseWriterAgent` follows the pattern `{agent_snake}_buffer_overflow_total`, which resolves to `signal_writer_agent_buffer_overflow_total` for the signal writer.

Without this fix, the CRITICAL alert for signal data loss would never fire, meaning training data could be dropped without operator notification.

## Changes Made

### Task 1: Fix nonexistent metric name in Grafana alert rule and dashboard

**Files modified:**
- `production/grafana/provisioning/alerting/alert-rules.yml`
- `production/grafana/dashboards/operations.json`

**Changes:**
1. Fixed alert rule description (line 117): Updated from `signal_writer_buffer_dropped_total` to `signal_writer_agent_buffer_overflow_total`
2. Fixed dashboard panel query (line 502): Updated from `rate(signal_writer_buffer_dropped_total[1m])` to `rate(signal_writer_agent_buffer_overflow_total[1m])`
3. Alert rule expression (line 93) was already correct and required no change

**Verification:**
- Zero occurrences of `signal_writer_buffer_dropped_total` in both files
- Three occurrences of `signal_writer_agent_buffer_overflow_total` (2 in alert-rules.yml, 1 in operations.json)

## Deviations from Plan

**None** — plan executed exactly as written. The alert rule expression was already correct, which was a minor deviation from the task description that expected 2 substitutions in alert-rules.yml, but only the description required fixing.

## Threat Surface Scan

**No new threat surface introduced.** This fix corrects an existing misconfiguration that prevented a security-relevant alert from firing. The threat model already identified this issue (T-067-08-01: Denial of Service via silent alert failure).

## Verification

**Acceptance criteria met:**
- [x] Zero occurrences of `signal_writer_buffer_dropped_total` in alert-rules.yml
- [x] Zero occurrences of `signal_writer_buffer_dropped_total` in operations.json
- [x] At least 2 occurrences of `signal_writer_agent_buffer_overflow_total` in alert-rules.yml
- [x] At least 1 occurrence of `signal_writer_agent_buffer_overflow_total` in operations.json

**Automated verification passed:**
```bash
grep -c "signal_writer_buffer_dropped_total" production/grafana/provisioning/alerting/alert-rules.yml production/grafana/dashboards/operations.json
# Output: Zero occurrences - fix complete

grep -c "signal_writer_agent_buffer_overflow_total" production/grafana/provisioning/alerting/alert-rules.yml production/grafana/dashboards/operations.json
# Output: alert-rules.yml:2, operations.json:1
```

## Technical Details

**Root cause:** The metric name `signal_writer_buffer_dropped_total` was likely a typo or outdated reference from before `BaseWriterAgent` metric standardization. The actual metric follows the naming pattern established in `src/core/agent/base_writer.py` line 87-88:

```python
self._buffer_overflow_total = _get_or_create_counter(
    f"{agent_snake}_buffer_overflow_total",
    f"Rows dropped due to buffer overflow in {name}",
)
```

For `SignalWriterAgent`, this produces `signal_writer_agent_buffer_overflow_total`.

**Impact:** The CRITICAL alert `signals_dropped` was completely non-functional. If signal writer buffer overflow occurred (training data loss), no alert would fire to telegram-critical contact point.

**Fix scope:** Only metric name substitutions were made. No other alert rules, panels, or configurations were modified.

## Next Steps

After deployment, verify the alert fires correctly by:
1. Checking Grafana alert rule state transitions to "Alerting" when `signal_writer_agent_buffer_overflow_total` increases
2. Confirming telegram-critical contact point receives notification
3. Validating operations dashboard "Signal Writer Buffer Drops" panel shows data

No infrastructure restarts required — Grafana auto-reloads provisioning changes.

## Commit

**Commit hash:** `780b87b6`
**Commit message:** `fix(067-08): fix Grafana metric name from signal_writer_buffer_dropped_total to signal_writer_agent_buffer_overflow_total`

## Self-Check: PASSED

- [x] Commit exists in git log
- [x] All task completion criteria met
- [x] Verification passed
- [x] No stubs introduced
- [x] SUMMARY.md created in plan directory
