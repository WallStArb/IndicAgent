# Multi-Engine HMM Regime Architecture

**Status:** Idea / Research
**Extends:** `intel-10-hmm-observation-vector.md`

---

## Thesis

The current single HMM answers one question: *how is price moving?* (momentum, volatility, volume anomaly -- all microstructure). The highest-IC alpha cells live where **price action is detached from structural positioning** -- where the "how" and the "who" diverge. A momentum-only HMM cannot see this. It assigns the same regime label to a quiet institutional accumulation and a retail-FOMO melt-up, even though those two bars have opposite IC profiles for continuation features.

The fix: decompose regime into orthogonal, independently-trained engines. Each engine trains on features from a single information domain. Joint regime state is the product at inference time -- no cross-engine coupling during training. The IC engine already implements this: adding a new HMM engine column to `feature_vectors` and stratifying by it is the entire integration path.

**Falsification criterion:** for each new engine, run Partial IC = `Corr(X_bar, Y | S_engine)`. If IC does not increase significantly when conditioned on the new engine's state, the engine adds no information and should be dropped.

---

## Engine Registry

| # | Engine | Observation Domain | Data Required | Status | K |
|---|---|---|---|---|---|
| 0 | **Price/Vol HMM** (current) | Momentum, realized vol, vol-of-vol, rel_volume | OHLCV (live) | Live | 5 |
| 1 | **Volatility Structure HMM** | Vol magnitude + velocity + geometry (Parkinson, YZ, noise ratio) | OHLCV (live) | Buildable now | 5 |
| 2 | **Volume Character HMM** | Detrended volume, VSR, VPC | OHLCV (live) | Buildable now | 5 |
| 3 | **Flow/Positioning HMM** | Institutional filings (13F, Form PF, ADV) | SEC filings -- not yet acquired | Blocked | 5 |
| 4 | **Corporate Event Vector** | Form 4 insider buys/sells, buyback windows, NLP legal friction | SEC EDGAR (Form 4 public) | Partially available | N/A -- stamped scalar, not HMM |
| 5 | **Sentiment / GEX Vector** | Options GEX, call/put ratio, retail NLP sentiment | CBOE data, scraping | Research | N/A |
| 6 | **Supply Chain Vector** | Commodity spreads, freight indices, satellite inventory | IBKR futures (spreads available); satellite = vendor | Partially available | N/A |

Build engines 1 and 2 first. All required features derive from existing `market_data_ohlcv`. Same code as the current HMM -- only the observation matrix changes.

---

## Engine 0: Price/Vol HMM (Current, Live)

**Question answered:** How and how fast is price moving?

**Observation vector (5D):**

| Dim | Feature | Formula |
|---|---|---|
| 0 | `log_return` | `ln(close[t] / close[t-1])` |
| 1 | `realized_vol` | rolling std of log_returns |
| 2 | `momentum` | `sum(log_returns[-W:]) / realized_vol` |
| 3 | `vol_of_vol` | rolling std of `realized_vol` |
| 4 | `rel_volume` | `log(volume[t]) - rolling_mean(log(volume))` |

**Output labels (K=5, sorted by emission mean of log_return):**
trending_down / transition_down / ranging / transition_up / trending_up

**Limitation:** labels are momentum-centric. A crowded-long distribution bar and a genuine institutional accumulation bar can produce identical labels with opposite forward IC profiles.

---

## Engine 1: Volatility Structure HMM

**Question answered:** What is the structural character of volatility -- and is it compressing or expanding?

Raw realized vol fed directly to this HMM produces poor separation because vol is ARCH-clustered and fat-tailed. Discriminate on two axes: **magnitude** and **velocity/geometry**.

### Observation features

**Garman-Klass Volatility** -- OHLC range-based; ~5x more efficient than close-to-close per bar:
```
σ²_GK[t] = 0.5 * ln(H/L)² - (2*ln2 - 1) * ln(C/O)²
```

**Parkinson Volatility** -- High/Low only; optimal for intraday bars where overnight gaps are irrelevant:
```
σ²_Parkinson[t] = (1 / (4*ln2)) * ln(H/L)²
```

**Yang-Zhang Volatility** -- gold standard for OHLC data; explicitly separates overnight gaps from intraday vol:
```
σ²_YZ = σ²_overnight + k * σ²_open + (1-k) * σ²_RS
```
Where `σ²_RS` = Rogers-Satchell. Prevents gap events from contaminating the intraday vol estimate.

