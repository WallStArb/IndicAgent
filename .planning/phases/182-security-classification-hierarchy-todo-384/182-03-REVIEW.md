# Phase 182 plan 03: indicagent_v1 mapping review (D-04, D-06)

Author: Claude (Opus 5.5), executor. Date: 2026-09-25. The owner delegated this review ("i dont need
to review i trust you", 2026-09-25), so there is no human checkpoint.

Scope: 118 nodes and 295 assignments in `src/config/classification_seed_data.py`: 168 single names
from `config/classification/ibkr_classification_candidates.csv` (168/168 `ok`), 105 ETFs and
funds, and 22 inactive futures and FX pairs. Migration 365 is re-rendered from the reviewed data
and is still unapplied. Plan 07 applies it.

## Review passes

1. **Executor pass.** Every row was checked against its IBKR triple and the company's primary
   business, or against the fund mandate, grouped by code. Where a call was contestable, it was
   checked against two years of daily log returns from `market_data_ohlcv_tradeable` (1d).
   Correlations below are over roughly 370-500 overlapping days.
2. **Independent pass.** The plan names AGY, but AGY returned `RESOURCE_EXHAUSTED (429)`
   (individual quota, resets in about 133 h). The fallback, Codex (`gpt-5.5`), also hit its usage
   limit (resets 2026-10-15). The pass therefore ran as a fresh-context headless Claude
   (`claude -p --model opus --tools ""`). Its input was the review table and the D-03..D-06 rules
   only. It had no access to the executor's reasoning, the correlation evidence, or tools. This
   pass is independent of the executor's context, but not cross-vendor (see Deviations in
   182-03-SUMMARY.md).

## Rule adopted: ETF depth

The independent pass found that the ETF rows mixed two rules: "the mandate pins it down" (XHB,
CIBR) and "the dominant holdings decide" (ITB, URA, JETS). One written rule now governs all of
them, and the data module's docstring records it:

> An ETF sits at the deepest node that holds roughly 80% or more of its index weight by the fund's
> own methodology. Otherwise it moves up a level. A mandate spanning two or more sectors goes to
> EQ.BROAD.

The reviewer suggested about 85% (less than about 15% outside). The executor chose 80% because
holdings weights are not in the DB, so the threshold is applied by index methodology plus return
evidence, and a precision of plus or minus 5 points would be false.

## Rows changed

| Symbol | Before | After | Found by | Evidence |
|---|---|---|---|---|
| XTL | EQ.COM.TELECOM | EQ.BROAD | both | The S&P Telecom Select Industry index includes Communications Equipment (IT) at over a third of names. Correlation is 0.76 with XLK and 0.73 with SMH, but -0.03 with T, -0.04 with VZ and 0.01 with TMUS. |
| IYZ | EQ.COM.TELECOM | EQ.BROAD | both | Its own basis names telecom equipment. Correlation is 0.63 with XLK and 0.52 with XLC, but only 0.27 with T and 0.24 with VZ. |
| XHB | EQ.CD | EQ.BROAD | independent | Building products (Industrials) are about a third of an equal-weighted index, so the mandate spans two sectors. |
| ITB | EQ.CD.DURABLES.HOUSEHOLD | EQ.CD | independent | Homebuilders are about two thirds, below the 80% needed for the industry level. The rest is mostly home-improvement retail and furnishings (CD), plus building products. Correlation with DHI is 0.92, but the depth rule uses the mandate, not returns. |
| URA | EQ.EN.ENERGY | EQ.BROAD | both (different targets) | The mandate names miners, physical uranium trusts and nuclear component and construction makers. Correlation with XLE is 0.08, so Energy was wrong under either rule. The executor proposed EQ.MAT.MATERIALS. The independent pass proposed EQ.BROAD, and that was adopted under the written rule because the component makers and physical trusts fall outside Materials. |
| JETS | EQ.IND.TRANSPORT.AIRLINES | EQ.IND.TRANSPORT | independent | The index includes airports, aircraft makers and online travel agents alongside airlines. Airlines plus airports sit in Transportation. Correlation with DAL is 0.91, so the airline sleeve dominates, but it is not 80%+ airlines by methodology. |
| CCJ | EQ.EN.ENERGY.OILGAS (override) | EQ.MAT.MATERIALS.METALS (no override) | executor | Correlation is 0.08 with XLE, -0.01 with XOM and 0.02 with COP, against 0.51 with FCX, 0.48 with GDX, 0.45 with BHP and 0.42 with NEM. The IBKR triple (Mining / Non-Ferrous Metals) agrees. The primary activity is mining. |
| CMD.ENERGY (node name) | "Energy" | "Energy commodities" | independent | This was a level-2 name collision with EQ.EN "Energy". D-10 makes the level-2 node name the `Instrument.sector` label, so CL/NG futures and XLE would have merged into one "Energy" stratum. `validate_seed` now rejects duplicate names within a level (new unit test). |
| PG | - | override_reason added | independent | The triple is cosmetics/personal care, but fabric & home care is the largest segment, so Household Products. |
| GEV | - | override_reason added | independent | The triple is Machinery, but turbines and grid equipment are Electrical Equipment. |
| COIN | - | override_reason added | independent | It shares a triple with PURR. The split is explained on both rows now. |
| META | - | override_reason added | independent | It shares a triple with NFLX. The split is explained on both rows now. |

## Disagreements and how each was decided

