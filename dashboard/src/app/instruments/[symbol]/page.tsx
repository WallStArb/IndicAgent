"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ChevronLeft } from "lucide-react";
import { CARD, ErrorNote, LoadingNote, Panel, SMALL_LABEL } from "@/components/cockpit";
import { HistoryChart } from "@/components/history-chart";
import { useApi } from "@/hooks/use-api";
import type { IdentityRow, Passport } from "@/lib/types";
import { cn, spaced } from "@/lib/utils";

function Fact({ label, children, dim }: { label: string; children: React.ReactNode; dim?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className={SMALL_LABEL}>{label}</dt>
      <dd className={cn("text-sm", dim && "text-[var(--text-secondary)]")}>{children}</dd>
    </div>
  );
}

/** A yes/no gate; "no" reads dimmer so the gates a name has not passed stand back. */
function Flag({ label, on }: { label: string; on: boolean }) {
  return (
    <Fact label={label} dim={!on}>
      {on ? "yes" : "no"}
    </Fact>
  );
}

function Title({ symbol, name }: { symbol: string; name?: string | null }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
      <h1 className="font-display text-3xl font-extrabold tracking-tight">{symbol}</h1>
      {name && <span className="text-lg text-[var(--text-secondary)]">{name}</span>}
    </div>
  );
}

function Identity({ id }: { id: IdentityRow }) {
  const path = [id.level_1, id.level_2, id.level_3, id.level_4].filter(Boolean);
  return (
    <>
      <p className="text-xs text-[var(--text-secondary)]">
        {path.length ? path.join(" / ") : "No current classification"}
      </p>
      {id.listing_ended && (
        <p className="w-fit rounded-lg border border-[var(--border-bright)] px-3 py-1.5 text-xs">
          Listing ended {id.listing_ended} ({id.listing_end_reason && spaced(id.listing_end_reason)}). Its bars stay as
          history.
        </p>
      )}
      <dl className="flex flex-wrap gap-x-8 gap-y-3">
        <Flag label="Active" on={id.is_active} />
        <Flag label="Intraday compute" on={id.compute_eligible} />
        <Flag label="Daily compute" on={id.compute_eligible_1d} />
        <Flag label="Tradeable" on={id.live_tradeable} />
        <Fact label="Exchange">{id.exchange ?? "-"}</Fact>
      </dl>
    </>
  );
}

export default function PassportPage() {
  const { symbol } = useParams<{ symbol: string }>();
  const { data, error, loading } = useApi<Passport>(`/api/universe/${encodeURIComponent(symbol)}`, "passport");
  const id = data?.identity.rows[0];

  return (
    <div>
      <header className="flex flex-col gap-4 border-b border-[var(--border-subtle)] px-6 pt-5 pb-5">
        <Link
          href="/instruments"
          className="flex w-fit items-center gap-1 text-xs text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
        >
          <ChevronLeft size={14} /> Instruments
        </Link>
        <Title symbol={id?.symbol ?? decodeURIComponent(symbol)} name={id?.name} />
        {id && <Identity id={id} />}
        {data?.identity.meta.error && (
          <p className="text-xs text-[var(--red)]">
            The identity query failed ({data.identity.meta.error}): eligibility, classification and any listing end are
            unknown. The sections below are unaffected.
          </p>
        )}
      </header>
      <ErrorNote error={error} />
      <LoadingNote loading={loading}>Loading the full history...</LoadingNote>
      {data && (
        <div className="flex flex-col gap-4 p-6">
          <Panel
            className={cn(CARD, "min-w-0")}
            title="History"
            question="The daily close, and the bars each timeframe and vendor holds per session. A gap is an empty track; a pale bin holds partial sessions."
            error={data.lanes.meta.error ?? data.closes.meta.error}
            source={data.lanes.source}
            asOf={data.lanes.as_of}
          >
            <HistoryChart
              lanes={data.lanes.rows}
              closes={data.closes.rows[0]}
              closeTimeframe={data.closes.meta.timeframe}
              listingEnded={id?.listing_ended ?? null}
            />
          </Panel>

          <div className="grid gap-4 grid-cols-[repeat(auto-fill,minmax(min(460px,100%),1fr))]">
            <Panel
              className={cn(CARD, "col-span-full")}
              title="Coverage ledger"
              question="What the fetcher recorded per feed: the span held, the last ask and its failures."
              rows={data.coverage.rows}
              error={data.coverage.meta.error}
              source={data.coverage.source}
              asOf={data.coverage.as_of}
              tone={(r) => (Number(r.failures ?? 0) > 0 ? "bad" : undefined)}
              empty="The fetcher has no coverage row for this name."
            />
            <Panel
              className={CARD}
              title="Restatements"
              question="Vendor re-serves that changed stored bars, flagged by the raw capture."
              rows={data.restatements.rows}
              error={data.restatements.meta.error}
              source={data.restatements.source}
              asOf={data.restatements.as_of}
              tone={(r) => (r.reviewed_at ? "dim" : undefined)}
              empty="No vendor has restated this name's bars."
            />
            <Panel
              className={CARD}
              title="Tags"
              question="Current instrument tags: what it is (human) and how it behaves (measured)."
              rows={data.tags.rows}
              error={data.tags.meta.error}
              source={data.tags.source}
              asOf={data.tags.as_of}
              empty="No current tags."
            />
          </div>
        </div>
      )}
    </div>
  );
}
