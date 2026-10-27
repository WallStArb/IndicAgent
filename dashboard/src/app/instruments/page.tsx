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
  SearchInput,
  SectionTitle,
  ToggleGroup,
} from "@/components/cockpit";
import { STATE_LABEL, STATE_ORDER, StateSwatch, UniverseMap, passportHref } from "@/components/universe-map";
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
    <ToggleGroup
      label="Filter names by state"
      options={STATE_ORDER.filter((s) => counts.get(s)).map((state) => ({
        key: state,
        value: state,
        content: (
          <>
            <StateSwatch state={state} className="size-2.5" />
            <span className="text-[var(--text-primary)]">{STATE_LABEL[state]}</span>
            <span className="font-mono">{counts.get(state)!.toLocaleString()}</span>
          </>
        ),
      }))}
      selected={selected}
      onSelect={onToggle}
    />
  );
}

/** The table's columns, in the order an operator scans a name; each renders from the raw row. */
const COLUMNS: (keyof UniverseRow & string)[] = [
  "symbol",
  "name",
  "sector",
  "state",
  "newest_bar",
  "failing_feeds",
  "compute_eligible",
];

const LABELS: Partial<Record<keyof UniverseRow & string, string>> = { compute_eligible: "compute" };

const RENDER: Partial<Record<keyof UniverseRow & string, (r: UniverseRow) => React.ReactNode>> = {
  symbol: (r) => (
    <Link href={passportHref(r.symbol)} prefetch={false} className="font-semibold text-[var(--accent-cyan)] hover:underline">
      {r.symbol}
    </Link>
  ),
  state: (r) => (
    <span className="flex items-center gap-1.5">
      <StateSwatch state={r.state} />
      {STATE_LABEL[r.state]}
      {r.listing_ended && ` ${r.listing_ended}`}
    </span>
  ),
  newest_bar: (r) => <span title={fmtUtc(r.newest_bar)}>{fmtAgo(r.newest_bar)}</span>,
  failing_feeds: (r) => `${r.failing_feeds ?? 0} of ${r.feeds ?? 0}`,
  compute_eligible: compute,
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
  const listed = rows.filter((r) => (filtering ? isLit(r) : r.state !== "current"));
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
            <SearchInput
              value={query}
              onChange={setQuery}
              onKeyDown={(e) => {
                if (e.key === "Enter" && rows.some((r) => r.symbol === q)) router.push(passportHref(q));
              }}
              label="Find a symbol or name"
              hint="Enter opens an exact symbol"
            />
          </div>

          <section className={cn(CARD, "flex flex-col gap-4")}>
            <UniverseMap rows={rows} isLit={isLit} />
            <Lineage source={data.source} asOf={data.as_of} />
          </section>

          <section className={cn(CARD, "flex flex-col gap-2")}>
            <SectionTitle title={title} count={listed.length} />
            <RowsTable rows={listed} columns={COLUMNS} render={RENDER} labels={LABELS} empty="No names match." />
          </section>
        </div>
      )}
    </div>
  );
}
