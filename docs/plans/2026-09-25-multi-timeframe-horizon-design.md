# Multiple timeframes and horizons in the research layer: one clock, one target, measured decay

**Author:** Claude (Opus 5.5), 2026-09-25, at Brandon's request ("why aren't we looking at this
on multiple TF, especially across day event horizons ... design this like Renaissance would").
**Informed by:** independent adversarial review, 2026-09-25, by a fresh-context Claude (Opus)
agent (AGY and Codex were both out of quota); 13 findings, dispositions in section 9.
**Parents:** `docs/plans/2026-09-25-alpha-research-architecture.md` (S0 to S8),
`docs/plans/2026-09-24-evidence-framework.md` (E15 rules).
**Status:** proposed, revision 2 (D6 updated 2026-09-25 for the adopted E16). Build items in section 7 are a follow-on phase after 183 (183 was
planned, 10 plans, before this revision and does not include them). D6 needs an owner
decision (a methodology change to E15's refusal rule).

## 1. The question and the answer

The corpus IC table (ledger section 5, 2026-09-25 disclosure) shows the slow price-position
features predict returns as a function of calendar horizon, not timeframe: 1h at 60 bars matches
1d at 10 bars, 5m and 15m are flat only because their horizon ladders end inside the session,
and IC over the square root of horizon is flat out to 10 days, the longest horizon measured. The
research layer cannot express any of this for intraday inputs, because `panel.forward_returns`
sets an intraday target that crosses a session to NaN.

The tempting fix is a bigger grid: more horizons per timeframe, every feature on every timeframe.
That grid is what produced the Phase 148 failure (selection over thin tf x horizon x regime
cells). This design goes the other way:

- **Horizon is a property of a signal, recorded as its decay, not a dimension to search.**
- **Timeframe is a property of an input, handled by one causal alignment node, not a separate
  test.**
- **Each book has one clock and one target.**

## 2. Why cumulative-horizon IC is the wrong object

The ladder ICs (`h` = 1, 2, 5, 10) are correlations with overlapping cumulative returns: the
h 10 target shares 9 of its 10 days with h 9, and the table's standard errors carry no overlap
correction. For a linear predictor, a flat IC over the square root of h means the same per-day
predictability at every horizon, which a one-session target already carries with no overlap.

The descriptive object is the **IC term structure by lag**, `IC_k = corr(s_t, r_{t+k})` on
one-period residual returns. Its lags are **not** independent estimates: the covariance of the
errors of `IC_k` and `IC_{k+1}` scales with the signal's own autocorrelation, which is about 0.99
for a 52-week feature. The curve of a slow signal is smooth by construction, and a bump at one
range of lags can be a single noise draw. It is read only as a whole curve against a joint band
from the same shift null (D2), never lag by lag.

## 3. Decisions

**D1. One clock and one target per book.**

| Book | Clock | Target (Invariant 1) |
|---|---|---|
| Daily | one row per session | `ln(open[t+2] / open[t+1])`, S1 residual |
| Intraday | session slot grid | next-slot open to open, S1 residual, never crossing a session (unchanged) |

A book's holding period follows from its members' persistence and the construction, not from a
declared target horizon. Multi-day targets are deleted as a design option: they add overlap,
not information.

**D2. The term structure is a record, not a design input on the same vintage.** Every recorded
run emits each member's IC term structure (lags 1 to 60 on the daily clock, one session on the
intraday clock) with a joint band from the run's shift null. It feeds nothing in the run. Using
it on vintage 1 to add, drop or re-parameterize a member is outcome-based selection (framework
section 6); if that is ever done, it is a counted, disclosed re-specification like any other.
Its intended consumers are the confirmation record and, after confirmation, cost-aware
construction.

**D3. Persistence enters through one fixed menu, declared before any data.** A member is the raw
signal or its exponential smoothing at a half-life from a single global menu, {5, 21, 63}
sessions on the daily clock, the same for every family. A family chooses from the menu by its
mechanism's stated time scale in the pre-registration, never from a term structure. A lagged
member (`s_{t-k}`) is admissible only when the mechanism names the delay (for example a
disclosure date). Ridge on the one-session target then weights fast and slow members together.
Turnover-aware construction (Garleanu and Pedersen 2013) is the post-confirmation construction;
E15 defers costs until then.

