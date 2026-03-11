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
import { NarrativePanel } from "./narrative-panel";
import { PriceHero } from "./price-hero";
import { RegimeAmbiance } from "./regime-ambiance";
import { SignalBanner } from "./signal-banner";
import { NarrativeElevated } from "./narrative-elevated";
import { TimeframeMatrix } from "./timeframe-matrix";
import { DrillPanel } from "./drill-panel";
import type { Timeframe, ConnectionStatus, SymbolData, NarrativeData, GroupNarrativeData, SignalData } from "@/lib/types";
import { TF_OFFSETS } from "@/lib/timeframe-utils";
import { TIMEFRAMES } from "@/lib/types";
import { fmtTimeHMS } from "@/lib/format";

const TF_STALENESS_MS: Record<string, number> = {
  "1m":  10 * 60_000,
  "5m":  50 * 60_000,
  "15m": 150 * 60_000,
  "1h":  10 * 3_600_000,
  "4h":  40 * 3_600_000,
  "1d":  10 * 86_400_000,
};

function IndicAgentLogo({ size = 28 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 28 28"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <rect x="2"  y="5"  width="24" height="3" rx="1.5" fill="var(--accent-cyan)" opacity="0.4" />
      <rect x="5"  y="10" width="18" height="3" rx="1.5" fill="var(--accent-cyan)" opacity="0.65" />
      <rect x="8"  y="15" width="12" height="3" rx="1.5" fill="var(--accent-cyan)" opacity="0.85" />
      <rect x="11" y="20" width="6"  height="3" rx="1.5" fill="var(--accent-cyan)" />
      <circle cx="24" cy="21.5" r="2.5" fill="var(--accent-cyan)" opacity="0.9" />
    </svg>
  );
}

