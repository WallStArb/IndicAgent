# Multiple timeframes and horizons in the research layer: one clock, one target, measured decay

**Author:** Claude (Opus 5.5), 2026-09-25, at Brandon's request ("why aren't we looking at this
on multiple TF, especially across day event horizons ... design this like Renaissance would").
**Parents:** `docs/plans/2026-09-25-alpha-research-architecture.md` (S0 to S8),
`docs/plans/2026-09-24-evidence-framework.md` (E15 rules).
**Status:** proposed. Build items in section 7 extend phase 183.

## 1. The question and the answer

The corpus IC table (ledger section 5, 2026-09-25 disclosure) shows the slow price-position
features predict returns as a function of calendar horizon, not timeframe: 1h at 60 bars matches
1d at 10 bars, 5m and 15m are flat only because their horizon ladders end inside the session,
and IC over the square root of horizon is flat out to 10 days, the longest horizon measured. The
research layer cannot express any of this for intraday inputs, because `panel.forward_returns`
sets an intraday target that crosses a session to NaN.

The tempting fix is a bigger grid: more horizons per timeframe, every feature on every timeframe.
That grid is what produced the Phase 148 failure (selection over thin tf x horizon x regime
cells). The design here goes the other way:

- **Horizon is a property of a signal, measured once as its decay, not a dimension to search.**
- **Timeframe is a property of an input, handled by one causal alignment node, not a separate
  test.**
- **Each book has one clock and one target.**

## 2. Why cumulative-horizon IC is the wrong object

The ladder ICs (`h` = 1, 2, 5, 10) are correlations with overlapping cumulative returns. The
h 10 target shares 9 of its 10 days with the h 9 target, so a ladder of cumulative ICs repeats
the same information several times, and its standard errors need overlap corrections the table
never applied. For a linear predictor, a flat IC over the square root of h means the same
per-day predictability at every horizon, which a one-session target already captures with no
overlap.

The object that carries information is the **IC term structure by lag**:
`IC_k = corr(s_t, r_{t+k})` for single-period residual returns, k = 1 .. K. Each lag's target
is one period, the lags are close to independent (residual returns have little serial
correlation), and the curve shows directly whether an effect is immediate, persistent, delayed,
or reverses. A signal that predicts days 20 to 60 but not days 1 to 10 appears as a bump at those
lags; a cumulative ladder blurs it.

## 3. Decisions

**D1. One clock and one target per book.** Two book types, one each:

| Book | Clock | Target (Invariant 1) |
|---|---|---|
| Daily | one row per session | `ln(open[t+2] / open[t+1])`, S1 residual |
| Intraday | session slot grid | next-slot open to open, S1 residual, never crossing a session (unchanged) |

A book's holding period follows from its members' decay and the construction, not from a
declared target horizon. Multi-day targets are deleted as a design option: they add overlap,
not information.

**D2. Decay is measured, never searched.** Every recorded run emits each member's IC term
structure (lags 1 to 60 on the daily clock, 1 to one session on the intraday clock) as a
diagnostic sink. It does not feed admission, weights or the book test, so reading it spends
nothing. It is the evidence for D3 declarations in the next family version.

**D3. Persistent or delayed effects enter as declared transforms.** A member may be declared
as the raw signal, a lag (`s_{t-k}`), or an exponential smoothing at a stated half-life, each
fixed in the pre-registration with its prior. Ridge on the one-session target then weights
fast and slow members together. Turnover-aware construction (Garleanu and Pedersen 2013: trade
toward an aim portfolio weighted by each signal's decay rate) is the right construction once
costs are sized, which E15 defers until after confirmation; it is recorded here so the term
structure from D2 is already the input it needs.

**D4. Timeframes meet through one causal alignment node.** S0 adds `closes_at` to the Panel:
each row's bar end, UTC, from the exchange calendar (half days and DST included). A new pure
node:

```
align(alpha_src, src_panel, dst_panel, max_age) -> alpha on dst_panel's grid
value at dst row t = alpha_src at the last src row with closes_at <= dst.closes_at[t]
NaN when that row is older than max_age or missing (never filled past max_age)
```

Decision time is the destination row's close; entry is the next open (S5 unchanged). This rule
covers every direction: an intraday signal sampled onto the daily clock takes the session's last
completed bar; a daily signal on the intraday clock takes the previous session's value, because
today's daily bar does not close until the session ends. The node is the only place timeframes
mix, so the only place a cross-timeframe lookahead can enter, so it carries the guards (D7).

**D5. Corpus features are recomputed in the research layer, never read from `feature_vectors`.**
`feature_vectors` has a separate lineage (FeatureFactory code version, live APR windows, the
calendar grid with placeholder bars) and has been stale since 2026-08-10. Instead:

- `feature_factory.py` exposes a public kernel table: name -> (pure `_*_series_full` function,
  required price fields, window parameters, declared memory). One implementation serves the
  production corpus and the research layer.
- A `kernel_source(name, params)` adapter builds a `SignalSource` from a kernel, with the
  window values pinned in the pre-registration (not read from live APR, which can drift).
- S0's Panel adds `high` and `low`, which most kernels need.
- A kernel runs per symbol over that symbol's present rows (a missing bar is missing, as the
  corpus treats it) and scatters back to the grid; the manifest counts gaps.
