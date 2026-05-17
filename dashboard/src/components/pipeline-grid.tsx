"use client";

import type { ObservabilityMetrics } from "@/hooks/use-observability-stream";

type Props = Pick<ObservabilityMetrics, "pipeline">;

const STATUS_CLASS: Record<string, string> = {
  active: "text-[var(--text-muted)]",
  warning: "text-[var(--accent-amber)]",
  error: "text-[var(--red)]",
};

export function PipelineGrid({ pipeline }: Props) {
  return (
    <div className="surface rounded-xl p-6 border-[var(--border-default)]">
      <div className="flex items-center justify-between mb-8">
        <h2 className="text-[0.65rem] font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]">Intelligence Pipeline Flow</h2>
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-[var(--green)] live-pulse" />
          <span className="text-[0.6rem] font-mono text-[var(--text-secondary)]">OPERATIONAL</span>
        </div>
      </div>

      <div className="space-y-4">
        {(pipeline ?? []).map((p, i) => (
          <div key={p.id} className="relative group">
            <div className="flex items-center justify-between p-3 rounded-lg bg-[var(--bg-elevated)] border border-[var(--border-subtle)] hover:border-[var(--border-bright)] transition-colors">
              <div className="flex items-center gap-4">
                <div className="w-6 h-6 flex items-center justify-center rounded bg-[var(--bg-base)] text-[0.7rem] text-[var(--text-muted)]">
                  {i + 1}
                </div>
                <div>
                  <div className="text-[0.8rem] font-semibold text-[var(--text-primary)] capitalize">{p.id}</div>
                  <div className={`text-[0.6rem] font-mono ${STATUS_CLASS[p.status] ?? STATUS_CLASS.active}`}>
                    {p.status.toUpperCase()}
                  </div>
                </div>
              </div>
              <div className="font-mono text-[0.7rem] text-[var(--accent-cyan)]">{p.throughput}</div>
            </div>
            {i < pipeline.length - 1 && (
              <div className="absolute left-[34px] top-full w-px h-4 bg-[var(--border-subtle)]" />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
