"use client";

import type { ContextData } from "@/lib/types";

interface ContextPanelProps {
  context: ContextData | null;
}

/** I4 Context — compact column layout */
export function ContextPanel({ context }: ContextPanelProps) {
  const c = context;

  return (
    <div className="px-2 py-1">
      <div className="flex items-start gap-2">
        <span className="zone-label shrink-0 pt-px w-10">I4</span>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5">
          {/* Volatility regime */}
          <span className="inline-flex items-center gap-1 whitespace-nowrap">
            <span className="text-[0.55rem] font-medium uppercase tracking-wider text-[var(--text-muted)]">
              Vol
            </span>
            <VolPill regime={c?.volatility_regime} />
            {c?.vol_expanding !== undefined && (
              <span
                className={`font-data text-[0.55rem] ${c.vol_expanding ? "text-[var(--amber)]" : "text-[var(--blue)]"}`}
              >
                {c.vol_expanding ? "↑" : "↓"}
              </span>
            )}
          </span>

          {/* ATR percentile */}
          {c?.atr_percentile !== undefined && (
            <span className="inline-flex items-center gap-1 whitespace-nowrap">
              <span className="text-[0.55rem] font-medium uppercase tracking-wider text-[var(--text-muted)]">
                ATR%
              </span>
              <MiniBar value={c.atr_percentile} />
            </span>
          )}

          {/* Trend regime */}
          <span className="inline-flex items-center gap-1 whitespace-nowrap">
            <span className="text-[0.55rem] font-medium uppercase tracking-wider text-[var(--text-muted)]">
              Trend
            </span>
            <TrendLabel regime={c?.trend_regime} />
          </span>

          {/* Momentum bias */}
          <span className="inline-flex items-center gap-1 whitespace-nowrap">
            <span className="text-[0.55rem] font-medium uppercase tracking-wider text-[var(--text-muted)]">
              Mom
            </span>
            <MomGauge bias={c?.momentum_bias} dir={c?.momentum_direction} />
          </span>
        </div>
      </div>
    </div>
  );
}

function VolPill({ regime }: { regime?: string }) {
  const colors: Record<string, string> = {
    low: "bg-[var(--blue-dim)] text-[var(--blue)]",
    normal: "bg-[var(--bg-elevated)] text-[var(--text-accent)]",
    high: "bg-[var(--amber-dim)] text-[var(--amber)]",
    extreme: "bg-[var(--red-dim)] text-[var(--red)]",
  };

  return (
    <span
      className={`px-1 rounded text-[0.55rem] font-semibold uppercase tracking-wider ${colors[regime ?? ""] ?? colors.normal}`}
    >
      {regime ?? "—"}
    </span>
  );
}

function TrendLabel({ regime }: { regime?: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    strong_up: { label: "Strong▲", cls: "text-up" },
    weak_up: { label: "Weak▲", cls: "text-up opacity-60" },
    neutral: { label: "Neutral", cls: "text-neutral" },
    weak_down: { label: "Weak▼", cls: "text-down opacity-60" },
    strong_down: { label: "Strong▼", cls: "text-down" },
  };
  const e = map[regime ?? ""] ?? { label: "—", cls: "text-neutral" };
  return (
    <span className={`font-data text-[0.7rem] font-semibold ${e.cls}`}>
      {e.label}
    </span>
  );
}

function MiniBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color =
    value >= 0.8
      ? "var(--red)"
      : value >= 0.5
        ? "var(--amber)"
        : "var(--blue)";
  return (
    <>
      <div className="w-8 h-1.5 rounded-full bg-[var(--bg-base)] overflow-hidden">
        <div
          className="h-full rounded-full"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <span className="font-data text-[0.55rem] text-[var(--text-muted)]">
        {pct}
      </span>
    </>
  );
}

function MomGauge({
  bias,
}: {
  bias?: number;
  dir?: string;
}) {
  if (bias === undefined) {
    return (
      <span className="font-data text-[0.7rem] text-neutral">—</span>
    );
  }
  const color =
    bias > 0 ? "var(--green)" : bias < 0 ? "var(--red)" : "var(--text-muted)";
  return (
    <span className="font-data text-[0.7rem] font-semibold" style={{ color }}>
      {bias > 0 ? "+" : ""}
      {bias.toFixed(1)}
    </span>
  );
}
