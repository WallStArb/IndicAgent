"use client";

import { useEffect, useState } from "react";
import { BrainCircuit, AlertTriangle } from "lucide-react";
import { getApiBase } from "@/lib/api";

interface AgentResult {
  agent_id: string;
  display_name: string;
  multiplier: number | null;
  confidence: number | null;
  shadow_at_write: boolean | null;
  error: string | null;
  reasoning: string | null;
}

interface SignalAI {
  signal_id: string;
  agents: AgentResult[];
  swarm: {
    multiplier: number | null;
    adjusted_confidence: number | null;
    agent_count: number | null;
    ml_score: number | null;
  };
  narrative: {
    text: string | null;
    model: string | null;
    latency_ms: number | null;
    generated_at: string | null;
  };
}

const AGENT_COLORS: Record<string, string> = {
  skeptic_v1: "var(--red)",
  correlation_v1: "var(--accent-cyan)",
  regime_coherence_v1: "var(--purple)",
  counterfactual_v1: "var(--orange)",
};

function MultiplierBar({ value }: { value: number | null }) {
  if (value == null) return <span className="text-[var(--text-muted)]">—</span>;
  // Multiplier range ~0.05–1.5; center at 1.0
  const pct = Math.min(100, Math.max(0, (value / 1.5) * 100));
  const color = value >= 1.0 ? "var(--green)" : value >= 0.5 ? "var(--accent-cyan)" : "var(--orange)";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-[var(--bg-base)] rounded-full overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="font-mono text-[0.65rem] text-[var(--text-primary)] w-10 text-right">
        {value.toFixed(3)}x
      </span>
    </div>
  );
}

export function SignalSwarmBreakdown({ signalId }: { signalId: string }) {
  const [data, setData] = useState<SignalAI | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!signalId) return;
    setLoading(true);
    fetch(`${getApiBase()}/api/signals/${signalId}/ai`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => setData(d))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [signalId]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-[0.65rem] text-[var(--text-muted)] italic">
        <BrainCircuit size={11} />
        Loading AI analysis...
      </div>
    );
  }

  if (!data || (data.agents.length === 0 && !data.narrative.text)) {
    return (
      <div className="flex items-center gap-2 text-[0.65rem] text-[var(--text-muted)] italic">
        <BrainCircuit size={11} />
        No swarm data yet
      </div>
    );
  }

  const hasSwarm = data.swarm.multiplier != null;
  const multiplierColor =
    data.swarm.multiplier == null
      ? "var(--text-muted)"
      : data.swarm.multiplier >= 1.0
      ? "var(--green)"
      : data.swarm.multiplier >= 0.5
      ? "var(--accent-cyan)"
      : "var(--orange)";

  return (
    <div className="flex flex-col gap-3">
      {/* Section header + aggregate */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-[0.6rem] font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]">
          <BrainCircuit size={10} />
          Swarm AI
        </div>
        {hasSwarm && (
          <div className="flex items-center gap-2">
            <span className="text-[0.6rem] text-[var(--text-muted)]">composite</span>
            <span className="font-mono font-bold text-xs" style={{ color: multiplierColor }}>
              {data.swarm.multiplier!.toFixed(3)}x
            </span>
            {data.swarm.adjusted_confidence != null && (
              <span className="text-[0.6rem] text-[var(--text-muted)] font-mono">
                → {(data.swarm.adjusted_confidence * 100).toFixed(1)}% adj conf
              </span>
            )}
          </div>
        )}
      </div>

      {/* Per-agent rows */}
      {data.agents.length > 0 && (
        <div className="flex flex-col gap-2">
          {data.agents.map((agent) => (
            <div key={agent.agent_id}>
              <div className="flex items-center gap-2 mb-1">
                <div
                  className="w-1.5 h-1.5 rounded-full shrink-0"
                  style={{ background: AGENT_COLORS[agent.agent_id] ?? "var(--text-muted)" }}
                />
                <span className="text-[0.6rem] text-[var(--text-muted)]">{agent.display_name}</span>
                {agent.error && (
                  <span title={agent.error ?? undefined}><AlertTriangle size={9} className="text-[var(--orange)]" /></span>
                )}
                {agent.shadow_at_write && (
                  <span className="text-[0.55rem] text-[var(--text-muted)] italic">shadow</span>
                )}
                {agent.confidence != null && (
                  <span className="ml-auto text-[0.6rem] font-mono text-[var(--text-muted)]">
                    {(agent.confidence * 100).toFixed(0)}% conf
                  </span>
                )}
              </div>
              <MultiplierBar value={agent.error ? null : agent.multiplier} />
              {agent.reasoning && (
                <p className="text-[0.6rem] text-[var(--text-muted)] italic mt-1 leading-snug line-clamp-2">
                  {agent.reasoning}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* ML score */}
      {data.swarm.ml_score != null && (
        <div className="flex items-center gap-2 text-[0.6rem]">
          <span className="text-[var(--text-muted)]">ML score</span>
          <span className="font-mono text-[var(--text-primary)]">{data.swarm.ml_score.toFixed(3)}</span>
        </div>
      )}

      {/* Narrative */}
      {data.narrative.text && (
        <div className="border-t border-[var(--border-subtle)] pt-2 mt-1">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[0.55rem] font-bold uppercase tracking-widest text-[var(--text-muted)]">
              AI Narrative
            </span>
            {data.narrative.model && (
              <span className="text-[0.55rem] font-mono text-[var(--text-muted)]">{data.narrative.model}</span>
            )}
          </div>
          <p className="text-[0.7rem] text-[var(--text-secondary)] leading-relaxed">
            {data.narrative.text}
          </p>
        </div>
      )}
    </div>
  );
}
