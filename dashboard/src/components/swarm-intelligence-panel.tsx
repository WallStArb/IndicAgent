"use client";

import { useEffect, useState, useCallback } from "react";
import { BrainCircuit, Zap, Clock, CheckCircle, AlertTriangle, RefreshCw } from "lucide-react";
import { getApiBase } from "@/lib/api";
import { DashboardNav } from "@/components/dashboard-nav";

interface AgentStat {
  agent_id: string;
  display_name: string;
  model: string;
  provider: string;
  calls_24h: number;
  avg_latency_ms: number;
  p95_latency_ms: number;
  tokens_24h: number;
  parse_rate: number | null;
  success_rate: number | null;
}

interface ProviderStat {
  provider: string;
  calls_24h: number;
  tokens_24h: number;
  avg_latency_ms: number;
}

interface NarrativeEntry {
  signal_id: string | null;
  symbol: string;
  timeframe: string;
  model: string;
  provider: string;
  latency_ms: number;
  tokens: number;
  succeeded: boolean;
  called_at: string;
  text_preview: string;
}

interface AiStats {
  agents: AgentStat[];
  providers: ProviderStat[];
  narratives: NarrativeEntry[];
  totals: {
    calls_24h: number;
    tokens_24h: number;
    success_rate: number | null;
  };
}

const AGENT_COLORS: Record<string, string> = {
  skeptic_v1: "var(--red)",
  correlation_v1: "var(--accent-cyan)",
  regime_coherence_v1: "var(--purple)",
  counterfactual_v1: "var(--orange)",
  narrative_v1: "var(--green)",
  ml_scorer_v1: "var(--yellow)",
};

