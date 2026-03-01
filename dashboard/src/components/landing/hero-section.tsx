"use client";

import { PipelineAnimation } from "./pipeline-animation";
import { FeatureCards } from "./feature-cards";

export function HeroSection() {
  return (
    <section
      className="relative min-h-[60vh] flex flex-col items-center justify-center px-6 py-12 overflow-hidden"
      style={{
        background: "var(--landing-bg-gradient)",
      }}
    >
      {/* Animated background */}
      <div className="absolute inset-0 opacity-40">
        <PipelineAnimation />
      </div>

      {/* Content overlay */}
      <div className="relative z-10 max-w-5xl mx-auto space-y-10">
        {/* Tagline */}
        <div className="text-center space-y-4">
          <h1
            className="text-5xl md:text-6xl font-bold leading-tight"
            style={{
              color: "var(--text-primary)",
              fontFamily: "var(--font-display)",
            }}
          >
            Real-time Trading Intelligence Platform
          </h1>
          <p
            className="text-lg md:text-xl"
            style={{ color: "var(--text-secondary)" }}
          >
            Futures · Forex · Crypto · Tiered analysis pipeline · Event-driven architecture
          </p>
        </div>

        {/* Feature cards */}
        <FeatureCards />
      </div>
    </section>
  );
}
