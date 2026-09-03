# Tag Calibrator Phase 2: Regime-Conditioning Design (TAG-02)

**Status:** Design-only. Not scheduled, not scoped into Phase 146. Ships later, gated on the
condition stated in "Ship condition" below.
**Informed by:** `docs/research/stratification-instrument-tag-calibrator.md` (primary design doc,
"Regime conditioning (Phase 2)" section, F6.3, F7, Sequencing) and
`.planning/milestones/v3.1-phases/146-empirical-instrument-tag-calibrator/146-CONTEXT.md` (D-01 through
D-12, this phase's Wave 0-1 decisions) and `146-RESEARCH.md` (live schema/APR-key verification,
2026-07-17).

## 1. Problem

Phase 1 (this phase, 146) computes one unconditional OLS loading per `(symbol, tag)` pair — a
single beta averaged across whatever market conditions fell inside the 252-day lookback window.
That is a first-order approximation. Factor exposure is not constant through time; it is
regime-dependent, and averaging across regimes can produce a number that is not representative of
either regime it was blended from.

The canonical example (design doc, "Regime conditioning (Phase 2)"): TLT's `rate_sensitive` beta
in a high-vol, flight-to-quality regime is materially different from its beta in a calm,
low-vol regime — in a flight-to-quality episode, capital flows into long-duration Treasuries for
reasons that have little to do with the rate move itself, temporarily distorting the measured
rate-sensitivity of every instrument that also catches a flight-to-quality bid. A single blended
beta averages this distortion into every unconditional reading, unconditionally, forever. XLU's
`rate_sensitive` beta shows the same effect from the other direction — a utility ETF's rate
sensitivity in a high-vol regime is not the same number as in a low-vol regime, and Phase 1 cannot
represent that difference; it can only report the single-regime-blind average.

Renaissance's own practice (cited directly in the design doc) treats this as a first-order
correction, not an optional refinement: "everything was regime-conditional." Phase 1 ships the
unconditional version because it is simpler to build and is a legitimate starting point — not
because the unconditional number is believed to be sufficient on its own.

## 2. Schema extension

The primary key of `instrument_tags` extends from `(symbol, tag)` to `(symbol, tag, regime)`.

```
-- Phase 1 (live after migration 238, Plan 02):
PRIMARY KEY (symbol, tag)

-- Phase 2 (sketch, not a migration to run now):
PRIMARY KEY (symbol, tag, regime)
```

Every measurement-contract column migration 238 added to `instrument_tags` — `loading`,
`p_value`, `bh_adjusted_p`, `passes_fdr`, `consecutive_fails`, `sample_n`, `estimated_at`,
`valid_from`, `valid_to` — carries over unchanged in meaning, just computed per-regime instead of
once. A regime-conditioned row is not a new kind of measurement; it is the same measurement
re-run inside a stratified subset of the same 252-day (or Phase-2-appropriate) lookback window.
`valid_from`/`valid_to` behavior does not change either: each `(symbol, tag, regime)` row has its
own independent temporal-validity lifecycle exactly as each `(symbol, tag)` row does today — a
tag can expire in one regime (`consecutive_fails` hits `expiry_consecutive_fails` for that regime
stratum specifically) while remaining valid in another. There is no cross-regime coupling in the
expiry logic; each stratum is measured, gated, and expired independently.

`tag_vocabulary`'s measurement-contract columns (`factor_series`, `measurement_type`,
`lookback_days`, `loading_threshold`, `half_life_days`) do not gain a regime dimension — they stay
per-tag, not per-`(tag, regime)`. The *contract* for what gets measured and how (which factor
series, what threshold) does not change between regimes; only the *measured value* does. This
mirrors Phase 1's own separation of concerns: `tag_vocabulary` defines what is measured,
`instrument_tags` holds the measurement's result.

`sample_n` becomes the load-bearing column for the per-stratum sample-size guard (Section 5) —
under Phase 1 it records "how many paired daily-return observations went into this beta"; under
Phase 2 it records the same thing per regime stratum, which is materially smaller per row than
Phase 1's `sample_n` because the 252-day window gets split across regime states instead of used
whole.

## 3. Regime axis choice

