const LAYERS = [
  {
    layer: "01",
    name: "Data foundation",
    subtitle: "Ingest · raw capture · canonical bars",
    accent: false,
    tierBadges: ["ingest"] as string[],
    items: [
      "IBKR and Alpaca bars, 5m to 1d, for 1,529 US equities and ETFs",
      "Every vendor answer is stored raw, last-wins, with a revision log",
      "Canonical bars are a rebuildable selection from raw plus a source policy",
      "Bad prints are flagged and quarantined, never deleted",
    ],
    example: "ohlcv_raw -> market_data_ohlcv -> market_data_ohlcv_tradeable",
  },
  {
    layer: "02",
    name: "Features and measurement",
    subtitle: "Feature store · regimes · information coefficient",
    accent: false,
    tierBadges: ["feature", "measure"],
    items: [
      "Feature vectors per bar, written once by a single writer",
      "Market regimes labeled with walk-forward fitting",
      "Information coefficient term structure per feature and horizon",
      "Targets are executable: market-on-open entry and exit",
    ],
    example: "feature_vectors · market_regimes · ic_measure",
  },
  {
    layer: "03",
    name: "Research machine",
    subtitle: "Panel · families · guards · combiner · book test",
    accent: true,
    tierBadges: ["research"],
    items: [
      "A point-in-time panel feeds family tests, guards, a combiner, and a construction rule",
      "Every look at a vintage is recorded in the research ledger",
      "Selection uses Romano-Wolf StepM over everything tried on the vintage",
      "Results are bit-exact reproducible from snapshot, code, and spec hash",
    ],
    example: "panel -> target -> families -> guards -> combiner -> book test",
  },
  {
    layer: "04",
    name: "Frozen books",
    subtitle: "Promotion · sealed forward shadow",
    accent: false,
    tierBadges: ["book"],
    items: [
      "Promotion requires positive net expectation after costs",
      "A frozen book is confirmed once on its own unsearched forward span",
      "The forward runner records shadow positions; nothing trades yet",
      "Capital follows proof, never the other way round",
    ],
    example: "frozen book -> forward runner -> sealed shadow -> capital",
  },
] as const;

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
            Four layers
          </h2>
          <span className="text-xs" style={{ color: "var(--text-muted)" }}>
            data flows one way, each layer reads only the one below
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-0 border rounded-xl overflow-hidden"
          style={{ borderColor: "var(--border-subtle)" }}
        >
          {LAYERS.map((layer, i) => (
            <div
              key={layer.layer}
              className="relative flex flex-col gap-0 overflow-hidden"
              style={{
                background: layer.accent ? "rgba(78,214,200,0.03)" : "var(--surface-card)",
                borderRight: i < LAYERS.length - 1 ? `1px solid var(--border-subtle)` : undefined,
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
                    {layer.tierBadges.length > 0 && (
                      <div className="flex gap-1">
                        {layer.tierBadges.map((tid) => (
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
