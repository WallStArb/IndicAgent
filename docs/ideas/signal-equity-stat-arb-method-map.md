# Equity stat arb methods: the seven-method map against the ledger

**Status:** Idea, 2026-10-28. Not reviewed: Sonnet 5.5 mapping against the ledger; needs an Opus or Fable rigor pass before it moves to `docs/research/`. A catalogue entry; nothing here is queued and no look has been taken.
**Source:** seven stat arb slides from quantguy_usa, pasted by the owner 2026-10-28.
**Mapped by:** Claude (Sonnet 5.5), interactive session, against `docs/research/construction-verdict-ledger.md`.
**Ledger rows:** section 3 of the ledger, "Equity stat arb" rows; verdict rows and queued families are
linked in the table below.

## The common pipeline

Hedge the factors, trade the residual: universe and data, factor model, residuals, signal, neutral
portfolio, costs and risk. The slides' own warning: transaction costs, turnover and factor neutrality
decide whether a backtest survives, and poor factor hedging turns stat arb into a hidden beta bet.
Here that maps to S1 (target residualized against market and sector), the research runner, and
"costs never enter a test statistic, but promotion needs positive net expectation".

## The seven methods

| # | Method | Slide's form | Main risk (slides) | Where it stands here |
|---|---|---|---|---|
| 1 | PCA or sector-ETF residuals | Regress returns on PCA factors or sector ETFs; model the residual `X` as mean reverting; z-score `(X - m) / sigma_eq`; long and short, factor neutral | Factor-model drift | Not tested as a residual reversion book. `statistical_factor_residual` (DEAD 2026-09-01) asked a different question: whether residualizing improved `ctf_momentum`'s IC. Nearest queued work: residual reversal R1-R3 in the daily residual family (todos 441 and 423, ledger row 4) |
| 2 | Fundamental factor residuals | Size, value, momentum and industry factors; trade the residual's mean reversion | Style crowding | Never tested. Needs size, value and quality characteristics; no fundamentals table is stored (S0 reads high, low and point-in-time sector). `docs/research/data-alt-data-sources.md` has the as-reported, release-date keyed design |
| 3 | ML on residuals | Lagged residuals plus features into trees, nets or transformers; predict the next residual; out-of-sample forecast-decile spread (IC about 0.11 in the slide's example) | Overfitting, leakage | Not tested as stated. Nearest: todo 440 (grammar over daily OHLCV, in-fold selection plus ridge) and the S7 combiner. An IC of 0.11 is far above anything measured here; read it as a leakage warning, not a target |
| 4 | Cointegration pairs | Engle-Granger or Johansen, hedge ratio, spread z-score, exit at the mean | Relationships break | `cointegrated_pairs_residual` DEAD, closed for good (ETF and 471 same-sector single-name pairs); `docs/research/measurement-cointegrated-pairs-residual.md` |
| 5 | Kalman filter and OU spread | Time-varying hedge ratio and mean; fit Ornstein-Uhlenbeck, half-life `ln 2 / kappa`; trade the filtered residual | Over-tuned filters | A new estimator on the pairs that are closed, so it needs an explicit owner reopen. The v2.x Kalman trend plugin is a different thing and is not a v3 column |
| 6 | Short-term reversal | Rank by recent return; long losers, short winners; market and sector neutral | Costs, momentum | Queued: ledger row 4 (todo 423), daily form with the 231-name exclusion |
| 7 | ETF or index arbitrage | ETF price against the constituent basket; trade the gap and hedge | Speed, hedging cost | ETF-to-constituent lead-lag at 5m to 1h is ledger row 3 (design only). The arbitrage form is speed and creation-redemption bound and conflicts with the rule against hyper-traded strategies (extend horizon, not frequency); not pursued |

## What would enter a book

Only 1 (as a residual reversal member with a statistical factor model) and 3 (as a fitted combiner
member, after E17's memory rule) are testable on the stored data without new inputs. Both would be
pre-registered family members, counted under E18, and run after the 1d re-derive. 2 waits on a
fundamentals source; 4 and 5 are closed; 6 is already queued; 7 is out of scope.

Feature candidates these methods imply, and the pre-rebuild window for stored columns: `docs/plans/2026-10-28-pre-rebuild-feature-additions-draft.md` (todo 558).
