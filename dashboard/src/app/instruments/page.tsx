"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import {
  CARD,
  ErrorNote,
  Lineage,
  LoadingNote,
  PageHeader,
  RowsTable,
  SectionTitle,
} from "@/components/cockpit";
import { STATE_FILL, STATE_LABEL, STATE_ORDER, UniverseMap, passportHref } from "@/components/universe-map";
import { useApi } from "@/hooks/use-api";
import { fmtAgo, fmtUtc } from "@/lib/time";
import type { NameState, UniverseRow, UniverseSummary } from "@/lib/types";
import { cn } from "@/lib/utils";

function compute(row: UniverseRow): string {
  const tiers = [row.compute_eligible && "intraday", row.compute_eligible_1d && "1d"].filter(Boolean);
  return tiers.length ? tiers.join(", ") : "none";
}

/** The legend doubles as the filter: each state with its count, pressed to light only it. */
function Legend({
  rows,
  selected,
  onToggle,
}: {
  rows: UniverseRow[];
  selected: NameState | null;
  onToggle: (state: NameState) => void;
}) {
  const counts = new Map<NameState, number>();
  for (const row of rows) counts.set(row.state, (counts.get(row.state) ?? 0) + 1);
  return (
    <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter names by state">
      {STATE_ORDER.filter((s) => counts.get(s)).map((state) => (
        <button
          key={state}
          type="button"
          aria-pressed={selected === state}
          onClick={() => onToggle(state)}
          className={cn(
            "flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs transition-colors",
            selected === state
              ? "border-[var(--text-secondary)] bg-[var(--bg-elevated)]"
              : "border-[var(--border-subtle)] hover:bg-[var(--bg-hover)]",
          )}
        >
          <span className={cn("size-2.5 rounded-[2px]", STATE_FILL[state])} />
          {STATE_LABEL[state]}
          <span className="font-mono text-[var(--text-secondary)]">{counts.get(state)!.toLocaleString()}</span>
        </button>
      ))}
    </div>
  );
}

/** The table's view of a name: what an operator scans for, in reading order. */
function tableRow(row: UniverseRow) {
  return {
    symbol: row.symbol,
    name: row.name ?? "-",
    sector: row.sector ?? "-",
    state: STATE_LABEL[row.state] + (row.listing_ended ? ` ${row.listing_ended}` : ""),
    newest_bar: fmtAgo(row.newest_bar),
    failing_feeds: `${row.failing_feeds ?? 0} of ${row.feeds ?? 0}`,
    compute: compute(row),
    _row: row,
  };
}

type TableRow = ReturnType<typeof tableRow>;

const RENDER = {
  symbol: (r: TableRow) => (
    <Link href={passportHref(r.symbol)} prefetch={false} className="font-semibold text-[var(--accent-cyan)] hover:underline">
      {r.symbol}
    </Link>
  ),
  state: (r: TableRow) => (
    <span className="flex items-center gap-1.5">
      <span className={cn("size-2 rounded-[2px]", STATE_FILL[r._row.state])} />
      {r.state}
    </span>
  ),
  newest_bar: (r: TableRow) => <span title={fmtUtc(r._row.newest_bar)}>{r.newest_bar}</span>,
};

export default function InstrumentsPage() {
  const { data, error, loading } = useApi<UniverseSummary>("/api/universe/summary");
  const router = useRouter();
  const [selected, setSelected] = useState<NameState | null>(null);
  const [query, setQuery] = useState("");
  const rows = useMemo(() => data?.rows ?? [], [data]);
  const q = query.trim().toUpperCase();

  const isLit = (row: UniverseRow) =>
    (!selected || row.state === selected) &&
    (!q || row.symbol.startsWith(q) || (row.name ?? "").toUpperCase().includes(q));
  // With no filter the table answers "which names need attention"; with one, it lists the lit cells.
  const filtering = selected !== null || q !== "";
  const listed = rows.filter((r) => (filtering ? isLit(r) : r.state !== "current")).map(tableRow);
  const title = selected ? STATE_LABEL[selected] : q ? "Matching names" : "Names needing attention";

  return (
    <div>
      <PageHeader title="Instruments">
        {data && `${rows.length.toLocaleString()} names, stale after ${data.meta.stale_hours} h`}
      </PageHeader>
      <ErrorNote error={error} />
      <LoadingNote loading={loading} />
      {data && (
        <div className="flex flex-col gap-4 p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Legend rows={rows} selected={selected} onToggle={(s) => setSelected(selected === s ? null : s)} />
            <input
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && rows.some((r) => r.symbol === q)) router.push(passportHref(q));
              }}
              placeholder="Find a symbol or name"
              aria-label="Find a symbol or name; Enter opens an exact symbol"
              className="w-64 rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-1.5 text-sm placeholder:text-[var(--text-muted)] focus:border-[var(--accent-cyan)] focus:outline-none"
            />
          </div>

          <section className={cn(CARD, "flex flex-col gap-4")}>
            <UniverseMap rows={rows} isLit={isLit} />
            <Lineage source={data.source} asOf={data.as_of} />
          </section>

          <section className={cn(CARD, "flex flex-col gap-2")}>
            <SectionTitle title={title} count={listed.length} />
            <RowsTable rows={listed} render={RENDER} empty="No names match." />
          </section>
        </div>
      )}
    </div>
  );
}
