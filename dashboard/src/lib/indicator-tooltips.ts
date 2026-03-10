// dashboard/src/lib/indicator-tooltips.ts
import type { TooltipContent } from "@/components/tooltip";
import { fmtMinutesHM } from "@/lib/format";

// ─── I1 Indicator tooltips ────────────────────────────────────────────────────

export function rsiTooltip(value?: number | null): TooltipContent {
  const description = "Relative Strength Index (0–100). Momentum oscillator measuring speed and magnitude of price moves.";
  if (value == null) return { description, context: null };
  if (value > 70) return { description, context: `${value.toFixed(1)} — Overbought. Momentum may be fading; watch for reversal.` };
  if (value < 30) return { description, context: `${value.toFixed(1)} — Oversold. Selling may be exhausted; potential bounce.` };
  return { description, context: `${value.toFixed(1)} — Neutral zone. No extreme momentum pressure.` };
}

export function macdTooltip(histogram?: number | null): TooltipContent {
  const description = "MACD (12/26/9). Difference between 12-EMA and 26-EMA, smoothed by a 9-EMA signal line.";
  if (histogram == null) return { description, context: null };
  if (histogram > 0) return { description, context: "Histogram positive — bullish momentum building." };
  if (histogram < 0) return { description, context: "Histogram negative — bearish momentum building." };
  return { description, context: "Histogram at zero — momentum neutral / crossover." };
}

export function stochTooltip(k?: number | null): TooltipContent {
  const description = "Stochastic Oscillator (14,3). Compares close to the 14-bar range. K=fast line, D=3-bar smoothed.";
  if (k == null) return { description, context: null };
  if (k > 80) return { description, context: `K ${k.toFixed(0)} — Overbought. Watch for K crossing below D as exit signal.` };
  if (k < 20) return { description, context: `K ${k.toFixed(0)} — Oversold. Watch for K crossing above D as entry signal.` };
  return { description, context: `K ${k.toFixed(0)} — Mid-range. No overbought/oversold signal.` };
}

export function cciTooltip(value?: number | null): TooltipContent {
  const description = "Commodity Channel Index. Measures deviation from average price. ±100 are key thresholds.";
  if (value == null) return { description, context: null };
  if (value > 100) return { description, context: `${value.toFixed(0)} — Above +100: overbought / strong trend.` };
  if (value < -100) return { description, context: `${value.toFixed(0)} — Below −100: oversold / strong down-trend.` };
  return { description, context: `${value.toFixed(0)} — Between ±100: mean-reversion zone.` };
}

export function williamsRTooltip(value?: number | null): TooltipContent {
  const description = "Williams %R (−100 to 0). Inverted oscillator — readings near 0 are overbought, near −100 are oversold.";
  if (value == null) return { description, context: null };
  if (value > -20) return { description, context: `${value.toFixed(0)} — Overbought territory (near 0).` };
  if (value < -80) return { description, context: `${value.toFixed(0)} — Oversold territory (near −100).` };
  return { description, context: `${value.toFixed(0)} — Mid-range. No extreme reading.` };
}

export function atrTooltip(): TooltipContent {
  return {
    description: "Average True Range (14). Measures bar-to-bar volatility in price points. Higher = wider moves expected.",
    context: null,
  };
}

export function bbTooltip(): TooltipContent {
  return {
    description: "Bollinger Bands (20 SMA ± 2σ). Shows lower–upper boundary. Price near upper band = extended; near lower = depressed.",
    context: null,
  };
}

export function mfiTooltip(value?: number | null): TooltipContent {
  const description = "Money Flow Index (0–100). Volume-weighted RSI — measures buying vs. selling pressure.";
  if (value == null) return { description, context: null };
  if (value > 80) return { description, context: `${value.toFixed(1)} — Overbought on volume. Distribution likely.` };
  if (value < 20) return { description, context: `${value.toFixed(1)} — Oversold on volume. Accumulation likely.` };
  return { description, context: `${value.toFixed(1)} — Neutral flow. No volume-pressure extreme.` };
}

