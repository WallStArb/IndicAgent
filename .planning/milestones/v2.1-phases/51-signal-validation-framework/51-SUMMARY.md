---
phase: "51"
plan: "01"
subsystem: "production/scripts"
tags: ["data-quality", "validation", "observability", "systemd"]
completed_date: "2026-03-26"
status: "complete-retroactive"
---

# Phase 51: Signal & Indicator Validation Framework — Summary

## Outcome

Phase closed retroactively — all 4 goals were delivered across prior phases (Phase 39 primarily) without a formal GSD execution.

## Goals vs Delivery

| Goal | Delivered by | Evidence |
|------|-------------|---------|
| Per-layer sanity checks (I1→I7 data quality) | Phase 39 (feat/039-06) | `production/scripts/data_quality_check.py` — checks null rates, pipeline staleness, lag P50/P95, OHLCV completeness, IC health |
| Signal outcome completeness audit | Phase 39 | `production/scripts/lifecycle_replay.py` `validate()` — confirms all resolved signals have outcome populated |
| Setup performance gate verification | Phase 39 | `check_ic_health()` in data_quality_check.py — IC score + significant fraction metrics |
| Automated validation on deploy | Phase 39 (feat/039-06) | `indicagent-data-quality.service` + `.timer` installed in `/etc/systemd/system/` — runs every 15 minutes |

## Key Artifacts

- `production/scripts/data_quality_check.py` — full audit script with Prometheus text file output at `/tmp/data_quality_metrics.prom`
- `src/observability/data_quality_metrics.py` — Prometheus gauges: `DQ_NULL_CIS_RATE`, `DQ_INTELLIGENCE_STALENESS_SECONDS`, `DQ_PIPELINE_LAG_P50_MS`, `DQ_PIPELINE_LAG_P95_MS`, `DQ_OHLCV_MISSING_BARS_DAILY`, `DQ_IC_SCORE`
- `/etc/systemd/system/indicagent-data-quality.timer` — 15-minute schedule
- Critical threshold exits (1% null CIS, >900s staleness, >500ms P95 lag)
