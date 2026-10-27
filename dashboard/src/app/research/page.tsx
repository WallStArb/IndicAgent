"use client";

import { CARD, ErrorNote, LoadingNote, PageHeader, Panel, RowsTable, type RowTone } from "@/components/cockpit";
import { useApi } from "@/hooks/use-api";
import { fmtAgo, fmtUtc } from "@/lib/time";
import type { ResearchSummary, RunRow, VintageRow } from "@/lib/types";
import { fixed, spaced } from "@/lib/utils";

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
  statistic: (r) => (r.statistic ? spaced(r.statistic) : "-"),
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

const VINTAGE_COLUMNS: (keyof VintageRow & string)[] = [
  "vintage",
  "kind",
  "mode",
  "attempts",
  "charged",
  "completed",
  "failed",
  "guard_failed",
  "refused",
  "unfinished",
  "newest",
];

const VINTAGE_RENDER: Partial<Record<keyof VintageRow & string, (v: VintageRow) => React.ReactNode>> = {
  kind: (v) => spaced(v.kind),
  newest: (v) => fmtAgo(v.newest),
};

export default function ResearchPage() {
  const { data, error, loading } = useApi<ResearchSummary>("/api/research/summary");
  const runs = data?.runs.rows ?? [];
  const unfinished = data?.vintages.rows.reduce((n, v) => n + v.unfinished, 0) ?? 0;

  return (
    <div>
      <PageHeader title="Research">
        {data &&
          (data.runs.meta.error
            ? "? attempts"
            : `${runs.length.toLocaleString()} attempts in ${data.runs.meta.run_groups ?? "?"} runs · ${unfinished} unfinished`)}
      </PageHeader>
      <ErrorNote error={error} />
      <LoadingNote loading={loading} />
      {data && (
        <div className="flex flex-col gap-4 p-6">
          <Panel
            className={CARD}
            title="Looks per vintage"
            question="Every attempt the ledger recorded, by vintage, kind and mode: how many the vintage's budget charges (all but refused and guard-failed) and how each ended. Unfinished is still started: in progress, or its runner died."
            source={data.vintages.source}
            asOf={data.vintages.as_of}
            error={data.vintages.meta.error}
          >
            <RowsTable
              rows={data.vintages.rows}
              columns={VINTAGE_COLUMNS}
              render={VINTAGE_RENDER}
              empty="The ledger has no attempts yet."
            />
          </Panel>

          <Panel
            className={CARD}
            title="Attempts"
            count={data.runs.meta.error ? undefined : runs.length}
            question="Each attempt newest first with the headline the runner stored: the decision statistic, its t and p, gross annualized Sharpe and mean P&L per session, before costs."
            source={data.runs.source}
            asOf={data.runs.as_of}
            error={data.runs.meta.error}
          >
            <RowsTable
              rows={runs}
              columns={COLUMNS}
              labels={LABELS}
              render={RENDER}
              tone={tone}
              empty="The ledger has no attempts yet."
              maxHeight="640px"
            />
          </Panel>

          <Panel
            className={CARD}
            title="Legacy gates"
            question="Gate verdicts from before the v3.5 research runner, kept as the record they are; new evidence goes through the ledger above."
            rows={data.gates.rows.map((g) => ({ gate: g.gate_id, result: g.result, run: fmtUtc(g.run_ts) }))}
            source={data.gates.source}
            asOf={data.gates.as_of}
            tone={(g) => (g.result === "fail" ? "bad" : "dim")}
            empty="No legacy gate verdicts."
            error={data.gates.meta.error}
          />
        </div>
      )}
    </div>
  );
}