**Volatility Velocity** -- log-differenced rolling vol; stationary at any vol level:
```
vol_velocity[t] = ln(σ_GK[t]) - ln(σ_GK[t-lag])
```
The single most important feature for separating State 4 (orderly expansion) from State 5 (accelerating panic). Without it the HMM conflates two states with opposite trading implications.

**Intraday Noise Ratio** -- path length vs. net displacement:
```
noise_ratio[t] = sum(|log_return_5m|, last N 5m bars) / max(|log_return_1d[t]|, ε)
```
High = violent oscillation without progress (chop). Low = clean directional move. Cross-timeframe: requires 5m bars fed alongside 1d baseline.

### K=5 Volatility Regimes

| # | State | Magnitude | Velocity | Bar Behavior | Trading Implication |
|---|---|---|---|---|---|
| 1 | **Institutional Compression** | Ultra-low | Compressing | 1d/1h ranges shrinking well below 20d MA; frequent inside bars | Spring coiling. Disable mean-reversion; stage for breakout |
| 2 | **Quiet Bull Drift** | Low | Stable | Low intraday variance; closes consistently near highs; gaps minimal and filled | High signal reliability. Lower-TF features have best IC here |
| 3 | **Mean-Reverting Chop** | Medium intraday, low 1d | Near-zero | Large 5m/15m wicks both sides; high GK vol intraday but low 1d close-to-close variance | Market makers dominating. Fade extremes; breakout strategies fail |
| 4 | **Directional Expansion** | High | Rising linearly | Wide-range bars; open near one extreme, close near other; low wick-to-body ratio | Orderly trend. Trend-following on 15m/1h |
| 5 | **Systemic Liquidation** | Ultra-high | Parabolic/accelerating | Massive 1m/5m true ranges; large opening gaps; asymmetric downside bars; extreme intraday variance | Standard S/R irrelevant. Risk engine must downsize |

State 3 vs. State 4 is the critical distinction -- same intraday vol magnitude but opposite velocity. `noise_ratio` and `vol_velocity` together separate them.

---

## Engine 2: Volume Character HMM

**Question answered:** What kind of participation is driving this bar?

Raw volume is non-stationary, has a strong intraday U-shape (surge at open/close), and varies by orders of magnitude across symbols. Three required transformations before the HMM sees volume data:

**1. Detrend intraday U-shape:**
```
vol_detrended[t] = volume[t] / mean(volume[same_time_of_day_slot], lookback=30d)
```

**2. Rolling Z-score:**
```
vol_z[t] = (vol_detrended[t] - rolling_mean) / rolling_std  [20d window]
```

**3. Volume-to-Spread Ratio (VSR):**
```
vsr[t] = vol_detrended[t] / max(high[t] - low[t], ε)
```
This single feature separates the two opposite high-volume states (absorption vs. breakout) that are indistinguishable on raw volume alone.

**Volume-Price Coupling (VPC):**
```
vpc[t] = rolling_corr(Δvolume, sign(log_return) * |log_return|, window=W)
```
Distinct from `rel_volume` in Engine 0 -- that measures absolute volume anomaly. VPC measures whether volume is directionally coupled to price, separating informed institutional flow from noise.

### K=5 Volume Regimes

| # | State | Vol Z | VSR | VPC | Character |
|---|---|---|---|---|---|
| 1 | **Drying Up / Illiquidity** | Very low | -- | Near zero | Late-stage consolidation; exhausted bear |
| 2 | **Normal Liquid Flow** | ~0 | Mid | Moderate | Baseline institutional execution |
| 3 | **Institutional Absorption** | High | High (tight range) | Low | Smart money soaking supply without price extension |
| 4 | **Aggressive Breakout** | High | Low (wide range) | High | Initiative volume; directional conviction |
| 5 | **Climactic Exhaustion** | Extreme | Variable | Decoupling | Structural turning point; capitulation or panic |

---

## Engine 3: Flow/Positioning HMM (Blocked -- Requires Data)

**Question answered:** Who is behind the price movement and why?

This engine modifies the Transition Probability Matrix with an exogenous regulatory flow vector `u_t`:
```
P(S_t = j | S_{t-1} = i, u_t)
```

When `u_t` signals de-leveraging, transition probability into bullish states drops regardless of microstructure. When `u_t` is constructive, microstructure acts as the tactical trigger. The macro layer rules out states; the micro layer picks them.

### Data dependencies (all with significant lag)

