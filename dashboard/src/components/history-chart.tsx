"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { TOOLTIP, ToggleGroup } from "@/components/cockpit";
import { dayLabel, toDay } from "@/lib/time";
import type { CloseSeries, LaneRow } from "@/lib/types";
import { cn } from "@/lib/utils";

const DAY_MS = 86_400_000;

// Layout, in px.
const CLOSE_H = 120;
const CLOSE_PAD = 6;
const LANE_H = 16;
const LANE_GAP = 6;
const AXIS_H = 18;
const LABEL_Y_TOP = 14;
const LABEL_Y_HIGH = 30;
const MIN_WIDTH = 200;
const INITIAL_WIDTH = 900;
/** The narrowest a bin may draw; the bin's span in days follows from the width. */
const MIN_BIN_PX = 3;
/** The lane label gutter; narrower on a phone. */
const labelWidth = (width: number) => (width < 520 ? 72 : 92);
/** A bin holding any bars is at least this opaque, so a thin partial session never reads as a
 *  hole (2.3:1 against the empty track; the dataviz validator's ordinal floor is 2:1). */
const MIN_OPACITY = 0.35;
/** The close panel switches to a log scale when the window's high exceeds its low this many times. */
const LOG_ABOVE = 4;
const MAX_TICKS = 8;

const RANGES: { label: string; days: number | null }[] = [
  { label: "All", days: null },
  { label: "5y", days: 5 * 365 },
  { label: "1y", days: 365 },
  { label: "3m", days: 91 },
];

const isWeekday = (day: number) => {
  const dow = new Date(day * DAY_MS).getUTCDay();
  return dow !== 0 && dow !== 6;
};
const UNIT_MINUTES: Record<string, number> = { m: 1, h: 60, d: 1440, w: 10080 };
const minutes = (tf: string) => parseInt(tf, 10) * (UNIT_MINUTES[tf.slice(-1)] ?? 1);

interface Lane {
  key: string;
  label: string;
  first: number;
  byDay: Map<number, number>;
  /** Median bars per session with data: a full session for this lane. */
  full: number;
}

interface LaneBin {
  sessions: number;
  bars: number;
  /** Full-session equivalents per weekday, in [0, 1]. */
  fill: number;
}

interface Bin {
  start: number;
  end: number;
  weekdays: number;
  lanes: LaneBin[];
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted.length ? sorted[Math.floor(sorted.length / 2)] : 1;
}

/** Coarse to fine (1d beside the close line first), then vendor. Sessions arrive sorted. */
function buildLanes(rows: LaneRow[]): Lane[] {
  return [...rows]
    .filter((r) => r.sessions.length)
    .sort((a, b) => minutes(b.timeframe) - minutes(a.timeframe) || a.vendor.localeCompare(b.vendor))
    .map((r) => ({
      key: `${r.timeframe}:${r.vendor}`,
      label: `${r.timeframe} ${r.vendor}`,
      first: toDay(r.sessions[0]),
      byDay: new Map(r.sessions.map((s, i) => [toDay(s), r.bars[i]])),
      full: median(r.bars),
    }));
}

function laneBin(lane: Lane, start: number, end: number, weekdays: number): LaneBin {
  let sessions = 0;
  let bars = 0;
  let full = 0;
  for (let d = start; d < end; d++) {
    const n = lane.byDay.get(d);
    if (n === undefined) continue;
    sessions++;
    bars += n;
    full += Math.min(n / lane.full, 1);
  }
  // A bin of weekend days only has no weekday to measure against: any session there is full.
  const fill = weekdays === 0 ? Math.min(sessions, 1) : Math.min(full / weekdays, 1);
  return { sessions, bars, fill };
}

function buildBins(lanes: Lane[], from: number, to: number, binDays: number): Bin[] {
  const bins: Bin[] = [];
  for (let start = from; start <= to; start += binDays) {
    const end = Math.min(start + binDays, to + 1);
    let weekdays = 0;
    for (let d = start; d < end; d++) if (isWeekday(d)) weekdays++;
    bins.push({ start, end, weekdays, lanes: lanes.map((lane) => laneBin(lane, start, end, weekdays)) });
  }
  return bins;
}

/** First-of-month ticks, stepped so at most MAX_TICKS show; a multi-year window steps by years. */
function ticks(from: number, to: number): { day: number; label: string }[] {
  const months = (to - from) / 30.44;
  const unit = months > 24 ? 12 : 1;
  const step = Math.max(1, Math.ceil(months / unit / MAX_TICKS)) * unit;
  const start = new Date(from * DAY_MS);
  // A yearly step starts at the next January so its labels are whole years.
  const firstMonth = unit === 12 ? 12 : start.getUTCMonth() + 1;
  const out: { day: number; label: string }[] = [];
  for (let m = firstMonth; ; m += step) {
    const day = Date.UTC(start.getUTCFullYear(), m, 1) / DAY_MS;
    if (day > to) break;
    const d = new Date(day * DAY_MS);
    const label =
      unit === 12
        ? String(d.getUTCFullYear())
        : d.toLocaleString("en", { month: "short", year: "2-digit", timeZone: "UTC" });
    out.push({ day, label });
  }
  return out;
}

