import { AlertTriangle, CircleCheck, Clock } from "lucide-react";
import { CARD, SMALL_LABEL } from "@/components/cockpit";
import { fmtAgo, fmtUtc } from "@/lib/time";
import type { PipelineSummary, Stage, StageName, StageStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

// Every figure here quotes a field of /api/pipeline/summary; nothing is re-judged in the browser
// (design decision 5). Status words come from the API's stage status.
const NEEDS_ACTION = new Set<StageStatus>(["failing", "error", "stale"]);

function rowsOf(stage: Stage | undefined): Record<string, unknown>[] {
  return stage?.rows ?? [];
}

/** The `field` figure of the row whose status is `status` (0 when the stage has no such row). */
function figure(stage: Stage | undefined, status: string, field: string): number {
  return Number(rowsOf(stage).find((r) => r.status === status)?.[field] ?? 0);
}

/**
 * Data flows one way, so the first stage in DAG order that needs action is the most upstream
 * problem. Names that stage, why, and the evidence; later stages that also need action are listed.
 */
function Bottleneck({
  summary,
  label,
}: {
  summary: PipelineSummary;
  label: (stage: StageName) => string;
}) {
  const index = summary.stages.findIndex((s) => NEEDS_ACTION.has(s.status));
  if (index < 0) {
    return (
      <a href="#stages" className={cn(CARD, "tile flex flex-col justify-center gap-2 md:row-span-2")}>
        <span className={SMALL_LABEL}>First stage to act on</span>
        <span className="flex items-center gap-3 text-2xl md:text-3xl font-semibold tracking-tight">
          <CircleCheck size={26} className="shrink-0 text-[var(--green)]" />
          Every stage is passing
        </span>
      </a>
    );
  }

  const stage = summary.stages[index];
  const name = label(stage.stage);
  const downstream = summary.stages
    .slice(index + 1)
    .filter((s) => NEEDS_ACTION.has(s.status))
    .map((s) => label(s.stage));
  const failingFeeds = rowsOf(stage).filter((r) => Number(r.failing ?? 0) > 0).length;

  let headline: string;
  let evidence: string;
  if (stage.status === "error") {
    headline = `${name} could not be read`;
    evidence = `The stage query failed (${stage.meta.error ?? "no detail"}); the other stages are unaffected.`;
  } else if (stage.meta.failing_rows) {
    headline = `${name} is ${stage.status}`;
    evidence =
      `${stage.meta.failing_rows.toLocaleString()} names have repeated fetch failures across ` +
      `${failingFeeds} of ${rowsOf(stage).length} feeds. Newest bar ${fmtAgo(stage.as_of)}.`;
  } else {
    headline = `${name} is ${stage.status}`;
    evidence = stage.as_of
      ? `Newest row ${fmtAgo(stage.as_of)}, past the ${summary.stale_hours} h window.`
      : (stage.meta.detail ?? "The stage has no rows yet.");
  }
  const tone = stage.status === "stale" ? "var(--amber)" : "var(--red)";

  return (
    <a
      href={`#stage-${stage.stage}`}
      className={cn(CARD, "tile relative flex flex-col justify-between gap-4 overflow-hidden md:row-span-2")}
      style={{ borderTop: `2px solid ${tone}` }}
    >
      <span className={SMALL_LABEL}>First stage to act on</span>
      <span className="flex flex-col gap-2">
        <span className="flex items-center gap-3 text-2xl md:text-3xl font-semibold tracking-tight">
          <AlertTriangle size={26} className="shrink-0 attention" style={{ color: tone }} />
          {headline}
        </span>
        <span className="max-w-[60ch] text-sm text-[var(--text-secondary)]">{evidence}</span>
      </span>
      <span className="text-xs text-[var(--text-muted)]">
        {downstream.length > 0
          ? `Also needs action downstream: ${downstream.join(", ")}.`
          : "Nothing downstream needs action."}
      </span>
    </a>
  );
}

function StatTile({
  label,
  value,
  context,
  source,
  href,
}: {
  label: string;
  value: string;
  context: string;
  source: string;
  href: string;
}) {
  return (
    <a href={href} className={cn(CARD, "tile flex flex-col gap-1.5 py-4")} title={`Source: ${source}`}>
      <span className={SMALL_LABEL}>{label}</span>
      <span className="text-[1.75rem] font-semibold leading-none tracking-tight">{value}</span>
      <span className="text-xs text-[var(--text-secondary)]">{context}</span>
    </a>
  );
}

/** The Pipeline page's opening row: where to act, and the four figures an operator checks first. */
export function Headline({
  summary,
  label,
}: {
  summary: PipelineSummary;
  label: (stage: StageName) => string;
}) {
  const byName = new Map(summary.stages.map((s) => [s.stage, s]));
  const ingest = byName.get("ingest");
  const measure = byName.get("measure");
  const research = byName.get("research");
  const feeds = rowsOf(ingest);
  const currentFeeds = feeds.filter((r) => r.status === "ok").length;
  const runs = rowsOf(research).reduce((sum, r) => sum + Number(r.runs ?? 0), 0);

  return (
    <section className="grid gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)]">
      <Bottleneck summary={summary} label={label} />
      <StatTile
        label="Newest bar"
        value={ingest?.as_of ? fmtAgo(ingest.as_of) : "none"}
        context={ingest?.as_of ? fmtUtc(ingest.as_of) : "No coverage rows yet"}
        source={ingest?.source ?? "ohlcv_coverage"}
        href="#stage-ingest"
      />
      <StatTile
        label="Feeds current"
        value={`${currentFeeds} of ${feeds.length}`}
        context={`${(ingest?.meta.failing_rows ?? 0).toLocaleString()} names failing fetch`}
        source={ingest?.source ?? "ohlcv_coverage"}
        href="#stage-ingest"
      />
      <StatTile
        label="Active concepts"
        value={figure(measure, "active", "count").toLocaleString()}
        context={`${figure(measure, "candidate", "count")} candidates, IC rows written ${measure?.meta.ic_rows ?? 0}`}
        source={measure?.source ?? "concept_registry"}
        href="#stage-measure"
      />
      <StatTile
        label="Research runs"
        value={runs.toLocaleString()}
        context={
          research?.as_of
            ? `${figure(research, "completed", "runs")} completed, newest ${fmtAgo(research.as_of)}`
            : "None recorded yet"
        }
        source={research?.source ?? "research_run"}
        href="#stage-research"
      />
    </section>
  );
}

/** The old dashboard's "last updated" stamp: when this payload was generated, in UTC. */
export function UpdatedStamp({ summary }: { summary: PipelineSummary }) {
  return (
    <span className="flex flex-col items-end gap-0.5" title={`Stale after ${summary.stale_hours} h`}>
      <span className={SMALL_LABEL}>Last updated</span>
      <span className="flex items-center gap-1.5 font-mono text-xs text-[var(--text-secondary)]">
        <Clock size={12} />
        {fmtUtc(summary.generated_at)}, every {summary.refresh_seconds} s
      </span>
    </span>
  );
}
