# Universe expansion: file lineage

Author: Claude Opus 5.5 (batches 1 and 2, session 2026-09-26); Claude Sonnet 5.5 (batch 3,
session 2026-10-03)

Process: `docs/foundation/instrument-onboarding-sop.md`, which also lists the biases every batch
carries (survivorship, venue truncation, unscrubbed prints, price-only bars). Each batch gets an
entry here (stage 10): its rationale, source files, selection rule, deviations and verify
results. This file holds lineage only; process changes go in the SOP.

| Batch | Date | Names | Manifests | State |
|---|---|---|---|---|
| 1. Stocks and size-style, country, equal-weight ETFs | 2026-09-26 | 546 | `expansion_2026_09_26.csv` | onboarded, 1d |
| 1b. Small-cap draws the history screen dropped | 2026-09-26 | 70 | `expansion_smallcaps_2026_09_26.csv` | onboarded, 1d |
| 2. Industry, EM country, commodity, fixed-income ETFs | 2026-09-26 | 43 | `expansion_etfs_2026_09_26.csv` | onboarded, 1d |
| 3. Wave 2: stocks and ETFs | 2026-10-03 | 568 stocks, 29 ETFs | `wave2_stocks_2026_10_03.csv`, `wave2_etfs_2026_10_03.csv` | onboarded 2026-10-03 13:47 UTC, 1d fetch running |

Batches 1, 1b and 2 took the universe from 273 to 932 active names; batch 3 makes it 1,529.
Source holdings snapshots and drawn lists sit beside the manifests with their dates.

## Batch 1: stocks (2026-09-26)

546 equity instruments onboarded at 1d only on 2026-09-26 04:04 UTC, all with
`compute_eligible_1d = false` until their 1d backfill lands and
`universe_expansion_promote_compute_eligible.py --dimension compute_1d` promotes them.
`expansion_2026_09_26.csv` is the manifest that was onboarded, row for row. Its 16
`spread_leg` tags went in without the reciprocal `pair` evidence that tag requires; migration
371 added the pairs. A manifest row cannot express a pair, so any future `spread_leg` tag needs
its own migration.

| Cohort (`cohort` column) | Rows | Source |
|---|---|---|
| `spx` | 368 | S&P 500 members from `ivv_holdings_2026_09_23.csv` not already in `instruments` |
| `r2k_draw_iwv_rank1001` | 65 | `r3k_rank1001_draw_2026_09_26.csv`, history-screen passes |
| `r2k_draw_iwm` | 60 | `r2k_draw_2026_09_26.csv`, history-screen passes |
| `etf_country` | 12 | country ETF panel |
| `etf_equal_weight` | 10 | the remaining RSP sector funds plus QQEW |
| `dow_transports` | 9 | DJTA members not held (FDXF left out) |
| `dow_utilities` | 9 | DJUA members not held |
| `etf_size_style` | 6 | IJH, IJR, IWC, IWN, IWO, VIXM |
| `dow_industrials` | 4 | AMGN, CSCO, IBM, NKE |
| `etf_treasury` | 3 | SHV, IEI, TLH |

### Small-cap draws

Both draws come from `universe_expansion_holdings_draw.py`: seed 42, 10 cap buckets, 100 names,
`--min-price 5`, excluding the 295 symbols in `instruments` at draw time. One draws from IWM
holdings; the other from IWV holdings with `--skip-top 1000` (Russell 3000 rank 1001 and below).

- The draws overlap (ALRM, FRME, OTTR, STBA, UNF), because each excluded only symbols already
  held. The manifests label all five `r2k_draw_iwm`, so the rank-1001 cohort shows 95 rows
  although all 100 of its drawn names are held.
- Every drawn name is now held, so the cap strata match the draw. Survivorship remains: the draws
  sample current members only (todo 376).
- The provenance JSON files come from an earlier draw-script revision (key `r2k_sample_size`, now
  `sample_size`; `holdings_file` paths relative to a sibling worktree). They are kept as generated.

### History screen (deleted)

The screen dropped drawn names with no IBKR daily bar in the two weeks before 2016-09-26 (125
passed, 70 failed). It was wrong: 14 failures were probes that exhausted retries on IBKR pacing,
and a SMART-routed probe finds no bar before a name's last listing-venue move (todo 433). The
script was deleted the same day and `history_screen_2026_09_26.csv` is kept only as a record of
it. The 70 were onboarded from `expansion_smallcaps_2026_09_26.csv` (todo 434): 40 `r2k_draw_iwm`
and 30 `r2k_draw_iwv_rank1001`. CLBK is held out of `compute_eligible_1d`: IBKR serves no daily
history for its current conId (902968711).

## Batch 2: ETFs (2026-09-26)

`expansion_etfs_2026_09_26.csv`: 44 ETFs approved the same day, onboarded 1d-only at about 12:10
UTC. 43 went in; XWEB (SPDR S&P Internet) did not qualify on IBKR.

