# Phase 146: Empirical Instrument Tag Calibrator - Context

**Gathered:** 2026-07-16
**Status:** Ready for planning

<domain>
## Phase Boundary

**The founding concept, restated explicitly (2026-07-16, confirmed by the project owner):** this
phase is not "compute these 10 specific betas" — it is a **general-purpose calibration engine for
measuring an instrument's sensitivity to multiple stratifications of exposure**, where the
current ~10 factor primitives (equity, rate, curve, credit, gold, dollar, china, inflation, vol,
oil, plus free-rider em_flows/semi_cycle/yen_carry) are the *initial seed set* the engine ships
with, not its ceiling. This framing is not new scope — it is exactly what the design doc's F8
"Simons inversion" (full-matrix OLS loop: measure every instrument against every registered
`factor_series` value, derive tags from the results, never hand-pick which pairs get tested)
already architects, unchanged by this discussion. The deliverable of Wave 1 is the engine plus its
initial seed set, not a fixed list — adding a genuinely new stratification later (tech, a GICS
sector, a factor style) costs one `tag_vocabulary` row with a `factor_series` value, zero new code
or schema, the same namespace-keyed extensibility principle established in Phase 161's Controlled
Vocabulary discussion. See D-12 below for what this does and does not license.

Build the `TagAuditor`/`TagCalibrator` empirical calibration system that replaces manually-asserted
instrument tags with measured OLS factor betas (nightly batch), per ROADMAP Phase 146's TAG-01/02/03
requirements. This phase's design was already extensively reviewed (2026-07-06 Fable pass, F1-F9,
all resolved) before this discussion started. This session's discussion surfaced a genuine blocker
the prior review didn't check — live factor-data availability — via a dispatched second Fable
review (`docs/research/fable-2026-07-16-tag-calibrator-taxonomy-review.md`, findings T1-T7). That
review adds a new **Wave 0** (taxonomy cleanup + factor-data readiness) ahead of the original
3-wave plan and reorders Wave 1/2 (schema migration must precede the service that reads/writes it).
The 3-wave shape otherwise survives unchanged.

</domain>

<decisions>
## Implementation Decisions

### Wave 0 added — taxonomy cleanup + factor-data readiness (blocks Wave 1)
- **D-01:** Add a Wave 0 before the original Wave 1 (TagAuditor service) / Wave 2 (DB migration) /
  Wave 3 (Phase 2 regime-conditioning design). Wave 1's OLS pipeline cannot be coded until the
  factor-series list is real — 3 of TAG-01's originally-specified 8 factor series (VIX, USO, DXY)
  have zero usable daily bars in `market_data_ohlcv` (verified live 2026-07-16). Wave 0 also fixes
  the Wave 1/2 ordering defect: the roadmap had the service (reads/writes `tag_vocabulary`/
  `instrument_tags` columns) built before the migration that creates those columns — backwards.
  The measurement-contract migration belongs at the start of Wave 1 or end of Wave 0.

