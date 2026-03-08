"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";

interface HeroSectionProps {
  activeSignalCount: number;
}

const STATS = [
  { value: "91", label: "Plugins" },
  { value: "I1→I8", label: "Intelligence Tiers" },
  { value: "24", label: "Instruments" },
  { value: "6", label: "Timeframes" },
  { value: "<10ms", label: "Latency" },
];

export function HeroSection({ activeSignalCount }: HeroSectionProps) {
  return (
    <section
      className="relative"
      style={{ minHeight: "68vh", background: "#080b11" }}
    >
      {/* Background layers — clipped independently so text can overflow freely */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        {/* Dot-grid texture */}
        <div
          className="absolute inset-0"
          style={{
            backgroundImage: "radial-gradient(circle, rgba(78,214,200,0.07) 1px, transparent 1px)",
            backgroundSize: "28px 28px",
          }}
        />
        {/* Gradient mesh */}
        <div
          className="absolute inset-0"
          style={{
            background:
              "radial-gradient(ellipse 55% 45% at 5% 15%, rgba(78,214,200,0.09) 0%, transparent 65%), " +
              "radial-gradient(ellipse 45% 50% at 95% 85%, rgba(212,168,75,0.07) 0%, transparent 60%)",
          }}
        />
        {/* Bottom fade */}
        <div
          className="absolute bottom-0 left-0 right-0 h-32"
          style={{ background: "linear-gradient(to bottom, transparent, #080b11)" }}
        />
      </div>

      <div className="relative z-10 max-w-7xl mx-auto px-6 pt-16 pb-20">
        {/* Status bar */}
        <div className="flex items-center gap-3 mb-14">
          <span
            className="w-1.5 h-1.5 rounded-full animate-pulse shrink-0"
            style={{ background: "var(--accent-cyan)" }}
          />
          <span
            style={{
              fontFamily: "var(--font-jetbrains)",
              fontSize: "0.62rem",
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--accent-cyan)",
            }}
          >
            {activeSignalCount > 0 ? `${activeSignalCount} signals live` : "pipeline live"}
          </span>
          <div className="flex-1 h-px" style={{ background: "var(--border-subtle)" }} />
          <span
            style={{
              fontFamily: "var(--font-jetbrains)",
              fontSize: "0.62rem",
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              color: "var(--text-muted)",
            }}
          >
            I1 → I8 · 91 PLUGINS · 24 INSTRUMENTS
          </span>
        </div>

        {/* Tagline — above headline so it's the first thing read */}
        <div className="flex items-center gap-4 mb-6" style={{ maxWidth: "640px" }}>
          <div className="h-px w-8" style={{ background: "var(--border-bright)" }} />
          <span
            style={{
              fontFamily: "var(--font-jetbrains)",
              fontSize: "0.62rem",
              letterSpacing: "0.12em",
              color: "var(--accent-amber)",
              whiteSpace: "nowrap",
            }}
          >
            ticks → indicators → structure → signals → AI narrative
          </span>
          <div className="h-px flex-1" style={{ background: "var(--border-bright)" }} />
        </div>

        {/* Headline */}
        <h1
          style={{
            fontFamily: "var(--font-display)",
            fontSize: "clamp(3rem, 6.5vw, 6.5rem)",
            fontWeight: 800,
            lineHeight: 0.92,
            letterSpacing: "-0.035em",
            color: "var(--text-primary)",
            textTransform: "uppercase",
          }}
        >
          Agentic
          <br />
          <span style={{ color: "var(--accent-cyan)" }}>Market</span>
          <br />
          Intelligence
        </h1>

        {/* Body copy */}
        <p
          style={{
            maxWidth: "520px",
            fontFamily: "var(--font-outfit)",
            fontSize: "1rem",
            lineHeight: 1.75,
            color: "var(--text-secondary)",
          }}
        >
          Raw market data flows in across 24 instruments. 91 intelligence plugins transform it —
          tier by tier — into regime-aware signals, CIS-validated setups, and AI-enriched narrative.
          Every output measured. Every outcome recorded. The system learns from both.
        </p>

        {/* Stats */}
        <div className="flex flex-wrap gap-8 mt-10 mb-10">
          {STATS.map(({ value, label }) => (
            <div key={label} className="flex flex-col gap-1">
              <span
                style={{
                  fontFamily: "var(--font-jetbrains)",
                  fontSize: "1.75rem",
                  fontWeight: 600,
                  color: "var(--text-primary)",
                  letterSpacing: "-0.04em",
                  lineHeight: 1,
                }}
              >
                {value}
              </span>
              <span
                style={{
                  fontFamily: "var(--font-outfit)",
                  fontSize: "0.6rem",
                  letterSpacing: "0.1em",
                  textTransform: "uppercase",
                  color: "var(--text-muted)",
                }}
              >
                {label}
              </span>
            </div>
          ))}
        </div>

        {/* CTA */}
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-3 group"
          style={{
            fontFamily: "var(--font-display)",
            fontSize: "0.85rem",
            fontWeight: 700,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: "var(--accent-cyan)",
            transition: "opacity 0.2s",
          }}
        >
          Open Dashboard
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              justifyContent: "center",
              width: "2.2rem",
              height: "2.2rem",
              borderRadius: "50%",
              border: "1.5px solid var(--accent-cyan)",
              flexShrink: 0,
            }}
          >
            <ArrowRight size={14} />
          </span>
        </Link>
      </div>
    </section>
  );
}
