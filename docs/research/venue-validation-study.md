# Venue validation study (D3)

Author: Claude Sonnet 5.5, executing phase 185 plan 13, 2026-09-29
Informed by: config/bars/venue_study_preregistration.json (committed before any fetch), docs/plans/2026-09-26-daily-data-foundation.md (D3, D-17, D-18), src/intelligence/bars/venue_study.py

## Method

Names per venue: {"NYSE": 12, "ISLAND": 12, "ARCA": 12}. Selection is sha256(seed||symbol) ascending with seed 185017. Routes: SMART, NYSE, ARCA, ISLAND, AMEX, BATS. Windows: 504 daily sessions and 20 5m sessions. fetch_run_id 62cd2054-db25-4f92-889a-d9cb13e8bc0f; client id 48; caller 'venue-study'.

Pre-registration sha256 94ff1f4c63d075744593919a4fc4104b955af8fdf74b4540962c3236291f91bd.

5m artifact: data/venue_study/62cd2054-db25-4f92-889a-d9cb13e8bc0f.csv.gz (sha256 4aa3c211d548178b79ca7463e6558b1a6fac67adcb65962b99a37930bf6b7ea2, not committed).

## Verdict

| Timeframe | Criterion A (listing venue has most volume) | Criterion B (only listing closes match) | Passed |
| --- | --- | --- | --- |
| 1d | False | False | False |
| 5m | False | False | False |

## 1d per-name statistics

Names by venue: {"NYSE": 12, "ISLAND": 12, "ARCA": 12}. Reasons: criterion_a: 0.833 of names pass, need 0.9; criterion_b: 0.139 of names pass, need 0.9.

| Symbol | Venue | Days | Listing max-volume share | Listing close match | Max other close match | Volume | Close |
| --- | --- | --- | --- | --- | --- | --- | --- |
| JPM | NYSE | 751 | 1.000 | 1.000 | 0.903 | True | False |
| KR | NYSE | 751 | 1.000 | 1.000 | 0.964 | True | False |
| FDS | NYSE | 751 | 1.000 | 1.000 | 0.696 | True | False |
| ALK | NYSE | 751 | 1.000 | 1.000 | 0.875 | True | False |
| WAT | NYSE | 751 | 0.999 | 1.000 | 0.700 | True | False |
| PGR | NYSE | 751 | 1.000 | 1.000 | 0.909 | True | False |
| CMS | NYSE | 751 | 0.999 | 1.000 | 0.964 | True | False |
| BMY | NYSE | 751 | 1.000 | 1.000 | 0.911 | True | False |
| RSG | NYSE | 751 | 1.000 | 1.000 | 0.880 | True | False |
| NAD | NYSE | 751 | 0.995 | 1.000 | 0.806 | True | False |
| AES | NYSE | 751 | 1.000 | 1.000 | 0.792 | True | False |
| WSM | NYSE | 751 | 1.000 | 1.000 | 0.802 | True | False |
| FISV | ISLAND | 751 | 0.294 | 1.000 | 0.955 | False | False |
| ASML | ISLAND | 751 | 1.000 | 1.000 | 0.764 | True | False |
| COST | ISLAND | 751 | 1.000 | 1.000 | 0.897 | True | False |
| STBA | ISLAND | 751 | 0.987 | 1.000 | 0.358 | True | True |
| PATK | ISLAND | 751 | 0.996 | 1.000 | 0.382 | True | True |
| ATRO | ISLAND | 751 | 0.999 | 1.000 | 0.457 | True | True |
| FCEL | ISLAND | 751 | 0.985 | 1.000 | 0.530 | True | False |
| SSP | ISLAND | 751 | 0.999 | 1.000 | 0.868 | True | False |
| WYNN | ISLAND | 751 | 1.000 | 1.000 | 0.905 | True | False |
| ADSK | ISLAND | 751 | 0.996 | 1.000 | 0.840 | True | False |
| BKNG | ISLAND | 751 | 0.999 | 1.000 | 0.479 | True | True |
| BIIB | ISLAND | 751 | 0.999 | 1.000 | 0.756 | True | False |
| KRE | ARCA | 751 | 0.983 | 1.000 | 0.879 | True | False |
| EWG | ARCA | 751 | 0.794 | 1.000 | 0.847 | False | False |
| XLU | ARCA | 751 | 0.993 | 1.000 | 0.952 | True | False |
| XLF | ARCA | 751 | 0.997 | 1.000 | 0.895 | True | False |
| VCR | ARCA | 751 | 0.919 | 1.000 | 0.525 | False | False |
| EWW | ARCA | 751 | 0.975 | 1.000 | 0.826 | True | False |
| VWO | ARCA | 751 | 0.984 | 1.000 | 0.977 | True | False |
| VUG | ARCA | 751 | 0.984 | 1.000 | 0.856 | True | False |
| EFA | ARCA | 751 | 0.967 | 1.000 | 0.979 | True | False |
| RSP | ARCA | 751 | 0.778 | 1.000 | 0.977 | False | False |
| XSD | ARCA | 751 | 0.917 | 1.000 | 0.450 | False | True |
| VTV | ARCA | 751 | 0.928 | 1.000 | 0.960 | False | False |

