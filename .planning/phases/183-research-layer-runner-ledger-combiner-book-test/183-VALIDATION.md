---
phase: 183
slug: research-layer-runner-ledger-combiner-book-test
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-09-25
---

# Phase 183 - validation strategy

> Per-phase validation contract for feedback sampling during execution. Requirement ids are
> the CONTEXT.md decision ids (D-01 to D-25).

## Test infrastructure

| Property | Value |
|----------|-------|
| Framework | pytest (`pytest.ini`, `--strict-markers`, asyncio auto, `slow` and `integration` markers registered) |
| Config file | `pytest.ini` |
| Quick run command | `.venv/bin/pytest tests/unit/research -q` |
| Full suite command | `.venv/bin/pytest tests/unit/ -q` |
| Bit identity | `.venv/bin/python scripts/analysis/sleeve_walk_forward/repro_frozen.py <scratch> --logs /home/bg/dev/indicagent/logs` |
| DB tests | `.venv/bin/pytest tests/integration/test_research_ledger.py -m integration -q` |
| Estimated runtime | about 15 s quick, 20 s bit identity |

## Sampling rate

- After every task commit: quick run command; plus `repro_frozen.py` for any change under
  `src/intelligence/research/`.
- After every plan wave: full unit suite; integration ledger tests once the migration exists.
- Before verify-work: full unit suite green, bit identity holds, integration ledger tests
  green, migration applied live and committed.
- Max feedback latency: 60 s.

## Per-requirement verification map

| Req | Behavior | Type | Automated command | File exists | Status |
|-----|----------|------|-------------------|-------------|--------|
| D-13, D-24 | R1 legs sum to +0.5/-0.5 per row; floor 20 gives no position; direction flips sign; own trailing vol, no covariance plan | unit, synthetic | `pytest tests/unit/research/test_portfolio_r1.py -q` | W0 | pending |
| D-14 | R2 on a 1-bar panel equals default path; per-session sums match a slow loop; observed and every shift aggregated alike; bootstrap block in sessions | unit, synthetic | `pytest tests/unit/research/test_evaluate_session_scoring.py -q` | W0 | pending |
| D-16 | frozen 179/181 artifacts bit-identical | script | `repro_frozen.py` | yes | pending |
| D-01 | canonical hash ignores whitespace/comments; strict schema rejects YAML type traps and extra keys; dotted paths limited to `families.` | unit | `pytest tests/unit/research/test_spec.py -q` | W0 | pending |
| D-02 | refuse untracked, staged-only, modified spec; dirty `src/intelligence/`; accept clean | unit, temp git repo | `pytest tests/unit/research/test_runner_git.py -q` | W0 | pending |
| D-02, D-07 | second real run for a spec hash refused in Python and by the partial unique index | integration | `pytest tests/integration/test_research_ledger.py -m integration -k spec_once` | W0 | pending |
| D-07 | trigger: started to terminal once; other edits, DELETE, TRUNCATE raise; snapshot hash set once | integration | `... -k trigger` | W0 | pending |
| D-08 | charge rules; refuse at M; APR keys seeded | integration | `... -k budget` | W0 | pending |
| D-05 | sole-writer grep with legacy migration allow-list | unit | `pytest tests/unit/research/test_ledger_sole_writer.py -q` | W0 | pending |
| D-03, D-04 | run order with fakes; crash leaves started; synthetic mode never touches git or ledger | unit | `pytest tests/unit/research/test_runner_order.py -q` | W0 | pending |
| D-09 | evidence JSON complete, NaN-free, plain types; book adds screen outcome | unit | `pytest tests/unit/research/test_runner_evidence.py -q` | W0 | pending |
| D-10, D-22 | ridge causal (probe), matches slow lstsq reference, fold-only standardization, complete cases, recovers planted coefficients | unit, synthetic | `pytest tests/unit/research/test_combiner.py -q` | W0 | pending |
| D-11 | joint roll via flattened stack; refit per shift proven; whole sessions; refuse below 600 | unit, synthetic | `pytest tests/unit/research/test_book.py -q` | W0 | pending |
| D-11 (calibration) | book null size within binomial band on unplanted panels | slow, synthetic | `pytest tests/unit/research/test_book.py -m slow -q` | W0 | pending |
| D-12, D-19, D-20, D-23 | early-stopped decision equals full-set decision; curtailed R equals fixed R; b_max arithmetic; generator hits planted IC and participation ratio | unit | `pytest tests/unit/research/test_power.py tests/unit/research/test_synthetic.py -q` | W0 | pending |
| D-15, D-25 | P1-P4 placement, slot sums, half-window rule, centred rank floor, declared memory; guards pass on synthetic panels; spec resolves | unit, synthetic | `pytest tests/unit/research/test_families_intraday.py -q` | W0 | pending |
| D-15 final | real evidence runs then book v1, through the runner only | runner, real data | runner CLI then ledger query | n/a | pending |

## Wave 0 requirements

- [x] `tests/unit/research/test_portfolio_r1.py`, `test_evaluate_session_scoring.py`
- [x] `tests/unit/research/test_spec.py`, `test_runner_git.py`, `test_runner_order.py`, `test_runner_evidence.py`
- [x] `tests/unit/research/test_combiner.py`, `test_book.py`, `test_power.py`, `test_synthetic.py`
- [x] `tests/unit/research/test_families_intraday.py`, `test_ledger_sole_writer.py`
- [x] `tests/integration/test_research_ledger.py`

## Manual-only verifications

| Behavior | Requirement | Why manual | Instructions |
|----------|-------------|------------|--------------|
| First real-data run records evidence rows and one book test row | D-15 final | needs the live 15m panel and hours of compute | run the runner on the committed spec, then query `research_run` |

## Validation sign-off

- [x] All tasks have an automated verify or a Wave 0 dependency
- [x] No 3 consecutive tasks without automated verify
- [x] Wave 0 covers all missing references
- [x] No watch-mode flags
- [x] Feedback latency under 60 s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-09-25 (plan checker: 0 blockers; per-task verifies exclude slow tests, which run at wave and phase gates)
