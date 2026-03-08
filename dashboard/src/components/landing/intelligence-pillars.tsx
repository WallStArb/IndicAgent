const pillars = [
  {
    num: "01",
    title: "Dependency-Ordered Execution",
    tag: "DAG · Topological sort · No polling",
    body: "Every plugin declares its inputs. The engine runs Kahn's topological sort at startup. Execution order is a mathematical property of the dependency graph, not a convention anyone maintains. Cycles hard-crash at startup. Silent corruption is impossible. Adding a plugin means declaring its dependencies; ordering is inferred.",
  },
  {
    num: "02",
    title: "Regimented Signal Validation",
    tag: "CIS · 6-bucket convergence gate · Evidence required",
    body: "When 5–8 setup plugins fire on the same bar, CIS decides what gets published and whether anything does. Six buckets (Trend, Momentum, Structure, Pattern, Institutional, Regime) must converge: score > ±0.35 AND 3 of 6 must agree on direction. One dominant bucket cannot override the rest. Discipline enforced by the architecture, not by policy.",
  },
  {
    num: "03",
    title: "Data as Ground Truth",
    tag: "Feature store · Outcome tracing · Self-improving",
    body: "Every signal is tagged with the weight version that produced it. Every outcome (stop hit, target reached, TTL expired) is written back to the feature store with the full signal vector. Nothing is dropped. When outcome data is sufficient, weights update from evidence. The pipeline captures what it produces and learns from what it captured.",
  },
  {
    num: "04",
    title: "Canonical Typed Vocabulary",
    tag: "IntelligenceEvent schema · Stream-native · API-first",
    body: "Every output at every tier is encoded into a versioned IntelligenceEvent schema and published to the stream bus. Producers publish. Consumers subscribe. No service calls another directly. A new consumer (alert engine, execution system, ML scorer) subscribes to the existing stream without changing the producers. The bus is the API. Extension is additive.",
  },
];

export function IntelligencePillars() {
  return (
    <section
      className="px-6 py-14 border-t"
      style={{ borderColor: "var(--border-subtle)" }}
    >
      <div className="max-w-7xl mx-auto">
        {/* Section header */}
        <div className="flex items-end gap-6 mb-12">
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
              Architecture
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
              Engineering Principles
            </h2>
          </div>
          <div className="flex-1 h-px mb-1" style={{ background: "var(--border-subtle)" }} />
        </div>

        {/* Principles — rule-separated list */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-16 gap-y-0">
          {pillars.map(({ num, title, tag, body }, i) => {
            const accentColor = i % 2 === 0 ? "var(--accent-cyan)" : "var(--accent-amber)";
            return (
            <div
              key={num}
              className="py-8 border-t flex flex-col gap-3"
              style={{ borderColor: "var(--border-subtle)" }}
            >
              <div className="flex items-start gap-5">
                {/* Large ghost number */}
                <span
                  className="shrink-0 select-none"
                  style={{
                    fontFamily: "var(--font-display)",
                    fontSize: "2.8rem",
                    fontWeight: 800,
                    lineHeight: 1,
                    letterSpacing: "-0.04em",
                    color: accentColor,
                    opacity: 0.18,
                  }}
                >
                  {num}
                </span>
                <div className="flex-1 min-w-0">
                  <h3
                    style={{
                      fontFamily: "var(--font-display)",
                      fontSize: "1rem",
                      fontWeight: 700,
                      letterSpacing: "-0.01em",
                      color: "var(--text-primary)",
                      lineHeight: 1.2,
                    }}
                  >
                    {title}
                  </h3>
                  <p
                    className="mt-1"
                    style={{
                      fontFamily: "var(--font-jetbrains)",
                      fontSize: "0.6rem",
                      letterSpacing: "0.08em",
                      textTransform: "uppercase",
                      color: accentColor,
                      opacity: 0.8,
                    }}
                  >
                    {tag}
                  </p>
                </div>
              </div>
              <p
                className="text-xs leading-relaxed"
                style={{ color: "var(--text-secondary)", paddingLeft: "4.5rem" }}
              >
                {body}
              </p>
            </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