export default function TradingDashboard() {
  const [mounted, setMounted] = useState(false);
  const [timeframe, setTimeframe] = useState<Timeframe>("5m");
  const [selectedDrillSignal, setSelectedDrillSignal] = useState<SignalData | null>(null);
  const [activeProfile, setActiveProfile] = useState(
    symbolConfig.getActiveProfile()
  );

  const profiles = useMemo(() => symbolConfig.getAllProfiles(), []);
  const symbols = useMemo(
    () => profiles[activeProfile]?.symbols ?? ["ES", "NQ", "RTY"],
    [activeProfile, profiles]
  );

  const { symbolData, connectionStatus, lastUpdate, narratives, groupNarratives, signalsHistory } = useMarketStream(
    timeframe,
    symbols
  );

  useEffect(() => {
    symbolConfig.loadConfig().then(() => setMounted(true));
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
      <header
        className="flex items-center justify-between px-5 py-2.5 border-b border-[var(--border-subtle)] shrink-0"
        style={{
          background: "rgba(10, 14, 20, 0.85)",
          backdropFilter: "blur(8px)",
        }}
      >
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2.5">
            <IndicAgentLogo size={22} />
            <span style={{
              fontFamily: "var(--font-display)",
              fontWeight: 800,
              fontSize: "0.95rem",
              letterSpacing: "-0.01em",
              color: "var(--text-primary)",
            }}>
              Indic<span style={{ color: "var(--accent-cyan)" }}>Agent</span>
            </span>
          </div>

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
            // Pass all narratives for this symbol — card picks the right TF
            const symNarratives = Object.fromEntries(
              Object.entries(narratives).filter(([, n]) => n.symbol === sym)
            );
            return <SymbolCard
            key={sym}
            data={data}
            narratives={symNarratives}
            globalTf={timeframe}
            selectedDrillSignal={selectedDrillSignal}
            signalsHistory={signalsHistory}
            setSelectedDrillSignal={setSelectedDrillSignal}
          />;
          })}
        </div>
      </main>

      {/* ── AI Narrative Feed ── */}
      <NarrativePanel
        narratives={narratives}
        groupNarratives={groupNarratives}
        activeSymbol={symbols[0] ?? "ES"}
        activeTimeframe={timeframe}
      />

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
  narratives,
  globalTf,
  selectedDrillSignal,
  signalsHistory,
  setSelectedDrillSignal,
}: {
  data: SymbolData;
  narratives: Record<string, NarrativeData>;
  globalTf: Timeframe;
  selectedDrillSignal: SignalData | null;
  signalsHistory: Record<string, SignalData[]>;
  setSelectedDrillSignal: (signal: SignalData | null) => void;
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

  // Active signal is strictly per-TF — signals only show on the TF that generated them.
  // signal_generator currently only emits 1m, so signals appear on the 1m tab only.
  const rawSignal = data.signalsByTf[activeTf] ?? null;
  // Inline (no memo): Date.now() must stay fresh every render so staleness expiry works.
  const activeSignal = (() => {
    if (!rawSignal) return null;
    const ts = new Date(rawSignal.timestamp).getTime();
    const cutoff = TF_STALENESS_MS[activeTf] ?? 3_600_000;
    return isNaN(ts) || Date.now() - ts > cutoff ? null : rawSignal;
  })();

  // Narrative is TF-matched — only show narrative for the active timeframe
  const narrative = narratives[`${data.symbol}:${activeTf}`] ?? null;

  const isLong = activeSignal?.direction === "long";
  const hasSignal = activeSignal !== null;
  const confidence = activeSignal?.confidence ?? null;

  // Bar time from intelligence snapshot (most stable "last computed" indicator)
  const barTime = intel?.barTime ?? indicators?.timestamp ?? null;
  // Age is measured from bar CLOSE (open + tf period), not open — otherwise a fresh 5m bar
  // at 13:15 shows "7m ago" at 13:22 when the close was only 2m ago.
  const tfPeriodMs = (TF_OFFSETS[activeTf] ?? 60) * 1000;
  const barCloseMs = barTime ? new Date(barTime).getTime() + tfPeriodMs : null;
  const barAgeMs = barCloseMs ? Date.now() - barCloseMs : null;
  const barIsStale = barAgeMs !== null && barAgeMs > tfPeriodMs; // >1 full period past close
  const fmtHHMM = (ms: number) => new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  const barOpenStr = barTime ? fmtHHMM(new Date(barTime).getTime()) : null;
  const barCloseStr = barCloseMs ? fmtHHMM(barCloseMs) : null;
  const barOhlcv = intel?.barOhlcv ?? null;

  return (
    <div
      className="flex flex-col surface rounded overflow-hidden"
      style={{
        boxShadow:
          activeSignal && activeSignal.confidence > 0.75
            ? activeSignal.direction === "long"
              ? "0 0 0 1px var(--green-dim)"
              : "0 0 0 1px var(--red-dim)"
            : undefined,
        transition: "box-shadow 0.5s ease",
      }}
    >
      {/* Header: name + symbol + contract + signal badge */}
      <div className="flex items-center justify-between px-3 pt-1.5 pb-0.5 bg-[var(--bg-elevated)]">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-bold text-[var(--text-primary)] tracking-tight">
            {displayName}
          </span>
          <span className="text-[0.6rem] font-semibold text-[var(--text-muted)] uppercase tracking-wider">
            {data.symbol}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          {hasSignal && (
            <div className="flex items-center gap-1">
              <span
                className="text-[0.6rem] font-bold uppercase tracking-widest px-1.5 py-0.5 rounded"
                style={{
                  backgroundColor: isLong ? "var(--green-dim)" : "var(--red-dim)",
                  color: isLong ? "var(--green)" : "var(--red)",
                }}
              >
                {isLong ? "LONG" : "SHORT"}
                {confidence !== null && (
                  <span className="ml-1 opacity-75">{Math.round(confidence * 100)}%</span>
                )}
              </span>
              {activeSignal.signal_computed_at && (
                <span className="text-[0.5rem] font-data text-[var(--text-muted)] opacity-70">
                  {fmtTimeHMS(activeSignal.signal_computed_at)}
                </span>
              )}
            </div>
          )}
          <span className="text-[0.55rem] font-medium text-[var(--text-muted)] bg-[var(--bg-base)] px-1.5 py-0.5 rounded">
            {contract}
          </span>
        </div>
      </div>

      {/* L0: Price hero — bid/ask, bar details, range bars */}
      <div className="bg-[var(--bg-elevated)] border-b border-[var(--border-subtle)]">
        <PriceHero data={data} activeTf={activeTf} />
      </div>

      {/* L0: High-confidence signal banner */}
      <SignalBanner signal={activeSignal} onDrillDown={() => setIsDrilling(true)} />

      {/* L0: Elevated AI narrative (only when high confidence + fresh) */}
      <NarrativeElevated narrative={narrative} signal={activeSignal} />

      {/* L1: Cross-TF matrix — clicking a TF switches card view, not sidebar */}
      <div className="flex items-center justify-between px-2 py-0.5 border-b border-[var(--border-subtle)] bg-[var(--bg-elevated)]">
        {/* Bar time / lag indicator on left */}
        {barCloseStr && (
          <div className="group relative flex items-center gap-1.5 cursor-default">
            <span className="text-[0.55rem] text-[var(--text-muted)] uppercase tracking-wider">
              {activeTf} bar
            </span>
            <span
              className="text-[0.55rem] font-data"
              style={{ color: barIsStale ? "var(--red)" : "var(--text-muted)" }}
            >
              {barCloseStr}
            </span>
            {barIsStale && (
              <span className="text-[0.5rem] text-[var(--red)] opacity-75">
                {barAgeMs !== null ? `${Math.round(barAgeMs / 60000)}m ago` : "stale"}
              </span>
            )}
            {/* OHLCV tooltip */}
            {barOhlcv && (
              <div
                className="pointer-events-none absolute bottom-full left-0 mb-2 z-[9999]
                           opacity-0 group-hover:opacity-100 transition-opacity duration-150
                           rounded border shadow-xl px-2.5 py-2 flex flex-col gap-1 min-w-[10rem]"
                style={{ backgroundColor: "var(--bg-base)", borderColor: "var(--border-default)" }}
              >
                <span className="text-[0.5rem] text-[var(--text-muted)] uppercase tracking-wider mb-0.5">
                  {activeTf} bar · {barOpenStr} → {barCloseStr}
                </span>
                <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
                  {(["open", "high", "low", "close"] as const).map((k) => (
                    <div key={k} className="flex justify-between gap-2">
                      <span className="text-[0.5rem] text-[var(--text-muted)] uppercase">{k}</span>
                      <span className="text-[0.5rem] font-data" style={{ color: "var(--text-primary)" }}>
                        {barOhlcv[k].toFixed(2)}
                      </span>
                    </div>
                  ))}
                </div>
                <div className="flex justify-between gap-2 border-t pt-1" style={{ borderColor: "var(--border-subtle)" }}>
                  <span className="text-[0.5rem] text-[var(--text-muted)] uppercase">vol</span>
                  <span className="text-[0.5rem] font-data" style={{ color: "var(--text-secondary)" }}>
                    {barOhlcv.volume.toLocaleString()}
                  </span>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Timeframe pills on right */}
        <TimeframeMatrix
          tfSignals={data.tfSignals}
          confluence={confluence}
          activeTf={activeTf}
          onSelectTf={(tf) => setActiveTf(tf)}
          onDrillDown={() => setIsDrilling(true)}
        />
      </div>

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
      </RegimeAmbiance>

      {isDrilling && (
        <DrillPanel
          symbol={data.symbol}
          timeframe={activeTf}
          data={data}
          signal={selectedDrillSignal}
          signalsHistory={signalsHistory[data.symbol] || []}
          onSignalSelect={setSelectedDrillSignal}
          onClose={() => {
            setIsDrilling(false);
            setSelectedDrillSignal(null);
          }}
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
    disconnected: { color: "bg-[var(--red)]", label: "Disconnected" },
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
