---
priority: P2
status: pending
---

# 353: `is_earnings_season` calendar primitive — validated candidate, not yet built

**Origin:** 2026-08-23 session, user recalled prior "temporal primitives with great IC" and asked
whether earnings-season effects were covered. They weren't — no primitive in `feature_factory.py`
encodes earnings season. User definition, corrected mid-session: earnings season starts ~2 weeks
after calendar quarter end and runs ~4 weeks (i.e., days 14-42 post-quarter-end, not days 0-42 —
the proxy test below used the uncorrected 0-42 window before the correction landed; the real
build must use 14-42).

## Cheap proxy test run (SQL only, no new feature built)

Defined `is_earnings_season` as a derived flag directly off `forward_returns.bar_ts` (calendar
math, no new data source needed — market-wide earnings season is a date-based phenomenon, not
per-company): day falls within 42 days after Mar 31 / Jun 30 / Sep 30 / Dec 31.

Tested against `forward_returns.return_fast`, `return_type = 'executable_open_to_open'`,
`tf = '1d'`, `complete_fast AND NOT return_fast_suspect` (Invariant 1 compliant).

**Results:**
- Pooled: mean return in-season = 0.000484, off-season = 0.000113 (4.3x), Welch t=8.55,
  p=1.2e-17 (n=923,353 daily obs).
- Per-symbol: 186/230 symbols (81%) show higher mean return in-season — broad, not
  concentrated in a few names.
- Confirmed equity-specific: all rows in the `forward_returns JOIN instruments` split were
  `asset_class = 'equity'` — not diluted or driven by futures/fx macro seasonality.
- Not redundant with existing calendar primitives: `quarter_position` /
  `quarter_cycle_sin`/`cos` are smooth continuous encodings of position-in-quarter; earnings
  season is a step function over the first ~46% of each quarter with a plausible sharp
  boundary effect, not something a linear/cyclical encoding necessarily captures.

**Caveat on significance:** daily returns within a 6-week earnings-season block are
autocorrelated (not independent draws), so the naive Welch t-stat overstates the effective N —
same discipline the project already applies via `n_independent` in `feature_ic_scores`. The raw
effect size and 81% cross-symbol sign consistency are still a strong prior, but this needs to go
through the same `ic_engine.py`/FDR/walk-forward gates as every other feature before being
treated as confirmed, not just the pooled t-test above.

## Not done here (deliberately, to avoid mid-run scope creep)

- No migration, no `feature_factory.py` computation, no `concept_registry` row, no backfill.
  Building this properly means: (1) add `is_earnings_season` (and consider
  `days_since_quarter_end` as a continuous companion) to `FeatureVector` schema + migration,
  (2) implement in `feature_factory.py` calendar group, (3) `concept_registry` genesis-seed row
  per migration-time-DDL exemption, (4) recompute across the 231-symbol corpus, (5) real
  `feature_ic_scores` gate pass (FDR + walkforward), not just the SQL proxy above.
- That's a real multi-hour-plus commitment (new primitive → backfill → recompute), same class
  of cost as the fingerprint-invalidation issue this session already worked around once. Do not
  launch it opportunistically mid-corpus-run; scope and schedule deliberately.

## Recommendation

Promising enough to build for real. Suggest scheduling after the current in-flight
`ic_engine --cross-sectional-only` run (see `project_disk_full_incident_2026_08_13.md`) and its
downstream `ic_shrinkage → ensemble_trainer → alpha_publisher` chain complete, so it doesn't
compete for compute or trigger another fingerprint-invalidation re-run mid-flight.

**Before building:** re-run the SQL proxy test with the corrected 14-42-day window (not the
0-42 window used above) to confirm the effect holds under the accurate definition before
committing the migration/backfill.

## Second finding: earnings season amplifies existing volatility/volume feature IC (not just its own effect)

Follow-up test (same session, corrected 14-42-day window): `up_vol_body_diff` (an already-live
`feature_factory.py` primitive, equity, 1d, `feature_vectors JOIN forward_returns`) shows Spearman
IC nearly **doubling** inside the earnings-season window vs. outside it:
- In-season: n=297,136, IC=+0.0197, p=6.5e-27
- Off-season: n=622,796, IC=+0.0103, p=5.7e-16

Same sign both regimes, real amplification not noise. Implication: `is_earnings_season` is
worth testing not just as a standalone feature but as a **conditioning/interaction regime** for
`ic_engine.py`'s existing regime segmentation (alongside the HMM-derived calm/elevated/turbulent
buckets) — vol/volume-family features broadly may be regime-conditional on earnings season in a
way the current HMM regime split doesn't capture, since HMM regimes are volatility-clustering
based, not calendar-based.
