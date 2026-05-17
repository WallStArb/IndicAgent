"use client";

import { useState, useEffect } from "react";

interface PipelineMetric {
  id: string;
  throughput: string;
  status: "active" | "warning" | "error";
}

interface JitterMetric {
  latency: string;
  jitter: string;
  health: string;
}

export interface ObservabilityMetrics {
  pipeline: PipelineMetric[];
  jitter: JitterMetric;
}

// null = series missing in Prometheus (service likely down); "0" = present but idle
async function fetchMetric(query: string, signal: AbortSignal): Promise<string | null> {
  try {
    const res = await fetch(`/api/metrics?query=${encodeURIComponent(query)}`, { signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    const result = json?.data?.result;
    if (!result || result.length === 0) return null;
    return result[0]?.value?.[1] ?? "0";
  } catch (e) {
    if (e instanceof Error && e.name === "AbortError") return null;
    console.error(`Telemetry fetch error for [${query}]:`, e);
    return null;
  }
}

function safeFloat(v: string | null, decimals = 0): number {
  if (v === null) return 0;
  const n = Number(v);
  if (!Number.isFinite(n)) return 0;
  return decimals > 0 ? parseFloat(n.toFixed(decimals)) : Math.round(n);
}

function formatThroughput(val: string | null, unit: string, decimals = 1): string {
  return `${safeFloat(val, decimals)} ${unit}`;
}

function statusFrom(healthVal: string | null): "active" | "warning" {
  return healthVal !== null ? "active" : "warning";
}

export function useObservabilityStream(): ObservabilityMetrics {
  const [metrics, setMetrics] = useState<ObservabilityMetrics>({
    pipeline: [
      { id: "ingestion", throughput: "---", status: "active" },
      { id: "intelligence", throughput: "---", status: "active" },
      { id: "signals", throughput: "---", status: "active" },
      { id: "writers", throughput: "---", status: "active" },
    ],
    jitter: { latency: "---", jitter: "---", health: "---" },
  });

  useEffect(() => {
    const controller = new AbortController();

    const updateMetrics = async () => {
      const [
        ingestionRate, ingestionHealth,
        intelligenceRate, intelligenceHealth,
        signalsRate,
        writersRate, writersHealth,
        pipelineLatency, i1Latency,
        activeSignals,
      ] = await Promise.all([
        fetchMetric("rate(bar_agg_bars_processed_total[1m])", controller.signal),
        fetchMetric("bar_aggregator_bars_in_flight", controller.signal),
        fetchMetric("rate(intelligence_pipeline_bars_processed_total[1m])", controller.signal),
        fetchMetric("intelligence_pipeline_output_buffer_depth", controller.signal),
        fetchMetric("rate(intelligence_pipeline_signals_generated_total[1m])", controller.signal),
        fetchMetric("rate(feature_writer_events_consumed_total[1m])", controller.signal),
        fetchMetric("feature_writer_agent_buffer_depth", controller.signal),
        fetchMetric("intelligence_pipeline_pipeline_latency_ms", controller.signal),
        fetchMetric("intelligence_pipeline_i1_latency_ms", controller.signal),
        fetchMetric("signal_tracker_compute_active_signals", controller.signal),
      ]);

      if (controller.signal.aborted) return;

      setMetrics({
        pipeline: [
          { id: "ingestion", throughput: formatThroughput(ingestionRate, "bars/s"), status: statusFrom(ingestionHealth) },
          { id: "intelligence", throughput: formatThroughput(intelligenceRate, "bars/s"), status: statusFrom(intelligenceHealth) },
          { id: "signals", throughput: formatThroughput(signalsRate, "sig/s", 2), status: statusFrom(intelligenceHealth) },
          { id: "writers", throughput: formatThroughput(writersRate, "events/s"), status: statusFrom(writersHealth) },
        ],
        jitter: {
          latency: pipelineLatency !== null ? `${safeFloat(pipelineLatency)}ms` : "---",
          jitter: i1Latency !== null ? `${safeFloat(i1Latency)}ms` : "---",
          health: activeSignals !== null ? `${safeFloat(activeSignals)} sigs` : "---",
        },
      });
    };

    updateMetrics();
    const interval = setInterval(updateMetrics, 5000);
    return () => {
      controller.abort();
      clearInterval(interval);
    };
  }, []);

  return metrics;
}
