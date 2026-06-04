"use client";

import { useState, useEffect, useMemo } from "react";
import { getApiBase } from "@/lib/api";
import type { ActiveSignal } from "@/lib/types";
import { fmtNum } from "@/lib/format";
import { TrendingUp, TrendingDown, AlertTriangle, Zap } from "lucide-react";

const REGIME_LABELS: Record<number, string> = { 0: "TREND", 1: "RANGE", 2: "VOL" };
const REGIME_COLORS: Record<number, string> = {
  0: "var(--green)",
  1: "var(--amber)",
  2: "var(--red)",
};

const BUCKET_ORDER = ["trend", "momentum", "structure", "institutional", "regime", "pattern"];

function RegimeBadge({ regime }: { regime: number | null }) {
  if (regime == null) return null;
  return (
    <span className="text-[0.48rem] font-bold px-1 py-0.5 rounded"
      style={{
        color: REGIME_COLORS[regime] ?? "var(--text-muted)",
        border: `1px solid ${REGIME_COLORS[regime] ?? "var(--border-subtle)"}`,
        backgroundColor: "rgba(0,0,0,0.3)",
      }}>
      {REGIME_LABELS[regime] ?? `R${regime}`}
    </span>
  );
}

function CISBucketBars({ buckets }: { buckets: Record<string, number> | null }) {
  if (!buckets) return null;
  const sorted = BUCKET_ORDER
    .filter(k => k in buckets)
    .map(k => ({ key: k, val: buckets[k] }))
    .sort((a, b) => Math.abs(b.val) - Math.abs(a.val))
    .slice(0, 2);

  return (
    <div className="flex flex-col gap-0.5">
      {sorted.map(({ key, val }) => (
        <div key={key} className="flex items-center gap-1">
          <span className="text-[0.45rem] text-[var(--text-muted)] w-[52px] shrink-0 truncate">{key}</span>
          <div className="flex-1 h-1 rounded overflow-hidden bg-[var(--bg-elevated)]">
            <div className="h-full rounded"
              style={{
                width: `${Math.min(100, Math.abs(val) * 100)}%`,
                backgroundColor: val >= 0 ? "var(--green)" : "var(--red)",
              }} />
          </div>
          <span className="text-[0.45rem] font-data w-[28px] text-right shrink-0"
            style={{ color: val >= 0 ? "var(--green)" : "var(--red)" }}>
            {val >= 0 ? "+" : ""}{fmtNum(val, 2)}
          </span>
        </div>
      ))}
    </div>
  );
}

function AgeDots({ barsElapsed, ttlBars }: { barsElapsed: number; ttlBars: number }) {
  const DOTS = 10;
  const filled = Math.min(DOTS, Math.round((barsElapsed / Math.max(ttlBars, 1)) * DOTS));
  const ratio = barsElapsed / Math.max(ttlBars, 1);
  const color = ratio < 0.5 ? "var(--text-secondary)" : ratio < 0.8 ? "var(--amber)" : "var(--red)";
  return (
    <span className="flex gap-0.5 items-center">
      {Array.from({ length: DOTS }, (_, i) => (
        <span key={i} className="inline-block w-1.5 h-1.5 rounded-full"
          style={{ backgroundColor: i < filled ? color : "var(--bg-elevated)" }} />
      ))}
    </span>
  );
}

