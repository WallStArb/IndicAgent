"use client";

import Link from "next/link";
import { Gauge, Database, BrainCircuit, Activity, ChevronRight } from "lucide-react";
import { FloatingDock } from "@/components/floating-dock";

const GRAFANA_URL = process.env.NEXT_PUBLIC_GRAFANA_URL ?? "http://localhost:3001";
const LANGFUSE_URL = process.env.NEXT_PUBLIC_LANGFUSE_URL ?? "http://localhost:3010";
const MLFLOW_URL = process.env.NEXT_PUBLIC_MLFLOW_URL ?? "http://localhost:5000";

const TOOLS = [
  { name: "Command Center", path: "/dashboard/observability", icon: Activity, desc: "Real-time swarm pulse & latency", isExternal: false },
  { name: "Swarm Intelligence", path: "/dashboard/ai", icon: BrainCircuit, desc: "Agent stats, narrative feed, latency & token observability", isExternal: false },
  { name: "Forensic Analysis", path: GRAFANA_URL, icon: Gauge, desc: "Grafana deep-dive metrics", isExternal: true },
  { name: "Training Data", path: MLFLOW_URL, icon: Database, desc: "MLflow model versioning", isExternal: true },
];

export function ObservabilityHub() {
  return (
    <div className="min-h-screen bg-[var(--bg-base)]">
    <DashboardNav />
    <div className="p-6 max-w-4xl mx-auto">
      <header className="mb-10">
        <h1 className="text-2xl font-bold text-[var(--text-primary)]">Observability Hub</h1>
        <p className="text-[var(--text-muted)]">Centralized cockpit for swarm intelligence and system forensics</p>
      </header>

      <div className="grid gap-4">
        {TOOLS.map((tool) => (
          <Link
            key={tool.name}
            href={tool.path}
            target={tool.isExternal ? "_blank" : undefined}
            rel={tool.isExternal ? "noopener noreferrer" : undefined}
            className="flex items-center justify-between p-6 rounded-xl surface border border-[var(--border-subtle)] hover:border-[var(--accent-cyan)] transition-colors group"
          >
            <div className="flex items-center gap-4">
              <div className="p-3 rounded-lg bg-[var(--bg-elevated)] text-[var(--accent-cyan)]">
                <tool.icon size={20} />
              </div>
              <div>
                <h2 className="font-semibold text-[var(--text-primary)]">{tool.name}</h2>
                <p className="text-xs text-[var(--text-muted)]">{tool.desc}</p>
              </div>
            </div>
            <ChevronRight className="text-[var(--border-bright)] group-hover:text-[var(--accent-cyan)]" />
          </Link>
        ))}
      </div>
    </div>
    </div>
  );
}
