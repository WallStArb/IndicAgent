"use client";

import { useObservabilityStream } from "@/hooks/use-observability-stream";
import { PipelineGrid } from "./pipeline-grid";
import { JitterRadar } from "./jitter-radar";

export default function ObservabilityPanel() {
  const { pipeline, jitter } = useObservabilityStream();

  return (
    <div className="flex flex-col min-h-screen bg-[var(--bg-base)]">
      <div className="flex flex-col flex-1 p-6 gap-6">
      <header>
        <h1 className="text-xl font-bold text-[var(--text-primary)]">System Command Center</h1>
        <p className="text-sm text-[var(--text-muted)]">Real-time observability and intelligence pipeline health</p>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 flex-1">
        <PipelineGrid pipeline={pipeline} />
        <div className="lg:col-span-2 grid grid-cols-1 md:grid-cols-2 gap-6">
          <JitterRadar jitter={jitter} />
        </div>
      </div>
      </div>
    </div>
  );
}
