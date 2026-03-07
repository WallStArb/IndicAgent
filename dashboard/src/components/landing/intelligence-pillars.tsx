export function IntelligencePillars() {
  const pillars = [
    {
      icon: "🧠",
      title: "Tiered Intelligence",
      body: "I1→I8 pipeline. 91 plugins: technical indicators, volatility models, Smart Money Concepts, pattern detection, signal generation, and AI narrative. Regime-aware gating at every layer.",
    },
    {
      icon: "📊",
      title: "CIS + Adaptive Scoring",
      body: "Composite Intelligence Score with regime-aware gating. Shadow signals feed adaptive weight learning — every suppressed signal trains the model. Confidence-gated signal selection.",
    },
    {
      icon: "🤖",
      title: "AI Narratives",
      body: "Per-signal LLM analysis. Group synthesis across 6 asset classes. Confidence-gated (>0.7) and staleness-aware. Falls back to local Ollama when needed.",
    },
  ];

  return (
    <section className="px-6 py-10">
      <div className="max-w-5xl mx-auto grid grid-cols-1 md:grid-cols-3 gap-4">
        {pillars.map((p) => (
          <div
            key={p.title}
            className="p-5 rounded-lg border"
            style={{
              background: "var(--surface-card)",
              borderColor: "var(--border-subtle)",
            }}
          >
            <div className="text-2xl mb-3">{p.icon}</div>
            <h3
              className="text-sm font-semibold mb-2"
              style={{
                color: "var(--text-primary)",
                fontFamily: "var(--font-display)",
              }}
            >
              {p.title}
            </h3>
            <p className="text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
              {p.body}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
