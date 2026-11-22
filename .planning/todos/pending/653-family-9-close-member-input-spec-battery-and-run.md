---
status: pending
priority: P2
filed: 2026-11-22
source: lead ruling 2026-11-22 (indicagent-bd), after the ranking in docs/plans/2026-11-22-next-counted-family-after-daily-residual.md
blocked_on: the daily residual and H-C seasonality runs are counted (both read runner functions this work edits)
---

# Family 9 (52-week high): the close member input, spec, battery and run

## What

The kernel `high_distance` and its member wrapper are on main (`src/intelligence/research/families/high_anchor.py`, tests in `tests/unit/research/test_families_high_anchor.py`). The family cannot run: a member receives only S1 residual returns (`families/common.py`), and F1 reads the total-return close. Preregistration: `docs/plans/2026-11-15-family9-52week-high-prereg-draft.md`, adopted as E26 (2 looks).

## Scope

1. One change adds a `close` member input kind (the panel's total-return close, `panel.total_return` declared) to `runner.member_input` and `runner._member_fn` and to `MemberInputSpec.kind` in `spec.py`. Both runner functions are in `battery_pass.RUNNER_STATISTIC_FUNCTIONS`, so the same commit rebinds `research/battery_passes/daily_residual_*.json` and `seasonality_*.json`. New optional spec fields go in `_OPTIONAL_*_FIELDS`.
2. `research/specs/family9_high_anchor_h5.yaml` and the core panel spec (spec-hash pin test), window 252 and 240 finite, sign +1.
3. A battery module (synthetic closes built from the battery's own panels) with the B2 size cells at 0.05, 0.01 and 0.00167, a bound pass record, `NULL_BATTERY` in `high_anchor.py`.
4. Gates before the run: todo 610 witness for 2005 to 2007 closes (or the with-and-without report), the split continuity and dividend basis gates of prereg section 6, a ledger line from the lead that the run is registered.

## Gates

`repro_frozen` bit-identical, suite exit 0, `/simplify`, independent review, record rebinds shown in the landing commit. No edit while a fingerprinted run that imports `runner` is live.
