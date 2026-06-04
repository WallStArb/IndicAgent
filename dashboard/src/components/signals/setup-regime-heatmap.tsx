"use client";

import { useState, useEffect, useMemo } from "react";
import { getApiBase } from "@/lib/api";
import type { HeatMapCell } from "@/lib/types";
import { fmtNum } from "@/lib/format";

const REGIME_LABELS = ["Trend", "Range", "Vol"];

type Metric = "avg_r" | "win_rate";

function cellBg(value: number | null, n: number): string {
  if (value == null || n === 0) return "var(--bg-elevated)";
  const nOpacity = Math.min(1, n / 30) * 0.75 + 0.15;
  const intensity = Math.min(1, Math.abs(value) / 0.3);
  const alpha = nOpacity * intensity;
  if (value > 0) return `rgba(0, 220, 130, ${alpha.toFixed(2)})`;
  return `rgba(255, 71, 87, ${alpha.toFixed(2)})`;
}

function cellText(value: number | null, metric: Metric): string {
  if (value == null) return "—";
  if (metric === "avg_r") return (value >= 0 ? "+" : "") + fmtNum(value, 2) + "R";
  return fmtNum(value * 100, 1) + "%";
}

export function SetupRegimeHeatMap({
  onCellClick,
}: {
  onCellClick?: (setup: string, regime: number) => void;
}) {
  const [cells, setCells] = useState<HeatMapCell[]>([]);
  const [metric, setMetric] = useState<Metric>("avg_r");

  useEffect(() => {
    fetch(`${getApiBase()}/api/signals/heatmap`)
      .then(r => r.ok ? r.json() : { cells: [] })
      .then(d => setCells(d.cells ?? []))
      .catch(() => {});
  }, []);

  const { setups, grid } = useMemo(() => {
    const seenSetups: string[] = [];
    const lookup = new Map<string, HeatMapCell>();
    for (const c of cells) {
      const key = `${c.setup_plugin}|${c.regime}`;
      lookup.set(key, c);
      if (!seenSetups.includes(c.setup_plugin)) seenSetups.push(c.setup_plugin);
    }
    return {
      setups: seenSetups.slice(0, 15),
      grid: (setup: string, regime: number) => lookup.get(`${setup}|${regime}`) ?? null,
    };
  }, [cells]);

  if (setups.length === 0) {
    return (
      <div className="flex items-center justify-center h-[160px]"
        style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "4px" }}>
        <span className="text-[0.6rem] text-[var(--text-muted)] italic">Loading heat map…</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 p-3 rounded"
      style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}>
      <div className="flex items-center justify-between">
        <span className="text-[0.52rem] font-bold uppercase tracking-widest text-[var(--text-muted)]">
          Setup × Regime
        </span>
        <div className="flex gap-1">
          {(["avg_r", "win_rate"] as Metric[]).map(m => (
            <button key={m} onClick={() => setMetric(m)}
              className="text-[0.5rem] px-1.5 py-0.5 rounded font-semibold"
              style={{
                background: metric === m ? "var(--bg-elevated)" : "transparent",
                color: metric === m ? "var(--text-primary)" : "var(--text-muted)",
                border: `1px solid ${metric === m ? "var(--border-default)" : "var(--border-subtle)"}`,
              }}>
              {m === "avg_r" ? "Avg R" : "Win%"}
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-0.5" style={{ paddingLeft: "120px" }}>
        {REGIME_LABELS.map(l => (
          <div key={l} className="text-[0.48rem] font-semibold uppercase text-[var(--text-muted)] text-center"
            style={{ width: "64px" }}>
            {l}
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-0.5">
        {setups.map(setup => (
          <div key={setup} className="flex items-center gap-0.5">
            <div className="text-[0.52rem] font-data text-[var(--text-secondary)] truncate shrink-0"
              style={{ width: "116px" }} title={setup}>
              {setup.replace(/^(trad_|ind_|smc_)/, "")}
            </div>
            {[0, 1, 2].map(regime => {
              const cell = grid(setup, regime);
              const value = cell ? (metric === "avg_r" ? cell.avg_r : cell.win_rate) : null;
              const n = cell?.n ?? 0;
              return (
                <div key={regime}
                  onClick={() => cell && onCellClick?.(setup, regime)}
                  className="flex items-center justify-center rounded text-[0.5rem] font-data font-bold shrink-0"
                  style={{
                    width: "64px", height: "20px",
                    backgroundColor: cellBg(value, n),
                    color: value != null && value !== 0 ? "var(--text-primary)" : "var(--text-muted)",
                    cursor: cell ? "pointer" : "default",
                    opacity: n === 0 ? 0.2 : 1,
                  }}
                  title={cell ? `N=${cell.n}  Win ${fmtNum((cell.win_rate ?? 0) * 100, 1)}%  Avg R ${fmtNum(cell.avg_r ?? 0, 3)}` : "No data"}>
                  {cellText(value, metric)}
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
