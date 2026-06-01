const HIGHLIGHTS: { label: string; value: string; desc: string; accent: "cyan" | "amber" }[] = [
  {
    label: "Event-Native Architecture",
    value: "Decoupled by Design",
    desc:
      "Every stage publishes to a durable stream and consumes from it. Producers and consumers never call each other directly. A new subscriber — alert engine, execution system, ML scorer — connects to existing streams without touching the producers. Extension is additive.",
    accent: "cyan",
  },
  {
    label: "Signal Lifecycle Tracking",
    value: "8-Class Outcome Model",
    desc:
      "Every signal is a hypothesis. The system tracks it from emission through activation and exit, recording MAE, MFE, bars-in-trade, and outcome class. Eight outcome labels — from never_activated to target_full — create a labeled training set from every market move.",
    accent: "amber",
  },
  {
    label: "Regime Context",
    value: "Multi-Model Consensus",
    desc:
      "HMM state detection, GARCH volatility modeling, Kalman trend filtering, and VIX regime classification run on every bar. Setup plugins declare a regime type; the aggregator suppresses misaligned setups before anything reaches the convergence gate.",
    accent: "cyan",
  },
  {
    label: "Self-Optimizing Feedback Loop",
    value: "Evidence-Gated Weights",
    desc:
      "Outcome data writes back. Setup performance multipliers update from verified PnL and Sharpe roll-ups once 30+ samples are available. The pipeline improves from its own track record — no manual tuning required.",
    accent: "amber",
  },
  {
    label: "Full Audit Trail",
    value: "Nothing Is a Black Box",
    desc:
      "Every LLM call, every signal emission, every outcome is logged with full context — agent ID, prompt version, parse rate, token burn, latency. Adaptive routing promotes models that demonstrate statistical edge. The system is inspectable at every layer.",
    accent: "cyan",
  },
  {
    label: "Feature Store",
    value: "Ground-Truth Persistence",
    desc:
      "Every bar’s full feature vector is written to a TimescaleDB hypertable — all 132 plugin outputs, tagged with the weight version that produced them. Signal outcomes JOIN back to their originating feature vector. The history is queryable and replayable.",
    accent: "amber",
  },
];

export function PlatformHighlights() {
  return (
    <section
      className="px-6 py-10 border-t"
      style={{ borderColor: "var(--border-subtle)", background: "rgba(0,0,0,0.2)" }}
    >
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex items-end gap-6 mb-8">
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
              Design
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
              Platform Design
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
