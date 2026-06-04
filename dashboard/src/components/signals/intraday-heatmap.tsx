"use client";

import { useState, useEffect } from "react";
import { getApiBase } from "@/lib/api";
import type { IntradayCell } from "@/lib/types";
import { fmtNum } from "@/lib/format";

const DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri"];
const HOURS = [8, 9, 10, 11, 12, 13, 14, 15, 16, 17];

function cellBg(avgR: number | null, n: number): string {
  if (avgR == null || n === 0) return "var(--bg-elevated)";
  const opacity = Math.min(1, n / 50) * 0.7 + 0.15;
  const intensity = Math.min(1, Math.abs(avgR) / 0.25);
  const a = (opacity * intensity).toFixed(2);
  return avgR > 0 ? `rgba(0,220,130,${a})` : `rgba(255,71,87,${a})`;
}

export function IntradayHeatMap() {
  const [cells, setCells] = useState<IntradayCell[]>([]);

  useEffect(() => {
    fetch(`${getApiBase()}/api/signals/intraday-heatmap`)
      .then(r => r.ok ? r.json() : { cells: [] })
      .then(d => setCells(d.cells ?? []))
      .catch(() => {});
  }, []);

  const lookup = new Map<string, IntradayCell>();
  for (const c of cells) lookup.set(`${c.hour}|${c.dow}`, c);

  if (cells.length === 0) {
    return (
      <div className="flex items-center justify-center h-[100px]"
        style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "4px" }}>
        <span className="text-[0.6rem] text-[var(--text-muted)] italic">Loading…</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1.5 p-3 rounded"
      style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}>
      <span className="text-[0.52rem] font-bold uppercase tracking-widest text-[var(--text-muted)]">Intraday Edge</span>
      <div className="flex items-center gap-0.5" style={{ paddingLeft: "28px" }}>
        {DOW_LABELS.map(d => (
          <div key={d} className="text-[0.45rem] font-semibold text-[var(--text-muted)] text-center" style={{ width: "36px" }}>{d}</div>
        ))}
      </div>
      {HOURS.map(hour => (
        <div key={hour} className="flex items-center gap-0.5">
          <div className="text-[0.45rem] text-[var(--text-muted)] text-right shrink-0" style={{ width: "24px" }}>{hour}:00</div>
          {[1, 2, 3, 4, 5].map(dow => {
            const cell = lookup.get(`${hour}|${dow}`) ?? null;
            return (
              <div key={dow}
                className="flex items-center justify-center rounded text-[0.42rem] font-data shrink-0"
                style={{
                  width: "36px", height: "16px",
                  backgroundColor: cellBg(cell?.avg_r ?? null, cell?.n ?? 0),
                  color: "var(--text-primary)",
                  opacity: (cell?.n ?? 0) === 0 ? 0.2 : 1,
                }}
                title={cell ? `N=${cell.n}  Avg R ${fmtNum(cell.avg_r ?? 0, 3)}` : "No data"}>
                {cell?.avg_r != null ? ((cell.avg_r >= 0 ? "+" : "") + fmtNum(cell.avg_r, 2)) : ""}
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
