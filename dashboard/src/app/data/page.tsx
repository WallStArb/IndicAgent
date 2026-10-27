"use client";

import { useState } from "react";
import { CARD, ErrorNote, PageHeader, Panel } from "@/components/cockpit";
import { useApi } from "@/hooks/use-api";
import { fmtAgo } from "@/lib/time";
import type { DataSummary } from "@/lib/types";

// The failing list runs to a few hundred names; show the worst first and the rest on request.
const FAILING_PREVIEW = 25;
const SCROLL = "520px";

const pct = (share: number) => `${(share * 100).toFixed(1)}%`;

/** A section whose query failed reports it beside its own card; the others still render. */
function SectionError({ error }: { error?: string }) {
  return error ? (
    <p className="text-xs text-[var(--red)] py-1">Query failed ({error}); the other sections are unaffected.</p>
  ) : null;
}

export default function DataPage() {
  const { data, error } = useApi<DataSummary>("/api/data/summary");
  const [showAllFailing, setShowAllFailing] = useState(false);

  // Ages instead of timestamps keep the feed columns inside the card. Status comes from the API.
  const feedRows = (data?.feeds.rows ?? []).map((f) => ({
    timeframe: f.timeframe,
    provider: f.provider,
    symbols: f.symbols,
    newest_bar: fmtAgo(f.newest_bar),
    last_fetch: fmtAgo(f.last_fetch),
    failing: f.failing,
    status: f.status,
  }));
  const integrityRows = (data?.integrity.rows ?? []).map((r) => ({
    monitor: r.monitor_type,
    check: r.metric_name,
    failed: `${r.failed.toLocaleString()} / ${r.evaluated.toLocaleString()}`,
    share: r.evaluated ? pct(r.failed / r.evaluated) : "-",
    run: fmtAgo(r.evaluated_at),
    _failed: r.failed,
  }));
  const failingAll = data?.failing.rows ?? [];
  const failingRows = (showAllFailing ? failingAll : failingAll.slice(0, FAILING_PREVIEW)).map((r) => ({
    symbol: r.symbol,
    timeframe: r.timeframe,
    provider: r.provider,
    failures: r.consecutive_failures,
    status: r.last_fetch_status ?? "-",
    last_fetch: fmtAgo(r.last_fetched_at),
  }));
  const restatementRows = (data?.restatements.rows ?? []).map((r) => ({
    symbol: r.symbol,
    timeframe: r.timeframe,
    vendor: r.vendor,
    kind: r.kind,
    changed: `${r.n_changed.toLocaleString()} / ${r.n_stored.toLocaleString()}`,
    share: pct(r.share),
    flagged: fmtAgo(r.flagged_at),
  }));

  return (
    <div>
      <PageHeader title="Data">
        {data && (
          <>
            {feedRows.length} feeds · {failingAll.length} failing names ·{" "}
            {integrityRows.filter((r) => r._failed > 0).length} checks failing
          </>
        )}
      </PageHeader>
      <ErrorNote error={error} />

      <div className="grid gap-4 p-6 grid-cols-[repeat(auto-fill,minmax(520px,1fr))]">
        <Panel
          className={CARD}
          title="Feeds"
          question="Bars held per timeframe and vendor, the newest one, and names failing to fetch."
          rows={feedRows}
          source={data?.feeds.source ?? null}
          asOf={data?.feeds.as_of ?? null}
          tone={(f) => (f.status === "ok" ? undefined : "bad")}
          empty="The coverage ledger has no rows yet."
          footer={<SectionError error={data?.feeds.meta.error} />}
        />

        <Panel
          className={CARD}
          title="Integrity"
          question="Each check's latest run: subjects that failed of those evaluated."
          rows={integrityRows}
          source={data?.integrity.source ?? null}
          asOf={data?.integrity.as_of ?? null}
          tone={(r) => (r._failed > 0 ? "bad" : "dim")}
          empty="No integrity check has run yet."
          scroll={SCROLL}
          footer={<SectionError error={data?.integrity.meta.error} />}
        />

        <Panel
          className={CARD}
          title="Failing names"
          question="Names whose last fetches failed, worst first."
          rows={failingRows}
          source={data?.failing.source ?? null}
          asOf={data?.failing.as_of ?? null}
          empty="No name is failing to fetch."
          scroll={SCROLL}
          footer={
            <>
              <SectionError error={data?.failing.meta.error} />
              {failingAll.length > FAILING_PREVIEW && (
                <button
                  type="button"
                  onClick={() => setShowAllFailing((v) => !v)}
                  className="self-start text-[0.65rem] font-mono text-[var(--accent-cyan)] hover:underline"
                >
                  {showAllFailing ? `show the worst ${FAILING_PREVIEW}` : `show all ${failingAll.length}`}
                </button>
              )}
            </>
          }
        />

        <Panel
          className={CARD}
          title="Restatements"
          question="Vendor restatements the raw capture flagged and nobody has reviewed yet."
          rows={restatementRows}
          source={data?.restatements.source ?? null}
          asOf={data?.restatements.as_of ?? null}
          empty="No unreviewed restatements."
          footer={<SectionError error={data?.restatements.meta.error} />}
        />

        <Panel
          className={CARD}
          title="Listing ends"
          question="Names whose listing ended, and why; their bars stay as history."
          rows={data?.listing_ends.rows ?? []}
          source={data?.listing_ends.source ?? null}
          asOf={data?.listing_ends.as_of ?? null}
          tone={() => "dim"}
          empty="No listing has ended."
          footer={<SectionError error={data?.listing_ends.meta.error} />}
        />

        <Panel
          className={CARD}
          title="Dividend coverage"
          question="Names with dividend history per source and the span it covers; outside it dividends are unknown, never zero."
          rows={data?.dividends.rows ?? []}
          source={data?.dividends.source ?? null}
          asOf={data?.dividends.as_of ?? null}
          empty="No dividend coverage recorded."
          footer={<SectionError error={data?.dividends.meta.error} />}
        />
      </div>
    </div>
  );
}
