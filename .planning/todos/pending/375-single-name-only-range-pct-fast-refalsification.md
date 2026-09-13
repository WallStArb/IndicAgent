---
status: pending
priority: P1
filed: 2026-09-13
source: council review of the personal-scale edge program's decision gate, verified against primary sources
---

# Single-name-only `range_pct_fast_xs_ls_h5` re-falsification — real, verified, unresolved lead

## What was found

A council review of the fired decision gate (rule 3, 2026-09-12) raised a specific,
falsifiable objection: `range_pct_fast_xs_ls_h5`'s DEAD verdict (beta +1.14, R²=0.75,
pooled across 231 symbols = 128 single-name equities + 103 ETFs) was never checked for
whether the beta contamination is a property of the *signal* or a property of *pooling
baskets with single names in one cross-sectional ranking* — ETFs are mechanically
beta-dominated by construction; single names carry more idiosyncratic variance.

Built and ran `scripts/analysis/range_pct_fast_beta_by_universe_composition.py`
(read-only diagnostic, reuses `_build_phase` unchanged from the original falsification
script; sanity-checked by reproducing the original pooled verdict's exact beta/R² before
trusting the subset splits). Result, 2026-09-13:

| subset | rebalances | beta | R² | gross mean (bp) | neutralized mean (bp) |
|---|---|---|---|---|---|
| pooled (sanity check) | 931 | +1.1368 | 0.747 | 22.46 | 4.87 |
| single-name-only | 925 | +0.9126 | 0.443 | 16.48 | **10.17** |
| ETF-only | 931 | +1.3102 | 0.819 | 8.80 | 1.34 |

The single-name subset shows materially less beta contamination (R² 0.44 vs 0.75 pooled,
0.82 ETF-only) and a neutralized intercept **more than double** the pooled result. The
ETF subset is the more contaminated half, confirming the original pooled test's beta
story was disproportionately an ETF-subset property.

## Why this doesn't reopen the fired kill criterion

Per this project's own discipline (kill criteria are binding; don't reopen without
genuinely new falsifiable evidence, not renewed enthusiasm) — this diagnostic computed
**no cost drag, no bootstrap CI, no shuffled null, no stability check**. A positive
neutralized intercept only says an OLS beta fit leaves a positive residual mean; nothing
here says that residual survives personal costs, sampling noise, or the original
pre-registration's PASS rule. The gate's firing stands; this is a corroborating lead
that needs its own falsification, not proof it was wrong.

A companion screen, run the same session
(`scripts/analysis/tsmom_per_symbol_ic_screen.py`), tested the "near-free" time-series/
absolute-momentum check flagged in
`docs/research/2026-09-11-strategic-plans-features-ensemble-construction.md` but never
executed before the gate fired — a structurally different construction (per-symbol,
no cross-sectional ranking) that would sidestep this exact contamination mode. It came
back **decisively negative**: mean IC negative across pooled/single-name/ETF splits
(-0.026/-0.028/-0.024), 0/231, 0/128, 0/103 qualify BY-FDR at any split. That thread is
closed — recorded in `docs/research/construction-verdict-ledger.md`'s supporting
measurements section, no further action needed there.

## What to do

Design and pre-register a proper single-name-only `range_pct_fast` falsification,
matching the rigor of the original: full cost-band drag (9 spread×borrow combos,
turnover measured fresh on the 128-symbol universe — k=25 leg size differs from the
pooled k=46, so commission-minimum-binding behavior may differ), circular block
bootstrap CI, shuffled null, 3-subperiod stability check. AGY-review the design before
running, per this program's standing practice. If it PASSes, this is a genuine
successor construction the pooled DEAD verdict never actually tested. If it fails, this
closes the single strongest open lead from the graveyard-reconsideration/gate-firing
review and the "universe expansion is primary" resourcing call stands on firmer ground.

Not urgent in the sense of blocking anything — the gate has already fired and universe
expansion can proceed in parallel — but this is the highest-leverage item in the queue:
cheap (no new data, reuses existing panel/machinery), and it's the one lead this review
found that could plausibly change next-quarter's resourcing priority if it lands.
