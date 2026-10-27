import { RowsTable, type RowTone } from "@/components/cockpit";
import { fmtAgo, fmtUtc } from "@/lib/time";
import type { RunRow } from "@/lib/types";
import { fixed, spaced } from "@/lib/utils";

// Research ledger attempts as both the Research and Books pages list them, so one row reads the
// same on each.

/** A p-value readable at any size: decimals down to 0.001, scientific below. */
const pValue = (p: number | null) => (p === null ? "-" : p >= 0.001 ? p.toFixed(3) : p.toExponential(1));

/** The spec file's name without its directory and extension. */
const specName = (path: string) => (path.split("/").pop() ?? path).replace(/\.ya?ml$/, "");

const COLUMNS: (keyof RunRow & string)[] = [
  "started_at",
  "spec_path",
  "concept",
  "kind",
  "status",
  "statistic",
  "decision_t",
  "decision_p",
  "gross_sharpe",
  "mean_session_pnl",
  "n_sessions",
  "span_start",
  "note",
];

const LABELS: Partial<Record<keyof RunRow & string, string>> = {
  started_at: "started",
  spec_path: "spec",
  decision_t: "t",
  decision_p: "p",
  gross_sharpe: "gross sharpe",
  mean_session_pnl: "pnl / session (bp)",
  n_sessions: "sessions",
  span_start: "span",
};

const RENDER: Partial<Record<keyof RunRow & string, (r: RunRow) => React.ReactNode>> = {
  started_at: (r) => <span title={fmtUtc(r.started_at)}>{fmtAgo(r.started_at)}</span>,
  spec_path: (r) => <span title={r.spec_path}>{specName(r.spec_path)}</span>,
  kind: (r) => `${spaced(r.kind)}${r.mode === "real" ? "" : ` (${r.mode})`}`,
  status: (r) => spaced(r.status),
  statistic: (r) => r.statistic ?? "-",
  decision_t: (r) => fixed(r.decision_t, 2),
  decision_p: (r) => pValue(r.decision_p),
  gross_sharpe: (r) => fixed(r.gross_sharpe, 2),
  mean_session_pnl: (r) => fixed(r.mean_session_pnl === null ? null : r.mean_session_pnl * 1e4, 2),
  n_sessions: (r) => r.n_sessions?.toLocaleString() ?? "-",
  span_start: (r) => (r.span_start ? `${r.span_start} to ${r.span_end}` : "-"),
  note: (r) => r.note ?? "",
};

/** A failed attempt reads red; one the ledger refused or a guard stopped (not charged) is dimmed. */
const tone = (r: RunRow): RowTone =>
  r.status === "failed" ? "bad" : r.status === "refused" || r.status === "guard_failed" ? "dim" : undefined;

/** Ledger attempts, newest first, with the headline the runner stored. */
export function RunsTable({ rows, empty }: { rows: RunRow[]; empty: string }) {
  return (
    <RowsTable rows={rows} columns={COLUMNS} labels={LABELS} render={RENDER} tone={tone} empty={empty} maxHeight="640px" />
  );
}
