"use client";

import { useState, useEffect } from "react";
import { fmtLatency } from "@/lib/format";

// ── Types ────────────────────────────────────────────────────────────────────

export interface PipelineNode {
  id: string;
  label: string;
  sublabel: string;
  rate: number | null;
  rateUnit: string;
  latencyMs: number | null;
  lagSec: number | null;
  errorRate: number | null;
  bufferDepth: number | null;
  extras: Array<{ label: string; value: string }>;
  health: "active" | "stale" | "degraded" | "unknown";
  isBottleneck: boolean;
  grafanaDashboard: string;
}

export interface ServiceEntry {
  unit: string;
  label: string;
  layer: number;
  layerName: string;
  health: "active" | "stale" | "unknown";
  lastSeenSec: number | null;
}

export interface SummaryMetrics {
  activeSignals: number | null;
  pipelineLatencyMs: number | null;
  i1LatencyMs: number | null;
  i7LatencyMs: number | null;
  ingestionRate: number | null;
  featureWriteRate: number | null;
  threadWorkers: number | null;
}

export interface ObservabilityData {
  nodes: PipelineNode[];
  services: ServiceEntry[];
  summary: SummaryMetrics;
  lastUpdated: number;
}

// ── Service layer map ────────────────────────────────────────────────────────

const SERVICE_LAYERS: Array<{ layer: number; name: string; units: string[] }> = [
  { layer: 1, name: "Data Ingestion", units: ["indicagent-ibkr-provider"] },
  { layer: 2, name: "Stream Merge",   units: ["indicagent-provider-merger"] },
  { layer: 3, name: "Bar Processing", units: ["indicagent-bar-aggregator", "indicagent-bar-auditor"] },
  { layer: 4, name: "OHLCV Persist",  units: ["indicagent-bar-writer"] },
  { layer: 5, name: "Intelligence",   units: ["indicagent-intelligence-pipeline", "indicagent-cross-asset", "indicagent-macro-compute"] },
  { layer: 6, name: "Feature Writers",units: ["indicagent-feature-writer", "indicagent-signal-writer", "indicagent-signal-tracker-compute", "indicagent-lifecycle-writer", "indicagent-lineage-writer", "indicagent-ctx-writer"] },
  { layer: 7, name: "AI / LLM",       units: ["indicagent-alpha-swarm", "indicagent-narrative-compute", "indicagent-llm-writer", "indicagent-swarm-ledger-writer"] },
  { layer: 8, name: "Analytics",      units: ["indicagent-signal-metrics-compute", "indicagent-signal-metrics-writer", "indicagent-graduation-compute", "indicagent-graduation-writer", "indicagent-dlq-drain", "indicagent-ml-training"] },
  { layer: 9, name: "Audit",          units: ["indicagent-signal-auditor", "indicagent-signal-replay", "indicagent-alerting-agent"] },
  { layer: 10, name: "Meta",          units: ["indicagent-service-auditor"] },
];

// Maps systemd unit names to the agent_id label value in agent_last_message_timestamp_seconds.
// Only services that emit that metric are listed here.
const UNIT_TO_AGENT: Record<string, string> = {
  "indicagent-signal-tracker-compute":  "signal_tracker",
  "indicagent-alpha-swarm":             "alpha_swarm",
  "indicagent-cross-asset":             "cross_asset_analyzer",
  "indicagent-macro-compute":           "macro_analyzer",
  "indicagent-graduation-compute":      "graduation_analyzer",
  "indicagent-lifecycle-writer":        "lifecycle_writer",
  "indicagent-lineage-writer":          "lineage_writer",
  "indicagent-signal-writer":           "signal_writer",
  "indicagent-llm-writer":              "llm_writer",
};

const GRAFANA = {
  pipeline: "http://localhost:3001/d/indicagent-pipeline-health",
  signals:  "http://localhost:3001/d/indicagent-signals-i8",
  ops:      "http://localhost:3001/d/indicagent-operations",
  plugins:  "http://localhost:3001/d/indicagent-plugin-latency",
};

// ── Fetch helpers ────────────────────────────────────────────────────────────

async function fetchScalar(query: string, signal: AbortSignal): Promise<number | null> {
  try {
    const res = await fetch(`/api/metrics?query=${encodeURIComponent(query)}`, { signal });
    if (!res.ok) return null;
    const json = await res.json();
    const r = json?.data?.result;
    if (!r || r.length === 0) return null;
    const v = parseFloat(r[0]?.value?.[1]);
    return Number.isFinite(v) ? v : null;
  } catch (e) {
    if (e instanceof Error && e.name === "AbortError") return null;
    return null;
  }
}

interface VectorResult { labels: Record<string, string>; value: number }

