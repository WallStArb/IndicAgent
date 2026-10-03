# Moved-name inventory

Author: phase 185 plan 14 (ops_head_rerun.py)
Informed by: D1 ohlcv_request / ohlcv_observation (D-16), D-20, D-27 step 2, plan 13 verdict (venue bars stay stored and unused)

Generated 2026-09-30. Late names are 1d names whose first ibkr_named bar falls after 2006-11-01: 382 counted at run time. Dispositions come from stored D1 answers only; unresolved is never counted as empty.

## Counts

| Disposition | Names |
| --- | --- |
| moved | 39 |
| verified_empty | 0 |
| reached_window_start | 301 |
| unresolved | 42 |
| total | 382 |

Distinct symbols with pre_move in ohlcv_venue_head among late names: 39 (moved count above: 39).

## Requests of this run

Fetch run ids: b8312c6e-a092-4264-9dd6-c0dd5dcbd5c9, 1847bc00-a523-40ff-8181-59c43d60e7e5

| Outcome | Requests |
| --- | --- |
| failed | 13 |
| no_data | 53 |

Failed-request outcomes seen: failed (error -): 13

## Every late name

| Symbol | SMART head | Disposition | Venue spans (first to last venue bar) |
| --- | --- | --- | --- |
| AA | 2016-10-18 | reached_window_start |  |
| ABBV | 2012-12-10 | reached_window_start |  |
| ABNB | 2020-12-10 | reached_window_start |  |
| ACMR | 2017-11-03 | reached_window_start |  |
| ACRS | 2015-10-07 | reached_window_start |  |
| ACVA | 2021-03-24 | reached_window_start |  |
| ADI | 2012-04-02 | moved | ARCA 2006-04-03 to 2012-03-29; BATS 2008-10-17 to 2012-03-29; NYSE 2006-04-03 to 2012-03-29 |
| ADP | 2008-10-21 | moved | BATS 2008-10-17 to 2008-10-17; NYSE 2005-10-19 to 2008-10-17 |
| ADPT | 2019-06-27 | reached_window_start |  |
| AGL | 2021-04-15 | reached_window_start |  |
| AKTS | 2026-01-09 | reached_window_start |  |
| ALLE | 2013-11-18 | reached_window_start |  |
| ALMS | 2024-06-28 | reached_window_start |  |
| ALRM | 2015-06-26 | reached_window_start |  |
| AMCR | 2019-06-11 | reached_window_start |  |
| AMD | 2015-01-02 | moved | ARCA 2006-01-03 to 2014-12-30; BATS 2008-10-17 to 2014-12-30; NYSE 2006-01-03 to 2014-12-30 |
| AMLP | 2010-08-25 | reached_window_start |  |
| AMPH | 2014-06-25 | unresolved |  |
| ANET | 2014-06-06 | unresolved |  |
| ANGL | 2012-04-11 | reached_window_start |  |
| ANRO | 2024-02-02 | reached_window_start |  |
| APMD | 2026-07-31 | reached_window_start |  |
| APO | 2016-12-09 | reached_window_start |  |
| APP | 2021-04-15 | reached_window_start |  |
| APPS | 2013-06-12 | unresolved |  |
| APTV | 2011-11-17 | reached_window_start |  |
| ARES | 2014-05-02 | unresolved |  |
| ARGT | 2011-03-03 | reached_window_start |  |
| ARKK | 2014-10-31 | reached_window_start |  |
| ARRY | 2020-10-16 | reached_window_start |  |
| ARTV | 2024-07-19 | reached_window_start |  |
| ATMU | 2023-05-26 | reached_window_start |  |
| AVBP | 2024-01-26 | reached_window_start |  |
| AVGO | 2016-02-02 | reached_window_start |  |
| AWK | 2008-04-23 | reached_window_start |  |
| AZTA | 2021-12-01 | moved | AMEX 2017-08-11 to 2021-11-29; ARCA 2009-06-22 to 2021-11-29; BATS 2007-05-07 to 2021-11-29; NYSE 2019-01-22 to 2021-11-29 |
| BAND | 2017-11-10 | reached_window_start |  |
| BCML | 2012-08-29 | unresolved |  |
| BE | 2018-07-25 | reached_window_start |  |
| BEAM | 2020-02-06 | reached_window_start |  |
| BH | 2010-04-09 | reached_window_start |  |
| BIL | 2007-05-30 | reached_window_start |  |
| BKLN | 2011-03-03 | reached_window_start |  |
| BKR | 2017-07-05 | reached_window_start |  |
| BLBD | 2014-03-20 | unresolved |  |
| BNDX | 2013-06-04 | reached_window_start |  |
| BNTX | 2019-10-10 | reached_window_start |  |
| BOC | 2017-06-16 | reached_window_start |  |
| BOW | 2024-05-23 | reached_window_start |  |
| BOX | 2015-01-23 | reached_window_start |  |
| BR | 2007-03-22 | reached_window_start |  |
| BRBR | 2019-10-17 | reached_window_start |  |
| BRSL | 2015-04-07 | reached_window_start |  |
| BTAL | 2011-09-14 | reached_window_start |  |
| BWIN | 2019-10-24 | reached_window_start |  |
| BWX | 2007-10-05 | reached_window_start |  |
| BX | 2007-06-22 | reached_window_start |  |
| C | 2009-07-21 | moved | ARCA 2006-07-19 to 2009-07-17; BATS 2008-10-17 to 2009-07-17 |
| CAR | 2010-12-31 | moved | ARCA 2006-01-03 to 2010-12-29; BATS 2008-10-17 to 2010-12-29; NYSE 2006-01-03 to 2010-12-29 |
| CARR | 2020-03-19 | reached_window_start |  |
| CBC | 2009-07-06 | reached_window_start |  |
| CBOE | 2010-06-15 | reached_window_start |  |
| CDRE | 2021-11-04 | reached_window_start |  |
| CDW | 2013-06-27 | reached_window_start |  |
| CEG | 2022-01-19 | reached_window_start |  |
| CFG | 2014-09-24 | reached_window_start |  |
| CGON | 2024-01-25 | reached_window_start |  |
| CHTR | 2010-09-15 | unresolved |  |
| CIBR | 2015-07-07 | reached_window_start |  |
| CMDB | 2025-05-01 | reached_window_start |  |
| CMPR | 2019-12-06 | reached_window_start |  |
| CNXC | 2020-11-24 | reached_window_start |  |
| COFS | 2012-07-23 | unresolved |  |
| COIN | 2021-04-14 | reached_window_start |  |
| COO | 2023-09-26 | reached_window_start |  |
| CORN | 2010-06-09 | reached_window_start |  |
| COUR | 2021-03-31 | reached_window_start |  |
| CPAY | 2010-12-15 | reached_window_start |  |
| CPER | 2011-11-16 | reached_window_start |  |
| CPS | 2013-10-17 | unresolved |  |
| CRC | 2020-10-28 | reached_window_start |  |
| CRH | 2023-09-25 | unresolved |  |
| CRSP | 2016-10-19 | reached_window_start |  |
| CRWD | 2019-06-12 | reached_window_start |  |
| CRWV | 2025-03-28 | reached_window_start |  |
| CSIQ | 2006-11-09 | reached_window_start |  |
| CSTM | 2013-05-23 | reached_window_start |  |
| CSX | 2015-12-22 | moved | ARCA 2005-12-21 to 2015-12-18; BATS 2008-10-17 to 2015-12-18; NYSE 2005-12-21 to 2015-12-18 |
| CTVA | 2019-05-24 | reached_window_start |  |
| CUBI | 2013-05-16 | unresolved |  |
| CVNA | 2017-04-28 | reached_window_start |  |
| CWB | 2009-04-17 | reached_window_start |  |
| CYRX | 2015-07-24 | unresolved |  |
| DAL | 2007-04-26 | unresolved |  |
| DASH | 2020-12-09 | reached_window_start |  |
| DBA | 2007-01-05 | reached_window_start |  |
| DBB | 2007-01-05 | reached_window_start |  |
| DD | 2017-09-01 | reached_window_start |  |
| DDOG | 2019-09-19 | reached_window_start |  |
| DELL | 2018-12-21 | reached_window_start |  |
| DG | 2009-11-13 | reached_window_start |  |
| DHC | 2016-07-01 | moved | ARCA 2006-07-03 to 2016-06-29; BATS 2008-10-17 to 2016-06-29; NYSE 2006-07-03 to 2016-06-29 |
| DLO | 2021-06-03 | reached_window_start |  |
| DOCS | 2021-06-24 | reached_window_start |  |
| DOW | 2019-03-20 | reached_window_start |  |
| ECH | 2007-11-16 | unresolved |  |
| ECHO | 2007-12-31 | reached_window_start |  |
| ECVT | 2017-09-29 | reached_window_start |  |
| EDV | 2007-12-13 | reached_window_start |  |
| EIDO | 2010-05-07 | reached_window_start |  |
| EMB | 2007-12-19 | reached_window_start |  |
| EMLC | 2010-07-26 | reached_window_start |  |
| ENOV | 2008-05-08 | reached_window_start |  |
| ENPH | 2012-03-30 | reached_window_start |  |
| ENTA | 2013-03-21 | reached_window_start |  |
| EPHE | 2010-09-29 | reached_window_start |  |
| EPOL | 2010-05-26 | reached_window_start |  |
| EPSN | 2019-02-13 | reached_window_start |  |
| EPU | 2009-06-23 | reached_window_start |  |
| ETHA | 2024-07-23 | reached_window_start |  |
| EVRG | 2018-06-05 | reached_window_start |  |
| EXE | 2021-02-10 | reached_window_start |  |
| FANG | 2012-10-12 | reached_window_start |  |
| FBRT | 2021-10-19 | reached_window_start |  |
| FERG | 2021-03-10 | reached_window_start |  |
| FLGT | 2016-09-29 | reached_window_start |  |
| FMAO | 2016-12-20 | reached_window_start |  |
| FOXA | 2019-03-13 | reached_window_start |  |
| FRHC | 2011-09-30 | unresolved |  |
| FSBC | 2021-05-05 | reached_window_start |  |
| FSLR | 2006-11-17 | reached_window_start |  |
| FTNT | 2009-11-18 | reached_window_start |  |
| FTV | 2016-06-13 | reached_window_start |  |
| FXY | 2007-02-13 | reached_window_start |  |
| GDDY | 2015-04-01 | reached_window_start |  |
| GDXJ | 2009-11-12 | reached_window_start |  |
| GEHC | 2022-12-15 | reached_window_start |  |
| GENB | 2026-02-27 | reached_window_start |  |
| GEV | 2024-03-27 | reached_window_start |  |
| GKOS | 2015-06-25 | reached_window_start |  |
| GM | 2010-11-18 | reached_window_start |  |
| GNRC | 2010-02-11 | reached_window_start |  |
| GRBK | 2007-06-14 | reached_window_start |  |
| HAS | 2010-12-21 | moved | ARCA 2005-12-19 to 2010-12-17; BATS 2008-10-17 to 2010-12-17; NYSE 2005-12-19 to 2010-12-17 |
| HCA | 2011-03-10 | reached_window_start |  |
| HCKT | 2008-01-02 | reached_window_start |  |
| HII | 2011-03-22 | reached_window_start |  |
| HLT | 2013-12-12 | reached_window_start |  |
| HNRG | 2010-05-21 | unresolved |  |
| HONA | 2026-06-15 | reached_window_start |  |
| HOOD | 2021-07-29 | unresolved |  |
| HPE | 2015-10-19 | reached_window_start |  |
| HYD | 2009-02-05 | reached_window_start |  |
| HYG | 2007-04-11 | reached_window_start |  |
| IBB | 2008-09-24 | moved | AMEX 2006-09-21 to 2008-09-19 |
| IBEX | 2020-08-10 | reached_window_start |  |
| IBIT | 2024-01-11 | reached_window_start |  |
| IBKR | 2007-05-04 | reached_window_start |  |
| IBP | 2014-02-13 | unresolved |  |
| ICLN | 2008-06-25 | reached_window_start |  |
| IDR | 2011-02-24 | unresolved |  |
| IEF | 2017-08-03 | moved | AMEX 2006-08-07 to 2017-08-01; ARCA 2006-08-07 to 2017-08-01; BATS 2010-06-22 to 2017-08-01; NYSE 2006-08-07 to 2007-08-16 |
| IEI | 2017-08-03 | moved | ARCA 2007-01-17 to 2017-08-01; BATS 2010-06-22 to 2017-08-01; NYSE 2007-01-11 to 2007-12-05 |
| IIPR | 2016-12-01 | reached_window_start |  |
| INDA | 2013-10-18 | reached_window_start |  |
| INGN | 2014-02-14 | unresolved |  |
| INSP | 2018-05-03 | reached_window_start |  |
| INSW | 2016-11-16 | reached_window_start |  |
| INVH | 2017-02-01 | reached_window_start |  |
| IPO | 2013-10-16 | reached_window_start |  |
| IQV | 2013-05-09 | reached_window_start |  |
| IR | 2017-05-12 | reached_window_start |  |
| IRT | 2013-08-13 | reached_window_start |  |
| IVZ | 2007-05-24 | reached_window_start |  |
| JBS | 2025-06-13 | reached_window_start |  |
| JCI | 2009-03-17 | moved | BATS 2008-10-17 to 2009-03-13 |
| JETS | 2015-04-30 | reached_window_start |  |
| JMSB | 2013-11-21 | reached_window_start |  |
| KDP | 2008-04-28 | reached_window_start |  |
| KEYS | 2014-10-20 | reached_window_start |  |
| KHC | 2015-07-06 | reached_window_start |  |
| KKR | 2010-07-15 | reached_window_start |  |
| KMI | 2011-02-11 | reached_window_start |  |
| KN | 2014-02-14 | unresolved |  |
| KRUS | 2019-08-01 | reached_window_start |  |
| KSA | 2015-09-18 | reached_window_start |  |
| KURA | 2015-11-05 | unresolved |  |
| KVUE | 2023-05-04 | reached_window_start |  |
| KWEB | 2013-08-01 | reached_window_start |  |
| LASR | 2018-04-26 | reached_window_start |  |
| LDOS | 2013-09-30 | moved | ARCA 2013-09-11 to 2013-09-26; BATS 2013-09-11 to 2013-09-26; ISLAND 2013-09-11 to 2013-09-26 |
| LIN | 2018-10-31 | reached_window_start |  |
| LITE | 2015-07-23 | reached_window_start |  |
| LMNR | 2010-05-27 | unresolved |  |
| LOAR | 2024-04-25 | reached_window_start |  |
| LQDA | 2018-07-26 | reached_window_start |  |
| LULU | 2007-07-27 | reached_window_start |  |
| LYB | 2010-10-14 | unresolved |  |
| MAMA | 2014-07-18 | unresolved |  |
| MAR | 2013-10-21 | moved | ARCA 2005-10-20 to 2013-10-17; BATS 2008-10-17 to 2013-10-17; NYSE 2005-10-20 to 2013-10-17 |
| MARA | 2014-07-28 | unresolved |  |
| MATX | 2012-07-02 | moved | ARCA 2006-07-03 to 2012-06-28; BATS 2007-05-07 to 2012-06-28 |
| MBB | 2017-08-03 | moved | AMEX 2007-03-16 to 2017-08-01; ARCA 2007-05-22 to 2017-08-01; BATS 2008-10-17 to 2017-08-01 |
| MBX | 2024-09-13 | reached_window_start |  |
| MCHI | 2016-02-04 | moved | ARCA 2011-03-31 to 2016-02-02; BATS 2011-04-01 to 2016-02-02 |
| META | 2012-05-18 | reached_window_start |  |
| MFP | 2026-06-29 | reached_window_start |  |
| MGTX | 2018-06-08 | reached_window_start |  |
| MNST | 2015-06-16 | reached_window_start |  |
| MOO | 2007-09-05 | reached_window_start |  |
| MPB | 2008-10-21 | moved | AMEX 2005-10-19 to 2008-10-17 |
| MPC | 2011-06-23 | reached_window_start |  |
| MRNA | 2018-12-07 | reached_window_start |  |
| MSCI | 2007-11-15 | reached_window_start |  |
| MTUM | 2013-04-18 | reached_window_start |  |
| MU | 2009-12-30 | moved | ARCA 2005-12-30 to 2009-12-28; BATS 2008-10-17 to 2009-12-28; NYSE 2005-12-30 to 2009-12-28 |
| MUB | 2007-09-10 | reached_window_start |  |
| MUX | 2012-01-27 | reached_window_start |  |
| MVBF | 2010-06-28 | reached_window_start |  |
| MYRG | 2008-09-09 | unresolved |  |
| NCLH | 2013-01-18 | reached_window_start |  |
| NEE | 2010-06-24 | reached_window_start |  |
| NESR | 2017-06-05 | reached_window_start |  |
| NEXT | 2017-07-26 | moved | ARCA 2015-06-16 to 2017-07-21; BATS 2015-07-10 to 2017-07-21 |
| NOW | 2012-06-29 | reached_window_start |  |
| NRIX | 2020-07-27 | reached_window_start |  |
| NTR | 2018-01-02 | reached_window_start |  |
| NUVB | 2020-08-26 | reached_window_start |  |
| NVST | 2019-09-18 | reached_window_start |  |
| NWSA | 2013-06-19 | reached_window_start |  |
| NXPI | 2010-08-06 | reached_window_start |  |
| NXRT | 2015-03-19 | reached_window_start |  |
| OCUL | 2014-07-25 | unresolved |  |
| ODFL | 2024-05-07 | unresolved |  |
| OEC | 2014-07-25 | unresolved |  |
| OGS | 2014-01-16 | unresolved |  |
| OIH | 2011-12-21 | reached_window_start |  |
| OLED | 2013-06-24 | unresolved |  |
| OSW | 2019-03-21 | reached_window_start |  |
| OTIS | 2020-03-19 | reached_window_start |  |
| OUT | 2014-03-28 | unresolved |  |
| P | 2015-10-07 | reached_window_start |  |
| PAG | 2007-07-02 | reached_window_start |  |
| PAGS | 2018-01-24 | reached_window_start |  |
| PALL | 2010-01-11 | reached_window_start |  |
| PANW | 2012-07-20 | reached_window_start |  |
| PARR | 2014-07-22 | unresolved |  |
| PAYO | 2020-10-16 | reached_window_start |  |
| PBFS | 2019-07-18 | reached_window_start |  |
| PENG | 2017-05-24 | reached_window_start |  |
| PEP | 2017-12-20 | moved | AMEX 2017-07-25 to 2017-12-18; ARCA 2005-12-22 to 2017-12-18; BATS 2008-10-17 to 2017-12-18; NYSE 2005-12-22 to 2017-12-18 |
| PFF | 2017-08-03 | moved | AMEX 2007-03-30 to 2017-08-01; ARCA 2007-05-22 to 2017-08-01; BATS 2008-10-17 to 2017-08-01 |
| PFG | 2017-12-18 | moved | AMEX 2017-07-25 to 2017-12-14; ARCA 2005-12-19 to 2017-12-14; BATS 2008-10-17 to 2017-12-14; NYSE 2005-12-19 to 2017-12-14 |
| PGNY | 2019-10-25 | reached_window_start |  |
| PLD | 2011-06-03 | reached_window_start |  |
| PLMR | 2019-04-17 | reached_window_start |  |
| PLOW | 2010-05-05 | reached_window_start |  |
| PLTR | 2024-09-25 | reached_window_start |  |
| PM | 2008-03-17 | reached_window_start |  |
| PMTS | 2015-10-09 | reached_window_start |  |
| PODD | 2007-05-15 | reached_window_start |  |
| POST | 2012-01-27 | reached_window_start |  |
| POWI | 2007-08-13 | unresolved |  |
| PPLT | 2010-01-11 | reached_window_start |  |
| PSKY | 2025-08-07 | reached_window_start |  |
| PSX | 2012-04-12 | reached_window_start |  |
| PTGX | 2016-08-11 | reached_window_start |  |
| PUMP | 2017-03-17 | reached_window_start |  |
| PURR | 2025-12-03 | reached_window_start |  |
| PWP | 2020-11-20 | reached_window_start |  |
| PYPL | 2015-07-06 | reached_window_start |  |
| Q | 2025-10-27 | reached_window_start |  |
| QUAL | 2013-07-18 | reached_window_start |  |
| RCAT | 2007-05-11 | reached_window_start |  |
| RDDT | 2024-03-21 | reached_window_start |  |
| RDW | 2021-01-14 | reached_window_start |  |
| REA | 2026-05-06 | reached_window_start |  |
| RIOT | 2012-12-20 | moved | ARCA 2009-06-22 to 2012-12-18; BATS 2007-09-11 to 2012-12-18 |
| RIVN | 2021-11-10 | reached_window_start |  |
| RLAY | 2020-07-17 | reached_window_start |  |
| RSPC | 2018-11-07 | reached_window_start |  |
| RSPD | 2006-11-07 | reached_window_start |  |
| RSPF | 2006-11-07 | reached_window_start |  |
| RSPG | 2006-11-07 | reached_window_start |  |
| RSPH | 2006-11-07 | reached_window_start |  |
| RSPM | 2006-11-07 | reached_window_start |  |
| RSPN | 2006-11-07 | reached_window_start |  |
| RSPR | 2018-04-09 | moved | BATS 2015-11-04 to 2018-03-29 |
| RSPS | 2006-11-07 | reached_window_start |  |
| RSPT | 2006-11-07 | reached_window_start |  |
| RSPU | 2006-11-07 | reached_window_start |  |
| RVMD | 2020-02-13 | reached_window_start |  |
| SCHD | 2011-10-21 | reached_window_start |  |
| SCHW | 2010-03-05 | moved | ARCA 2009-06-22 to 2010-03-03; BATS 2007-05-07 to 2010-03-03 |
| SDOG | 2012-06-29 | reached_window_start |  |
| SDRL | 2022-08-29 | reached_window_start |  |
| SEZL | 2023-08-17 | reached_window_start |  |
| SGHC | 2020-11-23 | unresolved |  |
| SHC | 2020-11-20 | reached_window_start |  |
| SHV | 2007-01-11 | reached_window_start |  |
| SHY | 2017-08-03 | moved | AMEX 2006-08-07 to 2017-08-01; ARCA 2006-08-07 to 2017-08-01; BATS 2010-06-22 to 2017-08-01; NYSE 2006-08-07 to 2007-08-16 |
| SJNK | 2012-03-15 | reached_window_start |  |
| SLM | 2011-12-12 | moved | ARCA 2005-12-12 to 2011-12-08; BATS 2008-10-17 to 2011-12-08; NYSE 2005-12-12 to 2011-12-08 |
| SMCI | 2007-03-29 | reached_window_start |  |
| SMH | 2011-12-21 | reached_window_start |  |
| SNDK | 2025-02-13 | reached_window_start |  |
| SOLV | 2024-03-26 | reached_window_start |  |
| SOYB | 2011-09-19 | reached_window_start |  |
| SPHB | 2011-05-05 | reached_window_start |  |
| SPNT | 2013-08-15 | reached_window_start |  |
| SRRK | 2018-05-24 | reached_window_start |  |
| STIP | 2010-12-03 | reached_window_start |  |
| STUB | 2025-09-17 | reached_window_start |  |
| SVRA | 2017-04-28 | moved | AMEX 2006-05-01 to 2017-04-26; ARCA 2006-05-01 to 2017-04-26; BATS 2008-10-17 to 2017-04-26 |
| SW | 2024-07-08 | reached_window_start |  |
| SYF | 2014-07-31 | reached_window_start |  |
| TDOC | 2015-07-01 | reached_window_start |  |
| TEL | 2007-06-14 | reached_window_start |  |
| THD | 2008-03-28 | reached_window_start |  |
| THRM | 2012-06-13 | reached_window_start |  |
| TLH | 2007-01-11 | reached_window_start |  |
| TLT | 2016-02-03 | moved | AMEX 2006-02-06 to 2007-08-30; ARCA 2006-02-06 to 2016-02-01; BATS 2010-06-22 to 2016-02-01; NYSE 2006-02-06 to 2007-08-16 |
| TMUS | 2007-04-19 | reached_window_start |  |
| TPB | 2016-05-11 | reached_window_start |  |
| TPL | 2021-01-12 | reached_window_start |  |
| TRGP | 2010-12-07 | reached_window_start |  |
| TRV | 2007-02-27 | reached_window_start |  |
| TSLA | 2010-06-29 | reached_window_start |  |
| TUR | 2017-08-03 | moved | AMEX 2017-07-26 to 2017-07-26; ARCA 2008-03-28 to 2017-08-01; BATS 2010-06-22 to 2017-08-01 |
| TXN | 2012-01-03 | moved | ARCA 2006-01-03 to 2011-12-29; BATS 2008-10-17 to 2011-12-29; NYSE 2006-01-03 to 2011-12-29 |
| UAL | 2018-09-10 | moved | AMEX 2017-07-25 to 2018-09-06; ARCA 2009-06-22 to 2018-09-06; BATS 2007-05-07 to 2018-09-06; NYSE 2010-10-01 to 2018-09-06 |
| UBER | 2019-05-10 | reached_window_start |  |
| ULTA | 2007-10-25 | reached_window_start |  |
| UNG | 2007-04-18 | unresolved |  |
| UNL | 2009-11-19 | reached_window_start |  |
| UPB | 2024-10-11 | reached_window_start |  |
| URA | 2010-11-05 | reached_window_start |  |
| USAU | 2016-07-11 | moved | ARCA 2009-06-23 to 2016-07-07; BATS 2007-05-10 to 2016-07-07 |
| USL | 2007-12-06 | unresolved |  |
| USMV | 2011-10-21 | reached_window_start |  |
| UUP | 2007-02-20 | reached_window_start |  |
| UUUU | 2013-12-04 | unresolved |  |
| V | 2008-03-19 | reached_window_start |  |
| VATE | 2013-10-29 | reached_window_start |  |
| VCLT | 2009-11-23 | reached_window_start |  |
| VEEV | 2013-10-16 | reached_window_start |  |
| VICI | 2017-10-18 | reached_window_start |  |
| VISN | 2013-10-25 | reached_window_start |  |
| VIXM | 2011-01-04 | reached_window_start |  |
| VIXY | 2011-01-04 | reached_window_start |  |
| VLTO | 2023-09-27 | reached_window_start |  |
| VNM | 2009-08-17 | unresolved |  |
| VOR | 2021-02-08 | reached_window_start |  |
| VOYG | 2025-06-11 | reached_window_start |  |
| VRP | 2014-05-01 | unresolved |  |
| VRSK | 2009-10-07 | reached_window_start |  |
| VRT | 2018-07-30 | reached_window_start |  |
| VST | 2016-10-05 | reached_window_start |  |
| VSTS | 2023-09-27 | reached_window_start |  |
| VTRS | 2008-12-29 | moved | BATS 2008-10-17 to 2008-12-24; NYSE 2005-12-27 to 2008-12-24 |
| VYM | 2006-11-16 | reached_window_start |  |
| WDAY | 2017-09-20 | moved | AMEX 2017-07-25 to 2017-09-18; ARCA 2012-10-12 to 2017-09-18; BATS 2012-10-12 to 2017-09-18; NYSE 2012-10-12 to 2017-09-18 |
| WDC | 2012-06-01 | moved | ARCA 2006-06-02 to 2012-05-30; BATS 2008-10-17 to 2012-05-30; NYSE 2006-06-02 to 2012-05-30 |
| WEAT | 2011-09-19 | reached_window_start |  |
| WRB | 2006-11-16 | reached_window_start |  |
| WSHP | 2025-11-14 | reached_window_start |  |
| WT | 2011-07-27 | unresolved |  |
| WTW | 2016-01-05 | reached_window_start |  |
| XAR | 2011-09-29 | reached_window_start |  |
| XEL | 2018-01-02 | moved | AMEX 2017-07-25 to 2017-12-28; ARCA 2006-01-03 to 2017-12-28; BATS 2008-10-17 to 2017-12-28; NYSE 2006-01-03 to 2017-12-28 |
| XERS | 2018-06-21 | reached_window_start |  |
| XHE | 2011-01-27 | reached_window_start |  |
| XHS | 2011-09-29 | reached_window_start |  |
| XLC | 2018-06-19 | reached_window_start |  |
| XLRE | 2015-10-08 | reached_window_start |  |
| XSW | 2011-09-29 | reached_window_start |  |
| XTL | 2011-01-27 | reached_window_start |  |
| XTN | 2011-01-27 | reached_window_start |  |
| XYL | 2011-10-13 | reached_window_start |  |
| XYZ | 2015-11-19 | reached_window_start |  |
| XZO | 2025-11-05 | reached_window_start |  |
| ZTS | 2013-02-01 | reached_window_start |  |

