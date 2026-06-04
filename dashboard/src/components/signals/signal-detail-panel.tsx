"use client";

import { useState, useEffect } from "react";
import { getApiBase } from "@/lib/api";
import { fmtNum } from "@/lib/format";
import { X, ChevronDown, ChevronUp, TrendingUp, TrendingDown } from "lucide-react";

const REGIME_LABELS: Record<number, string> = { 0: "TREND", 1: "RANGE", 2: "VOL" };
const REGIME_COLORS: Record<number, string> = { 0: "var(--green)", 1: "var(--amber)", 2: "var(--red)" };
const TIER_COLORS: Record<string, string> = { hero: "var(--blue)", monitored: "var(--text-secondary)", candidate: "var(--text-muted)" };
const BUCKET_ORDER = ["trend", "momentum", "structure", "institutional", "regime", "pattern"];

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Detail = Record<string, any>;

function SectionLabel({ label }: { label: string }) {
  return <div className="text-[0.48rem] font-bold uppercase tracking-widest text-[var(--text-muted)] mt-3 mb-1">{label}</div>;
}

function PriceLadder({ detail }: { detail: Detail }) {
  const entry = detail.entry_price as number | null;
  const stop = detail.stop_loss as number | null;
  const targets = (detail.targets as number[]) ?? [];
  const direction = detail.direction as number;
  if (!entry || !stop) return null;
  const risk = Math.abs(entry - stop);
  const rAtLevel = (price: number) => risk > 0 ? ((price - entry) / risk) * direction : 0;
  const levels: { label: string; price: number; r: number; isEntry?: boolean }[] = [
    ...targets.map((t, i) => ({ label: `T${i + 1}`, price: t, r: rAtLevel(t) })).reverse(),
    { label: "ENTRY", price: entry, r: 0, isEntry: true },
    { label: "SL", price: stop, r: rAtLevel(stop) },
  ];
  return (
    <div className="flex flex-col gap-0.5">
      {levels.map(({ label, price, r, isEntry }) => (
        <div key={label} className="flex items-center gap-2 text-[0.6rem] font-data">
          <span className="w-[12px] text-[var(--text-muted)]" style={{ color: isEntry ? "var(--blue)" : undefined }}>{isEntry ? "●" : ""}</span>
          <span className="w-[32px] font-bold" style={{ color: label === "SL" ? "var(--red)" : label === "ENTRY" ? "var(--text-primary)" : "var(--green)" }}>{label}</span>
          <span className="flex-1 text-[var(--text-secondary)]">{fmtNum(price, 2)}</span>
          {r !== 0 && <span style={{ color: r > 0 ? "var(--green)" : "var(--red)" }}>{r >= 0 ? "+" : ""}{fmtNum(r, 1)}R</span>}
        </div>
      ))}
    </div>
  );
}

function CISBuckets({ buckets }: { buckets: Record<string, number> | null }) {
  if (!buckets) return <span className="text-[0.55rem] text-[var(--text-muted)] italic">No CIS data</span>;
  const sorted = BUCKET_ORDER.filter(k => k in buckets).map(k => ({ key: k, val: buckets[k] })).sort((a, b) => Math.abs(b.val) - Math.abs(a.val));
  return (
    <div className="flex flex-col gap-1">
      {sorted.map(({ key, val }) => (
        <div key={key} className="flex items-center gap-1.5">
          <span className="text-[0.5rem] text-[var(--text-muted)] w-[68px] shrink-0 capitalize">{key}</span>
          <div className="flex-1 h-1.5 rounded overflow-hidden bg-[var(--bg-elevated)]">
            <div className="h-full rounded" style={{ width: `${Math.min(100, Math.abs(val) * 100)}%`, backgroundColor: val >= 0 ? "var(--green)" : "var(--red)" }} />
          </div>
          <span className="text-[0.52rem] font-data w-[32px] text-right shrink-0" style={{ color: val >= 0 ? "var(--green)" : "var(--red)" }}>
            {val >= 0 ? "+" : ""}{fmtNum(val, 2)}
          </span>
        </div>
      ))}
    </div>
  );
}

