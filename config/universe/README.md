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
  excluded only symbols already in `instruments`, not the other draw. The manifest labels
  all five `r2k_draw_iwm`, so the rank-1001 cohort shows 65 rows although 70 of its drawn
  names are onboarded.
- Names that failed the history screen were dropped, not replaced within their cap bucket
  (the S&P 500 fill took their place in the batch). The failures cluster in young-listing
  buckets, so the onboarded small caps lean toward long-listed firms more than the
  stratification intends. That comes on top of the current-membership survivorship bias
  (todo 376). The draw script's in-bucket replacement option was never used for the final
  draws (`replacements: {}`) and has since been removed.
- The provenance JSON files came from an earlier revision of the draw script. They carry
  the key `r2k_sample_size` (now `sample_size`), and their `holdings_file` paths are
  relative to a sibling worktree. They are kept as generated.

## History screen

`history_screen_2026_09_26.csv` records whether each drawn name had an IBKR daily bar in
the two weeks before 2016-09-26: 125 pass and 70 fail. That run predates the screen's
control fetch. For 14 of the 70, the probe exhausted its retries on IBKR pacing errors,
so their FAIL is not evidence of missing history: VOR, PAYO, ACVA, RDW, SGHC, SDRL (IWM
draw) and NUVB, CMDB, PWP, AGL, VSTS, CNXC, MFP, CLBK (rank-1001 draw). They are due for a
re-screen, and any that pass get onboarded into their original cohort.
