Author: Claude (session correcting Phase 174's single-name-equity framing, 2026-09-16)

# Cross-Asset-Class Diversification: Pre-Registration (Phase 174 follow-on)

**Status:** PRE-REGISTERED. The candidate list below is fixed and committed in this document.
The correlation-structure gate (Gate A) has **not been evaluated** against this list — that is
the next, separate step, to be run and reported regardless of outcome. Do not add or remove a
candidate after seeing a correlation number.

**Correction (same day, still before Gate A has been run against any candidate list):** the
first version of this document's selection rule picked candidates independently per group with
no check for redundancy *within* a group, and it silently recreated the exact failure mode this
whole document exists to avoid. Verified live: Group 2's original 11 equities included CVX+XOM
(pairwise correlation 0.850 — higher than a typical stock's correlation to the S&P) and five
homebuilders, DHI/LEN/MTH/NVR pairwise 0.65-0.85, because 8 of the 11 qualified via
`yield_curve`/`rate_sensitive`/`inflation` — three tags that are one underlying theme (duration
sensitivity), not three independent ones. Group 1's original 15-symbol list had the same issue:
TLT-IEF 0.910, IEF-SHY 0.784, IEF/TLT-LQD 0.70-0.71 (one duration trade wearing four tickers),
GLD-SLV-PPLT 0.62-0.79 (one precious-metals trade wearing three), and EMB-EMLC 0.672 (one EM
sovereign-debt trade wearing two). A candidate list padded with same-theme redundant tickers
inflates the raw symbol count without adding real independent bets — exactly the n_eff problem
D-10 exists to catch, just hidden inside the list this document was about to gate. Fixed by
adding an explicit within-pool de-duplication rule (below) and rebuilding both groups against it.
This is not a threshold renegotiation after seeing a gate result — Gate A has still never been
run against any version of this candidate list; it is a selection-methodology fix made before
any such result exists, discovered by checking the list's own internal correlation structure
before spending the gate on it.

**Supersedes-in-part:** STATE.md's Strategic Plan claim that "single-name equity IS the primary
breadth-scaling lever" (2026-09-13). See `docs/plans/methodology-change-ledger.md` E13 for the
full correction record and why that framing was wrong for the general equity population.

## Background

Phase 174's D-10 pilot (`174-15-SUMMARY.md`, `docs/research/phase174-down-cap-correlation-gate-verdict.md`)
drew 40 unbiased, market-cap-stratified single-name equities from the Russell 3000 and measured
their raw pairwise correlation against the existing 117-name book. Both pre-registered thresholds
failed by a wide margin (unconditional 0.3025 vs. ≤0.10; `high_bear` 0.4303 vs. ≤0.30).

Root-cause investigation (this session, 2026-09-16) found:

1. Not one of 18 regime-conditioned raw-correlation cells — 9 regimes × 2 independent equity
   populations (the pilot and the existing baseline) — clears even 0.14, let alone the 0.10
   unconditional threshold. The lowest of all 18 is baseline's `mid_bull` at 0.1423. A threshold
   no cell in either population can reach was never a fair test of *this* population specifically.
2. The driving mechanism, confirmed via `TagCalibrator`'s newly-fixed `equity_beta` measurement
   (mean loading ~0.39 across 107 measured single-names) and a direct residualization check: raw
   daily-return correlation among unhedged long-only U.S. equities is dominated by shared market
   beta, not by company-specific ("idiosyncratic") return drivers. Stripping SPY beta out of the
   pilot's returns drops correlation from 0.30 to 0.10 — right at the original threshold — meaning
   the idiosyncratic component genuinely is close to orthogonal; raw correlation just doesn't
   isolate it.
3. An exploratory 11-instrument cross-asset-class basket (GLD, DBC, URA, TLT, UUP, VIXY, EMLC,
   HYG, XOM, FCX, NEM — all already active/compute_eligible, zero onboarding cost) was run through
   the identical script and thresholds (`scripts/analysis/universe_expansion_correlation_structure_check.py
   --symbols ... --gate`) and **passed cleanly**: unconditional 0.0947, `high_bear` 0.1180, n_eff
   between 5.05 and 7.20 across every regime — beating the entire existing single-name book's best
   regime (n_eff ≈ 3.25) by a wide margin, with just 11 instruments.

That 11-symbol result is informative context, not a validated finding: it was hand-assembled in
conversation (some ETFs I already knew were in the corpus, some equities picked because their
business obviously tracks a commodity), which is exactly the selection-bias risk this project's
own pre-registration discipline (D-02: "systematic, no cherry-picking") exists to prevent. This
document replaces that hand-picked list with a mechanical, reproducible selection rule, committed
before any correlation number is computed against it.

## Why single-name-equity expansion isn't dead, but was mis-scoped

The original framing (STATE.md, 2026-09-13) argued single-name equity was the primary
breadth lever because it has "the scale (potentially hundreds to thousands of names) to move
[effective breadth] materially," versus ETF additions which "move the count from 231 to ~250,
noise against a breadth problem this severe." That's a *raw-count* argument. It was never checked
against a *decorrelation-quality* argument, and today's numbers show quality dominates: 11
well-chosen instruments beat the entire 117-128-name equity book's achievable n_eff. Scale without
decorrelation is not breadth — this is the same n_eff → 1/avg_corr math the pilot's own verdict
document already stated, just not carried through to its conclusion about *which* population to
draw from.

Separately, the reason nobody tested a thematically-selected equity population before now isn't
that it was overlooked — it's that the tool to identify such names without hand-picking didn't
functionally exist. `equity_beta` was correctly wired in `tag_vocabulary` (factor_series=SPY) but
had zero measured rows before this session, because `TagCalibrator` is a manual, no-timer oneshot
tool that had never been run comprehensively against the single-name book. Before today, "XOM
behaves like an oil stock" was an assertion, not a falsifiable, mechanically-derived fact.

## Hypothesis

A basket combining (1) instruments whose fund mandate tracks a genuinely non-equity underlying,
already active and compute-eligible in the corpus, and (2) single-name equities mechanically
identified as low-market-beta / high-alternative-factor via `TagCalibrator`'s empirical
measurements, clears the D-10 correlation gate and delivers materially higher effective breadth
than any equity-only construction — on a candidate list fixed *before* the correlation check is
run, not after.

## Group 1 — non-equity-underlying instruments (definitional, not statistical)

Membership criterion: the fund's own mandate tracks a physical commodity, a currency, a fixed-income
index, or an implied-volatility index — a verifiable fact about what the fund holds, not an
inferred statistical property, and applied without reference to any correlation number. This is
the same definitional-vs-empirical distinction the Instrument Tag Registry already draws for
`exposure`-category tags (`docs/foundation/instrument-tag-registry.md`).

**Explicitly not used for this selection:** `instrument_tags` rows for `clean_energy` (proxy=ICLN)
or `commodity_uranium` (proxy=URA) — checked live, both produced 294 empirical rows across
ordinary large-cap equities, confirming ICLN/URA are themselves equity-structured thematic funds
carrying real market beta, not clean non-equity proxies. Good for measuring *which stocks are
exposed to that theme* (their original purpose, fixed this session); wrong for defining "this
instrument itself is non-equity."

**Within-pool de-duplication rule (fixed after the correction above, applied uniformly, not
selectively):** compute all pairwise raw daily-return correlations within the candidate pool
before finalizing membership; where a pair exceeds 0.60, keep only the single most-liquid/most-
canonical instrument for that shared theme and drop the rest. 0.60 is a round, pre-committed cut
— not tuned to produce a particular final list: it excludes every pair actually found between
0.619 and 0.910, and admits everything found at or below 0.594.

| Symbol | Category | Mandate | Dropped same-theme siblings (>0.60 pairwise) |
|---|---|---|---|
| GLD | Precious metals | Physical gold | SLV (0.793), PPLT (0.619 w/ GLD, 0.689 w/ SLV) |
| DBA | Commodities | Broad agriculture futures | — (0.580 w/ DBC, below cutoff) |
| DBB | Commodities | Broad base-metals futures | — (0.566 w/ DBC, below cutoff) |
| DBC | Commodities | Broad commodity futures index | — |
| URA | Commodities | Uranium miners | — (max 0.444 w/ HYG, well clear) |
| TLT | Duration | 20+yr U.S. Treasury | IEF (0.910), SHY (via IEF 0.784), LQD (0.695) |
| UUP | Currency | USD index | — |
| VIXY | Volatility | VIX-futures-linked | — |
| EMLC | EM currency/duration | EM local-currency sovereign debt | EMB (0.672) |
| HYG | Credit | USD high-yield corporate bonds | — |

10 symbols, all confirmed `is_active=true AND compute_eligible=true` as of 2026-09-16 — zero
onboarding or backfill required. DBA/DBB/DBC are kept as three separate entries deliberately:
their pairwise correlations (0.566-0.580) sit below the 0.60 cutoff, and treating a composite
index alongside its own narrower sub-slices as fully redundant would be a stricter, different
rule than the one applied everywhere else in this table — flagged here so the choice is visible,
not buried.

## Group 2 — mechanically-selected low-beta / high-alt-factor single-name equities

Membership criterion, fixed before running: `equity_beta` (empirical, source='empirical') in the
bottom tertile of the single-name-equity population **AND** at least one of
{`oil_price`, `semi_cycle`, `china_demand`, `em_flows`, `dollar_strength`, `credit_risk`,
`inflation`, `rate_sensitive`, `yield_curve`} in the top tertile of *that tag's own* single-name
population. Tertile cutoffs computed from the live data, not chosen to hit a target list:

- `equity_beta` bottom-tertile cutoff: ≤ 0.3222 (n=107 measured single-names)
- Per-tag top-tertile cutoffs: `oil_price` ≥0.3423 (n=83), `semi_cycle` ≥0.3674 (n=74),
  `china_demand` ≥0.2984 (n=54), `em_flows` ≥0.3989 (n=90), `dollar_strength` ≥0.2397 (n=26),
  `credit_risk` ≥0.2870 (n=43), `inflation` ≥0.3455 (n=28), `rate_sensitive` ≥0.2825 (n=25),
  `yield_curve` ≥0.3243 (n=47)

Raw mechanical result (SQL in Appendix): **BKNG, CVX, DHI, ECL, GRBK, LEN, MTH, NVR, PGR, SPG,
XOM** (11 symbols). Checked this list's own within-pool correlation before finalizing membership
(same rule as Group 1) and it failed badly: CVX-XOM 0.850, and DHI/LEN/MTH/NVR pairwise
0.65-0.85 — 8 of the 11 qualified via `yield_curve`/`rate_sensitive`/`inflation`, three tags that
collapse onto one real theme (rate/duration sensitivity), not three independent ones.

**De-duplication, same 0.60 cutoff as Group 1, collapsing tags into their real underlying theme
rather than treating each tag as independent:** oil (`oil_price`) is one theme — keep the higher
of XOM (0.815 loading, corr 0.850 w/ CVX) or CVX; keep **XOM**. Rate/duration sensitivity
(`yield_curve`+`rate_sensitive`+`inflation` together) is one theme spanning DHI/ECL/GRBK/LEN/MTH/
NVR/SPG — keep only the single highest loading found across all three tags in that cluster:
**DHI** (`yield_curve` 0.479). `semi_cycle` is a singleton, no cluster: keep **PGR** (0.383).
No candidate qualified via `em_flows`/`china_demand`/`dollar_strength`/`credit_risk` at all in
this universe — an honest null result for those four themes, not a gap in the rule.

**Final Group 2: XOM, DHI, PGR** (3 symbols, down from 11). Sanity check against known business
exposure (checked after the mechanical rule, to confirm it isn't nonsense, not used to select):
XOM is an oil major; DHI is a homebuilder, rate-financing-dependent by construction; PGR is an
insurer, plausible bond-yield-sensitive investment book for the `semi_cycle` hit specifically
warrants a closer look during Gate B rather than being excluded here.

## Combined candidate list (13 symbols, post-correction)

GLD, DBA, DBB, DBC, URA, TLT, UUP, VIXY, EMLC, HYG, XOM, DHI, PGR

Verified no remaining pair across the full 13-symbol combined list exceeds 0.60 (checked live,
2026-09-16) — the highest is EMLC-HYG at 0.594, just under the cutoff.

## Gate A — correlation structure (not yet run)

Reuse D-10's exact thresholds and script, unmodified, for direct comparability:

```
.venv/bin/python scripts/analysis/universe_expansion_correlation_structure_check.py \
  --symbols GLD,DBA,DBB,DBC,URA,TLT,UUP,VIXY,EMLC,HYG,XOM,DHI,PGR \
  --gate --json-out /var/tmp/phase174_crossasset_prereg_gate.json
```

| Condition | Threshold |
|---|---|
| Unconditional avg pairwise raw correlation | ≤ 0.10 |
| `high_bear` avg pairwise raw correlation | ≤ 0.30 |

Reusing these values is now justified, not just inherited: the exploratory 11-symbol check
already demonstrated they are achievable for a genuinely cross-asset population, unlike for any
equity-only construction (see root-cause section above). Both outcomes are valid, complete results
— a FAIL here would mean the mechanical selection rule itself needs revision (e.g., different
tertile cutoffs, different factor tags), not that cross-asset diversification is dead; the
exploratory check already proved the concept works for *some* combination of these instruments.

## Gate B — real predictive signal (only if Gate A passes)

A passing correlation-structure gate proves the candidate list is well-diversified, not that any
of it has real alpha. Before this candidate list is used for anything beyond a diversification
demonstration, it needs the same OOS-proof discipline Phase 148 established for the existing
book (Gate 1/Gate 2): measured IC per instrument via the existing `ic_engine` pipeline. A
diversified basket of pure noise is not an improvement over a correlated basket of real signal.

## What this document does not do

It does not onboard anything (all 13 already exist and are compute-eligible in the general
corpus), does not run Gate A, does not set `compute_eligible` for any new *purpose* against
this candidate list specifically, and does not modify `alpha.universe.target_sample_size`
(D-01 still governs that key; unaffected by this document).

## Appendix — reproducible SQL for the Group 2 selection

```sql
-- Tertile cutoffs (re-run to reproduce the exact values above)
SELECT percentile_cont(0.33) WITHIN GROUP (ORDER BY weight) AS equity_beta_p33
FROM instrument_tags
WHERE tag='equity_beta' AND source='empirical'
AND symbol IN (SELECT symbol FROM instrument_tags WHERE tag='single_name_equity');

SELECT tag, percentile_cont(0.67) WITHIN GROUP (ORDER BY weight) AS p67, count(*) AS n
FROM instrument_tags
WHERE tag IN ('oil_price','semi_cycle','china_demand','em_flows','dollar_strength',
              'credit_risk','inflation','rate_sensitive','yield_curve')
AND source='empirical'
AND symbol IN (SELECT symbol FROM instrument_tags WHERE tag='single_name_equity')
GROUP BY tag;

-- Resulting candidate list (literal cutoffs from above, frozen at time of this document)
SELECT symbol FROM instrument_tags t
WHERE t.symbol IN (SELECT symbol FROM instrument_tags WHERE tag='single_name_equity')
AND t.tag='equity_beta' AND t.source='empirical' AND t.weight <= 0.3222
AND t.symbol IN (
  SELECT symbol FROM instrument_tags
  WHERE source='empirical' AND (
    (tag='oil_price' AND weight >= 0.3423) OR (tag='semi_cycle' AND weight >= 0.3674) OR
    (tag='china_demand' AND weight >= 0.2984) OR (tag='em_flows' AND weight >= 0.3989) OR
    (tag='dollar_strength' AND weight >= 0.2397) OR (tag='credit_risk' AND weight >= 0.2870) OR
    (tag='inflation' AND weight >= 0.3455) OR (tag='rate_sensitive' AND weight >= 0.2825) OR
    (tag='yield_curve' AND weight >= 0.3243)
  )
)
ORDER BY 1;
```
