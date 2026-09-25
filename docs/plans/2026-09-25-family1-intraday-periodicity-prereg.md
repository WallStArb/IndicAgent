# Pre-registration: family 1, cross-sectional intraday periodicity

**Author:** Claude (Opus 5.5), 2026-09-25, at Brandon's request (family 1 of
`docs/plans/2026-09-25-alpha-research-architecture.md` section 4).
**Governing rules:** `docs/plans/2026-09-24-evidence-framework.md` version 4
(methodology-change-ledger E15).
**Status:** DRAFT until the AGY review is recorded (section 8), then REGISTERED. No real-data number for any member exists. The first
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

A fifth member tests a weaker, related prior: a name's own residual return in the first half
hour predicts its residual return in the last half hour (the stock-level analogue of Gao, Han,
Li and Zhou 2018, whose documented effect is market-level and is removed by residualization).
Direction +1. Its prior is weaker than the four same-slot members and is recorded as such.

## 2. Data

- **Panel:** 15m bars from `market_data_ohlcv_tradeable`, compute_eligible universe (233
  names), built by `src.intelligence.research.snapshot.build_panel`, 26 slots per session,
  end-exclusive at `alpha.validation.oos_start` (2025-12-24). Names enter when their bars
  start; a missing bar is NaN, never filled.
- **Returns:** S1 residual bar returns (`src.intelligence.research.factors`, vintage-1 spec as
  merged at the time of the run: leave-one-out market, causal price-correlation clusters,
  5 principal components, loadings from past data only). Signals are built from residual bar
  returns, not neutralized after the fact (factors.py's rule for return-built signals).
- **Half-hour slot:** two consecutive 15m bars. Slot j of session d covers bars 2j and 2j+1
  (j = 0..12). Slot residual return = sum of its two bar residual returns; NaN if either bar
  is missing.
- **Scored span:** 2010-01-04 through 2025-12-23. Reported sub-periods: 2010-2014, 2015-2019,
  2020-2025-12-23 (reported, not voted on).

## 3. Members

For the same-slot members, alpha is formed at the last bar before slot j (row t = bar 2j - 1
of session d) from past sessions' slot j residual returns only. Slot 0 (09:30) carries no
same-slot position, because its signal row would sit in the previous session:

| Member | alpha before slot j of session d | Declared memory (sessions of slot history) |
|---|---|---|
| P1 `same_slot_lag1` | slot j residual return on d-1 | 1 |
| P2 `same_slot_mean5` | mean slot j residual return over d-5 .. d-1 | 5 |
| P3 `same_slot_mean20` | mean over d-20 .. d-1 | 20 |
| P4 `same_slot_mean40` | mean over d-40 .. d-1 (the horizon HKS report) | 40 |
| P5 `first_to_last_half_hour` | own residual return in slot 0 (09:30-10:00) of session d, held for slot 12 (15:30-16:00) | 0 (same session) |

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
- **P5:** alpha at row t = bar 23 (15:15), enter at the 15:30 open, exit at the session's final
  close (horizon 2 with the close exit).
- **Construction:** `portfolio.fixed_sign_returns`, direction +1, on the centred rank; a
  dollar-neutral long-short book scaled by each name's volatility, as the evaluator's
  covariance plan provides.
- **Costs:** gross (standing directive). Turnover and the cost band are reported as
  diagnostics. Same-slot members trade every half hour, so the band will be large; that
  binds at the capital step, not here.

## 5. Evidence and the test

- **Evidence records** (diagnostic, gate nothing): each member standalone, through
  `evaluate()` with the whole-session shift null: excess annualized Sharpe over the null
  median, stationary-bootstrap standard error, permutation p, per-period estimates, turnover,
  and the cross-sectional rank-IC series of residualized alpha against the residualized
  target once S5's rank-IC readout exists.
- **Book version 1 (screen test 1 of M = 30 on vintage 1):** all five members, combined by the
  S7 walk-forward ridge (phase 183), tested by S8 at one-sided p < 0.05 / 30 = 0.00167. No
  member is dropped after seeing its record; dropping one would be a new, counted book version.
- **Refusals before any real-data number:** S3 guards on every member (integrity, causality
  probe, memory check); at least 600 admissible whole-session shifts; synthetic V3 power of
  the book at a planted per-slot rank IC of 0.01 of at least 50%. If power is below 50%, the
  run is refused and the result is recorded as "underpowered at IC 0.01", with no real-data
  number produced.
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

Pending: AGY adversarial review of this draft, 2026-09-25.
