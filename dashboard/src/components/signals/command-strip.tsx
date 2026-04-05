// dashboard/src/components/signals/command-strip.tsx
"use client";

import { useState, useEffect } from "react";
import { getApiBase } from "@/lib/api";
import type { SignalStatsData } from "@/lib/types";
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

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch(`${getApiBase()}/api/signals/stats`);
        if (res.ok) setStats(await res.json());
      } catch {
        // fail silently — show dashes
      }
    };
    load();
    const interval = setInterval(load, 60_000);
    return () => clearInterval(interval);
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
    </div>
  );
}
