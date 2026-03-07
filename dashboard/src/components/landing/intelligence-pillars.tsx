import { GitBranch, BarChart3, RefreshCcw, Layers } from "lucide-react";

const pillars = [
  {
    Icon: Layers,
    title: "DAG-Ordered Pipeline",
    subtitle: "91 plugins · I1→I8 · No polling",
    body: "Every plugin declares its inputs. The engine runs topological sort at startup — execution order is a property of the dependency graph, not a convention. Raw OHLCV feeds I1 indicators, which feed I3 structure and I4 regime models (GARCH, Kalman, HMM), which feed I5 patterns and I6 Smart Money Concepts, which converge in I7 setup generation and I8 AI narrative. Each tier builds on the tier below. Cycles hard-crash at startup — silent corruption is impossible.",
  },
  {
    Icon: BarChart3,
    title: "Composite Intelligence Score",
    subtitle: "6-bucket gate · Cross-tier confirmation required",
    body: "When 5–8 setup plugins fire simultaneously on the same bar, CIS decides which signal to publish — and whether to publish at all. Six evidence buckets (Trend, Momentum, Structure, Pattern, Institutional, Regime) must converge: score must exceed ±0.35 AND at least 3 of 6 buckets must agree on direction. One strong bucket cannot override the rest. The result: high-noise bars produce no signal rather than a wrong one.",
  },
  {
    Icon: RefreshCcw,
    title: "Self-Improving Feedback Loop",
    subtitle: "Outcome-traced weights · No manual retuning",
    body: "Every signal is tagged with the CIS weight version that produced it. Every outcome — stop hit, target reached, TTL expired — is written to the feature store alongside that version tag. When outcome data is sufficient, weights update and CIS improves without code changes. The system learns which market conditions precede profitable setups. Bootstrap weights run the system on day one; labeled outcome data trains the next version.",
  },
  {
    Icon: GitBranch,
    title: "Microservices Over Streams",
    subtitle: "No service calls another · The bus is the contract",
    body: "Each pipeline stage is a separate process that reads from and writes to Redis streams. No direct service-to-service HTTP calls exist in the pipeline. Restarting the analysis service to deploy a new plugin has zero effect on the signal lifecycle service tracking open trades. A new consumer — a Slack alert, an execution system, an ML scorer — subscribes to the existing intelligence stream without any change to the producers. Extension is additive.",
  },
];

export function IntelligencePillars() {
  return (
    <section className="px-6 py-12">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-8">
          <h2
            className="text-2xl font-semibold mb-2"
            style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}
          >
            What Makes This Different
          </h2>
          <p className="text-sm max-w-xl mx-auto" style={{ color: "var(--text-secondary)" }}>
            Most market intelligence systems are monolithic pipelines. IndicAgent is built around three architectural principles that solve the hard problems directly.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {pillars.map(({ Icon, title, subtitle, body }) => (
            <div
              key={title}
              className="p-5 rounded-lg border flex flex-col gap-3"
              style={{
                background: "var(--surface-card)",
                borderColor: "var(--border-subtle)",
              }}
            >
              <div className="flex items-start gap-3">
                <div
                  className="p-2 rounded-md shrink-0 mt-0.5"
                  style={{ background: "rgba(78, 214, 200, 0.1)" }}
                >
                  <Icon size={16} style={{ color: "var(--accent-cyan)" }} />
                </div>
                <div>
                  <h3
                    className="text-sm font-semibold leading-snug"
                    style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}
                  >
                    {title}
                  </h3>
                  <p className="text-xs mt-0.5" style={{ color: "var(--accent-cyan)", opacity: 0.75 }}>
                    {subtitle}
                  </p>
                </div>
              </div>
              <p className="text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                {body}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