function fmtMs(ms: number | null | undefined): string {
  if (ms == null) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${ms}ms`;
}

function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function fmtPct(v: number | null): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function providerLabel(provider: string): string {
  if (provider.startsWith("ollama:")) return provider.replace("ollama:", "Ollama/");
  if (provider.startsWith("openrouter:")) return provider.replace("openrouter:", "OR/");
  return provider;
}

function AgentCard({ agent }: { agent: AgentStat }) {
  const color = AGENT_COLORS[agent.agent_id] ?? "var(--accent-cyan)";
  const parseOk = agent.parse_rate != null && agent.parse_rate >= 0.95;
  const latencyWarn = agent.avg_latency_ms != null && agent.avg_latency_ms > 30_000;

  return (
    <div className="surface rounded-xl p-5 border border-[var(--border-subtle)] flex flex-col gap-3">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full shrink-0" style={{ background: color }} />
          <span className="font-semibold text-sm text-[var(--text-primary)]">{agent.display_name}</span>
        </div>
        <span className="text-[0.6rem] font-mono uppercase tracking-widest px-1.5 py-0.5 rounded bg-[var(--bg-elevated)] text-[var(--text-muted)]">
          {providerLabel(agent.provider)}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
        <div>
          <div className="text-[var(--text-muted)] text-[0.6rem] uppercase tracking-wider mb-0.5">Calls / 24h</div>
          <div className="font-mono text-[var(--text-primary)] font-medium">{agent.calls_24h.toLocaleString()}</div>
        </div>
        <div>
          <div className="text-[var(--text-muted)] text-[0.6rem] uppercase tracking-wider mb-0.5">Avg Latency</div>
          <div className={`font-mono font-medium ${latencyWarn ? "text-[var(--orange)]" : "text-[var(--text-primary)]"}`}>
            {fmtMs(agent.avg_latency_ms)}
          </div>
        </div>
        <div>
          <div className="text-[var(--text-muted)] text-[0.6rem] uppercase tracking-wider mb-0.5">p95 Latency</div>
          <div className="font-mono text-[var(--text-muted)]">{fmtMs(agent.p95_latency_ms)}</div>
        </div>
        <div>
          <div className="text-[var(--text-muted)] text-[0.6rem] uppercase tracking-wider mb-0.5">Tokens</div>
          <div className="font-mono text-[var(--text-primary)]">{fmtTokens(agent.tokens_24h)}</div>
        </div>
        <div>
          <div className="text-[var(--text-muted)] text-[0.6rem] uppercase tracking-wider mb-0.5">Parse Rate</div>
          <div className={`font-mono font-medium flex items-center gap-1 ${parseOk ? "text-[var(--green)]" : "text-[var(--orange)]"}`}>
            {parseOk
              ? <CheckCircle size={10} />
              : <AlertTriangle size={10} />}
            {fmtPct(agent.parse_rate)}
          </div>
        </div>
        <div>
          <div className="text-[var(--text-muted)] text-[0.6rem] uppercase tracking-wider mb-0.5">Model</div>
          <div className="font-mono text-[var(--text-muted)] truncate text-[0.65rem]">{agent.model}</div>
        </div>
      </div>
    </div>
  );
}

function NarrativeFeedRow({ entry }: { entry: NarrativeEntry }) {
  const relTime = entry.called_at
    ? new Date(entry.called_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "—";

  return (
    <div className="px-4 py-3 border-b border-[var(--border-subtle)] last:border-0 hover:bg-[var(--bg-elevated)] transition-colors">
      <div className="flex items-center gap-3 mb-1.5">
        <span className="font-bold text-xs text-[var(--text-primary)] w-10 shrink-0">{entry.symbol}</span>
        <span className="text-[0.6rem] font-mono px-1.5 py-0.5 rounded bg-[var(--bg-base)] text-[var(--text-muted)]">{entry.timeframe}</span>
        <span className="text-[0.6rem] text-[var(--text-muted)] ml-auto">{relTime}</span>
        <span className="text-[0.6rem] font-mono text-[var(--text-muted)]">{fmtMs(entry.latency_ms)}</span>
        <span className="text-[0.6rem] font-mono text-[var(--text-muted)]">{fmtTokens(entry.tokens ?? 0)}</span>
        {!entry.succeeded && (
          <AlertTriangle size={10} className="text-[var(--red)]" />
        )}
      </div>
      <p className="text-[0.7rem] text-[var(--text-secondary)] leading-relaxed line-clamp-2">
        {entry.text_preview || <span className="italic text-[var(--text-muted)]">No response text</span>}
      </p>
    </div>
  );
}

export function SwarmIntelligencePanel() {
  const [stats, setStats] = useState<AiStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch(`${getApiBase()}/api/ai/stats`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setStats(data);
      setLastRefresh(new Date());
    } catch (e) {
      console.error("Failed to fetch AI stats", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStats();
    const id = setInterval(fetchStats, 30_000);
    return () => clearInterval(id);
  }, [fetchStats]);

  const swarmAgents = stats?.agents.filter((a) => a.agent_id !== "narrative_v1") ?? [];
  const narrativeAgent = stats?.agents.find((a) => a.agent_id === "narrative_v1") ?? null;

  return (
    <div className="flex flex-col min-h-screen bg-[var(--bg-base)]">
    <DashboardNav />
    <div className="flex flex-col flex-1 p-6 gap-6 overflow-auto">
      <header className="flex items-center justify-between shrink-0">
        <div className="flex items-center gap-3">
          <BrainCircuit size={20} className="text-[var(--accent-cyan)]" />
          <div>
            <h1 className="text-xl font-bold text-[var(--text-primary)]">Swarm Intelligence</h1>
            <p className="text-sm text-[var(--text-muted)]">AI agent observability — last 24 hours</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {lastRefresh && (
            <span className="text-[0.6rem] text-[var(--text-muted)]">
              updated {lastRefresh.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
            </span>
          )}
          <button
            onClick={fetchStats}
            className="p-1.5 rounded-lg hover:bg-[var(--bg-elevated)] text-[var(--text-muted)] hover:text-[var(--text-primary)] transition-colors"
          >
            <RefreshCw size={14} />
          </button>
        </div>
      </header>

      {/* Totals strip */}
      {stats && (
        <div className="grid grid-cols-3 gap-4 shrink-0">
          {[
            { label: "Total Calls", value: stats.totals.calls_24h.toLocaleString(), icon: Zap },
            { label: "Total Tokens", value: fmtTokens(stats.totals.tokens_24h), icon: BrainCircuit },
            { label: "Success Rate", value: fmtPct(stats.totals.success_rate), icon: CheckCircle },
          ].map(({ label, value, icon: Icon }) => (
            <div key={label} className="surface rounded-xl p-4 border border-[var(--border-subtle)] flex items-center gap-3">
              <Icon size={16} className="text-[var(--accent-cyan)] shrink-0" />
              <div>
                <div className="text-[0.6rem] uppercase tracking-widest text-[var(--text-muted)]">{label}</div>
                <div className="font-mono font-bold text-lg text-[var(--text-primary)]">{value}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Swarm agent cards */}
      <section className="shrink-0">
        <h2 className="text-[0.6rem] font-bold uppercase tracking-[0.2em] text-[var(--text-muted)] mb-3">
          Alpha Swarm Agents
        </h2>
        {loading ? (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="surface rounded-xl p-5 border border-[var(--border-subtle)] h-44 animate-pulse bg-[var(--bg-elevated)]" />
            ))}
          </div>
        ) : swarmAgents.length === 0 ? (
          <div className="text-sm text-[var(--text-muted)] italic">No swarm calls in the last 24 hours</div>
        ) : (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {swarmAgents.map((agent) => (
              <AgentCard key={agent.agent_id} agent={agent} />
            ))}
          </div>
        )}
      </section>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 flex-1 min-h-0">
        {/* Narrative feed */}
        <div className="lg:col-span-2 surface rounded-xl border border-[var(--border-subtle)] flex flex-col min-h-0">
          <div className="px-4 py-3 border-b border-[var(--border-subtle)] flex items-center justify-between shrink-0">
            <h2 className="text-[0.6rem] font-bold uppercase tracking-[0.2em] text-[var(--text-muted)]">
              Recent Narratives
            </h2>
            {narrativeAgent && (
              <div className="flex items-center gap-3 text-[0.6rem] text-[var(--text-muted)]">
                <span className="font-mono">{narrativeAgent.calls_24h} calls</span>
                <span className="font-mono">{fmtMs(narrativeAgent.avg_latency_ms)} avg</span>
              </div>
            )}
          </div>
          <div className="overflow-auto flex-1">
            {loading ? (
              <div className="p-4 text-sm text-[var(--text-muted)] italic">Loading...</div>
            ) : (stats?.narratives ?? []).length === 0 ? (
              <div className="p-4 text-sm text-[var(--text-muted)] italic">No narratives generated in the last 24 hours</div>
            ) : (
              (stats?.narratives ?? []).map((entry, i) => (
                <NarrativeFeedRow key={i} entry={entry} />
              ))
            )}
          </div>
        </div>

        {/* Provider breakdown + timing */}
        <div className="flex flex-col gap-4">
          <div className="surface rounded-xl border border-[var(--border-subtle)] p-5">
            <h2 className="text-[0.6rem] font-bold uppercase tracking-[0.2em] text-[var(--text-muted)] mb-4">
              Provider Breakdown
            </h2>
            {loading ? (
              <div className="text-sm text-[var(--text-muted)]">—</div>
            ) : (stats?.providers ?? []).length === 0 ? (
              <div className="text-sm text-[var(--text-muted)] italic">No data</div>
            ) : (
              <div className="flex flex-col gap-3">
                {(stats?.providers ?? []).map((p) => (
                  <div key={p.provider}>
                    <div className="flex justify-between items-center mb-1">
                      <span className="text-xs text-[var(--text-primary)] font-medium">{providerLabel(p.provider)}</span>
                      <span className="text-[0.6rem] font-mono text-[var(--text-muted)]">{p.calls_24h.toLocaleString()} calls</span>
                    </div>
                    <div className="flex justify-between text-[0.6rem] text-[var(--text-muted)] font-mono">
                      <span>{fmtTokens(p.tokens_24h)} tokens</span>
                      <span>{fmtMs(p.avg_latency_ms)} avg</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="surface rounded-xl border border-[var(--border-subtle)] p-5">
            <h2 className="text-[0.6rem] font-bold uppercase tracking-[0.2em] text-[var(--text-muted)] mb-4 flex items-center gap-2">
              <Clock size={11} />
              Latency Budget
            </h2>
            <div className="flex flex-col gap-3">
              {(stats?.agents ?? [])
                .filter((a) => a.agent_id !== "narrative_v1")
                .map((a) => {
                  const budget = 5000;
                  const pct = Math.min(100, ((a.avg_latency_ms ?? 0) / budget) * 100);
                  const over = (a.avg_latency_ms ?? 0) > budget;
                  return (
                    <div key={a.agent_id}>
                      <div className="flex justify-between items-center mb-1">
                        <span className="text-[0.6rem] text-[var(--text-muted)]">{a.display_name}</span>
                        <span className={`text-[0.6rem] font-mono ${over ? "text-[var(--orange)]" : "text-[var(--green)]"}`}>
                          {fmtMs(a.avg_latency_ms)}
                        </span>
                      </div>
                      <div className="w-full h-1 bg-[var(--bg-base)] rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all"
                          style={{
                            width: `${pct}%`,
                            background: over ? "var(--orange)" : "var(--accent-cyan)",
                          }}
                        />
                      </div>
                    </div>
                  );
                })}
              <p className="text-[0.55rem] text-[var(--text-muted)] italic mt-1">
                5s budget is observational — latency does not gate execution
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
    </div>
  );
}
