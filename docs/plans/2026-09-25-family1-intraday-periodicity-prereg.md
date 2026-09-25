# Pre-registration: family 1, cross-sectional intraday periodicity

**Author:** Claude (Opus 5.5), 2026-09-25, at Brandon's request (family 1 of
`docs/plans/2026-09-25-alpha-research-architecture.md` section 4).
**Governing rules:** `docs/plans/2026-09-24-evidence-framework.md` version 4
(methodology-change-ledger E15).
**Status:** REGISTERED 2026-09-25 after the AGY review (section 8). No real-data number exists.
The first real-data run waits for phase 183 (runner, ledger, combiner, book test) and for the
three build requirements in section 9. No real-data number for any member exists. The first
real-data run waits for phase 183's runner and ledger; the runner's machine spec must
reproduce every number pinned here, and a mismatch is a methodology change.

## 1. Hypothesis and mechanism

Heston, Korajczyk and Sadka (2010, Journal of Finance): a stock's return in a given half-hour
of the trading day predicts its return in the same half-hour on following days, relative to
other stocks, at lags of 1 to about 40 trading days. The proposed mechanism is recurring
institutional order flow: funds that split large orders trade at the same time of day across
days, so the price pressure recurs by slot. The effect is measured relative to other stocks,
which is why it fits a factor-residualized book; whether it survives this project's S1
residualization is part of what is being tested.

Direction for every same-slot member: continuation (+1). A name whose residual return in slot
s was high on recent days is expected to have a high residual return in slot s today.

The first-half-hour to last-half-hour idea (the stock-level analogue of Gao, Han, Li and Zhou
2018) was in the draft as a fifth member. It is a different mechanism (same-session momentum,
not multi-day periodicity) and trades one slot a day, so it is not a member of this family; it
will be registered as its own family.

## 2. Data

- **Panel:** 15m bars from `market_data_ohlcv_tradeable`, compute_eligible universe (233
  names), built by `src.intelligence.research.snapshot.build_panel`, 26 slots per session,
  end-exclusive at `alpha.validation.oos_start` (2025-12-24). Names enter when their bars
  start; a missing bar is NaN, never filled.
