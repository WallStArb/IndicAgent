---
status: in_progress
priority: P2
filed: 2026-11-22
source: lead brief 2026-11-22 (indicagent-21), ranking in docs/plans/archive/2026-11-22-next-counted-family-after-daily-residual.md section 3
---

# Family 10 (volume shock): kernels on main, spec, members, battery and run

## What

Two volume-shock members on the daily clock (prereg `docs/plans/2026-11-15-family10-volume-shock-prereg-draft.md`, adopted as E24, 4 looks: 2 members, 1 horizon, 2 panels). The pure kernels are in `src/intelligence/research/families/volume_shock.py` (new module, unregistered, no `NULL_BATTERY`), tests in `tests/unit/research/test_families_volume_shock.py`. The family cannot run: each member reads share volume and the S1 residual e (V1 residualizes the volume rank on e[d] and abs(e[d]); V2 on the 5-session sum of e), and a member receives one array of S1 residuals. Todo 653 is rescoped to add the source and the e pass-through for families 9 and 10 in one change; nothing here edits the runner.

## Scope

1. Done: kernels `volume_rank` (V1 `short=1`, V2 `short=5`), `volume_shock` (the rank orthogonalized to the S1 residual sum and its absolute value) and `residualize_rows`, with `window`, `short`, `min_finite`, `min_finite_short` and `min_names` as required arguments (spec fields, no kernel defaults). Unit tests: the rank and tie rule, V2 against an explicit reference over its 46 short means, the 50-session window edge (rows d-50 to d-53 do not move row d), the 40-of-50 rule, the short-means floor boundary at 36 and 37, no_fill, causality, volume-basis invariance.
   V2 definition and ruling (lead, pre-run, no result exists, ledger entry by the lead): the rank of m[d] runs over the 46 short means m[d-45..d]; it needs at least 37 of them finite (80 percent, as the 40-of-50 rule on volume), so `min_finite_short` is 37 in the spec. `min_names` (200) is a spec field too.
2. Blocked on 653: member wrappers, `research/specs/family10_volume_shock_h5.yaml` and the core twin with the spec-hash pin test, the battery module (B2 size cells at 0.05, 0.01 and 0.00167; the pass runs the runner's own statistic path, so it is built after 653 lands), B3 power statement, the run.
3. Open data gates (heavy slot): prereg section 6 gate 4 (Massive over Alpaca volume ratio, median within 0.99 to 1.01, 5th to 95th within 0.95 to 1.05) and gate 5 (volume continuity across split dates). A grouped scan of the base table costs about 2 s per one-year 1d slice. Gates 4 and 5 re-run after step 7 and at the forward confirmation.

## Gates cleared (read-only, 2026-11-22, 1d, 2005-01-03 to 2025-12-23, base table)

- Todo 563 (no NULL volume): vendor and kind are only massive `sip_flat_adj` (42,024,440 rows) and alpaca `sip_rth` (333,114 rows); zero ibkr rows and zero `kind = 'venue'` rows (the tradeable view NULLs volume only for venue; the base column is NOT NULL). 173,699 rows have volume <= 0 (0.41 percent); the view drops them and the 40-of-50 rule masks the member.
- Todo 560 (volume basis seam): both pairs map to `VOLUME_BASIS_CONSOLIDATED`, so the span holds one basis.

## Gates

`black`, `ruff`, `tools/check_glossary.py`, targeted tests, suite exit 0, `/simplify`, independent review. After 653: `repro_frozen` bit-identical, record rebinds shown in the landing commit, ledger line from the lead that the run is registered.

## Build 2026-11-23 (indicagent-fe; ledger 2026-11-23e rulings; 653 landed in 03ae3f770)

Landed in the family 10 commit: `volume_rank_member` and `NULL_BATTERY` in `families/volume_shock.py`; `research/specs/family10_volume_shock_h5.yaml` and `_h5_core.yaml` (spec-hash pinned); `src/intelligence/research/null_battery_volume_shock.py`; tests (battery, wrapper, spec pins, the stage's causality and memory); the 43-event disclosure `docs/research/family10-gate5-near-factor-events.md`; the prereg amendments. No recorded spec hash or code key moved.

Battery cells (in order, 8): `volume_gaussian`, `volume_static_means`, `volume_late_listings`, `volume_hostile`, `volume_hostile_no_static`, `volume_s1_hostile`, plus the diagnostic `volume_convex_stress` and `volume_unit_root_stress`. 300 names, 3,200 sessions per panel; gating sizes static sd 0.06 and market mean 0.04 (the daily and seasonality batteries' values), stress static sd 0.3.

Generator constants (named in `null_battery_volume_shock.py`; log volume = name level + AR(1) per-name + AR(1) market + loadings on |u| + noise): name sd 0.5, AR(1) phi 0.9 (stress cell 0.99), per-name sd 0.3, market sd 0.2, loading on |u| same session 0.15 and previous session 0.15, noise sd 0.2 (Student t4 in the hostile cells), hostile cells: 1 percent holes (NaN), 30 percent of names with one permanent level step of ln 8; stress cell adds 0.3 x |u|^2. The hole rate was set at 1 percent because 5 percent leaves V2 mostly undefined (0.95^5 of the short means finite against the 37 of 46 floor), which also says V2's real coverage depends on the missing-bar rate, to be disclosed with the first run. Cost per simulation about 1 to 2 s, except `volume_s1_hostile` about 110 s (S1 on 300 names), so one 1,000-simulation block is about 2 hours on 16 workers.

Driver, block 1 (heavy, lead launches; do not run beside another heavy job):
`.venv/bin/python scripts/research/e17_null_battery.py logs/family10_battery_b1.json --battery src.intelligence.research.null_battery_volume_shock --sims 1000 --workers 16 --seed-base 11000000`
Bind (one block): `.venv/bin/python scripts/research/bind_battery_pass.py --battery src.intelligence.research.null_battery_volume_shock --spec research/specs/family10_volume_shock_h5.yaml --spec research/specs/family10_volume_shock_h5_core.yaml --driver logs/family10_battery_b1.json --driver-commit <sha> --seed-base 11000000`.
Fallback (only if block 1 fails; declared in 2026-11-23e): a second block `... --seed-base 12000000` to `logs/family10_battery_b2.json`, then bind with `--replication-driver logs/family10_battery_b2.json --seed-base 11000000 --seed-base 12000000`.

Closure coupling (2026-11-23): family 9's battery imports `volume_shock` through `member_sources`, so any later edit to `families/volume_shock.py` changes family 9's battery code key and stales its pass (the family 10 landing does exactly that, so family 9's real runs go first), and family 10's own battery key depends on the same module in the same way.
