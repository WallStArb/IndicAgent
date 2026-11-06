const pillars = [
  {
    num: "01",
    title: "One-way DAG",
    tag: "Every node does one thing · No cycles",
    body: "Ingest feeds features, features feed measurement, measurement feeds research, research feeds frozen books. Each stage has one job and data moves in one direction. A silent wrong answer is worse than a loud crash.",
  },
  {
    num: "02",
    title: "Point-in-time reads",
    tag: "Temporal integrity · No fill",
    body: "A read for time t sees only facts knowable at t, by availability time. Universe, classification, tags, and parameters are as of t. Missing data is NaN, warmup is masked by declared memory, and no placeholder bar reaches compute.",
  },
  {
    num: "03",
    title: "Compute apart from persistence",
    tag: "Single writer · Pure compute",
    body: "Compute is pure functions over arrays with state at the edges. Each table has exactly one writer, and compute daemons never persist their own output. Transport is not state: Kafka is a sink, not a store.",
  },
  {
    num: "04",
    title: "Lineage on every output",
    tag: "Recipe · Run · Snapshot",
    body: "Every output traces to its recipe and the run that produced it. Derived data is a rebuildable cache, raw market data is permanent, and conclusions are records. Nothing that could contain signal is dropped.",
  },
  {
    num: "05",
    title: "Shadow mode first",
    tag: "Earn capital through proof",
    body: "A candidate is a screen, not proof. It spends one confirmation on the forward span after the vintage cutoff, on data nobody has searched, and runs in sealed shadow before it touches capital. Concept status only changes through the registry service; no model overrides it.",
  },
  {
    num: "06",
    title: "Asset class is data",
    tag: "Registries · Tunable parameters",
    body: "No code branches on asset class. Claims about what an instrument is live in a tag registry, valid codes in a controlled vocabulary, and every tunable number in a versioned parameter registry with a recorded history of changes.",
  },
];

export function IntelligencePillars() {
  return (
    <section
      className="px-6 py-10 border-t"
      style={{ borderColor: "var(--border-subtle)" }}
    >
      <div className="max-w-7xl mx-auto">
        {/* Section header */}
        <div className="flex items-end gap-6 mb-8">
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
              Engineering principles
            </h2>
          </div>
          <div className="flex-1 h-px mb-1" style={{ background: "var(--border-subtle)" }} />
        </div>

        {/* Principles - rule-separated list */}
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
