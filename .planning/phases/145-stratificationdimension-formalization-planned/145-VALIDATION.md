---
phase: 145
slug: stratificationdimension-formalization-planned
status: planned
nyquist_compliant: true
wave_0_complete: true
created: 2026-08-06
updated: 2026-08-06
---

# Phase 145 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (project standard, `pytest.ini` at repo root) |
| **Config file** | `pytest.ini` — `testpaths = tests`, `python_files = test_*.py`, `asyncio_mode = auto` |
| **Quick run command** | `.venv/bin/pytest tests/unit/test_stratification_<name>.py -x -q` (per new test file) |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~60-120 seconds (full suite, project-standard) |

---

## Sampling Rate

- **After every task commit:** Run the relevant single new test file (`-x -q` fast-fail)
- **After every plan wave:** Run `.venv/bin/pytest tests/unit/ -v` (full suite)
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~120 seconds

---

## Per-Task Verification Map

No formal `REQUIREMENTS.md` IDs exist for this phase — mapped against CONTEXT.md's decisions
(D-01 through D-07), which function as this phase's real requirements.

| Decision | Behavior | Test Type | Automated Command | Owning Plan | Status |
|----------|----------|-----------|--------------------|-------------|--------|
| D-01 (row-grain, Option B) | `registry_name` encodes `(dimension, regime_group)` distinctly, e.g. `hmm_price_vol__equity` != `hmm_price_vol__rates`, and round-trips through `parse_registry_name` | unit | `.venv/bin/pytest tests/unit/test_stratification_contract.py -x -q` | 145-01 | ⬜ pending |
| D-02 (contract stays regime_group-agnostic) | Parametrized over all six live regime groups plus one invented group with identical behavior; `volatility_pct` source contains no hardcoded group name | unit | `.venv/bin/pytest tests/unit/test_stratification_contract.py -x -q` | 145-01, 145-04 | ⬜ pending |
| D-03 (BH-FDR across candidate pool) | `apply_bh_fdr` called exactly once per `regime_group` family over cumulative history; a marginal test loses eligibility as its own group's family grows but not another group's | unit | `.venv/bin/pytest tests/unit/test_stratification_gates.py -x -q -k fdr` | 145-02 | ⬜ pending |
| D-04 (effective-N from transitions) | `effective_n_from_transitions` returns transitions+1, collapses a 5000-bar constant sequence to 1, and safely handles empty/single/object-dtype input; gate 2 vetoes on floor breach | unit | `.venv/bin/pytest tests/unit/test_stratification_gates.py -x -q -k "effective_n or substitution"` | 145-02, 145-06 | ⬜ pending |
| D-05 (acausal-placebo registration gate) | Prefix-invariance and placebo-IC sub-checks each raise `AcausalPlaceboRegistrationViolation` on their respective leak shapes; a clean provider passes; the gate cannot be omitted from `validate_registration` | unit | `.venv/bin/pytest tests/unit/test_acausal_placebo_registration.py -x -q` | 145-03 | ⬜ pending |
| D-06 (`volatility_pct` pilot provider) | Conforming provider, causal `score()`, HMM-parity smoothing in `compute()`, clears the real D-05 gate | unit | `.venv/bin/pytest tests/unit/test_volatility_pct_pilot.py -x -q` | 145-04 | ⬜ pending |
| D-06 (full gate stack, real data) | Pre-registered scope, all five cascade stages executed against real corpus data, results written to a standalone artifact | integration (read-only live DB) | `.venv/bin/python scripts/analysis/volatility_pct_stratification_gate_pilot.py --dry-run` then the full run; artifact asserted by the JSON check in 145-05 Task 3 | 145-05 | ⬜ pending |
| D-07 (no `concept_registry` write; APR migration deferred) | Zero rows in `concept_registry`/`concept_transition_log` with `domain='regime_model'`; every deferred numeric constant carries a D-07 / Phase 170 comment; zero new migrations | unit + psql | `.venv/bin/pytest tests/unit/test_volatility_pct_pilot_artifact.py -x -q` and `psql -tAc "select count(*) from concept_transition_log where domain='regime_model';"` | 145-02, 145-03, 145-04, 145-05, 145-06 | ⬜ pending |
| `ic_engine.py` compatibility | `to_regime_pass` output is consumable by `services.ic_engine._build_regime_passes` without modifying `ic_engine.py` | unit | `.venv/bin/pytest tests/unit/test_stratification_contract.py -x -q -k ic_engine_compat` | 145-01 | ⬜ pending |
| Ring 0/1/2 boundary | No `.py` file under `src/intelligence/stratification/` imports from `services/` | unit (source assertion) | `.venv/bin/pytest tests/unit/test_stratification_contract.py -x -q -k ring` | 145-01 | ⬜ pending |
| Derived thresholds (D-04/D-06 closure) | `_MAX_CORRELATION_DEFAULT` and `_EFFECTIVE_N_FLOOR_DEFAULT` are non-None and equal the values recorded in the pilot artifact | unit | `.venv/bin/pytest tests/unit/test_stratification_gates.py -x -q -k derived` | 145-06 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Wave 0 is satisfied inside each plan: every plan's first task is the RED test file for the code
its later tasks implement. No test file is referenced by a verify command before the task that
creates it.

- [x] `tests/unit/test_stratification_contract.py` — created by 145-01 Task 1 (RED), consumed by 145-01 Task 2
- [x] `tests/unit/test_stratification_gates.py` — created by 145-02 Task 1 (RED), consumed by 145-02 Tasks 2/3 and extended by 145-06 Task 1
- [x] `tests/unit/test_acausal_placebo_registration.py` — created by 145-03 Task 1 (RED), consumed by 145-03 Task 2
- [x] `tests/unit/test_volatility_pct_pilot.py` — created by 145-04 Task 1 (RED), consumed by 145-04 Task 2
- [x] `tests/unit/test_volatility_pct_pilot_artifact.py` — created by 145-05 Task 1 (RED), consumed by 145-05 Task 2
- No new framework/config install needed — pytest is already fully configured project-wide.

---

## Manual-Only Verifications

*None — all phase behaviors have automated verification. This is a backend contract/governance
phase with no UI and no manual QA surface. The one live-data step (145-05 Task 3) is verified by a
scripted JSON assertion plus two psql count checks, not by inspection.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 120s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved at `/gsd-plan-phase 145`, 2026-08-06
