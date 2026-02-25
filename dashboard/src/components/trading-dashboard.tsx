"use client";

import { useState, useEffect, useMemo } from "react";
import { symbolConfig } from "@/lib/symbol-config";
import { useMarketStream } from "@/hooks/use-market-stream";
import { IndicatorGrid } from "./indicator-grid";
import { StructurePanel } from "./structure-panel";
import { ContextPanel } from "./context-panel";
import { PatternPanel } from "./pattern-panel";
import { SmartMoneyPanel } from "./smart-money-panel";
import { ConfluencePanel } from "./confluence-panel";
import { SignalPanel } from "./signal-panel";
import { NarrativePanel } from "./narrative-panel";
import { ConfidenceRing } from "./confidence-ring";
import { RegimeAmbiance } from "./regime-ambiance";
import { SignalBanner } from "./signal-banner";
import { NarrativeElevated } from "./narrative-elevated";
import { TimeframeMatrix } from "./timeframe-matrix";
import { DrillPanel } from "./drill-panel";
import type { Timeframe, ConnectionStatus, SymbolData, NarrativeData } from "@/lib/types";
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
            // Find freshest narrative for this symbol across any timeframe
            const narrative =
              Object.values(narratives)
                .filter((n) => n.symbol === sym)
                .sort((a, b) => b.receivedAt - a.receivedAt)[0] ?? null;
            return <SymbolCard key={sym} data={data} narrative={narrative} globalTf={timeframe} />;
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
function SymbolCard({
  data,
  narrative,
  globalTf,
}: {
  data: SymbolData;
  narrative: NarrativeData | null;
  globalTf: Timeframe;
}) {
  const [isDrilling, setIsDrilling] = useState(false);
  // activeTf: per-card TF override; resets to global when globalTf changes
  const [activeTf, setActiveTf] = useState<string>(globalTf);
  useEffect(() => { setActiveTf(globalTf); }, [globalTf]);

  const info = symbolConfig.getSymbolInfo(data.symbol);
  const displayName = info?.display_name ?? data.symbol;
  const contract = info?.contract ?? data.symbol;

  // Derive display data from per-TF maps for the active timeframe
  const indicators = data.indicatorsByTf[activeTf] ?? null;
  const intel = data.intelligenceByTf[activeTf] ?? null;
  const structure = intel?.structure ?? null;
  const context = intel?.context ?? null;
  const patterns = intel?.patterns ?? null;
  const smartMoney = intel?.smartMoney ?? null;
  const confluence = intel?.confluence ?? null;

  return (
    <div
      className="flex flex-col surface rounded overflow-hidden"
      style={{
        boxShadow:
          data.signal && data.signal.confidence > 0.75
            ? data.signal.direction === "long"
              ? "0 0 0 1px var(--green-dim)"
              : "0 0 0 1px var(--red-dim)"
            : undefined,
        transition: "box-shadow 0.5s ease",
      }}
    >
      {/* Header: instrument identity */}
      <div className="flex items-center justify-between px-3 py-1.5 bg-[var(--bg-elevated)] border-b border-[var(--border-subtle)]">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-bold text-[var(--text-primary)] tracking-tight">
            {displayName}
          </span>
          <span className="text-[0.6rem] font-semibold text-[var(--text-muted)] uppercase tracking-wider">
            {data.symbol}
          </span>
        </div>
        <span className="text-[0.55rem] font-medium text-[var(--text-muted)] bg-[var(--bg-base)] px-1.5 py-0.5 rounded">
          {contract}
        </span>
      </div>

      {/* L0: Confidence ring + price */}
      <div className="bg-[var(--bg-elevated)] border-b border-[var(--border-subtle)]">
        <ConfidenceRing
          confluence={confluence}
          signal={data.signal}
          price={data.tick.price}
        />
      </div>

      {/* L0: High-confidence signal banner */}
      <SignalBanner signal={data.signal} onDrillDown={() => setIsDrilling(true)} />

      {/* L0: Elevated AI narrative (only when high confidence + fresh) */}
      <NarrativeElevated narrative={narrative} signal={data.signal} />

      {/* L1: Cross-TF matrix — clicking a TF switches card view, not sidebar */}
      <TimeframeMatrix
        tfSignals={data.tfSignals}
        confluence={confluence}
        activeTf={activeTf}
        onSelectTf={(tf) => setActiveTf(tf)}
      />

      {/* L0: Regime ambiance wraps the tier stack */}
      <RegimeAmbiance context={context}>
        {/* Intelligence tiers — fed from active-TF data */}
        <IndicatorGrid indicators={indicators} />
        <div className="border-t border-[var(--border-subtle)]">
          <StructurePanel structure={structure} />
        </div>
        <div className="border-t border-[var(--border-subtle)]">
          <ContextPanel context={context} />
        </div>
        <div className="border-t border-[var(--border-subtle)]">
          <PatternPanel patterns={patterns} />
        </div>
        <div className="border-t border-[var(--border-subtle)]">
          <SmartMoneyPanel smartMoney={smartMoney} />
        </div>
        <div className="border-t border-[var(--border-subtle)]">
          <ConfluencePanel confluence={confluence} />
        </div>
        <div className="border-t border-[var(--border-subtle)]">
          <SignalPanel signal={data.signal} />
        </div>
      </RegimeAmbiance>

      {isDrilling && (
        <DrillPanel
          symbol={data.symbol}
          timeframe={activeTf}
          data={data}
          onClose={() => setIsDrilling(false)}
        />
      )}
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
