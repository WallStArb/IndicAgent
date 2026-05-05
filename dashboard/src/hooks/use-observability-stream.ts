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

async function fetchMetric(query: string, signal: AbortSignal): Promise<string> {
  try {
    const res = await fetch(`/api/metrics?query=${encodeURIComponent(query)}`, { signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    return json?.data?.result?.[0]?.value?.[1] ?? "0";
  } catch (e) {
    if (e instanceof Error && e.name === "AbortError") return "0";
    console.error(`Telemetry fetch error for [${query}]:`, e);
    return "0";
  }
}

export function useObservabilityStream(): ObservabilityMetrics {
  const [metrics, setMetrics] = useState<ObservabilityMetrics>({
    pipeline: [
      { id: "ingestion", throughput: "0", status: "active" },
      { id: "discovery", throughput: "0", status: "active" },
      { id: "compute", throughput: "0", status: "active" },
      { id: "writer", throughput: "0", status: "active" },
    ],
    jitter: { latency: "0ms", jitter: "0ms", health: "0%" },
  });

  useEffect(() => {
    const controller = new AbortController();

    const updateMetrics = async () => {
      const [ingestion, discovery, compute, writer, latency] = await Promise.all([
        fetchMetric("rate(otel_consumer_messages_total[1m])", controller.signal),
        fetchMetric("rate(otel_discovery_ops_total[1m])", controller.signal),
        fetchMetric("rate(otel_compute_ops_total[1m])", controller.signal),
        fetchMetric("rate(otel_writer_ops_total[1m])", controller.signal),
        fetchMetric("otel_ingestion_latency_ms_avg", controller.signal),
      ]);

      if (controller.signal.aborted) return;

      const safe = (v: string) => { const n = Number(v); return Number.isFinite(n) ? Math.round(n) : 0; };
      setMetrics({
        pipeline: [
          { id: "ingestion", throughput: `${safe(ingestion)} msg/s`, status: "active" },
          { id: "discovery", throughput: `${safe(discovery)} ops/s`, status: "active" },
          { id: "compute", throughput: `${safe(compute)} ops/s`, status: "active" },
          { id: "writer", throughput: `${safe(writer)} ops/s`, status: "active" },
        ],
        jitter: {
          latency: `${safe(latency)}ms`,
          // TODO: wire otel_feed_jitter_ms and otel_feed_health_pct Prometheus queries
          jitter: "0.2ms",
          health: "99.9%",
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