## 5m per-name statistics

Names by venue: {"NYSE": 12, "ISLAND": 12, "ARCA": 12}. Reasons: criterion_a: 0.028 of names pass, need 0.9; criterion_b: 0.000 of names pass, need 0.9.

| Symbol | Venue | Days | Listing max-volume share | Listing close match | Max other close match | Volume | Close |
| --- | --- | --- | --- | --- | --- | --- | --- |
| JPM | NYSE | 2340 | 0.662 | 0.980 | 0.963 | False | False |
| KR | NYSE | 2340 | 0.524 | 0.947 | 0.924 | False | False |
| FDS | NYSE | 2340 | 0.412 | 0.460 | 0.406 | False | False |
| ALK | NYSE | 2340 | 0.521 | 0.782 | 0.722 | False | False |
| WAT | NYSE | 2340 | 0.391 | 0.650 | 0.625 | False | False |
| PGR | NYSE | 2340 | 0.553 | 0.829 | 0.764 | False | False |
| CMS | NYSE | 2340 | 0.376 | 0.921 | 0.926 | False | False |
| BMY | NYSE | 2340 | 0.400 | 0.963 | 0.959 | False | False |
| RSG | NYSE | 2340 | 0.479 | 0.776 | 0.742 | False | False |
| NAD | NYSE | 2340 | 0.508 | 0.949 | 0.922 | False | False |
| AES | NYSE | 2340 | 0.451 | 0.962 | 0.971 | False | False |
| WSM | NYSE | 2340 | 0.649 | 0.687 | 0.541 | False | False |
| FISV | ISLAND | 2340 | 0.913 | 0.929 | 0.832 | False | False |
| ASML | ISLAND | 2340 | 0.887 | 0.972 | 0.947 | False | False |
| COST | ISLAND | 2340 | 0.869 | 0.964 | 0.911 | False | False |
| STBA | ISLAND | 2340 | 0.538 | 0.783 | 0.489 | False | False |
| PATK | ISLAND | 2340 | 0.568 | 0.539 | 0.394 | False | False |
| ATRO | ISLAND | 2340 | 0.586 | 0.463 | 0.285 | False | False |
| FCEL | ISLAND | 2340 | 0.876 | 0.720 | 0.599 | False | False |
| SSP | ISLAND | 2340 | 0.564 | 0.904 | 0.779 | False | False |
| WYNN | ISLAND | 2340 | 0.761 | 0.800 | 0.685 | False | False |
| ADSK | ISLAND | 2340 | 0.848 | 0.765 | 0.571 | False | False |
| BKNG | ISLAND | 2340 | 0.984 | 0.997 | 0.992 | True | False |
| BIIB | ISLAND | 2340 | 0.662 | 0.646 | 0.410 | False | False |
| KRE | ARCA | 2340 | 0.877 | 0.997 | 0.993 | False | False |
| EWG | ARCA | 2340 | 0.618 | 0.957 | 0.935 | False | False |
| XLU | ARCA | 2340 | 0.856 | 0.995 | 0.992 | False | False |
| XLF | ARCA | 2340 | 0.802 | 1.000 | 0.998 | False | False |
| VCR | ARCA | 2340 | 0.336 | 0.659 | 0.490 | False | False |
| EWW | ARCA | 2340 | 0.668 | 0.891 | 0.785 | False | False |
| VWO | ARCA | 2340 | 0.599 | 0.993 | 0.984 | False | False |
| VUG | ARCA | 2340 | 0.578 | 0.989 | 0.976 | False | False |
| EFA | ARCA | 2340 | 0.633 | 1.000 | 0.997 | False | False |
| RSP | ARCA | 2340 | 0.615 | 0.999 | 1.000 | False | False |
| XSD | ARCA | 2340 | 0.571 | 0.620 | 0.365 | False | False |
| VTV | ARCA | 2340 | 0.634 | 0.977 | 0.956 | False | False |

