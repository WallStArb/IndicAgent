# Archived superpowers plans

Status: archived stub (2026-11-15). The six implementation plans from July and September 2026 for the v2.x and
v3.0-era `ic_engine`, ensemble and counterfactual tracker are deleted. Each plan's todo is completed, and the code
it targeted was shipped or has since been deleted (`services/ic_engine.py` and `services/counterfactual_tracker.py`
in phase 186, `scripts/analysis/` in 186-16). The matching design specs stay in `docs/superpowers/specs/`, because
source files and migration 271 cite them by path.

Plans (full text in git history at `ddd16cebc`, path `docs/superpowers/archive/plans/<name>.md`):

| Plan | Outcome |
|---|---|
| `2026-07-20-bar-ingestion-price-sanity-guard` | Shipped (todo 149); the guard lives in `src/intelligence/statistics/price_sanity.py`. |
| `2026-07-21-regime-stratified-promotion-and-per-timeframe-eligibility` | Shipped (todo list completed), then superseded by the v3.5 research DAG. |
| `2026-07-21-restore-symbol-hmm-ic-measurement-for-routed-symbols` | Shipped, then superseded (old ic_engine deleted). |
| `2026-07-29-canary-seed-and-broadcast-feature-audit` | Canary seeding done 2026-07-29 (todo 203). |
| `2026-07-30-per-tf-active-scale-set` | Shipped as `alpha.ic.active_scales.{tf}`; the readers were deleted in phase 186. |
| `2026-09-16-cross-instrument-covariance-aware-portfolio-diagnostic` | Diagnostic design; its spec stays in `docs/superpowers/specs/`. |
