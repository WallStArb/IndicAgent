# Implied Borrow Cost from Listed Derivatives — Idea

**Status:** Idea — not planned. Needs a Fable rigor pass before promotion to `docs/research/`.
**Author:** Claude (Sonnet 5), interactive session, 2026-08-07 — not a Fable dispatch. The
"what already exists" section below was verified live against the repo/DB this session; the
options-pricing mechanics are standard derivatives theory, not independently re-derived or
backtested here.
**Origin:** User idea, stated directly in conversation: extract the market-implied stock
borrow/financing rate from listed option prices, as a new signal source orthogonal to
everything currently computed from price/volume bars.

---

## The hypothesis

Options markets embed information about stock financing costs that isn't recoverable from
price/volume data alone. Two complementary extraction methods, different robustness/cost
tradeoffs:

1. **Box spread + conversion/reversal (primary, model-free).** A box spread (long call K1 /
   short call K2 / short put K1 / long put K2) has a fixed payoff at expiry regardless of where
   the stock settles — its market price directly implies a clean risk-free/repo rate, with no
   stock leg, so no borrow cost embedded. A conversion or reversal (stock + opposite options at
   one strike) *does* require an actual stock leg — the reversal (short stock + long call +
   short put) is a synthetic long risk-free bond whose implied rate embeds the risk-free rate
   **plus** the cost of borrowing the stock, since executing it actually requires shorting.
   `reversal_rate − box_rate ≈ implied_borrow_cost`. Pure put-call-parity arithmetic — no
   Black-Scholes, no IV inversion, no options-pricing library needed for this leg.
2. **Deep ITM put richness (secondary, confirming/fallback, model-dependent).** A dealer short
   a deep ITM put (delta near −1) hedges by shorting stock, so anticipated borrow cost over the
   option's life gets priced into the put premium — deep ITM calls don't have this (delta near
   +1 hedges via long stock, no borrow needed), so this is put-specific. **Complication:**
   deep ITM American puts also carry a real early-exercise discount driven by the risk-free
   rate (financing the strike proceeds), which pulls the *opposite* direction and has nothing to
   do with borrow. Disentangling the two requires a pricing-model baseline (at minimum a
   binomial tree or Black-Scholes-plus-early-exercise-correction) to compare the put's actual
   market price against — this leg is NOT model-free the way the box/reversal identity is.
   Best used as a cross-check where it agrees with the box/reversal estimate, or as a fallback
   where a clean box isn't available (wide/illiquid markets on a specific name).

---

## What already exists (verified live this session — there is currently nothing)

- **No options asset class at all.** `instruments.contract_details->>'asset_class'` has exactly
  3 live values: `equity`, `futures`, `fx` (checked via direct query 2026-08-07). No options
  contracts are tracked anywhere in the schema.
- **No options-pricing library in the dependency stack.** `requirements.txt`'s math stack is
  `numpy`/`pandas`/`scipy`/`statsmodels`/`hmmlearn`/`numba`/`scikit-learn`/
  `pandas-market-calendars` — a repo-wide grep for Black-Scholes/implied-vol/greeks/
  `py_vollib`/`QuantLib` returns zero hits. Nothing to reuse or conflict with.
- **IBKR already supports options data** via the same `ib_async` path this codebase already
  uses for equities/futures/fx (`src/providers/ibkr.py` — per the Ring rule, any new options
  provider logic belongs here too, not a new file). Chain discovery
  (`reqSecDefOptParams`)/quotes (`reqMktData`) are standard `ib_async` calls, not a new
  integration pattern.
- **Phase 146's tag calibrator** (`TagCalibrator`, `instrument_tags.loading`/`p_value`/`source`,
  closed 2026-07-17) is the closest existing analog — it already turns a market-derived,
  statistically-gated measurement into a per-symbol time-varying value with expiry
  (`half_life_days`, `valid_from`/`valid_to`). Worth deciding against this precedent whether
  implied borrow cost fits that same shape or needs its own path (see Open Questions).

**Nothing needs to be reused or worked around — this is a clean net-new build**, which also
means there's no existing infrastructure accidentally biasing the design toward a shape that
doesn't fit the actual problem.

---

## Why this doesn't need what "bring in options data" generally would

A full options integration (IV surface, full greeks, chain-wide backfill) is a much bigger
build than this idea actually requires. The primary extraction method (box + reversal) needs
only a handful of near-the-money, near-term-expiry quotes per underlying per day — a thin,
targeted `options_quotes`-shaped table (symbol, expiry, strike, right, bid, ask, timestamp),
not a full chain history. No pricing library is required for the primary signal; one is only
needed if the secondary ITM-put cross-check is built.

