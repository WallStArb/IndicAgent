"use client";

import { useState, useEffect, useMemo } from "react";
import { symbolConfig } from "@/lib/symbol-config";
import { useMarketStream } from "@/hooks/use-market-stream";
import { PriceHero } from "./price-hero";
import { IndicatorGrid } from "./indicator-grid";
import { StructurePanel } from "./structure-panel";
import { ContextPanel } from "./context-panel";
import { PatternPanel } from "./pattern-panel";
import { SmartMoneyPanel } from "./smart-money-panel";
import { ConfluencePanel } from "./confluence-panel";
import { SignalPanel } from "./signal-panel";
import { NarrativePanel } from "./narrative-panel";
import type { Timeframe, ConnectionStatus, SymbolData } from "@/lib/types";
import { TIMEFRAMES } from "@/lib/types";

export default function TradingDashboard() {
  const [mounted, setMounted] = useState(false);
  const [timeframe, setTimeframe] = useState<Timeframe>("1m");
  const [activeProfile, setActiveProfile] = useState(
    symbolConfig.getActiveProfile()
  );

  const profiles = useMemo(() => symbolConfig.getAllProfiles(), []);
  const symbols = useMemo(
    () => profiles[activeProfile]?.symbols ?? ["ES", "NQ", "RTY"],
    [activeProfile, profiles]
  );

  const { symbolData, connectionStatus, lastUpdate, narratives } = useMarketStream(
    timeframe,
    symbols
  );

  useEffect(() => {
    setMounted(true);
  }, []);

  function handleProfileChange(profile: string) {
    symbolConfig.setActiveProfile(profile);
    setActiveProfile(profile);
  }

  if (!mounted) {
    return (
      <div className="flex items-center justify-center h-screen bg-[var(--bg-base)]">
        <div className="flex flex-col items-center gap-2">
          <div className="w-6 h-6 border-2 border-[var(--border-bright)] border-t-[var(--blue)] rounded-full animate-spin" />
          <span className="text-xs text-[var(--text-muted)]">Loading...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-[var(--bg-base)] overflow-hidden">
      {/* ── Top Bar ── */}
      <header className="flex items-center justify-between px-3 py-1.5 border-b border-[var(--border-subtle)] bg-[var(--bg-surface)] shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold tracking-tight text-[var(--text-primary)]">
            INDIC<span className="text-[var(--blue)]">AGENT</span>
          </span>

          {/* Profile switcher */}
          <ProfileSwitcher
            profiles={profiles}
            active={activeProfile}
            onChange={handleProfileChange}
          />

          <span className="text-[0.6rem] text-[var(--text-muted)]">
            {symbols.length} instruments
          </span>
        </div>

        <div className="flex items-center gap-3">
          {/* Timeframe pills */}
          <div className="flex items-center gap-0.5 bg-[var(--bg-base)] rounded p-0.5">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf.value}
                onClick={() => setTimeframe(tf.value)}
                className={`
                  px-2 py-0.5 rounded text-[0.65rem] font-semibold transition-colors
                  ${
                    timeframe === tf.value
                      ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]"
                      : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
                  }
                `}
              >
                {tf.short}
              </button>
            ))}
          </div>
          <StatusDot status={connectionStatus} />
        </div>
      </header>

      {/* ── Symbol Grid ── */}
      <main className="flex-1 overflow-auto p-1.5">
        <div
          className="grid gap-1.5 content-start"
          style={{
            gridTemplateColumns: `repeat(auto-fill, minmax(340px, 1fr))`,
          }}
        >
          {symbols.map((sym) => {
            const data = symbolData[sym];
            if (!data) return null;
            return <SymbolCard key={sym} data={data} />;
          })}
        </div>
      </main>

      {/* ── AI Narrative Feed ── */}
      <NarrativePanel narratives={narratives} />

      {/* ── Footer ── */}
      <footer className="flex items-center justify-between px-3 py-1 border-t border-[var(--border-subtle)] bg-[var(--bg-surface)] shrink-0">
        <span className="text-[0.6rem] text-[var(--text-muted)]">
          {lastUpdate > 0
            ? `Last update: ${new Date(lastUpdate).toLocaleTimeString()}`
            : "Waiting for data..."}
        </span>
        <span className="text-[0.6rem] text-[var(--text-muted)]">
          {timeframe.toUpperCase()} · {symbols.length} symbols · IndicAgent v0.2
        </span>
      </footer>
    </div>
  );
}

/** Self-contained instrument card with all intelligence tiers */
function SymbolCard({ data }: { data: SymbolData }) {
  return (
    <div className="flex flex-col surface rounded overflow-hidden">
      {/* Price hero with symbol header */}
      <div className="bg-[var(--bg-elevated)] border-b border-[var(--border-subtle)]">
        <PriceHero data={data} />
      </div>

      {/* Indicators */}
      <IndicatorGrid indicators={data.indicators} />

      {/* Intelligence tiers */}
      <div className="border-t border-[var(--border-subtle)]">
        <StructurePanel structure={data.structure} />
      </div>
      <div className="border-t border-[var(--border-subtle)]">
        <ContextPanel context={data.context} />
      </div>
      <div className="border-t border-[var(--border-subtle)]">
        <PatternPanel patterns={data.patterns} />
      </div>
      <div className="border-t border-[var(--border-subtle)]">
        <SmartMoneyPanel smartMoney={data.smartMoney} />
      </div>
      <div className="border-t border-[var(--border-subtle)]">
        <ConfluencePanel confluence={data.confluence} />
      </div>
      <div className="border-t border-[var(--border-subtle)]">
        <SignalPanel signal={data.signal} />
      </div>
    </div>
  );
}

/** Compact profile pill switcher */
function ProfileSwitcher({
  profiles,
  active,
  onChange,
}: {
  profiles: Record<string, { name: string; symbols: string[]; description: string }>;
  active: string;
  onChange: (key: string) => void;
}) {
  const keys = Object.keys(profiles);

  return (
    <div className="flex items-center gap-0.5 bg-[var(--bg-base)] rounded p-0.5">
      {keys.map((key) => (
        <button
          key={key}
          onClick={() => onChange(key)}
          title={profiles[key].description}
          className={`
            px-2 py-0.5 rounded text-[0.6rem] font-semibold transition-colors whitespace-nowrap
            ${
              active === key
                ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]"
                : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
            }
          `}
        >
          {profiles[key].name}
        </button>
      ))}
    </div>
  );
}

function StatusDot({ status }: { status: ConnectionStatus }) {
  const config = {
    connected: { color: "bg-[var(--green)]", label: "Live" },
    connecting: { color: "bg-[var(--amber)]", label: "Connecting" },
    disconnected: { color: "bg-[var(--red)]", label: "Offline" },
  };
  const { color, label } = config[status];

  return (
    <div className="flex items-center gap-1.5">
      <span
        className={`w-1.5 h-1.5 rounded-full ${color} ${status === "connected" ? "live-pulse" : ""}`}
      />
      <span className="text-[0.6rem] font-medium text-[var(--text-muted)]">
        {label}
      </span>
    </div>
  );
}