| Item | Executor | Independent pass | Decision and evidence |
|---|---|---|---|
| CCJ | EQ.MAT.MATERIALS.METALS | keep EQ.EN.ENERGY.OILGAS (GICS convention for uranium) | **METALS.** The return evidence is decisive for a stratification scheme (correlations in the table above), and it matches the IBKR triple. indicagent_v1 reuses GICS names, not GICS assignments (D-03). |
| URA | EQ.MAT.MATERIALS | EQ.BROAD | **EQ.BROAD**, under the written depth rule (see the table above). |
| XRT | keep EQ.CD.RETAIL | EQ.BROAD (staples retailers are about a quarter of names) | **Keep EQ.CD.RETAIL.** Staples-side retailers are about 15 of about 78 equal-weighted names (about 20%), at the edge of the 80% rule. Returns side with discretionary: 0.78 with VCR and 0.74 with XLY, against 0.43 with XLP and 0.47 with VDC. Recorded as borderline. |
| EQ.IT.SEMI.EQUIP code | keep | rename to EQ.IT.SEMI.SEMI (the code reads as "equipment only") | **Keep.** The code is pinned by D-02, which gives it as its own example, and by the plan. The node's name is the full industry name, so the display is correct. Codes cannot change after apply, so this is settled now. |
| CCY.DM / CCY.USD names | keep | reword ("vs USD", "US dollar index") | **Keep.** These are pinned D-04 names, and there is no name collision. Names can update in place later if a consumer needs it. |
| ENPH, FSLR | considered EQ.IND.CAPGOODS.ELECTRICAL (with ARRY) | keep SEMI, borderline | **Keep SEMI.** Returns do not discriminate: 0.29 with SMH and 0.25 with EMR for ENPH, 0.36 and 0.27 for FSLR. The three solar names correlate 0.46-0.51 with each other and 0.57-0.67 with ICLN, so neither node captures the solar factor. The products are semiconductor devices (thin-film PV, ASIC-based microinverters). |
| CIBR | keep EQ.IT (IGV correlation 0.89 suggests Software & Services) | keep EQ.IT | **Keep EQ.IT.** The mandate includes hardware and communications equipment names, and some Industrials (about 10%). |

## Borderline rows kept (both passes agree)

- TDOC (Providers vs Health Care Technology): care is delivered through affiliated clinicians and BetterHelp therapy, so it is a service. Returns are weak either way (0.30 with XLV, 0.42 with XLC).
- MARA, RIOT, MSTR, PURR (EQ.FIN.FINSVC.FINSVC): the return driver is bitcoin (MSTR 0.79 with IBIT, MARA 0.69, RIOT 0.61). All four sit together. Revisit MARA and RIOT if the AI/HPC hosting pivot becomes the primary business (they would move to ITSVC like CRWV).
- AMZN (Broadline Retail): most revenue is retail, although AWS drives operating income.
- AVGO (Semis): chips still lead VMware software revenue.
- INSW (Oil & Gas): 0.30 with XOP and 0.29 with XLE, against 0.21 with KEX.
- HON (Conglomerates): revisit when the aerospace separation completes.
- DD (Chemicals), ACTG (Professional Services, a residual for a holding company), IBB (Biotech), IGV (Software), and the country and factor funds plus QQQ/NQ/EWT (EQ.BROAD by mandate).
- WSHP: the independent pass did not recognise the ticker. Its identity is IBKR's own `longName` (WESHOP HOLDINGS LTD-CL A) with triple Communications / Internet / E-Commerce/Products, so it is mapped to Broadline Retail as for AMZN. If a later reclassification finds a different primary business, that change goes through a close-and-insert migration.

## Thin non-equity branches

VOL has a single level-2 node (VOL.EQUITY) and MA has a single one (MA.ALT). CCY.EM, CRY.BROAD,
VOL.RATES and MA.ALLOC are unseeded until an instrument needs one, because `validate_seed` rejects
unused non-equity nodes. Both passes accept this, and a later migration adds each node through
`render_node_guard_sql`. EQ.RE.MGMT has no assignment. That is by design: all 25 equity industry
groups are seeded in full, and only level 4 is seeded on use.

## GICS naming (D-03)

The scheme row reads `indicagent_v1` / "IndicAgent security classification v1" / authority
`IndicAgent` / source_ref `phase_182_build`. `validate_seed` rejects "GICS" in any scheme field.
In the data module, "GICS" appears only in the docstring disclaimer and in two section comments
(`grep -ci gics` = 4 lines).

## Left for later (not in this plan's scope)

- **RSPG instrument name is wrong in `instruments`.** The name says "Invesco S&P 500 Equal Weight
  Consumer Staples ETF" and `sector` says `consumer_staples`. The ticker has been the Equal Weight
  Energy fund since Invesco's 2023 renaming (staples is RSPS). Correlation with XLE is 0.98 and
  with XLP 0.15. The seed maps it to EQ.EN.ENERGY with that evidence in the basis. The `name`
  field itself needs a data-fix migration. Logged in `deferred-items.md`.
- **VIX and VX are two inactive instrument rows for the same CFE contract** (trading class VX,
  point value 1000). Both map to VOL.EQUITY. Whether one row should be retired is an instruments
  question, not a classification one. Logged in `deferred-items.md`.
- Revisit triggers: MARA/RIOT (HPC pivot), HON (aerospace separation), and XRT if its staples share
  grows past about 20%.