This project runs a **dual regime system** (`.planning/STATE.md`, "Dual Regime System"), and Phase
2 must state, per tag, which axis a regime-conditioned row is stratified on — never a bare
`regime` label with an implicit, undocumented axis:

- **`feature_vectors.regime`** — per-symbol HMM label (5 states: `trending_down`,
  `transition_down`, `ranging`, `transition_up`, `trending_up`), written by `regime_writer.py`
  (K=5, causal forward-filter). This is an **idiosyncratic/symbol regime** — it describes the
  instrument's own trend state, not the market's.
- **`market_regimes`** — cross-sectional label keyed by `regime_group` (a named peer group with a
  pluggable regime signal: `breadth_vol` for equity, `curve_credit` for rates), written by
  `cross_sectional_regime_model.py` (Phase 144). This is a **systematic/market regime** — it
  describes the state of the peer group the instrument belongs to, not the instrument itself.

The design doc's TLT/XLU flight-to-quality example is a *systematic* regime effect — capital
flows during a market-wide flight-to-quality episode, not an idiosyncratic property of TLT's or
XLU's own price trend. The correct default axis for Phase 2's regime conditioning is therefore
**`market_regimes.regime_group`** (the systematic/cross-sectional axis), not the per-symbol HMM
label. This is a design default, not an unconditional rule: a future tag whose regime-dependence
is idiosyncratic (e.g., a tag whose loading genuinely differs depending on whether the *instrument
itself* is trending vs. ranging, independent of the broader market) would correctly condition on
`feature_vectors.regime` instead. The schema in Section 2 supports either axis identically —
`regime` is a single column, but its *value* must always resolve as a `(dimension, label)` pair,
never a bare label string, so downstream consumers know which regime system produced it:

```
regime_dimension  text  -- 'market_regime' | 'symbol_regime'
regime_label      text  -- e.g. 'risk_off' (market_regime) or 'trending_down' (symbol_regime)
```

(Sketch only — the exact column split, whether `regime` stays a single composite value or two
columns as shown, is Claude's Discretion at Phase 2 execution time, not locked here. The load-bearing
requirement is that the resolved value is never ambiguous about which regime system produced it —
a bare `'risk_off'` string is insufficient if both systems could plausibly emit an overlapping
label.)

Both axes may eventually condition the same tag if empirical evidence (Section 4's trigger gate)
shows divergence on both — nothing in this design forecloses that; it is simply not the Phase-1
default assumption for the canonical TLT/XLU example.

## 4. Trigger gate

Phase 2 ships only when **IC stratification by tag shows regime-dependent divergence** — this is
the ship condition (ROADMAP TAG-02), restated operationally here so a future execution has a
concrete test rather than a subjective judgment call:

**Operational definition of "divergence":** for a given `(symbol, tag)` pair with an established
Phase-1 unconditional loading, stratify the same lookback window's paired returns by the chosen
regime axis (Section 3) and compute a per-stratum loading with its own HAC-adjusted confidence
interval (reusing `ic_math._fisher_z_ci`/`_hac_sharpe_nd`'s pattern, per Phase 1's F4 precedent).
Divergence is present when two or more strata's confidence intervals do not overlap — i.e., the
measured loadings differ by more than can be explained by estimation noise alone, not merely a
numeric difference in point estimates. A point-estimate difference alone (e.g., 0.35 in one regime
vs 0.28 in another) with overlapping CIs is not divergence under this definition; it is exactly
the kind of noise the unconditional Phase-1 measurement already absorbs correctly.

This test should be run tag-by-tag (not universe-wide) as part of Phase 146's own operation once
Phase 1 has accumulated enough calibration history to stratify meaningfully — it is not a
one-time gate decided in the abstract before any Phase-1 data exists. The natural place to run it
is a periodic (e.g., quarterly) audit query against `instrument_tags`' accumulated history,
joined against `market_regimes`, looking for tags whose per-regime-stratified loadings show
non-overlapping CIs for a material fraction of their holder population. A single instrument
showing divergence does not trigger Phase 2 for the whole tag; the gate is about a tag's general
regime-dependence, evidenced across its holder population, not a single anecdote.

**Phase 2 does not ship in Phase 146.** This document exists so that when the trigger condition is
eventually evaluated and met, the schema/axis/gate decisions are already settled rather than
re-litigated at that time.

## 5. Per-stratum sample-size guard

Conditioning on regime shrinks the sample available to each stratum — the design doc's F6.3
finding states this directly: "conditioning on 9 cross-sectional regimes splits a 252-day lookback
into strata that can drop below 30 observations." (The "9" comes from the design doc's own
illustrative regime count; the actual number of live `regime_group` × label combinations at Phase
2 execution time may differ and should be re-verified rather than assumed.)

