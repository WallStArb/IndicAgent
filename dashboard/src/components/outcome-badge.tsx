"use client";

// Map 8-class lifecycle outcomes to 5 display labels
const OUTCOME_LABEL_MAP: Record<string, string> = {
  never_activated: "EXPIRED",
  stopped_at_entry: "STOPPED",
  stopped_in_trade: "STOPPED",
  target_1: "T1 HIT",
  target_1_2: "T1+T2 HIT",
  target_full: "FULL TARGET",
  ttl_expired_ahead: "EXPIRED",
  ttl_expired_behind: "EXPIRED",
};

interface OutcomeBadgeProps {
  outcome?: string;
  small?: boolean;
}

/** Renders a colored badge showing the resolved signal outcome. Returns null if no outcome. */
function OutcomeBadge({ outcome, small }: OutcomeBadgeProps) {
  if (!outcome) return null;

  const label = OUTCOME_LABEL_MAP[outcome] ?? outcome.toUpperCase();

  const colorClass =
    label.includes("HIT") || label.includes("TARGET")
      ? "bg-green-600"
      : label === "STOPPED"
        ? "bg-red-600"
        : "bg-gray-600";

  const sizeClass = small
    ? "text-[0.45rem] px-1 py-0.5 rounded-sm"
    : "text-xs px-2 py-1 rounded";

  return (
    <div
      className={`${colorClass} ${sizeClass} text-white font-bold inline-block`}
    >
      {label}
    </div>
  );
}

export { OutcomeBadge };
