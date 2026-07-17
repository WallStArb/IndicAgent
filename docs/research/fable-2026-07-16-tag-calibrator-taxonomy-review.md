# Tag Calibrator Taxonomy Review - The Vocabulary Is Fixable in a Week; the Factor Data Layer Is the Real Blocker

**Date:** 2026-07-16 · **Author:** Fable 5 (dispatched via Claude Code Agent tool) · **Type:** research/review, read-only
**Scope:** resolves the last open question in `docs/research/stratification-instrument-tag-calibrator.md` (line 694, "is the live 6-category `tag_vocabulary` taxonomy itself sound?", folded in from todo 041) against live DB state, `docs/foundation/glossary.md` category definitions (lines 342-403), and `.planning/ROADMAP.md` Phase 146 (lines 1400-1427). Every claim verified live 2026-07-16 via psql unless cited otherwise. Explicitly does NOT re-litigate the 2026-07-06 review's F1-F9; findings here are numbered T1-T7 to keep the namespaces separate.
**Verdict up front:** the taxonomy problems are real but small and all resolvable with one data migration plus doc edits; the only true intra-vocabulary duplicate is the credit pair, gold needs no tag at all, and `spread_leg` is salvageable with an evidence backfill and a boundary-style test rather than a new table. The finding this review adds that no prior session caught: **three of TAG-01's eight specified factor series (VIX, USO, DXY) have zero usable daily bars in this system today** - the phase as roadmapped would fail, or worse silently skip, 3 of 8 columns of the factor vector it exists to compute. That, not the taxonomy, is what forces a Wave 0.

---

## 1. Live state verified (baseline for everything below)

- `tag_vocabulary`: 71 tags across 6 categories (exposure 37, macro_driver 10, signal_role 9, factor_regime 6, sensitivity 5, cycle_position 4). Matches the prior session's numbers exactly.
- `instrument_tags`: 410 rows; 28 `spread_leg` (~7%), of which 17 have NULL evidence. Matches.
- Two vocabulary tags have **zero** assignments: `volatility` (sensitivity) and `fx_em` (exposure).
- `instrument_tags` live columns: `symbol, tag, weight, source, evidence, assigned_at` only. **No `valid_from`/`valid_to`** - those exist only on `instrument_annotations` (migration `production/migrations/227_instrument_tag_vocabulary.sql` lines 37-38). See T6.
- Factor-series daily-bar coverage (`market_data_ohlcv`, `timeframe='1d'`): SPY 7,315 · TLT 3,808 · GLD 7,313 · HYG 7,024 · UUP 7,075 · FXI 7,299 · KWEB 4,724 · EEM 7,311 · TIP 7,316 · IEF 3,261 (2017-08→present) · SHY 3,261 · FXY 7,081 · SMH 5,313 · XHB 7,312 · KRE 7,313. **VIX: 0 rows** (raw and tradeable view). **CL: 0 rows** (instrument exists, futures, `is_active=false`). **USO and DXY: not in `instruments` at all.**

---

## 2. Findings

### T1 - Three of TAG-01's eight factor series are not computable from live data. [HIGH]

