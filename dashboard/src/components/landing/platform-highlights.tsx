import { guarantees } from "@/lib/copy/landing";

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
              {guarantees.eyebrow}
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
              {guarantees.title}
            </h2>
          </div>
          <div className="flex-1 h-px mb-1" style={{ background: "var(--border-subtle)" }} />
        </div>

        {/* 3-column grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-px"
          style={{ background: "var(--border-subtle)" }}
        >
          {guarantees.items.map(({ label, value, desc, accent }) => (
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
