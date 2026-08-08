# Instrument Tag Registry (ITR)

**Canonical name:** Instrument Tag Registry (ITR)
**Informal aliases:** tag system, tag vocabulary (colloquial — acceptable in casual conversation, not in architecture docs or code comments)
**Status:** current — TagCalibrator (empirical measurement engine) live since 2026-07-17
**Last Updated:** 2026-08-08
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

**Banned aliases:** `credit_cycle` was merged into `credit_risk` (Phase 146, migration 237, 2026-07-17) — both tagged the identical underlying `credit_risk` factor loading on the same holders (`HYG`, `LQD`) at near-identical weights. Do not reintroduce it. Full rule: two tags must never share the same `factor_series` value (redundant measurements of the same quantity under different names).

---

## How TagCalibrator Works

`services/tag_calibrator.py` — a `BaseBatch` oneshot (no systemd unit; run manually or via the ops batch runner, not on a timer), generic three-pass measurement engine over the full instrument × measurable-tag matrix (F8 "Simons inversion" — measure everything, then decide, rather than deciding what to measure ahead of time).

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
```

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

---

## Consumers

ITR is a read dependency for peer-group resolution, not itself a compute stage. Three live readers, all keying off `exposure`-category tag prefixes (`eq_*`, `intl_*`, `fi_*`, `fx_*`) — none currently consume the `sensitivity`/`macro_driver` tags TagCalibrator measures (see Known Gap):

- **`services/equity_regime_model.py`** — breadth universe = symbols with `eq_*`/`intl_*` tags.
- **`services/cross_sectional_regime_model.py`** — each systematic regime group (`equity`, `rates`, `commodity`, `fx`) declares a `tag_filter` (prefix list) resolved against `instrument_tags` at startup, once.
- **`services/ic_engine.py`** — resolves `regime_group` peer sets the same way for cross-sectional IC stratification; enabled groups' `tag_filter`s must be mutually exclusive over the resolved universe (`AmbiguousRegimeGroupError` on overlap).

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

- **`discovery_oos_days` is computed but not enforced** (todo 125, pending). A freshly discovered tag writes a fully live `source='empirical'` row immediately — `discovery_state: pending_oos` is stashed in `evidence` JSONB but nothing reads it to gate weight or downstream consumption. Practical urgency is low: no live consumer touches the `sensitivity`/`macro_driver` tags this affects yet (all three live readers key off definitional `exposure` prefixes).
- **No dashboard.** APR has `/config/parameters`; ITR has no equivalent UI. Inspecting live tag state means querying `tag_vocabulary`/`instrument_tags` directly.
- **No dedicated audit-log table.** Unlike APR's `config_history`, there's no append-only record of every tag-state transition — the evidence trail lives inline on the current row (`loading`, `p_value`, `consecutive_fails`) plus point-in-time `instrument_annotations` notes on discovery/expiry/contradiction events. A `git log`-style "show me this tag's full history" query isn't directly supported.
- **`correlation`/`cross_correlation`/`mutual_information` measurement types are schema-allowed but unimplemented.** Any future tag using one of these is silently skipped (logged once, never measured) rather than erroring — by design (T-146-11 defense-in-depth), but worth knowing before assigning one expecting it to actually run.

---

## Related Docs

- `docs/foundation/glossary.md` — canonical vocabulary: `tag`, `primitive`, `tag vocabulary`, `classification scheme` vs. `taxonomy`, p-value/r² gates.
- `docs/foundation/adaptive-parameter-registry.md` — the sibling registry this doc's structure mirrors.
- `docs/research/stratification-instrument-tag-calibrator.md` — original Phase 146 design doc (TAG-01/02/03 breakdown, Simons-critique review history).
- `docs/research/tag-calibrator-phase2-regime-conditioning.md` — unscheduled Phase 2 design (regime-conditioned betas).
- `docs/research/fable-2026-07-16-tag-calibrator-taxonomy-review.md` — taxonomy soundness review, factor-series data-coverage findings.
- `docs/research/concept-governance-registries.md` — where ITR sits among IndicAgent's other governance registries.