ROADMAP TAG-01 (line 1410) specifies `vol_beta (VIX)`, `oil_beta (USO)`, `dollar_beta (DXY)`. Verified live: VIX exists as an inactive futures instrument with zero daily bars in `market_data_ohlcv`; USO is not an instrument; DXY is not an instrument; CL (the design doc's oil series, line 50) exists inactive with zero bars. The live systematic regime model already routes around exactly this gap: `src/intelligence/regime_signals/breadth_vol.py` (lines 3, 44-46) substitutes an "SPY realized-vol z-score" as its "realized-vol VIX proxy" because no VIX series is ingested.

This is not a taxonomy question; it is a silent-wrong-answer risk baked into the phase spec. The doc's derived-tag definitions depend on these betas (`risk_off` needs `gold_beta`, `defensive` needs `vol_beta`, doc lines 100-103). A Phase 1 that quietly skips unavailable factors ships a factor vector with holes that downstream threshold derivations read as "no loading," which is a wrong answer, not a missing one.

**Fix:**
- `dollar_beta`: substitute **UUP** (active, 7,075 daily bars). Trivial; the doc's own mapping already avoided DXY by choosing EURUSD-inverse (line 204), and UUP is the more direct live proxy. `dollar_strength` is the single most-assigned macro_driver tag (16 rows), so this factor must not slip.
- `vol_beta`: **resolved 2026-07-16 (project owner, post-review discussion) — reuse the existing SPY-realized-vol z-score already computed live in `breadth_vol.py` (lines 3, 44-46) as the factor input.** Not this review's original recommendation (ingest VIX dailies) — the concept-over-specific-proxy principle applied further: the platform already computes the same conceptual signal (volatility-regime sensitivity) live, so reusing it costs zero new ingestion. VIX ingestion remains a reasonable future enhancement if implied (not realized) vol is ever specifically needed, but is not required for Phase 1.
- `oil_beta`: **resolved 2026-07-16 (project owner, post-review discussion) — measurable in Phase 1 via XLE-SPY long-short, not deferred.** This review's original "no in-universe non-circular factor" framing was too narrow: it looked for a *pure* commodity series (CL/USO, neither has usable data) rather than applying the same long-short-purification technique this review already uses for `credit_beta` (HYG-IEF) and `inflation` (TIP-IEF). Verified live: XLE (5,034 bars), OIH (3,651), XOP (5,033), AMLP (3,986), SPY (5,033) via `market_data_ohlcv_tradeable` all have solid history. XLE-SPY long-short purifies out general equity-market beta; F6.1's existing degenerate-regression guard already handles XLE-tested-against-itself, and does not block OIH/XOP/AMLP or any other instrument from legitimate testing against this factor.

### T2 - credit_cycle / credit_risk / credit_beta: genuinely redundant, and the univariate HYG regression makes any credit tag meaningless for equities without a spread-purified factor. [HIGH]

Verified live: **HYG and LQD each carry BOTH tags at near-identical weights** (HYG: credit_cycle 0.9, credit_risk 1.0; LQD: 0.8 and 0.8) - the redundancy is already expressed in the data, not just the vocabulary. The glossary's claimed distinction ("Macro driver identifies the causal force; sensitivity measures the magnitude of response," glossary.md lines 399-401) is not operationalizable: no OLS distinguishes a causal force from a response magnitude; both reduce to a loading against a credit proxy. The design doc's attempt to manufacture a distinction by mapping `credit_cycle` to KRE correlation (doc line 217) fails on its own terms: KRE is an equity instrument that itself carries `credit_risk`, `yield_curve`, and `stress_indicator` tags; regressing XLF/XLY/XRT/IWM on KRE measures shared equity beta, not the credit cycle.

The deeper defect: raw HYG returns carry substantial equity beta, so a univariate `credit_beta` vs HYG will "empirically confirm" credit sensitivity for essentially the whole equity book - roughly the same failure class as F6.1's self-regression tautology, one step removed. A falsification engine that confirms everything falsifies nothing.

**Resolution (concrete):**
1. **Merge:** migrate the 8 `credit_cycle` assignments into `credit_risk` rows (HYG/LQD collide; keep the max weight), retire `credit_cycle` from `tag_vocabulary`, and record it in the glossary as a banned alias of `credit_risk`. The prior session's tentative read is confirmed on this point.
2. **Purify the factor:** define `credit_beta`'s factor series as the rate-hedged spread component - the **HYG minus duration-matched Treasury long-short return** (HYG-IEF is the practical in-universe construction) - so the loading measures spread risk rather than equity-plus-duration shadow. The long-short constructor is required anyway for `yield_curve` and `inflation` (T4), so this costs one shared helper in `factor_math.py`, not new machinery.

The intent difference the two tags encoded (bonds that ARE credit vs equities DRIVEN BY credit) is not lost: it re-emerges empirically as loading magnitude on the purified factor, which is exactly where a measurement system should express it.

### T3 - gold_beta: keep it in Phase 1; do not seed a tag, and do not drop the beta. [MEDIUM]

GLD is live with 7,313 daily bars - the cheapest, cleanest series in the set. Both horns of the prior session's proposal ("seed a gold sensitivity tag now, or drop gold_beta from Phase 1") are wrong, and for the same reason: under F8's Simons inversion the factor vector is the source of truth and tags are derived read-outs. `gold_beta` is a required input to two derived-tag definitions (`risk_off`, doc line 100; `inflation`, line 107) and to the crisis-hedge fingerprint the doc calls "the signal" (line 67). Dropping it breaks those derivations; seeding a human tag would insert a belief precisely where this phase exists to replace beliefs. If instruments genuinely load on gold, F8's full-matrix pass discovers the rows and F5's OOS gate confirms them - that is the designed path. The human query handle for gold instruments already exists and is correctly definitional: `commodity_metals_precious` (exposure, 4 rows: GLD, SLV, GDX, PPLT).

### T4 - The eight unmapped tags partition cleanly by one rule: measurable iff the factor series is constructible from live daily bars. [MEDIUM]

Applying that rule, with live holder lists verified:

| Tag | Holders (live) | Verdict | Factor series / reason |
|-----|---------------|---------|------------------------|
| `yield_curve` | EDV, IEF, KRE, PFF, XLF | **Measurable, Phase 1** | IEF-SHY daily long-short return (both live, 3,261 bars ≈ 13y ≥ 252-day lookback). The prompt's premise that this is "a different regression methodology entirely" is wrong: the regressor is a constructed spread series; the OLS is unchanged. The doc already lists `curve_beta` as a primitive (line 52) and maps yield_curve → IEF/SHY (line 211). It is the 9th core beta, and TAG-01's "8" should defer to the doc's primitive table (the 2026-07-06 review's own count-drift note, lines 33-36, already says to read "8" as "the primitive set"). |
| `inflation` | DBA, DBC, GLD, PPLT, SLV, TIP | **Measurable, Phase 1, corrected factor** | The doc holds two contradictory definitions: TIP beta (mapping table, line 203) vs `gold_beta > 0.3 AND rate_beta < 0` (derivation table, line 107). Raw TIP beta is duration-dominated and would largely re-measure `rate_beta`. Use the TIP-IEF long-short (breakeven proxy) - same constructor as curve - and delete the line-107 derivation. |
| `em_flows` | EEM, EMB, EWY, EWZ, FXI, INDA, VWO | **Measurable, Phase 1, honest description** | vs EEM (7,311 bars; F6.1 skips EEM itself). What OLS measures is EM co-movement, not "institutional capital flows" - fix the description or accept the tag means EM beta. Note VWO-vs-EEM is a same-index pseudo-tautology F6.1's `symbol != factor_series` check will not catch (loading real but uninformative); add to the doc's F6 inventory. Same pattern: MCHI vs FXI. |
| `china_demand` | 12 holders incl. FXI, KWEB, MCHI | **Measurable, Phase 1** (already in TAG-01) | ROADMAP says FXI, doc says KWEB (line 215). FXI: 7,299 bars vs KWEB 4,724. Pick FXI, record the decision. |
| `semi_cycle` | EWT, EWY, SMH | **Measurable, free under F8** | vs SMH (5,313 bars); F6.1 skips SMH, leaving EWT/EWY as real hypotheses. Costs nothing once the full-matrix loop exists. |
| `yen_carry` | EWJ, FXY | **Measurable, free under F8** | vs FXY (7,081 bars); F6.1 skips FXY. Yen-carry loading on risk assets is a real, known relationship; the full matrix measures all 80 symbols anyway. |
| `fed_policy` | BIL, EDV, IEF, SHY, TIP, TLT, VNQ, XLU | **Definitional; deletion candidate** | The doc maps it to SHY beta (line 216), but SHY daily returns run a few bps of vol - regression on a near-constant series is the F6 degenerate class - and the holder list is dominated by the proxy family itself (SHY, IEF, TLT: tautologies). Its measurable content is spanned by `rate_beta` + `curve_beta`. Annotate `measurement_type='definitional'` with owner per TAG-03; delete if no consumer ever distinguishes it from rate+curve. |
| `geopolitical` | CIBR, GLD, IBIT, ITA | **Definitional with owner** | No factor series exists or is constructible from the universe. A legitimate human prior and query handle; TAG-03's rule covers it exactly. |
| `housing_cycle` | XHB (only) | **Delete** | Population of one, and the sole holder IS the doc's own factor proxy (line 214 maps housing_cycle → XHB): the row is the exact F6.1 self-regression tautology, pre-committed in the seed data. `eq_sub_sector` already encodes what XHB is. Zero information content; 5-step delete of both the assignment and the vocabulary row. |
| `volatility` | **zero holders** | **Kept — cheap to keep, not dead vocabulary** | Resolved 2026-07-16 (project owner): a tag *definition* with zero current holders costs nothing to retain (no schema, no service) — the "don't build infrastructure for unproven ideas" rule governs new machinery, not cheap taxonomy rows. `volatility` becomes the natural home once `vol_beta` measures via the `breadth_vol.py` SPY-realized-vol proxy (see T1 resolution above). (`fx_em`, the other zero-holder tag, is definitional exposure and harmless.) |

