import { layers } from "@/lib/copy/landing";

export function TierShowcase() {
  return (
    <section
      className="px-6 py-8 border-b"
      style={{ borderColor: "var(--border-subtle)" }}
    >
      <div className="max-w-7xl mx-auto">
        <div className="flex items-baseline justify-between mb-6">
          <h2
            className="text-lg font-semibold"
            style={{ color: "var(--text-primary)", fontFamily: "var(--font-display)" }}
          >
            {layers.title}
          </h2>
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            {layers.note}
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-0 border rounded-xl overflow-hidden"
          style={{ borderColor: "var(--border-subtle)" }}
        >
          {layers.items.map((layer, i) => (
            <div
              key={layer.layer}
              className="relative flex flex-col gap-0 overflow-hidden"
              style={{
                background: layer.accent ? "rgba(78,214,200,0.03)" : "var(--surface-card)",
                borderRight: i < layers.items.length - 1 ? `1px solid var(--border-subtle)` : undefined,
              }}
            >
              {/* Accent top bar */}
              <div
                className="h-0.5 w-full"
                style={{
                  background: layer.accent
                    ? "linear-gradient(90deg, var(--accent-cyan), transparent)"
                    : "transparent",
                }}
              />

              <div className="p-5 flex flex-col gap-3 flex-1">
                {/* Ghost number - design element */}
                <div
                  className="absolute bottom-2 right-3 select-none pointer-events-none"
                  style={{
                    fontFamily: "var(--font-display)",
                    fontSize: "7rem",
                    fontWeight: 800,
                    lineHeight: 1,
                    color: layer.accent ? "var(--accent-cyan)" : "var(--text-primary)",
                    opacity: layer.accent ? 0.05 : 0.03,
                    letterSpacing: "-0.05em",
                  }}
                >
                  {layer.layer}
                </div>

                {/* Header */}
                <div>
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <p
                      className="text-xs font-semibold tracking-wide uppercase"
                      style={{
                        color: layer.accent ? "var(--accent-cyan)" : "var(--text-muted)",
                        fontFamily: "var(--font-display)",
                        letterSpacing: "0.08em",
                        fontSize: "0.6rem",
                      }}
                    >
                      Layer {layer.layer}
                    </p>
                    {/* Tier badges */}
                    {layer.badges.length > 0 && (
                      <div className="flex gap-1">
                        {layer.badges.map((tid) => (
                          <span
                            key={tid}
                            style={{
                              fontFamily: "var(--font-jetbrains)",
                              fontSize: "0.55rem",
                              fontWeight: 600,
                              letterSpacing: "0.05em",
                              padding: "1px 5px",
                              borderRadius: "3px",
                              background: layer.accent
                                ? "rgba(78,214,200,0.12)"
                                : "rgba(255,255,255,0.06)",
                              color: layer.accent ? "var(--accent-cyan)" : "var(--text-muted)",
                              border: `1px solid ${layer.accent ? "rgba(78,214,200,0.25)" : "rgba(255,255,255,0.1)"}`,
                            }}
                          >
                            {tid}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  <p
                    className="font-semibold leading-tight"
                    style={{
                      fontFamily: "var(--font-display)",
                      fontSize: "1rem",
                      color: "var(--text-primary)",
                    }}
                  >
                    {layer.name}
                  </p>
                  <p
                    className="text-[0.62rem] mt-0.5"
                    style={{ color: "var(--text-muted)" }}
                  >
                    {layer.subtitle}
                  </p>
                </div>

                {/* Item list */}
                <ul className="space-y-1.5 flex-1">
                  {layer.items.map((item) => (
                    <li
                      key={item}
                      className="flex items-start gap-2 text-[0.67rem] leading-snug"
                      style={{ color: "var(--text-secondary)" }}
                    >
                      <span
                        className="shrink-0 mt-[0.3rem]"
                        style={{
                          width: "3px",
                          height: "3px",
                          borderRadius: "50%",
                          background: layer.accent ? "var(--accent-cyan)" : "var(--text-muted)",
                          opacity: layer.accent ? 0.8 : 0.5,
                          display: "block",
                        }}
                      />
                      {item}
                    </li>
                  ))}
                </ul>

                {/* Example */}
                <div
                  className="mt-auto pt-3 border-t"
                  style={{ borderColor: layer.accent ? "rgba(78,214,200,0.12)" : "var(--border-subtle)" }}
                >
                  <p
                    className="text-[0.59rem] leading-relaxed"
                    style={{
                      fontFamily: "var(--font-jetbrains)",
                      color: layer.accent ? "rgba(78,214,200,0.7)" : "var(--text-muted)",
                      opacity: layer.accent ? 1 : 0.8,
                    }}
                  >
                    {layer.example}
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