| Cohort | Rows | Contents |
|---|---|---|
| `etf_industry` | 15 (14 onboarded) | SPDR S&P Select Industry funds (XAR, XES, XHE, XHS, XME, XPH, XSD, XSW, KBE, KIE, KCE; XWEB rejected) plus IHI, SLX, GDXJ |
| `etf_country_em` | 12 | EIDO, THD, EPOL, TUR, EZA, ECH, EPU, ARGT, KSA, VNM, EPHE, EWM |
| `etf_commodity` | 10 | USO, USL, UNG, UNL, CPER, PALL, CORN, WEAT, SOYB, GSG |
| `etf_fixed_income` | 7 | MBB, BKLN, ANGL, SJNK, VCLT, BNDX, BWX |

Migration 372 added the fixed-income nodes these needed (FI.SECURITIZED, FI.INTL,
FI.CREDIT.LOANS) and the `fi_mbs` and `fi_intl` exposure tags. Migration 373 paired the
commodity curve funds (USO/USL, UNG/UNL). IGOV was left out as a near-duplicate of BWX; BNDX and
BWX are not paired because BNDX also holds corporate bonds.

## Batch 3: wave 2, stocks and ETFs (2026-10-03)

Rationale, written before any bar of these names was fetched. The 932-name universe held nearly
every top-500 Russell 3000 name but only about a quarter of ranks 501-1000, and the thin sectors
were Energy (0 of 19 in that band), Utilities (3 of 15), Materials (4 of 22) and Communication
(4 of 16). Outside equities it had no managed-futures or merger-arbitrage fund, credit only at
long duration and high yield, no softs, refined energy, CHF or GBP exposure, and no regional
developed-market or international small-cap fund. The cohorts close those gaps by rule, not by
name. No candidate was chosen or dropped on returns, volatility, history length or data
availability.

Source: `iwv_holdings_2026_09_14.csv` (SHA-256 in the provenance JSON). Selection script:
`scripts/infrastructure/universe_expansion_wave2_select.py`, seed 42 and 10 cap buckets from
APR. Output: `wave2_selection_2026_10_03.csv` plus its provenance JSON.

| Manifest | Cohort | Rows | Rule |
|---|---|---|---|
| `wave2_stocks_2026_10_03.csv` | `r3k_top500_fill` | 66 | ranks 1-500 by holdings market value, not held |
| | `r3k_501_1000` | 410 | ranks 501-1000, not held (band taken whole) |
| | `r3k_utilities_depth` | 18 | Utilities at rank 1001+, not held (the rest of the sector) |
| | `r3k_depth_draw` | 74 | Energy, Materials, Communication at rank 1001+: 25 per sector, cap-stratified draw |
| `wave2_etfs_2026_10_03.csv` | `etf_alternatives` | 4 | DBMF, KMLM, CTA, MNA |
| | `etf_credit_duration` | 5 | VCIT, VCSH, FLOT, JAAA, LTPZ |
| | `etf_currency` | 2 | FXB, FXF |
| | `etf_commodity_gap` | 3 | CANE, UGA, BNO |
| | `etf_industry_gap` | 6 | SIL, COPX, REMX, URNM, LIT, TAN |
| | `etf_international_gap` | 5 | VGK, SCZ, EPI, GREK, EIS |
| | `etf_real_assets_gap` | 4 | VNQI, REET, IGF, PSP |

Left out as near-duplicates of held funds (the IGOV precedent): JNK and USHY, IGSB, SGOV, VMBS,
SOXX, VEA and VXUS, ACWI and VT, VSS, CEW. Second share classes of an issuer already held or
selected are excluded (GOOG, BRK B, FWONK, NWS, LLYVK, LBTYK and similar).

Deviations and facts to carry:

- P5N994 is a holdings-file ticker with no IBKR contract and no name. It fell into the Energy
  depth draw and was dropped, not replaced, so that cohort holds 74 names, not 75; the selection
  CSV still lists it.
- JO, BAL, NIB and COW (iPath softs and livestock ETNs) did not qualify on IBKR and are not in
  the ETF manifest. CANE is the only softs fund.
- Stock classifications: IBKR industry, category and subcategory were fetched for every row and
  mapped to a level-4 node by the majority node among held names with the same IBKR triple inside
  the same sector (the holdings file's sector sets level 2). A person reviewed every row whose
  mapping was not unanimous and overrode the ones that disagreed with the GICS-style industry.
- Migration 436 added the `managed_futures` tag for DBMF, KMLM and CTA. MNA carries
  `factor_market_neutral`. JAAA carries `credit_risk`; the vocabulary has no CLO tag.

Onboarded (stage 6) at 13:47 UTC: 597 rows, all `compute_eligible_1d = false`. The stage 7 1d
fetch started 09:54 EDT on client 41 under the bulk tier of the `ibkr_history_stream` lease (log
`logs/backfill_ops/wave2_1d_fetch.log`). This entry gets the held-name and verify results (stage 8)
and the promote count (stage 9) when they run.
