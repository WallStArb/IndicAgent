# 187-08: ridge and kappa cells in the E17 H0 battery

Driver: `scripts/research/e17_null_battery.py`, 1,000 simulations per cell, family 1's members
(same-slot means 1, 5, 20, 40), book through R1 and the horizon rule, L from `book_memory()`.
Bounds: the upper 99% binomial quantile at each level (67, 18 and 5 of 1,000). Gating cells:
ridge, kappa 0.5, kappa 0.2, each on the base null and at twice family 1's measured static size;
diagnostic: ridge with kappa 0.5 on the hostile stress.

## Book arms

| Cell | Book arm | 1,500: 0.05 / 0.01 / 0.00167 | 4,000: 0.05 / 0.01 / 0.00167 | 4,000 mean t, sd t |
|---|---|---|---|---|
| kappa_0.2 | book_equal_weight_k0.2 | 56/67 / 12/18 / 2/5 | 56/67 / 13/18 / 2/5 | +0.02, 0.99 |
| kappa_0.2_static | book_equal_weight_k0.2 | 53/67 / 16/18 / 4/5 | 60/67 / 15/18 / 3/5 | +0.05, 1.01 |
| kappa_0.5 | book_equal_weight_k0.5 | 59/67 / 10/18 / 0/5 | 63/67 / 8/18 / 2/5 | +0.04, 1.03 |
| kappa_0.5_static | book_equal_weight_k0.5 | 54/67 / 10/18 / 2/5 | 72/67 / 14/18 / 3/5 | +0.10, 1.02 |
| ridge | book_ridge_k1 | 68/67 / 13/18 / 1/5 | 47/67 / 14/18 / 2/5 | +0.01, 1.01 |
| ridge_kappa_hostile | book_ridge_k0.5 | 75/67 / 21/18 / 5/5 | 62/67 / 15/18 / 1/5 | -0.03, 1.07 |
| ridge_static | book_ridge_k1 | 65/67 / 13/18 / 3/5 | 48/67 / 8/18 / 1/5 | -0.01, 1.02 |

Records: `logs/research/e17_battery_187_08_20261027.json` (1,500 sessions, the cells' default)
and `logs/research/e17_battery_187_08_s4000_20261027.json` (4,000 sessions, the real panel
length, the standard the owner set for the StepM battery on 2026-10-27).

## Reading

- At 1,500 sessions three member arms (not touched by ridge or kappa) and the ridge book (68 of
  67) crossed their bounds: the short-panel excess E17's own battery documents.
- At 4,000 sessions every book arm holds except `kappa_0.5_static` at 0.05 (72 of 67, mean t
  +0.10, the one sign of bias in the run). A smoothed book's weights are more persistent, and E17
  documents that a persistent weight times static cell means leaks into D_s (the 0.3 static
  diagnostic); kappa 0.2 smooths harder yet held (60), so the kappa 0.5 result is either that
  mechanism at the margin or sampling error (sd about 7). Not certified either way.
- The diagnostic cell (ridge with kappa 0.5, hostile) holds at 4,000 sessions (62 of 67, sd of t
  1.07); it is not a gating cell, so it certifies nothing.
- Every cell's mean t is within 0.10 of 0: the ridge's training reach and the horizon rule's
  reach in L remove the bias a fitted or smoothed book would otherwise carry.

## Certificate

`research/certificates/e17_fitted_books.json`, written by
`scripts/research/certify_fitted_books.py` from the 4,000-session record (battery commit
34af081ca; the certified code is unchanged since). The runner admits, in real and exploration
mode: ridge books at the configuration the battery ran (window 252, refit 21, penalty 1.0,
min_obs 10,000 sessions-based, book_v1's), refusing any other ridge settings; equal-weight books
with kappa 0.2. The certificate pins a per-definition fingerprint of 25 definitions (the horizon
rule and its cutoff, the combiners, the E17 series and HAC, book_memory and BookMemory, R1,
fwd_span, and the whole battery module) and a committed copy of the record
(`research/certificates/records/`). Refused: kappa 0.5 (its static cell
fails), ridge with any kappa (no gating cell), any other kappa (no cell). Synthetic mode is
always open.

## Open

The per-cell bound at 99% is applied to many cells: when the true size is a little above 5%
(E17 runs about 5.5% here), a few cells cross by chance in every run, and which ones changes
with the seeds. Whether the criterion should account for the number of cells is the owner's
decision (raised with the StepM battery, which shows the same pattern).
