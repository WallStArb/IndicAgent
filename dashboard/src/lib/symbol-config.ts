// Symbol configuration for dashboard
export interface SymbolInfo {
  symbol: string
  display_name: string
  contract?: string
  description: string
  sector: "equity_index" | "energy" | "metals" | "volatility" | "interest_rates" | "agriculture" | "fx" | "crypto" | "etf"
}

export interface SymbolProfile {
  name: string
  symbols: string[]
  description: string
}

export interface DashboardConfig {
  dashboard_symbols: {
    futures: SymbolInfo[]
    etfs: SymbolInfo[]
  }
  active_profile: string
  profiles: Record<string, SymbolProfile>
}

// Default configuration — will be replaced by GET /api/instruments fetch in future
const defaultConfig: DashboardConfig = {
  dashboard_symbols: {
    futures: [
      // Equity Index Futures
      {
        symbol: "ES",
        display_name: "S&P 500",
        contract: "ESH6",
        description: "S&P 500 E-mini Futures",
        sector: "equity_index",
      },
      {
        symbol: "NQ",
        display_name: "Nasdaq 100",
        contract: "NQH6",
        description: "Nasdaq 100 E-mini Futures",
        sector: "equity_index",
      },
      {
        symbol: "RTY",
        display_name: "Russell 2000",
        contract: "RTYH6",
        description: "Russell 2000 E-mini Futures",
        sector: "equity_index",
      },
      // Energy
      {
        symbol: "CL",
        display_name: "Crude Oil",
        contract: "CLJ6",
        description: "Crude Oil WTI Futures",
        sector: "energy",
      },
      {
        symbol: "NG",
        display_name: "Natural Gas",
        contract: "NGJ6",
        description: "Natural Gas Futures",
        sector: "energy",
      },
      // Precious Metals
      {
        symbol: "GC",
        display_name: "Gold",
        contract: "GCJ6",
        description: "Gold Futures",
        sector: "metals",
      },
      {
        symbol: "SI",
        display_name: "Silver",
        contract: "SIH6",
        description: "Silver Futures",
        sector: "metals",
      },
      // Industrial Metals
      {
        symbol: "HG",
        display_name: "Copper",
        contract: "HGH6",
        description: "Copper Futures",
        sector: "metals",
      },
      {
        symbol: "PL",
        display_name: "Platinum",
        contract: "PLJ6",
        description: "Platinum Futures",
        sector: "metals",
      },
      // Volatility
      {
        symbol: "VX",
        display_name: "VIX Futures",
        contract: "VXH6",
        description: "CBOE VIX Futures",
        sector: "volatility",
      },
      // Interest Rate Futures
      {
        symbol: "ZN",
        display_name: "10-Year T-Note",
        contract: "ZNH6",
        description: "10-Year Treasury Note Futures",
        sector: "interest_rates",
      },
      {
        symbol: "ZF",
        display_name: "5-Year T-Note",
        contract: "ZFH6",
        description: "5-Year Treasury Note Futures",
        sector: "interest_rates",
      },
      {
        symbol: "ZB",
        display_name: "30-Year T-Bond",
        contract: "ZBH6",
        description: "30-Year Treasury Bond Futures",
        sector: "interest_rates",
      },
      {
        symbol: "ZT",
        display_name: "2-Year T-Note",
        contract: "ZTH6",
        description: "2-Year Treasury Note Futures",
        sector: "interest_rates",
      },
    ],
    etfs: [
      {
        symbol: "SPY",
        display_name: "SPDR S&P 500",
        description: "S&P 500 ETF",
        sector: "etf",
      },
      {
        symbol: "QQQ",
        display_name: "Invesco QQQ",
        description: "Nasdaq 100 ETF",
        sector: "etf",
      },
      {
        symbol: "IWM",
        display_name: "iShares Russell 2000",
        description: "Russell 2000 ETF",
        sector: "etf",
      },
    ],
  },
  active_profile: "all_futures",
  profiles: {
    all_futures: {
      name: "All Futures",
      symbols: [
        "ES", "NQ", "RTY",
        "CL", "NG",
        "GC", "SI", "HG", "PL",
        "VX",
        "ZN", "ZF", "ZB", "ZT",
      ],
      description: "All 14 futures contracts",
    },
    equity_index: {
      name: "Equity Indices",
      symbols: ["ES", "NQ", "RTY"],
      description: "E-mini equity index futures",
    },
    commodities: {
      name: "Commodities",
      symbols: ["CL", "NG", "GC", "SI", "HG", "PL"],
      description: "Energy and metals futures",
    },
    interest_rates: {
      name: "Interest Rates",
      symbols: ["ZN", "ZF", "ZB", "ZT"],
      description: "Treasury futures",
    },
    etfs: {
      name: "ETF Trading",
      symbols: ["SPY", "QQQ", "IWM"],
      description: "Exchange Traded Funds",
    },
  },
}

class SymbolConfigManager {
  private config: DashboardConfig = defaultConfig

  getActiveSymbols(): string[] {
    const activeProfile = this.config.active_profile
    const profile = this.config.profiles[activeProfile]
    return profile ? profile.symbols : ["ES", "NQ", "RTY"]
  }

  getSymbolInfo(symbol: string): SymbolInfo | null {
    for (const future of this.config.dashboard_symbols.futures) {
      if (future.symbol === symbol) {
        return future
      }
    }
    for (const etf of this.config.dashboard_symbols.etfs) {
      if (etf.symbol === symbol) {
        return etf
      }
    }
    return null
  }

  getDisplayName(symbol: string): string {
    const info = this.getSymbolInfo(symbol)
    return info?.display_name || symbol
  }

  getContract(symbol: string): string {
    const info = this.getSymbolInfo(symbol)
    return info?.contract || symbol
  }

  isFuturesSymbol(symbol: string): boolean {
    return this.config.dashboard_symbols.futures.some(
      (f) => f.symbol === symbol
    )
  }

  getAllProfiles(): Record<string, SymbolProfile> {
    return this.config.profiles
  }

  getActiveProfile(): string {
    return this.config.active_profile
  }

  setActiveProfile(profile: string): void {
    if (this.config.profiles[profile]) {
      this.config.active_profile = profile
    }
  }

  /** Strip expiry suffix from a contract code to get the dashboard base symbol.
   *  "NGJ6" → "NG", "VXH6" → "VX", "6EH6" → "6E", "ESH6" → "ES"
   */
  private contractToBase(contract: string): string {
    const m = contract.match(/^([A-Z0-9]{1,4}?)[A-Z]\d+$/)
    return m ? m[1] : contract
  }

  async loadConfig(): Promise<void> {
    try {
      const base = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"
      const res = await fetch(`${base}/api/instruments`)
      if (!res.ok) return
      const instruments: Array<{
        symbol: string  // full contract code, e.g. "NGJ6"
        name: string
        sector: string
        is_active: boolean
        asset_class: string
      }> = await res.json()

      const futures: SymbolInfo[] = instruments
        .filter((i) => i.is_active && i.asset_class === "futures")
        .map((i) => ({
          symbol: this.contractToBase(i.symbol),
          display_name: i.name,
          contract: i.symbol,
          description: `${i.name} Futures`,
          sector: i.sector as SymbolInfo["sector"],
        }))

      this.config = { ...this.config, dashboard_symbols: { ...this.config.dashboard_symbols, futures } }
    } catch {
      // Keep static fallback on error
    }
  }
}

export const symbolConfig = new SymbolConfigManager()
export default symbolConfig
