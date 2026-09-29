---
card_id: legacy-cointegrated-pairs-residual
kind: legacy_verdict
title: Cointegrated pairs residual (6 named ETF pairs, then 471 same-sector single-name pairs)
idea: "Economically linked pairs share a stable cointegrating relationship whose short-run deviations mean-revert and predict forward returns."
verdict: DEAD
verdict_date: 2026-08-07
recipe:
  spec: docs/research/measurement-cointegrated-pairs-residual.md
  script: scripts/analysis/cointegrated_pairs_residual_same_sector_screen.py
  recipe_commit: 9843888f14a7f65250eb23caf1fab20b1004643f
results:
  - name: etf_pairs_stage1_qualifying
    value: "0 of 6 (Engle-Granger, trend c, autolag aic, split 2024-01-01)"
    source: docs/research/measurement-cointegrated-pairs-residual.md#result-run-2026-08-07
  - name: etf_pair_p_eem_vwo
    value: 0.2116
    source: docs/research/measurement-cointegrated-pairs-residual.md#result-run-2026-08-07
  - name: etf_pair_p_efa_ezu
    value: 0.6185
    source: docs/research/measurement-cointegrated-pairs-residual.md#result-run-2026-08-07
  - name: etf_pair_p_mchi_fxi
    value: 0.6628
    source: docs/research/measurement-cointegrated-pairs-residual.md#result-run-2026-08-07
  - name: etf_pair_p_ief_tlt
    value: 0.2408
    source: docs/research/measurement-cointegrated-pairs-residual.md#result-run-2026-08-07
  - name: etf_pair_p_gdx_gld
    value: 0.4069
    source: docs/research/measurement-cointegrated-pairs-residual.md#result-run-2026-08-07
  - name: etf_pair_p_oih_xop
    value: 0.7399
    source: docs/research/measurement-cointegrated-pairs-residual.md#result-run-2026-08-07
  - name: same_sector_pairs_tested
    value: "471 (ITR single_name_equity tag by instruments.contract_details sector, 20 sectors)"
    source: docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
  - name: same_sector_pairs_qualifying
    value: "0 of 471 (0 survive BY-FDR-corrected Stage 1 alone; Stage 2 split-sample reconfirmation had no survivors to test)"
    source: docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
known_defects:
  - "The original 2026-08-07 screen covered 6 hand-named ETF pairs, so its 0/6 was underpowered; the 2026-09-11 same-sector screen replaced it as the better-powered result."
  - "Only Stages 1 and 2 of the 5-stage design ever ran. Stages 3-5 (OU fit, day-clustered bootstrap on the residual z, cost gate) never ran because nothing survived to feed them."
  - "Both runs read daily closes through the end of the corpus at the time (2026-07-28 and 2026-08-12), so they read data at or after alpha.validation.oos_start."
spans_looked_at:
  - {start: 2006-09-01, end: 2026-08-12, role: full_history}
forward_span_looks: 2
tables: [market_data_ohlcv_tradeable, instruments, instrument_tags]
status_now: closed
reopened_as: null
reproducible: false
sources:
  - docs/research/measurement-cointegrated-pairs-residual.md
  - scripts/analysis/cointegrated_pairs_residual_pilot.py
  - docs/research/2026-09-11-strategic-plans-features-ensemble-construction.md
  - docs/research/construction-verdict-ledger.md#4-verdict-record-frozen-chronological
related_cards: []
---

# Cointegrated pairs residual (6 named ETF pairs, then 471 same-sector single-name pairs)

Author: Claude Sonnet 5.5, 2026-09-29
Informed by: `docs/research/construction-verdict-ledger.md` section 4 row `cointegrated_pairs_residual`; `docs/research/measurement-cointegrated-pairs-residual.md`

## What was tried

Two screens with the same Engle-Granger methodology (`statsmodels.tsa.stattools.coint`, trend
`c`, `autolag='aic'`) and the same 2024-01-01 in-sample and out-of-sample split. The first
(2026-08-07, `cointegrated_pairs_residual_pilot.py`) tested six economically linked ETF pairs:
EEM/VWO, EFA/EZU, MCHI/FXI, IEF/TLT, GDX/GLD, OIH/XOP. The second (reconsidered 2026-09-11,
`cointegrated_pairs_residual_same_sector_screen.py`) tested 471 same-sector single-name pairs
with BY-FDR across all 471, then Stage 2 split-sample reconfirmation for corrected survivors.

## What was found

None of the six ETF pairs cointegrates in-sample: p-values run from 0.2116 to 0.7399, none
borderline. The 471-pair screen found 0 pairs that qualify; not one survives corrected Stage 1
alone. Under the pre-registered fast-kill rule this is decisive: cointegration is rare in this
corpus and era regardless of granularity.

## Known defects

The ETF screen was too small to rule out weak cointegration, which is why the same-sector screen
was run. Stages 3-5 never executed, so the mean-reversion of any spread was never measured.

## Why closed

The ledger froze it closed for good: both the ETF and single-name forms are exhausted and the
ledger says not to narrow further or re-litigate. It cannot be rerun as-is: the recipe scripts
are deleted by 186-16, `feature_vectors` is rebuilt, and E15 changed the gates.

## Where the numbers came from

The ETF p-values are copied from the result table in
`docs/research/measurement-cointegrated-pairs-residual.md` (run 2026-08-07). The 471-pair figures
come from the ledger section 4 row (reconsidered 2026-09-11); the graveyard doc in `sources`
records the design and fast-kill rule, not a separate result table.
No query was run and no script was rerun for this card.

`verdict_date` is the original 2026-08-07 verdict; the reconsideration date (2026-09-11) is in
this prose. `recipe.script` is the same-sector screen because it produced the decisive 0/471.
`recipe_commit` is `git log -1 --format=%H --before="2026-09-11 23:59:59" -- scripts/analysis/cointegrated_pairs_residual_same_sector_screen.py`.
The ETF pilot sits in `sources` (it last changed at commit
`803294354add0500e08238e7195fa1f04ec0c276`). `tables` come from the screen's SQL
(`instrument_tags`, `instruments`) and the shared `_fetch_bars_from_db` helper, which reads
`market_data_ohlcv_tradeable`.

The span is the corpus start convention of the 186-01 cards to the last data date at the time of
the second run (2026-08-12, when ingestion last delivered bars, per the statistical factor
residual doc). `forward_span_looks` is 2, one per run, since each read data at or after
2025-12-24; no other card counts them.
