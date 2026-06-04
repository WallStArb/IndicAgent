"use client";

import { useState, useEffect, useMemo } from "react";
import { getApiBase } from "@/lib/api";
import type { EdgeSeriesPoint } from "@/lib/types";
import { fmtNum } from "@/lib/format";

const W = 280, H = 72, PAD = { top: 8, bottom: 8, left: 4, right: 4 };

export function EdgeSparkline() {
  const [series, setSeries] = useState<EdgeSeriesPoint[]>([]);

  useEffect(() => {
    fetch(`${getApiBase()}/api/signals/edge-series`)
      .then(r => r.ok ? r.json() : { series: [] })
      .then(d => setSeries(d.series ?? []))
      .catch(() => {});
  }, []);

  const { points, zeroY, areaAbove, areaBelow, rollingPoints } = useMemo(() => {
    if (series.length < 2) return { points: "", zeroY: H / 2, areaAbove: "", areaBelow: "", rollingPoints: "" };

    const values = series.map(d => d.avg_r ?? 0);
    const minV = Math.min(0, ...values);
    const maxV = Math.max(0, ...values);
    const range = maxV - minV || 0.01;
    const innerW = W - PAD.left - PAD.right;
    const innerH = H - PAD.top - PAD.bottom;

    const sx = (i: number) => PAD.left + (i / (series.length - 1)) * innerW;
    const sy = (v: number) => PAD.top + innerH - ((v - minV) / range) * innerH;
    const zY = sy(0);

    const pts = series.map((d, i) => `${sx(i)},${sy(d.avg_r ?? 0)}`).join(" ");

    const rolling = series.map((_, i) => {
      const slice = series.slice(Math.max(0, i - 6), i + 1);
      const avg = slice.reduce((s, p) => s + (p.avg_r ?? 0), 0) / slice.length;
      return avg;
    });
    const rPts = rolling.map((v, i) => `${sx(i)},${sy(v)}`).join(" ");

    const abovePts = series.map((d, i) => ({ x: sx(i), y: sy(Math.max(0, d.avg_r ?? 0)) }));
    const above = [`${abovePts[0].x},${zY}`, ...abovePts.map(p => `${p.x},${p.y}`), `${abovePts[abovePts.length - 1].x},${zY}`].join(" ");

    const belowPts = series.map((d, i) => ({ x: sx(i), y: sy(Math.min(0, d.avg_r ?? 0)) }));
    const below = [`${belowPts[0].x},${zY}`, ...belowPts.map(p => `${p.x},${p.y}`), `${belowPts[belowPts.length - 1].x},${zY}`].join(" ");

    return { points: pts, zeroY: zY, areaAbove: above, areaBelow: below, rollingPoints: rPts };
  }, [series]);

  const last = series[series.length - 1];

  if (series.length === 0) {
    return (
      <div className="flex items-center justify-center h-[88px]"
        style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)", borderRadius: "4px" }}>
        <span className="text-[0.6rem] text-[var(--text-muted)] italic">Loading…</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-1 p-3 rounded"
      style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}>
      <div className="flex items-center justify-between">
        <span className="text-[0.52rem] font-bold uppercase tracking-widest text-[var(--text-muted)]">30d Edge</span>
        {last && (
          <span className="text-[0.55rem] font-data"
            style={{ color: (last.avg_r ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
            today {(last.avg_r ?? 0) >= 0 ? "+" : ""}{fmtNum(last.avg_r ?? 0, 3)}R
          </span>
        )}
      </div>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}>
        <line x1={PAD.left} y1={zeroY} x2={W - PAD.right} y2={zeroY}
          stroke="var(--border-default)" strokeWidth="0.5" strokeDasharray="3 3" />
        <polygon points={areaAbove} fill="rgba(0,220,130,0.08)" />
        <polygon points={areaBelow} fill="rgba(255,71,87,0.08)" />
        <polyline points={rollingPoints} fill="none" stroke="rgba(255,255,255,0.2)" strokeWidth="1" />
        <polyline points={points} fill="none" stroke="var(--cyan, #06b6d4)" strokeWidth="1.5" />
        {last && series.length > 1 && (() => {
          const values = series.map(d => d.avg_r ?? 0);
          const minV = Math.min(0, ...values);
          const maxV = Math.max(0, ...values);
          const range = maxV - minV || 0.01;
          const innerH2 = H - PAD.top - PAD.bottom;
          const lx = W - PAD.right;
          const ly = PAD.top + innerH2 - (((last.avg_r ?? 0) - minV) / range) * innerH2;
          return <circle cx={lx} cy={ly} r={3} fill={(last.avg_r ?? 0) >= 0 ? "var(--green)" : "var(--red)"} stroke="var(--bg-surface)" strokeWidth="1" />;
        })()}
      </svg>
    </div>
  );
}
