---
phase: 47
slug: shadow-mode-graduation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-22
---

# Phase 47 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `pytest.ini` / `setup.cfg` (project root) |
| **Quick run command** | `.venv/bin/pytest tests/unit/ -x -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/ -x -q`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 47-01 | regime-gate | 1 | SHADOW-01 | unit | `.venv/bin/pytest tests/unit/test_regime_gate.py -x` | ❌ W0 | ⬜ pending |
| 47-02 | cross-asset | 1 | SHADOW-02 | unit | `.venv/bin/pytest tests/unit/service_tests/ -x -k cross_asset` | ❌ W0 | ⬜ pending |
| 47-03 | roll-detection | 1 | SHADOW-03 | unit | `.venv/bin/pytest tests/unit/test_roll_detection_algorithm.py -x -v` | ✅ rewrite | ⬜ pending |
| 47-04 | dual-divergence | 2 | SHADOW-04 | unit | `.venv/bin/pytest tests/unit/intelligence/test_weight_updater.py -x -k shadow` | ❌ W0 | ⬜ pending |
| 47-05 | intel-04-migration | 2 | INTEL-04 | migration | Manual DB check | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_regime_gate.py` — stubs for SHADOW-01: parametric `apply_regime_gate()` using Settings `prob_min`/`dur_min`
- [ ] `tests/unit/intelligence/test_shadow_stats.py` — stubs for SHADOW-04: bootstrap CI, Prometheus gauge emission, 0-row guard
- [ ] `tests/unit/test_roll_detection_algorithm.py` — **full rewrite** (existing tests broken ratio logic — replace with calendar window + z-score approach)
- [ ] `production/migrations/049_roll_premium_pct.sql` — INTEL-04 column addition to `intelligence_features`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `CROSS_ASSET_ENABLED=true` live in production env | SHADOW-02 | Requires env var change + service restart | Set env var, restart `indicagent-cross-asset` + `indicagent-signal-generator`, query `signal_ledger` for `trad_CrossAssetDivergence` signals |
| `ROLL_MONITOR_ENABLED=true` roll event fires | SHADOW-03 | Requires real/simulated roll event + pipeline services running | Simulate roll event (or wait for calendar event), verify `contract_metadata.is_front_month` toggles and `system_events` table records the event |
| `roll_premium_pct` populated in `intelligence_features` | INTEL-04 | Requires a roll event to occur during live session | After migration: query `SELECT count(*) FROM intelligence_features WHERE roll_premium_pct IS NOT NULL AND ts > now() - interval '7 days'` — expect > 0 after roll |
| `trad_DualDivergence` fires live (IS_SHADOW removed) | SHADOW-04 | Requires N >= 50 resolved signals + win rate > 50% statistical gate | Query `signal_ledger WHERE setup_type = 'trad_DualDivergence' AND is_shadow = FALSE` — must have >= 50 rows resolved |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