**The guard:** each `(symbol, tag, regime)` stratum must independently satisfy the same
minimum-sample-size floor Phase 1 already enforces for the unconditional case —
`alpha.tag_calibrator.min_sample_n` (live APR key, seeded by migration 238 at default 60,
`[initial_estimate]`; see 146-RESEARCH.md's Live Schema State section). A stratum with fewer than
`min_sample_n` paired observations is not measured at all for that regime — it is skipped, the
same way Phase 1 skips a `(symbol, factor_series)` pair with insufficient history today. There is
no separate, lower threshold for regime-conditioned strata; the guard is the same key, applied
per-stratum instead of once per pair. This is a direct extension of an existing gate, not new
machinery — the `min_sample_n` check itself does not change; what changes is that it now runs once
per `(symbol, tag, regime)` combination instead of once per `(symbol, tag)`.

**Hypothesis-count consequence (also F6.3):** stratifying by regime multiplies the number of
statistical tests run per calibration pass by roughly the number of regime states on the chosen
axis (e.g., ~9 in the design doc's illustrative cross-sectional case) — from Phase 1's baseline of
~1,600 `(symbol, tag)` pairs to on the order of ~14,000 `(symbol, tag, regime)` tests. Phase 1's
run-level Benjamini-Hochberg FDR correction (`alpha.tag_calibrator.fdr_alpha`, already live) is
therefore a **hard prerequisite** for Phase 2, not an enhancement to consider adding later — the
same FDR machinery already built for Phase 1 must be applied across the larger Phase-2 hypothesis
family, correcting once per calibration run across every `(symbol, tag, regime)` cell measured
that run, exactly as it already does across every `(symbol, tag)` cell today.

## 6. Non-goals / deferral

This document does not ship code, does not run a migration, and does not change Phase 146's Wave
1/2 schema (migration 238, Plan 02). It exists solely to record the settled design so Phase 146's
Phase-1 schema decisions are made with the extension path documented, per this plan's objective.

**What must be true before Phase 2 is scheduled:**

1. Phase 146 (Phase 1) must ship and run in production long enough to accumulate calibration
   history across at least one full market-regime cycle — a regime-divergence test run against a
   single regime snapshot cannot distinguish real divergence from a transient artifact of whatever
   regime happened to be live during the brief accumulation window.
2. The trigger gate (Section 4) must actually be evaluated against real accumulated
   `instrument_tags`/`market_regimes` data and show non-overlapping-CI divergence for a material
   fraction of at least one tag's holder population — not merely be judged plausible in the
   abstract.
3. The per-stratum sample-size guard (Section 5) must be confirmed still adequate at whatever the
   live universe size and regime-state count are at Phase 2 execution time (the design doc's "9
   regimes" and "~14,000 tests" figures are illustrative, computed against the universe/regime-count
   at design time in 2026-07, and should be re-derived rather than assumed current).
4. Phase 146's own definitional/deprecation decisions (D-06's kept-not-deleted `cycle_position`
   tags — `early_cycle`/`mid_cycle`/`late_cycle`/`recession` — currently shipped as static human
   seed priors) are explicitly **superseded** by Phase 2 once it ships, per the design doc's own
   statement: "Phase 2 regime conditioning — connecting instrument betas to HMM state — is the
   correct long-term implementation and supersedes them." Phase 2's execution plan should include
   retiring or re-deriving those definitional tags from the new regime-conditioned measurement,
   not leaving both systems live in parallel indefinitely.

Per the ROADMAP and this phase's `146-CONTEXT.md` (Deferred Ideas), Phase 2 is explicitly out of
scope for Phase 146's Wave 1-2 code and remains gated on the above, not on a calendar date.
