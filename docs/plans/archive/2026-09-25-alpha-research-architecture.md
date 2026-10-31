# Alpha research architecture: one research DAG, one book, breadth over sleeves

Original: 2026-09-25 (adopted 2026-09-25; mechanics carried forward by the unified design, E18).
Archived 2026-10-31: pre-unified design, kept for the diagnosis and the family priors.

Ideas worth keeping:
- Diagnosis: testing one hand-designed construction at a time cannot find a Renaissance-type
  edge (IC 0.01 to 0.03, individually insignificant, useful only in combination); 18
  standalone verdicts with zero PASS is that process's output whether or not edge exists.
- Breadth beats the 13-ETF sleeve: portfolio-level tests had run where statistical resolution
  is worst (n_eff about 6.3; a Sharpe-1 book needs 4 years there), while feature_vectors held
  233 names at intraday frequencies.
- Family priors in search order: intraday same-slot periodicity (Heston-Korajczyk-Sadka
  2010), overnight versus intraday decomposition (Lou-Polk-Skouras 2019), then price
  anchoring, short-term reversal and the rest; designs in section 4, status only in the
  ledger.
- One research DAG (panel, target, families, guards, combiner, construction rule, book test)
  with a per-vintage look-count budget.

Live successor: docs/plans/2026-09-26-unified-research-to-production-design.md; family
status: docs/research/construction-verdict-ledger.md.
Full text in git history at docs/plans/2026-09-25-alpha-research-architecture.md as of 708f3fe09.
