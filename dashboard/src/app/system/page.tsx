"use client";

import { CARD, ErrorNote, PageHeader, Panel } from "@/components/cockpit";
import { useApi } from "@/hooks/use-api";
import { fmtAgo } from "@/lib/time";
import type { DlqResponse, UnitsResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function SystemPage() {
  const units = useApi<UnitsResponse>("/api/system/units");
  const dlq = useApi<DlqResponse>("/api/system/dlq");

  // Failed units first, then running ones; idle oneshots and timers are normal and sort last.
  const rank = (u: { active: string }) => (u.active === "failed" ? 0 : u.active === "active" ? 1 : 2);
  const unitRows = [...(units.data?.rows ?? [])].sort((a, b) => rank(a) - rank(b)).map((u) => ({
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
        className={cn(CARD, "mx-6 mt-6")}
        title="Services and timers"
        question="A oneshot that is inactive between runs is normal; failed is the state to act on."
        rows={unitRows}
        source={units.data?.source ?? null}
        asOf={units.data?.as_of ?? null}
        tone={(u) => (u.state === "failed" ? "bad" : u.state === "inactive" ? "dim" : undefined)}
        empty="No indicagent units."
      />

      <Panel
        className={cn(CARD, "mx-6 my-4")}
        title="Dead letters"
        question={`Messages a service could not process, last ${dlq.data?.meta.window_days ?? "-"} days.`}
        rows={dlq.data?.rows ?? []}
        source={dlq.data?.source ?? null}
        asOf={dlq.data?.as_of ?? null}
        tone={(r) => (r.quarantined > 0 ? "bad" : undefined)}
        empty="No dead letters in the window."
      />
    </div>
  );
}
