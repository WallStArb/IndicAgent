"use client";

import type { SignalData } from "@/lib/types";
import { Grid, KV, Empty } from "../ui/primitives";
import { Tooltip } from "@/components/tooltip";
import { SignalDetailHeader } from "./signal-detail-header";
import { SignalDetailTargets } from "./signal-detail-targets";
import { SignalConfidencePipeline } from "./signal-confidence-pipeline";
import { fmtPrice, fmtPriceRange } from "@/lib/format";
import { ENTRY_TYPE_LABELS, STOP_TYPE_LABELS, abbreviatePlugin } from "@/lib/signal-utils";
import { barTimeTooltip, sigTimeTooltip, barClosePriceTooltip, marketPriceTooltip, ttsTooltip, entryTooltip, slTooltip, zoneTooltip } from "@/lib/signal-tooltips";

/**
 * Complete signal detail view.
 * Composes header, prices, targets, confidence pipeline, and metadata.
 */
export function SignalDetail({ signal }: { signal: SignalData }) {
  const isLong = signal.direction === "long";
  const dirColor = isLong ? "var(--green)" : "var(--red)";

  return (
    <div className="flex flex-col gap-2">
      <SignalDetailHeader signal={signal} dirColor={dirColor} />

      {/* Bar close + signal price context */}
      <Grid>
        {signal.bar_close_price != null && (
          <KV
            label="Bar close"
            tooltip={barClosePriceTooltip()}
            value={fmtPrice(signal.bar_close_price)}
          />
        )}
        {signal.market_price_at_signal != null && (
          <KV
            label="Signal price"
            tooltip={marketPriceTooltip()}
            value={fmtPrice(signal.market_price_at_signal)}
          />
        )}
      </Grid>

      {/* Entry target / Stop */}
      <Grid>
        <KV
          label="Entry target"
          value={`${fmtPrice(signal.entry_price)}${signal.entry_type ? ` (${ENTRY_TYPE_LABELS[signal.entry_type] ?? signal.entry_type})` : ""}`}
          tooltip={entryTooltip()}
        />
        <KV
          label="Stop"
          value={`${fmtPrice(signal.stop_loss)}${signal.stop_type ? ` (${STOP_TYPE_LABELS[signal.stop_type] ?? signal.stop_type})` : ""}`}
          tooltip={slTooltip()}
        />
      </Grid>

      {/* Entry Zone */}
      {signal.entry_zone_low != null && signal.entry_zone_high != null && (
        <Grid>
          <KV
            label="Wait → enter zone"
            tooltip={zoneTooltip()}
            value={fmtPriceRange(signal.entry_zone_low, signal.entry_zone_high)}
          />
          {signal.zone_valid_at_signal != null && (
            <KV
              label="In zone at signal"
              value={signal.zone_valid_at_signal ? "yes ✓" : "not yet"}
            />
          )}
        </Grid>
      )}

      {/* Targets */}
      <SignalDetailTargets signal={signal} />

      {/* Confidence pipeline */}
      <SignalConfidencePipeline signal={signal} />

      {/* Meta */}
      <Grid>
        <KV label="Regime" value={signal.regime_context} />
        <KV label="Plugin" value={abbreviatePlugin(signal.setup_plugin)} />
      </Grid>
    </div>
  );
}
