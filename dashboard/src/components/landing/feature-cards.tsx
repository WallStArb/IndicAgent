"use client";

import { useState } from "react";

interface FeatureCardProps {
  title: string;
  description: string;
  detail: string;
}

function FeatureCard({ title, description, detail }: FeatureCardProps) {
  const [isHovered, setIsHovered] = useState(false);
  const [isFocused, setIsFocused] = useState(false);
  const isExpanded = isHovered || isFocused;

  return (
    <div
      tabIndex={0}
      className="group relative p-6 rounded-lg border transition-all duration-300 hover:scale-[1.02] cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-cyan)]"
      style={{
        background: "var(--surface-card)",
        borderColor: "var(--border-subtle)",
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      onFocus={() => setIsFocused(true)}
      onBlur={() => setIsFocused(false)}
    >
      <div className="space-y-3">
        <h3
          className="text-lg font-semibold"
          style={{
            color: "var(--text-primary)",
            fontFamily: "var(--font-display)",
          }}
        >
          {title}
        </h3>
        <p
          className="text-sm"
          style={{ color: "var(--text-secondary)" }}
        >
          {description}
        </p>
        <div
          className={`overflow-hidden transition-all duration-300 ${
            isExpanded ? "max-h-20 opacity-100" : "max-h-0 opacity-0"
          }`}
        >
          <p className="text-xs pt-2" style={{ color: "var(--text-muted)" }}>
            {detail}
          </p>
        </div>
      </div>

      {/* Subtle accent border on hover/focus */}
      <div
        className={`absolute inset-0 rounded-lg pointer-events-none transition-all duration-300 ${
          isExpanded ? "opacity-100" : "opacity-0"
        }`}
        style={{
          border: "1px solid var(--accent-cyan-dim)",
          boxShadow: "0 0 12px rgba(78, 214, 200, 0.1)",
        }}
      />
    </div>
  );
}

export function FeatureCards() {
  const features = [
    {
      title: "Multi-Asset Coverage",
      description: "Futures, Forex, and Crypto markets in real-time",
      detail: "Covers equity indices (ES/NQ/RTY/YM), energy (CL), metals (GC/SI/HG/PL), rates (ZN/ZF/ZB/ZT/VX), FX pairs, and crypto assets.",
    },
    {
      title: "Tiered Intelligence",
      description: "8 intelligence layers from I1 indicators to I8 AI narratives",
      detail: "Real-time processing through mathematical, pattern, and smart money concepts layers with composite intelligence scoring.",
    },
    {
      title: "Event-Driven Architecture",
      description: "Canonical typed event stream with shared data bus",
      detail: "Typed IntelligenceEvent schema ensures consistent data flow across all services and UI components.",
    },
    {
      title: "Production Grade",
      description: "Sub-10ms processing latency with health monitoring",
      detail: "Built for institutional-grade reliability with graceful degradation and comprehensive metrics.",
    },
  ];

  return (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
      {features.map((feature) => (
        <FeatureCard
          key={feature.title}
          title={feature.title}
          description={feature.description}
          detail={feature.detail}
        />
      ))}
    </div>
  );
}
