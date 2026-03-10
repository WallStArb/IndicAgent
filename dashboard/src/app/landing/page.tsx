"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import { useMarketStream } from "@/hooks/use-market-stream";
import { symbolConfig } from "@/lib/symbol-config";
import { LandingNav } from "@/components/landing/landing-nav";
import { HeroSection } from "@/components/landing/hero-section";
import { TierShowcase } from "@/components/landing/tier-showcase";
import { PlatformHighlights } from "@/components/landing/platform-highlights";
import { IntelligencePillars } from "@/components/landing/intelligence-pillars";
import { SignalFilters, type SignalFilters as SignalFiltersType } from "@/components/landing/signal-filters";
import SignalCard from "@/components/landing/signal-card";
import { ArrowRight } from "lucide-react";
import type { Timeframe, SignalData } from "@/lib/types";

// Asset class groupings — single source of truth for the landing page.
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

// TF-aware staleness windows and long-TF display caps
const TF_STALENESS_MS: Record<string, number> = {
  "1m":  15 * 60_000,
  "5m":  30 * 60_000,
  "15m": 60 * 60_000,
  "1h":  4 * 3_600_000,
  "4h":  8 * 3_600_000,
  "1d":  24 * 3_600_000,
};
const TF_MAX_SHOWN: Record<string, number> = {
  "1h": 3,
  "4h": 2,
  "1d": 1,
};

export default function LandingPage() {
  const [activeTf] = useState<Timeframe>("5m");
  const [filters, setFilters] = useState<SignalFiltersType>({
    confidence: "all",
    cis: "all",
    timeframe: "all",
    assetClass: "all",
  });

  const { symbolData, narratives, signalsHistory } = useMarketStream(activeTf, allSymbols);

  // No-op callback for signal selection - managed internally by DrillPanel/RecentSignals
  const handleSignalSelect = () => {};

  const filteredSignals = useMemo(() => {
    const signals: Array<{
      symbol: string;
      displayName: string;
      signal: SignalData;
      assetClass: string;
    }> = [];

    const longTfCounts: Record<string, number> = {};
    const now = Date.now();

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

        // TF-aware staleness filter
        const signalTs = new Date(signal.timestamp).getTime();
        const stalenessMs = TF_STALENESS_MS[tf] ?? 3_600_000;
        if (isNaN(signalTs) || now - signalTs > stalenessMs) return;

        // Cap long-TF signals to avoid stale dominance
        if (TF_MAX_SHOWN[tf] != null) {
          longTfCounts[tf] = longTfCounts[tf] ?? 0;
          if (longTfCounts[tf] >= TF_MAX_SHOWN[tf]) return;
          longTfCounts[tf]++;
        }

        // Asset class filter
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

    return signals
      .map((s) => ({ ...s, ts: new Date(s.signal.timestamp).getTime() }))
      .sort((a, b) => {
        const confDiff = b.signal.confidence - a.signal.confidence;
        return confDiff !== 0 ? confDiff : b.ts - a.ts;
      });
  }, [symbolData, filters]);

  return (
    <div className="min-h-screen">
      <LandingNav />
      <HeroSection activeSignalCount={filteredSignals.length} />
      <TierShowcase />
      <PlatformHighlights />
      <IntelligencePillars />

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
              className="text-sm font-medium flex items-center gap-1 hover:opacity-80 transition-opacity"
              style={{ color: "var(--accent-cyan)" }}
            >
              View all <ArrowRight size={14} />
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
                  signalsHistory={signalsHistory[item.symbol] || []}
                  onSignalSelect={handleSignalSelect}
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
    </div>
  );
}
