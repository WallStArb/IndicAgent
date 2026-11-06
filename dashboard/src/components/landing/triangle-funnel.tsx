"use client";

import { motion, useReducedMotion, useScroll, useTransform } from "motion/react";
import { useRef } from "react";
import { triangle } from "@/lib/copy/landing";
import { SectionHeading, pad2 } from "./section-heading";

export function TriangleFunnel() {
  const ref = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  // The fill follows the scroll position, base to apex; reduced motion shows it finished.
  const { scrollYProgress } = useScroll({ target: ref, offset: ["start 80%", "end 40%"] });
  const grown = useTransform(scrollYProgress, [0, 1], [0.04, 1]);
  const fill = reduce ? 1 : grown;

  return (
    <section className="px-6 py-12 border-t" style={{ borderColor: "var(--border-subtle)" }}>
      <div className="max-w-7xl mx-auto">
        <SectionHeading eyebrow={triangle.eyebrow} title={triangle.title} intro={triangle.intro} />
        <div ref={ref} className="grid items-center gap-10 md:grid-cols-[minmax(0,26rem)_1fr] md:gap-16">
          <svg viewBox="0 0 480 420" role="img" aria-label={triangle.figureLabel} className="h-auto w-full max-w-[26rem]">
            <defs>
              <clipPath id="landing-triangle">
                <polygon points="240,24 456,396 24,396" />
              </clipPath>
              <linearGradient id="landing-triangle-fill" x1="0" y1="1" x2="0" y2="0">
                <stop offset="0" stopColor="#4ED6C8" stopOpacity="0.12" />
                <stop offset="1" stopColor="#4ED6C8" stopOpacity="0.7" />
              </linearGradient>
            </defs>
            <g clipPath="url(#landing-triangle)">
              <motion.rect
                width="480"
                height="420"
                fill="url(#landing-triangle-fill)"
                style={{ scaleY: fill, transformOrigin: "50% 100%", transformBox: "fill-box" }}
              />
            </g>
            <polygon points="240,24 456,396 24,396" fill="none" stroke="#4ED6C8" strokeWidth="2" />
            <line x1="95" y1="290" x2="385" y2="290" stroke="#D4A84B" strokeWidth="1.5" strokeDasharray="4 6" />
            <line x1="160" y1="175" x2="320" y2="175" stroke="#D4A84B" strokeWidth="1.5" strokeDasharray="4 6" />
          </svg>
          <ol className="grid gap-8">
            {triangle.stages.map((stage, index) => (
              <li key={stage.label} className="border-t pt-4" style={{ borderColor: "var(--accent-cyan)" }}>
                <p style={{ fontFamily: "var(--font-jetbrains)", fontSize: "0.6rem", letterSpacing: "0.18em", color: "var(--accent-cyan)" }}>
                  {pad2(index + 1)}
                </p>
                <p className="mt-2 text-xl font-semibold leading-tight" style={{ fontFamily: "var(--font-display)", color: "var(--text-primary)" }}>
                  {stage.label}
                </p>
                <p className="mt-2 text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>
                  {stage.note}
                </p>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