| Source | Content | Lag | Availability |
|---|---|---|---|
| Form PF | Hedge fund systemic risk, leverage, net positioning | 60 days | Not public; requires vendor (Preqin, Burgiss) |
| 13F | Institutional equity holdings by fund | 45 days | Public via SEC EDGAR; parseable |
| Form ADV | RIA AUM and registration | Annual + amendments | Public via SEC EDGAR |
| Form D | Private offering / fund capital raise | ~15 days | Public via SEC EDGAR |
| NFA data | Futures positioning by category | Weekly | CFTC COT report (public) |

The lag is not a disqualifier -- a 45-day-lagged 13F is a valid slow-moving prior on the TPM. It rules out regimes across quarters, not within bars. 4 TPM updates per year is sufficient resolution for structural positioning context.

### K=5 Flow/Positioning Regimes

| # | State | Primary Signal | Macro Signature | Micro Footprint |
|---|---|---|---|---|
| 1 | **Short Squeeze / De-leveraging** | NFA + Form PF | High short futures exposure + sudden leverage drop | Negative VPC, vol cascade spike, whipsaw close_skew |
| 2 | **Quiet Accumulation** | 13F + Form D | Concentration building; AUM scaling; Form D offerings rising | High close_skew on up-bars; moderate VPC; low vol cascade |
| 3 | **Balanced / Neutral Roll** | All baseline | No aggressive positioning shifts | VPC ~0; low vol cascade; close_skew ~0.5 |
| 4 | **Institutional Distribution** | 13F + ADV | AUM flat or falling despite rising price; smart money exiting into retail | Falling close_skew; high VPC on down-bars into rising price |
| 5 | **Systemic Liquidation** | Form PF | Macro funds rushing to cash; cross-asset futures liquidation | Massive vol cascade; strongly negative VPC; structural gap risk |

---

## Orthogonality: Why Separate Engines

If these domains were correlated, joint training on a merged observation vector would be the right approach. They are not:

| Engine | Captures | The question |
|---|---|---|
| Price/Vol (E0) | Current microstructure | *How* and *how fast* is price moving? |
| Volatility Structure (E1) | Vol geometry and acceleration | *Is volatility stable or about to transition?* |
| Volume Character (E2) | Participation intent | *What kind* of volume is behind the move? |
| Flow/Positioning (E3) | Institutional structural intent | *Who* is moving it and *why?* |

Joint training on a merged vector produces multicollinearity between engines and dilutes the Gaussian emission estimates. Each engine trained independently captures its domain cleanly. The product state at inference time is purely an IC stratification key -- no cross-engine coupling.

### High-conviction divergence cells

The highest-IC cells are where engines disagree -- where the "how" and "who" diverge:

| E0 State | E3 State | Market Reality | IC Implication |
|---|---|---|---|
| Bear Vol Spike (panic selling) | Quiet Accumulation | **Institutional Liquidity Hunt** -- large players using retail panic to fill blocks. High-probability mean-reversion buy. | Mean-reversion features have highest IC; continuation features inverted |
| Bull Trend / Low Vol (grinding up) | Institutional Distribution | **Exhaustion / Exhaust Wave** -- price rising on retail FOMO, smart money exiting. Structurally fragile. Asymmetric short setup. | Continuation IC low/negative; reversal features activated |
| Mean-Reverting Range (choppy) | Systemic Liquidation | **Calm Before the Storm** -- bar looks quiet but underlying leverage is unstable. Any micro-trigger produces explosive downside vol breakout. | Vol breakout features have highest IC; all directional features suppressed |

A momentum-only HMM assigns the same label to the first two rows. Only the joint cell reveals the signal.

---

## Partial IC Validation Protocol

For each new engine added, validate it earns its place before corpus re-run:

```
IC_partial = Corr(X_bar, Y_forward | S_engine)
```

1. Train new engine on 3-5 symbols (not full corpus)
2. Stamp `S_engine` onto existing `feature_vectors`
3. Query `feature_ic_scores` stratified by `(existing_hmm_state, new_engine_state)`
4. Compare IC Sharpe with and without the new stratification axis
5. **Pass criterion:** IC Sharpe increases by >10% in at least one joint cell with N > 20k bars
6. If pass: full corpus re-run with new engine column baked in

The IC engine already implements this -- adding `S_engine` as a stratification column requires no infrastructure changes. The `WHERE regime_label = ? AND new_engine_state = ?` query is already the pattern.

---

## Joint State Space and Sparsity

| Engines active | Joint cells | Practical cells (impossible combos removed) |
|---|---|---|
| E0 only (current) | 5 | 5 |
| E0 + E1 | 25 | ~18 |
| E0 + E1 + E2 | 125 | ~60 |
| E0 + E1 + E2 + E3 | 625 | ~150 |

