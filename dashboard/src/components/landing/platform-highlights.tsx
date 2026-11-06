const HIGHLIGHTS: { label: string; value: string; desc: string; accent: "cyan" | "amber" }[] = [
  {
    label: "Raw capture",
    value: "Nothing a vendor serves is dropped",
    desc:
      "Every vendor answer lands in one raw table, last-wins, with a revision log that records restatements. Restatements are detected, never blocked. Canonical bars are a selection from raw plus a source policy, and a gate proves the selection is a pure function of raw.",
    accent: "cyan",
  },
  {
    label: "Counted testing",
    value: "Every look is recorded",
    desc:
      "Every backtest goes through the research runner and is counted against its vintage. Iteration is uncapped; the count is what makes the final selection honest. The research ledger was reset on 2026-10-30, so the count starts at zero.",
    accent: "amber",
  },
  {
    label: "Selection",
    value: "Romano-Wolf StepM",
    desc:
      "A step-down multiple test runs over everything tried on the vintage at family-wise 0.05. Costs never enter a test statistic, but a book is promoted only when its net expectation is positive.",
    accent: "cyan",
  },
  {
    label: "Executable returns",
    value: "Market-on-open targets",
    desc:
      "Information coefficients use forward returns from open[T+1] to open[T+N+1], the entry and exit a trader can actually get. Close-to-close returns capture overnight gaps nobody can trade and overstate the signal.",
    accent: "amber",
  },
  {
    label: "Data integrity",
    value: "Quarantine, flag, never delete",
    desc:
      "Scrub rules flag suspect bars and a quarantine list hides them from research while keeping them stored. Nightly reconciliation writes integrity verdicts that rebuilds and promotion read. A coverage ledger records which requests ran, per timeframe and provider.",
    accent: "cyan",
  },
  {
    label: "Determinism",
    value: "Bit-exact from the recipe",
    desc:
      "A result is a function of the data snapshot hash, the code key, and the spec hash. Frozen verdicts are replayed after every change to the research or statistics code and must come back bit-identical.",
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
              Method
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
              What makes a result believable
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
