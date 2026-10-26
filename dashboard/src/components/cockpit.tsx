import { cn } from "@/lib/utils";
import { fmtAgo, fmtUtc } from "@/lib/time";
import type { StageStatus } from "@/lib/types";

const STATUS_STYLE: Record<StageStatus, string> = {
  ok: "text-[var(--green)] bg-[var(--green-dim)]",
  stale: "text-[var(--amber)] bg-[var(--amber-dim)]",
  failing: "text-[var(--red)] bg-[var(--red-dim)]",
  error: "text-[var(--red)] border-[var(--red)]",
  empty: "text-[var(--text-secondary)] bg-[var(--bg-elevated)]",
  not_built: "text-[var(--text-muted)] border-dashed border-[var(--border-bright)]",
};

export function StatusChip({ status }: { status: StageStatus }) {
  return (
    <span
      className={cn(
        "inline-block rounded border border-transparent px-1.5 py-0.5 text-[0.65rem] font-semibold uppercase tracking-wider",
        STATUS_STYLE[status],
      )}
    >
      {status.replace("_", " ")}
    </span>
  );
}

/** Where a figure came from and how new it is (design decision 4: lineage on every number). */
export function Lineage({ source, asOf }: { source: string | null; asOf: string | null }) {
  return (
    <div className="text-[0.65rem] text-[var(--text-muted)] font-mono">
      {source ?? "no source yet"}
      {asOf && ` as of ${fmtAgo(asOf)} (${fmtUtc(asOf)})`}
    </div>
  );
}

function cell(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "string" && /^\d{4}-\d{2}-\d{2}T/.test(value)) return fmtUtc(value);
  if (typeof value === "number") return value.toLocaleString();
  return String(value);
}

/** A compact table over API rows; columns default to the first row's keys. */
export function RowsTable<R extends object>({
  rows,
  columns,
  highlight,
  empty = "No rows.",
}: {
  rows: R[];
  columns?: (keyof R & string)[];
  highlight?: (row: R) => boolean;
  empty?: string;
}) {
  if (rows.length === 0) {
    return <p className="text-xs text-[var(--text-muted)] py-2">{empty}</p>;
  }
  const cols = columns ?? (Object.keys(rows[0]) as (keyof R & string)[]);
  return (
    <table className="w-full text-xs">
      <thead>
        <tr className="text-left text-[var(--text-muted)]">
          {cols.map((c) => (
            <th key={c} className="font-medium py-1 pr-3 whitespace-nowrap">
              {c.replaceAll("_", " ")}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="font-mono">
        {rows.map((row, i) => (
          <tr
            key={i}
            className={cn(
              "border-t border-[var(--border-subtle)]",
              highlight?.(row) && "text-[var(--red)]",
            )}
          >
            {cols.map((c) => (
              <td key={c} className="py-1 pr-3 whitespace-nowrap">
                {cell(row[c])}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

/**
 * One titled block of a page: what it answers, its rows, and where they came from. `aside`
 * sits beside the title (a status chip, a count); `children` replaces the table when given;
 * `footer` renders below it.
 */
export function Panel<R extends object>({
  title,
  question,
  rows,
  source,
  asOf,
  aside,
  highlight,
  empty,
  className,
  children,
  footer,
}: {
  title: string;
  question: string;
  rows: R[];
  source: string | null;
  asOf: string | null;
  aside?: React.ReactNode;
  highlight?: (row: R) => boolean;
  empty?: string;
  className?: string;
  children?: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <section className={cn("flex flex-col gap-2", className)}>
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{title}</h2>
        {aside}
      </div>
      <p className="text-xs text-[var(--text-secondary)]">{question}</p>
      {children ?? <RowsTable rows={rows} highlight={highlight} empty={empty} />}
      {footer}
      <div className="mt-auto pt-1">
        <Lineage source={source} asOf={asOf} />
      </div>
    </section>
  );
}

export function PageHeader({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <header className="flex items-baseline justify-between gap-4 px-6 pt-5 pb-3 border-b border-[var(--border-subtle)]">
      <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
      <div className="text-xs text-[var(--text-muted)]">{children}</div>
    </header>
  );
}

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return <p className="px-6 pt-3 text-xs text-[var(--red)]">Last poll failed: {error}</p>;
}
