"use client";

import Link from "next/link";
import { PipelineAnimation } from "./pipeline-animation";
import { ArrowRight } from "lucide-react";

interface HeroSectionProps {
  activeSignalCount: number;
}

export function HeroSection({ activeSignalCount }: HeroSectionProps) {
  return (
    <section
      className="relative flex flex-col items-center justify-center px-6 py-20 overflow-hidden"
      style={{
        minHeight: "55vh",
        background: "var(--landing-bg-gradient)",
      }}
    >
      {/* Pipeline animation — the architecture, visualized */}
      <div className="absolute inset-0" style={{ opacity: 0.6 }}>
        <PipelineAnimation />
      </div>

      {/* Content overlay */}
      <div className="relative z-10 max-w-3xl mx-auto text-center space-y-5">
        {/* Badge */}
        <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full text-xs font-medium"
          style={{
            background: "rgba(78, 214, 200, 0.08)",
            border: "1px solid rgba(78, 214, 200, 0.2)",
            color: "var(--accent-cyan)",
          }}
        >
          <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: "var(--accent-cyan)" }} />
          {activeSignalCount > 0 ? `${activeSignalCount} signals live` : "Pipeline live"}
        </div>

        {/* Headline */}
        <div className="space-y-4">
          <h1
            className="text-5xl md:text-6xl font-bold leading-tight"
            style={{
              color: "var(--text-primary)",
              fontFamily: "var(--font-display)",
            }}
          >
            Market Intelligence
            <br />
            <span style={{ color: "var(--accent-cyan)" }}>Built Like a Quant Fund</span>
          </h1>
          <p
            className="text-base md:text-lg leading-relaxed max-w-2xl mx-auto"
            style={{ color: "var(--text-secondary)" }}
          >
            Event-driven microservices. DAG-ordered 8-tier pipeline. 91 plugins from raw indicators
            to AI narrative. Regime-aware signal selection that improves from its own outcome data.
          </p>
        </div>

        {/* CTA */}
        <Link
          href="/dashboard"
          className="inline-flex items-center gap-2 px-8 py-3 rounded-lg font-semibold text-base transition-all duration-200 hover:scale-105"
          style={{
            background: "var(--accent-cyan)",
            color: "#0A0E14",
            boxShadow: "0 4px 20px rgba(78, 214, 200, 0.35)",
          }}
        >
          Open Dashboard
          <ArrowRight size={18} />
        </Link>
      </div>
    </section>
  );
}
