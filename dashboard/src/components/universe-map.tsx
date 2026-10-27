"use client";

import Link from "next/link";
import { memo, useCallback, useMemo, useRef, useState } from "react";
import { SectionTitle, TOOLTIP } from "@/components/cockpit";
import type { NameState, UniverseRow } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Most in need of action first: the order of the legend, and of the names inside each sector
 *  block. This is display order; which state a name gets is the API's precedence (`name_state`). */
export const STATE_ORDER: NameState[] = ["failing", "stale", "ended", "no_data", "inactive", "current"];

export const STATE_LABEL: Record<NameState, string> = {
  failing: "Failing fetch",
  stale: "Stale",
  ended: "Listing ended",
  no_data: "No bars",
  inactive: "Inactive",
  current: "Current",
};

/** Cell fill per state. Current is the quiet majority so the states to act on stand out. */
export const STATE_FILL: Record<NameState, string> = {
  failing: "bg-[var(--red)]",
  stale: "bg-[var(--amber)]",
  ended: "bg-[var(--text-secondary)]",
  no_data: "border border-dashed border-[var(--text-secondary)]",
  inactive: "border border-[var(--border-bright)]",
  current: "bg-[var(--state-current)]",
};

/** The small square a state is drawn as, everywhere a state is named. */
export function StateSwatch({ state, className = "size-2" }: { state: NameState; className?: string }) {
  return <span className={cn("shrink-0 rounded-[2px]", STATE_FILL[state], className)} />;
}

export const passportHref = (symbol: string) => `/instruments/${encodeURIComponent(symbol)}`;

interface Block {
  sector: string;
  names: UniverseRow[];
  flagged: number;
}

interface AssetClass {
  name: string;
  blocks: Block[];
  total: number;
}

const rank = (s: NameState) => STATE_ORDER.indexOf(s);

/** Asset class -> sector blocks, largest first; inside a block most severe first, then symbol. */
function group(rows: UniverseRow[]): AssetClass[] {
  const classes = new Map<string, Map<string, UniverseRow[]>>();
  for (const row of rows) {
    const cls = row.asset_class ?? "Unclassified";
    const sector = row.sector ?? "Unclassified";
    if (!classes.has(cls)) classes.set(cls, new Map());
    const sectors = classes.get(cls)!;
    if (!sectors.has(sector)) sectors.set(sector, []);
    sectors.get(sector)!.push(row);
  }
  return [...classes]
    .map(([name, sectors]) => {
      const blocks = [...sectors]
        .map(([sector, names]) => ({
          sector,
          names: names.sort((a, b) => rank(a.state) - rank(b.state) || a.symbol.localeCompare(b.symbol)),
          flagged: names.filter((n) => n.state !== "current").length,
        }))
        .sort((a, b) => b.names.length - a.names.length);
      return { name, blocks, total: blocks.reduce((n, b) => n + b.names.length, 0) };
    })
    .sort((a, b) => b.total - a.total);
}

const Cell = memo(function Cell({
  row,
  lit,
  onEnter,
}: {
  row: UniverseRow;
  lit: boolean;
  onEnter: (row: UniverseRow, el: HTMLElement) => void;
}) {
  return (
    <Link
      href={passportHref(row.symbol)}
      prefetch={false}
      tabIndex={-1}
      aria-label={`${row.symbol}, ${STATE_LABEL[row.state]}`}
      className={cn(
        "size-[11px] rounded-[2px] transition-opacity hover:outline hover:outline-2 hover:outline-[var(--text-primary)]",
        STATE_FILL[row.state],
        !lit && "opacity-15",
      )}
      onMouseEnter={(e) => onEnter(row, e.currentTarget)}
    />
  );
});

/**
 * Every name as one cell, grouped by asset class and sector and coloured by state, so where the
 * problems cluster is visible at a glance. `isLit` decides which cells stay at full strength
 * (the legend filter and the search); the rest dim. Hovering a cell names it; clicking opens its
 * passport. Cells are not tab stops (1,500 of them); the table below is the keyboard path.
 */
export function UniverseMap({
  rows,
  isLit,
}: {
  rows: UniverseRow[];
  isLit: (row: UniverseRow) => boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<{ row: UniverseRow; x: number; y: number } | null>(null);
  const classes = useMemo(() => group(rows), [rows]);
  const onEnter = useCallback((row: UniverseRow, el: HTMLElement) => {
    const box = el.getBoundingClientRect();
    const origin = host.current!.getBoundingClientRect();
    setHover({ row, x: box.left - origin.left, y: box.bottom - origin.top });
  }, []);

  return (
    <div ref={host} className="relative flex flex-col gap-6" onMouseLeave={() => setHover(null)}>
      {classes.map((cls) => (
        <section key={cls.name} className="flex flex-col gap-3">
          <SectionTitle title={cls.name} count={cls.total} />
          <div className="flex flex-wrap gap-x-6 gap-y-4">
            {cls.blocks.map((block) => (
              <div key={block.sector} className="flex max-w-[22rem] flex-col gap-1.5">
                <div className="flex items-baseline gap-2 text-xs">
                  <span className="text-[var(--text-secondary)]">{block.sector}</span>
                  <span className="font-mono text-[0.65rem] text-[var(--text-muted)]">
                    {block.names.length}
                    {block.flagged > 0 && `, ${block.flagged} flagged`}
                  </span>
                </div>
                <div className="flex flex-wrap gap-[2px]">
                  {block.names.map((row) => (
                    <Cell key={row.symbol} row={row} lit={isLit(row)} onEnter={onEnter} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}
      {hover && (
        <div className={cn(TOOLTIP, "mt-2")} style={{ left: Math.max(0, hover.x - 8), top: hover.y }}>
          <div className="flex items-center gap-2">
            <StateSwatch state={hover.row.state} />
            <span className="font-mono font-semibold">{hover.row.symbol}</span>
            <span className="text-[var(--text-secondary)]">{STATE_LABEL[hover.row.state]}</span>
          </div>
          {hover.row.name && <div className="mt-0.5 text-[var(--text-secondary)]">{hover.row.name}</div>}
        </div>
      )}
    </div>
  );
}
