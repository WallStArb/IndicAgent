# Multiple timeframes and horizons in the research layer: one clock, one target, measured decay

**Author:** Claude (Opus 5.5), 2026-09-25, at Brandon's request ("why aren't we looking at this
on multiple TF, especially across day event horizons ... design this like Renaissance would").
**Informed by:** independent adversarial review, 2026-09-25, by a fresh-context Claude (Opus)
agent (AGY and Codex were both out of quota); 13 findings, dispositions in section 9.
**Parents:** `docs/plans/2026-09-25-alpha-research-architecture.md` (S0 to S8),
`docs/plans/2026-09-24-evidence-framework.md` (E15 rules).
**Status:** proposed, revision 3 (2026-09-26), aligned with the adopted unified design
(`docs/plans/2026-09-26-unified-research-to-production-design.md`, UD-25 and section 14.7).
Build items in section 7 are roadmap phase 184, after phases 183, 185's derived grid and 186's
kernel registry. D6 is superseded by E16.
**Revision 3 (2026-09-26, todos 435, 436 and 446):** D4's 5m aggregation moves from S0 to the
data layer (phase 185), so features, targets and research read one grid; D5 is rewritten: S0
reads the rebuilt `feature_vectors`, whose one implementation is phase 186's kernel registry;
`panel.forward_returns` is the only target definition and the `forward_returns` table goes; the
term structure is computed by the shrunk ic_engine and disclosed here, feeding nothing (kappa
included, unified design 4.4). B3 alignment is a prerequisite for feature books.

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

Both targets come from one function, `panel.forward_returns`, the only forward-return definition
in the codebase (unified design UD-25). A stored table of forward returns counted N traded bars
rather than N grid rows, so its holding time stretched with illiquidity; it is deleted in phase
186.

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

- **One intraday source, derived in the data layer.** Phase 185's derivation writes 15m and 1h
  bars from 5m on session-anchored edges (09:30, 09:45, ...; 09:30, 10:30, ...); stored IBKR 15m
  and 1h bars become raw observations. Features, targets, S0 and the forward runner then read the
  same grid; deriving inside S0 alone (revision 2) would have left features on the stored grid and
  targets on the derived one. Measured 2026-09-26 (todo 446): stored 15m bars equal aggregated
  5m exactly; stored 1h bars equal aggregated 5m where present, but 39 of 231 names (SPY
  included, every year 2006 to 2025) have no 09:30 to 10:00 bar at all, only a zero-volume 09:00
  placeholder, while the other 192 carry a 30-minute partial 09:30 bar (review finding 11). 5m
  history starts in 2006, the same as 1h and 15m, so nothing is lost. Daily rows stay the stored
  1d bars (official open and close).
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

**D5. Features have one implementation; research reads its output (revision 3).**
Revision 2 recomputed features inside the research layer because `feature_vectors` was stale and
read live APR windows. The unified design removes both reasons: phase 186 rebuilds
`feature_vectors` append-only with provenance (code key per kernel, APR snapshot, input digest),
on the derived grid, from one kernel registry (unified design 14.6 item 1). S0 reads that table;
a pre-registration pins a feature by its provenance, so later APR edits cannot drift it. The
requirements revision 2 placed on research kernels become requirements on the registry, checked
in phase 186:

- **Declared inputs and memory.** Each registry entry declares its inputs (price fields or other
  entries, resolved once as a small acyclic graph), window parameters and memory. A recursive
  kernel (Wilder RSI) declares memory as the lag where its impulse response falls below 1e-4 of
  peak, the `signals.py` convention.
- **Bounded memory only.** A kernel whose value depends on the start of the array is excluded.
  `_vwap_dev_sigma_series_full` uses an expanding `cumsum` from index 0, so its value depends on
  where the history starts; family 9's VWAP member is a new rolling-window kernel (the corpus IC
  of the expanding version does not transfer).