Net effect: of the "no home in the 8-beta plan" list, five (`yield_curve`, `inflation`, `em_flows`, `semi_cycle`, `yen_carry`) belong IN Phase 1 - four of them essentially free under F8's full-matrix loop, which this review leaned on repeatedly and which is the right Phase 1 shape - and three (`fed_policy`, `geopolitical`, `housing_cycle`) resolve to definitional / definitional / delete. The prior session's blanket "out of TAG-01 Phase 1 scope" was too conservative: it priced each tag as its own machinery, but under F8 the marginal cost of a measurable tag is one `factor_series` value in a vocabulary row.

### T5 - spread_leg: salvageable as definitional; the fix is one data migration plus a boundary-style test, not a new table. [MEDIUM]

Facts verified live: 28/410 rows carry `spread_leg`; 17 have NULL evidence - all 17 trace to migration 227's original seed, which inserted `(symbol, tag, weight, source)` only (e.g. lines 158, 175-179); the 11 documented rows came with the ETF-expansion migrations 188/190. **Zero code consumers**: `grep -r spread_leg` across `src/`, `services/`, `scripts/`, `tests/` returns nothing; only the three migrations mention it. And the brokenness is worse than "17 missing pairs" - it is asymmetric in both directions: partners named in evidence are sometimes untagged entirely (UUP named by FXE's row, USMV by SPHB's, FXI by MCHI's - none carry `spread_leg`), and sometimes tagged but evidence-NULL (LQD named by CWB, TLT by EDV, SPY by IPO and EZU, SCHD by VYM).

