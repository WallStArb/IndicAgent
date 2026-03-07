const TIERS = [
  {
    id: "I1",
    name: "Technical Indicators",
    count: "23 plugins",
    accent: false,
    caps: ["RSI · MACD · ATR", "VWAP · OBV · MFI", "Supertrend · Stochastic", "Bollinger Bands"],
  },
  {
    id: "I2",
    name: "Composite Events",
    count: "8 plugins",
    accent: false,
    caps: ["MACD crossovers", "RSI threshold events", "2nd-derivative momentum", "ADX trend strength"],
  },
  {
    id: "I3",
    name: "Market Structure",
    count: "7 plugins",
    accent: false,
    caps: ["Swing H/L detection", "Support & resistance", "Anchored VWAP", "Fibonacci zones"],
  },
  {
    id: "I4",
    name: "Regime Classification",
    count: "7 plugins",
    accent: true,
    caps: ["GARCH volatility model", "Kalman trend filter", "Session & killzone context", "Multi-TF vol regime"],
  },
  {
    id: "I5",
    name: "Pattern Recognition",
    count: "14 plugins",
    accent: false,
    caps: ["RSI divergence", "Bollinger squeeze", "Chart pattern completion", "Volume profile & divergence"],
  },
  {
    id: "I6",
    name: "Smart Money Concepts",
    count: "14 plugins",
    accent: true,
    caps: ["HMM hidden regime detection", "BOS/CHoCH · FVG · Order blocks", "ICT killzones · AMD cycles", "Cross-timeframe confluence"],
  },
  {
    id: "I7",
    name: "Signal Generation",
    count: "17 setup plugins",
    accent: true,
    caps: ["CIS 6-bucket gate", "Trend, mean-rev, SMC setups", "Regime eligibility filter", "R/R gate · zone validation"],
  },
  {
    id: "I8",
    name: "AI Narrative",
    count: "3-tier LLM chain",
    accent: false,
    caps: ["Per-signal GLM-5 synthesis", "6-group cross-asset narrative", "Regime-aware model routing", "Ollama local fallback"],
  },
] as const;

export function TierShowcase() {
  return (
    <section
      className="px-6 py-10 border-b"
      style={{ borderColor: "var(--border-subtle)" }}
    >
      <div className="max-w-7xl mx-auto">
        <div className="flex items-baseline justify-between mb-6">
          <h2
            className="text-lg font-semibold"
            style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}
          >
            8 Tiers of Intelligence
          </h2>
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            I1 → I8 · each tier builds on the tier below
          </span>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {TIERS.map((tier) => (
            <div
              key={tier.id}
              className="relative p-4 rounded-lg border flex flex-col gap-2.5 overflow-hidden"
              style={{
                background: tier.accent
                  ? "rgba(78, 214, 200, 0.04)"
                  : "var(--surface-card)",
                borderColor: tier.accent
                  ? "rgba(78, 214, 200, 0.25)"
                  : "var(--border-subtle)",
              }}
            >
              {/* Tier label — top right */}
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p
                    className="text-xs font-semibold leading-snug"
                    style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}
                  >
                    {tier.name}
                  </p>
                  <p
                    className="text-[0.65rem] mt-0.5"
                    style={{ color: "var(--text-muted)" }}
                  >
                    {tier.count}
                  </p>
                </div>
                <span
                  className="text-sm font-bold font-mono shrink-0 tabular-nums"
                  style={{
                    color: tier.accent ? "var(--accent-cyan)" : "var(--text-muted)",
                    opacity: tier.accent ? 1 : 0.5,
                    letterSpacing: "-0.02em",
                  }}
                >
                  {tier.id}
                </span>
              </div>

              {/* Capability list */}
              <ul className="space-y-1">
                {tier.caps.map((cap) => (
                  <li
                    key={cap}
                    className="text-[0.67rem] leading-snug"
                    style={{ color: "var(--text-secondary)" }}
                  >
                    {cap}
                  </li>
                ))}
              </ul>

              {/* Accent glow for highlighted tiers */}
              {tier.accent && (
                <div
                  className="absolute top-0 right-0 w-16 h-16 pointer-events-none"
                  style={{
                    background: "radial-gradient(circle at top right, rgba(78, 214, 200, 0.08), transparent 70%)",
                  }}
                />
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
