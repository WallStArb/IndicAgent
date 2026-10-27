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

/** The card surface every panel sits on. */
export const CARD = "rounded-xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-5";

/** Uppercase tracked display label for section titles and column headers. */
const LABEL = "font-display uppercase tracking-[0.12em]";

export function Logo({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" fill="none" aria-hidden>
      <rect x="2" y="5" width="24" height="3" rx="1.5" fill="var(--accent-cyan)" opacity="0.4" />
      <rect x="5" y="10" width="18" height="3" rx="1.5" fill="var(--accent-cyan)" opacity="0.65" />
      <rect x="8" y="15" width="12" height="3" rx="1.5" fill="var(--accent-cyan)" opacity="0.85" />
      <rect x="11" y="20" width="6" height="3" rx="1.5" fill="var(--accent-cyan)" />
    </svg>
  );
}

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

// Cell values that name a state worth acting on are coloured; every other state stays plain.
const VALUE_TONE: Record<string, string> = {
  stale: "text-[var(--amber)]",
  failing: "text-[var(--red)]",
  failed: "text-[var(--red)]",
  error: "text-[var(--red)]",
};

/** How a row reads: `bad` is tinted red, `dim` is a normal row that needs no attention. */
export type RowTone = "bad" | "dim" | undefined;

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
  tone,
  empty = "No rows.",
}: {
  rows: R[];
  columns?: (keyof R & string)[];
  tone?: (row: R) => RowTone;
  empty?: string;
}) {
  if (rows.length === 0) {
    return <p className="text-xs text-[var(--text-muted)] py-2">{empty}</p>;
  }
  const cols = columns ?? (Object.keys(rows[0]) as (keyof R & string)[]);
  return (
    <div className="overflow-x-auto">
    <table className="w-full text-xs">
      <thead>
        <tr className="text-left text-[var(--text-muted)]">
          {cols.map((c) => (
            <th
              key={c}
              className={cn(
                LABEL,
                "text-[0.6rem] font-semibold py-1.5 pr-4 whitespace-nowrap",
                typeof rows[0][c] === "number" && "text-right",
              )}
            >
              {c.replaceAll("_", " ")}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="font-mono tabular-nums">
        {rows.map((row, i) => {
          const rowTone = tone?.(row);
          return (
            <tr
              key={i}
              className={cn(
                "border-t border-[var(--border-subtle)]",
                rowTone === "bad" && "bg-[var(--red-faint)]",
                rowTone === "dim" && "text-[var(--text-secondary)]",
              )}
            >
              {cols.map((c) => {
                const value = row[c];
                return (
                  <td
                    key={c}
                    className={cn(
                      "py-1.5 pr-4 whitespace-nowrap",
                      typeof value === "number" && "text-right",
                      typeof value === "string" && VALUE_TONE[value],
                    )}
                  >
                    {cell(value)}
                  </td>
                );
              })}
            </tr>
          );
        })}
      </tbody>
    </table>
    </div>
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
  tone,
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
  tone?: (row: R) => RowTone;
  empty?: string;
  className?: string;
  children?: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <section className={cn("flex min-w-0 flex-col gap-2", className)}>
      <div className="flex items-center justify-between gap-2">
        <h2 className={cn(LABEL, "text-xs font-bold")}>{title}</h2>
        {aside}
      </div>
      <p className="text-xs text-[var(--text-secondary)]">{question}</p>
      {children ?? <RowsTable rows={rows} tone={tone} empty={empty} />}
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
      <h1 className="font-display text-xl font-bold tracking-tight">{title}</h1>
      <div className="text-xs text-[var(--text-muted)]">{children}</div>
    </header>
  );
}

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return <p className="px-6 pt-3 text-xs text-[var(--red)]">Last poll failed: {error}</p>;
}
