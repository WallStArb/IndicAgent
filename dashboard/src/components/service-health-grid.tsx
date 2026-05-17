"use client";

import { useMemo } from "react";
import type { ServiceEntry } from "@/hooks/use-observability-stream";

const DOT_CLASS: Record<ServiceEntry["health"], string> = {
  active:  "bg-[var(--green)] shadow-[0_0_6px_var(--green-dim)]",
  stale:   "bg-[var(--accent-amber)] shadow-[0_0_6px_var(--amber-dim)]",
  unknown: "bg-[var(--border-bright)]",
};

const TEXT_CLASS: Record<ServiceEntry["health"], string> = {
  active:  "text-[var(--green)]",
  stale:   "text-[var(--accent-amber)]",
  unknown: "text-[var(--text-muted)]",
};

function formatAge(sec: number | null): string {
  if (sec === null) return "no data";
  if (sec < 60)   return `${Math.round(sec)}s ago`;
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
  return `${(sec / 3600).toFixed(1)}h ago`;
}

function ServiceDot({ svc }: { svc: ServiceEntry }) {
  return (
    <div className="relative group/dot">
      <div className={`w-2.5 h-2.5 rounded-full ${DOT_CLASS[svc.health]} transition-transform group-hover/dot:scale-125`} />
      {/* Tooltip */}
      <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-10 pointer-events-none opacity-0 group-hover/dot:opacity-100 transition-opacity">
        <div className="bg-[var(--bg-elevated)] border border-[var(--border-bright)] rounded-lg px-2.5 py-1.5 whitespace-nowrap shadow-xl">
          <div className="text-[0.65rem] font-mono text-[var(--text-primary)]">{svc.label}</div>
          <div className={`text-[0.55rem] font-mono ${TEXT_CLASS[svc.health]}`}>
            {svc.health.toUpperCase()} · {formatAge(svc.lastSeenSec)}
          </div>
        </div>
        <div className="w-2 h-2 bg-[var(--bg-elevated)] border-r border-b border-[var(--border-bright)] rotate-45 mx-auto -mt-1" />
      </div>
    </div>
  );
}

export function ServiceHealthGrid({ services }: { services: ServiceEntry[] }) {
  const layers = useMemo(() => {
    const map = new Map<number, { name: string; services: ServiceEntry[] }>();
    for (const svc of services) {
      if (!map.has(svc.layer)) {
        map.set(svc.layer, { name: svc.layerName, services: [] });
      }
      map.get(svc.layer)!.services.push(svc);
    }
    return Array.from(map.entries()).sort(([a], [b]) => a - b);
  }, [services]);

  return (
    <div className="surface rounded-xl p-5 border-[var(--border-default)]">
      <div className="flex items-center justify-between mb-4">
        <h2
          className="text-[0.65rem] font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          Service DAG
        </h2>
        <div className="flex items-center gap-3 text-[0.55rem] font-mono text-[var(--text-muted)]">
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[var(--green)]" /> Active</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[var(--accent-amber)]" /> Idle</span>
          <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-[var(--border-bright)]" /> Unknown</span>
        </div>
      </div>

      <div className="space-y-1.5">
        {layers.map(([layer, { name, services: svcs }]) => {
          const activeCount = svcs.filter(s => s.health === "active").length;
          const hasIssue = svcs.some(s => s.health === "stale");

          return (
            <div
              key={layer}
              className="flex items-center gap-3 px-3 py-2 rounded-lg bg-[var(--bg-elevated)] border border-[var(--border-subtle)] hover:border-[var(--border-default)] transition-colors group"
            >
              {/* Layer badge */}
              <div
                className={`flex-shrink-0 w-6 h-6 rounded flex items-center justify-center text-[0.6rem] font-bold font-mono
                  ${hasIssue ? "bg-[var(--amber-dim)] text-[var(--accent-amber)]" : "bg-[var(--bg-base)] text-[var(--text-muted)]"}`}
              >
                L{layer}
              </div>

              {/* Layer name */}
              <div className="flex-shrink-0 w-28">
                <div className="text-[0.65rem] font-semibold text-[var(--text-secondary)] truncate">{name}</div>
                <div className="text-[0.5rem] text-[var(--text-muted)] font-mono">
                  {activeCount}/{svcs.length} active
                </div>
              </div>

              <div className="flex items-center gap-2 flex-wrap">
                {svcs.map(svc => (
                  <ServiceDot key={svc.unit} svc={svc} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
