---
phase: 164
slug: smc-institutional-footprint-primitives
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-25
---

# Phase 164 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | pytest.ini / pyproject.toml |
| **Quick run command** | `.venv/bin/pytest tests/unit/ -q -k smc or -k structural` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -q` |
| **Estimated runtime** | ~{N} seconds — planner to confirm against current suite runtime |

---

## Sampling Rate

- **After every task commit:** Run quick run command
- **After every plan wave:** Run full suite command
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 120 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| {N}-01-01 | 01 | 1 | REQ-{XX} | T-{N}-01 / — | {expected secure behavior or "N/A"} | unit | `{command}` | ✅ / ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_regime_signals_breadth_vol.py`-style non-constant/non-NULL regression guard for each new SMC field, mirroring Phase 163's Plan 02 guard
- [ ] Fixtures for synthetic OHLCV series that trigger each SMC pattern (order block, FVG, liquidity sweep, etc.) deterministically

*Planner to confirm exact file names against RESEARCH.md's findings.*

---

## Manual-Only Verifications

*None identified — all phase behaviors (feature computation) have automated verification via unit tests against synthetic and historical bar fixtures.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
