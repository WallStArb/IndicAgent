# Participation state and style spreads - Idea

**Status:** Idea, not registered. Two parts with different vehicles; neither is a family on the
S1 residual target (section 2 says why). No real-data number has been computed for either.
**Author:** Claude (Opus 5.5), interactive session, 2026-09-25. Instrument coverage and S1's
factor set verified live this session; literature citations from memory, not re-read.
**Origin:** Owner idea, 2026-09-25: compare equal-weight and cap-weight index ETFs, keep a few
ratios, and use them as momentum features or market regimes; trade relationships or specific
names when participation is broad or narrow.

## 1. The spreads

All legs are already in the universe with daily bars (`market_data_ohlcv_tradeable`, 1d):

| Spread | Reads | Daily history |
|---|---|---|
| RSP / SPY | Mega-cap concentration (equal minus cap weight) | 2006-06 |
| IWM / SPY | Size | 2006-06 |
| VTV / VUG | Value minus growth | 2006-06 |
| SPHB / USMV | Risk appetite (high beta minus low volatility) | 2011-05 |
| MTUM / SPY | Momentum factor | 2013-04 |
| QUAL / SPY | Quality | 2013-07 |

QQEW / QQQ (concentration inside NDX) would need QQEW onboarded; not needed for a first test.
An equal-weight R1K ETF adds nothing over RSP, and no liquid equal-weight R2K ETF exists.

Prices are split-adjusted, not dividend-adjusted (todo 428). The legs' yields differ by a
fraction of a percent a year, which is noise against a quarter-long trend but is disclosed.

## 2. Why this is not a family on the S1 target

S1 (`src/intelligence/research/factors.py`, `VINTAGE_1`) residualizes every target against the
market, a leave-one-out cluster mean and 5 principal components fitted on the trailing 252
sessions. Size, value/growth, beta and concentration are among the largest common return
components in a 233-name panel of ETFs and large caps, so the 5 PCs almost certainly span them.
A member that predicts which style wins (a name's spread loading times the spread's trend)
predicts the part of the return S1 removes, and scores near zero by construction. This is the
same reason the market-level intraday momentum form is not a family 1 member.

Two things survive that, and they are the two parts below.

## 3. Part A: participation state as a combiner regime (the owner's main idea)

Question: do the registered residual signals (momentum, reversal, periodicity, ...) behave
differently when market participation is broad versus narrow? Participation does not need to
be predictable itself; it only conditions how much weight each signal deserves.

Vehicle: the "regime-conditioned combiner" already listed in the ledger (section 3), with
participation as its regime variable. A combiner variant is a new book version, so it costs
one screen test of the M = 30 vintage 1 budget and needs a base book (S7) to exist first.

Proposed pre-registration, one variant, no sweep:

- **State.** `c_t` = 63-session log return of RSP minus that of SPY, read at the close of t,
  applied from the open of t+1. The conditioning input is `z_t` = the percentile rank of `c_t`
  within its own trailing 252 sessions, minus 0.5 (range -0.5 to +0.5, negative = narrowing).
  Continuous, not a median split: a split discards the distance from the threshold and adds a
  cut point someone chose; a trailing rank has no free threshold, is bounded against outliers,
  and is causal. 63 sessions is one quarter, declared, never swept. First usable value about
  2007-09, before the 2010 scored span.
- **Combiner inputs.** Every registered member `s` enters as `s` and `s x z_t`; ridge,
  walk-forward as in S7, sets both weights. This parametrization matters: ridge shrinks the
  interaction weight toward zero, which is "participation does not matter", the correct null.
  The alternative (`s x 1{broad}` and `s x 1{narrow}`) would shrink both halves toward zero and
  bias the book toward no position in either state. Nothing else changes against the base book.
- **Diagnostic arm.** The same variant with the state series circularly shifted (E16: the shift
  null is a diagnostic, not the decision). The standing regime rule (clear a scrambled-state
  control first) is met by this arm being reported alongside.
- **Prior.** Moderate. Momentum payoffs depend on the market regime (Cooper, Gutierrez and Hameed
  2004; Daniel and Moskowitz 2016 on momentum crashes after rebounds), and cross-sectional
  return dispersion predicts lower momentum and value premia (Stivers and Sun 2010).
  Concentration is a related but different state from either. The ledger's earlier regime
  gates on this data scored poorly (regime-conditional persistence 0/270 cells), which is why
  this is one variant, not a family of thresholds.
