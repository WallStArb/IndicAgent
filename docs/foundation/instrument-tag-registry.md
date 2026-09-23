# Instrument Tag Registry (ITR)

**Canonical name:** Instrument Tag Registry (ITR)
**Informal aliases:** tag system, tag vocabulary (colloquial — acceptable in casual conversation, not in architecture docs or code comments)
**Status:** current — TagCalibrator (empirical measurement engine) live since 2026-07-17
**Last Updated:** 2026-09-23 -- Phase 175 shipped (migration 346): `TagCalibrator` is now a 4-pass engine with a materiality filter (Pass 4), `instrument_tags` carries eleven new evidence columns, the `instrument_tags_active` read-contract view exists, and todos 125/126 (both Known Gaps below) are closed. Still shadow-mode only (D-03) -- see the Pass 4 and Read contract sections.
**Phase introduced:** 120 (schema + human seed), extended Phase 146 (empirical calibration)

---

## What It Is

The **Instrument Tag Registry (ITR)** is the system-wide home for every claim about what an instrument *is* or *how it behaves* — asset class, sector, factor exposure, sensitivity to a macro driver, structural role in a spread. Every downstream consumer that needs to resolve "which symbols belong to this peer group" (regime breadth universes, cross-sectional regime groups, IC stratification) reads from here rather than hardcoding a symbol list.

"Tag" is a specific, narrower claim than a generic descriptive attribute. Per the glossary (`docs/foundation/glossary.md` §tag): **a tag is a falsifiable hypothesis, not a category.** It asserts a measurable relationship exists between an instrument and a factor or role. Tags with `measurement_type != 'definitional'` are empirically validated by `TagCalibrator` and expire if the relationship stops clearing significance.

This is the direct structural analog of the [Adaptive Parameter Registry](adaptive-parameter-registry.md) — same shape of problem, same fix. APR asked "why is this threshold a hardcoded guess when we can measure and validate it?" ITR asks the identical question about instrument classification: why is "TLT is rate-sensitive" a permanent human assertion when it's an OLS beta anyone can measure and re-check? Both systems replace an opinion with a falsifiable, evidence-tracked claim that machinery can promote, contradict, or expire.

The ITR tag lifecycle is:

```
human seed → empirical measurement (TagCalibrator) → keep / contradict / expire, on a recurring cadence
```