export function obvTooltip(): TooltipContent {
  return {
    description: "On-Balance Volume. Cumulative volume flow indicator. Rising OBV = accumulation; falling = distribution.",
    context: null,
  };
}

export function vwapTooltip(): TooltipContent {
  return {
    description: "Volume Weighted Average Price. Session fair value — heavily referenced by institutional traders for entries and exits.",
    context: null,
  };
}

export function sma20Tooltip(): TooltipContent {
  return {
    description: "SMA 20. Simple Moving Average over 20 bars. Short-term trend reference — price above = near-term bullish bias.",
    context: null,
  };
}

export function sma50Tooltip(): TooltipContent {
  return {
    description: "SMA 50. Simple Moving Average over 50 bars. Medium-term trend. Key institutional reference level.",
    context: null,
  };
}

export function ema13Tooltip(): TooltipContent {
  return {
    description: "EMA 13. Fast exponential moving average. Reacts quickly to momentum shifts; crossover with EMA 21 signals short-term entries.",
    context: null,
  };
}

export function ema21Tooltip(): TooltipContent {
  return {
    description: "EMA 21. Fibonacci exponential moving average. Trend confirmation; acts as dynamic support/resistance.",
    context: null,
  };
}

export function adxTooltip(adx?: number | null): TooltipContent {
  const description = "Average Directional Index (0–100). Measures trend strength — not direction. Values >25 = trending; <20 = ranging or weak trend.";
  if (adx == null) return { description, context: null };
  if (adx > 50) return { description, context: `${adx.toFixed(1)} — Very strong trend. High conviction directional move.` };
  if (adx > 25) return { description, context: `${adx.toFixed(1)} — Trending market. Trend-following setups favoured.` };
  return { description, context: `${adx.toFixed(1)} — Weak or no trend. Mean-reversion environment.` };
}

export function diTooltip(plusDi?: number | null, minusDi?: number | null): TooltipContent {
  const description = "+DI vs −DI (Directional Indicators). +DI > −DI = bullish directional pressure; −DI > +DI = bearish. Crossovers signal potential trend changes.";
  if (plusDi == null || minusDi == null) return { description, context: null };
  const bull = plusDi > minusDi;
  return {
    description,
    context: bull
      ? `+DI ${plusDi.toFixed(1)} > −DI ${minusDi.toFixed(1)} — Bullish directional bias.`
      : `−DI ${minusDi.toFixed(1)} > +DI ${plusDi.toFixed(1)} — Bearish directional bias.`,
  };
}

export function supertrendTooltip(dir?: number | null, value?: number | null): TooltipContent {
  const description = "Supertrend. ATR-based ratcheting band that flips only on price crossover. Bullish = price above band; bearish = price below band.";
  if (dir == null) return { description, context: null };
  const label = dir > 0 ? "Bullish" : "Bearish";
  const lvl = value != null ? ` (band at ${value.toFixed(2)})` : "";
  return { description, context: `${label}${lvl} — price is ${dir > 0 ? "above" : "below"} the supertrend band.` };
}

export function rocTooltip(value?: number | null): TooltipContent {
  const description = "Rate of Change (14-period). % price change over 14 bars. Positive = price higher than 14 bars ago; negative = lower.";
  if (value == null) return { description, context: null };
  if (Math.abs(value) < 0.1) return { description, context: `${value.toFixed(2)}% — Price largely unchanged over 14 bars.` };
  return {
    description,
    context: value > 0
      ? `+${value.toFixed(2)}% — Price higher than 14 bars ago. Positive momentum.`
      : `${value.toFixed(2)}% — Price lower than 14 bars ago. Negative momentum.`,
  };
}

export function aoTooltip(value?: number | null): TooltipContent {
  const description = "Awesome Oscillator. SMA(5) minus SMA(34) of bar midpoints. Positive = bullish momentum; negative = bearish; zero crosses signal momentum shifts.";
  if (value == null) return { description, context: null };
  if (value > 0) return { description, context: `${value.toFixed(2)} — Positive. Bullish momentum above zero line.` };
  return { description, context: `${value.toFixed(2)} — Negative. Bearish momentum below zero line.` };
}

