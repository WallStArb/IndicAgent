# First corpus family on stored 1d columns: what is missing and the least that must exist

Status: draft design note for the lead (indicagent-9b), 2026-11-27, written by indicagent-b9 on request. Read-only: code read at origin/main (50ad13530), todos 547, 586, 588, 636, 669, 674 and `docs/plans/2026-11-24-family-order-after-1d-corpus.md`. No research code is edited, no battery is run, no look is charged. Numbers marked "unmeasured" have no source yet.

## 1. What the IC sweep's horizons change, and what they do not

The IC sweep measures 1, 2, 5 and 10 (`alpha.ic_measure.horizons`) to propose columns; it writes `feature_ic_scores` and is not a counted look by itself. A counted family is registered at one horizon per member (E23: series = members x horizons x panels), and every ranked family in the family-order note is at h = 5. So the runner and the battery need horizon 5 only. Certificates for 1, 2 and 10 have no consumer today (Musk step 1: deleted). A column the sweep proposes at h = 2 or 10 gets its own certificate when a family is written for it, not before.

## 2. What is missing for one route: stored 1d feature, 1d book, h = 5, equal weight, one family

| Piece | State | Source |
|---|---|---|
| Statistic that holds size for a slow predictor with overlapping targets (HAC lag tied to weight persistence and to target overlap) | built on the held branch `wip/586-persistence-statistic` (opt-in, not on main); never landed | 586, 547, 669 |
| The 1d to 1d route passes the battery under that statistic | not yet: `f1d_tau200` failed at 20 against a bound of 18 at 0.01; the design note allows one fair second look on other seeds | 669 status 2026-11-25 |
| True memory window of pass-through columns (`max_daily_return`, `idiosyncratic_volatility`, `equity_beta_z` declare 0) | landed with the single re-pin (R1, R2 at 639c244b1); the route's `source_memory_bars_max` must cover 252 (beta z) | 674, 669 |
| `_check_supported_subset` refuses `horizon != 1`; `_certificate_request` carries the horizon | widen to this one route; outside `RUNNER_STATISTIC_FUNCTIONS`, so by itself it stales no battery pass | runner.py:517 |
| Battery cells at h = 5 with `overlap_sessions = 4` | missing: `null_battery_persistent` fixes `_HORIZON = 1` for every cell; the horizon becomes a field of the cell's certificate | null_battery_persistent.py:218 |
| `_check_input_mix` (one family of input members, never beside residual-return members) | not an obstacle for H-B, which is one family of input members; lifting it is needed only for a mixed book | 588 m3 |
| Family, spec and preregistration | missing: no H-B spec yaml or family module exists (only the draft prereg, section H-B); `families/features.py` already carries the generic member function the battery certifies | prereg drafts 2026-11-15 |
| New spec fields | none needed: `input`, `horizon` and `panel` exist. A new optional field would go in `spec.py`'s `_OPTIONAL_*_FIELDS` or every recorded spec hash moves | spec.py:625 to 651 |

Cell count and cost. The 1d route has 6 gating cells today (`f1d_tau1, 5, 20, 60, 200` and `f1d_static_tau200`) plus the diagnostic `hostile_tau200`; at h = 5 that is 7 cells, two arms (member and book), 1,000 simulations per cell per block, and two blocks on declared seed bases for the pooled-pair rule of ledger 2026-11-23e: 14 cell runs of 1,000. Runtime at 4 workers is unmeasured: the 184-05 and 588-B runs recorded no wall time. Measure a 20-simulation smoke of one cell at 4 workers before declaring seed bases; the whole block is one heavy job and waits for the DIMM cap and an idle host.

`repro_frozen`. The statistic work edits `RUNNER_STATISTIC_FUNCTIONS` or `src/intelligence/statistics`: `repro_frozen` must report bit-identical (the 586 statistic is opt-in, so the frozen horizon-1 and daily-residual paths do not move), and the three bound pass records (`daily_residual_2026-11-21`, `seasonality_2026-11-21`, `family10_volume_shock_2026-11-24`) are rebound in the same commit with `bind_battery_pass.py`, each shown current by `runner.static_gate`. The route widening and the new cells alone stale nothing if `battery_pass` does not hash `null_battery_persistent.py`; check that first.

