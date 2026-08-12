# Phase 146: Empirical Instrument Tag Calibrator - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-16
**Phase:** 146-Empirical Instrument Tag Calibrator
**Areas discussed:** taxonomy soundness (carried over from Phase 161's discussion), factor-series
data availability, credit tag redundancy, gold_beta, unmapped-tag partition, spread_leg,
concept-over-specific-proxy principle, vol_beta and oil_beta data-source resolution

---

## Taxonomy soundness — initial pass (before Fable dispatch)

User raised, from the prior Phase 161 conversation's momentum, that these systems seemed
interrelated and asked to plan Tag Calibrator (146) alongside Controlled Vocabulary (161). During
scoping, live DB queries surfaced:
- `macro_driver` vs `sensitivity` categories overlap conceptually, with `credit_cycle`/`credit_risk`
  as a likely literal duplicate.
- `gold_beta` (ROADMAP's TAG-01 spec) has no live tag anchor.
- 6 `macro_driver` tags (em_flows, fed_policy, geopolitical, housing_cycle, semi_cycle, yen_carry)
  plus `sensitivity`'s `yield_curve` don't map cleanly to the 8-beta spec.
- `signal_role`'s `spread_leg` (28/410 `instrument_tags` rows) is a relational fact miscast as a
  unary tag; 17 of 28 rows have NULL evidence.

**User's reaction:** "the 8 beta spec seems not well researched and analyzed, should we use Fable
on this phase?" — matching this project's established convention (Fable 5 for architecture/
planning judgment calls).

---

## Fable review dispatch (`docs/research/fable-2026-07-16-tag-calibrator-taxonomy-review.md`)

Dispatched a Fable-model Agent to independently verify the above against live DB state and
`docs/foundation/glossary.md`/`.planning/ROADMAP.md`, with instructions to reach concrete
conclusions rather than just flag options. Findings T1-T7 (see the review doc). Headline finding
the initial pass missed entirely: **3 of TAG-01's originally-specified 8 factor series (VIX, USO,
DXY) have zero usable daily bars** — a bigger blocker than the taxonomy naming issues, forcing a
Wave 0 before Wave 1's OLS pipeline can be coded at all.

| Question | Review's answer | Later revised? |
|---|---|---|
| Credit redundancy | Genuine — HYG/LQD carry both tags at near-identical weights live | No — confirmed as-is (D-03) |
| gold_beta | Keep beta, seed no tag (F8 inversion: tags derive from vector) | No — confirmed as-is (D-04) |
| 8 unmapped tags | 5 measurable nearly-free under F8's full matrix; 2 definitional; 1 delete | No — confirmed as-is (D-05/D-06/D-07) |
| spread_leg | Salvageable via migration + boundary test, not a new table | No — confirmed as-is (D-09) |
| vol_beta data source | Ingest VIX index dailies (recommended) | **Yes — revised** |
| oil_beta | Defer, mark definitional | **Yes — revised** |

---

## Concept-over-specific-proxy principle (user-driven revision)

**User's framing:** "the concept is more important than the specifics — we can use different beta
classifications based on the current 80 [symbols]; not all stratifications/classifications we
identify require symbols that use them now, do they?"

This resolved two things the review had left more conservative than necessary:

1. **vol_beta:** rather than ingesting new VIX data, reuse the SPY-realized-vol z-score
   `src/intelligence/regime_signals/breadth_vol.py` already computes live — same concept
   (volatility-regime sensitivity), zero new ingestion.
2. **Cheap-to-keep vs. broken-concept distinction:** clarified that keeping a vocabulary
   *definition* with zero/low current holders (`volatility`, `fed_policy`, `geopolitical`) costs
   nothing and isn't the "infrastructure for unproven ideas" anti-pattern — that rule is about new
   schema/services, not cheap taxonomy rows. `housing_cycle`'s deletion, by contrast, rests on a
   different and stronger basis: the tag's own factor series IS its only holder (a self-regression
   tautology), not a population-size argument. The two must not be conflated.

**Follow-up user question:** "isn't the concept [here] to look at cointegration of a security
against a benchmark to determine if the reviewed security has beta to the concept the benchmark
represents — e.g. anything with high cointegration to OIH could be considered to have high beta
to energy/oil?"

This directly un-blocked `oil_beta`. Verified live: XLE (5,034 bars), OIH (3,651), XOP (5,033),
AMLP (3,986) all have solid history via `market_data_ohlcv_tradeable`. The review's "no
non-circular in-universe factor" framing had been searching for a *pure* commodity series (CL/USO,
neither usable) rather than applying the same long-short-purification technique the review itself
already used for `credit_beta` (HYG-IEF) and `inflation` (TIP-IEF). Resolution: `oil_beta` =
XLE-SPY long-short, measurable in Phase 1, not deferred. The only real constraint (XLE tested
against itself) is already handled by the design doc's existing F6.1 degenerate-regression guard.

**Both design docs updated in place** (the canonical design doc's open-question closure note, and
the Fable review's own T1 finding + operator-decisions section) so no two canonical documents are
left disagreeing about the vol/oil resolution.

---

## Tech/semi — engine-general vs. seed-specific

**User's question:** "do we need to add more/different beta categories? tech/semi?"

Checked: `semi_cycle` (SMH) already exists as a live, assigned macro_driver tag and was already
in Phase 1's scope (D-05, "free" under the full-matrix loop) — nothing to add. A broader `tech_beta`
was technically viable (QQQ 5,036 bars, XLK 5,034 bars, both solid) but recommended against
adding: no live tag, no consumer trigger, and it would be the first of a GICS-sector-style
expansion this project's Classification Hierarchy (deferred) is meant to eventually own, not
Tag Calibrator.

**User's clarification, restating the founding concept:** "the original concept was to have a way
to calibrate the sensitivities to multiple stratifications of exposure" — confirming Tag
Calibrator's actual mission is a general-purpose calibration *engine*, not a fixed list of ~10
betas. This matches the design doc's existing F8 "Simons inversion" architecture exactly (unchanged
by this discussion) — the initial primitives are a seed set the engine ships with, not its
ceiling. Locked as D-12: the mechanism (`TagCalibrator`/`factor_math.py`) must be generic over
`(symbol, factor_series, measurement_type)`, but this phase does not proactively seed
stratifications beyond what's already live — a real future need (tech or otherwise) costs one
`tag_vocabulary` row when it actually arrives, not anticipatory scaffolding now.

## Claude's Discretion

- Exact migration numbers, `TagCalibrator`/`factor_math.py` method signatures, APR key names.
- `factor_math.py` module boundary and reuse of `ic_math.py`'s measurement kernel, per the design
  doc's own F4 finding (unchanged by this discussion).

## Deferred Ideas

- `spread_leg`'s 13 non-mechanically-recoverable pairs — needs a human pass by whoever seeded
  migration 227; deferred to Wave 0 execution time, not resolved in this discussion.
- Phase 2 regime-conditioning (Wave 3) — unchanged, still gated on Phase 1 shipping.