**D4. Bars come from one source; timeframes meet in one causal alignment node.**

- **One intraday source.** S0 builds 15m and 1h grids by aggregating 5m bars on session-anchored
  edges (09:30, 09:45, ...; 09:30, 10:30, ...). Stored 15m and 1h bars are not read by the
  research layer: IBKR's 1h series has a 09:30 bar on some names and sessions and not others, and
  where present it is a 30-minute partial (review finding 11). 5m history starts in 2006, the same
  as 1h and 15m, so nothing is lost. Daily rows stay the stored 1d bars (official open and close).
  No family has a real-data number yet, so family 1 moves to the derived grids at no cost.
- **`closes_at`.** S0 adds each grid row's bar end, UTC, from the exchange calendar (half days,
  both DST transitions). A grid row no symbol traded (a half day's missing afternoon) gets NaT.
- **The node.**

```
align(alpha_src, src_panel, dst_panel, max_age_rows) -> alpha on dst_panel's grid
for each dst row t and symbol j:
    candidates = src rows with closes_at <= dst.closes_at[t]
    value = alpha_src at the latest candidate row where symbol j's value is finite
    NaN if that row is more than max_age_rows source rows before the latest candidate row
```

- **The invariant it enforces:** every aligned value comes from a source bar that closed no later
  than the destination row's close, and every position enters at the next open, strictly after
  that close. `<=` is therefore causal: on the intraday clock, the session's last slot may carry
  that session's daily value, because its position enters at the next session's open. Every other
  slot carries the previous session's daily value. `max_age_rows` is in source rows (sessions for
  a daily source), never calendar time, so a weekend does not age a value.

**D5. Corpus features are recomputed in the research layer from one implementation.**
`feature_vectors` is not read: it has been stale since 2026-08-10, and its windows come from live
APR, which can drift after a pre-registration. (Revision 1 also said it was computed on the
placeholder calendar grid; that was wrong, production reads `market_data_ohlcv_tradeable`.)

- **A kernel table in `feature_factory.py`:** name -> (pure `_*_series_full` function, inputs,
  window parameters, declared memory). Inputs are price fields or other table entries (ATR feeds
  the distance-from-high kernels), resolved once as a small acyclic graph and tested.
- **Bounded memory only.** A kernel whose value depends on the start of the array is excluded.
  `_vwap_dev_sigma_series_full` uses an expanding `cumsum` from index 0 for both VWAP and its
  deviation spread, so its value depends on where the history starts (production passes 2006
  onward). Family 9's VWAP member is re-specified as a rolling-window kernel (a new feature; the
  corpus IC of the expanding version does not transfer). A recursive kernel (Wilder RSI) declares
  memory as the lag where its impulse response falls below 1e-4 of peak, the `signals.py`
  convention.
- **No filled values.** Kernels return filled values during their own warmup (RSI 50, z-score 0,
  percentile 0.5, partial 52-week windows). `kernel_source` masks output to NaN wherever a symbol
  has fewer present rows than the declared memory, and S0 fetches a warmup prefix of the largest
  member memory before the span start, so the span's first rows are real.
- **Gaps.** A kernel runs over a symbol's present rows (a missing bar is missing, as in the
  corpus). Any window spanning more than a pinned number of missing sessions is NaN; the manifest
  counts both.
- **Pinned windows.** `kernel_source(name, params)` takes window values from the
  pre-registration. The kernels read no APR or global state (verified in review).
- **Parity.** A one-time test compares bounded-memory kernels, after warmup, against
  `feature_vectors` on a sample, to verify reuse fidelity. A test, not a dependency.

