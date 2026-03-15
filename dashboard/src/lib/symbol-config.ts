// Symbol configuration for dashboard
export interface SymbolInfo {
  symbol: string
  display_name: string
  contract?: string
  description: string
  asset_class?: string
  sector: string // equity_index | energy | metals | volatility | interest_rates | agriculture | fx | crypto | broad_market | rates | credit | etc.
}

export interface SymbolProfile {
  name: string
  symbols: string[]
  description: string
}

export interface DashboardConfig {
  dashboard_symbols: {
    futures: SymbolInfo[]
  }
  active_profile: string
  profiles: Record<string, SymbolProfile>
}

// Default configuration — will be replaced by GET /api/instruments fetch in production
// These are fallback values only; contract codes are auto-generated from /api/instruments

// Contract month codes (CME/ICE standard)
const MONTH_CODES = ["F", "G", "H", "J", "K", "M", "N", "Q", "U", "V", "X", "Z"] // Jan-Dec

/**
 * Generate a futures contract code from base symbol and expiry month/year.
 * @param baseSymbol Base symbol (e.g., "ES", "NQ", "CL")
 * @param month Month code (F=Jan, G=Feb, ..., Z=Dec)
 * @param year Last digit of year (e.g., 6 for 2026)
 * @returns Contract code (e.g., "ESH6", "CLJ6")
 */
export function generateContractCode(baseSymbol: string, month: string, year: string): string {
  return `${baseSymbol}${month}${year}`
}

/**
 * Get current month code for front-month contract.
 * @returns Month code for the current or next expiry month
 */
function getCurrentMonthCode(): string {
  const now = new Date()
  const month = now.getMonth() // 0-11
  // Front-month is typically 1-2 months ahead
  const targetMonth = (month + 2) % 12
  return MONTH_CODES[targetMonth]
}

/**
 * Get current year digit for contract codes.
 * @returns Single digit year (e.g., 6 for 2026)
 */
function getCurrentYearDigit(): string {
  const now = new Date()
  return now.getFullYear().toString().slice(-1)
}

/**
 * Generate a front-month contract code dynamically.
 * @param baseSymbol Base symbol (e.g., "ES", "NQ", "CL")
 * @returns Contract code (e.g., "ESH6", "CLK6")
 */
