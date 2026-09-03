---
phase: 146
slug: empirical-instrument-tag-calibrator
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-17
---

# Phase 146 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (`.venv/bin/pytest`) |
| **Config file** | none dedicated — project-wide `tests/unit/` convention |
| **Quick run command** | `.venv/bin/pytest tests/unit/test_factor_math.py tests/unit/test_spread_leg_pair_validity.py tests/unit/test_tag_calibrator.py -v` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -q` |
| **Estimated runtime** | ~60-90 seconds (project-wide unit suite) |

---

## Sampling Rate

- **After every task commit:** Run that task's own new test file (`test_factor_math.py`, `test_spread_leg_pair_validity.py`, or `test_tag_calibrator.py`)
- **After every plan wave:** `.venv/bin/pytest tests/unit/ -q` (full suite must stay green)
- **Before `/gsd:verify-work`:** Full suite green + zero new `test_market_data_ohlcv_boundary.py` allow-list entries for this phase's files + manual SQL spot-checks for Wave 0 data cleanup (credit merge, housing_cycle deletion, spread_leg evidence backfill) + a live dry-run of `TagCalibrator` against a small symbol subset before enabling any systemd timer
- **Max feedback latency:** ~90 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 146-0X-01 | TBD | 0 | TAG-03 | — | `spread_leg` evidence contract: every row's `evidence->>'pair'` resolves to a valid symbol, symmetric | unit | `.venv/bin/pytest tests/unit/test_spread_leg_pair_validity.py -v` | ❌ W0 | ⬜ pending |
| 146-0X-02 | TBD | 0 | Schema (D-10) | — | `instrument_tags` migration adds `valid_from`/`valid_to` without breaking existing rows | manual SQL | `psql ... -c "\d instrument_tags"` post-migration | N/A | ⬜ pending |
| 146-0X-03 | TBD | 0 | D-03/D-07 | — | credit_cycle merged into credit_risk; housing_cycle deleted | manual SQL | `SELECT * FROM instrument_tags WHERE tag IN ('credit_cycle','housing_cycle')` (expect 0 rows) | N/A | ⬜ pending |
| 146-0X-04 | TBD | 1 | TAG-01 | — | OLS loading computation matches expected value on synthetic fixture data | unit | `.venv/bin/pytest tests/unit/test_factor_math.py::test_ols_loading_synthetic -x` | ❌ W1 | ⬜ pending |
| 146-0X-05 | TBD | 1 | TAG-01 | — | HAC-adjusted standard error inflates correctly under autocorrelated synthetic data | unit | `.venv/bin/pytest tests/unit/test_factor_math.py::test_hac_se_inflation -x` | ❌ W1 | ⬜ pending |
| 146-0X-06 | TBD | 1 | TAG-01 | — | Long-short constructor (HYG-IEF/TIP-IEF/IEF-SHY/XLE-SPY) produces correct spread return series | unit | `.venv/bin/pytest tests/unit/test_factor_math.py::test_long_short_constructor -x` | ❌ W1 | ⬜ pending |
| 146-0X-07 | TBD | 1 | TAG-01 | — | F6.1 self-regression skip (`symbol == factor_series`) | unit | `.venv/bin/pytest tests/unit/test_tag_calibrator.py::test_skips_self_regression -x` | ❌ W1 | ⬜ pending |
| 146-0X-08 | TBD | 1 | TAG-01 | — | BH-FDR correction applied at run level, not per-hypothesis | unit | `.venv/bin/pytest tests/unit/test_tag_calibrator.py::test_run_level_fdr -x` | ❌ W1 | ⬜ pending |
| 146-0X-09 | TBD | 1 | TAG-01 | — | Expiry hysteresis: single failing run does not expire | unit | `.venv/bin/pytest tests/unit/test_tag_calibrator.py::test_expiry_hysteresis -x` | ❌ W1 | ⬜ pending |
| 146-0X-10 | TBD | 1 | TAG-01 | — | `vol_beta` reuses `breadth_vol._compute_vix_pct_rank` (import/call correctness) | unit | `.venv/bin/pytest tests/unit/test_tag_calibrator.py::test_vol_beta_uses_breadth_vol_proxy -x` | ❌ W1 | ⬜ pending |
| 146-0X-11 | TBD | 1 | TAG-01 (boundary) | — | Daily-return reads use `market_data_ohlcv_tradeable`, not raw table | CI guard | `.venv/bin/pytest tests/unit/test_market_data_ohlcv_boundary.py -v` (expect zero new allow-list entries) | ✅ exists | ⬜ pending |
| 146-0X-12 | TBD | 1 | TAG-03 | — | Definitional tags never written by the calibration loop | unit | `.venv/bin/pytest tests/unit/test_tag_calibrator.py::test_skips_definitional_tags -x` | ❌ W1 | ⬜ pending |
| 146-0X-13 | TBD | 3 | TAG-02 | — | Phase 2 regime-conditioning — design-only, no code | N/A | N/A | N/A | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky. Task IDs are placeholders — the planner assigns real plan/task IDs; this table's rows are the acceptance surface each plan's tasks must satisfy.*

---

## Wave 0 Requirements

- [ ] `tests/unit/test_spread_leg_pair_validity.py` — does not exist yet; D-09's boundary-style test (every `spread_leg` row's `evidence->>'pair'` resolves to a valid `instruments.symbol`, pair references symmetric). Model on `tests/unit/test_market_data_ohlcv_boundary.py`'s allow-list-and-assert pattern, adapted for a data-contract check.
- [ ] `tests/unit/test_factor_math.py` — new module, no existing test file.
- [ ] `tests/unit/test_tag_calibrator.py` — new service, no existing test file.
- [ ] No test framework install needed — pytest already configured and green project-wide; `statsmodels`/`scipy` already present for the statistical assertions these new tests need.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `instrument_tags` schema post-migration | Schema (D-10) | DDL shape verification, not a pytest assertion | `PGPASSWORD=postgres psql -U postgres -h localhost -d indicagent -c "\d instrument_tags"` — confirm `valid_from`/`valid_to` present |
| Wave 0 data cleanup (credit merge, housing_cycle deletion) | D-03/D-07 | One-time data migration verification, not an ongoing code invariant | `SELECT * FROM instrument_tags WHERE tag IN ('credit_cycle','housing_cycle')` — expect 0 rows |
| Live dry-run of `TagCalibrator` before enabling any systemd timer | TAG-01 | Every project systemd timer is currently disabled (per CLAUDE.md); enabling one is an operator sign-off, not this phase's automated test surface | Run the oneshot manually against a small symbol subset, inspect `instrument_tags` output rows before considering scheduling |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (3 new test files above)
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