- A one-time parity test compares kernel output on the panel against `feature_vectors` for a
  sample of symbols and dates, to verify reuse fidelity. It is a test, not a dependency.

**D6. Memory is declared and charged.** A member's memory is its kernel lookback plus any lag or
smoothing span (252 sessions for the 52-week features). S8 already refuses a book with fewer
than 600 admissible shifts; long-memory members reduce the admissible count, so a family with
52-week members states its expected shift count in the pre-registration.

**D7. Guards, all synthetic, all before any real-data run.**

1. A planted leak routed through `align` (an intraday signal built from the current session's
   close, aligned to the daily clock with the wrong decision time) must be detected: the
   canary's IC through the join is near 1 unless the rule is correct, so the test asserts the
   correct rule gives the canary no edge.
2. A daily signal on the intraday clock must equal the previous session's value on every slot,
   including the first slot after a half day.
3. `closes_at` fixtures for a half day, both DST transitions, and a session with a missing
   final bar.
4. A planted delayed effect (true signal at lag 20 only) must show in the D2 term structure at
   lag 20 and be recovered by a declared lag-20 member at the family's synthetic power.
5. `repro_frozen.py` stays bit-identical: the new Panel fields default to absent, and no
   existing path reads them.

**D8. Survivorship is named for the family most exposed.** Slow reversal and 52-week anchoring
are the constructions most inflated by a present-day universe: losers that later delisted are
missing, so "buy the losers" looks better than it was. Family 9's pre-registration records this,
and the book containing it does not go to confirmation without a survivorship bound (todo 376).

## 4. The DAG

```
S0 snapshot, one per tf (async, read-only pool)       -> Panel(tf): OHLCV + high, low, closes_at
S2 kernels, per tf (pure, per symbol)                 -> alpha(tf)
S2b align to the book clock (pure, causal)            -> alpha(book clock)
S3 guards -> S4 neutralize -> S7 ridge, one target -> S8 book test -> S6 ledger (sole writer)
                                   \-> D2 term structure (diagnostic sink, feeds nothing)
```

One direction, no cycles. S2b is the only node that sees two clocks. The term structure is a
sink, so it cannot select.

## 5. Performance

- **I/O is the only async part.** S0 fetches all timeframes and symbols concurrently on the
  existing read-only pool (bounded by pool size). Everything after S0 is synchronous numpy.
- **Intraday inputs never enter the daily book at intraday size.** A 5m panel over 233 names
  and about 13 years is roughly 250,000 rows; one float32 member is about 230 MB. Kernels run
  per symbol on the intraday panel and only the aligned daily row is kept, so a daily book holds
  about 3,300 x 233 per member regardless of the input timeframe.
- **Member stacks are cached by content hash** (snapshot digest, kernel code hash, pinned
  params) in `store`, float32, memory-mapped. The S8 null shifts the stack against returns, so
  no shift recomputes a kernel; ridge refits per shift are closed form.
- **Shift loop parallelism** follows the project rule: process workers are compute-only and
  return results; the main process alone writes.

## 6. Deletions

- No extension of `alpha.ic.lookahead.*` ladders and no tf x horizon x regime grid in the
  research layer. The legacy `feature_ic_scores` table stays a disclosure record, never an
  admission input.
- No reads of `feature_vectors` from the research layer.
- Family 9's "horizons 1d h 5, 10, 20, 60" is replaced by: daily clock, one-session target,
  term structure to lag 60, declared smoothing members.

## 7. Build items (phase 183 follow-on)

| # | Item | Depends on |
|---|---|---|
| B1 | Panel `high`, `low`, `closes_at`; S0 reads them; calendar-derived bar ends | none |
| B2 | Public kernel table in `feature_factory.py`, `kernel_source` adapter, parity test | B1 |
| B3 | `align` node with D7 guards 1 to 3 | B1 |
| B4 | Term-structure diagnostic sink in the recorded run | S8 |
| B5 | Declared lag and smoothing transforms on `SignalSource`, D7 guard 4 | B2 |
| B6 | `repro_frozen.py` bit-identity after each of B1 to B5 | each |

## 8. What would change this design

- If D2 term structures show most member information at lags beyond 20 sessions, a separate
  weekly-clock book becomes worth its screen test (fewer rows, less turnover); until then the
  daily clock carries it through declared smoothing.
- If the parity test in B2 finds kernel output diverging from `feature_vectors`, the corpus IC
  table (already only a disclosure) is also suspect for the diverging features, and the
  divergence is recorded in the ledger's section 5.
