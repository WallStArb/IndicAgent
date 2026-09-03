---
phase: 146-empirical-instrument-tag-calibrator
reviewed: 2026-07-17T00:00:00Z
depth: standard
files_reviewed: 9
files_reviewed_list:
  - docs/foundation/glossary.md
  - docs/research/tag-calibrator-phase2-regime-conditioning.md
  - production/migrations/237_tag_vocabulary_taxonomy_cleanup.sql
  - production/migrations/238_tag_calibrator_measurement_contract.sql
  - services/tag_calibrator.py
  - src/intelligence/statistics/factor_math.py
  - tests/unit/test_factor_math.py
  - tests/unit/test_spread_leg_pair_validity.py
  - tests/unit/test_tag_calibrator.py
findings:
  critical: 2
  warning: 5
  info: 2
  total: 9
status: issues_found
---

# Phase 146: Code Review Report

**Reviewed:** 2026-07-17
**Depth:** standard
**Files Reviewed:** 9
**Status:** issues_found

## Summary

Reviewed the Empirical Instrument Tag Calibrator (Phase 146, TAG-01): two migrations (237
taxonomy cleanup, 238 measurement-contract schema + APR seed), the `factor_math.py` pure
statistics kernel, the `TagCalibrator` `BaseBatch` service, and their unit tests. The
migrations and unit tests are careful and internally consistent (spread_leg symmetry is
verified live via a dedicated data-contract test; the FDR/hysteresis/self-regression unit
tests are well-targeted). However, tracing the actual measurement math against the tag
_vocabulary_ that migration 238 seeds turns up two real correctness bugs that the existing
tests do not catch because they only exercise the single-symbol case, not the long-short
factor-series case that four of Phase 1's twelve measurable tags actually use:

1. The `F6.1` self-regression guard (`symbol == factor_series`) does not generalize to the
   long-short (`"HYG-IEF"`-style) factor series — an instrument that is itself one leg of its
   own tag's factor series (HYG/IEF for `credit_risk`, TIP/IEF for `inflation`, IEF/SHY for
   `yield_curve`, XLE/SPY for `oil_price`) gets measured against a "factor" that mathematically
   contains its own return as an additive term, producing a tautologically inflated loading.
2. The discovery/OOS-confirmation gate (`alpha.tag_calibrator.discovery_oos_days`) is computed
   and stored as an evidence annotation but never actually gates anything — a first-pass
   discovery is written as a fully live `source='empirical'` row from day one, identical in
   weight/authority to a tag that has survived `discovery_oos_days` of out-of-sample
   confirmation. This directly contradicts both the APR key's own migration-238 description and
   the 146-04-PLAN.md pass-3 spec ("INSERT pending-OOS until discovery_oos_days ... confirm").

Both are detailed below with fixes. Several secondary robustness/data-integrity gaps
(`valid_to` churn on repeated post-expiry failures, a migration idempotency gap, a missing
`loading_threshold` null-guard, and an `inf`-vs-`NaN` gap in the return-series construction)
are filed as warnings.

## Structural Findings (fallow)

None provided for this review.

## Critical Issues

### CR-01: F6.1 self-regression guard does not catch a symbol that is one leg of its own long-short factor series

**File:** `services/tag_calibrator.py:184-198` (`_is_self_regression`, `_factor_leg_symbols`), exercised via `measure_matrix` at `services/tag_calibrator.py:338-342`

**Issue:** `_is_self_regression(symbol, factor_series)` is a literal string-equality check:

```python
def _is_self_regression(symbol: str, factor_series: str) -> bool:
    """F6.1: an instrument can never be regressed against itself."""
    return symbol == factor_series
```

This correctly skips the single-symbol case (`symbol == "TLT"` vs `factor_series == "TLT"`), but
migration 238 seeds four **long-short** factor series whose `factor_series` value is a hyphenated
pair, not a single symbol: `credit_risk` → `"HYG-IEF"`, `inflation` → `"TIP-IEF"`,
`yield_curve` → `"IEF-SHY"`, `oil_price` → `"XLE-SPY"`. For any of these, `symbol == factor_series`
is never true even when `symbol` is literally one of the two legs (e.g. `symbol == "HYG"`,
`factor_series == "HYG-IEF"`), so `_is_self_regression` returns `False` and the pair proceeds to
full measurement.

