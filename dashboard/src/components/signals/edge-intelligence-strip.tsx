"use client";

import { SetupRegimeHeatMap } from "./setup-regime-heatmap";
import { EdgeSparkline } from "./edge-sparkline";
import { IntradayHeatMap } from "./intraday-heatmap";

export function EdgeIntelligenceStrip({
  onHeatMapCellClick,
}: {
  onHeatMapCellClick?: (setup: string, regime: number) => void;
}) {
  return (
    <div className="grid gap-3" style={{ gridTemplateColumns: "1fr 1fr" }}>
      <SetupRegimeHeatMap onCellClick={onHeatMapCellClick} />
      <div className="flex flex-col gap-3">
        <EdgeSparkline />
        <IntradayHeatMap />
      </div>
    </div>
  );
}