function SignalCard({
  signal,
  isConflict,
  allActive,
}: {
  signal: ActiveSignal;
  isConflict: boolean;
  allActive: ActiveSignal[];
}) {
  const isHero = signal.signal_tier === "hero";
  const isLong = signal.direction === 1;
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!signal.signal_computed_at) return;
    const firedAt = new Date(signal.signal_computed_at).getTime();
    const tick = () => setElapsed(Math.floor((Date.now() - firedAt) / 60000));
    tick();
    const id = setInterval(tick, 30_000);
    return () => clearInterval(id);
  }, [signal.signal_computed_at]);

  const isRecent = elapsed < 5;
  const rr = signal.risk_reward_ratio;
  const ttlBars = signal.ttl_bars ?? 10;

  const hasRegimeShift = allActive.some(
    s => s.signal_id !== signal.signal_id
      && s.symbol === signal.symbol
      && s.timeframe === signal.timeframe
      && s.hmm_regime_at_fire !== signal.hmm_regime_at_fire
  );

  const isStale = signal.staleness_score != null && signal.staleness_score > 0;

  return (
    <div
      className="shrink-0 flex flex-col gap-1.5 p-2 rounded"
      style={{
        width: "188px",
        background: "var(--bg-surface)",
        border: `1px solid ${isHero ? "var(--blue)" : "var(--border-subtle)"}`,
        borderLeft: `3px solid ${isHero ? "var(--blue)" : "transparent"}`,
        boxShadow: isHero ? "0 0 12px rgba(59,130,246,0.12)" : undefined,
      }}
    >
      <div className="flex items-center justify-between gap-1">
        <div className="flex items-center gap-1">
          {isRecent && (
            <span className="w-1.5 h-1.5 rounded-full animate-pulse shrink-0"
              style={{ backgroundColor: "var(--blue)" }} />
          )}
          <span className="text-[0.75rem] font-bold font-data"
            style={{ color: isLong ? "var(--green)" : "var(--red)" }}>
            {signal.symbol}
          </span>
          {isLong
            ? <TrendingUp size={10} style={{ color: "var(--green)" }} />
            : <TrendingDown size={10} style={{ color: "var(--red)" }} />}
        </div>
        <div className="flex items-center gap-1">
          <RegimeBadge regime={signal.hmm_regime_at_fire} />
          <span className="text-[0.45rem] text-[var(--text-muted)]">{signal.timeframe}</span>
        </div>
      </div>

      <div className="text-[0.52rem] text-[var(--text-secondary)] truncate">
        {signal.setup_plugin.replace(/^(trad_|ind_|smc_)/, "")}
      </div>

      <div className="flex flex-col gap-0.5">
        <span className="text-[0.55rem] font-data font-bold"
          style={{ color: (signal.cis_score ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
          CIS {signal.cis_score != null ? ((signal.cis_score >= 0 ? "+" : "") + fmtNum(signal.cis_score, 2)) : "—"}
        </span>
        <CISBucketBars buckets={signal.bucket_scores} />
      </div>

      <div className="flex gap-1 text-[0.52rem] font-data">
        <span className="text-[var(--text-muted)]">E</span>
        <span className="text-[var(--text-primary)]">{signal.entry_price != null ? fmtNum(signal.entry_price, 2) : "—"}</span>
        <span className="text-[var(--text-muted)]">SL</span>
        <span style={{ color: "var(--red)" }}>{signal.stop_loss != null ? fmtNum(signal.stop_loss, 2) : "—"}</span>
        <span className="text-[var(--text-muted)]">T1</span>
        <span style={{ color: "var(--green)" }}>{signal.profit_target != null ? fmtNum(signal.profit_target, 2) : "—"}</span>
      </div>

      <div className="flex items-center justify-between">
        <span className="text-[0.5rem] font-data text-[var(--text-secondary)]">
          {rr != null ? `R:R ${fmtNum(rr, 1)}x` : ""}
        </span>
        <AgeDots barsElapsed={elapsed} ttlBars={ttlBars} />
        <span className="text-[0.48rem] text-[var(--text-muted)]">{elapsed}b</span>
      </div>

      {(isConflict || hasRegimeShift || isStale) && (
        <div className="flex gap-1 flex-wrap">
          {isConflict && (
            <span className="flex items-center gap-0.5 text-[0.45rem] px-1 py-0.5 rounded"
              style={{ color: "var(--red)", border: "1px solid var(--red)", backgroundColor: "rgba(255,71,87,0.08)" }}>
              <Zap size={8} /> CONFLICT
            </span>
          )}
          {hasRegimeShift && (
            <span className="flex items-center gap-0.5 text-[0.45rem] px-1 py-0.5 rounded"
              style={{ color: "var(--amber)", border: "1px solid var(--amber)", backgroundColor: "rgba(245,158,11,0.08)" }}>
              <AlertTriangle size={8} /> REGIME SHIFT
            </span>
          )}
          {isStale && (
            <span className="flex items-center gap-0.5 text-[0.45rem] px-1 py-0.5 rounded"
              style={{ color: "var(--amber)", border: "1px solid var(--amber)", backgroundColor: "rgba(245,158,11,0.08)" }}>
              <AlertTriangle size={8} /> STALE
            </span>
          )}
        </div>
      )}
    </div>
  );
}

export function LiveSignalCards() {
  const [signals, setSignals] = useState<ActiveSignal[]>([]);

  useEffect(() => {
    const load = async () => {
      try {
        const res = await fetch(`${getApiBase()}/api/signals/active`);
        if (res.ok) {
          const d = await res.json();
          setSignals(d.signals ?? []);
        }
      } catch { /* fail silently */ }
    };
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, []);

  const sorted = useMemo(() => {
    return [...signals].sort((a, b) => {
      const tierOrder: Record<string, number> = { hero: 0, monitored: 1, candidate: 2 };
      const ta = tierOrder[a.signal_tier] ?? 3;
      const tb = tierOrder[b.signal_tier] ?? 3;
      if (ta !== tb) return ta - tb;
      return Math.abs(b.cis_score ?? 0) - Math.abs(a.cis_score ?? 0);
    });
  }, [signals]);

  const conflictIds = useMemo(() => {
    const ids = new Set<string>();
    const byKey = new Map<string, ActiveSignal[]>();
    for (const s of signals) {
      const key = `${s.symbol}|${s.timeframe}`;
      if (!byKey.has(key)) byKey.set(key, []);
      byKey.get(key)!.push(s);
    }
    for (const group of byKey.values()) {
      if (group.some(s => s.direction === 1) && group.some(s => s.direction === -1)) {
        group.forEach(s => ids.add(s.signal_id));
      }
    }
    return ids;
  }, [signals]);

  if (sorted.length === 0) {
    return (
      <div className="flex items-center justify-center h-[120px] rounded"
        style={{ border: "1px solid var(--border-subtle)", background: "var(--bg-surface)" }}>
        <span className="text-[0.62rem] text-[var(--text-muted)] italic">
          No active signals — market quiet
        </span>
      </div>
    );
  }

  return (
    <div className="flex gap-2 overflow-x-auto pb-1" style={{ scrollbarWidth: "none" }}>
      {sorted.map(sig => (
        <SignalCard
          key={sig.signal_id}
          signal={sig}
          isConflict={conflictIds.has(sig.signal_id)}
          allActive={signals}
        />
      ))}
    </div>
  );
}
