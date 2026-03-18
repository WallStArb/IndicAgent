---
phase: 37
slug: cross-asset-intelligence-service
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-18
---

# Phase 37 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `pyproject.toml` (existing) |
| **Quick run command** | `.venv/bin/pytest tests/unit/test_cross_asset_features.py tests/unit/test_cross_asset_divergence_plugin.py -v` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/test_cross_asset_features.py tests/unit/test_cross_asset_divergence_plugin.py -v`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 037-01-01 | 01 | 1 | XA-01, XA-02 | unit | `.venv/bin/pytest tests/unit/test_cross_asset_features.py -v` | ❌ W0 | ⬜ pending |
| 037-01-02 | 01 | 1 | XA-01 | manual | `docker exec redpanda rpk topic consume development.cross_asset --num 1` | N/A | ⬜ pending |
| 037-02-01 | 02 | 1 | XA-03 | unit | `.venv/bin/pytest tests/unit/test_cross_asset_divergence_plugin.py -v` | ❌ W0 | ⬜ pending |
| 037-03-01 | 03 | 2 | XA-01, XA-03 | unit | `.venv/bin/pytest tests/unit/test_cross_asset_pipeline_wiring.py -v` | ❌ W0 | ⬜ pending |
| 037-03-02 | 03 | 2 | XA-01, XA-03 | manual | `.venv/bin/python production/scripts/historical_backfill.py --replay-only --symbols ESM6 --days 2` | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_cross_asset_features.py` — stubs for XA-01, XA-02 (spread_z, corr_break, buffer management)
- [ ] `tests/unit/test_cross_asset_divergence_plugin.py` — stubs for XA-03 (plugin fire conditions, regime-biased direction)
- [ ] `tests/unit/test_cross_asset_pipeline_wiring.py` — stubs for XA-01, XA-03 (TIER_I7 registration, feature_writer frame injection)

*All test file stubs are created within their respective plan tasks (Wave 0 is embedded in plan task acceptance criteria).*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `indicagent-cross-asset` service starts and publishes to Redpanda | XA-01 | Requires live Redpanda + IBKR data | `sudo systemctl start indicagent-cross-asset && docker exec redpanda rpk topic consume development.cross_asset --num 1` |
| `es_nq_spread_z`, `es_rty_spread_z`, `eq_corr_break` in payload | XA-02 | Requires live Kafka message | `docker exec redpanda rpk topic consume development.cross_asset --num 1 \| python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(list(d.keys()))"` |
| `trad_CrossAssetDivergence` fires in replay | XA-03 | Requires historical data replay | `.venv/bin/python production/scripts/historical_backfill.py --replay-only --symbols ESM6 --days 2` |
| Service registered in CLAUDE.md services table | XA-01 | Documentation audit | Grep CLAUDE.md for `cross_asset` and `:9118` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