**D6. Persistent predictors and the book test: superseded by E16 (adopted 2026-09-25).**
Revision 2 proposed an effective-draw refusal on the shift null. Simulation then showed the shift
null is anti-conservative at the screen bar once a book's autocorrelation time passes about 40
sessions (up to 4x at tau 199), that a sign-flip calibration only halves that, and that the shift
null cannot run a confirmation on the current forward span. E16
(`docs/plans/methodology-change-ledger.md`, built in 9152597eb) replaces it at both stages with a
HAC t on the timing P&L `sum (w - wbar)(r - rbar)`: weights minus their causal expanding mean and
returns minus theirs, per (slot, symbol) on intraday clocks and per symbol on the daily clock.
Demeaning the returns as well as the weights is required: with only the weights demeaned, the
`(w - wbar) * mean-return` term inherits the predictor's persistence, which the HAC lag cannot
see (0.15 rejection at the bar at tau 200 with large fixed effects); with both demeaned, size held
at the bar in every simulated cell. The shift null is a diagnostic only. Family 9 is screenable
under E16, subject to the survivorship and dividend conditions in D8.

**D7. Guards, all synthetic, all before any real-data run.**

1. A planted leak routed through `align` (an intraday signal built from a bar that closes after
   the destination row) must be rejected or produce no edge.
2. A daily signal on the intraday clock equals the previous session's value on every slot except
   the last, which carries the same session's value; checked across a half day and both DST
   transitions.
3. `closes_at` fixtures: half day, both DST transitions, a session with a missing final bar, a
   grid row with NaT.
4. Aggregated 15m and 1h bars equal a direct computation from 5m (open of first, close of last,
   high max, low min, volume sum), and no aggregated bar spans a session boundary.
5. A table entry with an expanding kernel is rejected; a masked kernel emits NaN until its
   declared memory.
6. The book test holds size on synthetic AR(1) predictors across autocorrelation times, at the
   screen bar (the E16 simulations, rerun on the built S8).
7. A synthetic high-yield name with zero alpha and a steady ex-dividend drop produces no family 9
   book edge after dividend adjustment (needs todo 428).
8. `repro_frozen.py` stays bit-identical after every build item: new Panel fields default to
   absent, and no existing path reads them.

**D8. Named biases.**

- **Survivorship.** Slow reversal and 52-week anchoring are the constructions most inflated by a
  present-day universe (delisted losers are missing). The book containing family 9 does not go to
  confirmation without a survivorship bound (todo 376).
- **Dividends (todo 428).** No dividend history exists, and equities are fetched split-adjusted
  but not dividend-adjusted. Ex-dividend drops sit in every daily open-to-open target and in every
  price-level feature, which can manufacture family 9's signal on high-yield names and biases
  family 2's overnight leg. The intraday book is immune (its targets never cross a session).
  Daily-clock books with price-level members do not go to confirmation until 428 lands.

## 4. The DAG

```
S0 snapshot (async, read-only pool): 1d bars; 5m bars -> derived 15m, 1h
      -> Panel(tf): OHLCV + high, low, closes_at, warmup prefix
S2 kernels per tf (pure, per symbol, masked to NaN before declared memory) -> alpha(tf)
S2b align to the book clock (pure, causal)                               -> alpha(book clock)
S3 guards -> S4 neutralize -> S7 ridge, one target -> S8 book test (E16 timing HAC t)
      -> S6 ledger (sole writer)
      \-> term structure with joint null band (record, feeds nothing)
```

One direction, no cycles. S0 is the only node that touches stored bars; S2b is the only node that
sees two clocks.

## 5. Performance

- **I/O is the only async part.** S0 fetches symbols concurrently on the existing read-only pool;
  everything after S0 is synchronous numpy. Deriving 15m and 1h from 5m removes two of three
  intraday fetches.
- **S0's own footprint.** `build_grid` allocates float64 (`snapshot.py`); five fields on a 5m
  panel over 233 names are about 2.4 GB. New intraday fields are float32; existing fields change
  dtype only if `repro_frozen.py` stays bit-identical.
- **Intraday inputs never enter the daily book at intraday size.** A float32 5m member is about
  230 MB; kernels run per symbol and only the aligned daily row is kept.
- **Two corpus kernels are too slow for 5m as written:** `_price_percentile_series_full` makes
  one scipy call per bar and `_high_52w_dist_series_full` is an O(n x w) Python loop. B2 adds
  vectorized equivalents (sliding-window rank and rolling max), parity-tested against the
  originals, and the table points at those.
- **Member stacks are cached by content hash** (snapshot digest, kernel code hash, pinned params),
  memory-mapped from `store`. The S8 null shifts the stack against returns, so no shift recomputes
  a kernel; ridge refits per shift are closed form. Process workers are compute-only; the main
  process alone writes.