function RangePicker({
  range,
  onRange,
  caption,
}: {
  range: number | null;
  onRange: (days: number | null) => void;
  caption: string;
}) {
  return (
    <ToggleGroup
      label="Time range"
      options={RANGES.map((r) => ({ key: r.label, value: r.days, content: <span className="font-mono">{r.label}</span> }))}
      selected={range}
      onSelect={onRange}
    >
      <span className="ml-auto font-mono text-[0.65rem] text-[var(--text-muted)]">{caption}</span>
    </ToggleGroup>
  );
}

function BinTooltip({
  bin,
  binDays,
  lanes,
  close,
  style,
}: {
  bin: Bin;
  binDays: number;
  lanes: Lane[];
  close: number | null;
  style: React.CSSProperties;
}) {
  return (
    <div className={cn(TOOLTIP, "top-0")} style={style}>
      <div className="font-mono text-[var(--text-secondary)]">
        {binDays === 1 ? dayLabel(bin.start) : `${dayLabel(bin.start)} to ${dayLabel(bin.end - 1)}`}
      </div>
      {close !== null && (
        <div className="mt-1">
          close <span className="font-mono">{close.toFixed(2)}</span>
        </div>
      )}
      <table className="mt-1 font-mono">
        <tbody>
          {lanes.map((lane, li) => (
            <tr key={lane.key}>
              <td className="pr-3 text-[var(--text-secondary)]">{lane.label}</td>
              <td className="pr-3 text-right">
                {bin.lanes[li].sessions}/{bin.weekdays} sessions
              </td>
              <td className="text-right">{bin.lanes[li].bars.toLocaleString()} bars</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * One name's history on one time axis: the daily close on top, then one lane per (timeframe,
 * vendor) whose bins fill by how much of each weekday's normal session the lane holds (a hole is
 * an empty track, a partial session a paler bin). The vendor handoffs and gaps the coverage
 * ledger's earliest/latest cannot show are visible here. Hover, or focus and use the arrow keys,
 * for the exact counts under the crosshair.
 */
export function HistoryChart({
  lanes: laneRows,
  closes,
  closeTimeframe,
  listingEnded,
}: {
  lanes: LaneRow[];
  closes: CloseSeries | undefined;
  closeTimeframe: string;
  listingEnded: string | null;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(INITIAL_WIDTH);
  const [range, setRange] = useState<number | null>(null);
  /** The start day of the bin under the crosshair; snapped, so moves inside a bin do not re-render. */
  const [cursor, setCursor] = useState<number | null>(null);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(MIN_WIDTH, entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const lanes = useMemo(() => buildLanes(laneRows), [laneRows]);
  const points = useMemo(
    () => (closes ? closes.t.map((t, i) => [toDay(t), closes.close[i]] as const) : []),
    [closes],
  );

  const to = Math.floor(Date.now() / DAY_MS);
  const earliest = Math.min(to, ...lanes.map((l) => l.first), points.length ? points[0][0] : to);
  const from = range === null ? earliest : Math.max(earliest, to - range);
  const labelW = labelWidth(width);
  const plotW = width - labelW;
  const span = to - from + 1;
  const binDays = Math.max(1, Math.ceil((span * MIN_BIN_PX) / plotW));
  const x = useCallback((day: number) => labelW + ((day - from) / span) * plotW, [labelW, from, span, plotW]);

  const bins = useMemo(() => buildBins(lanes, from, to, binDays), [lanes, from, to, binDays]);

  // The close line over the window on its own min-max scale; logarithmic once the window spans
  // more than LOG_ABOVE times its low, where a linear scale would flatten the early years.
  const close = useMemo(() => {
    const visible = points.filter(([d]) => d >= from);
    let lo = Infinity;
    let hi = -Infinity;
    for (const [, c] of visible) {
      lo = Math.min(lo, c);
      hi = Math.max(hi, c);
    }
    const log = lo > 0 && hi / lo > LOG_ABOVE;
    const scale = (c: number) => (log ? Math.log(c) : c);
    const y = (c: number) =>
      CLOSE_PAD + (1 - (scale(c) - scale(lo)) / (scale(hi) - scale(lo) || 1)) * (CLOSE_H - 2 * CLOSE_PAD);
    const path = visible.map(([d, c], i) => `${i ? "L" : "M"}${x(d).toFixed(1)},${y(c).toFixed(1)}`).join("");
    return { visible, lo, hi, log, path };
  }, [points, from, x]);

  const lanesTop = CLOSE_H + LANE_GAP;
  const height = lanesTop + lanes.length * (LANE_H + LANE_GAP) + AXIS_H;
  const bin = cursor === null ? null : (bins.find((b) => b.start === cursor) ?? null);
  const cursorClose = bin ? (close.visible.findLast(([d]) => d < bin.end)?.[1] ?? null) : null;
  const ended = listingEnded ? toDay(listingEnded) : null;

  const binStart = (day: number) => from + Math.floor((day - from) / binDays) * binDays;

  function onMove(clientX: number) {
    const px = clientX - box.current!.getBoundingClientRect().left - labelW;
    setCursor(px < 0 ? null : binStart(Math.min(to, from + Math.floor((px / plotW) * span))));
  }

  function onKey(e: React.KeyboardEvent) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const step = e.key === "ArrowLeft" ? -binDays : binDays;
    setCursor((c) => binStart(Math.min(to, Math.max(from, (c ?? binStart(to)) + step))));
  }

  // Everything but the crosshair: hovering re-renders only the cursor line and its tooltip, not
  // the lanes x bins rects (about 2,000 for a long-lived name at "All").
  const layer = useMemo(
    () => (
      <>
      <text x={0} y={LABEL_Y_TOP} className="fill-[var(--text-muted)] text-[10px]">
        {closeTimeframe} close{close.log && ", log"}
      </text>
      {close.visible.length > 1 && (
        <>
          <text x={0} y={LABEL_Y_HIGH} className="fill-[var(--text-secondary)] font-mono text-[10px]">
            {close.hi.toFixed(2)}
          </text>
          <text x={0} y={CLOSE_H - 4} className="fill-[var(--text-secondary)] font-mono text-[10px]">
            {close.lo.toFixed(2)}
          </text>
          <path d={close.path} fill="none" stroke="var(--text-primary)" strokeWidth={1.25} strokeLinejoin="round" />
        </>
      )}

      {lanes.map((lane, li) => {
        const top = lanesTop + li * (LANE_H + LANE_GAP);
        return (
          <g key={lane.key}>
            <text x={0} y={top + LANE_H - 4} className="fill-[var(--text-secondary)] font-mono text-[10px]">
              {lane.label}
            </text>
            <rect x={labelW} y={top} width={plotW} height={LANE_H} rx={2} fill="var(--bg-elevated)" />
            {bins.map((b) =>
              b.lanes[li].sessions ? (
                <rect
                  key={b.start}
                  x={x(b.start)}
                  y={top}
                  // Day bins keep a 1px gap so single sessions read apart; wider bins run continuous.
                  width={Math.max(1, x(b.end) - x(b.start) - (binDays === 1 ? 1 : 0))}
                  height={LANE_H}
                  fill="var(--accent-cyan)"
                  opacity={MIN_OPACITY + (1 - MIN_OPACITY) * b.lanes[li].fill}
                />
              ) : null,
            )}
          </g>
        );
      })}

      {ticks(from, to).map((t) => (
        <g key={t.day}>
          <line x1={x(t.day)} x2={x(t.day)} y1={height - AXIS_H} y2={height - AXIS_H + 4} stroke="var(--text-muted)" />
          <text x={x(t.day) + 3} y={height - 4} className="fill-[var(--text-muted)] font-mono text-[10px]">
            {t.label}
          </text>
        </g>
      ))}

      {ended !== null && ended >= from && (
        <g>
          <line x1={x(ended)} x2={x(ended)} y1={0} y2={height - AXIS_H} stroke="var(--text-secondary)" strokeDasharray="3 3" />
          <text x={x(ended) - 4} y={10} textAnchor="end" className="fill-[var(--text-secondary)] text-[10px]">
            listing ended
          </text>
        </g>
      )}
      </>
    ),
    [close, lanes, bins, x, labelW, plotW, binDays, from, to, height, ended, closeTimeframe],
  );

  const caption = `${dayLabel(from)} to ${dayLabel(to)}, ${binDays === 1 ? "one day" : `${binDays} days`} per bin`;

  return (
    <div className="flex flex-col gap-3">
      <RangePicker range={range} onRange={setRange} caption={caption} />
      <div
        ref={box}
        className="relative outline-none"
        tabIndex={0}
        role="img"
        aria-label={`${closeTimeframe} close and bars held per session for each timeframe and vendor`}
        onMouseMove={(e) => onMove(e.clientX)}
        onMouseLeave={() => setCursor(null)}
        onKeyDown={onKey}
        onBlur={() => setCursor(null)}
      >
        <svg width={width} height={height} className="block">
          {layer}
          {bin && <line x1={x(bin.start)} x2={x(bin.start)} y1={0} y2={height - AXIS_H} stroke="var(--text-secondary)" />}
        </svg>

        {bin && (
          <BinTooltip
            bin={bin}
            binDays={binDays}
            lanes={lanes}
            close={cursorClose}
            style={x(bin.start) > width / 2 ? { right: width - x(bin.start) + 8 } : { left: x(bin.start) + 8 }}
          />
        )}
      </div>
    </div>
  );
}
