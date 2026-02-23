// dashboard/src/components/regime-ambiance.tsx
"use client";

import type { ContextData } from "@/lib/types";

interface RegimeAmbianceProps {
  context: ContextData | null;
  children: React.ReactNode;
}

const REGIME_GRADIENT: Record<string, string> = {
  low:     "radial-gradient(ellipse at top, rgba(76, 154, 255, 0.06) 0%, transparent 70%)",
  normal:  "none",
  high:    "radial-gradient(ellipse at top, rgba(255, 179, 71, 0.08) 0%, transparent 70%)",
  extreme: "radial-gradient(ellipse at top, rgba(255, 71, 87, 0.10) 0%, transparent 70%)",
};

export function RegimeAmbiance({ context, children }: RegimeAmbianceProps) {
  const regime = context?.volatility_regime ?? "normal";
  const gradient = REGIME_GRADIENT[regime] ?? "none";

  return (
    <div
      style={{
        background: gradient,
        transition: "background 1.5s ease",
      }}
    >
      {children}
    </div>
  );
}
