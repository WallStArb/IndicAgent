---
claimable: true
status: pending
priority: P3
filed: 2026-11-27
source: todo 649 timer check (indicagent-a1, lead ruling 2026-11-27)
---

# split_feed_auditor emits its defect counts as metrics, not only a log line

## What

`services/split_feed_auditor.py` reports `n_inactive_ignored`, `n_recorded`, `n_candidates`, `n_unseen` and `n_overdue` only in the `split_feed_auditor.judged` log line. Prometheus sees one `job_completed_total{job_name="split-feed-auditor", status}` per run, so the base rate of defect classes (todo 649 closing criterion) and a Grafana trend need a log parse.

## Scope

Add one gauge per class (or one gauge with a `class` label) through `src/observability/metrics.py`, set once per run next to the `JOB_COMPLETED_TOTAL.add` call, and flush with the existing `flush_and_shutdown_metrics()`. Add the series to the metric-ref test's declared names if the test does not already pick them up, and one panel next to the oneshot panel on the operations dashboard.

## Gates

`tests/unit/services/test_split_feed_auditor.py` covers the emitted values; `tests/unit/observability/test_alert_and_dashboard_metric_refs.py` passes. The change edits auditor code, so it needs /simplify and /review; it is not in any pin closure.

## Not blocking

The alerts for a missed fire and for the `gap_found` and `candidates` statuses (`SplitFeedAuditorMissed`, `SplitFeedAuditorFinding`) read only `job_completed_total` and do not wait for this.

Claim note (lead 2026-11-27): timer-run code; edit it only in a detached worktree off `origin/main` and land only CI-green.
