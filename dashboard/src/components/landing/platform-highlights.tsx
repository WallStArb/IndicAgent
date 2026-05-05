const HIGHLIGHTS: { label: string; value: string; desc: string; accent: "cyan" | "amber" }[] = [
  {
    label: "Agentic Swarm Architecture",
    value: "Asynchronous Intelligence",
    desc:
      "Our swarm of agents functions as a unified, high-performance intelligence engine. By decoupling every component through a durable, replayable event bus, the system scales effortlessly, allowing our intelligence capabilities to evolve in lockstep with the market’s complexity.",
    accent: "cyan",
  },
  {
    label: "Validated Alpha Lifecycle",
    value: "8-Class Hypothesis Tracking",
    desc:
      "Every signal is treated as a data-proven hypothesis. We track performance from the moment of activation through to final resolution, recording granular MAE/MFE metrics against an 8-class outcome model to turn every market move into a labeled training sample.",
    accent: "amber",
  },
  {
    label: "Regime-Aware Predictive Modeling",
    value: "Multi-Model Consensus",
    desc:
      "Our system dynamically adapts to the current market environment by synthesizing GARCH volatility modeling, Kalman filters, HMM state detection, and BOCPD changepoint identification. This provides a multi-dimensional view of market regime, ensuring our intelligence is always contextually relevant.",
    accent: "cyan",
  },
  {
    label: "Self-Optimizing Alpha Loop",
    value: "Evidence-Gated Feedback",
    desc:
      "The loop from outcome to optimization is closed. System performance multipliers are automatically adjusted based on verified PnL and Sharpe ratio roll-ups, allowing our agentic intelligence to self-sharpen its edge without requiring manual code changes.",
    accent: "amber",
  },
  {
    label: "Predictive AI Narrative",
    value: "3-Tier Chain Synthesis",
    desc:
      "Beyond technical triggers, our I8 intelligence layer synthesizes complex market conditions into actionable AI narratives. By chaining specialized LLMs, we generate per-signal context and cross-asset reports that bridge the gap between algorithmic execution and human intuition.",
    accent: "cyan",
  },
  {
    label: "Ground-Truth Feature Store",
    value: "Universal Intelligence Vector",
    desc:
      "Our feature store is the backbone of our Alpha generation. It maintains a persistent record of every instrument's state across every timeframe and tier, creating a labeled, high-resolution dataset that ensures every output acts as a training sample for the next iteration.",
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
