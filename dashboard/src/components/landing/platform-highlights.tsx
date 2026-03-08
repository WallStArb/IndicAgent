const HIGHLIGHTS: { label: string; value: string; desc: string; accent: "cyan" | "amber" }[] = [
  {
    label: "The Bus is the Contract",
    value: "IntelligenceEvent",
    desc:
      "Every tick, every signal, every AI narrative flows through one shared, durable, replayable event bus. No service calls another directly. Producers publish. Consumers subscribe. A new downstream system (execution engine, ML scorer, alert bot) subscribes to the existing stream with zero changes to the producers.",
    accent: "cyan",
  },
  {
    label: "Signal Lifecycle Tracking",
    value: "8-class outcome",
    desc:
      "Every signal is tracked from fire to resolution: activation at entry zone, MAE/MFE per bar, 8-class outcome (stopped at entry, stopped in trade, T1/T2/full target, TTL expired). Shadow signals under regime suppression are tracked identically, building a labeled dataset for every market condition the system sees.",
    accent: "amber",
  },
  {
    label: "Regime-Aware Intelligence",
    value: "HMM · GARCH · Kalman",
    desc:
      "I4 classifies the current market regime using GARCH volatility modelling, a Kalman trend filter, HMM hidden state detection, and BOCPD changepoint detection. I7 setup plugins declare a regime_type (trend / mean-reversion / any) and are gated by the slow-clock regime of the next higher timeframe. Suppressed signals become regime_suppressed shadow signals, not dropped data.",
    accent: "cyan",
  },
  {
    label: "Self-Improving Feedback Loop",
    value: "Outcome → Weights → CIS",
    desc:
      "Every signal carries the CIS weight version that produced it. Every outcome is written back to the feature store alongside the full I1–I8 signal vector that triggered it. When 30+ samples accumulate per setup type, setup_performance rolls up win rate, avg pnl_r, and Sharpe, feeding back into CIS perf_multiplier weights without code changes.",
    accent: "amber",
  },
  {
    label: "AI Narrative Synthesis",
    value: "3-tier LLM chain",
    desc:
      "I8 runs a 3-tier LLM chain: ZAI GLM-5 (primary, <70ms), OpenRouter with 100+ model fallback, and Ollama local for offline operation. Every signal with confidence > 0.70 gets a per-signal narrative. Every 60s, a 6-group cross-asset synthesis narrative is generated from the full active signal set. All LLM calls, including failures, are logged with outcome back-fill.",
    accent: "cyan",
  },
  {
    label: "Feature Store as Training Set",
    value: "TimescaleDB · Forever",
    desc:
      "The intelligence_features hypertable is the ground truth training dataset. Every bar across every instrument and timeframe writes the full I1–I8 feature vector including JSONB tiers. Signal outcomes JOIN back via (symbol, feature_ts, feature_tf). Nothing is discarded. Storage is cheap. Every output is a labeled training sample.",
    accent: "amber",
  },
];

export function PlatformHighlights() {
  return (
    <section
      className="px-6 py-14 border-t"
      style={{ borderColor: "var(--border-subtle)", background: "rgba(0,0,0,0.2)" }}
    >
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex items-end gap-6 mb-12">
          <div>
            <p
              style={{
                fontFamily: "var(--font-jetbrains)",
                fontSize: "0.6rem",
                letterSpacing: "0.18em",
                textTransform: "uppercase",
                color: "var(--accent-cyan)",
                marginBottom: "4px",
              }}
            >
              Platform
            </p>
            <h2
              style={{
                fontFamily: "var(--font-display)",
                fontSize: "clamp(1.6rem, 3vw, 2.2rem)",
                fontWeight: 800,
                letterSpacing: "-0.03em",
                textTransform: "uppercase",
                color: "var(--text-primary)",
                lineHeight: 1,
              }}
            >
              How It Works
            </h2>
          </div>
          <div className="flex-1 h-px mb-1" style={{ background: "var(--border-subtle)" }} />
        </div>

        {/* 3-column grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-px"
          style={{ background: "var(--border-subtle)" }}
        >
          {HIGHLIGHTS.map(({ label, value, desc, accent }) => (
            <div
              key={label}
              className="flex flex-col gap-3 p-6"
              style={{ background: "#080b11" }}
            >
              <div>
                <p
                  style={{
                    fontFamily: "var(--font-jetbrains)",
                    fontSize: "0.58rem",
                    letterSpacing: "0.14em",
                    textTransform: "uppercase",
                    color: "var(--text-muted)",
                    marginBottom: "4px",
                  }}
                >
                  {label}
                </p>
                <p
                  style={{
                    fontFamily: "var(--font-display)",
                    fontSize: "1rem",
                    fontWeight: 700,
                    letterSpacing: "-0.01em",
                    color: accent === "cyan" ? "var(--accent-cyan)" : "var(--accent-amber)",
                    lineHeight: 1.2,
                  }}
                >
                  {value}
                </p>
              </div>
              <p
                className="text-xs leading-relaxed"
                style={{ color: "var(--text-secondary)" }}
              >
                {desc}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
