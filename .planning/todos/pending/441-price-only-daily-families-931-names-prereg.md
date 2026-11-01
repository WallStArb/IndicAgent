---
status: pending
priority: P1
filed: 2026-09-26
source: adopted unified design (todo 436), section 6 attempts 3-4; Fable review item 14
---

# Pre-register the price-only families on the 931 names: residual and industry momentum, sector lead-lag

## What

The shortest path to a tradeable verdict runs on data that needs no feature pipeline. Alongside
todo 423 (residual short-term reversal on the names the 2026-09-13 screen never saw), pre-register:

1. Residual momentum (12-1 month on S1 residual returns) and industry momentum (SCH industry
   groups), daily, on the 931 names.
2. Sector-ETF-leads-constituent lead-lag at 5m or 15m (ledger family 3), sectors from SCH,
   restricted to constituents with intraday bars.

Each spec states its universe as of t, carries phase 185 D0's labels (the survivorship bound was retired by the owner 2026-10-09, todo 514) and a
delisting-return sensitivity, and declares its costed construction for promotion (E18).

## Done when

Specs are registered and run as attempts 3 and 4.

## Dividends (todo 428, closed 2026-09-26)

A daily-clock spec declares `panel.total_return: {suspect_yield: <x>}`. Price-only daily returns
carry every ex-dividend drop as a loss, which biases daily targets and can manufacture
price-level signals on high-yield names. See `research/dividends.py`; state the suspect_yield
(0.10 is the value the reference checks used) in the pre-registration.

## Status 2026-10-27 (indicagent-5b)

Registered as one daily family with todo 441's residual momentum and todo 423's residual
reversal: `docs/plans/2026-10-27-daily-residual-momentum-reversal-prereg.md` (draft after two
Codex rounds; AGY out of quota). Five members (M1 12-1 residual momentum, M2 its standardized
form, R1/R2 5- and 21-session residual reversal, R3 the one-session-skip variant) at h = 5 on
`daily_unseen`: 1,269 names created after the 2026-09-13 screen, minus the TSMOM sleeve, with S1
fit on them only. Built (ee8c264df): `families/daily_residual.py`, the B1 universe rule,
`null_battery_daily_residual.py`, and E17's L amendment for daily targets
(`timing.e17_memory`). Left: the full B2 battery (1,000 per cell), B3 power, the spec
`research/specs/daily_residual_h5.yaml`, registration, then the run after 191-20's 1d
re-derive. h = 21 waits on todo 547. Industry momentum and sector lead-lag (441) are not in it.

## Status 2026-10-31 (Testing lane)

B2, the spec and the static-size precondition are done; B3 and registration are held with the
family (todo 547 PM decision 2026-10-31, option b: hold the whole family until the 186-26
rebuild swap plus an S1 regenerated from the rebuilt table). What actually ran, on the stale
S1 vintage:

- Static-size precondition passed on the real panel 2026-10-29: pooled static sd 0.0 against
  the 0.06 gate, time-of-day rms 0.0096 against 0.04 (log survives at
  `data/backups/reset-2026-10-30/files/b0/daily_residual_static_sizes_20261029.log`).
- B2 at 1,000 per cell with the landed daily statistic (`e17_battery_daily_residual_flat_
  20261030.json`, wiped in the 2026-10-30 reset; verdict numbers in todo 547): sd of t 0.88 to
  1.03 in every cell, three marginal exceedances, all in the pre-registered S1-drift pattern.
- B2 v2, the pre-registered 2,000-sim confirmation (seed base 90,000,000, journal only; numbers
  in todo 547): every cell passes except `daily_s1_hostile/residual_momentum_12_1_z` (124 > 123
  at 0.05, 9 > 8 at 0.00167), its twin at the bound. Exactly todo 547's cause 3.
- Spec written and hash-pinned: `research/specs/daily_residual_h5.yaml` (in
  `tests/unit/research/test_spec_hashes_pinned.py`); loads clean as a FamilySpec with the five
  members.

Deliberately not rerun here: battery or power numbers on the stale vintage would be unusable
under the hold. Pre-reset member evidence runs (spec hash `affc57c74b5bac58`) were wiped by the
reset; scratch copies sit in `data/backups/reset-2026-10-30/files/b0/runs/` and are not
evidence. Per todo 547, no real-data number for any daily member exists.

Left, in order, after the 186-27 swap and the fresh S1 vintage: a fresh pre-registration (new
seed base, declared before the run) -> battery cells rerun on the fresh vintage -> B3 power ->
registration (ledger families 4 and 11 move from design-only once numbers exist) -> the five
counted member evidence runs. h = 21 still waits on todo 547's horizon-lag amendment.
