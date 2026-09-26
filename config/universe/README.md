# Universe expansion 2026-09-26: file lineage

Author: Claude Opus 5.5 (session 2026-09-26)

546 equity instruments onboarded at 1d only on 2026-09-26 04:04 UTC, all with
`compute_eligible_1d = false` until their 1d backfill lands and
`universe_expansion_promote_compute_eligible.py --dimension compute_1d` promotes them.
`expansion_2026_09_26.csv` is the manifest that was onboarded, row for row. Its 16
`spread_leg` tags went in without the reciprocal `pair` evidence that tag requires;
migration 371 added the pairs. A manifest row cannot express a pair, so any future
`spread_leg` tag needs its own migration.

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

## Small-cap draws

Both draws come from `universe_expansion_holdings_draw.py`: seed 42, 10 cap buckets,
100 names, `--min-price 5`, excluding the 295 symbols in `instruments` at draw time. One
draws from IWM holdings (the Russell 2000 itself); the other draws from IWV holdings with
`--skip-top 1000` (Russell 3000 rank 1001 and below).

Deviations from a clean stratified sample:

- The draws overlap. ALRM, FRME, OTTR, STBA and UNF appear in both, because each draw
  excluded only symbols already in `instruments`, not the other draw. The manifests label
  all five `r2k_draw_iwm`, so the rank-1001 cohort shows 95 rows although all 100 of its drawn
  names are held.
- Names that failed the history screen were left out of the first manifest and onboarded the
  same day once the screen was deleted (below), so every drawn name is now held and the cap
  strata match the draw. Survivorship remains: the draws sample current members only (todo
  376). The draw script's in-bucket replacement option was never used for the final draws
  (`replacements: {}`) and has since been removed.
- The provenance JSON files came from an earlier revision of the draw script. They carry
  the key `r2k_sample_size` (now `sample_size`), and their `holdings_file` paths are
  relative to a sibling worktree. They are kept as generated.

## History screen (deleted)

`history_screen_2026_09_26.csv` records the screen that dropped drawn names with no IBKR
daily bar in the two weeks before 2016-09-26: 125 passed and 70 failed. The screen was
wrong in two ways:

- 14 of the failures were probes that exhausted their retries on IBKR pacing, not evidence
  of missing history.
- A SMART-routed probe finds no bar before a name's last listing-venue move (todo 433), so
  names that changed venue after 2016 also failed.

The script was deleted the same day. Drawn names are now onboarded as drawn and the research
panel's coverage rules handle short histories. The 70 were onboarded the same day from
`expansion_smallcaps_2026_09_26.csv` (todo 434), in their original cohorts (40 `r2k_draw_iwm`,
30 `r2k_draw_iwv_rank1001`) with the classifications the other 125 drawn names received. All
195 names both draws produced are now in `instruments`. CLBK is held out of `compute_eligible_1d`: IBKR
serves no daily history for its current conId (902968711), so it has no bars.

## ETF batch (second manifest)

`expansion_etfs_2026_09_26.csv`: 44 ETFs approved the same day, onboarded 1d-only at about
12:10 UTC. 43 went in; XWEB (SPDR S&P Internet) did not qualify on IBKR and was not written.

| Cohort | Rows | Contents |
|---|---|---|
| `etf_industry` | 15 (14 onboarded) | SPDR S&P Select Industry funds (XAR, XES, XHE, XHS, XME, XPH, XSD, XSW, KBE, KIE, KCE; XWEB rejected) plus IHI, SLX, GDXJ |
| `etf_country_em` | 12 | EIDO, THD, EPOL, TUR, EZA, ECH, EPU, ARGT, KSA, VNM, EPHE, EWM |
| `etf_commodity` | 10 | USO, USL, UNG, UNL, CPER, PALL, CORN, WEAT, SOYB, GSG |
| `etf_fixed_income` | 7 | MBB, BKLN, ANGL, SJNK, VCLT, BNDX, BWX |

Migration 372 added the fixed-income nodes these needed (FI.SECURITIZED, FI.INTL,
FI.CREDIT.LOANS) and the `fi_mbs` and `fi_intl` exposure tags. Migration 373 paired the
commodity curve funds (USO/USL, UNG/UNL). IGOV was left out as a near-duplicate of BWX; BNDX
and BWX are not paired because BNDX also holds corporate bonds.
