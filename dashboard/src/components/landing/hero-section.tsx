"use client";

import { PipelineAnimation } from "./pipeline-animation";

interface HeroSectionProps {
  activeSignalCount: number;
}

const OUTCOME_STATS = [
  { value: "6-bucket", label: "Convergence gate" },
  { value: "4-agent", label: "AI interrogation" },
  { value: "8-class", label: "Outcome model" },
  { value: "Every bar", label: "Every instrument" },
];

export function HeroSection({ activeSignalCount }: HeroSectionProps) {
  return (
    <section
      className="relative"
      style={{ background: "#080b11" }}
    >
      {/* Background layers */}
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
        {/* Pipeline animation — right half, fades into content */}
        <div
          className="absolute inset-y-0 right-0 w-full lg:w-1/2"
          style={{ opacity: 0.18 }}
        >
          <PipelineAnimation />
        </div>
        {/* Fade left over animation */}
        <div
          className="absolute inset-y-0 left-0 w-3/4 lg:w-1/2"
          style={{
            background: "linear-gradient(to right, #080b11 60%, transparent)",
          }}
        />
        {/* Bottom fade */}
        <div
          className="absolute bottom-0 left-0 right-0 h-32"
          style={{ background: "linear-gradient(to bottom, transparent, #080b11)" }}
        />
      </div>

      <div className="relative z-10 max-w-7xl mx-auto px-4 sm:px-6 pt-8 sm:pt-10 pb-8 sm:pb-10">
        {/* Status bar */}
        <div className="flex items-center gap-2 sm:gap-3 mb-6 sm:mb-8">
          <span
            className="w-1.5 h-1.5 rounded-full animate-pulse shrink-0"
            style={{ background: "var(--accent-cyan)" }}
          />
          <span
            className="shrink-0"
            style={{
              fontFamily: "var(--font-jetbrains)",
              fontSize: "0.58rem",
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              color: "var(--accent-cyan)",
            }}
          >
            {activeSignalCount > 0 ? `${activeSignalCount} LIVE` : "LIVE"}
          </span>
          <div className="flex-1 h-px" style={{ background: "var(--border-subtle)" }} />
          <span
            className="hidden sm:inline"
            style={{
              fontFamily: "var(--font-jetbrains)",
              fontSize: "0.58rem",
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              color: "var(--text-muted)",
            }}
          >
            I1→I8 pipeline · 4-agent swarm · every bar
          </span>
        </div>

        {/* Tagline */}
        <div className="flex items-center gap-2 sm:gap-4 mb-6" style={{ maxWidth: "640px" }}>
          <div className="h-px w-4 sm:w-8 shrink-0" style={{ background: "var(--border-bright)" }} />
          <span
            style={{
              fontFamily: "var(--font-jetbrains)",
              fontSize: "clamp(0.5rem, 1.5vw, 0.62rem)",
              letterSpacing: "0.08em",
              color: "var(--accent-amber)",
              lineHeight: 1.4,
            }}
          >
            Every signal survives convergence and interrogation before you see it
          </span>
          <div className="h-px flex-1 shrink-0" style={{ background: "var(--border-bright)" }} />
        </div>

        {/* Headline — tighter max */}
        <h1
          style={{
            fontFamily: "var(--font-display)",
            fontSize: "clamp(2rem, 5vw, 3.75rem)",
            fontWeight: 800,
            lineHeight: 0.92,
            letterSpacing: "-0.03em",
            color: "var(--text-primary)",
            textTransform: "uppercase",
            maxWidth: "600px",
          }}
        >
          Agentic
          <br />
          <span style={{ color: "var(--accent-cyan)" }}>Market</span>
          <br />
          Intelligence
        </h1>

        {/* Body copy — outcome-first */}
        <p
          className="mt-6"
          style={{
            maxWidth: "480px",
            fontFamily: "var(--font-outfit)",
            fontSize: "clamp(0.875rem, 2vw, 1rem)",
            lineHeight: 1.7,
            color: "var(--text-secondary)",
          }}
        >
          Most signals get killed before you see them. A 6-bucket convergence gate requires independent agreement across trend, momentum, structure, pattern, institutional flow, and regime context. Survivors are interrogated by a 4-agent AI swarm. What comes out is a thesis — entry, target, stop, and the case behind it.
        </p>

        {/* Outcome stats */}
        <div className="flex flex-wrap gap-6 sm:gap-8 mt-6 sm:mt-8">
          {OUTCOME_STATS.map(({ value, label }) => (
            <div key={label} className="flex flex-col gap-0.5">
              <span
                style={{
                  fontFamily: "var(--font-jetbrains)",
                  fontSize: "clamp(1rem, 2.5vw, 1.4rem)",
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
                  fontSize: "0.55rem",
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  color: "var(--text-muted)",
                }}
              >
                {label}
              </span>
            </div>
          ))}
        </div>

      </div>
    </section>
  );
}