`_build_factor_return_series` then constructs the factor as
`long_short_daily_returns(HYG_close, IEF_close) = log_ret(HYG) - log_ret(IEF)`. When HYG (or IEF)
is itself the instrument being measured, `standardized_loading` computes the correlation between
`log_ret(HYG)` and `log_ret(HYG) - log_ret(IEF)` — a series that contains the instrument's own
return as a literal additive term. This is a mathematical tautology, not a measurement: the
resulting loading will be strongly positive (or negative, for the short leg) purely by
construction, largely independent of any real credit/rate/oil relationship, and will very likely
clear both the BH-FDR and `loading_threshold` gates — writing a spurious, artificially-confident
`source='empirical'` row into `instrument_tags` for exactly the six symbols (HYG, IEF, TIP, SHY,
XLE, SPY) that are core, always-active benchmarks in this universe (all six already carry
human-asserted rows for related tags, per migration 227's seed data and migration 237's
credit_cycle merge commentary, confirming they are active ETFs that will hit this code path every
run).

This is the exact class of defect `F6.1`'s own stated invariant ("Self-regression pairs
(`symbol == factor_series`) are always skipped") was written to prevent — the design doc
(146-04-PLAN.md, `F6.1`) never considered the long-short case; RESEARCH.md's "Pitfall 2" discusses
a *different*, explicitly-deferred self-regression class (cross-symbol pseudo-tautologies like
MCHI vs FXI economically tracking the same index) — this leg-inclusion case is not that deferred
item, it is a plain implementation gap.

**Fix:** Check membership in the resolved leg set, not string equality against the raw
`factor_series` value — `_factor_leg_symbols` already exists and does exactly this resolution:

```python
def _is_self_regression(symbol: str, factor_series: str) -> bool:
    """F6.1: an instrument can never be regressed against a factor series it is
    itself a component of (single-symbol match OR one leg of a long-short spread)."""
    return symbol in _factor_leg_symbols(factor_series)
```

Add a regression test alongside the existing `test_skips_self_regression` that exercises the
long-short leg case, e.g. `_is_self_regression("HYG", "HYG-IEF") is True` and
`_is_self_regression("IEF", "HYG-IEF") is True`.

---

### CR-02: `discovery_oos_days` OOS-confirmation gate is computed but never enforced — new discoveries go live immediately

**File:** `services/tag_calibrator.py:432-542` (`_next_evidence`, `_apply_decision`)

**Issue:** `alpha.tag_calibrator.discovery_oos_days`'s own migration-238 description states it is
"days required before a newly discovered (gap-annotated) empirical tag is promoted to a live
`instrument_tags` row." 146-04-PLAN.md's pass-3 spec says the same thing operationally: "keep+no
row → INSERT pending-OOS until `discovery_oos_days` of disjoint data confirm."

But `_apply_decision`'s `insert_discovery` branch (`action in ("upsert_empirical",
"insert_discovery")` at line 507) executes the exact same `_UPSERT_EMPIRICAL_SQL` as a normal
keep-and-update, on the very first passing measurement:

```python
if action in ("upsert_empirical", "insert_discovery"):
    ...
    weight = abs(measurement["loading"])
    await conn.execute(_UPSERT_EMPIRICAL_SQL, symbol, tag, weight, evidence, ...)
```

The row is written with `source='empirical'`, full `weight`/`loading`/`p_value`, immediately —
indistinguishable in every queryable column from a tag that has survived `discovery_oos_days` of
confirmation. `_next_evidence` does compute a `discovery_state` field
(`"pending_oos"` vs `"confirmed"`) and stashes it in the `evidence` JSONB, but nothing in this
file — or anywhere else in the codebase (`grep -rn "discovery_state"` across `src/` and
`services/` returns only the lines that *write* it in `tag_calibrator.py` itself) — ever reads
that field to gate weight, gate downstream consumption, or otherwise treat a `pending_oos` row
differently from a `confirmed` one.

The practical effect: a single lucky (or noisy, pre-FDR-correction-notwithstanding) measurement on
run 1 makes a brand-new tag fully "empirical" and live, with the OOS confirmation step existing
only as dead metadata. This is precisely the kind of "prove edge before treating it as proven"
gate this codebase's own principles (`earn promotion through proof`) and this phase's own design
intend to enforce, but it currently does nothing.

**Fix:** Either (a) do not write a full `instrument_tags` row on `insert_discovery` until
`elapsed_days >= discovery_oos_days` — track the pending discovery state in
`instrument_annotations` only (which is already written unconditionally in this branch) until
confirmed, or (b) write the row but gate `weight` (or add a `pending` boolean the FDR/keep
consumers can filter on) so a `pending_oos` row cannot be mistaken for a confirmed one by any
current or future consumer. Whichever direction is chosen, add a test that asserts a fresh
discovery does NOT reach the same state as a `discovery_oos_days`-confirmed one until the elapsed
days actually clear the gate — none of the six existing `test_tag_calibrator.py` tests cover this
path today.

## Warnings

### WR-01: `valid_to` is overwritten on every failing run after a tag is already expired, corrupting the recorded expiry timestamp

**File:** `services/tag_calibrator.py:388-429` (`decide_outcome`), `475-486`
(`_UPDATE_FAILING_OR_EXPIRE_EMPIRICAL_SQL`)

**Issue:** `decide_outcome` never inspects `existing_row.get("valid_to")`. Once a tag has expired
(`consecutive_fails >= expiry_consecutive_fails`, `valid_to` set to that run's `now()`), a
subsequent failing run still takes the `keep=False`/`existing_row is not None` branch, computes
`new_fails = existing_row["consecutive_fails"] + 1` (still `>= expiry_consecutive_fails`), and
returns `action="expire"` again. `_apply_decision`'s `_UPDATE_FAILING_OR_EXPIRE_EMPIRICAL_SQL` then
re-executes `valid_to = CASE WHEN $10 THEN now() ELSE valid_to END` with `$10=True`, resetting
`valid_to` to the *current* run's timestamp — every run, indefinitely, for as long as the tag keeps
failing. `valid_to` stops meaning "the timestamp this tag actually became invalid" and instead
tracks "the timestamp of the most recent calibration run," silently corrupting any historical/
backtest query that joins on `valid_to` to determine when a tag stopped being true (exactly the
kind of temporal-validity leak the Phase 2 doc calls out for `classification_scheme` membership).

**Fix:** Guard the expire transition so it only fires once:

```python
if existing_row.get("valid_to") is not None:
    return {"action": "no_op", "consecutive_fails": existing_row.get("consecutive_fails", 0)}
