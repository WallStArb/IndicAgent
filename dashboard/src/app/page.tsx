"use client";

import { ChevronRight } from "lucide-react";
import { CARD, ErrorNote, LoadingNote, PageHeader, Panel, StatusChip } from "@/components/cockpit";
import { Headline, STAGE_LABEL, UpdatedStamp } from "@/components/headline";
import { useApi } from "@/hooks/use-api";
import { fmtAgo } from "@/lib/time";
import type { PipelineSummary, Stage, StageName, StageStatus } from "@/lib/types";
import { cn, spaced } from "@/lib/utils";

const STAGE_QUESTION: Record<StageName, string> = {
  ingest: "Vendor bars captured into the coverage ledger, per timeframe and provider",
  feature: "Newest bar in the feature store and in the rebuild target",
  regime: "Newest regime label",
  measure: "Concept lifecycle and the fresh IC writer",
  research: "Runs recorded in the research ledger",
  book: "Frozen books running forward",
};

const STATUS_DOT: Record<StageStatus, string> = {
  ok: "bg-[var(--green)]",
  stale: "bg-[var(--amber)]",
  failing: "bg-[var(--red)]",
  error: "bg-[var(--red)]",
  empty: "bg-[var(--text-secondary)]",
  not_built: "border border-dashed border-[var(--text-muted)]",
};

/** The DAG in one line: each stage's status and newest row, linking to its card below. */
function StageFlow({ stages }: { stages: Stage[] }) {
  return (
    <nav className={cn(CARD, "flex items-center gap-1 overflow-x-auto py-3")}>
      {stages.map((stage, i) => (
        <div key={stage.stage} className="flex items-center gap-1">
          {i > 0 && <ChevronRight size={14} className="shrink-0 text-[var(--text-muted)]" />}
          <a
            href={`#stage-${stage.stage}`}
            className="flex items-center gap-2 rounded-lg px-3 py-1.5 hover:bg-[var(--bg-hover)]"
          >
            <span className="font-display text-[0.6rem] font-bold text-[var(--accent-cyan)]">
              {String(i + 1).padStart(2, "0")}
            </span>
            <span className={cn("size-2 shrink-0 rounded-full", STATUS_DOT[stage.status])} />
            <span className="text-sm">{STAGE_LABEL[stage.stage]}</span>
            <span className="font-mono text-[0.65rem] text-[var(--text-muted)]">
              {stage.as_of ? fmtAgo(stage.as_of) : spaced(stage.status)}
            </span>
          </a>
        </div>
      ))}
    </nav>
  );
}

function StageCard({ stage }: { stage: Stage }) {
  const failing = stage.meta.failing_rows ?? 0;
  return (
    // Ingest carries the widest table (one row per feed), so it takes the full row.
    <div
      id={`stage-${stage.stage}`}
      className={cn("flex min-w-0 scroll-mt-6", stage.stage === "ingest" && "col-span-full")}
    >
    <Panel
      className={cn(CARD, "flex-1")}
      title={STAGE_LABEL[stage.stage]}
      question={STAGE_QUESTION[stage.stage]}
      rows={stage.rows}
      error={stage.meta.error}
      source={stage.source}
      asOf={stage.as_of}
      tone={(row) => (Number(row.failing ?? 0) > 0 ? "bad" : undefined)}
      empty="The table has no rows yet."
      aside={
        <span className="flex items-center gap-2">
          {failing > 0 && (
            <span className="text-[0.65rem] font-mono text-[var(--red)]">{failing} failing</span>
          )}
          <StatusChip status={stage.status} />
        </span>
      }
      footer={
        <>
        {stage.meta.detail && <p className="text-xs text-[var(--text-muted)] py-2">{stage.meta.detail}</p>}
        {stage.meta.ic_rows !== undefined && (
          <p className="text-[0.65rem] font-mono text-[var(--text-muted)] pt-1">IC rows written: {stage.meta.ic_rows}</p>
        )}
        </>
      }
    />
    </div>
  );
}

export default function PipelinePage() {
  const { data, error, loading } = useApi<PipelineSummary>("/api/pipeline/summary");

  return (
    <div>
      <PageHeader title="Pipeline">{data && <UpdatedStamp summary={data} />}</PageHeader>
      <ErrorNote error={error} />
      <LoadingNote loading={loading} />
      {data && (
        <div className="p-6 flex flex-col gap-4">
          <Headline summary={data} />
          <StageFlow stages={data.stages} />
          <div id="stages" className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(min(420px,100%),1fr))]">
            {data.stages.map((stage) => (
              <StageCard key={stage.stage} stage={stage} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
