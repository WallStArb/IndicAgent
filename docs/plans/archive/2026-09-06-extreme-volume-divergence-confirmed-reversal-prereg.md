# Extreme-volume divergence / confirmed-reversal pre-registration (H-A and H-B)

Original: 2026-09-06 (review rounds 2026-09-08 to 2026-09-09; run and verdict 2026-09-24).
Archived 2026-10-31: voided-era prereg, results voided by the owner's 2026-10-30 data reset.

Hypotheses (re-testable ideas; both on 15m residual returns over the 233-name corpus):
- H-A extreme-volume divergence: a high-volume bar whose close diverges from the session's
  prevailing direction predicts reversal over the next bars (capitulation read).
- H-B confirmed reversal (Fable's from-scratch redesign): the same event gated by
  swing-volume confirmation, with a write-once anchor and disjoint averaging windows. The
  redesign exists because review rounds 1 and 2 found real construction bugs (wrong column,
  causality, sign inversion, density subset logic).

Verdict: both FAILED Track 1 on all five gated criteria (H-A family IC -0.0022, null p 0.92;
H-B IC +0.0007, 0/233 symbols qualify). An exploratory 1d variant showed a sign-reversed
(capitulation-continuation) effect at multi-bar horizons, never pre-registered, never claimed.
Verdict record: docs/research/construction-verdict-ledger.md section 4; summary cards
docs/research/summary-cards/legacy-ha-extreme-volume-divergence.md and legacy-hb-confirmed-reversal.md.
The review trail (AGY rounds 1-3, Fable redesign, todo 372) is in git history only.

Full text in git history at docs/plans/2026-09-06-extreme-volume-divergence-confirmed-reversal-prereg.md as of 708f3fe09.