```

placed before the `new_fails` computation in the `keep=False`/non-human branch, or equivalently
change the SQL's CASE to `valid_to = CASE WHEN valid_to IS NULL AND $10 THEN now() ELSE valid_to END`.

---

### WR-02: No downstream consumer of `instrument_tags` filters on `valid_to` — the expiry mechanism has no observable effect yet

**File:** `services/ic_engine.py:2884`, `services/equity_regime_model.py:289`,
`services/cross_sectional_regime_model.py:261` (all read `instrument_tags`/`array_agg(tag)`
with no `WHERE valid_to IS NULL`)

**Issue:** Migration 238 introduces `valid_to` as the expiry marker for empirical rows, but every
existing live reader of `instrument_tags` (`ic_engine.py`'s `_build_symbol_regime_class`,
`equity_regime_model.py`'s breadth-universe query, `cross_sectional_regime_model.py`'s
`_load_tags_by_symbol`) selects the full table with no expiry filter. Today this doesn't produce
visibly wrong output because none of those readers key off the specific `sensitivity`/
`macro_driver` tags TagCalibrator measures (they use `eq_*`/`intl_*`/`fi_*`/`fx_*` exposure-tag
prefixes, which TagCalibrator never touches — those stay `measurement_type='definitional'`). But
there is currently no enforced contract anywhere that a *future* consumer of the empirically
calibrated tags (rate_sensitive, credit_risk, etc.) will remember to add `AND valid_to IS NULL`;
nothing (view, helper function, or even a code comment at each of the three existing call sites)
establishes this obligation.

**Fix:** Either add a canonical `instrument_tags_active` view (`... WHERE valid_to IS NULL`) that
becomes the required read path for any tag-membership query, or at minimum add a comment at each
existing `instrument_tags` read site noting that `valid_to` must be respected once any empirically
measured tag is consumed there.

---

### WR-03: Migration 238's `equity_beta` seed `INSERT` is not idempotent, unlike every other statement in the file

**File:** `production/migrations/238_tag_calibrator_measurement_contract.sql:92-95`

**Issue:** Every other data-mutating statement in this migration is written to be safely re-runnable
(`ADD COLUMN IF NOT EXISTS`, `ON CONFLICT (config_key) DO NOTHING`, plain `UPDATE`s that are
naturally idempotent). The one exception:

```sql
INSERT INTO tag_vocabulary (tag, category, description)
    VALUES ('equity_beta', 'sensitivity', '...');
