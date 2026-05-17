"use client";

import { ExternalLink, AlertTriangle } from "lucide-react";
import type { PipelineNode } from "@/hooks/use-observability-stream";
import { fmtLatency, fmtRate } from "@/lib/format";

// ── Health palette ────────────────────────────────────────────────────────────

const HEALTH = {
  active:   { dot: "bg-[var(--green)]",        text: "text-[var(--green)]",        border: "border-[var(--green)]",   glow: "shadow-[0_0_10px_var(--green-dim)]",   label: "ACTIVE"  },
  stale:    { dot: "bg-[var(--accent-amber)]",  text: "text-[var(--accent-amber)]", border: "border-[var(--amber)]",   glow: "shadow-[0_0_10px_var(--amber-dim)]",   label: "IDLE"    },
  degraded: { dot: "bg-[var(--red)]",           text: "text-[var(--red)]",          border: "border-[var(--red)]",     glow: "shadow-[0_0_10px_var(--red-dim)]",     label: "DEGRADED"},
  unknown:  { dot: "bg-[var(--text-muted)]",    text: "text-[var(--text-muted)]",   border: "border-[var(--border-default)]", glow: "",                              label: "UNKNOWN" },
};

const PARTICLE_COLOR = {
  active:   "bg-[var(--accent-cyan)]",
  stale:    "bg-[var(--accent-amber)]",
  degraded: "bg-[var(--red)]",
  unknown:  "bg-[var(--border-bright)]",
};

// ── Connector between nodes ───────────────────────────────────────────────────

function FlowConnector({ health, flowing }: { health: PipelineNode["health"]; flowing: boolean }) {
  return (
    <div className="relative flex justify-center items-stretch" style={{ height: 40 }}>
      <div className="w-px bg-[var(--border-bright)] h-full" />
      <div className="absolute inset-0 overflow-hidden flex justify-center">
        {flowing
          ? [1, 2, 3].map(i => (
              <span key={i} className={`flow-particle flow-particle-${i} ${PARTICLE_COLOR[health]}`} />
            ))
          : <span className="flow-particle flow-particle-1 bg-[var(--border-bright)] opacity-30" />
        }
      </div>
    </div>
  );
}

// ── Single pipeline node ──────────────────────────────────────────────────────

function PipelineNodeCard({
  node,
  index,
  showConnector,
}: {
  node: PipelineNode;
  index: number;
  showConnector: boolean;
}) {
  const h = HEALTH[node.health];
  const flowing = node.health === "active";

  return (
    <div className="node-enter" style={{ animationDelay: `${index * 80}ms` }}>
      <div
        className={`relative rounded-xl border bg-[var(--bg-elevated)] transition-all duration-300 group ${
          node.isBottleneck
            ? "border-[var(--accent-amber)] shadow-[0_0_20px_var(--amber-dim)]"
            : `border-[var(--border-default)] hover:border-[var(--border-bright)]`
        }`}
      >

        <div
          className={`absolute left-0 top-3 bottom-3 w-0.5 rounded-full ${h.dot} ${h.glow}`}
        />

        <div className="pl-4 pr-3 py-3">

          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className={`w-2 h-2 rounded-full flex-shrink-0 ${h.dot} ${flowing ? "live-pulse" : ""}`} />
              <span
                className="text-[0.7rem] font-bold uppercase tracking-[0.15em] text-[var(--text-primary)]"
                style={{ fontFamily: "var(--font-display)" }}
              >
                {node.label}
              </span>
              {node.isBottleneck && (
                <span className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[0.55rem] font-bold uppercase tracking-wider bg-[var(--accent-amber-dim)] text-[var(--accent-amber)] border border-[var(--accent-amber)] border-opacity-40">
                  <AlertTriangle size={8} />
                  bottleneck
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <span className={`text-[0.55rem] font-mono font-semibold tracking-wider ${h.text}`}>
                {h.label}
              </span>
              <a
                href={node.grafanaDashboard}
                target="_blank"
                rel="noopener noreferrer"
                className="opacity-0 group-hover:opacity-60 hover:!opacity-100 transition-opacity text-[var(--text-muted)] hover:text-[var(--accent-cyan)]"
                title="Open in Grafana"
              >
                <ExternalLink size={11} />
              </a>
            </div>
          </div>


          <div className="text-[0.6rem] text-[var(--text-muted)] mb-3 ml-4">{node.sublabel}</div>


          <div className="flex items-end justify-between ml-4 mb-3">
            <div>
              <div className="text-[0.5rem] uppercase tracking-wider text-[var(--text-muted)] mb-0.5">Throughput</div>
              <div className="text-[1.05rem] font-mono font-semibold text-[var(--accent-cyan)] tabular-nums leading-none">
                {fmtRate(node.rate, node.rateUnit)}
              </div>
            </div>
            {node.latencyMs !== null && (
              <div className="text-right">
                <div className="text-[0.5rem] uppercase tracking-wider text-[var(--text-muted)] mb-0.5">Last-bar latency</div>
                <div
                  className={`text-[0.9rem] font-mono font-semibold tabular-nums leading-none ${
                    node.latencyMs > 30000 ? "text-[var(--accent-amber)]"
                    : node.latencyMs > 5000  ? "text-[var(--amber)]"
                    : "text-[var(--green)]"
                  }`}
                >
                  {fmtLatency(node.latencyMs)}
                </div>
              </div>
            )}
          </div>

          {/* extras grid */}
          {node.extras.length > 0 && (
            <div
              className="ml-4 grid gap-x-4 gap-y-1 border-t border-[var(--border-subtle)] pt-2"
              style={{ gridTemplateColumns: `repeat(${Math.min(node.extras.length, 4)}, 1fr)` }}
            >
              {node.extras.map(e => (
                <div key={e.label}>
                  <div className="text-[0.5rem] uppercase tracking-wider text-[var(--text-muted)]">{e.label}</div>
                  <div className="text-[0.65rem] font-mono text-[var(--text-secondary)] tabular-nums">{e.value}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {showConnector && (
        <FlowConnector health={node.health} flowing={flowing} />
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export function PipelineFlow({ nodes }: { nodes: PipelineNode[] }) {
  if (nodes.length === 0) {
    return (
      <div className="surface rounded-xl p-6 flex items-center justify-center min-h-[400px]">
        <span className="text-[var(--text-muted)] text-sm font-mono animate-pulse">Loading pipeline...</span>
      </div>
    );
  }

  return (
    <div className="surface rounded-xl p-5 border-[var(--border-default)] flex flex-col">
      <div className="flex items-center justify-between mb-5">
        <h2
          className="text-[0.65rem] font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          Signal Path
        </h2>
        <div className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--green)] live-pulse" />
          <span className="text-[0.55rem] font-mono text-[var(--text-muted)] tracking-wider">LIVE · 5s</span>
        </div>
      </div>

      <div>
        {nodes.map((node, i) => (
          <PipelineNodeCard
            key={node.id}
            node={node}
            index={i}
            showConnector={i < nodes.length - 1}
          />
        ))}
      </div>
    </div>
  );
}
