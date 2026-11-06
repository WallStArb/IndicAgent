import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { cta } from "@/lib/copy/landing";
import { LandingNav } from "@/components/landing/landing-nav";
import { HeroSection } from "@/components/landing/hero-section";
import { TriangleFunnel } from "@/components/landing/triangle-funnel";
import { IdeasSection } from "@/components/landing/ideas-section";
import { EdgeSteps } from "@/components/landing/edge-steps";
import { FamiliesSection } from "@/components/landing/families-section";
import { TierShowcase } from "@/components/landing/tier-showcase";
import { PlatformHighlights } from "@/components/landing/platform-highlights";

export default function LandingPage() {
  return (
    <div className="min-h-screen">
      <LandingNav />
      <HeroSection />
      <TriangleFunnel />
      <IdeasSection />
      <EdgeSteps />
      <FamiliesSection />
      <TierShowcase />
      <PlatformHighlights />

      <section className="px-6 py-12 border-t" style={{ borderColor: "var(--border-subtle)" }}>
        <div className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-4">
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            {cta.text}
          </p>
          <Link
            href="/pipeline"
            className="text-sm font-medium flex items-center gap-1 hover:opacity-80 transition-opacity"
            style={{ color: "var(--accent-cyan)" }}
          >
            {cta.link} <ArrowRight size={14} />
          </Link>
        </div>
      </section>
    </div>
  );
}
