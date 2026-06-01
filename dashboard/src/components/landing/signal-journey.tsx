const STEPS = [
  {
    num: "01",
    label: "Raw Data",
    summary: "Every bar. Every instrument.",
    detail: "Institutional tick + bar ingestion across 24 instruments and 6 timeframes. Provider-agnostic bus. Nothing is sampled.",
    accent: false,
  },
  {
    num: "02",
    label: "Synthesis",
    summary: "Every layer. Every bar.",
    detail: "Indicators, composite events, structure, regime context — computed in dependency order, in a single in-process pass. No polling, no shortcuts.",
    accent: false,
  },
  {
    num: "03",
    label: "Convergence Gate",
    summary: "Most signals die here.",
    detail: "Six independent evidence buckets — Trend, Momentum, Structure, Pattern, Institutional, Regime — must converge. 3 of 6 required. Score threshold enforced. One strong bucket can't override the rest.",
    accent: true,
  },
  {
    num: "04",
    label: "AI Interrogation",
    summary: "Survivors get challenged.",
    detail: "Four agents attack each signal before it's published: Skeptic, Correlation, Regime Coherence, Counterfactual. The goal is to find reasons it's wrong.",
    accent: false,
  },
  {
    num: "05",
    label: "Actionable Signal",
    summary: "Entry. Thesis. Evidence.",
    detail: "Entry, target, stop, regime context, narrative rationale, confidence score. You know why the signal exists and what would have to change for it to fail.",
    accent: false,
  },
] as const;

export function SignalJourney() {
  return (
    <section
      className="px-6 py-10 border-b"
      style={{ borderColor: "var(--border-subtle)", background: "var(--surface-base)" }}
    >
      <div className="max-w-7xl mx-auto">
        <div className="flex items-end gap-6 mb-10">
          <div>
            <p
              className="mb-1"
              style={{
                fontFamily: "var(--font-jetbrains)",
                fontSize: "0.6rem",
                letterSpacing: "0.18em",
                textTransform: "uppercase",
                color: "var(--accent-cyan)",
              }}
            >
              How It Works
            </p>
            <h2
              style={{
                fontFamily: "var(--font-display)",
                fontSize: "clamp(1.5rem, 3vw, 2rem)",
                fontWeight: 800,
                letterSpacing: "-0.03em",
                textTransform: "uppercase",
                color: "var(--text-primary)",
                lineHeight: 1,
              }}
            >
              From Price to Signal
            </h2>
          </div>
          <div className="flex-1 h-px mb-1" style={{ background: "var(--border-subtle)" }} />
        </div>

        {/* Step flow — horizontal on desktop, vertical on mobile */}
        <div className="flex flex-col lg:flex-row gap-0">
          {STEPS.map((step, i) => (
            <div key={step.num} className="flex lg:flex-col flex-1 min-w-0">
              {/* Connector arrow between steps */}
              <div className="flex lg:flex-col items-stretch flex-1 min-w-0">
                {/* Step card */}
                <div
                  className="flex-1 relative p-5 border"
                  style={{
                    borderColor: step.accent ? "rgba(78,214,200,0.3)" : "var(--border-subtle)",
                    background: step.accent ? "rgba(78,214,200,0.04)" : "var(--surface-card)",
                    borderRadius: i === 0 ? "8px 0 0 8px" : i === STEPS.length - 1 ? "0 8px 8px 0" : "0",
                    borderLeftWidth: i > 0 ? 0 : undefined,
                  }}
                >
                  {/* Accent top bar */}
                  {step.accent && (
                    <div
                      className="absolute top-0 left-0 right-0 h-0.5"
                      style={{ background: "linear-gradient(90deg, var(--accent-cyan), transparent)" }}
                    />
                  )}

                  {/* Step number */}
                  <p
                    className="mb-2"
                    style={{
                      fontFamily: "var(--font-jetbrains)",
                      fontSize: "0.58rem",
                      letterSpacing: "0.12em",
                      color: step.accent ? "var(--accent-cyan)" : "var(--text-muted)",
                    }}
                  >
                    {step.num}
                  </p>

                  {/* Label */}
                  <p
                    className="mb-1 font-semibold"
                    style={{
                      fontFamily: "var(--font-display)",
                      fontSize: "0.9rem",
                      letterSpacing: "-0.01em",
                      color: step.accent ? "var(--accent-cyan)" : "var(--text-primary)",
                      lineHeight: 1.2,
                    }}
                  >
                    {step.label}
                  </p>

                  {/* Summary */}
                  <p
                    className="mb-3 text-[0.62rem] font-medium"
                    style={{
                      fontFamily: "var(--font-jetbrains)",
                      color: step.accent ? "rgba(78,214,200,0.75)" : "var(--text-secondary)",
                      letterSpacing: "0.02em",
                    }}
                  >
                    {step.summary}
                  </p>

                  {/* Detail */}
                  <p
                    className="text-[0.67rem] leading-relaxed"
                    style={{ color: "var(--text-muted)" }}
                  >
                    {step.detail}
                  </p>
                </div>
              </div>

              {/* Arrow connector (between cards) */}
              {i < STEPS.length - 1 && (
                <div
                  className="hidden lg:flex items-center justify-center shrink-0"
                  style={{
                    width: "1px",
                    background: "var(--border-subtle)",
                    position: "relative",
                    zIndex: 1,
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
