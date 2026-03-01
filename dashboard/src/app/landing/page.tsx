"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import { useMarketStream } from "@/hooks/use-market-stream";
import { symbolConfig } from "@/lib/symbol-config";
import { HeroSection } from "@/components/landing/hero-section";
import { SignalFilters, type SignalFilters as SignalFiltersType } from "@/components/landing/signal-filters";
import SignalCard from "@/components/landing/signal-card";
import { ArrowRight } from "lucide-react";
import type { Timeframe, SignalData } from "@/lib/types";

// Asset class groupings — single source of truth for the landing page.
// Filter, label derivation, and symbol list all derive from this one constant.
const ASSET_CLASSES = {
  Equity: ["ES", "NQ", "RTY", "YM"],
  Energy: ["CL"],
  Metals: ["GC", "SI", "HG", "PL"],
  Rates: ["ZN", "ZF", "ZB", "ZT", "VX"],
  FX: ["EURUSD", "GBPUSD", "USDJPY", "USDCHF"],
  Crypto: ["BTCUSD", "ETHUSD", "SOLUSD"],
  Agriculture: ["ZS", "ZC", "ZW"],
} as const;

// Hoisted — stable reference, never recreated on render
const allSymbols = Object.values(ASSET_CLASSES).flat() as string[];

function getAssetClass(symbol: string): string {
  for (const [cls, syms] of Object.entries(ASSET_CLASSES)) {
    if ((syms as readonly string[]).includes(symbol)) return cls;
  }
  return "Other";
}

export default function LandingPage() {
  const [activeTf, setActiveTf] = useState<Timeframe>("5m");
  const [filters, setFilters] = useState<SignalFiltersType>({
    confidence: "all",
    cis: "all",
    timeframe: "all",
    assetClass: "all",
  });

  const { symbolData, narratives } = useMarketStream(activeTf, allSymbols);

  const filteredSignals = useMemo(() => {
    const signals: Array<{
      symbol: string;
      displayName: string;
      signal: SignalData;
      assetClass: string;
    }> = [];

    const oneHourAgo = Date.now() - 3_600_000;

    Object.entries(symbolData).forEach(([symbol, data]) => {
      if (!data.signalsByTf) return;

      Object.entries(data.signalsByTf).forEach(([tf, signal]) => {
        if (!signal) return;

        // Timeframe filter
        if (filters.timeframe !== "all" && tf !== filters.timeframe) return;

        // Confidence filters
        if (filters.confidence === "65+" && signal.confidence < 0.65) return;
        if (filters.confidence === "75+" && signal.confidence < 0.75) return;

        // CIS filter
        if (filters.cis === "cis-only" && signal.confidence < 0.7) return;

        // Staleness filter
        const signalTs = new Date(signal.timestamp).getTime();
        if (isNaN(signalTs) || signalTs < oneHourAgo) return;

        // Asset class filter — single lookup into ASSET_CLASSES
        const assetClass = getAssetClass(symbol);
        if (filters.assetClass !== "all" && assetClass !== filters.assetClass) return;

        signals.push({
          symbol,
          displayName: symbolConfig.getDisplayName(symbol),
          signal,
          assetClass,
        });
      });
    });

    // Pre-compute timestamps for sort to avoid repeated Date parsing
    return signals
      .map((s) => ({ ...s, ts: new Date(s.signal.timestamp).getTime() }))
      .sort((a, b) => {
        const confDiff = b.signal.confidence - a.signal.confidence;
        return confDiff !== 0 ? confDiff : b.ts - a.ts;
      });
  }, [symbolData, filters]);

  return (
    <div className="min-h-screen">
      <HeroSection />

      <section className="px-6 py-12">
        <div className="max-w-7xl mx-auto">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2
                className="text-2xl font-semibold mb-2"
                style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}
              >
                Live Trading Signals
              </h2>
              <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
                Real-time signals across futures, forex, and crypto markets
              </p>
            </div>
            <Link
              href="/dashboard"
              className="flex items-center gap-2 px-4 py-2.5 rounded-lg font-medium transition-all duration-200 hover:scale-105"
              style={{
                background: "var(--accent-cyan)",
                color: "#0A0E14",
                boxShadow: "0 4px 12px rgba(78, 214, 200, 0.3)",
              }}
            >
              Enter Full Dashboard
              <ArrowRight size={18} />
            </Link>
          </div>

          <SignalFilters filters={filters} onFiltersChange={setFilters} />

          {filteredSignals.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {filteredSignals.map((item) => (
                <SignalCard
                  key={`${item.symbol}-${item.signal.timeframe}-${item.signal.timestamp}`}
                  symbol={item.symbol}
                  displayName={item.displayName}
                  signal={item.signal}
                  data={symbolData[item.symbol]}
                  assetClass={item.assetClass}
                  narrative={narratives[`${item.symbol}:${item.signal.timeframe}`] ?? null}
                />
              ))}
            </div>
          ) : (
            <div className="py-16 text-center" style={{ color: "var(--text-muted)" }}>
              No signals match the current filters.
            </div>
          )}
        </div>
      </section>

      <section className="px-6 py-12 border-t">
        <div className="max-w-5xl mx-auto">
          <h2
            className="text-2xl font-semibold mb-6 text-center"
            style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}
          >
            Intelligence Pipeline Architecture
          </h2>
          <div
            className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"
            style={{ color: "var(--text-secondary)" }}
          >
            {[
              { layer: "Layer 4", title: "AI Intelligence (I8)", detail: "LLM analysis, narrative generation" },
              { layer: "Layer 3", title: "Pattern Intelligence (I5-I7)", detail: "Pattern detection, confluence, trading signals" },
              { layer: "Layer 2", title: "Mathematical Intelligence (I1-I4)", detail: "Technical indicators, context classification" },
              { layer: "Layer 1", title: "Data Foundation", detail: "Tick/bar collection, event-driven bus, typed streams" },
            ].map(({ layer, title, detail }) => (
              <div
                key={layer}
                className="p-4 rounded-lg border"
                style={{ background: "var(--surface-card)", borderColor: "var(--border-subtle)" }}
              >
                <div className="text-sm font-semibold mb-2" style={{ color: "var(--text-primary)" }}>{layer}</div>
                <div className="text-xs">{title}</div>
                <div className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>{detail}</div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