export function generateFrontMonthContract(baseSymbol: string): string {
  const month = getCurrentMonthCode()
  const year = getCurrentYearDigit()
  return generateContractCode(baseSymbol, month, year)
}
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
        asset_class: "futures",
      },
      {
        symbol: "NQ",
        display_name: "Nasdaq 100",
        contract: "NQH6",
        description: "Nasdaq 100 E-mini Futures",
        sector: "equity_index",
        asset_class: "futures",
      },
      {
        symbol: "RTY",
        display_name: "Russell 2000",
        contract: "RTYH6",
        description: "Russell 2000 E-mini Futures",
        sector: "equity_index",
        asset_class: "futures",
      },
      // Energy
      {
        symbol: "CL",
        display_name: "Crude Oil",
        contract: "CLJ6",
        description: "Crude Oil WTI Futures",
        sector: "energy",
        asset_class: "futures",
      },
      {
        symbol: "NG",
        display_name: "Natural Gas",
        contract: "NGJ6",
        description: "Natural Gas Futures",
        sector: "energy",
        asset_class: "futures",
      },
      // Precious Metals
      {
        symbol: "GC",
        display_name: "Gold",
        contract: "GCJ6",
        description: "Gold Futures",
        sector: "metals",
        asset_class: "futures",
      },
      {
        symbol: "SI",
        display_name: "Silver",
        contract: "SIH6",
        description: "Silver Futures",
        sector: "metals",
        asset_class: "futures",
      },
      // Industrial Metals
      {
        symbol: "HG",
        display_name: "Copper",
        contract: "HGH6",
        description: "Copper Futures",
        sector: "metals",
        asset_class: "futures",
      },
      // Equity Index
      {
        symbol: "YM",
        display_name: "Dow Jones",
        contract: "YMH6",
        description: "E-mini Dow Futures",
        sector: "equity_index",
        asset_class: "futures",
      },
      // Volatility
      {
        symbol: "VX",
        display_name: "VIX Futures",
        contract: "VXJ6",
        description: "CBOE VIX Futures",
        sector: "volatility",
        asset_class: "futures",
      },
      // Interest Rate Futures
      {
        symbol: "ZN",
        display_name: "10-Year T-Note",
        contract: "ZNH6",
        description: "10-Year Treasury Note Futures",
        sector: "interest_rates",
        asset_class: "futures",
      },
      {
        symbol: "ZF",
        display_name: "5-Year T-Note",
        contract: "ZFH6",
        description: "5-Year Treasury Note Futures",
        sector: "interest_rates",
        asset_class: "futures",
      },
      {
        symbol: "ZB",
        display_name: "30-Year T-Bond",
        contract: "ZBH6",
        description: "30-Year Treasury Bond Futures",
        sector: "interest_rates",
        asset_class: "futures",
      },
      {
        symbol: "ZT",
        display_name: "2-Year T-Note",
        contract: "ZTH6",
        description: "2-Year Treasury Note Futures",
        sector: "interest_rates",
        asset_class: "futures",
      },
      // Agriculture
      {
        symbol: "ZS",
        display_name: "Soybeans",
        contract: "ZSH6",
        description: "Soybeans Futures",
        sector: "agriculture",
        asset_class: "futures",
      },
      {
        symbol: "ZC",
        display_name: "Corn",
        contract: "ZCH6",
        description: "Corn Futures",
        sector: "agriculture",
        asset_class: "futures",
      },
      {
        symbol: "ZW",
        display_name: "Wheat",
        contract: "ZWH6",
        description: "Wheat Futures",
        sector: "agriculture",
        asset_class: "futures",
      },
      // FX Futures
      // FX Spot
      {
        symbol: "EURUSD",
        display_name: "Euro/USD",
        contract: "EURUSD",
        description: "EUR/USD Spot FX",
        sector: "fx",
      },
      {
        symbol: "GBPUSD",
        display_name: "GBP/USD",
        contract: "GBPUSD",
        description: "GBP/USD Spot FX",
        sector: "fx",
      },
      {
        symbol: "USDJPY",
        display_name: "USD/JPY",
        contract: "USDJPY",
        description: "USD/JPY Spot FX",
        sector: "fx",
      },
      {
        symbol: "USDCHF",
        display_name: "USD/CHF",
        contract: "USDCHF",
        description: "USD/CHF Spot FX",
        sector: "fx",
      },
      // Crypto
      {
        symbol: "BTCUSD",
        display_name: "Bitcoin",
        contract: "BTCUSD",
        description: "Bitcoin/USD Spot",
        sector: "crypto",
      },
      {
        symbol: "ETHUSD",
        display_name: "Ethereum",
        contract: "ETHUSD",
        description: "Ether/USD Spot",
        sector: "crypto",
      },
      // ETFs — Broad Market
      { symbol: "SPY",  display_name: "S&P 500 ETF",    contract: "SPY",  description: "SPDR S&P 500 ETF",                    sector: "broad_market",          asset_class: "equity" },
      { symbol: "QQQ",  display_name: "Nasdaq 100 ETF", contract: "QQQ",  description: "Invesco QQQ Trust",                   sector: "broad_market",          asset_class: "equity" },
      { symbol: "IWM",  display_name: "Russell 2000 ETF",contract: "IWM", description: "iShares Russell 2000 ETF",            sector: "broad_market",          asset_class: "equity" },
      { symbol: "DIA",  display_name: "Dow Jones ETF",  contract: "DIA",  description: "SPDR Dow Jones ETF",                  sector: "broad_market",          asset_class: "equity" },
      // ETFs — Rates / Credit
      { symbol: "TLT",  display_name: "20yr Treasury",  contract: "TLT",  description: "iShares 20+ Year Treasury Bond ETF",  sector: "rates",                 asset_class: "equity" },
      { symbol: "IEF",  display_name: "7-10yr Treasury", contract: "IEF", description: "iShares 7-10 Year Treasury Bond ETF", sector: "rates",                 asset_class: "equity" },
      { symbol: "SHY",  display_name: "1-3yr Treasury", contract: "SHY",  description: "iShares 1-3 Year Treasury Bond ETF",  sector: "rates",                 asset_class: "equity" },
      { symbol: "HYG",  display_name: "High Yield Bonds",contract: "HYG", description: "iShares iBoxx High Yield ETF",        sector: "credit",                asset_class: "equity" },
      { symbol: "LQD",  display_name: "IG Corp Bonds",  contract: "LQD",  description: "iShares Investment Grade ETF",        sector: "credit",                asset_class: "equity" },
      // ETFs — Commodities
      { symbol: "GLD",  display_name: "Gold ETF",       contract: "GLD",  description: "SPDR Gold Shares",                    sector: "commodity",             asset_class: "equity" },
      { symbol: "SLV",  display_name: "Silver ETF",     contract: "SLV",  description: "iShares Silver Trust",                sector: "commodity",             asset_class: "equity" },
      { symbol: "USO",  display_name: "Oil ETF",        contract: "USO",  description: "United States Oil Fund",              sector: "energy",                asset_class: "equity" },
      { symbol: "GDX",  display_name: "Gold Miners",    contract: "GDX",  description: "VanEck Gold Miners ETF",              sector: "gold_miners",           asset_class: "equity" },
      { symbol: "GDXJ", display_name: "Jr Gold Miners", contract: "GDXJ", description: "VanEck Junior Gold Miners ETF",       sector: "gold_miners",           asset_class: "equity" },
      // ETFs — SPDR Sectors
      { symbol: "XLK",  display_name: "Technology",     contract: "XLK",  description: "Technology Select Sector SPDR",       sector: "technology",            asset_class: "equity" },
      { symbol: "XLF",  display_name: "Financials",     contract: "XLF",  description: "Financial Select Sector SPDR",        sector: "equity",                asset_class: "equity" },
      { symbol: "XLV",  display_name: "Health Care",    contract: "XLV",  description: "Health Care Select Sector SPDR",      sector: "healthcare",            asset_class: "equity" },
      { symbol: "XLE",  display_name: "Energy",         contract: "XLE",  description: "Energy Select Sector SPDR",           sector: "energy",                asset_class: "equity" },
      { symbol: "XLI",  display_name: "Industrials",    contract: "XLI",  description: "Industrial Select Sector SPDR",       sector: "industrials",           asset_class: "equity" },
      { symbol: "XLY",  display_name: "Cons. Discret.", contract: "XLY",  description: "Consumer Discretionary SPDR",         sector: "consumer_discretionary",asset_class: "equity" },
      { symbol: "XLP",  display_name: "Cons. Staples",  contract: "XLP",  description: "Consumer Staples SPDR",               sector: "consumer_staples",      asset_class: "equity" },
      { symbol: "XLB",  display_name: "Materials",      contract: "XLB",  description: "Materials Select Sector SPDR",        sector: "materials",             asset_class: "equity" },
      { symbol: "XLC",  display_name: "Comm. Services", contract: "XLC",  description: "Communication Services SPDR",         sector: "communications",        asset_class: "equity" },
      { symbol: "XLU",  display_name: "Utilities",      contract: "XLU",  description: "Utilities Select Sector SPDR",        sector: "utilities",             asset_class: "equity" },
      { symbol: "XLRE", display_name: "Real Estate",    contract: "XLRE", description: "Real Estate Select Sector SPDR",      sector: "real_estate",           asset_class: "equity" },
      { symbol: "XOP",  display_name: "Oil & Gas E&P",  contract: "XOP",  description: "SPDR Oil & Gas Exploration ETF",      sector: "energy",                asset_class: "equity" },
      // ETFs — Thematic / Factor
      { symbol: "SMH",  display_name: "Semiconductors", contract: "SMH",  description: "VanEck Semiconductor ETF",            sector: "technology",            asset_class: "equity" },
      { symbol: "IBB",  display_name: "Biotech",        contract: "IBB",  description: "iShares Biotechnology ETF",           sector: "biotech",               asset_class: "equity" },
      { symbol: "ITB",  display_name: "Homebuilders",   contract: "ITB",  description: "iShares U.S. Home Construction ETF",  sector: "homebuilders",          asset_class: "equity" },
      { symbol: "MTUM", display_name: "Momentum",       contract: "MTUM", description: "iShares MSCI USA Momentum ETF",       sector: "factor",                asset_class: "equity" },
      { symbol: "QUAL", display_name: "Quality",        contract: "QUAL", description: "iShares MSCI USA Quality ETF",        sector: "factor",                asset_class: "equity" },
      { symbol: "VLUE", display_name: "Value",          contract: "VLUE", description: "iShares MSCI USA Value ETF",          sector: "factor",                asset_class: "equity" },
      { symbol: "USMV", display_name: "Min Volatility", contract: "USMV", description: "iShares MSCI USA Min Vol ETF",        sector: "factor",                asset_class: "equity" },
      // ETFs — International / EM
      { symbol: "EEM",  display_name: "Emerging Mkts",  contract: "EEM",  description: "iShares MSCI Emerging Markets ETF",   sector: "emerging_markets",      asset_class: "equity" },
      { symbol: "EFA",  display_name: "Intl Dev Mkts",  contract: "EFA",  description: "iShares MSCI EAFE ETF",               sector: "international",         asset_class: "equity" },
      { symbol: "FXI",  display_name: "China",          contract: "FXI",  description: "iShares China Large-Cap ETF",         sector: "emerging_markets",      asset_class: "equity" },
      { symbol: "EWZ",  display_name: "Brazil",         contract: "EWZ",  description: "iShares MSCI Brazil ETF",             sector: "emerging_markets",      asset_class: "equity" },
      { symbol: "EMB",  display_name: "EM Bonds",       contract: "EMB",  description: "iShares EM Bond ETF",                 sector: "emerging_markets",      asset_class: "equity" },
    ],
  },
  active_profile: "all_futures",
  profiles: {
    all_futures: {
      name: "Futures",
      symbols: [
        "ES", "NQ", "RTY", "YM",
        "CL", "NG",
        "GC", "SI", "HG",
        "VX",
        "ZN", "ZF", "ZB", "ZT",
        "ZS", "ZC", "ZW",
      ],
      description: "All active futures contracts",
    },
    equity_index: {
      name: "Indices",
      symbols: ["ES", "NQ", "RTY", "YM", "VX"],
      description: "E-mini equity index + VIX futures",
    },
    etf_broad: {
      name: "ETFs Core",
      symbols: ["SPY", "QQQ", "IWM", "DIA", "TLT", "IEF", "SHY", "HYG", "LQD", "GLD", "SLV", "USO", "GDX", "GDXJ"],
      description: "Broad market, rates, credit, and commodity ETFs",
    },
    etf_sectors: {
      name: "Sectors",
      symbols: ["XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLB", "XLC", "XLU", "XLRE", "XOP", "SMH", "IBB"],
      description: "SPDR sector ETFs + thematic",
    },
    etf_factor: {
      name: "Factor/Intl",
      symbols: ["MTUM", "QUAL", "VLUE", "USMV", "EEM", "EFA", "FXI", "EWZ", "EMB", "ITB"],
      description: "Factor ETFs and international/EM",
    },
    fx_crypto: {
      name: "FX + Crypto",
      symbols: ["EURUSD", "GBPUSD", "USDCHF", "BTCUSD", "ETHUSD"],
      description: "Spot FX and crypto",
    },
    commodities: {
      name: "Commodities",
      symbols: ["CL", "NG", "GC", "SI", "HG", "ZS", "ZC", "ZW"],
      description: "Energy, metals, and agriculture futures",
    },
    interest_rates: {
      name: "Rates",
      symbols: ["ZN", "ZF", "ZB", "ZT", "TLT", "IEF", "SHY"],
      description: "Treasury futures + rate ETFs",
    },
  },
}

