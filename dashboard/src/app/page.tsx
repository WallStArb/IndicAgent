"use client";

import { ErrorNote, PageHeader, Panel, StatusChip } from "@/components/cockpit";
import { useApi } from "@/hooks/use-api";
import { fmtUtc } from "@/lib/time";
import type { PipelineSummary, Stage, StageName } from "@/lib/types";

const STAGE_LABEL: Record<StageName, string> = {
  ingest: "Ingest",
  feature: "Features",
  regime: "Regimes",
  measure: "Measure",
  research: "Research",
  book: "Books",
};

const STAGE_QUESTION: Record<StageName, string> = {
  ingest: "Vendor bars captured into the coverage ledger, per timeframe and provider",
  feature: "Newest bar in the feature store and in the rebuild target",
  regime: "Newest regime label",
  measure: "Concept lifecycle and the fresh IC writer",
  research: "Runs recorded in the research ledger",
  book: "Frozen books running forward",
};

function StageCard({ stage }: { stage: Stage }) {
  const failing = stage.meta.failing_rows ?? 0;
  return (
    <Panel
      className="rounded border border-[var(--border-default)] bg-[var(--bg-surface)] p-4"
      title={STAGE_LABEL[stage.stage]}
      question={STAGE_QUESTION[stage.stage]}
      rows={stage.rows}
      source={stage.source}
      asOf={stage.as_of}
      highlight={(row) => Number(row.failing ?? 0) > 0}
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
        {stage.meta.error && (
          <p className="text-xs text-[var(--red)] py-2">Query failed ({stage.meta.error}); the other stages are unaffected.</p>
        )}
        {stage.meta.ic_rows !== undefined && (
          <p className="text-[0.65rem] font-mono text-[var(--text-muted)] pt-1">IC rows written: {stage.meta.ic_rows}</p>
        )}
        </>
      }
    />
  );
}

export default function PipelinePage() {
  const { data, error, loading } = useApi<PipelineSummary>("/api/pipeline/summary");

  return (
    <div>
      <PageHeader title="Pipeline">
        {data && (
          <>
            generated {fmtUtc(data.generated_at)} · stale after {data.stale_hours} h · refresh{" "}
            {data.refresh_seconds} s
          </>
        )}
      </PageHeader>
      <ErrorNote error={error} />
      {loading && <p className="px-6 py-4 text-xs text-[var(--text-muted)]">Loading...</p>}
      {data && (
        <div className="p-6 grid gap-4 grid-cols-[repeat(auto-fill,minmax(420px,1fr))]">
          {data.stages.map((stage) => (
            <StageCard key={stage.stage} stage={stage} />
          ))}
        </div>
      )}
    </div>
  );
}
