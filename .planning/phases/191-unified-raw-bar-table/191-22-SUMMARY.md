---
phase: 191-unified-raw-bar-table
plan: 22
subsystem: bars
tags: [tradier-retirement, code-deletion, integrity-checks, vendor-basis]
requires: [191-21]
provides: [tradier-free integrity_checks and vendor_basis, 31-name digest proof]
affects: [191-23, 191-25]
key-files:
  modified:
    - src/intelligence/bars/integrity_checks.py
    - src/intelligence/bars/vendor_basis.py
    - src/intelligence/bars/verdict_gate.py
    - services/bar_reconciliation_audit.py
    - tests/unit/bars/test_integrity_checks.py
    - tests/unit/bars/test_vendor_basis.py
    - tests/unit/bars/test_verdict_gate.py
    - tests/unit/services/test_bar_reconciliation_audit.py
    - docs/foundation/canonical-truth-registry.md
metrics:
  completed: 2026-10-29
---

# Phase 191 Plan 22: Tradier branches out of integrity_checks and vendor_basis

The Tradier-against-IBKR `vendor_basis_run` check, `classify_run`, `ratio_pairs`, `blocking`, `canonical_vendor`, `VENDOR_TRADIER` and `BasisRun.continuous_vendor` are gone; canonical 1d digests for the 31 baseline names are identical before and after.

## What changed

- `integrity_checks.py`: the `vendor_basis_run` verdict and its `basis_closes` / `classify_run` measurement are deleted; `CHECKS_1D` loses the name (9 checks); `NameReport1d` loses `basis_runs` and `blocking_runs`. `_PRIMARY_LABEL` no longer exists in the file (plan 21 or earlier removed it), so there was nothing to edit for it. `alpaca_basis_run` is the successor and is unchanged.
- `vendor_basis.py`: keeps `BP`, `BasisRun` (without `continuous_vendor`) and `find_basis_runs` (used by `alpaca_basis_runs`); the rest is deleted. Its imports of `SplitRecord`, `CANONICAL_1D_SOURCES`, `math` and `Mapping` went with it.
- `verdict_gate.REQUIRED_CHECKS["1d"]` drops `vendor_basis_run`; `services/bar_reconciliation_audit.py` drops the basis-run counting and the `n_basis_runs` log field (a Rule 3 change forced by the `NameReport1d` shape; plan 23 owns the rest of that service). Old `vendor_basis_run` rows in `integrity_monitor` are ignored by the gate.
- Tests: the Tradier basis cases in `test_integrity_checks.py` and `test_vendor_basis.py` (RJF and REX known answers, `classify_run`, `ratio_pairs`, canonical side) are deleted; `find_basis_runs` keeps its synthetic cases. `test_verdict_gate.py` and `test_bar_reconciliation_audit.py` follow the 9-check list. `canonical-truth-registry.md` names `alpaca_basis_run` in place of `vendor_basis_run`.

## Digest proof (T-191-48)

Probe: scratch script (not committed; the plan lists no new files), `digest_probe.py <baseline.json> <out.json>`, run with `PYTHONPATH=<tree>`. Per name it computes the stored canonical 1d `bar_content_digest` (all rows, non-quarantine flag rules) and the digest of `read_daily_inputs` + `derive_daily_v2` bars with the derivation's own flags. Validation: run on a `git archive HEAD` copy of origin/main (bcaabe934) it reproduces `logs/tradier_code_delete_digest_before.json` exactly (31 names, 0 differences, all four fields). Run on this tree after the edits: 31 names, 0 differences. The probe source is `/tmp/claude-1000/-home-bg-dev-indicagent/404d9460-4809-434a-a5ec-4345647e0431/scratchpad/digest_probe.py`.

## Removed-symbol decisions

| Symbol | Decision |
|---|---|
| `vendor_basis.VENDOR_TRADIER`, `VENDOR_IBKR`, `classify_run`, `ratio_pairs`, `blocking`, `canonical_vendor` | deleted; caller grep found only `integrity_checks` and `test_vendor_basis`. |
| `ops_d191q_arbitration.py` | needs no edit: it imports `VENDOR_TRADIER` from `daily_rule`, not `vendor_basis`, so it stays importable. Plan 25 deletes it. |
| `source_admission.py` and its test | KEPT. The whole module is Tradier admission, but `scripts/ops/bars/ops_source_policy.py` imports `Admission`, `common_session_closes`, `tradier_admission` (and `ops_source_policy` is imported by `ops_d191q_arbitration`). Deleting now breaks two scripts plan 25 owns. Plan 25 deletes `tradier_admission` from `ops_source_policy`, then this module and `tests/unit/bars/test_source_admission.py`. |
| `daily_rule.basis_closes` | no caller left except daily_rule's own tests; daily_rule is not edited, so it stays (candidate for the owner-approved arm deletion). |
| `vendor_arbitration.py` | still names Tradier throughout (the D-191-Q arbitration, a closed-window module `ops_d191q_arbitration` and `integrity_checks.ARBITRATED_THROUGH` use). Not in this plan's file list; left for plan 25 / the owner-approved arm deletion. The plan's done-grep therefore prints these lines plus `source_admission.py`. |

## Deviations from plan

- [Rule 3] Touched `verdict_gate.py` and `services/bar_reconciliation_audit.py` (neither is in the plan's file list): removing the check changes the `NameReport1d` shape and the required-check set. A hard-coded passing verdict was rejected as a silent wrong answer. Deploy note: the gate and the audit must land together; a running old audit still writes `vendor_basis_run` (harmless), a new audit with an old gate would hold names on a missing `vendor_basis_run` verdict after `report_max_age_hours`.
- `test_daily_rule.py`, the d2v2 fixture and its README are NOT edited: `daily_rule.py` keeps the Tradier arm (plan 21 note: its deletion needs an owner-approved follow-up), so removing its Tradier-reading cases would only lower coverage of live code. The fixture is still read by `test_daily_rule.py`.
- `source_admission.py` kept (see table).
- The /simplify and /code-review skills are not callable from this agent; the diff was self-reviewed by hand. The data lane runs the independent review.
- No fingerprinted batch writer was live; `integrity_checks`, `vendor_basis` and `bar_reconciliation_audit` are imported by D7 (timer service). The 186-26 rebuild code key should be checked by the data lane if it covers `integrity_checks`.

## Verification

- Full `tests/unit` (`-n auto`): all pass, exit 0.
- Imports: every `services/*.py` (17 need `services/` on the path like their entry points; all import with `PYTHONPATH=.:services`), `scripts/ops/bars/*.py` and `scripts/infrastructure/backfill/*.py` import cleanly.
- `git diff --stat -- src/intelligence/bars/daily_rule.py` is empty.
- ruff and black clean.

## Self-check: PASSED
