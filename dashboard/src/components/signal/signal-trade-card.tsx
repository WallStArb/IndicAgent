"use client";

import { useState, useEffect } from "react";
import type { SignalData } from "@/lib/types";
import { fmtPrice, fmtNum } from "@/lib/format";
import { abbreviatePlugin } from "@/lib/signal-utils";
import { getApiBase } from "@/lib/api";

const BUCKET_ORDER = ["trend", "momentum", "structure", "institutional", "regime", "pattern"];

// ── Price Ladder ──────────────────────────────────────────────────────────────

type LevelKind = "target" | "entry" | "stop" | "zone_edge";

type LevelItem = {
  id: string;
  kind: LevelKind;
  label: string;
  price: number;
  r: number | null;
  targetLabel?: string;
  zoneEdge?: "high" | "low";
  inZone?: boolean;
};

function buildLevels(signal: SignalData): LevelItem[] {
  const {
    direction, entry_price: entry, stop_loss: stop,
    profit_target: t1, profit_target_2: t2, profit_target_3: t3,
    target_labels, rr_t1, rr_t2, rr_t3,
    entry_zone_low, entry_zone_high, zone_valid_at_signal,
  } = signal;

  const isLong = direction === "long";
  const risk = Math.abs(entry - stop);
  const rAt = (p: number): number =>
    risk > 0 ? (isLong ? (p - entry) / risk : (entry - p) / risk) : 0;

  const items: LevelItem[] = [
    { id: "entry", kind: "entry", label: "ENTRY", price: entry, r: null },
    { id: "sl", kind: "stop", label: "SL", price: stop, r: -1 },
  ];

  if (t1 != null) items.push({ id: "t1", kind: "target", label: "T1", price: t1, r: rr_t1 ?? rAt(t1), targetLabel: target_labels?.[0] });
  if (t2 != null) items.push({ id: "t2", kind: "target", label: "T2", price: t2, r: rr_t2 ?? rAt(t2), targetLabel: target_labels?.[1] });
  if (t3 != null) items.push({ id: "t3", kind: "target", label: "T3", price: t3, r: rr_t3 ?? rAt(t3), targetLabel: target_labels?.[2] });

  if (entry_zone_high != null) {
    items.push({ id: "zone_h", kind: "zone_edge", label: "ZONE", price: entry_zone_high, r: rAt(entry_zone_high), zoneEdge: "high", inZone: zone_valid_at_signal });
  }
  if (entry_zone_low != null) {
    items.push({ id: "zone_l", kind: "zone_edge", label: "ZONE", price: entry_zone_low, r: rAt(entry_zone_low), zoneEdge: "low", inZone: zone_valid_at_signal });
  }

  return items.sort((a, b) => b.price - a.price);
}

const DOT_COLOR: Record<LevelKind, string> = {
  target: "var(--green)",
  entry: "var(--blue)",
  stop: "var(--red)",
  zone_edge: "var(--amber)",
};

const LABEL_COLOR: Record<LevelKind, string> = {
  target: "var(--green)",
  entry: "var(--text-primary)",
  stop: "var(--red)",
  zone_edge: "var(--amber)",
};

