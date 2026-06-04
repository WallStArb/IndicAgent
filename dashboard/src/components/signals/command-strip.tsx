// dashboard/src/components/signals/command-strip.tsx
"use client";

import { useState, useEffect } from "react";
import { getApiBase } from "@/lib/api";
import type { SignalStatsData, ActiveSignal, RecentOutcome } from "@/lib/types";
import { fmtNum } from "@/lib/format";

function StatPill({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: string;
  sub?: string;
  color: string;
}) {
  return (
    <div
      className="flex flex-col gap-0.5 px-4 py-2 border-r border-[var(--border-subtle)] last:border-r-0 min-w-[120px]"
    >
      <span className="text-[0.5rem] font-semibold uppercase tracking-widest text-[var(--text-muted)]">
        {label}
      </span>
      <span
        className="text-sm font-bold font-data leading-none"
        style={{ color }}
      >
        {value}
      </span>
      {sub && (
        <span className="text-sm font-data text-[var(--text-muted)]">{sub}</span>
      )}
    </div>
  );
}

function SkewPill({ signals }: { signals: ActiveSignal[] }) {
  const longs = signals.filter(s => s.direction === 1).length;
  const shorts = signals.filter(s => s.direction === -1).length;
  const total = longs + shorts;
  if (total === 0) return null;
  const longPct = longs / total;
  const skewed = longPct >= 0.9 || longPct <= 0.1;
  return (
    <div className="flex flex-col gap-0.5 px-4 py-2 border-r border-[var(--border-subtle)] min-w-[100px]">
      <span className="text-[0.5rem] font-semibold uppercase tracking-widest text-[var(--text-muted)]">
        Live Skew
      </span>
      <span className="text-sm font-bold font-data leading-none"
        style={{ color: skewed ? "var(--amber)" : "var(--text-secondary)" }}>
        ▲{longs} / ▼{shorts}
      </span>
      <div className="h-1 rounded overflow-hidden bg-[var(--bg-elevated)] mt-0.5" style={{ width: "60px" }}>
        <div className="h-full rounded"
          style={{ width: `${longPct * 100}%`, backgroundColor: "var(--green)" }} />
      </div>
    </div>
  );
}

function StreakBar({ outcomes }: { outcomes: RecentOutcome[] }) {
  if (!outcomes || outcomes.length === 0) return null;
  const WIN_OUTCOMES = new Set(["target_1", "target_1_2", "target_full"]);
  return (
    <div className="flex flex-col gap-0.5 px-4 py-2 border-r border-[var(--border-subtle)] min-w-[140px]">
      <span className="text-[0.5rem] font-semibold uppercase tracking-widest text-[var(--text-muted)]">
        Last 10
      </span>
      <div className="flex gap-0.5 items-center mt-0.5">
        {outcomes.map((o, i) => {
          const isWin = WIN_OUTCOMES.has(o.outcome);
          const isExpired = o.outcome === "never_activated" || o.outcome === "ttl_expired";
          const bg = isWin ? "var(--green)" : isExpired ? "var(--text-muted)" : "var(--red)";
          return (
            <div key={i} className="w-3 h-3 rounded-sm"
              style={{ backgroundColor: bg, opacity: 0.85 }}
              title={`${o.outcome}${o.pnl_r != null ? ` (${o.pnl_r >= 0 ? "+" : ""}${o.pnl_r.toFixed(1)}R)` : ""}`}
            />
          );
        })}
      </div>
    </div>
  );
}

function latencyColor(p50: number | null): string {
  if (p50 === null) return "var(--text-muted)";
  if (p50 < 10) return "var(--green)";
  if (p50 < 30) return "var(--amber)";
  return "var(--red)";
}

function edgeTrendColor(trend: string): string {
  if (trend === "expanding") return "var(--green)";
  if (trend === "compressing") return "var(--red)";
  return "var(--text-muted)";
}

export function CommandStrip() {
  const [stats, setStats] = useState<SignalStatsData | null>(null);
  const [activeSignals, setActiveSignals] = useState<ActiveSignal[]>([]);

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch(`${getApiBase()}/api/signals/stats`);
        if (res.ok) setStats(await res.json());
      } catch {
        // fail silently — show dashes
      }
    };
    const loadActive = async () => {
      try {
        const res = await fetch(`${getApiBase()}/api/signals/active`);
        if (res.ok) {
          const d = await res.json();
          setActiveSignals(d.signals ?? []);
        }
      } catch {
        // fail silently
      }
    };
    load();
    loadActive();
    const interval = setInterval(load, 60_000);
    const activeInterval = setInterval(loadActive, 30_000);
    return () => {
      clearInterval(interval);
      clearInterval(activeInterval);
    };
  }, []);

  const s = stats;
  const heroRatePct = s ? `${fmtNum(s.hero_rate * 100, 1)}%` : "—";
  const heroRateTrend = s && typeof s.hero_rate_trend === 'number' && s.hero_rate_trend !== null
    ? (s.hero_rate_trend > 0 ? `↑ ${fmtNum(s.hero_rate_trend * 100, 1)}%` : `↓ ${fmtNum(Math.abs(s.hero_rate_trend) * 100, 1)}%`)
    : undefined;
  const confToday = s?.avg_confidence != null ? fmtNum(s.avg_confidence, 3) : "—";
  const conf7d = s?.avg_confidence_7d != null ? `7d avg ${fmtNum(s.avg_confidence_7d, 3)}` : undefined;
  const latP50 = s?.pipeline_latency_p50 != null ? `${fmtNum(s.pipeline_latency_p50, 1)}s` : "—";
  const latP95 = s?.pipeline_latency_p95 != null ? `p95 ${fmtNum(s.pipeline_latency_p95, 1)}s` : undefined;
  const alpha7d = s?.alpha_7d != null ? (s.alpha_7d >= 0 ? `+${fmtNum(s.alpha_7d, 3)}R` : `${fmtNum(s.alpha_7d, 3)}R`) : undefined;
  const alpha30d = s?.alpha_30d != null ? `30d ${s.alpha_30d >= 0 ? "+" : ""}${fmtNum(s.alpha_30d, 3)}R` : undefined;

  return (
    <div className="flex items-stretch overflow-x-auto" style={{ scrollbarWidth: "none" }}>
      <StatPill
        label="Signals / session"
        value={s ? String(s.signals_today) : "—"}
        sub={s ? `prev ${s.signals_prev_session}` : undefined}
        color="var(--blue)"
      />
      <StatPill
        label="Hero rate"
        value={heroRatePct}
        sub={heroRateTrend}
        color={s && s.hero_rate_trend !== null && s.hero_rate_trend > 0 ? "var(--amber)" : "var(--text-secondary)"}
      />
      <StatPill
        label="Avg confidence"
        value={confToday}
        sub={conf7d}
        color="var(--text-secondary)"
      />
      <StatPill
        label="P50 latency"
        value={latP50}
        color={latencyColor(s?.pipeline_latency_p50 ?? null)}
      />
      <StatPill
        label="P95 latency"
        value={latP95 ?? "—"}
        color={latencyColor(s?.pipeline_latency_p95 ?? null)}
      />
      <StatPill
        label="7d alpha"
        value={alpha7d ?? "—"}
        color="var(--text-secondary)"
      />
      <StatPill
        label="30d alpha"
        value={alpha30d ?? "—"}
        color="var(--text-secondary)"
      />
      <SkewPill signals={activeSignals} />
      {s?.recent_outcomes && <StreakBar outcomes={s.recent_outcomes} />}
    </div>
  );
}
