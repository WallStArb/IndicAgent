"use client";

import type { IndicatorData } from "@/lib/types";
import { fmtNum, oscClass, dirClass } from "@/lib/format";
import { Tooltip, type TooltipContent } from "@/components/tooltip";
import {
  rsiTooltip, macdTooltip, stochTooltip, cciTooltip, williamsRTooltip,
  atrTooltip, bbTooltip, mfiTooltip, obvTooltip, vwapTooltip,
  sma20Tooltip, sma50Tooltip, ema13Tooltip, ema21Tooltip,
  adxTooltip, diTooltip, supertrendTooltip, rocTooltip, aoTooltip, acTooltip,
} from "@/lib/indicator-tooltips";

interface IndicatorGridProps {
  indicators: IndicatorData | null;
}

export function IndicatorGrid({ indicators }: IndicatorGridProps) {
  const ind = indicators;

  const stDir = ind?.supertrend_dir;
  const stCls = stDir != null ? (stDir > 0 ? "text-[var(--green)]" : "text-[var(--red)]") : "text-[var(--text-accent)]";
  const stLabel = stDir != null ? (stDir > 0 ? "▲" : "▼") : "—";

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
        <M
          label="ROC"
          value={ind?.roc != null ? `${ind.roc > 0 ? "+" : ""}${fmtNum(ind.roc, 2)}%` : "—"}
          cls={dirClass(ind?.roc)}
          tooltip={rocTooltip(ind?.roc)}
        />
      </Zone>

      {/* Trend Strength */}
      <Zone label="TRND">
        <M
          label="ADX"
          value={fmtNum(ind?.adx, 1)}
          cls={ind?.adx != null && ind.adx > 25 ? "text-[var(--amber)]" : "text-[var(--text-accent)]"}
          tooltip={adxTooltip(ind?.adx)}
        />
        <M
          label="+DI/−DI"
          value={`${fmtNum(ind?.plus_di, 1)}/${fmtNum(ind?.minus_di, 1)}`}
          cls={ind?.plus_di != null && ind?.minus_di != null
            ? (ind.plus_di > ind.minus_di ? "text-[var(--green)]" : "text-[var(--red)]")
            : "text-[var(--text-accent)]"}
          tooltip={diTooltip(ind?.plus_di, ind?.minus_di)}
        />
        <M
          label="ST"
          value={stLabel}
          cls={stCls}
          tooltip={supertrendTooltip(ind?.supertrend_dir, ind?.supertrend_value)}
        />
      </Zone>

      {/* Volatility & MAs */}
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
        <M
          label="AO"
          value={fmtNum(ind?.ao, 2)}
          cls={dirClass(ind?.ao)}
          tooltip={aoTooltip(ind?.ao)}
        />
        <M
          label="AC"
          value={fmtNum(ind?.ac, 2)}
          cls={dirClass(ind?.ac)}
          tooltip={acTooltip(ind?.ac)}
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