export function acTooltip(value?: number | null): TooltipContent {
  const description = "Accelerator Oscillator (AO minus its 5-bar SMA). Leading indicator — turns before AO. Positive and rising = accelerating bullish momentum.";
  if (value == null) return { description, context: null };
  if (value > 0) return { description, context: `${value.toFixed(2)} — Positive. Momentum accelerating bullish.` };
  return { description, context: `${value.toFixed(2)} — Negative. Momentum decelerating or bearish.` };
}

// ─── I3 Structure tooltips ────────────────────────────────────────────────────

export function trendIntegrityTooltip(value?: number | null): TooltipContent {
  const description = "Trend integrity (0–1). How consistently price is making higher highs/lower lows. Higher = cleaner trend.";
  if (value == null) return { description, context: null };
  if (value > 0.7) return { description, context: `${(value * 100).toFixed(0)}% — Strong, well-defined trend.` };
  if (value > 0.4) return { description, context: `${(value * 100).toFixed(0)}% — Moderate trend with some chop.` };
  return { description, context: `${(value * 100).toFixed(0)}% — Weak trend — consolidation or reversal likely.` };
}

export function supportResistanceTooltip(kind: "support" | "resistance"): TooltipContent {
  return {
    description: kind === "support"
      ? "Nearest structural support level. Price area where buyers have historically stepped in."
      : "Nearest structural resistance level. Price area where sellers have historically emerged.",
    context: null,
  };
}

export function levelStrengthTooltip(kind: "support" | "resistance", value?: number | null): TooltipContent {
  const description = `${kind === "support" ? "Support" : "Resistance"} strength (0–1). Based on touch count and hold history. Higher = more significant level.`;
  if (value == null) return { description, context: null };
  if (value > 0.7) return { description, context: `${value.toFixed(2)} — Strong level. Multiple tests and holds.` };
  if (value > 0.4) return { description, context: `${value.toFixed(2)} — Moderate level. Some validation.` };
  return { description, context: `${value.toFixed(2)} — Weak level. Limited test history.` };
}

// ─── I4 Context tooltips ──────────────────────────────────────────────────────

export function volRegimeTooltip(regime?: string | null): TooltipContent {
  const description = "Volatility regime from GARCH model: low, normal, high, or extreme.";
  const contextMap: Record<string, string> = {
    low: "Low — price moving in tight ranges. Breakout potential building.",
    normal: "Normal — typical session volatility. Standard position sizing appropriate.",
    high: "High — wider bars, elevated risk. Reduce size or widen stops.",
    extreme: "Extreme — crisis-level volatility. Caution: slippage and whipsaws likely.",
  };
  return { description, context: regime ? (contextMap[regime] ?? regime) : null };
}

export function atrPercentileTooltip(value?: number | null): TooltipContent {
  const description = "ATR percentile vs. 90-day history. Shows where current volatility ranks relative to recent past.";
  if (value == null) return { description, context: null };
  const pct = Math.round(value * 100);
  if (pct > 80) return { description, context: `${pct}th percentile — Elevated volatility. Wider-than-normal moves.` };
  if (pct < 20) return { description, context: `${pct}th percentile — Compressed volatility. Breakout may be building.` };
  return { description, context: `${pct}th percentile — Normal volatility range.` };
}

export function volExpandingTooltip(expanding?: boolean | null): TooltipContent {
  const description = "Whether volatility is actively expanding (true) or contracting (false).";
  if (expanding == null) return { description, context: null };
  return {
    description,
    context: expanding
      ? "Expanding — momentum is increasing. Breakout environment."
      : "Contracting — energy compressing. Potential coil before next move.",
  };
}