function TradePriceLadder({ signal }: { signal: SignalData }) {
  const levels = buildLevels(signal);
  const { framing_method, direction } = signal;
  const isLong = direction === "long";

  const zoneHigh = signal.entry_zone_high;
  const zoneLow = signal.entry_zone_low;
  const inZoneBand = (price: number) =>
    zoneHigh != null && zoneLow != null && price <= zoneHigh && price >= zoneLow;

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[0.48rem] font-bold uppercase tracking-widest text-[var(--text-muted)]">
          Price Ladder
        </span>
        {framing_method && (
          <span
            className="text-[0.45rem] font-bold uppercase tracking-widest px-1.5 py-0.5 rounded"
            style={{
              color: framing_method === "structural" ? "var(--green)" : "var(--amber)",
              border: `1px solid ${framing_method === "structural" ? "var(--green)" : "var(--amber)"}`,
              opacity: 0.7,
            }}
          >
            {framing_method === "structural" ? "structural" : "ATR fallback"}
          </span>
        )}
      </div>

      <div className="flex flex-col gap-0">
        {levels.map((item) => {
          const isZoneEdge = item.kind === "zone_edge";
          const shaded = inZoneBand(item.price) && !isZoneEdge;

          return (
            <div
              key={item.id}
              className="flex items-center gap-2 text-[0.58rem] font-data px-1 py-0.5 rounded"
              style={{
                background: shaded
                  ? isLong ? "rgba(0,220,130,0.06)" : "rgba(255,71,87,0.06)"
                  : isZoneEdge ? isLong ? "rgba(0,220,130,0.08)" : "rgba(255,71,87,0.08)"
                  : undefined,
                borderLeft: isZoneEdge ? `2px solid ${isLong ? "var(--green)" : "var(--red)"}` : "2px solid transparent",
              }}
            >
              <span className="text-[0.5rem] shrink-0" style={{ color: DOT_COLOR[item.kind] }}>
                {item.kind === "entry" ? "●" : item.kind === "zone_edge" ? "◇" : "○"}
              </span>

              <span
                className="w-[28px] font-bold text-[0.55rem] shrink-0"
                style={{ color: LABEL_COLOR[item.kind] }}
              >
                {item.label}
              </span>

              <span className="flex-1 text-[var(--text-secondary)]">
                {fmtPrice(item.price)}
              </span>

              {item.targetLabel && (
                <span className="text-[0.48rem] text-[var(--text-muted)] truncate max-w-[60px] text-right">
                  {item.targetLabel.split(" ")[0]}
                </span>
              )}

              {item.r != null && (
                <span
                  className="text-[0.55rem] font-bold w-[36px] text-right shrink-0"
                  style={{ color: item.r >= 0 ? "var(--green)" : "var(--red)" }}
                >
                  {item.r >= 0 ? "+" : ""}{fmtNum(item.r, 1)}R
                </span>
              )}

              {isZoneEdge && item.zoneEdge === "high" && (
                <span
                  className="text-[0.42rem] font-bold uppercase tracking-widest px-1 py-0.5 rounded shrink-0"
                  style={{
                    color: item.inZone ? "var(--green)" : "var(--amber)",
                    border: `1px solid ${item.inZone ? "var(--green)" : "var(--amber)"}`,
                    opacity: 0.85,
                  }}
                >
                  {item.inZone ? "IN ZONE" : "WAIT"}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Setup Edge ────────────────────────────────────────────────────────────────

function SetupEdgeLine({ signal }: { signal: SignalData }) {
  const { setup_win_rate: wr, setup_avg_pnl_r: avgR, setup_plugin } = signal;
  if (wr == null) return null;

  const winColor = wr >= 0.5 ? "var(--green)" : wr >= 0.4 ? "var(--amber)" : "var(--red)";
  const avgRColor = avgR != null && avgR > 0 ? "var(--green)" : "var(--red)";

  return (
    <div className="flex items-center gap-3 text-[0.55rem] font-data">
      {setup_plugin && (
        <span className="text-[var(--text-muted)] truncate flex-1">
          {abbreviatePlugin(setup_plugin)}
        </span>
      )}
      <span>
        Win{" "}
        <span className="font-bold" style={{ color: winColor }}>
          {fmtNum(wr * 100, 1)}%
        </span>
      </span>
      {avgR != null && (
        <span>
          Avg{" "}
          <span className="font-bold" style={{ color: avgRColor }}>
            {avgR >= 0 ? "+" : ""}{fmtNum(avgR, 2)}R
          </span>
        </span>
      )}
    </div>
  );
}

// ── CIS Bucket Breakdown (lazy fetch) ─────────────────────────────────────────

function CISBucketBreakdown({ signalId, cisScore }: { signalId?: string; cisScore?: number | null }) {
  const [buckets, setBuckets] = useState<Record<string, number> | null | "loading">(
    signalId ? "loading" : null
  );

  useEffect(() => {
    if (!signalId) { setBuckets(null); return; }
    const controller = new AbortController();
    setBuckets("loading");
    fetch(`${getApiBase()}/api/signals/detail/${signalId}`, { signal: controller.signal })
      .then(r => r.ok ? r.json() : null)
      .then(d => setBuckets(d?.bucket_scores ?? null))
      .catch(() => setBuckets(null));
    return () => controller.abort();
  }, [signalId]);

  const scoreColor = cisScore != null
    ? cisScore >= 0 ? "var(--green)" : "var(--red)"
    : "var(--text-muted)";

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[0.48rem] font-bold uppercase tracking-widest text-[var(--text-muted)]">
          CIS Breakdown
        </span>
        {cisScore != null && (
          <span className="text-[0.55rem] font-bold font-data" style={{ color: scoreColor }}>
            {cisScore >= 0 ? "+" : ""}{fmtNum(cisScore, 2)}
          </span>
        )}
      </div>

      {buckets === "loading" && (
        <div className="flex flex-col gap-1">
          {[60, 40, 75, 30, 50, 45].map((w, i) => (
            <div key={i} className="flex items-center gap-1.5">
              <div className="w-[68px] h-2 rounded bg-[var(--bg-elevated)] animate-pulse" />
              <div className="flex-1 h-1.5 rounded bg-[var(--bg-elevated)] animate-pulse" style={{ maxWidth: `${w}%` }} />
              <div className="w-[28px] h-2 rounded bg-[var(--bg-elevated)] animate-pulse" />
            </div>
          ))}
        </div>
      )}

      {buckets === null && (
        <span className="text-[0.52rem] italic text-[var(--text-muted)]">No CIS breakdown</span>
      )}

      {buckets !== null && buckets !== "loading" && (() => {
        const sorted = BUCKET_ORDER
          .filter(k => k in buckets)
          .map(k => ({ key: k, val: buckets[k] }))
          .sort((a, b) => Math.abs(b.val) - Math.abs(a.val));

        return (
          <div className="flex flex-col gap-1">
            {sorted.map(({ key, val }) => (
              <div key={key} className="flex items-center gap-1.5">
                <span className="text-[0.48rem] text-[var(--text-muted)] w-[68px] shrink-0 capitalize">
                  {key}
                </span>
                <div className="flex-1 h-1.5 rounded overflow-hidden bg-[var(--bg-elevated)]">
                  <div
                    className="h-full rounded"
                    style={{
                      width: `${Math.min(100, Math.abs(val) * 100)}%`,
                      backgroundColor: val >= 0 ? "var(--green)" : "var(--red)",
                    }}
                  />
                </div>
                <span
                  className="text-[0.5rem] font-data w-[32px] text-right shrink-0 font-bold"
                  style={{ color: val >= 0 ? "var(--green)" : "var(--red)" }}
                >
                  {val >= 0 ? "+" : ""}{fmtNum(val, 2)}
                </span>
              </div>
            ))}
          </div>
        );
      })()}
    </div>
  );
}

// ── SignalTradeCard ───────────────────────────────────────────────────────────

export function SignalTradeCard({ signal }: { signal: SignalData }) {
  return (
    <div className="flex flex-col gap-3">
      <TradePriceLadder signal={signal} />
      <div className="border-t border-[var(--border-subtle)]" />
      <CISBucketBreakdown signalId={signal.signal_id} cisScore={signal.cis_score} />
      <div className="border-t border-[var(--border-subtle)]" />
      <SetupEdgeLine signal={signal} />
    </div>
  );
}
