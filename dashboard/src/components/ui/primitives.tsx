"use client";

import { Tooltip, type TooltipContent } from "@/components/tooltip";

/**
 * Reusable section container with elevated background.
 * Used throughout the dashboard for grouping related metrics.
 */
export function Section({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-[0.55rem] font-semibold uppercase tracking-widest text-[var(--text-muted)] mb-1.5">
        {label}
      </h3>
      <div
        className="rounded px-3 py-2"
        style={{ backgroundColor: "var(--bg-elevated)" }}
      >
        {children}
      </div>
    </div>
  );
}

/**
 * Two-column grid for key-value metric pairs.
 * Provides consistent spacing across all drill-down panels.
 */
export function Grid({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-1">
      {children}
    </div>
  );
}

/**
 * Key-value metric row with optional tooltip.
 * Truncates long values and handles empty states gracefully.
 */
export function KV({
  label,
  value,
  tooltip,
  valueClassName,
}: {
  label: string;
  value: string;
  tooltip?: TooltipContent;
  valueClassName?: string;
}) {
  const labelEl = (
    <span className="text-[0.55rem] text-[var(--text-muted)] shrink-0">{label}</span>
  );

  return (
    <div className="flex items-baseline justify-between gap-1 min-w-0">
      {tooltip ? (
        <Tooltip tooltip={tooltip}>{labelEl}</Tooltip>
      ) : (
        labelEl
      )}
      <span className={`text-[0.6rem] font-data truncate text-right ${valueClassName ?? "text-[var(--text-secondary)]"}`}>
        {value}
      </span>
    </div>
  );
}

/**
 * Empty state placeholder for sections awaiting data.
 * Provides consistent styling across the dashboard.
 */
export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-[0.6rem] italic text-[var(--text-muted)]">{children}</span>
  );
}