- **Returns:** S1 residual bar returns (`src.intelligence.research.factors`, vintage-1 spec as
  merged at the time of the run: leave-one-out market, causal price-correlation clusters,
  5 principal components, loadings from past data only). On intraday panels the market loading
  is estimated per slot (26 loadings per name, each from that slot's trailing 252 sessions),
  because market beta varies by time of day: a pooled beta leaves a slot-specific market
  exposure in every residual, and if the market's own slot returns recur across days, that
  exposure would pass for cross-sectional same-slot persistence (requirement R3). Signals are built from residual bar
  returns, not neutralized after the fact (factors.py's rule for return-built signals).
- **Half-hour slot:** two consecutive 15m bars. Slot j of session d covers bars 2j and 2j+1
  (j = 0..12). Slot residual return = sum of its two bar residual returns; NaN if either bar
  is missing.
- **Scored span:** 2010-01-04 through 2025-12-23. Reported sub-periods: 2010-2014, 2015-2019,
  2020-2025-12-23 (reported, not voted on).

## 3. Members

For every member, alpha for slot j of session d is formed at the last bar before the slot
(row t = bar 2j - 1 of session d; for slot 0, the previous session's last bar, entering at the
09:30 open) from past sessions' slot j residual returns only. All 13 slots trade, including the
opening slot, which carries the largest volume and the strongest effect in HKS:

| Member | alpha before slot j of session d | Declared memory (sessions of slot history) |
|---|---|---|
| P1 `same_slot_lag1` | slot j residual return on d-1 | 1 |
| P2 `same_slot_mean5` | mean slot j residual return over d-5 .. d-1 | 5 |
| P3 `same_slot_mean20` | mean over d-20 .. d-1 | 20 |
| P4 `same_slot_mean40` | mean over d-40 .. d-1 (the horizon HKS report) | 40 |

- Means require at least half the window's days finite; otherwise NaN.
- **Cross-sectional form:** at each row, alpha is converted to a centred rank,
  `rank / (n_valid - 1) - 0.5` over names with finite alpha; rows with fewer than 20 finite
  names carry no position (coverage floor).
- **Declared memory in rows** (what the null and the S3 memory check use) = slot history
  (sessions x 26) + S1's loading reach (252-session window plus one 21-session refit block)
  x 26, rounded up to whole sessions by the evaluator.
- A member whose declared memory fails the S3 memory check fails the family registration
  loudly; it is not re-declared after seeing the check.

## 4. Target and construction

- **Same-slot members:** enter at the open of slot j's first bar (row t + 1), exit at the open
  of the following slot (horizon 2 bars); slot 12 exits at the session's final close (the
  market-on-close exit in `panel.forward_returns(..., closes=...)`). No target crosses the
  overnight gap. Target is the S1 residual of that forward return (lag = fwd_span(horizon)).
- **Construction (requirement R1):** weights proportional to centred rank divided by each
  name's volatility; the positive weights are scaled to sum to +0.5 and the negative weights to
  -0.5, so every slot's book is exactly dollar-neutral whatever the volatility mix. Direction
  +1. The existing `fixed_sign_returns` is not used: it keeps only the sign of alpha and, after
  volatility scaling, is not dollar-neutral.
- **Scoring unit (requirement R2):** the book's P&L is summed over each session's 13 slots and
  scored as a daily series (annualized with 252), for the observed book and for every shifted
  copy alike. Daily is the unit the confirmation test and capital use, and it absorbs intraday
  autocorrelation between slots.
- **Costs:** gross (standing directive). Turnover and the cost band are reported as
  diagnostics. Same-slot members trade every half hour, so the band will be large; that
  binds at the capital step, not here.

## 5. Evidence and the test

- **Evidence records** (diagnostic, gate nothing): each member standalone, with the R1
  construction and R2 scoring, through
  `evaluate()` with the whole-session shift null: excess annualized Sharpe over the null
  median, stationary-bootstrap standard error, permutation p, per-period estimates, turnover,
  and the cross-sectional rank-IC series of residualized alpha against the residualized
  target once S5's rank-IC readout exists.
- **Book version 1 (screen test 1 of M = 30 on vintage 1):** all four members, combined by the
  S7 walk-forward ridge (phase 183), tested by S8 at one-sided p < 0.05 / 30 = 0.00167. No
  member is dropped after seeing its record; dropping one would be a new, counted book version.
- **Refusals before any real-data number:** S3 guards on every member (integrity, causality
  probe, memory check); at least 600 admissible whole-session shifts; synthetic V3 power of
  the book at a planted per-slot rank IC of 0.002 of at least 50%. An IC of 0.01 would imply an
  annualized IR near 4 on this breadth (0.01 x sqrt(13 slots x 252 days x about 60 independent
  names)), not a realistic effect for 30-minute residual returns on large caps; 0.002 implies
  about 0.9. If power is below 50%, the run is refused and recorded as "underpowered at IC
  0.002", with no real-data number produced.
- **If book version 1 clears the screen,** it is frozen and its confirmation date on the
  forward span is fixed at freeze by the power rule (evidence framework section 7).

## 6. Disclosed prior looks at this data

- Step 0 of the architecture (`docs/research/measurement-residual-breadth.md`) measured the
  cross-sectional correlation structure of 15m residual bar returns (breadth). It did not
  measure any serial or same-slot relationship, or any return predicted by a signal.
- The S1 cluster rule was chosen on 1d residual correlation structure (indicagent-63,
  2026-09-25), again with no signal or target involved.
- No other study on this project has looked at intraday same-slot returns or first-to-last
  half-hour returns on this data.

## 7. Known risks, stated before the run

- **Bid-ask bounce:** entry at the next bar's open, not the signal bar's close, removes the
  mechanical bounce between the signal and the entry price.
- **Survivorship (todo 376):** the universe is present-day. Periodicity is a flow effect, not a
  drift, so it is less exposed than momentum or reversal, but it is not immune.
- **Near-duplicate names** (IYT/XTN, IEF/SHY and others) stay correlated after S1; a same-slot
  signal on both counts one bet twice. The null keeps cross-name structure, so p-values stay
  valid; breadth is overstated.
- **Early-period coverage:** about 160 names carry 15m bars in 2010; the count grows to 233.
  Coverage per row is reported with every record.

## 8. Review record

AGY adversarial review of the draft, 2026-09-25 (commit 80eeb7767). Adopted: slot 0 was
dropped by an indexing choice, not a timing constraint, and HKS find the opening slot strongest
(now traded, entered at the open from the prior session's last bar); the sign-only,
volatility-scaled construction was neither magnitude-aware nor dollar-neutral (now R1); the
planted power IC of 0.01 implied an IR near 4 and would have made the power gate vacuous (now
0.002); the first-to-last half-hour member is a different mechanism and a one-slot signal (now
its own future family); a pooled intraday market beta leaks slot-specific market exposure (now
R3; AGY rated it LOW, but it is load-bearing here because slot-specific market exposure recurs
by slot). Partly adopted: zero-return rows distorting the Sharpe. The distortion is small (zeros
scale mean and standard deviation together, and the null carries the same zeros), but daily
scoring is cleaner and matches the confirmation unit, so R2 adopts it for that reason.

## 9. Build requirements before the first real-data run

- **R1** rank-weighted, leg-normalized, dollar-neutral construction in
  `src/intelligence/research/portfolio.py`.
- **R2** session-aggregated scoring in `evaluate()`: per-row construction P&L summed per
  session before the Sharpe, for observed and null alike.
- **R3** per-slot market loading in S1 for intraday panels.
- Phase 183's runner, ledger, combiner and book test.
