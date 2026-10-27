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

/** The small muted form of LABEL: column headers, tile and fact labels. */
export const SMALL_LABEL = cn(LABEL, "text-[0.6rem] font-semibold text-[var(--text-muted)]");

/** A floating hover card (chart crosshair, map cell). */
export const TOOLTIP =
  "pointer-events-none absolute z-10 rounded-lg border border-[var(--border-default)] bg-[var(--bg-elevated)] px-3 py-2 text-xs shadow-lg";

/** A section title with an optional muted count beside it. */
export function SectionTitle({ title, count }: { title: string; count?: number }) {
  return (
    <h2 className={cn(LABEL, "text-xs font-bold")}>
      {title}
      {count !== undefined && (
        <span className="ml-2 font-sans font-normal normal-case tracking-normal text-[var(--text-muted)]">
          {count.toLocaleString()}
        </span>
      )}
    </h2>
  );
}

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

/**
 * A compact table over API rows; columns default to the first row's keys. `maxHeight` scrolls
 * the rows inside their card under a header that stays in view.
 */
export function RowsTable<R extends object>({
  rows,
  columns,
  tone,
  render,
  labels,
  empty = "No rows.",
  maxHeight,
}: {
  rows: R[];
  columns?: (keyof R & string)[];
  tone?: (row: R) => RowTone;
  /**
   * Per-column cell renderers (a link, a state swatch). A rendered column owns its presentation:
   * the raw value's number alignment and state colour apply only to columns formatted by value.
   */
  render?: Partial<Record<keyof R & string, (row: R) => React.ReactNode>>;
  /** Header text per column where the key does not read as one (default: the key, spaced). */
  labels?: Partial<Record<keyof R & string, string>>;
  empty?: string;
  maxHeight?: string;
}) {
  if (rows.length === 0) {
    return <p className="text-xs text-[var(--text-muted)] py-2">{empty}</p>;
  }
  // Keys starting with "_" are hidden fields a page passes for `tone` (e.g. _failed).
  const cols =
    columns ?? (Object.keys(rows[0]).filter((k) => !k.startsWith("_")) as (keyof R & string)[]);
  const numeric = (c: keyof R & string, value: unknown) => !render?.[c] && typeof value === "number";
  return (
    <div className="overflow-auto min-h-0" style={{ maxHeight }}>
    <table className="w-full text-xs">
      <thead className="sticky top-0 bg-[var(--bg-surface)]">
        <tr className="text-left text-[var(--text-muted)]">
          {cols.map((c) => (
            <th
              key={c}
              className={cn(
                SMALL_LABEL,
                "py-1.5 pr-4 whitespace-nowrap",
                numeric(c, rows[0][c]) && "text-right",
              )}
            >
              {labels?.[c] ?? c.replaceAll("_", " ")}
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
                      numeric(c, value) && "text-right",
                      !render?.[c] && typeof value === "string" && VALUE_TONE[value],
                    )}
                  >
                    {render?.[c] ? render[c](row) : cell(value)}
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
 * `footer` renders below it; `scroll` caps the table's height and scrolls it inside the card.
 * `error` (the section's meta.error) replaces the body, so a failed query can never read as an
 * empty result.
 */
export function Panel<R extends object>({
  title,
  question,
  rows = [],
  error,
  source,
  asOf,
  aside,
  tone,
  empty,
  className,
  children,
  footer,
  scroll,
}: {
  title: string;
  question: string;
  rows?: R[];
  error?: string;
  source: string | null;
  asOf: string | null;
  aside?: React.ReactNode;
  tone?: (row: R) => RowTone;
  empty?: string;
  className?: string;
  children?: React.ReactNode;
  footer?: React.ReactNode;
  scroll?: string;
}) {
  return (
    <section className={cn("flex min-w-0 flex-col gap-2", className)}>
      <div className="flex items-center justify-between gap-2">
        <SectionTitle title={title} />
        {aside}
      </div>
      <p className="text-xs text-[var(--text-secondary)]">{question}</p>
      {error ? (
        <p className="text-xs text-[var(--red)] py-1">Query failed ({error}); the other sections are unaffected.</p>
      ) : (
        (children ?? <RowsTable rows={rows} tone={tone} empty={empty} maxHeight={scroll} />)
      )}
      {footer}
      <div className="mt-auto pt-1">
        <Lineage source={source} asOf={asOf} />
      </div>
    </section>
  );
}

/** A row of pressed/unpressed buttons choosing one value (a time range, a state filter). */
export function ToggleGroup<V>({
  label,
  options,
  selected,
  onSelect,
  children,
}: {
  label: string;
  options: { key: string; value: V; content: React.ReactNode }[];
  selected: V | null;
  onSelect: (value: V) => void;
  /** Trailing content after the buttons (a caption). */
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.key}
          type="button"
          aria-pressed={selected === o.value}
          onClick={() => onSelect(o.value)}
          className={cn(
            "flex items-center gap-2 rounded-md border px-2.5 py-1 text-xs transition-colors",
            selected === o.value
              ? "border-[var(--text-secondary)] bg-[var(--bg-elevated)] text-[var(--text-primary)]"
              : "border-[var(--border-subtle)] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]",
          )}
        >
          {o.content}
        </button>
      ))}
      {children}
    </div>
  );
}

export function PageHeader({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2 px-6 pt-5 pb-3 border-b border-[var(--border-subtle)]">
      <h1 className="font-display text-xl font-bold tracking-tight">{title}</h1>
      <div className="text-xs text-[var(--text-muted)]">{children}</div>
    </header>
  );
}

export function LoadingNote({ loading, children = "Loading..." }: { loading: boolean; children?: string }) {
  if (!loading) return null;
  return <p className="px-6 py-4 text-xs text-[var(--text-muted)]">{children}</p>;
}

export function ErrorNote({ error }: { error: string | null }) {
  if (!error) return null;
  return <p className="px-6 pt-3 text-xs text-[var(--red)]">Last poll failed: {error}</p>;
}
