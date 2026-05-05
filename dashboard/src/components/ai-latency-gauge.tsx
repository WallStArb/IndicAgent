"use client";

export function AiLatencyGauge() {
  // We'll extend our hook to provide this in a moment
  return (
    <div className="surface rounded-xl p-6 border-[var(--border-default)] flex flex-col h-full">
      <div className="flex items-center justify-between mb-8">
        <h2 className="text-[0.65rem] font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]">AI Performance & Latency</h2>
      </div>
      
      <div className="flex-1 flex flex-col justify-center gap-4">
        <div className="flex justify-between items-end">
          <span className="text-[0.6rem] uppercase text-[var(--text-muted)]">Prompt Construction</span>
          <span className="font-mono text-[0.8rem] text-[var(--text-primary)]">14ms</span>
        </div>
        <div className="w-full h-1 bg-[var(--bg-base)] rounded-full overflow-hidden">
          <div className="h-full bg-[var(--accent-cyan)] w-[30%]" />
        </div>

        <div className="flex justify-between items-end mt-4">
          <span className="text-[0.6rem] uppercase text-[var(--text-muted)]">LLM Inference</span>
          <span className="font-mono text-[0.8rem] text-[var(--text-primary)]">42ms</span>
        </div>
        <div className="w-full h-1 bg-[var(--bg-base)] rounded-full overflow-hidden">
          <div className="h-full bg-[var(--purple)] w-[65%]" />
        </div>
      </div>
    </div>
  );
}