- **Follow-up variant, only if the first shows anything:** cross-sectional return dispersion
  of the panel itself as the state, a direct participation measure instead of an ETF proxy.

The "trade specific names when participation is narrow" idea is covered here on the residual
side: the `s x 1{narrow}` weights let each signal's per-name positions scale with the state.

## 4. Part B: factor momentum on the spreads themselves

Question: does a style spread's own trend predict its next return (time-series factor
momentum; Ehsani and Linnainmaa 2022, Gupta and Kelly 2019)? This is the "trade the
relationship" half, on raw returns, where S1 does not apply.

Vehicle: a small time-series book on the spread returns, outside the residual panel. Low
turnover, daily, so costs are small against gross, the reverse of family 1's problem.

Power is the likely blocker, and the E15 refusal rule (synthetic power below 50% at the
declared effect size) should run before any real-data number. Rough arithmetic: the vintage 1
bar is one-sided p < 0.00167 (z about 2.94), so 80% power needs a true annual Sharpe of about
3.78 / sqrt(years): about 0.88 for the three 2006 spreads (about 18.5 scored years) and about
1.10 for all six from 2014 (about 12 years). Published diversified factor momentum uses 15 to 20
factors; 3 to 6 correlated spreads should be expected to sit well below those Sharpes. Expect
the power check to refuse it on vintage 1. If it does, record the refusal; the idea is not
dead, only unresolvable at this breadth.

## 5. Design review (council pass, 2026-09-25)

Checked against the principles in `docs/foundation/principles.md` before registration.

- **Delete first.** Nothing persistent is built for either part until one passes. The state is
  a pure function of the panel's closes; no service, table or topic.
- **DAG.** `S0 panel -> participation_state(panel) -> S7 combiner -> S8 book test`. The state
  reads only the panel S0 already loads (RSP and SPY are panel names), so there is no second
  data path and no second price source to reconcile. One direction, no cycle.
- **Reuse, no generic layer yet.** S7 needs a "regime input" slot: a causal `[T]` series that
  multiplies member signals. Participation is its first consumer; a market-level
  `regime_volatility` would be the second. Build the slot for this consumer with a plain
  `[T]` float contract, and generalize only when the second arrives (not before).
- **Hidden biases checked.**
  - Lookahead: the rank window, the 63-session return and the target never overlap (state at
    close t, target from open t+1). The S3 causality probe must cover the state function, not
    only the members, because a state that peeks contaminates every interaction term at once.
  - Seen data: no spread or state value has been computed on this data. The owner's prior comes
    from market knowledge, stated in the pre-registration.
  - Mechanical overlap: when mega-caps lead, `c_t` falls and a raw momentum signal is long
    mega-caps. S1 residualizes the target, so the member signals do not carry that exposure;
    the combiner cannot rediscover concentration as a disguised style bet. Verify with the
    book's loadings on the 5 PCs, reported as a diagnostic.
  - Dividends: price-only legs (todo 428); a sub-1% annual yield gap is negligible against a
    quarterly trend, disclosed.
  - Breadth illusion: the interaction does not add bets. The book's effective breadth is the
    base book's; the test is still one book-level HAC timing t.
- **Async.** Not applicable: this is batch numpy inside the research runner. Adding async
  machinery to pure compute would be complexity with no latency to recover.

## 6. Order

1. Part A waits for S7 and a base book (phase 183), then is one pre-registered combiner
   variant. Nothing to build before then except the state series, which is a few lines inside
   the runner, not a service or table.
2. Part B's synthetic power check can run any time; it reads no real data.
3. No writer, `factor_series` table, `FeatureVector` field or CVR regime code until one part
   passes (shadow first).

Related: `docs/ideas/from-ssfi/signal-factor-sensitivity-cross-asset.md` (factor sensitivity
levels), `docs/ideas/signal-sensitivity-regime-interaction-primitives.md` (sensitivity times
regime interactions; its lookahead finding applies to any per-name spread loading, which must
be estimated trailing, never from the calibrator's full-history tags).
