---
status: pending
priority: P2
filed: 2026-11-22
source: lead brief 2026-11-22 (indicagent-21), ranking in docs/plans/2026-11-22-next-counted-family-after-daily-residual.md section 3
blocked_on: todo 653 for the spec, the member wrappers, the battery and the run (the member input change that gives a member a panel source plus the S1 residual e)
---

# Family 10 (volume shock): kernels on main, spec, members, battery and run

## What

Two volume-shock members on the daily clock (prereg `docs/plans/2026-11-15-family10-volume-shock-prereg-draft.md`, adopted as E24, 4 looks: 2 members, 1 horizon, 2 panels). The pure kernels are in `src/intelligence/research/families/volume_shock.py` (new module, unregistered, no `NULL_BATTERY`), tests in `tests/unit/research/test_families_volume_shock.py`. The family cannot run: each member reads share volume and the S1 residual e (V1 residualizes the volume rank on e[d] and abs(e[d]); V2 on the 5-session sum of e), and a member receives one array of S1 residuals. Todo 653 is rescoped to add the source and the e pass-through for families 9 and 10 in one change; nothing here edits the runner.

## Scope

1. Done: kernels `volume_rank_shock` (V1 base, windows 50 and 1), `volume_rank_shock` with `smooth=5` (V2 base) and `residualize_rows` (per-row OLS on e and abs(e), 200-name floor), unit tests for the rank and tie rule, window edge, the 40-of-50 rule, no_fill, causality and volume-basis invariance.
2. Blocked on 653: member wrappers, `research/specs/family10_volume_shock_h5.yaml` and the core twin with the spec-hash pin test, the battery module (B2 size cells at 0.05, 0.01 and 0.00167; the pass runs the runner's own statistic path, so it is built after 653 lands), B3 power statement, the run.
3. Open data gates (heavy slot): prereg section 6 gate 4 (Massive over Alpaca volume ratio, median within 0.99 to 1.01, 5th to 95th within 0.95 to 1.05) and gate 5 (volume continuity across split dates). A grouped scan of the base table costs about 2 s per one-year 1d slice. Gates 4 and 5 re-run after step 7 and at the forward confirmation.

## Gates cleared (read-only, 2026-11-22, 1d, 2005-01-03 to 2025-12-23, base table)

- Todo 563 (no NULL volume): vendor and kind are only massive `sip_flat_adj` (42,024,440 rows) and alpaca `sip_rth` (333,114 rows); zero ibkr rows and zero `kind = 'venue'` rows (the tradeable view NULLs volume only for venue; the base column is NOT NULL). 173,699 rows have volume <= 0 (0.41 percent); the view drops them and the 40-of-50 rule masks the member.
- Todo 560 (volume basis seam): both pairs map to `VOLUME_BASIS_CONSOLIDATED`, so the span holds one basis.

## Gates

`black`, `ruff`, `tools/check_glossary.py`, targeted tests, suite exit 0, `/simplify`, independent review. After 653: `repro_frozen` bit-identical, record rebinds shown in the landing commit, ledger line from the lead that the run is registered.
