"use client";

import { ExternalLink, Activity, Gauge, BrainCircuit, Database } from "lucide-react";
import { useObservabilityStream } from "@/hooks/use-observability-stream";
import { fmtLatency, fmtRate } from "@/lib/format";
import { PipelineFlow } from "./pipeline-flow";
import { ServiceHealthGrid } from "./service-health-grid";

// ── KPI Card ──────────────────────────────────────────────────────────────────

function KpiCard({
  label,
  value,
  sub,
  accent = "cyan",
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: "cyan" | "green" | "amber" | "muted";
}) {
  const color = {
    cyan:  "text-[var(--accent-cyan)]",
    green: "text-[var(--green)]",
    amber: "text-[var(--accent-amber)]",
    muted: "text-[var(--text-secondary)]",
  }[accent];

  return (
    <div className="surface-elevated rounded-xl px-5 py-4 border border-[var(--border-default)] hover:border-[var(--border-bright)] transition-colors">
      <div className="text-[0.55rem] uppercase tracking-[0.18em] text-[var(--text-muted)] mb-2"
           style={{ fontFamily: "var(--font-display)" }}>
        {label}
      </div>
      <div className={`text-[1.4rem] font-mono font-semibold tabular-nums leading-none ${color}`}>
        {value}
      </div>
      {sub && (
        <div className="text-[0.55rem] font-mono text-[var(--text-muted)] mt-1.5">{sub}</div>
      )}
    </div>
  );
}

// ── Latency breakdown bar ─────────────────────────────────────────────────────

function LatencyBar({ label, ms, maxMs }: { label: string; ms: number | null; maxMs: number }) {
  const pct = ms !== null && maxMs > 0 ? Math.min((ms / maxMs) * 100, 100) : 0;
  const color =
    ms === null ? "bg-[var(--border-bright)]"
    : ms > 30000 ? "bg-[var(--red)]"
    : ms > 5000  ? "bg-[var(--accent-amber)]"
    : ms > 500   ? "bg-[var(--amber)]"
    : "bg-[var(--green)]";

  return (
    <div className="flex items-center gap-3">
      <div className="w-20 flex-shrink-0 text-[0.6rem] font-mono text-[var(--text-muted)] text-right">{label}</div>
      <div className="flex-1 h-2 bg-[var(--bg-base)] rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full latency-bar-fill ${color}`}
          style={{ "--bar-pct": `${pct}%` } as React.CSSProperties}
        />
      </div>
      <div className="w-14 flex-shrink-0 text-[0.65rem] font-mono tabular-nums text-right text-[var(--text-secondary)]">
        {fmtLatency(ms)}
      </div>
    </div>
  );
}

// ── Grafana link tile ─────────────────────────────────────────────────────────

function GrafanaTile({ icon: Icon, label, desc, href }: {
  icon: React.ComponentType<{ size: number }>;
  label: string;
  desc: string;
  href: string;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="flex items-center gap-3 px-4 py-3 rounded-xl bg-[var(--bg-elevated)] border border-[var(--border-subtle)] hover:border-[var(--accent-cyan)] hover:bg-[var(--bg-hover)] transition-all group"
    >
      <div className="w-8 h-8 rounded-lg bg-[var(--bg-base)] flex items-center justify-center text-[var(--accent-cyan)] group-hover:bg-[var(--accent-cyan-dim)] transition-colors">
        <Icon size={16} />
      </div>
      <div className="min-w-0">
        <div className="text-[0.7rem] font-semibold text-[var(--text-primary)] truncate">{label}</div>
        <div className="text-[0.55rem] text-[var(--text-muted)] truncate">{desc}</div>
      </div>
      <ExternalLink size={10} className="ml-auto flex-shrink-0 text-[var(--border-bright)] group-hover:text-[var(--accent-cyan)]" />
    </a>
  );
}

// ── Main panel ────────────────────────────────────────────────────────────────

const GRAFANA = process.env.NEXT_PUBLIC_GRAFANA_URL ?? "http://localhost:3001";

