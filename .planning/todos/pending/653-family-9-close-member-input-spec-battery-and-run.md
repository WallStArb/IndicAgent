---
status: pending
priority: P2
filed: 2026-11-22
source: lead ruling 2026-11-22 (indicagent-bd), after the ranking in docs/plans/2026-11-22-next-counted-family-after-daily-residual.md
blocked_on: the battery pass (scope 3, a heavy run the lead launches under seed base 9,000,000, ledger 2026-11-23d) and the lead's run registration (scope 4)
---

# Family 9 (52-week high): the close member input, spec, battery and run

## What

The kernel `high_distance` and its member wrapper are on main (`src/intelligence/research/families/high_anchor.py`, tests in `tests/unit/research/test_families_high_anchor.py`). The family cannot run: a member receives only S1 residual returns (`families/common.py`), and F1 reads the total-return close. Preregistration: `docs/plans/2026-11-15-family9-52week-high-prereg-draft.md`, adopted as E26 (2 looks).

## Scope

1. One change adds a `close` member input kind (the panel's total-return close, `panel.total_return` declared) to `runner.member_input` and `runner._member_fn` and to `MemberInputSpec.kind` in `spec.py`. Both runner functions are in `battery_pass.RUNNER_STATISTIC_FUNCTIONS`, so the same commit rebinds `research/battery_passes/daily_residual_*.json` and `seasonality_*.json`. New optional spec fields go in `_OPTIONAL_*_FIELDS`.
2. DONE 2026-11-23: `research/specs/family9_high_anchor_h5.yaml` and `..._h5_core.yaml`, hashes pinned in `tests/unit/research/test_spec_hashes_pinned.py`, window 252 and 240 finite, sign +1, `panel_source: close`.
3. Battery module and `NULL_BATTERY` DONE 2026-11-23 (`null_battery_high_anchor.py`, the daily battery's eight cells, synthetic closes from the same draw as the residual returns, the member through `member_sources.compute_panel_members`). OPEN: the bound pass record (one block, 1,000 simulations per cell, seed base 9,000,000; ledger 2026-11-23d point 3).
4. Gates before the run (ruled in ledger 2026-11-23d point 5): todo 610 witness for 2005 to 2007 closes (cleared by disclosure 2026-11-23, lead ruling, d29cc993b), the split continuity and dividend basis gates of prereg section 6, a ledger line from the lead that the run is registered.

## Gates

`repro_frozen` bit-identical, suite exit 0, `/simplify`, independent review, record rebinds shown in the landing commit. No edit while a fingerprinted run that imports `runner` is live.

## Rescope (lead ruling 2026-11-22): one panel-source input for families 9 and 10

Family 10 (E24, volume shock) hits the same wall from the other side: prereg section 3 has each member read share volume and the S1 residual together (V1 residualizes the volume rank on e and abs(e) per row, V2 on the 5-session sum of e), and a member receives one array today. One runner and spec change serves both families: a panel source input kind (the total-return close for family 9, share volume for family 10) and the S1 residual passed to every member as a fixed argument. It edits `runner.member_input`, `runner._member_fn` and `MemberInputSpec.kind`, all inside `battery_pass.RUNNER_STATISTIC_FUNCTIONS`, so it lands once, after both counted runs (daily residual and H-C seasonality), with every battery record rebound in the same commit. Family 10's kernels, tests and todo are built meanwhile in new modules (no pass record: an E17 pass must exercise the runner statistic path); its spec and member wrapper wait on this todo.

Family 10 data gates measured 2026-11-22 (read-only, 1d, 2005-01-03 to 2025-12-23): todo 563 holds (no NULL volume; vendor and kind are only massive sip_flat_adj 42,024,440 and alpaca sip_rth 333,114 rows, no ibkr or venue rows) and todo 560 holds (one basis, VOLUME_BASIS_CONSOLIDATED); 173,699 rows (0.41 percent) have volume <= 0 and are dropped by the tradeable view under the 40-of-50 rule.

