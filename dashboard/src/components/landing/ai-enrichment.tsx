const AGENTS = [
  {
    id: "skeptic",
    label: "Skeptic",
    challenge: "Finds the strongest case for why this setup fails.",
    detail: "Attacks the entry thesis directly — checks for overextension, adverse regime conditions, recent failure modes for this setup type, and evidence the move is already over.",
  },
  {
    id: "correlation",
    label: "Correlation",
    challenge: "Checks whether macro context supports the thesis.",
    detail: "Cross-asset consistency check — does DXY direction, yield curve posture, VIX regime, and correlated instrument behavior align with the directional call? Contradictions are flagged.",
  },
  {
    id: "regime_coherence",
    label: "Regime Coherence",
    challenge: "Asks if the market regime is right for this setup type.",
    detail: "Trend setups in ranging regimes and mean-reversion setups in strong trends are structurally misaligned. This agent validates that the HMM regime, session context, and volatility posture match the setup's required conditions.",
  },
  {
    id: "counterfactual",
    label: "Counterfactual",
    challenge: "What would have to be true for this to be wrong?",
    detail: "Constructs the conditions under which the signal fails — specific price levels, regime shifts, catalyst events — so you enter with a falsification condition, not just a target.",
  },
] as const;

const SAMPLE_NARRATIVE = `Bullish 5m ES setup: trend-regime aligned, SMC confluence confirmed.
FVG entry zone 5236–5238, target 5258 (R2.3), stop 5229.
Skeptic: no structural concern. Correlation: DXY soft, supportive.
Regime coherence: HMM trend-mode, session in NY overlap — valid.
Counterfactual: invalidated below 5229 or on VIX spike > 18.`;

export function AiEnrichment() {
  return (
    <section
      className="px-6 py-14 border-b"
      style={{ borderColor: "var(--border-subtle)" }}
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
                color: "var(--accent-amber)",
              }}
            >
              AI Layer
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
              Adversarial Enrichment
            </h2>
          </div>
          <div className="flex-1 h-px mb-1" style={{ background: "var(--border-subtle)" }} />
        </div>

        <p
          className="mb-10 max-w-2xl text-sm leading-relaxed"
          style={{ color: "var(--text-secondary)" }}
        >
          Before a signal reaches you, four agents attack it. The goal isn&apos;t narrative generation — it&apos;s adversarial interrogation. Each agent has a specific challenge. Survivors carry a full case.
        </p>

        {/* Agent grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-10">
          {AGENTS.map((agent) => (
            <div
              key={agent.id}
              className="p-5 border rounded-lg flex flex-col gap-2"
              style={{ borderColor: "var(--border-subtle)", background: "var(--surface-card)" }}
            >
              <div className="flex items-center gap-2">
                <span
                  style={{
                    display: "inline-block",
                    width: "5px",
                    height: "5px",
                    borderRadius: "50%",
                    background: "var(--accent-amber)",
                    flexShrink: 0,
                  }}
                />
                <p
                  style={{
                    fontFamily: "var(--font-display)",
                    fontSize: "0.85rem",
                    fontWeight: 700,
                    letterSpacing: "-0.01em",
                    color: "var(--text-primary)",
                  }}
                >
                  {agent.label}
                </p>
              </div>
              <p
                className="text-[0.67rem] font-medium"
                style={{
                  fontFamily: "var(--font-jetbrains)",
                  color: "var(--accent-amber)",
                  opacity: 0.85,
                  letterSpacing: "0.02em",
                }}
              >
                {agent.challenge}
              </p>
              <p
                className="text-[0.67rem] leading-relaxed"
                style={{ color: "var(--text-muted)" }}
              >
                {agent.detail}
              </p>
            </div>
          ))}
        </div>

        {/* Sample narrative output */}
        <div
          className="p-5 border rounded-lg"
          style={{
            borderColor: "rgba(78,214,200,0.2)",
            background: "rgba(78,214,200,0.03)",
          }}
        >
          <p
            className="mb-2"
            style={{
              fontFamily: "var(--font-jetbrains)",
              fontSize: "0.58rem",
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              color: "var(--accent-cyan)",
              opacity: 0.7,
            }}
          >
            Sample output
          </p>
          <pre
            className="text-[0.67rem] leading-relaxed whitespace-pre-wrap"
            style={{
              fontFamily: "var(--font-jetbrains)",
              color: "rgba(78,214,200,0.75)",
            }}
          >
            {SAMPLE_NARRATIVE}
          </pre>
        </div>
      </div>
    </section>
  );
}
