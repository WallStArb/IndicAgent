"use client";

import type { IndicatorData } from "@/lib/types";
import { fmtNum, oscClass, dirClass } from "@/lib/format";
import { Tooltip, type TooltipContent } from "@/components/tooltip";
import {
  rsiTooltip, macdTooltip, stochTooltip, cciTooltip, williamsRTooltip,
  atrTooltip, bbTooltip, mfiTooltip, obvTooltip, vwapTooltip,
  sma20Tooltip, sma50Tooltip, ema13Tooltip, ema21Tooltip,
} from "@/lib/indicator-tooltips";

interface IndicatorGridProps {
  indicators: IndicatorData | null;
}

export function IndicatorGrid({ indicators }: IndicatorGridProps) {
  const ind = indicators;

  return (
    <div className="divide-y divide-[var(--border-subtle)]">
      {/* Momentum */}
      <Zone label="MTM">
        <M
          label="RSI"
          value={fmtNum(ind?.rsi, 1)}
          cls={oscClass(ind?.rsi)}
          tooltip={rsiTooltip(ind?.rsi)}
        />
        <M
          label="MACD"
          value={fmtNum(ind?.macd, 2)}
          cls={dirClass(ind?.macd_histogram)}
          tooltip={macdTooltip(ind?.macd_histogram)}
        />
        <M
          label="Stoch"
          value={`${fmtNum(ind?.stoch_k, 0)}/${fmtNum(ind?.stoch_d, 0)}`}
          cls={oscClass(ind?.stoch_k, 80, 20)}
          tooltip={stochTooltip(ind?.stoch_k)}
        />
        <M
          label="CCI"
          value={fmtNum(ind?.cci, 0)}
          cls={dirClass(ind?.cci)}
          tooltip={cciTooltip(ind?.cci)}
        />
        <M
          label="W%R"
          value={fmtNum(ind?.williams_r, 0)}
          cls={oscClass(
            ind?.williams_r !== undefined ? -ind.williams_r : undefined,
            70,
            30
          )}
          tooltip={williamsRTooltip(ind?.williams_r)}
        />
      </Zone>

      {/* Volatility & Trend */}
      <Zone label="VOL">
        <M label="ATR" value={fmtNum(ind?.atr, 2)} tooltip={atrTooltip()} />
        <M
          label="BB"
          value={`${fmtNum(ind?.bb_lower, 0)}–${fmtNum(ind?.bb_upper, 0)}`}
          tooltip={bbTooltip()}
        />
        <M
          label="SMA20"
          value={fmtNum(ind?.sma_20, 0)}
          cls="text-[var(--text-accent)]"
          tooltip={sma20Tooltip()}
        />
        <M
          label="SMA50"
          value={fmtNum(ind?.sma_50, 0)}
          cls="text-[var(--text-accent)]"
          tooltip={sma50Tooltip()}
        />
        <M
          label="EMA13"
          value={fmtNum(ind?.ema_13, 0)}
          cls="text-[var(--text-accent)]"
          tooltip={ema13Tooltip()}
        />
        <M
          label="EMA21"
          value={fmtNum(ind?.ema_21, 0)}
          cls="text-[var(--text-accent)]"
          tooltip={ema21Tooltip()}
        />
      </Zone>

      {/* Volume */}
      <Zone label="VLME">
        <M
          label="MFI"
          value={fmtNum(ind?.mfi, 1)}
          cls={oscClass(ind?.mfi, 80, 20)}
          tooltip={mfiTooltip(ind?.mfi)}
        />
        <M label="OBV" value={fmtNum(ind?.obv, 0)} tooltip={obvTooltip()} />
        <M
          label="VWAP"
          value={fmtNum(ind?.vwap, 2)}
          cls="text-[var(--blue)]"
          tooltip={vwapTooltip()}
        />
      </Zone>
    </div>
  );
}

function Zone({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="px-2 py-1">
      <div className="flex items-start gap-2">
        <span className="zone-label shrink-0 pt-px w-10">{label}</span>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
          {children}
        </div>
      </div>
    </div>
  );
}

function M({
  label,
  value,
  cls = "text-[var(--text-accent)]",
  tooltip,
}: {
  label: string;
  value: string;
  cls?: string;
  tooltip?: TooltipContent;
}) {
  const inner = (
    <span className="inline-flex items-baseline gap-1 whitespace-nowrap">
      <span className="text-[0.55rem] font-medium uppercase tracking-wider text-[var(--text-muted)]">
        {label}
      </span>
      <span className={`font-data text-[0.7rem] font-medium ${cls}`}>
        {value}
      </span>
    </span>
  );

  if (!tooltip) return inner;
  return <Tooltip tooltip={tooltip}>{inner}</Tooltip>;
}
