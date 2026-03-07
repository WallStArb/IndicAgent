"use client";

import Link from "next/link";
import { PipelineAnimation } from "./pipeline-animation";
import { ArrowRight } from "lucide-react";

interface HeroStatPillProps {
  label: string;
  live?: boolean;
}

function HeroStatPill({ label, live }: HeroStatPillProps) {
  return (
    <div
      className="flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium"
      style={{
        background: "rgba(78, 214, 200, 0.08)",
        border: "1px solid rgba(78, 214, 200, 0.2)",
        color: "var(--text-secondary)",
      }}
    >
      {live && (
        <span
          className="w-1.5 h-1.5 rounded-full animate-pulse"
          style={{ background: "var(--accent-cyan)" }}
        />
      )}
      {label}
    </div>
  );
}

interface HeroSectionProps {
  activeSignalCount: number;
}

export function HeroSection({ activeSignalCount }: HeroSectionProps) {
  return (
    <section
      className="relative flex flex-col items-center justify-center px-6 py-16 overflow-hidden"
      style={{
        minHeight: "50vh",
        background: "var(--landing-bg-gradient)",
      }}
    >
      {/* Animation — primary visual, higher opacity */}
      <div className="absolute inset-0" style={{ opacity: 0.65 }}>
        <PipelineAnimation />
      </div>

      {/* Content overlay */}
      <div className="relative z-10 max-w-3xl mx-auto text-center space-y-6">
        {/* Headline */}
        <div className="space-y-3">
          <h1
            className="text-5xl md:text-6xl font-bold leading-tight"
            style={{
              color: "var(--text-primary)",
              fontFamily: "var(--font-display)",
            }}
          >
            Real-Time Market Intelligence
          </h1>
          <p
            className="text-base md:text-lg"
            style={{ color: "var(--text-secondary)" }}
          >
            8-tier intelligence pipeline · 91 plugins · AI narratives · 24 instruments
          </p>
        </div>

        {/* Live stat pills */}
        <div className="flex flex-wrap items-center justify-center gap-2">
          <HeroStatPill label="24 Instruments" live />
          <HeroStatPill
            label={activeSignalCount > 0 ? `${activeSignalCount} Active Signals` : "Signals Live"}
            live
          />
          <HeroStatPill label="CIS Scoring" live />
          <HeroStatPill label="AI Narratives" live />
        </div>

        {/* Primary CTA */}
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