Sparsity is handled by the existing 20k bar IC gate -- sparse cells emit no score rather than a noisy one. At 58 ETFs × 4 TFs, even 150 effective cells is tractable (~16 ETF-TF combinations needed per cell at 20k bars each).

The full bar fingerprint with all four engines: `(price_state, vol_state, volume_state, flow_state)`.

---

## Additional Intelligence Vectors (Non-HMM, Stamped Scalars)

These do not produce latent state labels. They are scalar or categorical features stamped directly onto bars and fed into the IC stratification as additional axes.

### Corporate Event Vector (Form 4, Buybacks)
- **Insider cluster signal:** binary/intensity indicator when senior executives net-buy their own stock (Form 4, SEC EDGAR, public). Insider buy + E3 Quiet Accumulation = highest-conviction long -- management and institutions aligned.
- **Active buyback window:** binary flag when a repurchase authorization is active. Creates structural price floor; dampens E1 vol spike states.
- **Regulatory/legal friction:** NLP sentiment from ongoing litigation, patent approvals, FDA pipelines. Slow-moving; sector-specific (biotech, pharma).

### Sentiment / GEX Vector
- **Gamma Exposure (GEX):** delta-adjusted market maker gamma from options open interest. Negative GEX = market makers must sell into down moves (amplifies vol). Positive GEX = market makers buy dips (suppresses vol). Directly modulates E1 vol regime interpretation.
- **Call/put ratio, retail sweep intensity:** real-time options flow from CBOE. When retail options buying extreme + E3 Institutional Distribution = high-probability reversal.
- **Retail NLP sentiment:** price grinding up + extreme optimism + E3 Distribution = divergence; reversal imminent.

### Supply Chain / Macro Vector
- **Cross-asset commodity spreads:** copper/gold ratio (growth vs. fear), Baltic Dry Index, energy spreads. Available via IBKR futures feeds already in the system.
- **Satellite / geospatial inventory:** parking lot density, oil tank floating lid positions, cargo congestion. Vendor data; expensive. Weekly/monthly update frequency.

---

## Build Sequence

**Phase 1 (OHLCV-only, no new data):**
1. Implement Engine 1 (Volatility Structure HMM) -- Parkinson, YZ, vol_velocity, noise_ratio
2. Validate via Partial IC on 3-5 symbols
3. Implement Engine 2 (Volume Character HMM) -- detrended vol_z, VSR, VPC
4. Validate via Partial IC on 3-5 symbols
5. If both pass: full corpus re-run with E1 and E2 columns in `feature_vectors`

**Phase 2 (requires data acquisition):**
1. Acquire 13F data via SEC EDGAR (public, parseable) -- Form 4 as well
2. Implement COT report ingestion (CFTC, public, weekly)
3. Build Engine 3 (Flow/Positioning HMM) with soft prior approach (features in obs vector, not hard TPM modification)
4. Validate via Partial IC
5. Full corpus re-run

**Phase 3 (vendor data):**
1. Options flow / GEX (CBOE data access)
2. Sentiment NLP pipeline
3. Satellite data (if warranted by Phase 1-2 results)

Any observation vector or engine change invalidates `feature_ic_scores`. Validate on 3-5 symbols before committing to a full run.

---

## Open Questions

1. **BIC re-selection per engine:** K=5 was BIC-optimal for the current 5D price/vol vector. Each new engine should run BIC independently on its own observation space. K may not be 5 for vol structure or volume character.
2. **Cross-timeframe features:** `noise_ratio` and `ivr` require 5m bars in a 1d context. `_build_obs_matrix()` currently takes a single timeframe. Needs a refactor to pass multi-TF data to the vol HMM.
3. **Hard vs. soft macro prior for Engine 3:** modifying the TPM directly (hard ARX constraint) vs. adding macro features to the observation vector (soft influence). Soft approach is implementable without changing the HMM class; hard approach is more principled but complex.
4. **13F seasonality:** 45-day lag means 4 TPM updates per year. This effectively creates 4 seasonal variants. Whether that resolution is sufficient or just adds noise to be determined empirically.

---

## Related Docs

- `docs/ideas/intel-10-hmm-observation-vector.md` -- current 5D price/vol vector and evaluation protocol
- `docs/ideas/intel-08-macro-cross-asset.md` -- macro/cross-asset signals
- `docs/intelligence/intelligence-alphaengine.md` -- IC engine design
- `docs/plans/2026-06-29-regime-stratification-alternatives.md` -- volatility_regime + volume_regime stratification (simpler percentile-rank approach, no HMM)