Every empirical write carries its own evidence (`loading`, `p_value`, `bh_adjusted_p`, `sample_n`) inline on the row — there is no separate audit-log table (contrast with APR's `config_history`); the row itself is the current state, and the human-vs-empirical `source` column is the provenance record.

### Relationship to APR

ITR and APR are siblings under the same [Concept Governance Registries](../research/concept-governance-registries.md) umbrella, but govern different kinds of knowledge:

- **APR** — governs *numeric parameters* (thresholds, weights, periods) that control algorithm behavior.
- **ITR** — governs *instrument classification claims* (this symbol has this exposure/sensitivity/role) that control which symbols participate in a computation.

`TagCalibrator` itself is an APR **consumer**, not a competing store — its own tuning constants (FDR alpha, hysteresis counts, sample-size floors) live under the `alpha.tag_calibrator.*` APR namespace (see below), governed by the exact same ConfigService machinery APR docs describe. ITR does not duplicate APR; it uses it.

---

## Infrastructure

Three tables (Phase 120), no dedicated audit-log table, no dashboard yet (see Gaps below).
<!-- src: production/migrations/220_instrument_tag_vocabulary.sql, 221_instrument_tag_vocabulary_v2.sql, 230_tag_calibrator_measurement_contract.sql -->

### Table Schemas

**`tag_vocabulary`** — the controlled taxonomy; one row per tag concept.

| Column | Type | Description |
|--------|------|--------------|
| `tag` | TEXT PRIMARY KEY | Tag name, e.g. `rate_sensitive` |
| `category` | TEXT NOT NULL | One of 6: `exposure`, `sensitivity`, `factor_regime`, `cycle_position`, `signal_role`, `macro_driver` (display/organizational grouping only — never read for measurement logic) |
| `description` | TEXT NOT NULL | Plain-language definition; owner-annotated tags append `[Owner: project_owner]` |
| `factor_series` | TEXT | The proxy symbol (or `LEG1-LEG2` long-short spread, or the `SPY_REALIZED_VOL` sentinel) a `beta_regression` tag is measured against. `NULL` for definitional tags. |
| `measurement_type` | TEXT NOT NULL, CHECK | `'beta_regression'` (implemented), `'correlation'` / `'cross_correlation'` / `'mutual_information'` (schema-allowed, not yet implemented), or `'definitional'` (never measured — seed prior, e.g. `fed_policy`, `geopolitical`) |
| `lookback_days` | INT NOT NULL DEFAULT 252 | OLS regression window |
| `loading_threshold` | FLOAT | Minimum `abs(loading)` to keep the tag on a "pass" measurement |
| `half_life_days` | INT NOT NULL DEFAULT 180 | Decay half-life for the measured relationship (clamped to `alpha.tag_calibrator.half_life_{min,max}_days`) |

**`instrument_tags`** — the assignment table; one row per `(symbol, tag)` pair.

| Column | Type | Description |
|--------|------|--------------|
| `symbol` | TEXT NOT NULL, FK → `instruments(symbol)` | |
| `tag` | TEXT NOT NULL, FK → `tag_vocabulary(tag)` | |
| PK | `(symbol, tag)` | |
| `weight` | FLOAT NOT NULL, CHECK `[0,1]` | Strength of the association; for empirical rows, `weight = abs(loading)` |
| `source` | TEXT NOT NULL, CHECK | `'human'` (seed prior, never auto-expired/overwritten), `'empirical'` (TagCalibrator-written), `'ai'` (reserved, not currently written) |
| `evidence` | JSONB | For empirical rows: `first_measured_at`, `discovery_state` (`pending_oos`/`confirmed` — see Known Gap below), `half_life_days` |
| `loading` | FLOAT | Signed OLS standardized loading (empirical only) |
| `p_value` | FLOAT | Raw HAC-adjusted p-value (Newey-West, Bartlett kernel) |
| `bh_adjusted_p` | FLOAT | Benjamini-Hochberg FDR-corrected p-value, applied once per run over the full measured matrix |
| `passes_fdr` | BOOLEAN | Whether `bh_adjusted_p` clears `alpha.tag_calibrator.fdr_alpha` |
| `consecutive_fails` | INT NOT NULL DEFAULT 0 | Hysteresis counter — a tag expires only after `expiry_consecutive_fails` consecutive failing runs, not on the first miss |
| `sample_n` | INT | Paired-observation count used in the measurement |
| `estimated_at` | TIMESTAMPTZ | When this measurement was taken |
| `assigned_at` | TIMESTAMPTZ NOT NULL DEFAULT now() | |
| `valid_from` / `valid_to` | TIMESTAMPTZ | `valid_to IS NULL` = currently live; set once expiry hysteresis trips |
| `partial_loading` | FLOAT | Pass 4: OLS beta of the (symbol, tag) loading after orthogonalizing against the control factor set (`control_factor_series`) -- the materiality-filtered replacement for a raw, unconditioned `loading` |
| `partial_loading_ci_low` | FLOAT | Pass 4: lower confidence-interval bound around `partial_loading` (R-05's lower-CI gate) |
| `incremental_r2` | FLOAT | Pass 4: incremental R-squared this tag's factor_series contributes beyond the control set alone -- the explanatory-power component of the materiality gate |
| `sign_stable_windows` / `sign_stable_windows_total` | INT | Pass 4: how many of the evaluated disjoint tail-anchored rolling windows agreed in sign with the run-level sign (D-06 sign-stability component); see the sign-stability sliding bar below |
| `null_arm_p_value` / `null_arm_bh_p` | FLOAT | Pass 4: raw, then BH-FDR-adjusted, p-value from the D-06 circular-shift null-arm control for this pair |
| `materiality_sample_n` | INT | Pass 4's own post-control-alignment observation count -- distinct from Pass 1's `sample_n`, a different alignment; the two must never be conflated |
| `passes_materiality` | BOOLEAN | Pass 4: the STATISTICAL gate only (R-04). Readers MUST additionally AND this with `discovery_state = 'confirmed'` and `valid_to IS NULL` -- see `services.tag_calibrator.is_materiality_eligible()`, the canonical predicate, in the Read contract section below |
| `discovery_state` | TEXT, CHECK | todo 125: typed promotion of the discovery-state concept out of the `evidence` JSONB. `NULL` until measured; otherwise `'pending_oos'` or `'confirmed'` -- the temporal gate `passes_materiality` explicitly excludes |
| `first_measured_at` | TIMESTAMPTZ | todo 125: typed promotion of the first-measurement timestamp out of `evidence` -- the anchor `discovery_oos_days` counts forward from |

**`instrument_annotations`** — free-form narrative; carries human theses (`annotation_type='thesis'`) and TagCalibrator's own discovery/expiry/contradiction notes (`annotation_type='ai_insight'`, `source='ai'`, `model_id='tag-calibrator'`).

| Column | Type | Description |
|--------|------|--------------|
| `id` | UUID PRIMARY KEY | |
| `symbol` | TEXT NOT NULL, FK → `instruments(symbol)` | |
| `annotation_type` | TEXT NOT NULL, CHECK | `'thesis'`, `'signal_context'`, `'ai_insight'`, `'regime_note'` |
| `content` | TEXT NOT NULL | |
| `source` | TEXT NOT NULL, CHECK | `'human'` / `'ai'` |
| `model_id` | TEXT | e.g. `'tag-calibrator'` for machine-written rows |
| `valid_from` / `valid_to` | TIMESTAMPTZ | |

---

## Tag Category Taxonomy

Six categories, defined in `docs/foundation/glossary.md` §"Tag category taxonomy". `category` is display/organizational only — the measurement contract lives entirely in `factor_series` + `measurement_type`, never in `category`.

| Category | What it captures | Validated? | Examples |
|----------|-------------------|------------|----------|
| `exposure` | What an instrument fundamentally IS — asset class, market segment | Never (definitional) | `eq_broad`, `fi_treasury`, `crypto` |
| `sensitivity` | How price responds to a factor move | Empirical (beta regression) | `rate_sensitive`, `credit_risk`, `inflation`, `equity_beta` |
| `factor_regime` | Conditional performance in a named market factor state | Empirical (correlation/beta) | `risk_on`, `risk_off`, `defensive`, `growth`, `value`, `momentum` |
| `cycle_position` | Historical alpha relative to economic cycle phase | Never (static institutional prior) | `early_cycle`, `mid_cycle`, `late_cycle`, `recession` |
| `signal_role` | How the instrument functions in the signal-generation system | Mostly definitional | `benchmark`, `regime_classifier`, `leading_indicator`, `spread_leg` |
| `macro_driver` | Primary macroeconomic force driving returns | Empirical (beta vs. macro proxy) | `fed_policy`, `oil_price`, `china_demand`, `yen_carry` |

**Banned aliases:** `credit_cycle` was merged into `credit_risk` (Phase 146, migration 229, 2026-07-17) — both tagged the identical underlying `credit_risk` factor loading on the same holders (`HYG`, `LQD`) at near-identical weights. Do not reintroduce it. Full rule: two tags must never share the same `factor_series` value (redundant measurements of the same quantity under different names).

---

## How TagCalibrator Works

`services/tag_calibrator.py` — a `BaseBatch` oneshot (no systemd unit; run manually or via the ops batch runner, not on a timer), generic 4-pass measurement engine over the full instrument × measurable-tag matrix (F8 "Simons inversion" — measure everything, then decide, rather than deciding what to measure ahead of time). Pass 4 (Phase 175, D-01) adds a materiality filter on top of Pass 1-3's existing keep/expire/discover decision -- see the Pass 4 subsection below.

```
Pass 1 — Measure           every (symbol, tag) pair with measurement_type='beta_regression'
                            AND factor_series IS NOT NULL:
                              • build the factor_series return series (single symbol,
                                long-short spread on '-', or the SPY_REALIZED_VOL sentinel)
                              • OLS standardized loading + Newey-West HAC p-value
                              • skip self-regression pairs (symbol is a leg of its own factor_series)
                              • skip pairs below alpha.tag_calibrator.min_sample_n

Pass 2 — Correct once      exactly ONE Benjamini-Hochberg FDR correction over the FULL
                            run's p-vector (never per-hypothesis) → bh_adjusted_p, passes_fdr

Pass 3 — Decide            keep = passes_fdr AND abs(loading) >= loading_threshold
                              • no existing row + keep         → insert_discovery (pending_oos)
                              • existing empirical row + keep  → upsert_empirical (reset fail counter)
                              • existing empirical row + fail  → increment_fails, or expire once
                                                                  consecutive_fails >= expiry_consecutive_fails
                              • existing human row + keep      → confirm_human (no write)
                              • existing human row + fail      → annotate_contradiction (no write —
                                                                  human seeds are never auto-expired)

Pass 4 - Materiality      for every pair Pass 1-3 KEPT (D-01a, see below): orthogonalized
          filter            partial loading vs. a 4-leg control set, incremental R², a
                             sign-stability window count, and a circular-shift null arm.
                             Persisted unconditionally as evidence, never gates weight or
                             writes -- passes_materiality is read at query time, not enforced
                             here.
```

### Pass 4 -- Materiality filter

Pass 1-3 alone answer "does a measurable OLS relationship exist between this symbol and this
factor." Pass 4 answers a stricter question: "does that relationship still hold once common
market beta is controlled for, and is it stable and not an artifact of chance." Every tag
category is dominated to some degree by broad market co-movement -- Pass 1's raw `loading`
cannot distinguish "genuinely rate-sensitive" from "moves with everything, including rates,
because it moves with the market." Pass 4 exists to make that distinction falsifiable rather
than assumed.

**Measurement universe (D-01a, amended 2026-09-18):** Pass 4 measures every row Pass 1-3 KEPT
-- `passes_fdr AND abs(loading) >= loading_threshold`, computed once and reused for both Pass 4
selection and the Pass 3 decision. A row that fails that gate is written `passes_materiality =
false` rather than measured at all, so `passes_fdr = false` can never sit beside
`passes_materiality = true` on the same row.

**Control set and its exclusions (R-01, R-03).** Each candidate's `factor_series` loading is
orthogonalized (Pearson-convention partial correlation, not Spearman -- this project's existing
Phase 146 `loading`/`loading_threshold` values are Pearson-calibrated) against a four-leg
control set: `SPY` (broad equity), `TLT` (rates), `HYG-IEF` (credit), `UUP` (dollar) -- no DBC
commodity leg, since no commodity-broad tag currently carries a `factor_series`. Two exclusions
apply before residualizing, both silent-wrong-answer guards, and both an extension of the F6.1 /
CR-01 self-regression tautology guard Pass 1 already applies to its own target factor:

- a control leg is dropped when it equals the tag's own `factor_series` (residualizing a factor
  against itself drives the partial loading identically to zero);
- a control leg is dropped when the candidate symbol is that control, or one leg of its
  long-short spread (the same tautology Pass 1 guards against, extended to the controls).

`incremental_r2` is `R²_full - R²_controls` (ΔR², R-06) -- the incremental explanatory power
`factor_series` contributes beyond the control set alone, not the squared partial correlation,
per D-05's instruction to seed the more conservative gate reading. `control_factor_series` is an
APR JSON behavioral list (`alpha.tag_calibrator.materiality.control_factor_series`), so adding a
DBC leg later, if the shadow diagnostic surfaces commodity-cycle confounding, is an APR edit, not
a code change.

**Sign stability -- a deliberate discrete step, not a gradual slide (R-07).** Pass 4 evaluates
disjoint, tail-anchored rolling windows (`sign_stability_window_days` = 252 each) and counts how
many agree in sign with the run-level `partial_loading` sign (`sign_stable_windows` out of
`sign_stable_windows_total`), requiring at least `min_sign_stable_windows` = 3 to pass.
`min_sample_n` (756) is exactly three `sign_stability_window_days` windows, so a symbol at the
sample floor has only three evaluable windows and must show 3-of-3 agreement (100%), while a
symbol with a full four evaluable windows needs only 3-of-4 (75%) and may carry one
disagreement. The bar is strictly discrete at n=1008 (four times 252), and it gets STRICTER for
shorter-history symbols, not looser -- this is retained deliberately (resolved during Phase
175's D-07 cross-AI review, not left ambiguous), because requiring a full four windows would make
the `min_sample_n` floor unreachable. Plan 04's NEAR MISS section (the sign-stable-windows
histogram of failing candidates, plus each gate's `sole_failure` count) is the evidence base for
any future loosen/tighten/leave-alone decision; see
`docs/foundation/apr-calibration-backlog.md` for the pointer.

**Null arm (D-06).** A circular-shift null control -- shifting only the `factor_series` proxy's
own return series, never the candidate's return or a control column -- produces
`null_arm_p_value` per pair, BH-FDR-corrected once per run into `null_arm_bh_p`
(`alpha.tag_calibrator.materiality.null_arm_alpha`). The null arm runs inline inside
`TagCalibrator.execute()` (R-02), not as a separate offline diagnostic, because its
per-pair pseudo-inverse is precomputed once and reused across all Monte-Carlo draws, keeping it
affordable in the same corpus loop.

**Full history, not `lookback_days` (R-07).** Pass 4 measures against each symbol's full
available return history, not `tag_vocabulary.lookback_days` (Pass 1's window). A 4-control
partial regression with a 756-observation sample floor and four 252-day stability windows cannot
fit inside Pass 1's shorter per-tag window -- Pass 4 is a deliberately longer-horizon
materiality judgment layered on top of Pass 1's bivariate measurement, not a replacement for it.

**The statistical gate, and nothing else (R-04).** `decide_materiality()` (`services/
tag_calibrator.py`) returns `passes_materiality = True` only when all six conditions hold:
`materiality_sample_n >= min_sample_n`, `abs(partial_loading) >= min_partial_loading`,
`partial_loading_ci_low >= min_partial_loading_ci_low`, `incremental_r2 >= min_incremental_r2`,
the sign-stability bar above, and the null arm passing its own BH-FDR. It deliberately does NOT
consider `discovery_state` or `valid_to` -- collapsing the temporal or expiry gate into
`passes_materiality` would make the column change value with no new measurement having run.

**Definitional tags are never measured** — `exposure`, `cycle_position`, and most `signal_role` tags are owner-annotated seed priors by design, not calibration targets. Only `sensitivity`, `factor_regime`, and `macro_driver` tags with a `factor_series` set are in scope.

**Human rows are permanent unless a human changes them.** TagCalibrator can confirm or contradict a human-asserted tag (writing an annotation either way) but never overwrites or expires `source='human'` rows itself.

### `alpha.tag_calibrator.*` APR namespace (7 keys)

| Key | Default | Controls |
|-----|---------|----------|
| `fdr_alpha` | 0.05 | Run-level Benjamini-Hochberg significance threshold |
| `expiry_consecutive_fails` | 3 | Failing runs required before an empirical tag expires (hysteresis) |
| `discovery_oos_days` | 63 | Days a newly discovered tag should sit pending-OOS before being treated as confirmed (see Known Gap) |
| `min_sample_n` | 60 | Minimum paired daily-return observations to measure a pair at all |
| `hac_max_lag` | 5 | Newey-West Bartlett-kernel max lag |
| `half_life_min_days` / `half_life_max_days` | 30 / 365 | Clamp bounds for a `tag_vocabulary` row's `half_life_days` |

All seeded `[initial_estimate]`/`[conventional]` (migration 230) — none have been empirically re-derived yet; treat the same as any APR-calibration-backlog entry.

### `alpha.tag_calibrator.materiality.*` APR namespace (11 keys, migration 346)

`MaterialityConfig` (`services/tag_calibrator.py`) binds all eleven keys once at startup as a
frozen dataclass, sibling to (not extending) the 7-key `TagCalibratorConfig` above -- the two
namespaces are separately calibrated.

| Key | Default | Controls |
|-----|---------|----------|
| `min_partial_loading` | 0.35 | Minimum `abs(partial_loading)` to pass the materiality gate |
| `min_partial_loading_ci_low` | 0.20 | Minimum `partial_loading_ci_low` (R-05's lower-CI gate) to pass |
| `min_incremental_r2` | 0.05 | Minimum `incremental_r2` to pass |
| `min_sample_n` | 756 | Minimum `materiality_sample_n` before a pair is measured at all -- exactly three `sign_stability_window_days` windows |
| `sign_stability_window_days` | 252 | Length in trading days of each rolling sign-stability window |
| `sign_stability_window_count` | 4 | Number of rolling windows evaluated for sign stability |
| `min_sign_stable_windows` | 3 | Minimum windows agreeing in sign to pass (the discrete-step bar; see Pass 4 above) |
| `null_arm_alpha` | 0.05 | BH-FDR alpha applied to the D-06 null-arm p-vector |
| `null_arm_draws` | 1000 | Monte-Carlo draw count for the D-06 null arm |
| `null_arm_seed` | 42 | Base seed mixed with a per-(symbol, tag) hash to derive each pair's null generator. `[conventional]` -- this project's standing default RNG seed, not an uncalibrated estimate. WARNING: changing it invalidates every previously computed `null_arm_p_value`/`null_arm_bh_p` |
| `control_factor_series` | `["SPY","TLT","HYG-IEF","UUP"]` | R-03's four-leg orthogonalization control set, an APR JSON behavioral list -- adding a DBC leg is an APR edit, not a code change |

The ten gate thresholds (everything except `null_arm_seed`) are `[initial_estimate]` --
Codex's D-05-proposed conservative defaults, not re-derived against this corpus's actual
partial-loading distribution. Tracked in `docs/foundation/apr-calibration-backlog.md`.
`null_arm_seed` is `[conventional]` and, per CLAUDE.md's APR mandate category 1 (seeds that
affect algorithm output), is APR-backed but deliberately NOT a calibration-backlog entry -- it
is a reproducibility knob, not a gate-shaped threshold awaiting corpus calibration.

---

## Read contract

`instrument_tags_active` (`SELECT * FROM instrument_tags WHERE valid_to IS NULL`, migration
346) is the required read path for any tag-membership query (todo 126) -- never read the bare
`instrument_tags` table for a membership decision.

For the materiality-filtered arm specifically, `services.tag_calibrator.is_materiality_eligible()`
is the canonical predicate (D-02: one measurement engine, N read-time cutoffs). It ANDs three
gates, stored separately by design so a future per-consumer cutover can calibrate its own bar:
the statistical gate (`passes_materiality`, Pass 4), the temporal gate
(`discovery_state == 'confirmed'`, todo 125), and the expiry gate (`valid_to IS NULL`, todo
126). Any future consumer of the materiality-filtered arm should import this function rather
than re-deriving the conjunction -- `scripts/analysis/itr_materiality_shadow_diagnostic.py`
does exactly this.

**Current measured state (2026-09-23, `175-04-SUMMARY.md`):** the first live Pass 4 run
measured 2170 empirical pairs; 222 cleared the statistical gate. Under the materiality-filtered
admission rule, the shadow diagnostic found 0 symbols would currently be added to any of the
four enabled `regime_group`s (equity/rates/commodity/fx) -- the seeded `[initial_estimate]`
thresholds are, on this first measurement, conservative enough to admit nothing. `min_partial_loading`
and `incremental_r2` are the dominant binding constraints; see the shadow report for the full
gate-attribution and near-miss breakdown.

---

## Consumers

ITR is a read dependency for peer-group resolution, not itself a compute stage. Two live readers, both keying off `exposure`-category tag prefixes (`eq_*`, `intl_*`, `fi_*`, `fx_*`) -- neither currently consumes the `sensitivity`/`macro_driver` tags TagCalibrator measures (see Known Gap). Verified live 2026-09-18: both readers restrict further to `source = 'human'` rows only (interim stopgap, todo 379 -- see Known Gap on empirical-tag materiality filtering).

- **`services/cross_sectional_regime_model.py`** — each systematic regime group (`equity`, `rates`, `commodity`, `fx`) declares a `tag_filter` (prefix list) resolved against `instrument_tags` at startup, once.
- **`services/ic_engine.py`** — resolves `regime_group` peer sets the same way for cross-sectional IC stratification; enabled groups' `tag_filter`s must be mutually exclusive over the resolved universe (`AmbiguousRegimeGroupError` on overlap).

**`services/equity_regime_model.py` no longer exists** -- deleted 2026-09-17 as dead code (todo 381; its `INSERT` referenced an `asset_class` column `market_regimes`' live schema had already dropped in Phase 144, so it hadn't been callable for a while before removal). A prior version of this doc listed it as a live third reader; corrected here after the deletion was independently caught in a Fable rigor pass (2026-09-18) on a downstream ITR consumer-use idea doc. If a doc, comment, or script elsewhere still cites `equity_regime_model.py` as live, it is stale -- the two readers above are exhaustive.

Neither live consumer has been repointed at the materiality-filtered arm -- both remain the
`source = 'human'` stopgap described above. This is D-03's shadow-mode boundary: Phase 175
ships measurement only. Cutting either consumer over is a separate, later decision gated on
the shadow report above plus the D-07 cross-AI review and the user's own review (tracked by
todo 380).

---

## Adding a New Tag

**Step 1 — Vocabulary.** Insert into `tag_vocabulary`. For an empirically measurable tag, set `measurement_type='beta_regression'`, a `factor_series` proxy, and a `loading_threshold`. For a structural/definitional tag, leave `measurement_type='definitional'` (the default sweep already does this for any row with `factor_series IS NULL`).

```sql
INSERT INTO tag_vocabulary (tag, category, description, factor_series, measurement_type, loading_threshold)
VALUES ('housing_cycle', 'macro_driver', 'Sensitive to housing starts, rates, affordability.',
        'XHB', 'beta_regression', 0.2);
```

**Step 2 — Seed assignment (optional).** A human can assert an initial `source='human'` row for known holders; TagCalibrator will independently discover others on its next run if a real relationship exists.

**Step 3 — Run TagCalibrator.** `python services/tag_calibrator.py` (no timer today — run manually, or wire into the ops batch cadence when this graduates past "run when someone remembers to").

**Step 4 — Never share a `factor_series` with an existing tag.** Collision means the two tags are redundant measurements of the same concept (see banned-alias rule above) — merge them instead of adding a duplicate.

---

## What Does NOT Belong Here

| Category | Where it lives | Why |
|----------|-----------------|-----|
| Regime state (per-bar, time-varying) | `feature_vectors.regime` / `market_regimes` | ITR tags are static per-symbol classification, not a per-bar conditioning label — see [`StratificationDimension`](../research/stratification-dimension-unification.md) |
| Numeric thresholds/weights (incl. TagCalibrator's own tuning constants) | APR (`config_state`) | ITR governs classification claims, not tunable numbers |
| GICS-style external sector/industry hierarchy | Design-only, unbuilt — see [`Security Classification Hierarchy`](../research/stratification-security-classification-hierarchy.md) | Strict, externally authoritative, single-parent — not falsifiable by this system, unlike a tag |
| Regime-conditioned tag betas (different loading per market regime) | Design-only, unscheduled — see [Phase 2 design](../research/tag-calibrator-phase2-regime-conditioning.md) | Not built; Phase 1 measures one unconditional beta per pair |

---

## Known Gaps

- **RESOLVED (todo 125, Phase 175, 2026-09-23): `discovery_oos_days` is now enforced.** `discovery_state`/`first_measured_at` are typed `instrument_tags` columns (migration 346), not JSONB-only, and `is_materiality_eligible()` reads `discovery_state == 'confirmed'` as its temporal gate (see Read contract above). A freshly discovered tag with a fully-passing statistical profile is still not eligible while `discovery_state = 'pending_oos'` -- test-pinned by `tests/unit/test_tag_calibrator.py::test_discovery_oos_gate_blocks_fresh_discovery`. The `evidence` JSONB copy of both fields is retained for backward compatibility (a repo-wide `grep -rn "discovery_state|first_measured_at" src/ services/ scripts/` found no other reader of either field besides `tag_calibrator.py`'s own write site and the shadow diagnostic's read site), not removed this phase.
- **`sensitivity`/`macro_driver` are measured but still unconsumed by any live query -- now with a materiality filter, not just raw significance.** Verified live 2026-09-18 (up from 211/300 at the original 2026-08-20 finding -- TagCalibrator has run since): 578 `sensitivity` rows and 875 `macro_driver` rows carry real `TagCalibrator`-measured betas (`source='empirical'`, non-null `loading`/`p_value`), several of them (`rate_sensitive`→`TLT`, `credit_risk`→`HYG-IEF`, `volatility`→`SPY_REALIZED_VOL`, `dollar_strength`→`UUP`) targeting the same reference instruments `market_regimes`' `regime_group` system already computes continuous group-level signals for -- via a completely separate, never-joined pipeline (see `docs/ideas/signal-sensitivity-regime-interaction-primitives.md`, revision-required, not yet promoted to `docs/research/`). **Current status (2026-09-23):** raw `loading`/`passes_fdr` alone no longer has to be the only available filter -- Pass 4's `passes_materiality`/`is_materiality_eligible()` now separate real sensitivity from common-beta noise (see Read contract above), and the shadow diagnostic has run against the live corpus. But the gap itself is unchanged in one respect: neither live consumer reads either tag category, filtered or not -- both still restrict to `source='human'` exposure-prefix rows (D-03 shadow mode). Cutover is gated on the shadow report plus the D-07 cross-AI review and the user's own review (todo 380), not yet scheduled.
- **RESOLVED (todo 126, Phase 175, 2026-09-23): the read contract is now established, but neither live consumer has been cut over to it.** `instrument_tags_active` (migration 346) is the required read path for unexpired rows -- see Read contract above -- and `is_materiality_eligible()` additionally re-checks `valid_to IS NULL` in code, not just via the view. What has NOT changed: `services/cross_sectional_regime_model.py` and `services/ic_engine.py` still query `source = 'human'` directly with no `valid_to` filter, exactly as before (D-03 shadow-mode boundary -- Phase 175 ships evidence and the view, not a consumer change). This is now a "not yet cut over" state rather than "no contract exists" -- a future cutover should read through `instrument_tags_active`, not re-derive the filter.
- **No dashboard.** APR has `/config/parameters`; ITR has no equivalent UI. Inspecting live tag state means querying `tag_vocabulary`/`instrument_tags` directly.
- **No dedicated audit-log table.** Unlike APR's `config_history`, there's no append-only record of every tag-state transition -- the evidence trail lives inline on the current row (`loading`, `p_value`, `consecutive_fails`) plus point-in-time `instrument_annotations` notes on discovery/expiry/contradiction events. A `git log`-style "show me this tag's full history" query isn't directly supported. This is also a structural lookahead risk, not just an audit-trail nicety: every `TagCalibrator` run overwrites `loading`/`p_value`/`sample_n` on the current row in place (only `valid_from` is set, once, on first insert), so a historical backtest joining a `sensitivity` loading against a past timestamp would silently use today's loading, not the loading as it stood then -- confirmed by a Fable rigor pass 2026-09-18 on `docs/ideas/signal-sensitivity-regime-interaction-primitives.md`. See `docs/ideas/itr-extension-opportunities.md` #1 for a sketched fix (append-only `instrument_tags_history`, mirroring APR's `config_history`) -- ranked there as the highest-leverage, least-documented ITR extension candidate; not designed to implementation-readiness.
- **`correlation`/`cross_correlation`/`mutual_information` measurement types are schema-allowed but unimplemented.** Any future tag using one of these is silently skipped (logged once, never measured) rather than erroring -- by design (T-146-11 defense-in-depth), but worth knowing before assigning one expecting it to actually run. `mutual_information` has a narrow, already-designed use case (a `regime_classifier` tag measuring MI against HMM regime state -- see `docs/research/stratification-instrument-tag-calibrator.md`); using it as a general nonlinear-sensitivity detector beyond that one case is unscoped. See `docs/ideas/itr-extension-opportunities.md` #3.

---

## Related Docs

- `docs/foundation/glossary.md` — canonical vocabulary: `tag`, `primitive`, `tag vocabulary`, `classification scheme` vs. `taxonomy`, p-value/r² gates.
- `docs/foundation/adaptive-parameter-registry.md` — the sibling registry this doc's structure mirrors.
- `docs/research/stratification-instrument-tag-calibrator.md` — original Phase 146 design doc (TAG-01/02/03 breakdown, Simons-critique review history).
- `docs/research/tag-calibrator-phase2-regime-conditioning.md` — unscheduled Phase 2 design (regime-conditioned betas).
- `docs/research/fable-2026-07-16-tag-calibrator-taxonomy-review.md` — taxonomy soundness review, factor-series data-coverage findings.
- `docs/research/concept-governance-registries.md` — where ITR sits among IndicAgent's other governance registries.
- `docs/foundation/controlled-vocabulary-registry.md` (CVR) -- sibling registry, deliberately kept separate (D-02): CVR governs fixed symbolic taxonomies (a code either exists or it doesn't), ITR governs falsifiable classification claims (a tag is a hypothesis with evidence). Not the same system despite both being colloquially "tag"-adjacent.
- `docs/ideas/itr-extension-opportunities.md` -- ranked survey of candidate extensions to this doc's Known Gaps (point-in-time history, walk-forward re-validation, cross-tag collinearity), cross-checked against existing design docs before writing anything new.