function SetupEdge({ detail }: { detail: Detail }) {
  const setup = detail.setup_plugin as string;
  const symbol = detail.symbol as string;
  const wr = detail.setup_win_rate as number | null;
  const avgR = detail.setup_avg_pnl_r as number | null;
  const regime = detail.hmm_regime_at_fire as number | null;
  return (
    <div className="flex flex-col gap-1 text-[0.58rem] font-data">
      <span className="text-[var(--text-secondary)] truncate">{setup?.replace(/^(trad_|ind_|smc_)/, "")} on {symbol}</span>
      <div className="flex gap-3">
        <span>Win <span style={{ color: wr != null && wr >= 0.1 ? "var(--green)" : "var(--amber)" }}>{wr != null ? fmtNum(wr * 100, 1) + "%" : "—"}</span></span>
        <span>Avg R <span style={{ color: avgR != null && avgR > 0 ? "var(--green)" : "var(--red)" }}>{avgR != null ? (avgR >= 0 ? "+" : "") + fmtNum(avgR, 3) : "—"}</span></span>
      </div>
      {regime != null && <span style={{ color: "var(--text-muted)" }}>In {REGIME_LABELS[regime] ?? `regime ${regime}`} regime</span>}
    </div>
  );
}

function CaptureBar({ detail }: { detail: Detail }) {
  const mae = detail.mae as number | null;
  const mfe = detail.mfe as number | null;
  const pnlR = detail.pnl_r as number | null;
  if (mae == null || mfe == null || pnlR == null) return null;
  const totalRange = Math.abs(mae) + Math.abs(mfe);
  if (totalRange === 0) return null;
  const maeW = Math.round((Math.abs(mae) / totalRange) * 100);
  const mfeW = 100 - maeW;
  const exitPct = mfe > 0 ? Math.min(100, Math.round((pnlR / mfe) * mfeW)) : 0;
  const capEff = mfe > 0 ? pnlR / mfe : null;
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-1 text-[0.5rem] font-data">
        <span style={{ color: "var(--red)" }}>MAE {fmtNum(mae, 1)}R</span>
        <div className="flex-1 flex h-2 rounded overflow-hidden">
          <div style={{ width: `${maeW}%`, backgroundColor: "rgba(255,71,87,0.25)" }} />
          <div className="relative" style={{ width: `${mfeW}%`, backgroundColor: "rgba(0,220,130,0.15)" }}>
            {exitPct > 0 && <div className="absolute left-0 top-0 h-full" style={{ width: `${exitPct}%`, backgroundColor: "rgba(0,220,130,0.5)" }} />}
          </div>
        </div>
        <span style={{ color: "var(--green)" }}>MFE +{fmtNum(mfe, 1)}R</span>
      </div>
      {capEff != null && <span className="text-[0.5rem] font-data text-[var(--text-muted)]">Captured {fmtNum(capEff * 100, 0)}% of available move (+{fmtNum(pnlR, 2)}R of {fmtNum(mfe, 2)}R)</span>}
    </div>
  );
}