### Concept over specific proxy — the standing principle for this phase's factor-series choices
- **D-02:** Every factor series substitution below follows one rule: **the registered thing is
  the concept (a factor loading), not a specific ticker** — the proxy symbol is an implementation
  detail that adapts to what the current 80-symbol universe actually has live data for. Applied
  consistently:
  - `dollar_beta`: **UUP** (not DXY — not an instrument; UUP has 7,075 live daily bars)
  - `china_beta`: **FXI** (not KWEB — FXI has 7,299 bars vs KWEB's 4,724; ROADMAP said FXI, doc said
    KWEB — FXI wins on history depth)
  - `credit_beta`: **HYG-IEF long-short** (not raw HYG) — purifies the credit-spread signal from
    HYG's substantial embedded equity beta, which would otherwise "confirm" credit sensitivity for
    the whole equity book (a false-positive risk, not just an aesthetic preference)
  - `inflation`: **TIP-IEF long-short** (breakeven-inflation proxy), not raw TIP beta (which is
    duration-dominated and would largely re-measure `rate_beta`)
  - `yield_curve`: **IEF-SHY long-short** (curve-slope proxy) — both live, 3,261 bars (~13y),
    clears the 252-day lookback with room to spare
  - `vol_beta`: **reuse the existing SPY-realized-vol z-score already computed live in
    `src/intelligence/regime_signals/breadth_vol.py`** (lines 3, 44-46) as the factor input.
    **Not VIX ingestion** — VIX exists as an inactive instrument with zero daily bars, and ingesting
    it would be new data-pipeline work for a concept (volatility-regime sensitivity) the platform
    already computes and uses live elsewhere. Zero new ingestion, zero new instrument onboarding.
    (Revises this discussion's own earlier lean toward "ingest VIX" — the concept-over-specifics
    principle gives a cheaper, more consistent answer once applied fully.)
  - `oil_beta`: **measurable in Phase 1 via XLE-SPY long-short** — not deferred. Revised during
    this discussion: the initial review's "circular, no substitute" call was too narrow — it looked
    for a *pure* commodity series (CL/USO, neither has usable data) when the same purification
    technique already used for `credit_beta`/`inflation` applies directly. XLE, OIH, XOP, and AMLP
    all have solid live daily bars (verified: 5,034/3,651/5,033/3,986 respectively via
    `market_data_ohlcv_tradeable`); XLE-SPY long-short purifies out general equity-market beta the
    same way HYG-IEF purifies credit and TIP-IEF purifies inflation. The only real constraint is
    the design doc's existing F6.1 degenerate-regression guard (`symbol == factor_series` skip),
    which already handles XLE-tested-against-itself — it does not block OIH/XOP/AMLP or any other
    instrument in the universe from being legitimately tested against this factor. Chose XLE over
    OIH/XOP as the benchmark for broader energy-sector representation and tied-deepest history.

### Credit tag merge (genuinely redundant, not just similarly named)
- **D-03:** Merge `credit_cycle` into `credit_risk` — verified live that HYG and LQD each already
  carry BOTH tags at near-identical weights (HYG: 0.9/1.0, LQD: 0.8/0.8), so the redundancy exists
  in the data, not just the taxonomy. Migrate the 8 `credit_cycle` assignments into `credit_risk`
  rows (max-weight on collisions), retire `credit_cycle` from `tag_vocabulary`, record it in
  `docs/foundation/glossary.md` as a banned alias.

### gold_beta: keep the beta, seed no tag
- **D-04:** GLD has 7,313 live daily bars — the cleanest series available. `gold_beta` stays a
  required input to the `risk_off`/`inflation` derivations and the crisis-hedge fingerprint the
  design doc calls "the signal." Do not seed a human gold-sensitivity tag — under the design doc's
  F8 Simons-inversion (factor vector is the source of truth; tags are derived read-outs), seeding a
  tag here would insert a belief precisely where this phase exists to replace beliefs. The human
  query handle already exists and is correctly definitional: `commodity_metals_precious`.