- **No filled values.** Output is NaN until a symbol has the declared memory of present rows
  (today's kernels emit RSI 50, z-score 0, percentile 0.5 and partial 52-week windows during
  warmup). The rebuild writes NaN, and S0 reads a warmup prefix of the largest member memory.
- **Gaps.** A kernel runs over a symbol's present rows; a window spanning more than a pinned
  number of missing sessions is NaN, counted in provenance.
- **Parity.** Bounded-memory kernels, after warmup, match the old `feature_vectors` on a sample
  before the swap, verifying the refactor changed no output.

Phase 184 adds only what research needs on top: the new kernels as registry entries (vectorized
percentile and 52-week, rolling VWAP) and the `kernel_source` adapter for members computed on a
panel at pinned windows that the table does not carry.

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
4. Derived 15m and 1h bars equal a direct computation from 5m (open of first, close of last,
   high max, low min, volume sum), and no derived bar spans a session boundary (a phase 185
   derivation test).
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
data layer (phase 185): 5m bars -> derived 15m, 1h bars; feature (phase 186): registry -> feature_vectors
S0 snapshot (async, read-only pool): 1d, 5m, 15m, 1h bars and feature_vectors
      -> Panel(tf): OHLCV + high, low, closes_at, warmup prefix
S1 target: panel.forward_returns (the only definition)
S2 members per tf: feature_vectors columns, or kernel_source at pinned windows -> alpha(tf)
S2b align to the book clock (pure, causal)                               -> alpha(book clock)
S3 guards -> S4 neutralize -> S7 ridge, one target -> S8 book test (E16 timing HAC t)
      -> S6 ledger (sole writer)
      \-> term structure with joint null band (record, feeds nothing)
```

One direction, no cycles. S0 is the only research node that reads stored data; S2b is the only
node that sees two clocks.

## 5. Performance

- **I/O is the only async part.** S0 fetches symbols concurrently on the existing read-only pool;
  everything after S0 is synchronous numpy. Targets are computed, not fetched: all four 5m
  horizons on 91M cells take about 5 s on one core, against 61 s to read them from a stored
  table (measured 2026-09-26).
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
- No reads of stored IBKR 15m or 1h bars by any consumer once phase 185 derives them; no stored
  `forward_returns` table (unified design 14.7).
- No multi-day targets and no per-family horizon lists; one fixed smoothing menu instead.
- Family 9's "horizons 1d h 5, 10, 20, 60" is gone (ledger row updated).

## 7. Build items (roadmap phase 184)

| # | Item | Depends on |
|---|---|---|
| B1 | S0: `high`, `low`, `closes_at` (NaT on untraded rows), warmup prefix, reading the derived 15m and 1h bars; D7 guard 3 | phase 185 derived grid |
| B2 | New registry entries (vectorized percentile and 52-week, rolling VWAP) and `kernel_source` on phase 186's registry; D7 guard 5 | phase 186 registry |
| B3 | `align` node; D7 guards 1 and 2 | B1 |
| B4 | Disclose the IC term structure the shrunk ic_engine computes (with the run's joint shift-null band) as a run record; feeds nothing | S8, phase 186 ic_engine |
| B5 | Fixed smoothing menu on `SignalSource` | B2 |
| B6 | Rerun the E16 size check (slot fixed effects, persistent predictors) on the built S8 with aligned and registry predictors; D7 guard 6 | 183 (E16 built) |
| B7 | `repro_frozen.py` bit-identical after each item (D7 guard 8) | each |

D7 guard 4 belongs to phase 185's derivation. Dividend history (todo 428, D7 guard 7) gates
confirmation of daily books with price-level members, not the screen.

## 8. What would change this design

- If step 0 shows most proposed daily families have `tau` above the D6 threshold, the
  within-cluster permutation null (D6 option 2) moves ahead of new family work, because without it
  the daily clock can only screen fast signals.
- If phase 186's registry parity test finds a bounded-memory kernel diverging from the old
  `feature_vectors` after warmup, the corpus IC table is also suspect for that feature, recorded
  in the ledger's section 5.

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