async function fetchVector(query: string, signal: AbortSignal): Promise<VectorResult[]> {
  try {
    const res = await fetch(`/api/metrics?query=${encodeURIComponent(query)}`, { signal });
    if (!res.ok) return [];
    const json = await res.json();
    return (json?.data?.result ?? []).map((r: { metric: Record<string, string>; value: [number, string] }) => ({
      labels: r.metric,
      value: parseFloat(r.value[1]),
    })).filter((r: VectorResult) => Number.isFinite(r.value));
  } catch {
    return [];
  }
}

// ── Health helpers ───────────────────────────────────────────────────────────

function nodeHealth(
  rate: number | null,
  errorRate: number | null,
  lagSec: number | null,
): "active" | "stale" | "degraded" | "unknown" {
  if (errorRate !== null && errorRate > 0.01) return "degraded";
  if (lagSec !== null && lagSec > 60) return "degraded";
  if (rate === null) return "unknown";
  if (rate > 0) return "active";
  return "stale";
}

function serviceHealth(lastSeenSec: number | null): "active" | "stale" | "unknown" {
  if (lastSeenSec === null) return "unknown";
  if (lastSeenSec < 300) return "active";
  return "stale";
}

// ── Main hook ────────────────────────────────────────────────────────────────

const EMPTY: ObservabilityData = {
  nodes: [],
  services: [],
  summary: {
    activeSignals: null, pipelineLatencyMs: null,
    i1LatencyMs: null, i7LatencyMs: null,
    ingestionRate: null, featureWriteRate: null, threadWorkers: null,
  },
  lastUpdated: 0,
};

