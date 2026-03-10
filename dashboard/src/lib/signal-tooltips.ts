// dashboard/src/lib/signal-tooltips.ts
// Shared tooltip definitions for signal display components
// Single source of truth for all signal-related tooltips to avoid duplication

import type { TooltipContent } from "../components/tooltip";

export function barTimeTooltip(): TooltipContent {
  return {
    description: "BAR: Time when candle closed and triggered analysis cascade.",
    context: null,
  };
}

export function sigTimeTooltip(): TooltipContent {
  return {
    description: "SIG: Time when signal_generator_service completed calculations.",
    context: null,
  };
}

export function ttsTooltip(): TooltipContent {
  return {
    description: "TTS: Time-to-signal (pipeline lag).",
    context: null,
  };
}

export function barClosePriceTooltip(): TooltipContent {
  return {
    description: "Bar close price: Close price of candle that triggered analysis.",
    context: null,
  };
}

export function marketPriceTooltip(): TooltipContent {
  return {
    description: "Market price at signal: Live bid/ask when signal was generated.",
    context: null,
  };
}

export function entryTooltip(): TooltipContent {
  return {
    description: "E: Recommended entry price.",
    context: null,
  };
}

export function slTooltip(): TooltipContent {
  return {
    description: "SL: Stop-loss price level.",
    context: null,
  };
}

export function t1Tooltip(): TooltipContent {
  return {
    description: "T1: First profit target.",
    context: null,
  };
}

export function t2Tooltip(): TooltipContent {
  return {
    description: "T2: Second profit target.",
    context: null,
  };
}

export function t3Tooltip(): TooltipContent {
  return {
    description: "T3: Third profit target (structural signals only).",
    context: null,
  };
}

export function rrTooltip(): TooltipContent {
  return {
    description: "R: Risk-reward ratio.",
    context: null,
  };
}

export function zoneTooltip(): TooltipContent {
  return {
    description: "ZONE: Optimal entry range — enter between low-high for best risk-reward.",
    context: null,
  };
}

export function exitTooltip(): TooltipContent {
  return {
    description: "X: Exit price (signal closed/resolved).",
    context: null,
  };
}

export function timestampTooltip(): TooltipContent {
  return {
    description: "Timestamp: When signal was published to the stream.",
    context: null,
  };
}