The open question's structural critique is correct in principle: pair membership is a relation, and a unary tag cannot carry it alone. But the project's own build-trigger test settles the remedy. A `spread_pairs` table is schema, writers, and query surface for a 28-row population with **zero consumers** - exactly the "infrastructure for a population of one" the project refuses elsewhere. Conversely, deleting the tag violates the retention principle for no savings: the 11 evidence strings are genuine pair hypotheses (CWB/LQD convertible-vs-straight-credit, SPHB/USMV factor spread, etc.) that a future spread predictor would want as seeds.

**The fix that fits the population size:**
1. **One data migration** backfilling the 17 NULL rows with structured evidence `{"pair": "<SYM>", "reason": "..."}`. At least four pairs are mechanically recoverable from the mirror mentions above (LQD←CWB, TLT←EDV, SPY←IPO/EZU, SCHD←VYM); the rest (AGG, EWY, HYG, IEF, KRE, OIH, RSP, SLV, TIP, VNQ, VTV, VUG, XOP) need a short human pass by whoever seeded 227 - most are guessable (VTV/VUG value-growth, IEF/SHY curve, TIP/IEF breakeven, GLD/SLV metals ratio) but guesses must not be written as facts; unrecoverable rows get the tag row deleted rather than a fabricated pair. Add the three missing reciprocal rows (UUP, USMV, FXI).
2. **A unit test in the house boundary-test style** (`tests/unit/test_market_data_ohlcv_boundary.py` is the precedent): assert every `spread_leg` row's `evidence->>'pair'` resolves to a valid `instruments.symbol` and that pair references are symmetric. A test, not a DB CHECK - a cross-table JSONB constraint is not expressible as a CHECK, a trigger is overkill for a human-edited 28-row set, and the test also catches the reciprocity failures a row-level constraint never could.
3. The tag stays `measurement_type='definitional'` (the doc's mapping already says so, line 222). Promote to a real pairs table only when a spread-monitoring consumer exists - at which point the structured evidence migrates mechanically.

### T6 - Schema drift the design doc does not know about: `instrument_tags` has no `valid_from`/`valid_to`. [MEDIUM]

The doc's "What Simons would keep" #3 (line 133) credits temporal validity to the live schema, and the revised calibration loop writes `valid_to = now()` on expiry (line 646) - but the live table has no such column (§1 above); temporal validity exists only on `instrument_annotations`. The revised-schema block (lines 599-621) does not add it either. As written, the loop's first expiry write fails loudly. Wave 2's migration must ADD `valid_from`/`valid_to` (or an `expired_at`) to `instrument_tags` alongside the F1-F3 columns. Related housekeeping in the same doc: "Architecture fit" (line 288) says the service reads `market_data_ohlcv` - under the tradeable-boundary rule that postdates the doc, daily-return reads should go through `market_data_ohlcv_tradeable` (safe: real daily bars all have volume > 0) or carry a boundary-test allow-list entry with a reason.

### T7 - macro_driver vs sensitivity as categories: keep both labels, but the measurement engine must be category-blind, and the glossary should say why. [LOW]

The glossary defines sensitivity as "empirically measured via beta regression" (line 355) and macro_driver as "empirically measured via beta against a canonical macro proxy" (line 399) - operationally the same sentence under two category names, distinguished only by an unmeasurable causal-force gloss. That overlap is how the credit duplicate happened. No schema change is needed: the measurement contract already lives per-tag (`factor_series`, `measurement_type` columns), so the calibrator never reads `category`. The T2 merge removes the only live duplicate. Doc fix only: glossary notes at both entries that the two categories differ in narrative intent, not measurement procedure, and that one factor series maps to exactly one tag across all categories (the collision rule that would have blocked `credit_cycle` at seeding time).

**On the open question's other numbered items** (doc lines 694-728): item 2 (`cycle_position` provisional-vs-active) is already resolved by the doc's own treatment (definitional human seed priors, line 148) plus TAG-03's annotation rule - Wave 2's `measurement_type='definitional'` annotation with owner closes it, no further action. Item 4 (sector granularity absent) re-verified as still true and correctly out of Phase 146 scope. Item 3 (macro_driver redundancy) resolves per T2/T7: real, but confined to the credit pair. Item 1 (`spread_leg`) resolves per T5. The open-question section can be closed against this review.

---

## 3. What's Solid (do not touch)

- **The 2026-07-06 F1-F9 review and its revised loop/schema.** Nothing here reopens any of it. In fact F8's full-matrix inversion did heavy lifting in this review: it is why gold needs no tag (T3) and why five "unmapped" tags cost nearly nothing to measure (T4).
- **The `exposure` category** (37 tags): cleanly definitional, correctly never validated, and it already provides the gold query handle (`commodity_metals_precious`) that made T3's answer easy. The doc's line-723 verdict that exposure "doesn't need re-litigating" is confirmed.
- **The clean 1:1 tag-beta matches**: `rate_sensitive`↔`rate_beta` (TLT), `china_demand`↔`china_beta` (FXI), `dollar_strength`↔`dollar_beta` (UUP after T1). The prior session's matches for oil and vol were structurally right and only fail on data availability.
- **The three-table layering** (`tag_vocabulary` / `instrument_tags` / `instrument_annotations`) and the `source` provenance CHECK - live schema verified, exactly as the doc describes.
- **`signal_role`'s measurable members** (`leading_indicator`, `regime_classifier`, `breadth`) and its definitional members (`benchmark`, `sentiment`, `stress_indicator`, `sector_rotation`, `factor_rotation`) per the doc's mapping table - only `spread_leg` needed work, and only its data, not its concept.

---

## 4. Punch List

### Wave-scope answer (task question 5)

The 3-wave plan survives with one addition and one ordering fix:

- **Add Wave 0 - taxonomy cleanup + factor-data readiness (1 plan, small).** (a) Credit merge migration (T2.1); (b) housing_cycle deletion (T4); (c) spread_leg evidence backfill + reciprocal rows + boundary test (T5); (d) the two operator data decisions (vol, oil - T1) resolved and recorded, with UUP and FXI substitutions locked; (e) glossary + design-doc edits below. Rationale: the doc's own closing warning (lines 725-726) - building the empirical machinery first bakes the confusion into a real system - plus T1's finding that Wave 1's OLS pipeline literally cannot be coded until the factor-series list is real.
- **Fix the Wave 1/2 ordering defect:** the roadmap has Wave 1 building the TagAuditor service and Wave 2 doing the DB migration - backwards; the service reads `tag_vocabulary.factor_series`/`measurement_type` and writes `instrument_tags.loading`/`passes_fdr`, none of which exist before the migration. The measurement-contract migration (revised schema block + T6's `valid_from`/`valid_to`) belongs at the start of Wave 1 or the end of Wave 0.
- Waves 1 (full-matrix `TagCalibrator` + `factor_math.py`, per F8/F4), 2 (expiry/hysteresis/OOS-pending mechanics), 3 (Phase 2 regime-conditioning design) otherwise unchanged.

### Doc edits

1. **`docs/research/stratification-instrument-tag-calibrator.md`**
   a. *Factor series mapping table (lines 199-226):* `dollar_strength` EURUSD → UUP; `china_demand` KWEB → FXI (record the history-depth rationale); `credit_risk` HYG → HYG-IEF long-short (T2.2); delete the `credit_cycle` row (T2.1); `inflation` TIP → TIP-IEF long-short; `oil_price` → XLE-SPY long-short (resolved 2026-07-16, not deferred — see T1 resolution); `vol_beta` → `breadth_vol.py` SPY-realized-vol proxy (resolved 2026-07-16, not VIX ingestion); `fed_policy` → definitional (T4); delete `housing_cycle` row (T4); note `em_flows` measures co-movement, not flows.
   b. *Derivation table (line 107):* delete the `inflation = gold_beta > 0.3 AND rate_beta < 0` row - contradicts the mapping table; TIP-IEF is the measurement (T4).
   c. *Revised schema block (lines 599-621):* add `valid_from`/`valid_to` to the `instrument_tags` ALTER (T6).
   d. *Architecture fit (line 288):* `market_data_ohlcv` → `market_data_ohlcv_tradeable` (T6).
   e. *F6 inventory:* add the same-index pseudo-tautology note (VWO/EEM, MCHI/FXI) (T4).
   f. *Open question section (lines 694-728):* close against this review - item 1 → T5, item 2 → closed by TAG-03 annotation, item 3 → confirmed for credit only (T2/T7), item 4 → confirmed out of scope.
2. **`.planning/ROADMAP.md` Phase 146:** rewrite TAG-01's beta list as the Phase 1 primitive set: equity (SPY), rate (TLT), curve (IEF-SHY), credit (HYG-IEF), gold (GLD), dollar (UUP), china (FXI), inflation (TIP-IEF), vol (SPY-realized-vol proxy via `breadth_vol.py`), oil (XLE-SPY long-short), plus free-rider tags em_flows (EEM), semi_cycle (SMH), yen_carry (FXY) — all resolved 2026-07-16, none deferred. Plans line: 3 waves → Wave 0 + 3 waves with the migration moved ahead of the service build.
3. **`docs/foundation/glossary.md`:** `credit_cycle` → banned alias of `credit_risk`; add the narrative-intent-only note to `sensitivity` (line 353) and `macro_driver` (line 397) entries plus the one-factor-series-one-tag collision rule (T7).

### Schema / data changes (Wave 0 migration)

1. Merge `credit_cycle` → `credit_risk` (8 rows, max-weight on HYG/LQD collisions); delete `credit_cycle` from `tag_vocabulary`.
2. Delete `housing_cycle` assignment (XHB) and vocabulary row.
3. Backfill `spread_leg` evidence (`{"pair","reason"}`) for the recoverable rows; delete unrecoverable ones rather than fabricate; add reciprocal rows for UUP, USMV, FXI.
4. New unit test: `spread_leg` evidence contract + pair symmetry (house boundary-test pattern).
5. (Wave 1 migration, not Wave 0:) revised-schema columns + `valid_from`/`valid_to` on `instrument_tags`.

### Operator decisions

1. ~~**vol_beta data source (T1)**~~ — **resolved 2026-07-16:** reuse the `breadth_vol.py` SPY-realized-vol proxy. Not this review's original recommendation (ingest VIX); see T1 resolution.
2. ~~**oil_beta (T1)**~~ — **resolved 2026-07-16:** XLE-SPY long-short, not deferred. Not this review's original recommendation (defer); see T1 resolution.
3. **fed_policy (T4):** **resolved 2026-07-16 — kept** as definitional query handle with owner, per the same cheap-to-keep principle as `volatility` above (a definitional tag with real conceptual meaning costs nothing to retain, even where its measurable content overlaps rate+curve).
4. **spread_leg backfill authorship (T5):** still open — the 13 non-mechanical pairs need the original seeder's intent; unrecoverable rows get deleted, not guessed. Deferred to Wave 0 execution time (see `146-CONTEXT.md`'s Deferred Ideas).

## References

- `docs/research/stratification-instrument-tag-calibrator.md` - subject doc (primitives table lines 40-52; derivations 96-112; mapping table 199-226; architecture fit 285-293; revised schema 599-621; revised loop 623-652; open question 694-728)
- `.planning/ROADMAP.md` lines 1400-1427 (Phase 146: TAG-01/02/03, plans line)
- `docs/foundation/glossary.md` lines 342-403 (six category definitions)
- `production/migrations/227_instrument_tag_vocabulary.sql` (seed provenance: annotations-only `valid_to` at 37-38; evidence-less `spread_leg` seeds at 158+), `188_etf_expansion.sql` / `190_etf_expansion_cwb.sql` (the 11 documented spread_leg rows)
- `src/intelligence/regime_signals/breadth_vol.py` lines 3, 44-46 (live SPY realized-vol VIX proxy precedent)
- `src/intelligence/statistics/ic_math.py` (existence re-verified; F4's reuse target unchanged)
- Live psql evidence (all 2026-07-16): tag/category counts; `instrument_tags` totals (410/28/17); dual credit tags on HYG/LQD; per-tag holder lists; factor-series daily-bar counts incl. VIX=0, CL=0, USO/DXY absent; `volatility`/`fx_em` zero-assignment check; `\d instrument_tags` / `\d tag_vocabulary` / `\d instrument_annotations`; `grep -r spread_leg` consumer sweep (zero hits outside migrations)
- `docs/research/fable-2026-07-04-concept-registry-cluster-review.md` (format precedent)
