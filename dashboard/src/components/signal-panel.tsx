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
}

/** Renders a colored badge showing the resolved signal outcome. Returns null if no outcome. */
function OutcomeBadge({ outcome }: OutcomeBadgeProps) {
  if (!outcome) return null;

  const label = OUTCOME_LABEL_MAP[outcome] ?? outcome.toUpperCase();

  const colorClass =
    label.includes("HIT") || label.includes("TARGET")
      ? "bg-green-600"
      : label === "STOPPED"
        ? "bg-red-600"
        : "bg-gray-600";

  return (
    <div
      className={`${colorClass} text-white text-xs font-bold px-2 py-1 rounded inline-block`}
    >
      {label}
    </div>
  );
}

export { OutcomeBadge };
