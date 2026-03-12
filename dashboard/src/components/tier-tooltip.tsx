// dashboard/src/components/tier-tooltip.tsx
"use client";

import type { ReactNode } from "react";
import { Tooltip } from "@/components/tooltip";

export type TierKey = "I1" | "I2" | "I3" | "I4" | "I5" | "SMC" | "I6" | "I7" | "I8";

const TIER_COPY: Record<TierKey, string> = {
  I1: "Technical Indicators — 25 indicators (RSI, MACD, Bollinger, ATR, ADX, HMA, etc.). Foundation: raw math on price/volume.",
  I2: "Derivative Events — Acceleration, exhaustion, momentum regime. Second-derivative layer: what's happening to the indicators.",
  I3: "Market Structure — Swing points, S/R levels, trend integrity, Fibonacci, VWAP, session levels.",
  I4: "Statistical Context — GARCH volatility, Kalman trend, HMM regime, BOCPD change detection. Adaptive statistical models.",
  I5: "Pattern Detection — RSI divergence, BB squeeze, candlestick patterns, volume divergence. Structural setups forming.",
  SMC: "Smart Money Concepts — BOS/CHoCH, FVG, order blocks, sweeps, killzones, AMD phase, premium/discount.",
  I6: "Confluence Score — Cross-timeframe alignment: how many TFs agree with the current signal direction.",
  I7: "Signal Generator — 17 setup plugins competing per bar. Winner selected by CIS composite scoring + regime eligibility.",
  I8: "AI Narrative — LLM synthesis of I1–I7 outputs into a structured trading context. Three-tier: action tag → short → deep.",
};

interface TierTooltipProps {
  tier: TierKey;
  children: ReactNode;
}

export function TierTooltip({ tier, children }: TierTooltipProps) {
  return (
    <Tooltip tooltip={{ description: TIER_COPY[tier], context: null }}>
      <span style={{ borderBottom: "1px dotted currentColor", cursor: "help" }}>
        {children}
      </span>
    </Tooltip>
  );
}
