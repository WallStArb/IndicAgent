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
import { WatchlistRail } from "./watchlist-rail";
import { SignalAlertStrip } from "./signal-alert-strip";
import { SkeletonCard } from "./skeleton-card";
import type { Timeframe, ConnectionStatus, SymbolData, NarrativeData, GroupNarrativeData, SignalData } from "@/lib/types";
import { TF_OFFSETS } from "@/lib/timeframe-utils";
import { TIMEFRAMES } from "@/lib/types";
import { fmtTimeHMS } from "@/lib/format";
import { LayoutGrid, Rows3, BarChart2 } from "lucide-react";
import Link from "next/link";

const TF_STALENESS_MS: Record<string, number> = {
  "1m":  10 * 60_000,
  "5m":  50 * 60_000,
  "15m": 150 * 60_000,
  "1h":  10 * 3_600_000,
  "4h":  40 * 3_600_000,
  "1d":  10 * 86_400_000,
};

// Auto-switch to focus layout above this count
const GRID_MODE_MAX = 12;

type LayoutMode = "focus" | "grid";

// ── Sector grouping config ──

const SECTOR_GROUPS: { key: string; label: string; sectors: string[] }[] = [
  { key: "equity",    label: "Equity Indices",    sectors: ["equity_index", "volatility"] },
  { key: "rates",     label: "Interest Rates",    sectors: ["interest_rates"] },
  { key: "energy",    label: "Energy",            sectors: ["energy"] },
  { key: "metals",    label: "Metals",            sectors: ["metals", "gold_miners", "commodity"] },
  { key: "ag",        label: "Agriculture",       sectors: ["agriculture"] },
  { key: "fx",        label: "FX",                sectors: ["fx"] },
  { key: "crypto",    label: "Crypto",            sectors: ["crypto"] },
  // ETF sub-groups
  { key: "etf_broad", label: "ETFs — Broad/Macro",sectors: ["broad_market", "rates", "credit"] },
  { key: "etf_sector",label: "ETFs — Sectors",    sectors: ["technology", "healthcare", "financials", "industrials", "consumer_discretionary", "consumer_staples", "materials", "communications", "utilities", "real_estate", "homebuilders", "biotech"] },
  { key: "etf_factor",label: "ETFs — Factor/Intl",sectors: ["factor", "emerging_markets", "international"] },
  { key: "other",     label: "Other",             sectors: [] }, // catch-all
];

function getSectorGroup(sector: string | undefined, assetClass?: string): string {
  if (!sector && !assetClass) return "other";
  for (const g of SECTOR_GROUPS) {
    if (g.key === "other") continue;
    if (sector && g.sectors.includes(sector)) return g.key;
  }
  // equity asset_class with unrecognized sector → ETF broad as fallback
  if (assetClass === "equity") return "etf_broad";
  return "other";
}

function filterNarrativesBySymbol(narratives: Record<string, NarrativeData>, symbol: string): Record<string, NarrativeData> {
  return Object.fromEntries(Object.entries(narratives).filter(([, n]) => n.symbol === symbol));
}

