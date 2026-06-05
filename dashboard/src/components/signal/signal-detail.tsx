"use client";

import type { SignalData } from "@/lib/types";
import { SignalDetailHeader } from "./signal-detail-header";
import { SignalConfidencePipeline } from "./signal-confidence-pipeline";
import { SignalTradeCard } from "./signal-trade-card";
import { SignalSwarmBreakdown } from "./signal-swarm-breakdown";

export function SignalDetail({ signal }: { signal: SignalData }) {
  const isLong = signal.direction === "long";
  const dirColor = isLong ? "var(--green)" : "var(--red)";

  return (
    <div className="flex flex-col gap-3">
      <SignalDetailHeader signal={signal} dirColor={dirColor} />
      <SignalConfidencePipeline signal={signal} />
      <div className="border-t border-[var(--border-subtle)]" />
      <SignalTradeCard signal={signal} />
      {signal.signal_id && (
        <div className="border-t border-[var(--border-subtle)] pt-2">
          <SignalSwarmBreakdown signalId={signal.signal_id} />
        </div>
      )}
    </div>
  );
}
