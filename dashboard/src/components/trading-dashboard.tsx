"use client";

import { useState, useEffect, useMemo, useRef } from "react";
import { symbolConfig } from "@/lib/symbol-config";
import { useMarketStream } from "@/hooks/use-market-stream";
import { IndicatorGrid } from "./indicator-grid";
import { StructurePanel } from "./structure-panel";
import { ContextPanel } from "./context-panel";
import { PatternPanel } from "./pattern-panel";
import { SmartMoneyPanel } from "./smart-money-panel";
import { ConfluencePanel } from "./confluence-panel";
import { PriceHero } from "./price-hero";
import { RegimeAmbiance } from "./regime-ambiance";
import { TimeframeMatrix } from "./timeframe-matrix";
import { DrillPanel } from "./drill-panel";
import { WatchlistRail } from "./watchlist-rail";
import { SkeletonCard } from "./skeleton-card";
import type { Timeframe, ConnectionStatus, SymbolData } from "@/lib/types";
import { TF_OFFSETS } from "@/lib/timeframe-utils";
import { TIMEFRAMES } from "@/lib/types";
import { LayoutGrid, Rows3, ScanLine, ChevronDown } from "lucide-react";

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

/** Groups symbols by sector and renders them in labeled sections */
function GroupedSymbolGrid({
  symbols,
  symbolData,
  timeframe,
}: {
  symbols: string[];
  symbolData: Record<string, SymbolData>;
  timeframe: Timeframe;
}) {
  const grouped = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const sym of symbols) {
      const info = symbolConfig.getSymbolInfo(sym);
      const groupKey = getSectorGroup(info?.sector, info?.asset_class);
      if (!map.has(groupKey)) map.set(groupKey, []);
      map.get(groupKey)!.push(sym);
    }
    return SECTOR_GROUPS
      .map((g) => ({ ...g, symbols: map.get(g.key) ?? [] }))
      .filter((g) => g.symbols.length > 0);
  }, [symbols]);

  return (
    <div className="p-4 space-y-6">
      {grouped.map((group) => (
        <section key={group.key}>
          {/* Section header */}
          <div className="flex items-center gap-3 mb-3 px-1">
            <span className="text-[0.65rem] font-bold uppercase tracking-[0.15em] text-[var(--text-muted)]">
              {group.label}
            </span>
            <span className="text-[0.55rem] font-mono text-[var(--border-bright)]">
              {group.symbols.length}
            </span>
            <div className="flex-1 h-px bg-[var(--border-subtle)]" />
          </div>

          {/* Card grid */}
          <div
            className="grid gap-3 content-start"
            style={{ gridTemplateColumns: "repeat(auto-fill, minmax(350px, 1fr))" }}
          >
            {group.symbols.map((sym) => {
              const data = symbolData[sym];
              if (!data) return <SkeletonCard key={sym} symbol={sym} />;
              return <SymbolCard key={sym} data={data} globalTf={timeframe} />;
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

  const { symbolData, connectionStatus, lastUpdate } = useMarketStream(
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
    <div className="h-full flex flex-col bg-[var(--bg-base)] overflow-hidden">
      {/* ── Top Bar ── */}
      <header
        className="flex items-center justify-between px-6 py-3 border-b border-[var(--border-subtle)] shrink-0"
        style={{
          background: "rgba(6, 9, 15, 0.95)",
          backdropFilter: "blur(12px)",
        }}
      >
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-3">
            <IndicAgentLogo size={24} />
            <span style={{
              fontFamily: "var(--font-display)",
              fontWeight: 800,
              fontSize: "1rem",
              letterSpacing: "-0.02em",
              color: "var(--text-primary)",
            }}>
              Indic<span style={{ color: "var(--accent-cyan)" }}>Agent</span>
            </span>
          </div>

          {/* Universe chip */}
          <ProfileChip
            profiles={profiles}
            active={activeProfile}
            symbolData={symbolData}
            onChange={handleProfileChange}
          />
        </div>

        <div className="flex items-center gap-2 md:gap-4">
          {/* Mobile: timeframe select */}
          <div className="relative md:hidden">
            <select
              value={timeframe}
              onChange={(e) => setTimeframe(e.target.value as Timeframe)}
              className="appearance-none text-[0.65rem] font-semibold bg-[var(--bg-elevated)] text-[var(--text-primary)] border border-[var(--border-default)] rounded-md pl-2.5 pr-6 py-1 outline-none cursor-pointer"
            >
              {TIMEFRAMES.map((tf) => (
                <option key={tf.value} value={tf.value}>{tf.short}</option>
              ))}
            </select>
            <ChevronDown size={10} className="absolute right-1.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)] pointer-events-none" />
          </div>

          {/* Desktop: timeframe pills */}
          <div className="hidden md:flex items-center gap-1 bg-[var(--bg-surface)] border border-[var(--border-subtle)] rounded-lg p-0.5">
            {TIMEFRAMES.map((tf) => (
              <button
                key={tf.value}
                onClick={() => setTimeframe(tf.value)}
                className={`
                  px-3 py-1 rounded-md text-[0.65rem] font-semibold transition-all
                  ${
                    timeframe === tf.value
                      ? "bg-[var(--bg-elevated)] text-[var(--text-primary)] shadow-sm"
                      : "text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
                  }
                `}
              >
                {tf.short}
              </button>
            ))}
          </div>

          {/* Layout mode toggle — desktop only */}
          <div className="hidden md:block">
            <LayoutToggle mode={layoutMode} onChange={setLayoutMode} />
          </div>

          <StatusDot status={connectionStatus} />
        </div>
      </header>

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
              timeframe={timeframe}
            />
          ) : (
            /* ── Focus View ── */
            <div className="p-1.5 flex gap-1.5 h-full">
              {/* Primary card */}
              <div className="flex-1 min-w-0 max-w-[480px]">
                {symbolData[activeSymbol] ? (
                  <SymbolCard data={symbolData[activeSymbol]} globalTf={timeframe} />
                ) : (
                  <SkeletonCard symbol={activeSymbol} />
                )}
              </div>

            </div>
          )}
        </main>
      </div>

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
  globalTf,
}: {
  data: SymbolData;
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
    >
      {/* Header: name + symbol | TF pills + drill button */}
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
        <div className="flex items-center gap-1.5 shrink-0">
          <TimeframeMatrix
            confluence={confluence}
            activeTf={activeTf}
            onSelectTf={(tf) => setActiveTf(tf)}
            compact
          />
          {/* Always-visible drill button */}
          <button
            onClick={() => setIsDrilling(true)}
            title="Open intelligence detail"
            className="p-0.5 rounded text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-surface)] transition-colors"
          >
            <ScanLine size={11} />
          </button>
        </div>
      </div>

      {/* Price hero — single inline row */}
      <PriceHero data={data} activeTf={activeTf} barWindowStr={barWindowStr} barIsStale={barIsStale} />

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
          onClose={() => setIsDrilling(false)}
        />
      )}
    </div>
  );
}

/** Universe context chip — compact trigger + profile popover */
function ProfileChip({
  profiles,
  active,
  symbolData,
  onChange,
}: {
  profiles: Record<string, { name: string; symbols: string[]; description: string }>;
  active: string;
  symbolData: Record<string, SymbolData>;
  onChange: (key: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const keys = Object.keys(profiles);
  const current = profiles[active];

  useEffect(() => {
    if (!open) return;
    function onOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onEsc(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onOutside);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onOutside);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  return (
    <div ref={ref} style={{ position: "relative" }}>
      {/* ── Chip trigger ── */}
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: "7px",
          padding: "5px 10px",
          background: open ? "var(--bg-elevated)" : "var(--bg-surface)",
          border: `1px solid ${open ? "rgba(78,214,200,0.35)" : "var(--border-default)"}`,
          borderRadius: "9px",
          cursor: "pointer",
          transition: "border-color 0.15s, background 0.15s",
          whiteSpace: "nowrap",
        }}
      >
        {/* Name */}
        <span style={{
          fontFamily: "var(--font-display)",
          fontWeight: 700,
          fontSize: "0.7rem",
          letterSpacing: "0.05em",
          textTransform: "uppercase",
          color: "var(--text-primary)",
        }}>
          {current?.name ?? active}
        </span>

        {/* Symbol count */}
        <span style={{
          fontFamily: "var(--font-jetbrains)",
          fontSize: "0.6rem",
          color: "var(--text-muted)",
          borderLeft: "1px solid var(--border-bright)",
          paddingLeft: "7px",
        }}>
          {current?.symbols.length ?? 0}
        </span>

        <ChevronDown
          size={11}
          style={{
            color: "var(--text-muted)",
            transform: open ? "rotate(180deg)" : "rotate(0)",
            transition: "transform 0.15s",
            marginLeft: "-2px",
          }}
        />
      </button>

      {/* ── Popover ── */}
      {open && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 8px)",
            left: 0,
            minWidth: "260px",
            background: "#111827",
            border: "1px solid var(--border-default)",
            borderRadius: "12px",
            boxShadow: "0 20px 56px rgba(0,0,0,0.75), 0 0 0 1px rgba(255,255,255,0.06) inset",
            overflow: "hidden",
            zIndex: 200,
          }}
        >
          {/* Header */}
          <div style={{
            padding: "8px 12px 6px",
            borderBottom: "1px solid var(--border-subtle)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}>
            <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "0.55rem", letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--text-muted)" }}>
              Universe
            </span>
            <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "0.55rem", letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--text-muted)" }}>
              Sym
            </span>
          </div>

          {/* Profile rows */}
          {keys.map((key) => {
            const p = profiles[key];
            const isActive = key === active;
            return (
              <button
                key={key}
                onClick={() => { onChange(key); setOpen(false); }}
                style={{
                  display: "flex",
                  alignItems: "center",
                  width: "100%",
                  padding: "9px 12px",
                  background: isActive ? "rgba(78,214,200,0.05)" : "transparent",
                  borderLeft: `2px solid ${isActive ? "var(--accent-cyan)" : "transparent"}`,
                  cursor: "pointer",
                  textAlign: "left",
                  transition: "background 0.1s",
                  gap: "8px",
                }}
                onMouseEnter={(e) => { if (!isActive) (e.currentTarget as HTMLElement).style.background = "rgba(255,255,255,0.03)"; }}
                onMouseLeave={(e) => { if (!isActive) (e.currentTarget as HTMLElement).style.background = "transparent"; }}
              >
                {/* Left: name + description */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    fontFamily: "var(--font-display)",
                    fontWeight: 600,
                    fontSize: "0.72rem",
                    letterSpacing: "0.02em",
                    color: isActive ? "var(--accent-cyan)" : "var(--text-primary)",
                    lineHeight: 1.2,
                  }}>
                    {p.name}
                  </div>
                  <div style={{
                    fontSize: "0.58rem",
                    color: "var(--text-muted)",
                    marginTop: "2px",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}>
                    {p.description}
                  </div>
                </div>

                {/* Right: counts */}
                <div style={{ display: "flex", alignItems: "center", gap: "8px", flexShrink: 0 }}>
                  <span style={{ fontFamily: "var(--font-jetbrains)", fontSize: "0.6rem", color: "var(--text-muted)", minWidth: "20px", textAlign: "right" }}>
                    {p.symbols.length}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      )}
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
      <span className="hidden md:inline text-[0.6rem] font-medium text-[var(--text-muted)]">
        {label}
      </span>
    </div>
  );
}