### 5 of 8 "unmapped" tags are measurable in Phase 1, nearly free
- **D-05:** `yield_curve`, `inflation`, `em_flows`, `semi_cycle`, `yen_carry` are all measurable
  under the full-matrix OLS loop (F8's Simons inversion) at near-zero marginal cost once that loop
  exists — a prior, more conservative read in this discussion (treating each as needing its own
  bespoke machinery) was wrong; under F8 the marginal cost of one more measurable tag is a single
  `factor_series` value in a vocabulary row, not new code.

### Definitional-only / deletion resolutions
- **D-06:** `fed_policy` and `geopolitical` stay as `measurement_type='definitional'` human-prior
  tags with an owner annotation (per TAG-03's rule) — **kept, not deleted**, despite `fed_policy`'s
  measurable content being largely spanned by `rate_beta`+`curve_beta`. Consistent with D-08's
  "cheap-to-keep" principle: a definitional tag with real conceptual meaning costs nothing to
  retain (no schema, no service), so redundant-but-meaningful is not the same bar as broken.
- **D-07:** `housing_cycle` is **deleted** — not a population-size call (it has exactly one
  holder, XHB) but a tautology call: `housing_cycle`'s own factor series IS XHB, so the
  "measurement" is a self-regression, mathematically meaningless regardless of holder count. This
  is a different, stronger reason than low population and should not be conflated with D-08.

### Cheap-to-keep vs. broken-concept — the distinction this phase must not blur
- **D-08:** `volatility` (sensitivity category, currently **zero** holders) is **kept, not
  deleted**, despite having no live assignments today. A tag *definition* is a row in
  `tag_vocabulary` — keeping it costs nothing (no schema, no service, no migration). The "don't
  build infrastructure for unproven ideas" principle governs new *machinery* (tables, services),
  not cheap taxonomy labels. `volatility` becomes the natural home once `vol_beta` measures via
  the D-02 SPY-realized-vol proxy. Contrast directly with D-07 (`housing_cycle`): that deletion is
  about a broken/circular measurement, not about low population — the two must not be conflated
  when this phase's plan or future phases cite this precedent.

### spread_leg: salvageable via data migration + test, not a new table
- **D-09:** Fix `signal_role`'s `spread_leg` tag (28/410 `instrument_tags` rows, 17 with NULL
  evidence) with one Wave 0 migration + a boundary-style unit test, **not** a new pairs table.
  Zero code consumers exist today (`grep -r spread_leg` across `src/`/`services/`/`scripts/`/
  `tests/` returns nothing but the seeding migrations) — building schema/writers/query surface for
  a 28-row, zero-consumer population would be exactly the "infrastructure for a population of one"
  anti-pattern this project avoids elsewhere. Concrete fix: backfill NULL evidence as
  `{"pair": "<SYM>", "reason": "..."}` — 4 pairs are mechanically recoverable from mirror mentions
  in other rows' evidence (LQD←CWB, TLT←EDV, SPY←IPO/EZU, SCHD←VYM); add the 3 missing reciprocal
  rows (UUP, USMV, FXI). The remaining 13 non-mechanical pairs need a human pass by whoever
  originally seeded migration 227 — **deferred to Wave 0 execution time**, not resolved in this
  discussion (see Deferred Ideas). Unrecoverable rows get deleted, not guessed. Add a unit test
  (house boundary-test pattern, precedent: `tests/unit/test_market_data_ohlcv_boundary.py`)
  asserting every `spread_leg` row's `evidence->>'pair'` resolves to a valid `instruments.symbol`
  and that pair references are symmetric.

### Schema bug fix (must land before Wave 1's expiry logic can work)
- **D-10:** `instrument_tags` has no `valid_from`/`valid_to` columns today (verified live) — the
  design doc's revised calibration loop writes `valid_to = now()` on expiry, which would fail
  loudly against the live schema as written. Add these columns in the Wave 0/1 migration (T6).

### Data-boundary compliance
- **D-11:** Daily-return reads for factor-series construction go through
  `market_data_ohlcv_tradeable`, not raw `market_data_ohlcv` (this project's tradeable-boundary
  rule, which postdates the design doc). Real daily bars all have `volume > 0`, so this is safe
  without a boundary-test allow-list entry.

### Engine-general, seed-specific — what "multiple stratifications of exposure" does and does not license
- **D-12:** The phase's mission is a general calibration engine (D-domain-boundary above), which
  means the *mechanism* must not hard-code assumptions specific to the ~10 initial primitives —
  `TagCalibrator`/`factor_math.py` should take `(symbol, factor_series, measurement_type)` from
  `tag_vocabulary` generically, the same loop regardless of what the tag represents. It does
  **not** mean this phase should proactively seed additional stratifications (tech, GICS sectors,
  factor styles) beyond what's already live today. Applied directly to the tech/semi question this
  discussion raised: `semi_cycle` (SMH) stays in scope because it already exists as a real,
  assigned tag; a broader `tech_beta` (viable data-wise via `XLK`-`SPY` long-short, same recipe as
  `oil_beta`) is deliberately **not** added — no live tag, no consumer, no trigger, and adding it
  would be the first of what should logically become one per GICS sector if applied consistently,
  which is exactly the scope Classification Hierarchy (deferred, gated on the individual-equities
  milestone) exists to eventually own. The engine supports it cheaply whenever a real need shows
  up; this phase does not need to anticipate that need.

### Claude's Discretion
- Exact migration numbers, `TagCalibrator`/`factor_math.py` method signatures, APR key names
  (`alpha.tag_auditor.*`) — follow the design doc's already-revised schema/loop
  (§"Revised schema", §"Revised calibration loop") plus this session's Wave 0 additions.
- `factor_math.py` reuses `src/intelligence/statistics/ic_math.py`'s measurement kernel
  (`_fisher_z_ci`, `_p_values_from_ic`, the HAC pattern from `_hac_sharpe_nd`) per the design doc's
  own F4 finding — new math (OLS loading with Newey-West HAC standard errors, lagged
  cross-correlation, mutual information vs. a discrete state series) goes in the new module, not a
  second reimplementation of existing kernel functions.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design doc (primary source — read first)
- `docs/research/stratification-instrument-tag-calibrator.md` — the full design: Simons critique,
  schema, calibration loop, 2026-07-06 Fable review (F1-F9, all resolved — reuse the measurement
  kernel, HAC standard errors, OOS confirmation gating, degenerate-regression guards, revised
  schema/loop). Treat as authoritative for HOW; this CONTEXT.md + the 2026-07-16 review below add
  the Wave 0 scope and factor-series resolutions.

### 2026-07-16 taxonomy/factor-data review (this session's primary new input)
- `docs/research/fable-2026-07-16-tag-calibrator-taxonomy-review.md` — findings T1-T7: the
  3-missing-factor-series blocker (T1), credit merge (T2), gold resolution (T3), the 8-tag
  partition table (T4), spread_leg fix (T5), the `valid_from`/`valid_to` schema bug (T6), and the
  category-overlap doc fix (T7). Full punch list (Wave-scope answer, doc edits, schema/data
  changes, operator decisions) at that doc's §4.

### Roadmap and prioritization context
- `.planning/ROADMAP.md` — "Phase 146: Empirical Instrument Tag Calibrator" section
  (TAG-01/02/03, 3 plans); the review's punch list item 2 rewrites TAG-01's beta list as the Phase
  1 primitive set (equity/rate/curve/credit/gold/dollar/china/inflation/oil, plus free-rider
  em_flows/semi_cycle/yen_carry; vol via the SPY-proxy and oil via the XLE-SPY long-short, both
  per D-02 — revised during this discussion, oil is no longer deferred).
- `docs/foundation/glossary.md` (lines 342-403) — six category definitions (`exposure`,
  `sensitivity`, `factor_regime`, `cycle_position`, `signal_role`, `macro_driver`); needs the T7
  doc fix (narrative-intent-only note, one-factor-series-one-tag collision rule).

### Code precedents cited in decisions
- `src/intelligence/regime_signals/breadth_vol.py` (lines 3, 44-46) — the live SPY-realized-vol
  VIX-proxy precedent D-02's `vol_beta` resolution reuses directly.
- `src/intelligence/statistics/ic_math.py` — the measurement kernel `factor_math.py` reuses
  (Claude's Discretion, D-11 note).
- `tests/unit/test_market_data_ohlcv_boundary.py` — the house boundary-test pattern D-09's
  `spread_leg` unit test follows.
- `production/migrations/227_instrument_tag_vocabulary.sql`, `188_etf_expansion.sql`,
  `190_etf_expansion_cwb.sql` — seed provenance for the `spread_leg` rows needing backfill.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/intelligence/statistics/ic_math.py` — `_fisher_z_ci`, `_p_values_from_ic`, HAC pattern
  from `_hac_sharpe_nd` — directly reusable for the calibrator's CI/p-value/HAC needs (F4).
- `src/intelligence/regime_signals/breadth_vol.py` — the SPY-realized-vol z-score computation
  D-02 reuses as `vol_beta`'s factor input instead of ingesting VIX.
- `tests/unit/test_market_data_ohlcv_boundary.py` — boundary-test pattern for D-09's new
  `spread_leg` pair-validity test.

### Established Patterns
- Full-matrix OLS loop (F8's "Simons inversion" — measure everything, derive tags from results,
  don't hand-pick which instruments get tested) is what makes D-05's 5 "free" tags nearly costless
  and is the shape Wave 1 should build to.
- Long-short factor construction (HYG-IEF for credit, TIP-IEF for inflation, IEF-SHY for curve) is
  one shared constructor needed by three separate tags — build once in `factor_math.py`.

### Integration Points
- `tag_vocabulary.category` — the calibrator never reads this column for measurement logic (T7);
  the measurement contract lives per-tag via `factor_series`/`measurement_type` columns.
- `instrument_tags` (symbol, tag, weight, source, evidence, assigned_at) — gains `valid_from`/
  `valid_to` in the Wave 0/1 migration (D-10); `evidence` JSONB gains a structured `{"pair": ...}`
  shape for `spread_leg` rows (D-09).

</code_context>

<specifics>
## Specific Ideas

User's steering input was architectural, matching the Phase 161 discussion's register: "the
concept is more important than the specifics" — the registered thing is a factor-loading concept
(dollar strength, credit spread risk, volatility-regime sensitivity, energy/oil sensitivity), and
the specific proxy ticker is an implementation detail that should adapt to what the current
80-symbol universe actually has live data for. This resolved `vol_beta`'s data-source question
more cheaply than the initial review recommendation (reuse the existing SPY-realized-vol proxy
rather than ingest VIX) and un-deferred `oil_beta` entirely (a cointegration-against-a-benchmark
framing — "anything highly cointegrated with OIH/XLE has energy beta" — showed the same
long-short-purification technique already used for credit/inflation applies here too, rather than
requiring a "pure" single-commodity series that doesn't exist in this system). It also sharpened
the review's population-based deletions into two distinct tests: cheap-to-keep (vocabulary rows
cost nothing, keep them even at zero/low current usage — `volatility`, `fed_policy`,
`geopolitical`) vs. broken-concept (delete regardless of population — `housing_cycle`'s
self-regression tautology).

</specifics>

<deferred>
## Deferred Ideas

- **spread_leg's 13 non-mechanically-recoverable pairs** — needs a human pass by whoever seeded
  migration 227 (or the project owner's own recollection) at Wave 0 execution time; not resolved
  in this discussion. Unrecoverable rows get deleted rather than guessed at.
- **Phase 2 regime-conditioning** (Wave 3) — unchanged in scope by this discussion; still gated on
  Phase 1 shipping first.
- **`docs/research/stratification-instrument-tag-calibrator.md`'s open-question section (lines
  694-728)** — closes against the 2026-07-16 review per its own §2 T7 closing note; no further
  discussion needed on the taxonomy-soundness question that originally motivated this session.

### Reviewed Todos (not folded)
- **`gsd-sdk`'s `todo.match-phase 146` query** returned 45 matches, the same generic 0.6
  keyword-overlap noise already flagged in the 160 and 161 discussions. Reviewed and judged
  noise — todo 041 (the taxonomy-soundness question) was already folded into the canonical design
  doc directly (not a separate file), and 110/111 (Controlled Vocabulary/Stratification) are this
  phase's siblings, not fold candidates.

</deferred>

---

*Phase: 146-Empirical Instrument Tag Calibrator*
*Context gathered: 2026-07-16*
