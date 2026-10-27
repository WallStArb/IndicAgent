"use client";

import { useState } from "react";
import {
  CARD,
  ErrorNote,
  LoadingNote,
  PageHeader,
  Panel,
  RowsTable,
  SearchInput,
  SMALL_LABEL,
  pressable,
  type RowTone,
} from "@/components/cockpit";
import { useApi } from "@/hooks/use-api";
import { fmtAgo, fmtUtc } from "@/lib/time";
import { CONCEPT_STATUSES, type ConceptRow, type ConceptsSummary } from "@/lib/types";
import { cn, fixed, spaced } from "@/lib/utils";

// A state the registry adds before this list learns it still gets a column (after the known
// ones), so no concept can drop out of the matrix.
const LIFECYCLE: readonly string[] = CONCEPT_STATUSES;

/** A cell of the lifecycle matrix: one domain in one state. */
type Cell = { domain: string; status: string };

const cellKey = (c: Cell) => `${c.domain}/${c.status}`;

/**
 * Concepts per domain per lifecycle state; the matrix is the filter, as the universe map's legend
 * is: pressing a count lists only its concepts, pressing it again lists them all.
 */
function LifecycleMatrix({
  rows,
  selected,
  onSelect,
}: {
  rows: ConceptRow[];
  selected: Cell | null;
  onSelect: (cell: Cell) => void;
}) {
  const domains = [...new Set(rows.map((r) => r.domain))];
  const seen = new Set(rows.map((r) => r.status));
  const statuses = [...LIFECYCLE, ...[...seen].filter((s) => !LIFECYCLE.includes(s))];
  const counts = new Map<string, number>();
  for (const r of rows) counts.set(cellKey(r), (counts.get(cellKey(r)) ?? 0) + 1);
  return (
    <table className="w-full max-w-2xl text-xs">
      <thead>
        <tr>
          <th className={cn(SMALL_LABEL, "py-1.5 pr-4 text-left")}>domain</th>
          {statuses.map((s) => (
            <th key={s} className={cn(SMALL_LABEL, "py-1.5 px-2 text-right")}>
              {spaced(s)}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="font-mono tabular-nums">
        {domains.map((domain) => (
          <tr key={domain} className="border-t border-[var(--border-subtle)]">
            <td className="py-1 pr-4">{spaced(domain)}</td>
            {statuses.map((status) => {
              const cell = { domain, status };
              const n = counts.get(cellKey(cell)) ?? 0;
              const pressed = selected !== null && cellKey(selected) === cellKey(cell);
              return (
                <td key={status} className="py-1 px-1 text-right">
                  {/* A pressed cell stays a button when its count drops to 0, so it can be released. */}
                  {n > 0 || pressed ? (
                    <button
                      type="button"
                      aria-pressed={pressed}
                      onClick={() => onSelect(cell)}
                      className={cn("min-w-12 rounded-md px-2 py-0.5 text-right", pressable(pressed))}
                    >
                      {n.toLocaleString()}
                    </button>
                  ) : (
                    <span className="px-2 text-[var(--text-muted)]">-</span>
                  )}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const COLUMNS: (keyof ConceptRow & string)[] = [
  "name",
  "group_name",
  "status",
  "passed",
  "statistic",
  "n_cells",
  "evaluated_at",
  "trigger_reason",
];

const LABELS: Partial<Record<keyof ConceptRow & string, string>> = {
  group_name: "group",
  passed: "evidence",
  n_cells: "cells",
  evaluated_at: "evaluated",
  trigger_reason: "last transition",
};

const RENDER: Partial<Record<keyof ConceptRow & string, (r: ConceptRow) => React.ReactNode>> = {
  name: (r) => (
    <span className="flex items-center gap-1.5">
      <span className="font-semibold">{r.name}</span>
      {r.is_control && (
        <span className="rounded border border-[var(--border-bright)] px-1 text-[0.6rem] text-[var(--text-secondary)]">
          {r.control_expectation ? spaced(r.control_expectation) : "control"}
        </span>
      )}
    </span>
  ),
  status: (r) => `${spaced(r.status)}${r.enabled ? "" : " (off)"}`,
  passed: (r) =>
    r.evidence_kind
      ? `${spaced(r.evidence_kind)}: ${r.passed ? "pass" : "fail"}${r.guard_status ? `, guard ${spaced(r.guard_status)}` : ""}`
      : "-",
  statistic: (r) => fixed(r.statistic, 4),
  evaluated_at: (r) => <span title={fmtUtc(r.evaluated_at)}>{fmtAgo(r.evaluated_at)}</span>,
  trigger_reason: (r) =>
    r.trigger_reason ? (
      <span title={fmtUtc(r.triggered_at)}>
        {spaced(r.from_status ?? "-")} to {spaced(r.to_status ?? "-")}, {spaced(r.trigger_reason)},{" "}
        {fmtAgo(r.triggered_at)}
      </span>
    ) : (
      "-"
    ),
};

/** Evidence that failed reads red; a deprecated concept needs no attention. */
const tone = (r: ConceptRow): RowTone => (r.passed === false ? "bad" : r.status === "deprecated" ? "dim" : undefined);

export default function ConceptsPage() {
  const { data, error, loading } = useApi<ConceptsSummary>("/api/concepts/summary");
  const [selected, setSelected] = useState<Cell | null>(null);
  const [query, setQuery] = useState("");
  const rows = data?.concepts.rows ?? [];
  const q = query.trim().toLowerCase();
  const listed = rows.filter(
    (r) =>
      (!selected || cellKey(selected) === cellKey(r)) &&
      (!q || r.name.toLowerCase().includes(q) || (r.group_name ?? "").toLowerCase().includes(q)),
  );
  const conceptsFailed = data?.concepts.meta.error;
  const active = rows.filter((r) => r.status === "active").length;
  const controls = rows.filter((r) => r.is_control).length;

  return (
    <div>
      <PageHeader title="Concepts">
        {data &&
          (conceptsFailed
            ? "? concepts"
            : `${rows.length.toLocaleString()} concepts · ${active.toLocaleString()} active · ${controls} controls`)}
      </PageHeader>
      <ErrorNote error={error} />
      <LoadingNote loading={loading} />
      {data && (
        <div className="flex flex-col gap-4 p-6">
          <Panel
            className={CARD}
            title="Lifecycle"
            question="Concepts per domain in each registry state; only the registry service moves a concept between them. Press a count to list those concepts."
            source={data.concepts.source}
            asOf={data.concepts.as_of}
            error={conceptsFailed}
          >
            <LifecycleMatrix
              rows={rows}
              selected={selected}
              onSelect={(cell) => setSelected(selected && cellKey(selected) === cellKey(cell) ? null : cell)}
            />
          </Panel>

          <Panel
            className={CARD}
            title="Measured IC"
            question="The fresh IC store at each timeframe, regime scope and horizon's newest training window: features measured, and features with at least one cell passing the FDR gate."
            rows={data.ic.rows.map((r) => ({
              timeframe: r.tf,
              scope: spaced(r.regime_scope),
              horizon_bars: r.lookahead_bars,
              passing_fdr: `${r.features_passing_fdr.toLocaleString()} / ${r.features.toLocaleString()}`,
              cells: r.rows,
              window_end: fmtAgo(r.window_end),
            }))}
            source={data.ic.source}
            asOf={data.ic.as_of}
            empty={`No IC measured yet: ${data.ic.meta.detail ?? "ic_measure has not written"}.`}
            error={data.ic.meta.error}
          />

          <Panel
            className={CARD}
            title={selected ? `${spaced(selected.domain)}, ${spaced(selected.status)}` : "All concepts"}
            count={conceptsFailed ? undefined : listed.length}
            question="Each concept's latest evaluation by the feature lifecycle and its latest registry transition."
            aside={<SearchInput value={query} onChange={setQuery} label="Find a concept or group" />}
            source={data.concepts.source}
            asOf={data.concepts.as_of}
            error={conceptsFailed}
          >
            <RowsTable
              rows={listed}
              columns={COLUMNS}
              labels={LABELS}
              render={RENDER}
              tone={tone}
              empty="No concepts match."
              maxHeight="640px"
            />
          </Panel>
        </div>
      )}
    </div>
  );
}