export default function ObservabilityPanel() {
  const { nodes, services, summary, lastUpdated } = useObservabilityStream();

  const bottleneck = nodes.find(n => n.isBottleneck);
  const maxLatencyMs = Math.max(
    summary.pipelineLatencyMs ?? 0,
    summary.i1LatencyMs ?? 0,
    summary.i7LatencyMs ?? 0,
  );

  const lastUpdatedStr = lastUpdated > 0
    ? new Date(lastUpdated * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : "—";

  return (
    <div className="min-h-screen bg-[var(--bg-base)] flex flex-col">

      {/* ── Page header ── */}
      <header className="px-6 pt-6 pb-4 border-b border-[var(--border-subtle)] bg-[var(--bg-base)]">
        <div className="flex items-center justify-between">
          <div>
            <h1
              className="text-xl font-bold text-[var(--text-primary)] tracking-tight"
              style={{ fontFamily: "var(--font-display)" }}
            >
              Signal Command Center
            </h1>
            <p className="text-[0.7rem] text-[var(--text-muted)] mt-0.5">
              End-to-end intelligence pipeline · ingestion → I1-I7 compute → signals → persistence → AI
            </p>
          </div>
          <div className="flex items-center gap-4">
            <div className="text-right">
              <div className="text-[0.55rem] uppercase tracking-wider text-[var(--text-muted)]">Last updated</div>
              <div className="text-[0.7rem] font-mono text-[var(--text-secondary)]">{lastUpdatedStr}</div>
            </div>
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[var(--green-dim)] border border-[var(--green)] border-opacity-30">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--green)] live-pulse" />
              <span className="text-[0.6rem] font-mono font-semibold text-[var(--green)] tracking-wider">LIVE</span>
            </div>
          </div>
        </div>
      </header>

      <div className="flex flex-col flex-1 p-6 gap-5 overflow-auto">

        {/* ── KPI summary strip ── */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <KpiCard
            label="Tracked Signals"
            value={summary.activeSignals !== null ? summary.activeSignals.toLocaleString() : "—"}
            sub="signal ledger"
            accent="green"
          />
          <KpiCard
            label="Pipeline Latency"
            value={fmtLatency(summary.pipelineLatencyMs)}
            sub="last-bar · end-to-end"
            accent={
              summary.pipelineLatencyMs === null ? "muted"
              : summary.pipelineLatencyMs > 30000 ? "amber"
              : "cyan"
            }
          />
          <KpiCard
            label="Bar Ingestion"
            value={fmtRate(summary.ingestionRate, "bars/s")}
            sub={summary.ingestionRate === 0 ? "markets closed" : "bar aggregator"}
            accent={summary.ingestionRate !== null && summary.ingestionRate > 0 ? "green" : "muted"}
          />
          <KpiCard
            label="Bottleneck"
            value={bottleneck ? bottleneck.label : "—"}
            sub={bottleneck ? `${fmtLatency(bottleneck.latencyMs)} last-bar` : "no latency data"}
            accent={bottleneck ? "amber" : "muted"}
          />
        </div>

        {/* ── Main 2-column layout ── */}
        <div className="grid grid-cols-1 xl:grid-cols-5 gap-5 flex-1">

          {/* Pipeline flow — left 2 cols */}
          <div className="xl:col-span-2">
            <PipelineFlow nodes={nodes} />
          </div>

          {/* Right side — 3 cols */}
          <div className="xl:col-span-3 flex flex-col gap-5">

            {/* Service health grid */}
            <ServiceHealthGrid services={services} />

            {/* Latency breakdown */}
            <div className="surface rounded-xl p-5 border-[var(--border-default)]">
              <div className="flex items-center justify-between mb-4">
                <h2
                  className="text-[0.65rem] font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]"
                  style={{ fontFamily: "var(--font-display)" }}
                >
                  Latency Breakdown
                </h2>
                <span className="text-[0.55rem] font-mono text-[var(--text-muted)]">last processed bar</span>
              </div>
              <div className="space-y-3">
                <LatencyBar label="I1 compute"   ms={summary.i1LatencyMs}         maxMs={maxLatencyMs} />
                <LatencyBar label="I7 compute"   ms={summary.i7LatencyMs}         maxMs={maxLatencyMs} />
                <LatencyBar label="Full pipeline" ms={summary.pipelineLatencyMs}  maxMs={maxLatencyMs} />
              </div>
              {summary.pipelineLatencyMs !== null && summary.pipelineLatencyMs > 10000 && (
                <p className="mt-3 text-[0.55rem] text-[var(--text-muted)] font-mono border-t border-[var(--border-subtle)] pt-2">
                  High latency is expected on weekends — gauge shows the last bar processed, which may be stale.
                </p>
              )}
              {summary.threadWorkers !== null && (
                <div className="mt-3 pt-2 border-t border-[var(--border-subtle)] flex gap-6">
                  <div>
                    <div className="text-[0.5rem] uppercase tracking-wider text-[var(--text-muted)]">Thread workers</div>
                    <div className="text-[0.75rem] font-mono text-[var(--accent-cyan)]">{Math.round(summary.threadWorkers)}</div>
                  </div>
                  <div>
                    <div className="text-[0.5rem] uppercase tracking-wider text-[var(--text-muted)]">GIL cap</div>
                    <div className="text-[0.75rem] font-mono text-[var(--text-secondary)]">12</div>
                  </div>
                </div>
              )}
            </div>

          </div>
        </div>

        {/* ── Grafana drill-through strip ── */}
        <div>
          <h2
            className="text-[0.6rem] font-bold uppercase tracking-[0.2em] text-[var(--text-muted)] mb-3"
            style={{ fontFamily: "var(--font-display)" }}
          >
            Deep Dive
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <GrafanaTile
              icon={Gauge}
              label="Pipeline Health"
              desc="Bar agg · I1-I7 · writers"
              href={`${GRAFANA}/d/indicagent-pipeline-health`}
            />
            <GrafanaTile
              icon={Activity}
              label="Signals + AI"
              desc="Signal ledger · LLM calls · swarm"
              href={`${GRAFANA}/d/indicagent-signals-i8`}
            />
            <GrafanaTile
              icon={BrainCircuit}
              label="Plugin Latency"
              desc="Per-plugin breakdown · I1-I7"
              href={`${GRAFANA}/d/indicagent-plugin-latency`}
            />
            <GrafanaTile
              icon={Database}
              label="Operations"
              desc="Service health · restarts · CBs"
              href={`${GRAFANA}/d/indicagent-operations`}
            />
          </div>
        </div>

      </div>
    </div>
  );
}
