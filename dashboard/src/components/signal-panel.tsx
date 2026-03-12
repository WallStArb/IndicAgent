"use client";

import type { SignalData } from "@/lib/types";
import { fmtPrice } from "@/lib/format";

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

interface SignalPanelProps {
  signal: SignalData;
}

/**
 * SignalPanel renders the signal price strip (Entry / SL / T1 / T2) plus
 * resolved-state overlays:
 *   - resolved === true  → 50% opacity + outcome badge
 *   - resolved undefined → full opacity, no badge (live signal)
 */
export function SignalPanel({ signal }: SignalPanelProps) {
  const hasT1 = signal.profit_target != null;
  const hasT2 = signal.profit_target_2 != null;
  const isResolved = signal.resolved === true;

  return (
    <div className={isResolved ? "opacity-50" : ""}>
      {/* Outcome badge — only for resolved signals */}
      {isResolved && (
        <div className="mb-2">
          <OutcomeBadge outcome={signal.outcome} />
        </div>
      )}

      {/* Price strip: Entry/SL on row 1, T1+T2 on row 2 */}
      <div
        className="py-1.5 border-t border-b text-xs font-data tabular-nums space-y-0.5"
        style={{ borderColor: "var(--border-subtle)" }}
      >
        <div className="flex items-center gap-3">
          <span style={{ color: "var(--text-muted)" }}>
            Entry{" "}
            <span style={{ color: "var(--text-primary)" }}>
              {fmtPrice(signal.entry_price)}
            </span>
          </span>
          <span style={{ color: "var(--border-subtle)" }}>|</span>
          <span style={{ color: "var(--text-muted)" }}>
            SL{" "}
            <span style={{ color: "var(--red)" }}>
              {fmtPrice(signal.stop_loss)}
            </span>
          </span>
          {/* Exit price shown when resolved */}
          {isResolved && signal.exit_price != null && (
            <>
              <span style={{ color: "var(--border-subtle)" }}>|</span>
              <span style={{ color: "var(--text-muted)" }}>
                Exit{" "}
                <span style={{ color: "var(--text-secondary)" }}>
                  {fmtPrice(signal.exit_price)}
                </span>
              </span>
            </>
          )}
          {/* P&L in R shown when resolved */}
          {isResolved && signal.pnl_r != null && (
            <span
              style={{
                color: signal.pnl_r >= 0 ? "var(--green)" : "var(--red)",
                fontWeight: 600,
              }}
            >
              {signal.pnl_r >= 0 ? "+" : ""}
              {signal.pnl_r.toFixed(2)}R
            </span>
          )}
        </div>

        {hasT1 && (
          <div className="flex items-center gap-3">
            <span style={{ color: "var(--text-muted)" }}>
              T1{" "}
              <span style={{ color: "var(--green)" }}>
                {fmtPrice(signal.profit_target!)}
              </span>
              {signal.rr_t1 != null && (
                <span
                  className="ml-1 px-1 py-px rounded"
                  style={{
                    background: "var(--bg-elevated)",
                    color: "var(--text-muted)",
                    fontSize: "0.65rem",
                  }}
                >
                  {signal.rr_t1.toFixed(1)}R
                </span>
              )}
            </span>
            {hasT2 && (
              <>
                <span style={{ color: "var(--border-subtle)" }}>·</span>
                <span style={{ color: "var(--text-muted)" }}>
                  T2{" "}
                  <span style={{ color: "var(--green)" }}>
                    {fmtPrice(signal.profit_target_2!)}
                  </span>
                  {signal.rr_t2 != null && (
                    <span
                      className="ml-1 px-1 py-px rounded"
                      style={{
                        background: "var(--bg-elevated)",
                        color: "var(--text-muted)",
                        fontSize: "0.65rem",
                      }}
                    >
                      {signal.rr_t2.toFixed(1)}R
                    </span>
                  )}
                </span>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export { OutcomeBadge };
export default SignalPanel;
