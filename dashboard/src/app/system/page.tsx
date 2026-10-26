"use client";

import { ErrorNote, PageHeader, Panel } from "@/components/cockpit";
import { useApi } from "@/hooks/use-api";
import { fmtAgo } from "@/lib/time";
import type { DlqResponse, UnitsResponse } from "@/lib/types";

export default function SystemPage() {
  const units = useApi<UnitsResponse>("/api/system/units");
  const dlq = useApi<DlqResponse>("/api/system/dlq");

  const unitRows = (units.data?.rows ?? []).map((u) => ({
    unit: u.unit.replace(/^indicagent-/, "").replace(/\.service$/, ""),
    state: u.active,
    sub: u.sub,
    timer: u.timer ? "yes" : "",
    last_run: u.last_run ? fmtAgo(u.last_run) : "",
    next_run: u.next_run ? fmtAgo(u.next_run) : "",
  }));
  const failed = unitRows.filter((u) => u.state === "failed").length;

  return (
    <div>
      <PageHeader title="System">
        {units.data && (
          <>
            {unitRows.length} units · {failed} failed
          </>
        )}
      </PageHeader>
      <ErrorNote error={units.error} />
      <ErrorNote error={dlq.error} />

      <Panel
        className="px-6 py-4"
        title="Services and timers"
        question="A oneshot that is inactive between runs is normal; failed is the state to act on."
        rows={unitRows}
        source={units.data?.source ?? null}
        asOf={units.data?.as_of ?? null}
        highlight={(u) => u.state === "failed"}
        empty="No indicagent units."
      />

      <Panel
        className="px-6 py-4 border-t border-[var(--border-subtle)]"
        title="Dead letters"
        question={`Messages a service could not process, last ${dlq.data?.meta.window_days ?? "-"} days.`}
        rows={dlq.data?.rows ?? []}
        source={dlq.data?.source ?? null}
        asOf={dlq.data?.as_of ?? null}
        highlight={(r) => r.quarantined > 0}
        empty="No dead letters in the window."
      />
    </div>
  );
}
