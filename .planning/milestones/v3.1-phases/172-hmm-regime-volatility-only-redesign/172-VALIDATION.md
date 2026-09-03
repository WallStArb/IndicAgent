---
phase: 172
slug: hmm-regime-volatility-only-redesign
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-08-08
---

# Phase 172 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (`pytest.ini` at repo root, `testpaths = tests`) |
| **Config file** | `/home/bg/dev/indicagent/pytest.ini` |
| **Quick run command** | `.venv/bin/pytest tests/unit/services/test_regime_writer.py -q` |
| **Full suite command** | `.venv/bin/pytest tests/unit/ -v` |
| **Estimated runtime** | ~ (existing suite already runs in CI; regime_writer file alone is fast) |

---

## Sampling Rate

- **After every task commit:** `.venv/bin/pytest tests/unit/services/test_regime_writer.py -q`
- **After every plan wave:** `.venv/bin/pytest tests/unit/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green, **plus** the null-arm wider-scope
  check (`hmm_production_regime_axes_null_arm_validation.py` at 15m/5m, larger symbol sample)
  must show a real-vs-null margin before any corpus-write wave proceeds — a domain-specific gate
  established by Phase 171's own investigation, not expressible as a unit test, and not optional.
- **Max feedback latency:** low tens of seconds for the automated suite; the null-arm check is a
  separate empirical gate run once before the corpus-relabel wave, not per-commit.

---

## Per-Task Verification Map

Filled in by the planner once tasks exist — mapped from the Phase Requirements → Test Map in
`172-RESEARCH.md`'s Validation Architecture section:

| Work item (ROADMAP "Rough shape") | Behavior | Test Type | Automated Command | File Exists |
|---|---|---|---|---|
| (1) APR migration + CVR entry | New `config_schema`/`config_state`/`controlled_vocabulary` rows present, `VocabularyDriftAuditor` recognizes the new namespace | unit | confirm `tests/unit/test_vocabulary_drift.py` (or equivalent) exists first | ❌ Wave 0 — verify before assuming |
| (2) Wire walk-forward against 2-col slice | Obs-matrix shape, `_build_label_map` vocab-param behavior at K=2/K=3, walk-forward fit unaffected by column count | unit | `.venv/bin/pytest tests/unit/services/test_regime_writer.py -q` | ✅ existing file, extend with new tests |
| (3) Null-arm check at wider scope | Real-vs-null margin holds at 15m/5m, larger symbol sample | manual/empirical — not pytest-covered | `python scripts/analysis/hmm_production_regime_axes_null_arm_validation.py --tf 15m 5m --symbols <list>` | ✅ script exists |
| (4) Full-corpus relabel | `regime_volatility` populated corpus-wide, no unexpected NULL gaps | integration/manual — reuse 171-03's provenance tool pattern | check `171-03-PLAN.md`'s artifact path before rebuilding | verify before reuse |
| (5) Downstream re-verification | `ic_engine.py`/`ensemble_trainer.py` unchanged in kind, keyed on new label set | integration | `.venv/bin/pytest tests/unit/ -k "ic_engine or ensemble_trainer" -q` + scoped `ic_engine.py --refresh` | ✅ existing tests, extend |

---

## Wave 0 Requirements

- [ ] Confirm whether `tests/unit/test_vocabulary_drift.py` (or equivalent) exists and covers
  namespace registration; if not, add coverage for the new `regime_volatility` CVR namespace as
  part of the migration task, not an afterthought.
- [ ] No new pytest fixtures expected — `test_regime_writer.py`'s existing synthetic-obs-matrix
  fixtures generalize directly to a 2-column case.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|--------------------|
| Null-arm reliability margin at wider scope (15m/5m, larger symbol sample) | Work item (3) | Empirical statistical validation against real vs. permuted data, not a deterministic code contract | `python scripts/analysis/hmm_production_regime_axes_null_arm_validation.py --tf 15m 5m --symbols <wider list>`; require margin comparable to the already-validated +0.62 (realized_vol) finding before proceeding to corpus relabel |
| Full-corpus relabel completeness | Work item (4) | Corpus-scale row-count/coverage check, not a unit-testable behavior | Reuse/extend the resumable NULL-out + provenance-verification tool from `171-03-PLAN.md` |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies — confirmed by gsd-plan-checker
  across all 19 tasks in the 7 finalized plans (172-01 through 172-07)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references — no MISSING references found
- [x] No watch-mode flags
- [x] Feedback latency acceptable (seconds, not minutes, for the automated path)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-08-08 (gsd-plan-checker VERIFICATION PASSED, 7/7 plans, 7/7 REQ IDs covered 1:1)