/** Groups symbols by sector and renders them in labeled sections */
function GroupedSymbolGrid({
  symbols,
  symbolData,
  narratives,
  timeframe,
  selectedDrillSignal,
  signalsHistory,
  setSelectedDrillSignal,
}: {
  symbols: string[];
  symbolData: Record<string, SymbolData>;
  narratives: Record<string, NarrativeData>;
  timeframe: Timeframe;
  selectedDrillSignal: SignalData | null;
  signalsHistory: Record<string, SignalData[]>;
  setSelectedDrillSignal: (s: SignalData | null) => void;
}) {
  // Build groups — preserve original order within each group
  const grouped = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const sym of symbols) {
      const info = symbolConfig.getSymbolInfo(sym);
      const groupKey = getSectorGroup(info?.sector, info?.asset_class);
      if (!map.has(groupKey)) map.set(groupKey, []);
      map.get(groupKey)!.push(sym);
    }
    // Return in canonical SECTOR_GROUPS order
    return SECTOR_GROUPS
      .map((g) => ({ ...g, symbols: map.get(g.key) ?? [] }))
      .filter((g) => g.symbols.length > 0);
  }, [symbols]);

  return (
    <div className="p-1.5 space-y-3">
      {grouped.map((group) => (
        <section key={group.key}>
          {/* Section header */}
          <div className="flex items-center gap-2 mb-1.5 px-0.5">
            <span className="text-[0.6rem] font-bold uppercase tracking-widest text-[var(--text-muted)]">
              {group.label}
            </span>
            <span className="text-[0.55rem] text-[var(--border-bright)]">
              {group.symbols.length}
            </span>
            <div className="flex-1 h-px bg-[var(--border-subtle)]" />
          </div>

          {/* Card grid */}
          <div
            className="grid gap-1.5 content-start"
            style={{ gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))" }}
          >
            {group.symbols.map((sym) => {
              const data = symbolData[sym];
              if (!data) return <SkeletonCard key={sym} symbol={sym} />;
              const symNarratives = filterNarrativesBySymbol(narratives, sym);
              return (
                <SymbolCard
                  key={sym}
                  data={data}
                  narratives={symNarratives}
                  globalTf={timeframe}
                  selectedDrillSignal={selectedDrillSignal}
                  signalsHistory={signalsHistory}
                  setSelectedDrillSignal={setSelectedDrillSignal}
                />
              );
            })}
          </div>
        </section>
      ))}
    </div>
  );
}

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

  // Layout mode: auto-select based on profile size, but allow manual override
  const [layoutMode, setLayoutMode] = useState<LayoutMode>(
    symbols.length > GRID_MODE_MAX ? "focus" : "grid"
  );

  // Selected instrument in focus mode (defaults to first symbol)
  const [selectedSymbol, setSelectedSymbol] = useState<string>(symbols[0] ?? "ES");

  // When profile changes: re-evaluate layout and reset selection
  useEffect(() => {
    setLayoutMode(symbols.length > GRID_MODE_MAX ? "focus" : "grid");
    setSelectedSymbol(symbols[0] ?? "ES");
  }, [symbols]);

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

  function handleSignalAlertSelect(sym: string) {
    setSelectedSymbol(sym);
    if (layoutMode === "grid") setLayoutMode("focus");
  }

  // Ensure selectedSymbol is always valid within current profile
  const activeSymbol = symbols.includes(selectedSymbol) ? selectedSymbol : (symbols[0] ?? "ES");

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

          <Link
            href="/signals"
            className="flex items-center gap-1 px-2 py-0.5 rounded text-[0.62rem] text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-elevated)] transition-colors"
          >
            <BarChart2 size={10} />
            Signals
          </Link>

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

          {/* Layout mode toggle */}
          <LayoutToggle mode={layoutMode} onChange={setLayoutMode} />

          <StatusDot status={connectionStatus} />
        </div>
      </header>

      {/* ── Global Signal Alert Strip ── */}
      <SignalAlertStrip
        symbolData={symbolData}
        symbols={symbols}
        onSelectSymbol={handleSignalAlertSelect}
      />

      {/* ── Main Content: Rail + View ── */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left watchlist rail — focus mode only */}
        {layoutMode === "focus" && (
          <WatchlistRail
            symbols={symbols}
            symbolData={symbolData}
            selectedSymbol={activeSymbol}
            globalTf={timeframe}
            onSelect={setSelectedSymbol}
          />
        )}

        {/* Content area */}
        <main className="flex-1 overflow-auto">
          {layoutMode === "grid" ? (
            /* ── Grouped Grid View ── */
            <GroupedSymbolGrid
              symbols={symbols}
              symbolData={symbolData}
              narratives={narratives}
              timeframe={timeframe}
              selectedDrillSignal={selectedDrillSignal}
              signalsHistory={signalsHistory}
              setSelectedDrillSignal={setSelectedDrillSignal}
            />
          ) : (
            /* ── Focus View ── */
            <div className="p-1.5 flex gap-1.5 h-full">
              {/* Primary card */}
              <div className="flex-1 min-w-0 max-w-[480px]">
                {symbolData[activeSymbol] ? (
                  <SymbolCard
                    data={symbolData[activeSymbol]}
                    narratives={filterNarrativesBySymbol(narratives, activeSymbol)}
                    globalTf={timeframe}
                    selectedDrillSignal={selectedDrillSignal}
                    signalsHistory={signalsHistory}
                    setSelectedDrillSignal={setSelectedDrillSignal}
                  />
                ) : (
                  <SkeletonCard symbol={activeSymbol} />
                )}
              </div>

              {/* Narrative feed: right column in focus mode */}
              <div className="w-72 shrink-0 hidden lg:block overflow-auto">
                <NarrativePanel
                  narratives={narratives}
                  groupNarratives={groupNarratives}
                  activeSymbol={activeSymbol}
                  activeTimeframe={timeframe}
                />
              </div>
            </div>
          )}
        </main>
      </div>

      {/* ── AI Narrative Feed — grid mode only (fixed bottom strip) ── */}
      {layoutMode === "grid" && (
        <NarrativePanel
          narratives={narratives}
          groupNarratives={groupNarratives}
          activeSymbol={symbols[0] ?? "ES"}
          activeTimeframe={timeframe}
        />
      )}

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

  // Bar window for active TF — data timestamp when available, clock-aligned fallback
  const tfPeriodMs = (TF_OFFSETS[activeTf] ?? 60) * 1000;
  const barTime = intel?.barTime || indicators?.timestamp || null;
  const dataBarOpenMs = barTime ? new Date(barTime).getTime() : NaN;
  const now = Date.now();
  const barOpenMs = !isNaN(dataBarOpenMs) ? dataBarOpenMs : Math.floor(now / tfPeriodMs) * tfPeriodMs - tfPeriodMs;
  const barCloseMs = barOpenMs + tfPeriodMs;
  const fmt = (ms: number): string => {
    const d = new Date(ms);
    if (isNaN(d.getTime())) return "??:??";
    return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  };
  const barWindowStr = `${fmt(barOpenMs)}→${fmt(barCloseMs)}`;
  // Staleness: last received bar is more than one full period behind the expected close
  const dataBarCloseMs = !isNaN(dataBarOpenMs) ? dataBarOpenMs + tfPeriodMs : null;
  const barIsStale = dataBarCloseMs !== null && now - dataBarCloseMs > tfPeriodMs;


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
      {/* Header: name + symbol | TF pills + signal badge */}
      <div className="flex items-center justify-between px-3 pt-1.5 pb-1 bg-[var(--bg-elevated)]">
        <div className="flex items-baseline gap-2 min-w-0">
          <span className="text-sm font-bold text-[var(--text-primary)] tracking-tight truncate">
            {displayName}
          </span>
          <span className="text-[0.6rem] font-semibold text-[var(--text-secondary)] uppercase tracking-wider shrink-0">
            {data.symbol}
          </span>
          <span className="text-[0.55rem] font-medium text-[var(--text-muted)] shrink-0">
            {contract}
          </span>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span
            className="text-[0.5rem] font-data tabular-nums"
            style={{ color: barIsStale ? "var(--red)" : "var(--text-secondary)" }}
          >
            {barWindowStr}{barIsStale && " ·stale"}
          </span>
          <TimeframeMatrix
            tfSignals={data.tfSignals}
            confluence={confluence}
            activeTf={activeTf}
            onSelectTf={(tf) => setActiveTf(tf)}
            compact
          />
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
            </div>
          )}
        </div>
      </div>

      {/* Price hero — single inline row */}
      <PriceHero data={data} activeTf={activeTf} />

      {/* L0: High-confidence signal banner */}
      <SignalBanner signal={activeSignal} onDrillDown={() => setIsDrilling(true)} />

      {/* L0: Elevated AI narrative (only when high confidence + fresh) */}
      <NarrativeElevated narrative={narrative} signal={activeSignal} />


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

/** Grid / Focus layout toggle */
function LayoutToggle({
  mode,
  onChange,
}: {
  mode: LayoutMode;
  onChange: (m: LayoutMode) => void;
}) {
  return (
    <div className="flex items-center gap-0.5 bg-[var(--bg-base)] rounded p-0.5">
      <button
        onClick={() => onChange("grid")}
        title="Grid view — all instruments"
        className={`p-1 rounded transition-colors ${
          mode === "grid"
            ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]"
            : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
        }`}
      >
        <LayoutGrid size={11} />
      </button>
      <button
        onClick={() => onChange("focus")}
        title="Focus view — watchlist + detail"
        className={`p-1 rounded transition-colors ${
          mode === "focus"
            ? "bg-[var(--bg-elevated)] text-[var(--text-primary)]"
            : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
        }`}
      >
        <Rows3 size={11} />
      </button>
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