export function useObservabilityStream(): ObservabilityData {
  const [data, setData] = useState<ObservabilityData>(EMPTY);

  useEffect(() => {
    const controller = new AbortController();
    const s = controller.signal;

    let running = false;

    const refresh = async () => {
      if (running) return;
      running = true;
      const [
        // Ingestion
        ingestionRate, ingestionLag, ingestionErrors,
        // Intelligence
        intelRate, pipelineLatency, i1Latency, i7Latency,
        intelErrors, intelBuffer, threadWorkers,
        // Signals
        signalRate, activeSignals, signalDlq,
        // Writers
        featureWriteRate, featureBuffer, barWriteRate, barWriterLag,
        featureCommitLatency,
        // Agent staleness (parallel with scalars)
        agentTimestamps,
      ] = await Promise.all([
        // Ingestion
        fetchScalar("rate(bar_agg_bars_processed_total[1m])", s),
        fetchScalar("bar_agg_consumer_lag_seconds", s),
        fetchScalar("rate(bar_agg_aggregation_errors_total[1m])", s),
        // Intelligence
        fetchScalar("rate(intelligence_pipeline_bars_processed_total[1m])", s),
        fetchScalar("intelligence_pipeline_pipeline_latency_ms", s),
        fetchScalar("intelligence_pipeline_i1_latency_ms", s),
        fetchScalar("intelligence_pipeline_i7_latency_ms", s),
        fetchScalar("rate(intelligence_pipeline_pipeline_errors_total[1m])", s),
        fetchScalar("intelligence_pipeline_output_buffer_depth", s),
        fetchScalar("intelligence_pipeline_thread_pool_workers", s),
        // Signals
        fetchScalar("rate(intelligence_pipeline_signals_generated_total[1m])", s),
        fetchScalar("signal_tracker_compute_active_signals", s),
        fetchScalar("rate(intelligence_pipeline_signal_dlq_total[1m])", s),
        // Writers
        fetchScalar("rate(feature_writer_events_consumed_total[1m])", s),
        fetchScalar("feature_writer_agent_buffer_depth", s),
        fetchScalar("rate(bar_writer_bars_written_total[1m])", s),
        fetchScalar("bar_writer_persistence_consumer_lag", s),
        fetchScalar("histogram_quantile(0.95, rate(feature_writer_agent_commit_latency_seconds_bucket[5m]))", s),
        fetchVector("agent_last_message_timestamp_seconds", s),
      ]);

      running = false;
      if (s.aborted) return;

      const now = Date.now() / 1000;
      const agentAge: Record<string, number> = {};
      for (const r of agentTimestamps) {
        const name = r.labels["agent_id"];
        if (name) agentAge[name] = now - r.value;
      }

      const swarmAge = agentAge["alpha_swarm"] ?? null;

      // ── Build nodes ───────────────────────────────────────────────────────

      const rawNodes: Omit<PipelineNode, "isBottleneck">[] = [
        {
          id: "ingestion",
          label: "Data Ingestion",
          sublabel: "Bar Aggregator · IBKR Provider",
          rate: ingestionRate,
          rateUnit: "bars/s",
          latencyMs: null,
          lagSec: ingestionLag,
          errorRate: ingestionErrors,
          bufferDepth: null,
          extras: [
            { label: "Lag",    value: ingestionLag    !== null ? `${ingestionLag.toFixed(1)}s`   : "—" },
            { label: "Errors", value: ingestionErrors  !== null ? `${ingestionErrors.toFixed(3)}/s` : "—" },
          ],
          health: nodeHealth(ingestionRate, ingestionErrors, ingestionLag),
          grafanaDashboard: GRAFANA.pipeline,
        },
        {
          id: "compute",
          label: "I1–I7 Intelligence",
          sublabel: "132 plugins · 6 tiers",
          rate: intelRate,
          rateUnit: "bars/s",
          latencyMs: pipelineLatency,
          lagSec: null,
          errorRate: intelErrors,
          bufferDepth: intelBuffer,
          extras: [
            { label: "I1 lat",   value: i1Latency      !== null ? fmtLatency(i1Latency)         : "—" },
            { label: "I7 lat",   value: i7Latency      !== null ? fmtLatency(i7Latency)         : "—" },
            { label: "Workers",  value: threadWorkers  !== null ? String(Math.round(threadWorkers)) : "—" },
            { label: "Buffer",   value: intelBuffer    !== null ? String(Math.round(intelBuffer))   : "—" },
          ],
          health: nodeHealth(intelRate, intelErrors, null),
          grafanaDashboard: GRAFANA.plugins,
        },
        {
          id: "signals",
          label: "Signal Generation",
          sublabel: "I7 aggregator · signal ledger",
          rate: signalRate,
          rateUnit: "sig/s",
          latencyMs: null,
          lagSec: null,
          errorRate: signalDlq,
          bufferDepth: null,
          extras: [
            { label: "Active",  value: activeSignals !== null ? activeSignals.toLocaleString() : "—" },
            { label: "DLQ/s",   value: signalDlq     !== null ? `${signalDlq.toFixed(3)}`        : "—" },
          ],
          health: nodeHealth(signalRate, signalDlq, null),
          grafanaDashboard: GRAFANA.signals,
        },
        {
          id: "writers",
          label: "Persistence Layer",
          sublabel: "Feature writer · Bar writer · Signal writer",
          rate: featureWriteRate,
          rateUnit: "events/s",
          latencyMs: featureCommitLatency !== null ? featureCommitLatency * 1000 : null,
          lagSec: barWriterLag,
          errorRate: null,
          bufferDepth: featureBuffer,
          extras: [
            { label: "Bar writes", value: barWriteRate    !== null ? `${barWriteRate.toFixed(2)}/s`     : "—" },
            { label: "Feat buf",   value: featureBuffer   !== null ? String(Math.round(featureBuffer)) : "—" },
            { label: "Bar lag",    value: barWriterLag    !== null ? `${barWriterLag.toFixed(0)}ms`     : "—" },
            { label: "P95 commit", value: featureCommitLatency !== null ? fmtLatency(featureCommitLatency * 1000) : "—" },
          ],
          health: nodeHealth(featureWriteRate, null, barWriterLag !== null ? barWriterLag / 1000 : null),
          grafanaDashboard: GRAFANA.pipeline,
        },
        {
          id: "ai",
          label: "AI Swarm",
          sublabel: "Alpha · Skeptic · Counterfactual · Narrative",
          rate: null,
          rateUnit: "agents",
          latencyMs: null,
          lagSec: null,
          errorRate: null,
          bufferDepth: null,
          extras: [
            { label: "Last seen", value: swarmAge !== null ? `${Math.round(swarmAge)}s ago` : "—" },
          ],
          health: (() => {
            if (swarmAge === null) return "unknown";
            if (swarmAge < 300)  return "active";
            if (swarmAge < 1800) return "stale";
            return "degraded";
          })(),
          grafanaDashboard: GRAFANA.signals,
        },
      ];

      // Mark bottleneck: node with highest latency
      const latencies = rawNodes.map(n => ({ id: n.id, ms: n.latencyMs ?? 0 }));
      const maxMs = Math.max(...latencies.map(l => l.ms));
      const bottleneckId = maxMs > 500 ? latencies.find(l => l.ms === maxMs)?.id : null;

      const nodes: PipelineNode[] = rawNodes.map(n => ({
        ...n,
        isBottleneck: n.id === bottleneckId,
      }));

      // ── Build service health ──────────────────────────────────────────────

      const services: ServiceEntry[] = SERVICE_LAYERS.flatMap(layer =>
        layer.units.map(unit => {
          const agentName = UNIT_TO_AGENT[unit];
          const lastSeenSec = agentName !== undefined ? (agentAge[agentName] ?? null) : null;
          const shortLabel = unit.replace("indicagent-", "");
          return {
            unit,
            label: shortLabel,
            layer: layer.layer,
            layerName: layer.name,
            health: serviceHealth(lastSeenSec),
            lastSeenSec,
          };
        })
      );

      setData({
        nodes,
        services,
        summary: {
          activeSignals,
          pipelineLatencyMs: pipelineLatency,
          i1LatencyMs: i1Latency,
          i7LatencyMs: i7Latency,
          ingestionRate,
          featureWriteRate,
          threadWorkers,
        },
        lastUpdated: now,
      });
    };

    refresh();
    const interval = setInterval(refresh, 5000);
    return () => { controller.abort(); clearInterval(interval); running = false; };
  }, []);

  return data;
}