export function trendRegimeTooltip(regime?: string | null): TooltipContent {
  const description = "Kalman filter trend regime across 5 levels: strong_up, weak_up, neutral, weak_down, strong_down.";
  const contextMap: Record<string, string> = {
    strong_up: "Strong uptrend — price making sustained higher highs.",
    weak_up: "Weak uptrend — bullish bias but momentum unconvincing.",
    neutral: "No clear trend — mean-reversion environment.",
    weak_down: "Weak downtrend — bearish bias but momentum unconvincing.",
    strong_down: "Strong downtrend — price making sustained lower lows.",
  };
  return { description, context: regime ? (contextMap[regime] ?? regime) : null };
}

export function momentumBiasTooltip(value?: number | null): TooltipContent {
  const description = "Net momentum bias (−1 to +1). Aggregates multiple momentum signals into a single directional score.";
  if (value == null) return { description, context: null };
  if (value > 0.2) return { description, context: `+${value.toFixed(2)} — Bullish momentum bias.` };
  if (value < -0.2) return { description, context: `${value.toFixed(2)} — Bearish momentum bias.` };
  return { description, context: `${value.toFixed(2)} — Momentum neutral.` };
}

// ─── I5 Pattern tooltips ──────────────────────────────────────────────────────

export function rsiDivTooltip(divergence?: string | null): TooltipContent {
  const description = "RSI Divergence. Price and RSI moving in opposite directions — often precedes reversals.";
  const contextMap: Record<string, string> = {
    bullish: "Bullish divergence: price made a lower low but RSI made a higher low. Bearish momentum weakening.",
    bearish: "Bearish divergence: price made a higher high but RSI made a lower high. Bullish momentum weakening.",
  };
  return { description, context: divergence ? (contextMap[divergence] ?? null) : null };
}

export function bbSqueezeTooltip(active?: boolean | null, count?: number | null): TooltipContent {
  const description = "Bollinger Band squeeze. Bands contracting to unusually tight levels — energy building for a breakout.";
  if (active == null) return { description, context: null };
  if (!active) return { description, context: "No squeeze — bands at normal width." };
  return { description, context: `Squeeze active for ${count ?? 0} bars — the longer it holds, the bigger the potential breakout.` };
}

export function volDivTooltip(divergence?: string | null): TooltipContent {
  const description = "Volume divergence. Volume trend opposing price direction — suggests the move lacks conviction.";
  const contextMap: Record<string, string> = {
    bullish: "Bullish volume divergence: rising volume on up-moves, declining on down-moves. Buyers are committed.",
    bearish: "Bearish volume divergence: rising volume on down-moves, declining on up-moves. Sellers are committed.",
  };
  return { description, context: divergence ? (contextMap[divergence] ?? null) : null };
}

export function i5ConfluenceTooltip(value?: number | null): TooltipContent {
  const description = "I5 pattern confluence (0–1). Agreement across RSI divergence, BB squeeze, and volume divergence signals.";
  if (value == null) return { description, context: null };
  if (value > 0.7) return { description, context: `${value.toFixed(2)} — High confluence. Multiple pattern signals aligned.` };
  if (value > 0.4) return { description, context: `${value.toFixed(2)} — Moderate confluence. Partial signal agreement.` };
  return { description, context: `${value.toFixed(2)} — Low confluence. Patterns not confirming each other.` };
}

// ─── SMC tooltips ─────────────────────────────────────────────────────────────

export function bosTooltip(): TooltipContent {
  return {
    description: "Break of Structure (BOS). Price broke through a prior swing high (bullish) or low (bearish), confirming trend direction.",
    context: null,
  };
}

export function chochTooltip(): TooltipContent {
  return {
    description: "Change of Character (CHoCH). A BOS in the opposite direction of the prior trend — early warning of trend reversal.",
    context: null,
  };
}

export function fvgTooltip(): TooltipContent {
  return {
    description: "Fair Value Gap (FVG). An imbalance candle where price moved too fast, leaving a gap. Price tends to return and fill it.",
    context: null,
  };
}

