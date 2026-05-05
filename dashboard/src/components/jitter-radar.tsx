"use client";

import type { ObservabilityMetrics } from "@/hooks/use-observability-stream";

type Props = Pick<ObservabilityMetrics, "jitter">;

export function JitterRadar({ jitter }: Props) {
  return (
    <div className="surface rounded-xl p-6 border-[var(--border-default)] flex flex-col h-full">
      <div className="flex items-center justify-between mb-8">
        <h2 className="text-[0.65rem] font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]">Data Feed Stability</h2>
        <span className="font-mono text-[0.6rem] text-[var(--accent-amber)]">LATENCY: {jitter.latency}</span>
      </div>

      <div className="flex-1 flex items-center justify-center relative min-h-[240px]">
        <div className="relative w-48 h-48 border border-[var(--border-subtle)] rounded-full flex items-center justify-center">
          <div className="w-32 h-32 border border-[var(--border-subtle)] rounded-full flex items-center justify-center">
            <div className="w-16 h-16 border border-[var(--border-subtle)] rounded-full" />
          </div>
          <div className="absolute w-2 h-2 rounded-full bg-[var(--accent-cyan)] ring-pulse shadow-[0_0_15px_var(--accent-cyan)]" />
        </div>
      </div>

      <div className="mt-6 grid grid-cols-2 gap-4 border-t border-[var(--border-subtle)] pt-6">
        <div>
          <div className="text-[0.55rem] uppercase text-[var(--text-muted)] tracking-wider">Jitter</div>
          <div className="text-[0.9rem] font-mono text-[var(--text-primary)]">{jitter.jitter}</div>
        </div>
        <div>
          <div className="text-[0.55rem] uppercase text-[var(--text-muted)] tracking-wider">Health</div>
          <div className="text-[0.9rem] font-mono text-[var(--green)]">{jitter.health}</div>
        </div>
      </div>
    </div>
  );
}
