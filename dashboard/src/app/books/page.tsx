"use client";

import { CARD, ErrorNote, LoadingNote, PageHeader, Panel, SectionTitle } from "@/components/cockpit";
import { RunsTable } from "@/components/runs-table";
import { useApi } from "@/hooks/use-api";
import type { ResearchSummary } from "@/lib/types";

// The ledger kinds that test a whole book rather than one member's evidence.
const BOOK_KINDS = new Set(["book_test", "pod_book"]);

// What phase 188 builds to fill this page (ROADMAP phase 188; unified design track E).
const PLANNED: { name: string; does: string }[] = [
  { name: "BookTracker", does: "runs a frozen book forward on the code that tested it, in sealed shadow" },
  { name: "BookPositionWriter", does: "persists append-only positions, with revision alarms and parity against research" },
  { name: "Cost model", does: "impact, borrow, capacity and implementation shortfall, so promotion reads net" },
  { name: "portfolio_state", does: "sizing and risk limits for capital earned on measured net" },
];

export default function BooksPage() {
  const { data, error, loading } = useApi<ResearchSummary>("/api/research/summary");
  const tests = (data?.runs.rows ?? []).filter((r) => BOOK_KINDS.has(r.kind));

  return (
    <div>
      <PageHeader title="Books">forward runner not built (phase 188)</PageHeader>
      <ErrorNote error={error} />
      <LoadingNote loading={loading} />
      <div className="flex flex-col gap-4 p-6">
        <section className={`${CARD} flex flex-col gap-3`}>
          <SectionTitle title="Not built yet" />
          <p className="text-xs text-[var(--text-secondary)]">
            Phase 188 fills this page. It starts once a candidate book is in the selection set and the
            borrow snapshots (todo 438) are running; each frozen book then shows its forward span, positions
            and net against the research it came from.
          </p>
          <ul className="flex flex-col gap-1.5 text-xs">
            {PLANNED.map((p) => (
              <li key={p.name}>
                <span className="font-mono font-semibold">{p.name}</span>
                <span className="text-[var(--text-secondary)]"> {p.does}</span>
              </li>
            ))}
          </ul>
        </section>

        {data && (
          <Panel
            className={CARD}
            title="Book tests"
            count={data.runs.meta.error ? undefined : tests.length}
            question="Every whole-book attempt in the research ledger: the road to a candidate book."
            source={data.runs.source}
            asOf={data.runs.as_of}
            error={data.runs.meta.error}
          >
            <RunsTable rows={tests} empty="No book has been tested yet." />
          </Panel>
        )}
      </div>
    </div>
  );
}