## 6. Deletions

- No extension of `alpha.ic.lookahead.*` ladders and no tf x horizon x regime grid in the
  research layer. `feature_ic_scores` stays a disclosure record, never an admission input.
- No reads of `feature_vectors`, stored 15m bars or stored 1h bars from the research layer.
- No multi-day targets and no per-family horizon lists; one fixed smoothing menu instead.
- Family 9's "horizons 1d h 5, 10, 20, 60" is gone (ledger row updated).

## 7. Build items (a follow-on phase after 183)

| # | Item | Depends on |
|---|---|---|
| B1 | S0: `high`, `low`, `closes_at` (NaT on untraded rows), warmup prefix, 15m and 1h derived from 5m; D7 guards 3 and 4 | none |
| B2 | Kernel table (bounded memory, declared inputs, NaN masking, gap rule), `kernel_source`, vectorized percentile and 52-week kernels, rolling VWAP kernel, parity test; D7 guard 5 | B1 |
| B3 | `align` node; D7 guards 1 and 2 | B1 |
| B4 | Term structure with joint shift-null band as a run record | S8 |
| B5 | Fixed smoothing menu on `SignalSource` | B2 |
| B6 | Rerun the E16 size check (slot fixed effects, persistent predictors) on the built S8 with phase 184's aligned and kernel predictors; D7 guard 6 | 183 (E16 built) |
| B7 | `repro_frozen.py` bit-identical after each item (D7 guard 8) | each |

Dividend history (todo 428, D7 guard 7) is outside phase 183 and gates confirmation, not the
screen.

## 8. What would change this design

- If step 0 shows most proposed daily families have `tau` above the D6 threshold, the
  within-cluster permutation null (D6 option 2) moves ahead of new family work, because without it
  the daily clock can only screen fast signals.
- If the B2 parity test finds a bounded-memory kernel diverging from `feature_vectors` after
  warmup, the corpus IC table is also suspect for that feature, recorded in the ledger's section 5.

## 9. Review dispositions (2026-09-25)

| # | Finding | Severity | Disposition |
|---|---|---|---|
| 1 | "Reading the term structure spends nothing" is false if it shapes the next family version | HIGH | Accepted: D2 rewritten (record only; any use is a counted re-specification), D3 uses a fixed menu |
| 2 | Lag ICs of a persistent signal are not near independent | HIGH | Accepted: section 2 corrected; joint band, whole-curve reading only |
| 3 | Consecutive shifts give about n / memory effective draws, so the 600-shift refusal is meaningless for slow members | HIGH | Accepted; the fix went further: proposed E16 replaces the shift null (D6) |
| 4 | Price-only (no dividend) prices can manufacture family 9's signal | HIGH | Accepted, verified (no dividend table; `TRADES` series): D8, todo 428, guard 7 |
| 5 | `_vwap_dev_sigma_series_full` has expanding memory from index 0 | MEDIUM | Accepted, verified: expanding kernels excluded, rolling VWAP kernel |
| 6 | Kernel warmup emits filled values | MEDIUM | Accepted: NaN masking plus warmup prefix |
| 7 | Gap compression understates lookback | MEDIUM | Accepted: pinned max-gap rule, manifest counts |
| 8 | Composed kernels do not fit a flat table | MEDIUM | Accepted: declared inputs resolved as an acyclic graph |
| 9 | `<=` contradicts guard 2 | MEDIUM | Guard was wrong, not the rule: `<=` is causal because entry is the next open; guard 2 corrected and the invariant stated |
| 10 | `align` ambiguous on missing bars, half days, `max_age` units | MEDIUM | Accepted: per-symbol latest finite value, NaT rows, `max_age_rows` in source rows |
| 11 | 1h grid heterogeneous (partial 09:30 bar on some names and sessions) | MEDIUM | Accepted, changed further than the suggested fix: 15m and 1h derived from 5m, stored series not read |
| 12 | Revision 1 said production features use the placeholder grid | LOW | Accepted: corrected in D5 |
| 13 | Memory and speed claims omitted S0 float64 and two slow kernels | LOW | Accepted: section 5 |