Correction 2026-11-27 (review of the build in `docs/plans/2026-11-27-hb-low-risk-prereg-draft.md`): the persistence-widened standard error reaches the member's evidence record, but selection does not use it. `statistics/stepm.py` recomputes `hac_mean_test` on the stored attempt series for the observed t and every bootstrap draw, with the plain Newey-West lag and no overlap or persistence term. A battery pass for `e17_persistent` therefore certifies the record statistic, not the StepM selection the detection rule rests on. The same gap already holds for horizon-5 overlap in the counted families (todo 547). The slice below gains one item before the family can be called detected: either StepM takes the member's persistence and overlap lags (an opt-in edit of the certified `stepm.py` with `repro_frozen` bit-identical), or a StepM-level H0 cell is added to the battery (null persistent h5 series through StepM, size at the declared levels). The lead and the owner rule which; until then H-B's detection rule is stated in terms of StepM on the stored series and the persistent record is a disclosure.

## 3. The least that must exist (one counted feature-family test)

1. A recorded decision on the second look: rerun `f1d_tau200` and its neighbours on other seed bases, declared in the ledger beforehand. If it fails again the route stays refused and the owner decides whether persistent members are in scope at all (stop here; nothing below is built).
2. The opt-in statistic landed under a methodology-change entry, with the rebind and `repro_frozen` bit-identical.
3. One certificate (feature, 1d to 1d, h = 5, equal weight, unsmoothed, `e17_persistent`, memory bound 312 from the member check) and its 7 cells; the pooled block pair; `bind_battery_pass.py`.
4. The runner admission for that one route.
5. The selection-statistic item of the correction above (StepM lags or a StepM-level H0 cell).
6. The H-B family, spec and preregistration (6 series), the E21 clean-data ruling for feature-vector families, then the counted run.

Deleted from the slice: horizons 1, 2 and 10, smoothing, other source timeframes, the 1h book, the multi-input book certificate, the regime slot cells, any `corpus_family` composition. Each is a separate item priced after the first read. The note's alternative of recomputing the stored columns as research kernels is not available: design D5 forbids a family from dodging the corpus that way.

## 4. Ranking against the minimum

| Rank | Family | Needs beyond the minimum slice |
|---|---|---|
| 1 | H-B low risk (MAX, idiosyncratic volatility, beta; 6 series) | nothing: it is the slice |
| 2 | `corpus_family` (2 series) | a multi-input book certificate and battery cells at the real member count; the most value per series, the most build |
| 3 | Market-residual reversion | the slice, plus a turnover check against todo 553; `informed_by` the selected `reversal_21` |
| 4 | Regime-conditioned `reversal_21` | the slice, a base book (todo 547 owner decision) and the S7 regime slot cells (todo 548) |
| 5 to 7 | interaction, `size_proxy`, momentum | the slice; low priors; wait |

The slice unlocks ranks 1, 3, 6 and 7 together (single-family, stored 1d, h = 5); ranks 2 and 4 each add a build. H-B stays first: it needs no more than the slice, and it is the family the preregistered drafts already describe.

## 5. Todos touched and the owner's rulings

- 669 carries the build (it already holds the design ruling and the 2026-11-25 status); this note narrows its scope to the one route above and adds the horizon field to the certificate.
- 547: the horizon-tied lag folds into 669; its separate owner decision (the S1-drift failure pattern, options A and B) gates the `reversal_21` book, not H-B.
- 586 closes only when its ten gating cells hold; the three 1d cells are on the path, the other seven (5m, smoothing, hourly book) are not.
- 588 m3 is not touched unless a mixed book is wanted.
- 636 (daily residual battery rerun with M3) is independent and competes for the same heavy slot.

The owner rules on: (a) the E21 clean-data lift for feature-vector families (the 2026-11-22 lift covers price-derived 1d only); (b) whether persistent members are in scope if the second look fails; (c) the 547 S1-drift options; (d) the heavy-slot order after `stage_1d`: IC measure, the battery block pair, the 656 container check, and the H-B counted run, one at a time.