---

## Known risks / data-quality concerns (this project's existing rigor bar applies directly)

- **Quote staleness/width.** Same class of problem `market_data_ohlcv`'s synthetic-fill rows
  already taught this codebase to distrust — illiquid strikes/names will have wide, stale
  quotes. Needs the same discipline already applied elsewhere: restrict to near-the-money,
  near-term expiries with tight bid-ask spreads and real open interest, not "as-quoted."
- **American exercise / dividends.** Box spreads structurally cancel most of this (all 4 legs
  held together); naive per-strike put-call parity or a bare conversion/reversal does not — the
  box+reversal combination is deliberately chosen for this reason, not just convenience.
- **Universe coverage will be uneven.** Commodity ETFs and large single-names (many of the
  recent universe-expansion additions — `COP`/`CVX`/`BHP`/`ADM`/etc.) have deep options
  markets; some thinner FX/niche-tag names in the current 231-symbol universe likely don't.
  Coverage needs to be measured, not assumed, before committing to a universe scope.
- **Time-varying, not slowly-decaying.** Unlike Phase 146's factor betas (180-day half-life,
  genuinely slow-moving characteristics), borrow cost can spike sharply on short-squeeze
  dynamics — a calibrator shaped like `TagCalibrator`'s nightly-batch-with-long-half-life
  pattern may be the wrong cadence/decay model for this specific signal (see Open Questions).

---

## Open questions for Fable

1. **Where does this live architecturally** — a new Feature Factory primitive (fast-moving,
   computed per compute cycle, fits the borrow-cost-can-spike-daily behavior) or an extension
   of the `TagCalibrator`/`instrument_tags` system (matches the "market-derived, statistically
   gated, expiring measurement" shape, but its 180-day-half-life design target may be wrong for
   something that can move day-to-day)? These have different persistence/DAG implications.
2. **Universe scope.** Which of the current 231 instruments have options liquid enough (tight
   markets, real OI) to produce a trustworthy estimate? Needs to be measured against real IBKR
   chain data before committing to "all instruments" or a curated subset.
3. **Minimum viable build.** Is the box+reversal method alone (no pricing model, purely
   algebraic) sufficient to ship a first version, with the ITM-put cross-check deferred as a
   phase 2 refinement once a pricing-model baseline is independently justified?
4. **Table/schema shape.** New `options_quotes`-style table vs. some other persistence shape —
   needs a real schema decision informed by exactly which strikes/expiries/fields the box and
   reversal constructions require, not overbuilt to hold a full chain nobody's using yet.
5. **What is this signal actually for?** Candidate downstream uses to evaluate: (a) a
   standalone feature tested for IC like any other Feature Factory primitive; (b) a
   `StratificationDimension` candidate (financing/borrow-cost regime) per
   `docs/research/stratification-dimension-unification.md`'s contract — worth checking that
   doc's candidate table before designing a new dimension shape from scratch; (c) a risk/data-
   quality input rather than an alpha signal per se (e.g., flagging names where short-side
   trade construction is unreliable). These have different success criteria.
6. **Priority relative to the current strategic plan.** The project is currently in a
   back-to-discovery posture on 5 already-scoped Signal-Extraction candidates
   (`cointegrated_pairs_residual`, `statistical_factor_residual`, `cross_asset_lead_lag`,
   `adaptive_combiner_weights`, `jump_diffusion_decomposition`) after Phase 167's construction
   FAILED re-verification. This idea is a genuinely new data domain, not a variant of any of
   those five — does it compete for the same discovery-track priority, or is it independent
   enough (new data source rather than new math on existing data) to run in parallel?

---

## References

- `src/providers/ibkr.py` — sole home for any new options provider logic (Ring rule)
- `.planning/phases/146-empirical-instrument-tag-calibrator/` — closest existing
  analog for a market-derived, statistically-gated, expiring per-symbol measurement
  (`TagCalibrator`, `instrument_tags.loading`/`p_value`/`valid_from`/`valid_to`)
- `docs/research/stratification-dimension-unification.md` — candidate-dimension contract to
  check before treating this as a new regime/stratification axis
- `.planning/STATE.md` — current strategic plan (back-to-discovery on the 5 Signal-Extraction
  candidates), the priority context question 6 above refers to