function Timeline({ detail }: { detail: Detail }) {
  const firedAt = detail.signal_computed_at as string | null;
  const activatedAt = detail.activated_at as string | null;
  const exitAt = detail.exit_at as string | null;
  const activationPrice = detail.activation_price as number | null;
  const barsToActivation = detail.bars_to_activation as number | null;
  const barsInTrade = detail.bars_in_trade as number | null;
  const exitReason = detail.exit_reason as string | null;
  const pnlR = detail.pnl_r as number | null;
  const status = detail.status as string;

  const fmt = (ts: string) => new Date(ts).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });

  const events = [
    { ts: firedAt, label: "Signal fired", detail: null, active: true },
    activatedAt
      ? { ts: activatedAt, label: `Activated at ${activationPrice != null ? fmtNum(activationPrice, 2) : "—"}`, detail: barsToActivation != null ? `${barsToActivation} bars to activation` : null, active: true }
      : { ts: null, label: status === "pending" ? "Waiting for activation…" : "Never activated", detail: null, active: false },
    exitAt
      ? { ts: exitAt, label: `Exited — ${exitReason ?? "unknown"}`, detail: pnlR != null ? `${pnlR >= 0 ? "+" : ""}${fmtNum(pnlR, 2)}R${barsInTrade != null ? ` · ${barsInTrade} bars` : ""}` : null, active: true }
      : activatedAt
      ? { ts: null, label: "In trade…", detail: barsInTrade != null ? `${barsInTrade} bars held` : null, active: false }
      : null,
  ].filter(Boolean) as { ts: string | null; label: string; detail: string | null; active: boolean }[];

  return (
    <div className="flex flex-col gap-1.5">
      {events.map((ev, i) => (
        <div key={i} className="flex items-start gap-2 text-[0.55rem]">
          <span style={{ color: ev.active ? "var(--text-secondary)" : "var(--text-muted)" }}>{ev.active ? "◉" : "○"}</span>
          <div className="flex flex-col gap-0.5">
            <span className="font-data" style={{ color: ev.active ? "var(--text-primary)" : "var(--text-muted)" }}>
              {ev.ts ? fmt(ev.ts) + "  " : ""}{ev.label}
            </span>
            {ev.detail && <span className="text-[0.48rem] text-[var(--text-muted)]">{ev.detail}</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

export function SignalDetailPanel({
  signalId,
  onClose,
}: {
  signalId: string;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [loading, setLoading] = useState(true);
  const [rawOpen, setRawOpen] = useState(false);

  useEffect(() => {
    setLoading(true);
    fetch(`${getApiBase()}/api/signals/detail/${signalId}`)
      .then(r => r.ok ? r.json() : null)
      .then(d => setDetail(d))
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [signalId]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const tier = detail?.signal_tier as string | undefined;
  const regime = detail?.hmm_regime_at_fire as number | null | undefined;
  const isLong = detail?.direction === 1;
  const barsAgo = detail?.bars_in_trade as number | null;

  return (
    <div className="flex flex-col border-l border-[var(--border-subtle)] overflow-y-auto shrink-0"
      style={{ width: "300px", background: "var(--bg-surface)" }}>
      <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border-subtle)]">
        <span className="text-[0.58rem] font-bold uppercase tracking-widest text-[var(--text-secondary)]">Signal Detail</span>
        <button onClick={onClose} aria-label="Close" className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"><X size={14} /></button>
      </div>

      {loading && <div className="p-4 text-[0.6rem] text-[var(--text-muted)] italic">Loading…</div>}
      {!loading && !detail && <div className="p-4 text-[0.6rem] text-[var(--red)] italic">Signal not found</div>}
      {!loading && detail && (
        <div className="p-3 flex flex-col gap-0.5 text-[0.6rem]">
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-base font-bold font-data" style={{ color: isLong ? "var(--green)" : "var(--red)" }}>{detail.symbol}</span>
              {isLong ? <TrendingUp size={14} style={{ color: "var(--green)" }} /> : <TrendingDown size={14} style={{ color: "var(--red)" }} />}
              {tier && <span className="text-[0.5rem] font-bold px-1.5 py-0.5 rounded" style={{ color: TIER_COLORS[tier] ?? "var(--text-muted)", border: `1px solid ${TIER_COLORS[tier] ?? "var(--border-subtle)"}` }}>{tier.toUpperCase()}</span>}
              {regime != null && <span className="text-[0.5rem] font-bold px-1.5 py-0.5 rounded" style={{ color: REGIME_COLORS[regime] ?? "var(--text-muted)", border: `1px solid ${REGIME_COLORS[regime] ?? "var(--border-subtle)"}` }}>{REGIME_LABELS[regime] ?? `R${regime}`}</span>}
              <span className="text-[0.5rem] text-[var(--text-muted)]">{detail.timeframe}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-[0.55rem] text-[var(--text-secondary)]">{(detail.setup_plugin as string)?.replace(/^(trad_|ind_|smc_)/, "")}</span>
              <span className="text-[0.52rem] font-data font-bold" style={{ color: (detail.cis_score as number ?? 0) >= 0 ? "var(--green)" : "var(--red)" }}>
                CIS {detail.cis_score != null ? ((detail.cis_score as number) >= 0 ? "+" : "") + fmtNum(detail.cis_score as number, 2) : "—"}
              </span>
            </div>
            {detail.signal_computed_at && (
              <span className="text-[0.48rem] text-[var(--text-muted)]">
                Fired {new Date(detail.signal_computed_at as string).toLocaleTimeString("en-US", { hour12: false })}
                {barsAgo != null ? ` · ${barsAgo} bars ago` : ""}
              </span>
            )}
          </div>

          <SectionLabel label="Trade Anatomy" />
          <PriceLadder detail={detail} />

          <SectionLabel label="CIS Breakdown" />
          <CISBuckets buckets={detail.bucket_scores as Record<string, number> | null} />

          <SectionLabel label="Setup Edge" />
          <SetupEdge detail={detail} />

          {detail.outcome && (
            <>
              <SectionLabel label="Capture Efficiency" />
              <CaptureBar detail={detail} />
            </>
          )}

          <SectionLabel label="Lifecycle" />
          <Timeline detail={detail} />

          <button onClick={() => setRawOpen(v => !v)} className="flex items-center gap-1 mt-3 text-[0.48rem] text-[var(--text-muted)] hover:text-[var(--text-secondary)]">
            {rawOpen ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
            Raw data
          </button>
          {rawOpen && (
            <pre className="text-[0.48rem] font-data text-[var(--text-muted)] whitespace-pre-wrap mt-1 overflow-x-auto">
              {JSON.stringify(detail, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