export function orderBlockTooltip(): TooltipContent {
  return {
    description: "Order Block. The last opposing candle before a strong impulse move — marks an institutional supply (bearish) or demand (bullish) zone.",
    context: null,
  };
}

export function sweepTooltip(reclaimed?: boolean | null): TooltipContent {
  const description = "Liquidity Sweep. Price briefly extended beyond a key level to trigger stop orders, then reversed.";
  if (reclaimed == null) return { description, context: null };
  return {
    description,
    context: reclaimed
      ? "Level reclaimed — strong reversal signal. Smart money filled liquidity and reversed."
      : "Level not yet reclaimed — sweep may extend further before reversal.",
  };
}

export function hmmRegimeTooltip(regime?: number | null, prob?: number | null): TooltipContent {
  const description = "HMM Market Regime. Hidden Markov Model probability of ranging (0), trending up (1), or trending down (2).";
  if (regime == null) return { description, context: null };
  const labels = ["Ranging", "Trending up", "Trending down"];
  const label = labels[regime] ?? `Regime ${regime}`;
  const pct = prob != null ? ` (${(prob * 100).toFixed(0)}% confidence)` : "";
  return { description, context: `${label}${pct}.` };
}

export function liquidityLevelTooltip(kind: "BSL" | "SSL"): TooltipContent {
  return {
    description: kind === "BSL"
      ? "Buy-Side Liquidity (BSL). Cluster of stop-loss orders above recent swing highs. Price is often drawn to these levels before reversing."
      : "Sell-Side Liquidity (SSL). Cluster of stop-loss orders below recent swing lows. Price may target these before reversing.",
    context: null,
  };
}

// ─── I6 Confluence tooltips ───────────────────────────────────────────────────

export function ctfScoreTooltip(value?: number | null): TooltipContent {
  const description = "Cross-Timeframe (CTF) confluence score (0–1). How aligned 1m, 5m, 15m, and 1h are in trend direction and structure.";
  if (value == null) return { description, context: null };
  if (value > 0.7) return { description, context: `${value.toFixed(2)} — Strong multi-timeframe alignment. High-probability setup zone.` };
  if (value > 0.4) return { description, context: `${value.toFixed(2)} — Moderate alignment. Some timeframes conflicted.` };
  return { description, context: `${value.toFixed(2)} — Weak alignment. Timeframes disagree — lower-conviction environment.` };
}

export function ctfTfsAlignedTooltip(count?: number | null): TooltipContent {
  const description = "Timeframes aligned (out of 4: 1m/5m/15m/1h). How many are pointing in the same direction.";
  if (count == null) return { description, context: null };
  if (count >= 4) return { description, context: "All 4 timeframes aligned — maximum confluence." };
  if (count >= 3) return { description, context: "3 of 4 timeframes aligned — strong but not unanimous." };
  if (count >= 2) return { description, context: "2 of 4 aligned — mixed signals." };
  return { description, context: "1 or fewer aligned — timeframes conflicting." };
}

export function ctfTrendAlignTooltip(value?: number | null): TooltipContent {
  const description = "Trend alignment (0–1). Consistency of trend direction across all monitored timeframes.";
  if (value == null) return { description, context: null };
  if (value > 0.7) return { description, context: `${value.toFixed(2)} — Trends aligned across timeframes.` };
  if (value > 0.4) return { description, context: `${value.toFixed(2)} — Partial trend alignment.` };
  return { description, context: `${value.toFixed(2)} — Trend conflicted across timeframes.` };
}

export function ctfStructureAlignTooltip(value?: number | null): TooltipContent {
  return {
    description: "Structure alignment (0–1). Agreement on Break of Structure (BOS) and CHoCH events across timeframes.",
    context: value != null
      ? value > 0.6
        ? `${value.toFixed(2)} — Structure confirming across TFs.`
        : `${value.toFixed(2)} — Structure mixed across TFs.`
      : null,
  };
}

