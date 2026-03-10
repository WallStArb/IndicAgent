// dashboard/src/components/tooltip.tsx
"use client";

import type { ReactNode } from "react";

export interface TooltipContent {
  /** One-line description of what this indicator measures. */
  description: string;
  /** Value-contextual interpretation, e.g. "Overbought — momentum may be fading." Null = omit. */
  context: string | null;
}

interface TooltipProps {
  children: ReactNode;
  tooltip: TooltipContent;
}

/**
 * CSS-only hover tooltip. Wraps children in a relative container and shows
 * a styled tooltip above on hover using Tailwind group/group-hover.
 * Zero JS, zero re-renders.
 */
export function Tooltip({ children, tooltip }: TooltipProps) {
  return (
    <span className="group relative inline-flex">
      {children}
      <span
        className="pointer-events-none absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-[9999]
                   w-52 rounded px-2.5 py-2 flex flex-col gap-1
                   border shadow-xl
                   opacity-0 group-hover:opacity-100 transition-opacity duration-150"
        style={{
          backgroundColor: "var(--bg-base)",
          borderColor: "var(--border-default)",
        }}
      >
        <span className="text-[0.55rem] leading-snug" style={{ color: "var(--text-secondary)" }}>
          {tooltip.description}
        </span>
        {tooltip.context && (
          <span
            className="text-[0.55rem] leading-snug font-medium border-t pt-1"
            style={{
              color: "var(--text-primary)",
              borderColor: "var(--border-subtle)",
            }}
          >
            {tooltip.context}
          </span>
        )}
      </span>
    </span>
  );
}
