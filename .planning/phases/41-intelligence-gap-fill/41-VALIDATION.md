---
phase: 41
slug: intelligence-gap-fill
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-20
---

# Phase 41 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `pyproject.toml` |
| **Quick run command** | `.venv/bin/pytest tests/unit/intelligence/ -x -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `.venv/bin/pytest tests/unit/intelligence/ -x -q`
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| FVG scoring | 01 | 1 | INTEL-01 | unit | `.venv/bin/pytest tests/unit/intelligence/test_cross_timeframe.py -x` | ✅ | ⬜ pending |
| FVG alignment zero | 01 | 1 | INTEL-01 | unit | `.venv/bin/pytest tests/unit/intelligence/test_cross_timeframe.py -x` | ✅ | ⬜ pending |
| OB scoring | 01 | 1 | INTEL-02 | unit | `.venv/bin/pytest tests/unit/intelligence/test_cross_timeframe.py -x` | ✅ | ⬜ pending |
| OB direction match | 01 | 1 | INTEL-02 | unit | `.venv/bin/pytest tests/unit/intelligence/test_cross_timeframe.py -x` | ✅ | ⬜ pending |
| VP near VAH boundary | 02 | 1 | INTEL-03 | unit | `.venv/bin/pytest tests/unit/intelligence/test_trade_framer.py -x` | ✅ | ⬜ pending |
| VP inside VA | 02 | 1 | INTEL-03 | unit | `.venv/bin/pytest tests/unit/intelligence/test_trade_framer.py -x` | ✅ | ⬜ pending |
| _select_vp session vs rolling | 02 | 1 | INTEL-03 | unit | `.venv/bin/pytest tests/unit/intelligence/test_trade_framer.py -x` | ✅ | ⬜ pending |
| HTF VP injection | 03 | 2 | INTEL-05 | unit | `.venv/bin/pytest tests/unit/intelligence/test_trade_framer.py -x` | ✅ | ⬜ pending |
| VWAP TF guard | 04 | 2 | INTEL-01/02 guard | unit | `.venv/bin/pytest tests/unit/intelligence/trading/ -x` | ✅ | ⬜ pending |
| ORB TF guard | 04 | 2 | INTEL-01/02 guard | unit | `.venv/bin/pytest tests/unit/intelligence/trading/ -x` | ✅ | ⬜ pending |
| Aggregator guard | 05 | 2 | invariant | unit | `.venv/bin/pytest tests/unit/intelligence/test_aggregator.py -x` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

New test cases added to existing test files (no new test files needed):

- [ ] `tests/unit/intelligence/test_cross_timeframe.py` — add `test_fvg_alignment_nonzero_when_fvg_present`, `test_fvg_alignment_zero_no_fvg`, `test_ob_alignment_nonzero_when_ob_present`, `test_fvg_alignment_direction_mismatch_reduces_score`
- [ ] `tests/unit/intelligence/test_trade_framer.py` — add `test_vp_target_near_vah_boundary_long`, `test_vp_target_inside_value_area_long`, `test_select_vp_session_for_short_tf`, `test_select_vp_rolling_for_long_tf`, `test_htf_vp_fallback_when_current_tf_absent`
- [ ] `tests/unit/intelligence/trading/test_anchored_vwap_reversion.py` — add `test_tf_guard_returns_no_signal_on_1h`
- [ ] `tests/unit/intelligence/trading/test_vwap_reclaim.py` — add `test_tf_guard_returns_no_signal_on_1h`
- [ ] `tests/unit/intelligence/trading/test_poc_rejection.py` — add `test_tf_guard_returns_no_signal_on_1h`
- [ ] `tests/unit/intelligence/trading/test_orb15.py` — add `test_tf_guard_returns_no_signal_on_1h`
- [ ] `tests/unit/intelligence/trading/test_orb30.py` — add `test_tf_guard_returns_no_signal_on_1h`
- [ ] `tests/unit/intelligence/trading/test_prev_day_level_test.py` — add `test_tf_guard_returns_no_signal_on_1h`
- [ ] `tests/unit/intelligence/test_aggregator.py` — add `test_active_signals_have_adjusted_rank_from_all_ranked`

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `i6_fvg_tf_alignment` non-zero in live `intelligence_features` | INTEL-01 | Requires live FVG data across TFs | Query: `SELECT i6->>'i6_fvg_tf_alignment' FROM intelligence_features WHERE ts > NOW() - INTERVAL '1h' AND i6->>'i6_fvg_tf_alignment' != '0.0' LIMIT 5` |
| HTF 1h VP reflected in signal_ledger targets | INTEL-05 | Requires live signal generation | Query `signal_ledger` for 1m/5m signals where `target_1` equals 1h POC level |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