## Recovery applied (plan 185-19, 2026-10-03)

The venue study failed both criteria at 1d and 5m (`config/bars/venue_study_verdict.json`) and
`infra.bar_derivation.venue_bars_1d` is false, so no venue bar became a canonical 1d bar. The 39
moved names keep their pre-move history as venue observations in D1 (`ohlcv_observation`, routes
NYSE, ARCA, AMEX, BATS, ISLAND), stored and unused: the derivation ignores venue observations
while the gate is false. Baseline taken before any step ran: 0 stored `ibkr_venue` 1d rows in
`market_data_ohlcv` and 0 rows with venue volume in `market_data_ohlcv_tradeable`; both are
unchanged. The per-name recovered spans are the table above. Enabling the gate later needs the
seam and volume checks recorded in `tests/integration/test_d3_d4_live.py`, which fails loudly
until they exist.

1d empty history reconciled from recorded answers (`reconcile_empty_history(conn, "1d", "ibkr")`):
115 rows considered, 26 kept (backed by SMART plus every former venue except the primary
answering no_data in one run), 89 deleted, 0 inserted, 0 extended. The 89 predate D1 capture
(verified 2026-09-24 to 2026-09-29, before the answers were recorded, and the bootstrap imported
stored bars as `legacy_import`, never as no_data windows), so nothing confirms them; their pre-listing spans are
asked again at the next 1d fetch of each name, about 12 requests per name.
