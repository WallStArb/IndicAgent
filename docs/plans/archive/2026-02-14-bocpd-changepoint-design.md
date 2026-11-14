# BOCPD change point detection plugin (archived)

Date: 2026-02-14. Condensed to a stub 2026-11-14.
Outcome: shipped as a v2.x I6 plugin; the v2.x I1-I7 plugin tier and signal path were deleted (plan 185-45, todo 509). Its fate is in `docs/research/construction-verdict-ledger.md`.

Idea kept: Bayesian online change point detection on log returns (run-length posterior, constant hazard, truncated run length) gives a per-bar change probability; a candidate regime-change feature, not a signal.

Full text: git history, `docs/plans/archive/2026-02-14-bocpd-changepoint-design.md` as of `8cbbeff32`.