## Effect

- infra.bar_derivation.venue_bars_1d is set to False (D2 rule may use listing-venue 1d bars only when true).
- infra.bar_derivation.venue_bars_intraday is set to False (plan 20 intraday recovery may use venue bars only when true).
- Venue volume stays NULL in market_data_ohlcv_tradeable whatever the verdict (D-18).
## Reading of the result

Both timeframes fail on the pre-registered thresholds, so venue bars stay stored and unused: the D2 rule
does not use listing-venue 1d bars and plan 20 does not use venue bars for intraday recovery. The two APR
switches are false (version 2 each, changed_by venue_study_185, reason cites the verdict sha256).

- 1d criterion A: 30 of 36 names have the listing venue as the volume leader on at least 95 percent of
  days (0.833 against 0.9 needed). The six misses are five NYSE Arca ETFs (for example EWG at 0.794 and
  VTV at 0.928), where other venues carry more volume on a large share of days, and FISV (Nasdaq, 0.294).
- 1d criterion B: 5 of 36 names pass (0.139 against 0.9). The listing venue matches SMART's close on
  essentially every day, but the other routes also match it on well over half the days (typically
  0.8 to 0.98 for ARCA, BATS and ISLAND on NYSE and ETF names). Against a tolerance of one cent or five
  basis points, a venue's last print is usually the consolidated close, so "only its closes match" does
  not hold as D-17 phrased it.
- 5m: criterion A 1 of 36 and criterion B 0 of 36. The listing venue rarely leads volume on individual
  five-minute bars and every liquid venue tracks the SMART close.

The verdict was not tuned after the fact: the thresholds were committed before the first request and the
script judges mechanically. If venue history is still wanted for moved names (todo 433), the
pre-registered test says it cannot be justified as "listing-venue bars are official closes"; a different
question (for example, recover only where SMART is absent and flag the source) needs its own pre-registration.

## Run notes

- The provider returned 751 daily bars and 2340 five-minute bars per route (about 3 years and 30 sessions),
  wider than the 504 and 20 session windows in the pre-registration, because history requests round up to
  whole chunk durations. Every route and SMART covered the same span, so the per-name shares are computed
  on identical day sets; the window difference does not change which side of a threshold any share falls.
- The study held the priority lease from its start to its end (about 75 minutes) and was never asked to yield, so the todo 449 chain waited behind it for that time. The gateway stayed connected for the whole run.
- The fetch phase outlived the server idle-session timeout on the script's control connection, so the
  verdict write failed at the very end; the script now opens a fresh connection for it and has an
  --apply-only mode, which applied the verdict from the committed file.
