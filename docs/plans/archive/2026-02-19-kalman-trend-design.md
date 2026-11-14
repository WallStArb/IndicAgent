# Kalman filter trend plugin (archived)

Date: 2026-02-19. Condensed to a stub 2026-11-14.
Outcome: shipped as a v2.x I4 plugin; the v2.x I1-I7 plugin tier and signal path were deleted (plan 185-45, todo 509). Its fate is in `docs/research/construction-verdict-ledger.md`.

Idea kept: A local-level Kalman trend adapts to noise where fixed-window averages whipsaw or lag, and its innovation variance is a principled confidence measure; measurement noise can scale with volatility.

Full text: git history, `docs/plans/archive/2026-02-19-kalman-trend-design.md` as of `8cbbeff32`.
