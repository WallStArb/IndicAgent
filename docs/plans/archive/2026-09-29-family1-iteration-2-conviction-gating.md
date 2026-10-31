# Family 1 iteration 2: conviction gating

Original: 2026-09-29 (exploration, prototype outside the runner, no research_run rows).
Archived 2026-10-31: voided-era exploration, results voided by the owner's 2026-10-30 reset; superseded by the 2026-10-27 daily residual family prereg.

Kept findings: clean dose-response in conviction (edge per unit traded rises steadily as the
keep quantile tightens, 0.10 to 0.25 bp from keep 0.5 to 0.05) but Sharpe falls with it;
trading only the top quarter of slots cuts turnover from 26 to 7 per session without raising
edge per trade. At 0.25 bp per unit traded, the book still loses money against the 0.7 bp
half-spread assumption. Gated construction needs the E17 H0 battery (todo 442 item 2).

Full text in git history at docs/plans/2026-09-29-family1-iteration-2-conviction-gating.md as of 708f3fe09.
