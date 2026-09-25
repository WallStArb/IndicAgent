---
phase: 183
plan: 07
status: complete
requirements: [D-01, D-02, D-03, D-04, D-09, D-15, D-16, D-17, D-18, D-21, D-24, D-25]
---

# 183-07 summary: runner evidence mode, family 1 spec, CLI

Executed inline by the orchestrator.

## What was built

- `evidence.py`: the section 5 evidence record (`research_evidence_v1`): estimate, bootstrap
  standard error and interval, permutation p, per-period means, shape, shift count, power
  (null for evidence runs), coverage, turnover and a diagnostic-only cost band, resolution
  years at 80% power, hashes and guard summary; JSON-clean through `jsonable`, no tokens.
- `runner.py`: `run_family` in real mode (gate: committed spec blob, declared memory
  consistent with the member definition, members resolve, clean tree, no prior real run; then
  `start_runs` before any data; S0 with verified snapshot hash and manifest check; S1 twice;
  S2; S3 split per D-25; shift-floor refusal with `power=None`; S5 per member with R1 on its
  own 20-session residual vol and R2; terminal update) and synthetic mode (no git, ledger or
  snapshot). Guard failure ends rows `guard_failed`, a refusal `refused`, any other error
  `failed` and re-raises; a failing final write leaves rows `started`.
- `store.verify` now returns the full digest; `snapshot.universe_symbols` (validated column
  name) and `build_panel(manifest_extra=...)`.
- `research/specs/family1_intraday_periodicity.yaml`: the prereg in machine form. Values the
  prereg does not pin, chosen before any data: R1 vol window 20 sessions of residual bar
  returns, min fraction 0.5; min_shift 63 sessions (phase 179); cost band 1-5 bps per side
  (diagnostic only); guard probes 12 rows, S1 probe on the first 330 sessions.
- `scripts/research/run_spec.py`: the CLI (the only layer importing services); APR budget and
  worker keys; `RESULT` lines and per-member evidence JSON under `logs/research/runs/`.

## Verification

- `test_runner_evidence.py` (7), `test_runner_order.py` (14: call order, five pre-row
  refusals, declared-memory refusal, guard_failed, refused on the shift floor, failed with
  propagation, started left on a failing final write, synthetic mode isolation, store digest
  and tampering, universe dimension validation), `test_family1_spec.py` (2) pass.
- `repro_frozen.py`: three bit-identical lines.
- Synthetic CLI smoke (400 sessions x 4 bars x 30 names, `--workers 2`): exit 0,
  `RESULT {"member": "lag1", "status": "completed", ...}` and the same for mean5.
- Real mode with an uncommitted edit to the family 1 spec: `REFUSED spec differs from HEAD`,
  exit 2. Live `research_run` still has 0 rows.

## Also in this plan's push

- `test_portfolio_r1.py`'s speed test now bounds an order of magnitude (20 s) instead of the
  idle wall time (2 s), which failed `pytest tests/unit` whenever the machine was loaded
  (reported by peer sessions).