export function ctfRegimeAgreementTooltip(value?: number | null): TooltipContent {
  return {
    description: "Regime agreement (0–1). How many timeframes share the same volatility and trend regime.",
    context: value != null
      ? value > 0.6
        ? `${value.toFixed(2)} — Regimes consistent across TFs — stable environment.`
        : `${value.toFixed(2)} — Regimes mixed — market transitioning.`
      : null,
  };
}

// ─── SMC extended tooltips ────────────────────────────────────────────────────

export function killzoneTooltip(name?: string | null, minutesUntil?: number | null): TooltipContent {
  const description = "ICT Killzones: high-probability session windows — Asia (00:00–04:00 UTC), London (07:00–10:00), NY AM (13:00–16:00), NY PM (19:00–21:00 UTC).";
  if (name) {
    return { description, context: `Currently in ${name} killzone — institutional order flow elevated.` };
  }
  if (minutesUntil != null) {
    return { description, context: `Not in killzone. Next opens in ${fmtMinutesHM(minutesUntil)}.` };
  }
  return { description, context: null };
}

export function amdPhaseTooltip(phase?: string | null, manipDetected?: boolean | null): TooltipContent {
  const description = "AMD Cycle (Wyckoff). Accumulation = smart money buying; Manipulation = false move to sweep stops; Distribution = smart money selling.";
  if (!phase) return { description, context: null };
  const phaseMap: Record<string, string> = {
    accumulation: "Accumulation — potential base forming; look for long setups after manipulation.",
    manipulation: "Manipulation — stop hunt underway; wait for direction confirmation.",
    distribution: "Distribution — smart money offloading; look for short setups.",
  };
  const manip = manipDetected ? " Manipulation candle detected." : "";
  return { description, context: `${phaseMap[phase] ?? phase}${manip}` };
}

function _zoneTooltip(description: string, high?: number | null, low?: number | null, distAtr?: number | null): TooltipContent {
  if (high == null || low == null) return { description, context: null };
  const dist = distAtr != null ? ` (${distAtr.toFixed(1)} ATR away)` : "";
  return { description, context: `Zone ${low.toFixed(2)}–${high.toFixed(2)}${dist}.` };
}

export function demandZoneTooltip(high?: number | null, low?: number | null, distAtr?: number | null): TooltipContent {
  return _zoneTooltip("Demand Zone. Price area where institutional buyers absorbed supply — strong impulse move originated here. Price often returns to re-test.", high, low, distAtr);
}

export function supplyZoneTooltip(high?: number | null, low?: number | null, distAtr?: number | null): TooltipContent {
  return _zoneTooltip("Supply Zone. Price area where institutional sellers overwhelmed buyers — strong impulse move down originated here. Price often returns to re-test.", high, low, distAtr);
}

export function breakerBlockTooltip(type?: number | null, distAtr?: number | null): TooltipContent {
  const description = "Breaker Block. A mitigated order block that has flipped polarity — now acts as resistance (bearish breaker) or support (bullish breaker).";
  if (type == null) return { description, context: null };
  const dir = type > 0 ? "Bullish breaker" : "Bearish breaker";
  const dist = distAtr != null ? ` (${distAtr.toFixed(1)} ATR away)` : "";
  return { description, context: `${dir}${dist} — flipped order block, expect reaction.` };
}

export function premiumDiscountPctTooltip(pct?: number | null): TooltipContent {
  const description = "Premium / Discount %. Position within the swing range relative to equilibrium (midpoint). Positive = premium (expensive); negative = discount (cheap).";
  if (pct == null) return { description, context: null };
  if (pct > 25) return { description, context: `+${pct.toFixed(1)}% — Deep premium. Favour shorts or wait for discount.` };
  if (pct > 0) return { description, context: `+${pct.toFixed(1)}% — Mild premium. Above equilibrium.` };
  if (pct < -25) return { description, context: `${pct.toFixed(1)}% — Deep discount. Favour longs or wait for premium.` };
  return { description, context: `${pct.toFixed(1)}% — Mild discount. Below equilibrium.` };
}
