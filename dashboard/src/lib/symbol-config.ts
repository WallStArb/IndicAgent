// Symbol configuration for dashboard
export interface SymbolInfo {
  symbol: string
  display_name: string
  contract?: string
  description: string
  sector: "equity_index" | "energy" | "metals" | "volatility" | "etf"
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

// Default configuration - will be loaded from API in production
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
        contract: "CLH6",
        description: "Crude Oil WTI Futures",
        sector: "energy",
      },
      {
        symbol: "NG",
        display_name: "Natural Gas",
        contract: "NGH6",
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
      ],
      description: "All 10 futures contracts",
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

  // In production, this would load from API
  async loadConfig(): Promise<void> {
    console.log(
      "Using default symbol configuration:",
      this.config.active_profile
    )
  }
}

export const symbolConfig = new SymbolConfigManager()
export default symbolConfig
