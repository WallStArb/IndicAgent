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
    detail: "Trend setups in ranging regimes and mean-reversion setups in strong trends are structurally misaligned. This agent validates HMM regime, session context, and volatility posture match the setup's required conditions.",
  },
  {
    id: "counterfactual",
    label: "Counterfactual",
    challenge: "What would have to be true for this to be wrong?",
    detail: "Constructs the conditions under which the signal fails — specific price levels, regime shifts, catalyst events — so you enter with a falsification condition, not just a target.",
  },
] as const;

const EAI_CONCEPTS = [
  {
    label: "Agent Genome",
    body: "Every agent carries a genome — a prompt and configuration parameter set that defines its behavior. The genome is what evolves. Agents aren't hand-tuned; they're bred.",
  },
  {
    label: "Breeding",
    body: "Three reproductive operators generate candidates: random mutation for exploration, recombination to combine fit parents, and LLM-directed mutation for targeted search. Each generation searches for alpha the current swarm doesn't see.",
  },
  {
    label: "Death & Failure Archive",
    body: "Agents that don't prove edge are demoted. Failures aren't discarded — they're frozen in a gene bank. Failed genomes encode what doesn't work, preventing the population from rediscovering dead ends.",
  },
  {
    label: "Promotion",
    body: "New agents start in shadow mode, invisible to production. Promotion requires statistical proof: n ≥ 100 signals, positive expected PnL at the lower confidence bound. The bar is high by design.",
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
      className="px-6 py-10 border-b"
      style={{ borderColor: "var(--border-subtle)" }}
    >
      <div className="max-w-7xl mx-auto">

        {/* ── Swarm ── */}
        <div className="flex items-end gap-6 mb-6">
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
              AI Swarm
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
              Adversarial Interrogation
            </h2>
          </div>
          <div className="flex-1 h-px mb-1" style={{ background: "var(--border-subtle)" }} />
        </div>

        <p
          className="mb-6 max-w-2xl text-sm leading-relaxed"
          style={{ color: "var(--text-secondary)" }}
        >
          Before a signal reaches you, four agents attack it. Each has a specific challenge. The goal isn&apos;t narrative generation — it&apos;s adversarial interrogation. Survivors carry a full case.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
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
                    background: "var(--accent-cyan)",
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
                  color: "var(--accent-cyan)",
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

        {/* Sample narrative */}
        <div
          className="p-5 border rounded-lg mb-12"
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

        {/* ── eAI ── */}
        <div className="flex items-end gap-6 mb-6">
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
              eAI · Evolutionary AI
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
              Agents That Evolve
            </h2>
          </div>
          <div className="flex-1 h-px mb-1" style={{ background: "var(--border-subtle)" }} />
        </div>

        <p
          className="mb-6 max-w-2xl text-sm leading-relaxed"
          style={{ color: "var(--text-secondary)" }}
        >
          The swarm isn&apos;t static. eAI breeds new agents through evolutionary operators — each generation searching for alpha the current swarm doesn&apos;t see. Agents that prove edge get promoted. Agents that don&apos;t get demoted. The population evolves.
        </p>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {EAI_CONCEPTS.map((concept) => (
            <div
              key={concept.label}
              className="p-5 border rounded-lg flex flex-col gap-2"
              style={{ borderColor: "rgba(212,168,75,0.2)", background: "rgba(212,168,75,0.03)" }}
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
                  {concept.label}
                </p>
              </div>
              <p
                className="text-[0.67rem] leading-relaxed"
                style={{ color: "var(--text-muted)" }}
              >
                {concept.body}
              </p>
            </div>
          ))}
        </div>

      </div>
    </section>
  );
}
