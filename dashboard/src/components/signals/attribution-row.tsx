// dashboard/src/components/signals/attribution-row.tsx
"use client";

import { useState, useEffect } from "react";
import { getApiBase, fetchJson } from "@/lib/api";
import type { SignalAttributionData, AttributionGroup } from "@/lib/types";
import { fmtNum } from "@/lib/format";

// ── P-value table ──
function PValueCell({ p }: { p: number | null }) {
  if (p === null) return <span className="text-[var(--text-muted)]">—</span>;
  const sig = p < 0.05;
  return (
    <span
      className="font-data text-[0.65rem]"
      style={{ color: sig ? "var(--cyan)" : "var(--text-secondary)" }}
    >
      {p.toFixed(3)}
      {sig && " *"}
    </span>
  );
}

function AttributionTable({
  title,
  data,
  onRowClick,
}: {
  title: string;
  data: AttributionGroup[];
  onRowClick: (name: string) => void;
}) {
  return (
    <div className="flex-1 min-w-0">
      <div className="text-[0.6rem] font-bold uppercase tracking-widest text-[var(--text-muted)] mb-2 px-1">
        {title}
      </div>
      <table className="w-full text-[0.65rem]" style={{ borderCollapse: "collapse" }}>
        <thead>
          <tr className="text-[var(--text-muted)]" style={{ borderBottom: "1px solid var(--border-subtle)" }}>
            <th className="text-left py-1 px-1 font-semibold">Setup</th>
            <th className="text-right py-1 px-1 font-semibold">N</th>
            <th className="text-right py-1 px-1 font-semibold">Win%</th>
            <th className="text-right py-1 px-1 font-semibold">Avg R</th>
            <th className="text-right py-1 px-1 font-semibold">Sharpe</th>
            <th className="text-right py-1 px-1 font-semibold">p-val</th>
          </tr>
        </thead>
        <tbody>
          {data.map((g) => (
            <tr
              key={g.name}
              className="cursor-pointer hover:bg-[var(--bg-elevated)] transition-colors"
              onClick={() => onRowClick(g.name)}
              style={{ borderBottom: "1px solid var(--border-subtle)" }}
            >
              <td className="py-1 px-1 font-data text-[var(--text-secondary)] truncate max-w-[160px]">
                {g.name.replace(/^(trad_|ind_|smc_)/, "")}
              </td>
              <td className="py-1 px-1 text-right font-data text-[var(--text-muted)]">{g.n}</td>
              <td className="py-1 px-1 text-right font-data"
                style={{ color: g.win_rate != null && g.win_rate >= 0.5 ? "var(--green)" : "var(--red)" }}>
                {g.win_rate != null ? `${fmtNum(g.win_rate * 100, 1)}%` : "—"}
              </td>
              <td className="py-1 px-1 text-right font-data"
                style={{ color: g.avg_pnl_r != null ? g.avg_pnl_r >= 0 ? "var(--green)" : "var(--red)" : "var(--text-muted)" }}>
                {g.avg_pnl_r != null ? (g.avg_pnl_r >= 0 ? "+" : "") + fmtNum(g.avg_pnl_r, 3) : "—"}
              </td>
              <td className="py-1 px-1 text-right font-data text-[var(--text-secondary)]">
                {g.sharpe_proxy != null ? fmtNum(g.sharpe_proxy, 2) : "—"}
              </td>
              <td className="py-1 px-1 text-right"><PValueCell p={g.p_value} /></td>
            </tr>
          ))}
          {data.length === 0 && (
            <tr><td colSpan={6} className="py-4 text-center text-[var(--text-muted)] italic">No data</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export function AttributionRow({
  onSetupClick,
  onAssetClassClick,
}: {
  onSetupClick: (setup: string) => void;
  onAssetClassClick: (ac: string) => void;
}) {
  const [setupData, setSetupData] = useState<SignalAttributionData | null>(null);
  const [acData, setAcData] = useState<SignalAttributionData | null>(null);

  useEffect(() => {
    const base = getApiBase();
    Promise.all([
      fetchJson(`${base}/api/signals/attribution?window=30d&group_by=setup`),
      fetchJson(`${base}/api/signals/attribution?window=30d&group_by=asset_class`),
    ]).then(([setup, ac]) => {
      setSetupData(setup);
      setAcData(ac);
    }).catch((err) => {
      console.error("Failed to fetch attribution data:", err);
    });
  }, []);

  return (
    <div
      className="flex gap-4 p-3 rounded"
      style={{ background: "var(--bg-surface)", border: "1px solid var(--border-subtle)" }}
    >
      <AttributionTable
        title="Setup Alpha (30d)"
        data={setupData?.groups ?? []}
        onRowClick={onSetupClick}
      />
      <div className="w-px bg-[var(--border-subtle)] shrink-0" />
      <AttributionTable
        title="Asset Class Alpha (30d)"
        data={acData?.groups ?? []}
        onRowClick={onAssetClassClick}
      />
    </div>
  );
}
