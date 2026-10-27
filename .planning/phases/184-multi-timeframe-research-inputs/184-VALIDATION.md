---
phase: 184
slug: multi-timeframe-research-inputs
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-10-27
---

# Phase 184 - Validation strategy

> Per-phase validation contract for feedback sampling during execution. Source: 184-RESEARCH.md, Validation Architecture.

---

## Test infrastructure

| Property | Value |
|----------|-------|
| Framework | pytest with xdist (repo venv) |
| Config file | `pyproject.toml`; existing `tests/unit/research/` |
| Quick run command | `.venv/bin/pytest tests/unit/research/<item test file> tests/unit/research/test_spec_hashes_pinned.py -q` |
| Research suite | `.venv/bin/pytest tests/unit/research tests/unit/intelligence -n auto -q` |
| Full suite command | `.venv/bin/pytest tests/unit/ -n auto` |
| Determinism gate | `.venv/bin/python -m scripts.research.determinism.repro_frozen <scratch> --logs /home/bg/dev/indicagent/logs` |
| Parity gate | `.venv/bin/python scripts/research/backfill_attempt_series.py --compare-all` |
| Estimated runtime | quick under 30 s; research suite about 110 s; full suite about 70 s with -n auto |

---

## Sampling rate

- After every task commit: the item's test file plus `test_spec_hashes_pinned.py`.
- After every plan touching `src/intelligence/research/` or `src/intelligence/statistics/`: full unit suite, repro_frozen bit-identical, compare-all.
- Before `/gsd-verify-work`: full suite green, B6 battery report committed, repro_frozen bit-identical.
- Max feedback latency: 120 seconds (the B6 battery is a recorded run, not a per-commit check).

---

## Per-requirement verification map

| Requirement | Behavior | Test type | Automated command | File exists | Status |
|-------------|----------|-----------|-------------------|-------------|--------|
| MTF-B1a | high/low on request; absent fields leave old snapshot bytes | unit | `pytest tests/unit/research/test_panel_optional_fields.py -q` (extends 187-15's file) | no | pending |
| MTF-B1b | closes_at across half day, both DST days, missing final bar, NaT row, short 1h bucket | unit | `pytest tests/unit/research/test_clock.py -q` | no | pending |
| MTF-B1c | warmup prefix fetched, scored span unchanged | unit | `pytest tests/unit/research/test_feature_inputs.py -k warmup -q` | no | pending |
| MTF-B1d | non-derived 15m/1h vendor refused | unit | `... -k vendor` | no | pending |
| MTF-B1e | feature arrays content-hashed; edited array fails verify | unit | `... -k hash` | no | pending |
| MTF-B1f | missing batch, APR mismatch, mixed code_key each refuse | unit | `... -k provenance` | no | pending |
| MTF-B1g | first memory rows NaN; path-dependent column refused | unit | `... -k warmup_mask` | no | pending |
| MTF-B1h | below-floor column refused | unit | `... -k coverage` | no | pending |
| MTF-B1i | planted lookahead in a feature member fails S3 | unit | `pytest tests/unit/research/test_runner_feature_members.py -k causality -q` | no | pending |
| MTF-B1j | hmm_* member refused without rebuild batches | unit | `... -k hmm` | no | pending |
| MTF-B1k | unlisted feature_vectors reader fails CI | unit | `pytest tests/unit/test_feature_vectors_read_boundary.py -q` | no | pending |
| MTF-B2a | vectorized percentile / rolling max bit-equal after warmup; rolling VWAP memory bounded | unit | `pytest tests/unit/intelligence/test_research_kernels.py -q` | no | pending |
| MTF-B2b | kernel_source over present rows, float32, NaN until memory, gap rule | unit | `pytest tests/unit/research/test_kernel_source.py -q` | no | pending |
| MTF-B2c | expanding kernel refused; truncation probe passes research kernels, fails an acausal control | unit | `... -k guard5` | no | pending |
| MTF-B3a | align: latest finite, max_age in source rows, weekend not aging, NaT dst, broadcast source | unit | `pytest tests/unit/research/test_align.py -q` | no | pending |
| MTF-B3b | planted leak rejected or no edge | unit | `... -k leak` | no | pending |
| MTF-B3c | daily-on-intraday across half day and DST | unit | `... -k daily_on_intraday` | no | pending |
| MTF-B4 | lag curve on synthetic AR predictor matches closed form; band from shifts; record unread | unit | `pytest tests/unit/research/test_term_structure_lag.py -q` | no | pending |
| MTF-B5 | menu literal; FIR weights; memory reach <= declared | unit | `pytest tests/unit/research/test_smoothing.py -q` | no | pending |
| MTF-B6 | E17 size at 0.05 / 0.01 / 0.00167 on persistent cells | battery | `.venv/bin/python scripts/research/e17_null_battery.py <out.json> --battery src.intelligence.research.null_battery_persistent --sims 1000 --workers 6` | no | pending |
| MTF-B7 | bit-identical, pinned hashes, compare-all | gate | determinism and parity gates above | yes | pending |
| MTF-B8a | knowledge cutoff, decision-time join, max age NaN, basis refusal | unit | `pytest tests/unit/research/test_economic_block.py -q` | no | pending |
| MTF-B8b | shifted rerun recorded | unit | `... -k shift_test` | no | pending |

Status: pending · green · red · flaky

---

## Wave 0 requirements

- [ ] Shared synthetic fixtures: a small multi-timeframe bar set (5m to derived 15m/1h to 1d) spanning a half day (2024-11-29) and both 2024 DST transitions (2024-03-11, 2024-11-04), plus a fake `provenance_batch` row set, in `tests/unit/research/conftest.py` or a fixture module.
- No framework install needed.

---

## Manual-only verifications

| Behavior | Requirement | Why manual | Instructions |
|----------|-------------|------------|--------------|
| E17 size on persistent predictors | MTF-B6 | Long battery run, recorded once | Run the battery command, commit the report to `184-BATTERY.md` |
| Real-data S0 read of rebuilt `feature_vectors` | MTF-B1 | Needs 186-27's swapped table | After 186-27, one dry S0 build on the rebuilt table; record row counts and refusals |

---

## Validation sign-off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all missing references
- [ ] No watch-mode flags
- [ ] Feedback latency under 120 s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
