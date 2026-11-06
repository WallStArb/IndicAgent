import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { LandingNav } from "@/components/landing/landing-nav";
import { HeroSection } from "@/components/landing/hero-section";
import { TierShowcase } from "@/components/landing/tier-showcase";
import { PlatformHighlights } from "@/components/landing/platform-highlights";
import { IntelligencePillars } from "@/components/landing/intelligence-pillars";

export default function LandingPage() {
  return (
    <div className="min-h-screen">
      <LandingNav />
      <HeroSection />
      <TierShowcase />
      <PlatformHighlights />
      <IntelligencePillars />

      <section className="px-6 py-12 border-t" style={{ borderColor: "var(--border-subtle)" }}>
        <div className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-4">
          <p className="text-sm" style={{ color: "var(--text-secondary)" }}>
            The cockpit is read-only: what each stage holds, how fresh it is, and what the ledger has counted.
          </p>
          <Link
            href="/pipeline"
            className="text-sm font-medium flex items-center gap-1 hover:opacity-80 transition-opacity"
            style={{ color: "var(--accent-cyan)" }}
          >
            Open the pipeline <ArrowRight size={14} />
          </Link>
        </div>
      </section>
    </div>
  );
}