class SymbolConfigManager {
  private config: DashboardConfig = defaultConfig
  private symbolInfoMap: Map<string, SymbolInfo> = new Map(
    defaultConfig.dashboard_symbols.futures.map((s) => [s.symbol, s])
  )

  getActiveSymbols(): string[] {
    const activeProfile = this.config.active_profile
    const profile = this.config.profiles[activeProfile]
    return profile ? profile.symbols : ["ES", "NQ", "RTY"]
  }

  getSymbolInfo(symbol: string): SymbolInfo | null {
    return this.symbolInfoMap.get(symbol) ?? null
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
    const info = this.symbolInfoMap.get(symbol)
    return info?.asset_class === "futures"
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
        .filter((i) => i.is_active)
        .map((i) => {
          const isFutures = i.asset_class === "futures"
          const baseSymbol = isFutures ? this.contractToBase(i.symbol) : i.symbol
          return {
            symbol: baseSymbol,
            display_name: i.name,
            contract: i.symbol,
            description: i.name,
            asset_class: i.asset_class,
            sector: i.sector ?? "",
          }
        })

      this.config = { ...this.config, dashboard_symbols: { ...this.config.dashboard_symbols, futures } }
      this.symbolInfoMap = new Map(futures.map((s) => [s.symbol, s]))
    } catch {
      // Keep static fallback on error
    }
  }
}

export const symbolConfig = new SymbolConfigManager()
export default symbolConfig