```

`tag_vocabulary.tag` is `PRIMARY KEY` (migration 227). Re-running this migration (e.g. after a
partial failure elsewhere in the same file, or a manual re-apply) raises a unique-violation on this
one statement, breaking the file's otherwise-consistent re-run safety.

**Fix:** `INSERT INTO tag_vocabulary (tag, category, description) VALUES (...) ON CONFLICT (tag) DO NOTHING;`

---

### WR-04: `keep` gate will raise `TypeError` if any future `beta_regression` row has a NULL `loading_threshold`

**File:** `services/tag_calibrator.py:690`

**Issue:**

```python
keep = m["passes_fdr"] and abs(m["loading"]) >= m["loading_threshold"]
```

`filter_measurable_tag_rows` (the module's own stated "defense-in-depth" gate) checks
`measurement_type` and `factor_series IS NOT NULL`, but never checks `loading_threshold IS NOT
NULL`. Every tag migration 238 currently seeds as `beta_regression` does get an explicit
`loading_threshold=0.2`, so this doesn't fire today — but if a future tag is added with
`measurement_type='beta_regression'` and `factor_series` set but `loading_threshold` left NULL
(easy to miss, since `tag_vocabulary.loading_threshold` has no `NOT NULL` constraint), this line
raises `TypeError: '>=' not supported between instances of 'float' and 'NoneType'` inside the
per-pair decision loop, aborting the entire run (caught only by the outer `try/except Exception`
in `execute()`, which re-raises after logging — losing every subsequent pair's decision for that
run, not just the one bad row).

**Fix:** Add `loading_threshold is not None` to `filter_measurable_tag_rows`'s measurability check
(same anomaly path as the existing null-`factor_series` guard), or default it defensively at the
comparison site.

---

### WR-05: `np.log(close / close.shift(1))` can inject `+/-inf` that `.dropna()` does not remove

**File:** `src/intelligence/statistics/factor_math.py:247`
(`_build_factor_return_series`'s single-symbol branch), same pattern in
`services/tag_calibrator.py:274` (`_measure_pair`'s `instrument_ret`)

**Issue:** `np.log(factor_close / factor_close.shift(1)).dropna()` computes `-inf` (not `NaN`) for
any zero-or-negative close price ratio, and `.dropna()` only removes `NaN`, not `+/-inf`. If a bad
tick or data-quality gap ever puts a non-positive close into `market_data_ohlcv_tradeable`, an
`inf` can flow into `standardized_loading`'s `std()`/`cov()` computation, and the final
`np.clip(loading, -1.0, 1.0)` would silently clip an `inf`-derived result to exactly `+1.0` or
`-1.0` rather than the `NaN` this module's own docstring claims to guarantee ("returns NaN rather
than a spurious 0.0 or +/-inf"). Low probability given `market_data_ohlcv_tradeable`'s `volume > 0`
filter, but the module explicitly claims to guard against exactly this failure mode and currently
doesn't for this specific input path.

**Fix:** `.replace([np.inf, -np.inf], np.nan).dropna()` at both return-construction sites, or
validate `close > 0` before taking the log.

## Info

### IN-01: `_loading_standard_errors`'s `naive_se`/`hac_se` split is redundant — the final effective-df calculation only ever uses their ratio

**File:** `src/intelligence/statistics/factor_math.py:183-196`, `237`

**Issue:** `loading_hac_pvalue` computes `inflation = (hac_se / naive_se) ** 2`, but `hac_se` is
defined inside `_loading_standard_errors` as `naive_se * math.sqrt(inflation)` (the identical
`inflation` value computed a few lines earlier) — so `(hac_se / naive_se) ** 2` always
recovers exactly the same `inflation` value that was already computed and then discarded.
Not incorrect (the math is self-consistent — the `naive_se` absolute value is otherwise only used
for a `< 1e-12` degeneracy check), but this is a confusing double-detour: computing `inflation`,
converting it to an SE, then converting that SE back into the same `inflation`.

**Fix (optional, non-blocking):** Have `_loading_standard_errors` return `inflation` directly (or
have `loading_hac_pvalue` call a variant that skips the SE round-trip) so the relationship between
the two functions is not obscured by an unnecessary detour through absolute SE units.

---

### IN-02: `factor_math.py` imports a private (`_`-prefixed) symbol across a Ring 1 module boundary

**File:** `src/intelligence/statistics/factor_math.py:32`

**Issue:** `from src.intelligence.regime_signals.breadth_vol import _compute_vix_pct_rank` reaches
into another module's private namespace. The module docstring explains this is deliberate reuse
("VERBATIM ... never a re-derived ... percentile rank"), which is the right call functionally, but
a leading-underscore name crossing a module boundary is a maintenance trap — a future
`breadth_vol.py` refactor could rename/remove `_compute_vix_pct_rank` without any signal that
`factor_math.py` depends on it (no public re-export, no `__all__` entry in `breadth_vol.py` for
it).

**Fix (optional, non-blocking):** Have `breadth_vol.py` export a small public wrapper (or add this
name to its own `__all__`) so the cross-module dependency is visible from the exporting side, not
just documented in the importing side's docstring.

---

_Reviewed: 2026-07-17T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
